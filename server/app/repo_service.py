from __future__ import annotations

import json
import re
import time
from typing import Any

from . import config
from .mcp_client import StdioMCPClient, result_text

_CACHE: dict[str, tuple[float, Any]] = {}
_LABEL_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _ttl() -> float:
    return float(config.load_config()["repo"]["cache_ttl_sec"])


def _cache_get(key: str) -> Any | None:
    item = _CACHE.get(key)
    if item is None:
        return None
    timestamp, value = item
    if time.time() - timestamp > _ttl():
        return None
    return value


def _cache_set(key: str, value: Any) -> None:
    _CACHE[key] = (time.time(), value)


def invalidate() -> None:
    _CACHE.clear()


def _as_json(text: str) -> Any:
    stripped = (text or "").strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _as_list(data: Any, keys: tuple[str, ...]) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
        for value in data.values():
            if isinstance(value, list):
                return value
    return []


def _find_key(data: Any, key: str) -> Any:
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for value in data.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_key(item, key)
            if found is not None:
                return found
    return None


async def _call_json(mcp: StdioMCPClient, name: str, arguments: dict) -> Any:
    result = await mcp.call_tool(name, arguments)
    text = result_text(result)
    data = _as_json(text)
    if data is None and text.strip():
        raise RuntimeError(f"{name}: не удалось разобрать ответ MCP")
    return data


def _owner_repo() -> tuple[str, str, str]:
    cfg = config.load_config()["github"]
    return cfg["owner"], cfg["repo"], cfg["branch"]


async def get_current_branch(mcp: StdioMCPClient, refresh: bool = False) -> str:
    if not refresh:
        cached = _cache_get("branch")
        if cached:
            return cached
    owner, repo, fallback = _owner_repo()
    branch: str | None = None
    try:
        data = await _call_json(
            mcp,
            "search_repositories",
            {"query": f"repo:{owner}/{repo}", "minimal_output": False, "perPage": 1},
        )
        value = _find_key(data, "default_branch")
        if isinstance(value, str) and value:
            branch = value
    except Exception:  # noqa: BLE001
        branch = None
    if not branch:
        try:
            branches = await _list_branches_uncached(mcp)
            if len(branches) == 1:
                branch = branches[0]["name"]
        except Exception:  # noqa: BLE001
            branch = None
    if not branch:
        branch = fallback
    _cache_set("branch", branch)
    return branch


async def _list_branches_uncached(mcp: StdioMCPClient) -> list[dict]:
    owner, repo, _ = _owner_repo()
    data = await _call_json(mcp, "list_branches", {"owner": owner, "repo": repo, "perPage": 100})
    branches: list[dict] = []
    for item in _as_list(data, ("branches", "items", "entries")):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        sha = item.get("sha")
        if not isinstance(sha, str):
            commit = item.get("commit") or {}
            sha = commit.get("sha") if isinstance(commit, dict) else None
        branches.append({"name": name, "sha": sha})
    branches.sort(key=lambda entry: entry["name"])
    return branches


async def list_branches(mcp: StdioMCPClient, refresh: bool = False) -> list[dict]:
    if not refresh:
        cached = _cache_get("branches")
        if cached is not None:
            return cached
    branches = await _list_branches_uncached(mcp)
    _cache_set("branches", branches)
    return branches


def _normalize_type(value: Any) -> str:
    return "dir" if value in ("tree", "dir", "directory") else "file"


def _build_tree(entries: list) -> tuple[list[dict], int, list[str]]:
    root: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            continue
        node_type = _normalize_type(entry.get("type"))
        parts = path.split("/")
        cursor = root
        for index, part in enumerate(parts):
            key = part
            leaf = index == len(parts) - 1
            child = cursor.setdefault(
                key,
                {
                    "name": part,
                    "path": "/".join(parts[: index + 1]),
                    "type": node_type if leaf else "dir",
                    "children": {},
                },
            )
            if leaf:
                child["type"] = node_type
            cursor = child["children"]

    def finalize(nodes: dict[str, dict]) -> list[dict]:
        result = []
        for node in nodes.values():
            children = finalize(node["children"])
            result.append(
                {
                    "name": node["name"],
                    "path": node["path"],
                    "type": node["type"],
                    "children": children,
                }
            )
        result.sort(key=lambda item: (item["type"] != "dir", item["name"].lower()))
        return result

    tree = finalize(root)

    files: list[str] = []

    def collect(nodes: list[dict]) -> None:
        for node in nodes:
            if node["type"] == "file":
                files.append(node["path"])
            collect(node["children"])

    collect(tree)
    return tree, len(files), sorted(files)


