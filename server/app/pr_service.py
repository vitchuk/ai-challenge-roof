from __future__ import annotations

import re
import time
from typing import Any

import httpx

from . import config

API_BASE = "https://api.github.com"
COMMENT_MARKER = "<!-- ai-review -->"
CHECK_JOB_NAME = "review"
VERDICT_RE = re.compile(r"Вердикт\s*:\s*(.+)", re.IGNORECASE)


class PrServiceError(RuntimeError):
    pass


class PrNotFound(PrServiceError):
    pass


class PrUpstreamError(PrServiceError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


_CACHE: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str) -> Any | None:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    stamp, value = entry
    if time.monotonic() - stamp > _ttl():
        _CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: Any) -> None:
    _CACHE[key] = (time.monotonic(), value)


def _ttl() -> int:
    return int(config.load_config()["pr"]["cache_ttl_sec"])


def _token() -> str:
    token = config.github_token()
    if not token:
        raise PrServiceError(
            "GITHUB_PERSONAL_ACCESS_TOKEN не задан — заполните .env и перезапустите сервер"
        )
    return token


def _owner_repo() -> tuple[str, str]:
    cfg = config.load_config()["github"]
    return cfg["owner"], cfg["repo"]


def _headers(token: str, *, diff: bool = False) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github.diff" if diff else "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _request(
    token: str,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    diff: bool = False,
    not_found_message: str | None = None,
) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method,
                url,
                headers=_headers(token, diff=diff),
                params=params,
                json=json_body,
            )
    except httpx.HTTPError as exc:
        raise PrUpstreamError(f"GitHub недоступен: {exc}") from exc
    if response.status_code == 404:
        raise PrNotFound(not_found_message or f"Не найдено: {url}")
    if response.status_code >= 400:
        raise PrUpstreamError(
            f"GitHub ответил {response.status_code}: {response.text[:300]}",
            response.status_code,
        )
    return response


def _parse_verdict(body: str) -> str | None:
    match = VERDICT_RE.search(body)
    if not match:
        return None
    text = match.group(1).lower()
    if "замечаний нет" in text:
        return "clean"
    if "есть замечания" in text or "issues" in text:
        return "issues"
    return None


async def _get_check(token: str, owner: str, repo: str, head_sha: str) -> dict | None:
    response = await _request(
        token,
        "GET",
        f"{API_BASE}/repos/{owner}/{repo}/commits/{head_sha}/check-runs",
        params={"per_page": 100},
    )
    runs = response.json().get("check_runs", [])
    target = next((run for run in runs if run.get("name") == CHECK_JOB_NAME), None)
    if target is None:
        target = next(
            (run for run in runs if "review" in (run.get("name") or "").lower()), None
        )
    if target is None:
        return None
    return {
        "name": target.get("name"),
        "status": target.get("status"),
        "conclusion": target.get("conclusion"),
        "html_url": target.get("html_url"),
    }


async def _get_review_comment(token: str, owner: str, repo: str, pr_number: int) -> dict | None:
    response = await _request(
        token,
        "GET",
        f"{API_BASE}/repos/{owner}/{repo}/issues/{pr_number}/comments",
        params={"per_page": 100},
    )
    for comment in response.json():
        body = comment.get("body") or ""
        if COMMENT_MARKER in body:
            return {
                "body": body,
                "updated_at": comment.get("updated_at"),
                "verdict": _parse_verdict(body),
            }
    return None


def _summary(item: dict) -> dict:
    return {
        "number": item["number"],
        "title": item.get("title", ""),
        "author": (item.get("user") or {}).get("login", ""),
        "head_branch": (item.get("head") or {}).get("ref", ""),
        "head_sha": (item.get("head") or {}).get("sha", ""),
        "base_branch": (item.get("base") or {}).get("ref", ""),
        "updated_at": item.get("updated_at"),
        "html_url": item.get("html_url"),
    }


