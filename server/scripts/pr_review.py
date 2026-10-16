from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import subprocess
import sys
from fnmatch import fnmatchcase
from pathlib import Path

import httpx

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from app import llm, rag  # noqa: E402

MODEL = "deepseek-chat"
TEMPERATURE = 0.2
MAX_OUTPUT_TOKENS = 4000

TOP_K_PER_FILE = 5
TOP_K_PR = 8
MAX_QUERY_FILES = 10
CONTEXT_MAX_CHARS = 40000

DIFF_MAX_LINES = 3000
CORPUS_FILE_MAX_KB = 100
FILE_CONTENT_MAX_KB = 50
MAX_CHANGED_FILES_IN_PROMPT = 20
PR_BODY_MAX_CHARS = 4000

ROOT_FILES = ("README.md", "AGENTS.md")
DOCS_DIR = "docs"
CODE_GLOBS = (
    "server/*.py",
    "server/**/*.py",
    "client/src/*.ts",
    "client/src/**/*.ts",
    "client/src/**/*.vue",
    "scripts/*.py",
)
TEXT_EXTS = {
    ".py", ".ts", ".vue", ".js", ".mjs", ".json", ".md", ".txt", ".toml",
    ".yml", ".yaml", ".bat", ".ps1", ".css", ".html", ".sql", ".ini", ".cfg",
}
EXCLUDED_PATHS = {"pikabu-txt.md", "package-lock.json", "pnpm-lock.yaml"}

COMMENT_MARKER = "<!-- ai-review -->"
VERDICT_RE = re.compile(r"VERDICT\s*:\s*(CLEAN|ISSUES)", re.IGNORECASE)
API_BASE = "https://api.github.com"

REVIEW_SYSTEM_PROMPT = (
    "Ты — старший инженер-ревьюер. Ты анализируешь pull request проекта (код и документация). "
    "Тебе даны diff, содержимое изменённых файлов и выдержки из базы знаний проекта "
    "(документация и исходный код).\n\n"
    "Правила:\n"
    "1. Оценивай только предоставленные материалы. Не выдумывай файлы, функции и факты.\n"
    "2. Опирайся на контекст базы знаний: проверяй, не противоречат ли изменения описанной "
    "архитектуре, инвариантам и соглашениям проекта; при необходимости ссылайся на файлы контекста.\n"
    "3. Отвечай на русском языке, структурировано и по делу, без воды.\n"
    "4. Верни markdown ровно с тремя разделами перечисленными ниже, в этом порядке:\n"
    "## Потенциальные баги\n"
    "## Архитектурные проблемы\n"
    "## Рекомендации\n"
    "5. В каждом разделе — список пунктов. Каждый пункт: суть проблемы, ссылка на файл (и строку "
    "или фрагмент, если можно), почему это проблема и чем грозит. Если пунктов нет, напиши «Нет».\n"
    "6. В «Рекомендации» включай улучшения читаемости, тестов, документации и т.п. — они не блокируют merge.\n"
    "7. Блокирующими считаются только реальные потенциальные баги и архитектурные проблемы.\n"
    "8. Последней строкой ответа обязательно выведи вердикт — ровно одно из двух:\n"
    "VERDICT: ISSUES — если есть потенциальные баги или архитектурные проблемы;\n"
    "VERDICT: CLEAN — если их нет.\n"
    "После строки вердикта не добавляй ничего."
)


def segment_match(segment: str, pattern: str) -> bool:
    return fnmatchcase(segment, pattern)


def path_matches(path: str, pattern: str) -> bool:
    parts = path.split("/")
    pat = pattern.split("/")

    def walk(pi: int, gi: int) -> bool:
        if gi == len(pat):
            return pi == len(parts)
        if pat[gi] == "**":
            if gi + 1 == len(pat):
                return True
            return any(walk(skip, gi + 1) for skip in range(pi, len(parts) + 1))
        if pi == len(parts):
            return False
        return segment_match(parts[pi], pat[gi]) and walk(pi + 1, gi + 1)

    return walk(0, 0)


def run_git(repo_dir: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def git_output(repo_dir: Path, args: list[str]) -> str:
    result = run_git(repo_dir, args)
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)}: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout


def read_file_at(repo_dir: Path, ref: str, path: str) -> str | None:
    result = run_git(repo_dir, ["show", f"{ref}:{path}"])
    if result.returncode != 0:
        return None
    return result.stdout


def pr_diff(repo_dir: Path, base: str, head: str) -> tuple[str, int, bool]:
    text = git_output(repo_dir, ["diff", "--no-color", "--no-ext-diff", f"{base}...{head}"])
    lines = text.splitlines()
    total = len(lines)
    if total > DIFF_MAX_LINES:
        return "\n".join(lines[:DIFF_MAX_LINES]), total, True
    return text, total, False


def changed_files(repo_dir: Path, base: str, head: str) -> list[tuple[str, str]]:
    output = git_output(
        repo_dir, ["diff", "--name-status", "--no-ext-diff", f"{base}...{head}"]
    )
    files: list[tuple[str, str]] = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            files.append((parts[0].strip(), parts[-1].strip()))
    return files