def parse_tree_result(text: str) -> dict:
    data = _as_json(text)
    entries = _as_list(data, ("tree", "entries", "items"))
    tree, count, flat = _build_tree(entries)
    return {"tree": tree, "files_count": count, "files": flat}


async def fetch_file_tree(
    mcp: StdioMCPClient, branch: str | None = None, refresh: bool = False
) -> dict:
    if branch is None:
        branch = await get_current_branch(mcp, refresh=refresh)
    cache_key = f"tree:{branch}"
    if not refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    owner, repo, _ = _owner_repo()
    data = await _call_json(
        mcp,
        "get_repository_tree",
        {"owner": owner, "repo": repo, "tree_sha": branch, "recursive": True},
    )
    entries = _as_list(data, ("tree", "entries", "items"))
    tree, count, flat = _build_tree(entries)
    result = {"branch": branch, "tree": tree, "files_count": count, "files": flat}
    _cache_set(cache_key, result)
    return result


async def _commits_for_branch(mcp: StdioMCPClient, branch: str) -> list[dict]:
    owner, repo, _ = _owner_repo()
    limit = int(config.load_config()["repo"]["graph_commits_per_branch"])
    data = await _call_json(
        mcp,
        "list_commits",
        {"owner": owner, "repo": repo, "sha": branch, "perPage": limit},
    )
    commits: list[dict] = []
    for item in _as_list(data, ("commits", "items", "entries")):
        if not isinstance(item, dict):
            continue
        sha = item.get("sha")
        if not isinstance(sha, str):
            continue
        info = item.get("commit") or {}
        message = info.get("message") if isinstance(info, dict) else None
        commits.append(
            {
                "sha": sha,
                "message": (message or "").split("\n")[0][:80],
            }
        )
    commits.reverse()
    return commits


def _sanitize_label(name: str, used: set[str]) -> str:
    label = _LABEL_RE.sub("-", name).strip("-") or "branch"
    if not re.match(r"^[A-Za-z]", label):
        label = f"b-{label}"
    base = label
    index = 2
    while label in used:
        label = f"{base}-{index}"
        index += 1
    used.add(label)
    return label


def _build_mermaid(lanes: list[tuple[str, list[str]]]) -> str:
    active = [(label, shas) for label, shas in lanes if shas]
    if not active:
        return ""
    lines = ["gitGraph"]
    for index, (label, shas) in enumerate(active):
        if index == 0:
            if label != "main":
                lines.append(f"    branch {label}")
                lines.append(f"    checkout {label}")
        elif label == "main":
            lines.append("    checkout main")
        else:
            lines.append(f"    branch {label}")
            lines.append(f"    checkout {label}")
        for sha in shas:
            lines.append(f'    commit id:"{sha[:7]}"')
    return "\n".join(lines)


async def build_branch_graph(mcp: StdioMCPClient, refresh: bool = False) -> dict:
    if not refresh:
        cached = _cache_get("graph")
        if cached is not None:
            return cached

    cfg = config.load_config()["repo"]
    limit = int(cfg["graph_branches_limit"])
    current = await get_current_branch(mcp, refresh=refresh)
    branches = await list_branches(mcp, refresh=refresh)

    ordered = [entry for entry in branches if entry["name"] == current]
    ordered += [entry for entry in branches if entry["name"] != current]
    selected = ordered[:limit]

    used: set[str] = set()
    seen_commits: set[str] = set()
    lanes: list[tuple[str, list[str]]] = []
    labels: list[dict] = []
    for entry in selected:
        label = _sanitize_label(entry["name"], used)
        try:
            commits = await _commits_for_branch(mcp, entry["name"])
        except Exception:  # noqa: BLE001
            commits = []
        own = [commit["sha"] for commit in commits if commit["sha"] not in seen_commits]
        seen_commits.update(commit["sha"] for commit in commits)
        lanes.append((label, own))
        labels.append(
            {
                "name": entry["name"],
                "label": label,
                "sha": entry["sha"],
                "commits": len(own),
                "current": entry["name"] == current,
            }
        )

    result = {
        "current_branch": current,
        "branches": labels,
        "mermaid": _build_mermaid(lanes),
    }
    _cache_set("graph", result)
    return result


async def repo_overview(mcp: StdioMCPClient, refresh: bool = False) -> dict:
    if refresh:
        invalidate()
    tree = await fetch_file_tree(mcp, refresh=refresh)
    graph = await build_branch_graph(mcp, refresh=refresh)
    return {
        "current_branch": graph["current_branch"],
        "branches": graph["branches"],
        "mermaid": graph["mermaid"],
        "tree": tree["tree"],
        "files_count": tree["files_count"],
    }