async def list_open_prs(refresh: bool = False) -> list[dict]:
    cached = _cache_get("list")
    if cached is not None and not refresh:
        return cached
    token = _token()
    owner, repo = _owner_repo()
    state = config.load_config()["pr"].get("state", "open")
    response = await _request(
        token,
        "GET",
        f"{API_BASE}/repos/{owner}/{repo}/pulls",
        params={"state": state, "sort": "updated", "direction": "desc", "per_page": 50},
        not_found_message=f"Репозиторий {owner}/{repo} не найден",
    )
    prs: list[dict] = []
    for item in response.json():
        pr = _summary(item)
        try:
            pr["check"] = (
                await _get_check(token, owner, repo, pr["head_sha"]) if pr["head_sha"] else None
            )
        except PrServiceError:
            pr["check"] = None
        try:
            pr["review"] = await _get_review_comment(token, owner, repo, pr["number"])
        except PrServiceError:
            pr["review"] = None
        prs.append(pr)
    _cache_set("list", prs)
    return prs


async def get_pr_detail(pr_number: int, refresh: bool = False) -> dict:
    cache_key = f"detail:{pr_number}"
    cached = _cache_get(cache_key)
    if cached is not None and not refresh:
        return cached
    token = _token()
    owner, repo = _owner_repo()
    base = f"{API_BASE}/repos/{owner}/{repo}"

    meta_response = await _request(
        token,
        "GET",
        f"{base}/pulls/{pr_number}",
        not_found_message=f"PR #{pr_number} не найден в {owner}/{repo}",
    )
    meta = meta_response.json()

    files_response = await _request(
        token,
        "GET",
        f"{base}/pulls/{pr_number}/files",
        params={"per_page": 100},
    )
    files = [
        {
            "filename": item.get("filename", ""),
            "status": item.get("status", ""),
            "additions": item.get("additions", 0),
            "deletions": item.get("deletions", 0),
        }
        for item in files_response.json()
    ]

    diff_response = await _request(
        token,
        "GET",
        f"{base}/pulls/{pr_number}",
        diff=True,
        not_found_message=f"PR #{pr_number} не найден в {owner}/{repo}",
    )
    diff = diff_response.text
    max_chars = int(config.load_config()["pr"]["diff_max_chars"])
    truncated = len(diff) > max_chars
    if truncated:
        diff = diff[:max_chars]

    head_sha = (meta.get("head") or {}).get("sha", "")
    try:
        check = await _get_check(token, owner, repo, head_sha) if head_sha else None
    except PrServiceError:
        check = None
    try:
        review = await _get_review_comment(token, owner, repo, pr_number)
    except PrServiceError:
        review = None

    detail = {
        "number": meta["number"],
        "title": meta.get("title", ""),
        "state": meta.get("state"),
        "draft": bool(meta.get("draft")),
        "author": (meta.get("user") or {}).get("login", ""),
        "head_branch": (meta.get("head") or {}).get("ref", ""),
        "head_sha": head_sha,
        "base_branch": (meta.get("base") or {}).get("ref", ""),
        "updated_at": meta.get("updated_at"),
        "html_url": meta.get("html_url"),
        "files": files,
        "diff": {"text": diff, "truncated": truncated},
        "check": check,
        "review": review,
    }
    _cache_set(cache_key, detail)
    return detail


async def rerun_review(pr_number: int) -> dict:
    token = _token()
    owner, repo = _owner_repo()
    cfg = config.load_config()
    branch = cfg["github"].get("branch", "main")
    workflow_file = cfg["pr"].get("workflow_file", "ai-review.yml")
    url = f"{API_BASE}/repos/{owner}/{repo}/actions/workflows/{workflow_file}/dispatches"
    try:
        await _request(
            token,
            "POST",
            url,
            json_body={"ref": branch, "inputs": {"pr_number": str(pr_number)}},
            not_found_message=f"Workflow {workflow_file} не найден в {owner}/{repo}",
        )
    except PrUpstreamError as exc:
        if exc.status_code == 403:
            raise PrUpstreamError(
                "GitHub отклонил запуск workflow (403): у PAT нет права actions:write "
                "(для классического PAT нужен scope repo, для fine-grained — Actions: write)",
                403,
            ) from exc
        raise
    return {"ok": True}