def file_title(path: str, text: str) -> str:
    match = re.search(r"(?m)^#{1,6}\s+(.+)$", text)
    if match:
        return match.group(1).strip()
    return path


def is_doc(path: str) -> bool:
    return path.startswith(f"{DOCS_DIR}/") and path.count("/") == 1 and path.endswith(".md")


def is_code(path: str) -> bool:
    return any(path_matches(path, pattern) for pattern in CODE_GLOBS)


def collect_corpus(repo_dir: Path, ref: str) -> list[dict]:
    tracked = git_output(repo_dir, ["ls-tree", "-r", "--name-only", ref]).splitlines()
    selected: list[str] = []
    for path in (*ROOT_FILES, *tracked):
        if path in EXCLUDED_PATHS or path in selected:
            continue
        if path in ROOT_FILES or is_doc(path) or is_code(path):
            selected.append(path)

    documents: list[dict] = []
    for path in selected:
        text = read_file_at(repo_dir, ref, path)
        if text is None or not text.strip():
            continue
        if len(text.encode("utf-8")) > CORPUS_FILE_MAX_KB * 1024:
            continue
        documents.append({"path": path, "title": file_title(path, text), "text": text})
    return documents


def corpus_digest(documents: list[dict]) -> str:
    payload = "".join(f"{doc['path']}:{len(doc['text'])}" for doc in documents)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def ensure_index(documents: list[dict]) -> tuple[dict, bool]:
    if not documents:
        raise RuntimeError("Корпус для индексации пуст")
    digest = corpus_digest(documents)
    if rag.index_exists():
        try:
            index = rag.load_index()
            if index.get("source", {}).get("sha256") == digest:
                return index, False
        except Exception:
            pass
    return await rag.build_index(documents), True


def format_context(hits: list[dict]) -> str:
    blocks: list[str] = []
    used = 0
    for hit in hits:
        block = f"[{hit['chunk_id']}] {hit['file']} — {hit['title']}\n{hit['text']}"
        if used + len(block) > CONTEXT_MAX_CHARS:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n---\n\n".join(blocks)


async def retrieve(changed_paths: list[str], title: str, body: str) -> list[dict]:
    queries: list[tuple[str, int]] = []
    for path in changed_paths[:MAX_QUERY_FILES]:
        queries.append((f"{title}. Изменённый файл: {path}", TOP_K_PER_FILE))
    overall = f"{title}\n{body[:500]}\nИзменённые файлы: {', '.join(changed_paths)}"
    queries.append((overall, TOP_K_PR))

    best: dict[str, dict] = {}
    for query, top_k in queries:
        for hit in await rag.search(query, top_k):
            existing = best.get(hit["chunk_id"])
            if existing is None or hit["score"] > existing["score"]:
                best[hit["chunk_id"]] = hit
    return sorted(best.values(), key=lambda item: item["score"], reverse=True)


def build_user_prompt(
    title: str,
    body: str,
    changes: list[tuple[str, str]],
    diff: str,
    diff_total: int,
    truncated: bool,
    contents: list[tuple[str, str]],
    context: str | None,
) -> str:
    parts = ["# Pull request", f"Заголовок: {title or '(не указан)'}"]
    if body.strip():
        parts.append(f"Описание:\n{body[:PR_BODY_MAX_CHARS]}")
    if changes:
        listed = "\n".join(f"- {status} {path}" for status, path in changes[:MAX_CHANGED_FILES_IN_PROMPT])
        parts.append(f"Изменённые файлы:\n{listed}")
    else:
        parts.append("Изменённые файлы: (нет)")

    parts.append("# Diff\n```diff\n" + (diff or "(пусто)") + "\n```")
    if truncated:
        parts.append(f"[Diff усечён: показаны первые {DIFF_MAX_LINES} строк из {diff_total}]")

    if contents:
        blocks = [f"## {path}\n```\n{text}\n```" for path, text in contents]
        parts.append("# Содержимое изменённых файлов\n" + "\n\n".join(blocks))

    if context:
        parts.append(
            "# Контекст базы знаний (документация и код проекта)\n" + context
        )
    else:
        parts.append("# Контекст базы знаний\n(недоступен)")

    parts.append(
        "Проведи ревью этого pull request строго по формату из системной инструкции "
        "и последней строкой выведи вердикт VERDICT: CLEAN или VERDICT: ISSUES."
    )
    return "\n\n".join(parts)


def split_verdict(text: str) -> tuple[str, str, bool]:
    matches = list(VERDICT_RE.finditer(text))
    if not matches:
        return "ISSUES", text.strip(), False
    last = matches[-1]
    body = (text[: last.start()] + text[last.end():]).strip()
    return last.group(1).upper(), body, True


