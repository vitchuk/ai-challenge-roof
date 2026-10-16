from __future__ import annotations

import base64
import json
import re
from pathlib import Path

from . import config, rag, repo_service, state
from .mcp_client import StdioMCPClient, result_is_error, result_text

_DOWNLOAD_PREFIX_RE = re.compile(
    r"^\s*successfully downloaded .*?\(SHA: [0-9a-f]+\)\s*\n?", re.IGNORECASE
)


def _strip_prefix(text: str) -> str:
    return _DOWNLOAD_PREFIX_RE.sub("", text, count=1)


def _decode_content(data: dict) -> str | None:
    content = data.get("content")
    if not isinstance(content, str):
        return None
    if data.get("encoding") == "base64":
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return ""
    return content


def _parse_file(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    if stripped[0] in "[{":
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return _strip_prefix(text)
        if isinstance(data, dict):
            decoded = _decode_content(data)
            if decoded is not None:
                return _strip_prefix(decoded)
            for key in ("text", "body", "value", "data"):
                if isinstance(data.get(key), str):
                    return _strip_prefix(data[key])
        if isinstance(data, list) and data and all(isinstance(item, str) for item in data):
            return _strip_prefix("\n".join(data))
    return _strip_prefix(text)


def _list_markdown(text: str, extension: str) -> list[str]:
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return []
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return []
    entries: list = []
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        for key in ("entries", "files", "items", "content", "tree"):
            value = data.get(key)
            if isinstance(value, list):
                entries = value
                break
    paths: list[str] = []
    for item in entries:
        if isinstance(item, str):
            if item.lower().endswith(extension.lower()):
                paths.append(item)
            continue
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        path = item.get("path") or item.get("name")
        if item_type not in (None, "file", "file_content"):
            continue
        if isinstance(path, str) and path.lower().endswith(extension.lower()):
            paths.append(path)
    return paths


def _title(path: str, text: str) -> str:
    match = rag.HEADING_RE.search(text)
    if match:
        return match.group(1).strip()
    return Path(path).stem


def _document(path: str, text: str) -> dict:
    return {"path": path, "title": _title(path, text), "text": text}


def _is_error(result) -> bool:
    return result_is_error(result)


async def _read(mcp: StdioMCPClient, owner: str, repo: str, path: str, branch: str) -> str:
    result = await mcp.call_tool(
        "get_file_contents",
        {"owner": owner, "repo": repo, "path": path, "ref": f"refs/heads/{branch}"},
    )
    if _is_error(result):
        raise RuntimeError(f"GitHub MCP вернул ошибку для {path}: {result_text(result)[:300]}")
    return result_text(result)


async def fetch_documents(mcp: StdioMCPClient) -> list[dict]:
    cfg = config.load_config()["github"]
    owner, repo = cfg["owner"], cfg["repo"]
    branch = await repo_service.get_current_branch(mcp)

    documents: list[dict] = []
    for path in cfg["root_files"]:
        text = _parse_file(await _read(mcp, owner, repo, path, branch))
        documents.append(_document(path, text))

    docs_dir = cfg["docs_dir"]
    listing = await _read(mcp, owner, repo, docs_dir, branch)
    doc_paths = _list_markdown(listing, cfg["docs_ext"][0])
    if not doc_paths:
        doc_paths = [f"{docs_dir}/{name}" for name in cfg.get("fallback_docs", [])]
    for path in doc_paths:
        text = _parse_file(await _read(mcp, owner, repo, path, branch))
        documents.append(_document(path, text))

    return [doc for doc in documents if doc["text"].strip()]


async def build(mcp: StdioMCPClient) -> dict:
    state.BUILD.update(status="building", error=None)
    try:
        documents = await fetch_documents(mcp)
        index = await rag.build_index(documents)
        state.BUILD.update(
            status="ready",
            error=None,
            chunks=len(index["chunks"]),
            files=len(documents),
            built_at=index["built_at"],
        )
        return {
            "chunks": len(index["chunks"]),
            "files": len(documents),
            "built_at": index["built_at"],
        }
    except Exception as exc:  # noqa: BLE001
        state.BUILD.update(status="error", error=str(exc))
        raise