def compose_comment(
    pr_number: int,
    head_sha: str,
    verdict: str,
    rag_status: str,
    review_body: str,
    parse_ok: bool,
) -> str:
    verdict_line = (
        "Вердикт: есть замечания — merge заблокирован"
        if verdict == "ISSUES"
        else "Вердикт: замечаний нет"
    )
    lines = [
        COMMENT_MARKER,
        "## AI Review",
        "",
        f"PR #{pr_number}, head `{head_sha[:10]}`",
        f"RAG: {rag_status}",
        verdict_line,
        "",
    ]
    if not parse_ok:
        lines.extend(
            ["Вердикт не распознан в ответе модели — считаю как «есть замечания».", ""]
        )
    lines.extend(["---", "", review_body.strip(), ""])
    return "\n".join(lines)


def github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def upsert_comment(token: str, repo: str, pr_number: int, body: str) -> str:
    url = f"{API_BASE}/repos/{repo}/issues/{pr_number}/comments"
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(url, headers=github_headers(token), params={"per_page": 100})
        response.raise_for_status()
        existing = next(
            (c for c in response.json() if COMMENT_MARKER in (c.get("body") or "")), None
        )
        if existing:
            update = await client.patch(
                f"{API_BASE}/repos/{repo}/issues/comments/{existing['id']}",
                headers=github_headers(token),
                json={"body": body},
            )
            update.raise_for_status()
            return "updated"
        create = await client.post(url, headers=github_headers(token), json={"body": body})
        create.raise_for_status()
        return "created"


async def publish(args: argparse.Namespace, comment: str) -> None:
    if args.dry_run:
        print(comment)
        return
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN не задан")
    action = await upsert_comment(token, args.repo, args.pr_number, comment)
    print(f"Комментарий: {action}")


async def publish_or_fail(args: argparse.Namespace, comment: str) -> bool:
    try:
        await publish(args, comment)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Не удалось опубликовать комментарий: {exc}")
        return False


def use_index_dir(value: str) -> None:
    target = Path(value).resolve()

    def index_path() -> Path:
        path = target / "index.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    rag.index_path = index_path  # type: ignore[assignment]


async def run(args: argparse.Namespace) -> int:
    if args.index_dir:
        use_index_dir(args.index_dir)
    repo_dir = Path(args.repo_dir).resolve()
    changes = changed_files(repo_dir, args.base, args.head)
    diff, diff_total, truncated = pr_diff(repo_dir, args.base, args.head)

    changed_paths = [path for status, path in changes if status != "D"]
    reviewable = [
        path
        for path in changed_paths
        if Path(path).suffix.lower() in TEXT_EXTS and path not in EXCLUDED_PATHS
    ]

    contents: list[tuple[str, str]] = []
    for path in reviewable[:MAX_CHANGED_FILES_IN_PROMPT]:
        text = read_file_at(repo_dir, args.head, path)
        if text is None:
            continue
        limit = FILE_CONTENT_MAX_KB * 1024
        if len(text.encode("utf-8")) > limit:
            text = text[:limit] + "\n... [файл усечён]"
        contents.append((path, text))

    rag_status = "не собирался"
    context: str | None = None
    try:
        corpus = collect_corpus(repo_dir, args.base)
        index, built = await ensure_index(corpus)
        hits = await retrieve(reviewable, args.title, args.body)
        context = format_context(hits)
        rag_status = (
            f"корпус {len(corpus)} файлов, {len(index.get('chunks', []))} фрагментов, "
            f"выбрано {len(hits)}"
            + (", индекс пересобран" if built else ", индекс из кэша")
        )
    except Exception as exc:  # noqa: BLE001
        rag_status = f"недоступен ({exc})"

    user_prompt = build_user_prompt(
        args.title, args.body, changes, diff, diff_total, truncated, contents, context
    )

    try:
        raw = await llm.chat_complete(
            [
                {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model=MODEL,
            temperature=TEMPERATURE,
            max_tokens=MAX_OUTPUT_TOKENS,
        )
    except Exception as exc:  # noqa: BLE001
        comment = compose_comment(
            args.pr_number,
            args.head,
            "ISSUES",
            rag_status,
            f"Ревью не выполнено: {exc}",
            True,
        )
        await publish_or_fail(args, comment)
        print(f"Ошибка LLM: {exc}")
        return 1

    verdict, review_body, parse_ok = split_verdict(raw)
    comment = compose_comment(
        args.pr_number, args.head, verdict, rag_status, review_body, parse_ok
    )
    if not await publish_or_fail(args, comment):
        return 1
    print(f"Вердикт: {verdict}")
    return 0 if verdict == "CLEAN" else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI-ревью pull request по diff и RAG-базе проекта"
    )
    parser.add_argument("--repo-dir", required=True, help="путь к локальному клону целевого репо")
    parser.add_argument("--base", required=True, help="base SHA (ветка, в которую мёржится PR)")
    parser.add_argument("--head", required=True, help="head SHA (ветка PR)")
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--index-dir", default="", help="папка для index.json (изолирует индекс от чат-приложения)")
    parser.add_argument("--title", default="")
    parser.add_argument("--body", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
