from __future__ import annotations

import json
import re
import time
from typing import Any

from . import chat_store, config, llm, rag, repo_service
from .mcp_client import StdioMCPClient, result_is_error, result_text

HELP_USAGE = (
    "Команда `/help` задаёт вопрос по документации проекта и отвечает на основе RAG-базы знаний, "
    "а для вопросов про файлы и ветки репозитория использует инструменты GitHub MCP.\n\n"
    "Пример: `/help кратко изложи суть проекта`\n\n"
    "Без команды `/help` сообщения обрабатываются как обычный чат с моделью."
)

FREE_CHAT_SYSTEM_PROMPT = (
    "Ты — дружелюбный ассистент-помощник. Отвечай на русском языке, кратко и по делу."
)

RAG_TOOLS_EXCEPTION = (
    "Исключение из правила «отвечать только по контексту»: вопросы о списке файлов, структуре "
    "репозитория, ветках и коммитах решай через инструменты GitHub MCP, даже если их нет в "
    "контексте. В таком ответе раздел «Источники:» не нужен."
)

FREE_TOOLS_ADDENDUM = (
    "Вопросы по документации проекта лучше задавать командой /help."
)

_REPO_TOOL_HINTS = (
    "Инструменты GitHub MCP и параметры репозитория: owner=\"{owner}\", repo=\"{repo}\", "
    "текущая ветка=\"{branch}\".\n"
    "- полное дерево файлов: get_repository_tree(owner, repo, tree_sha=<ветка>, recursive=true)\n"
    "- содержимое файла или листинг папки: get_file_contents(owner, repo, path=<путь>, ref=\"refs/heads/<ветка>\")\n"
    "- список ветвей: list_branches(owner, repo)\n"
    "- последние коммиты ветки: list_commits(owner, repo, sha=<ветка>, perPage=10)\n"
    "Если вопрос касается файлов, структуры, ветвей или коммитов — СНАЧАЛА вызови нужный "
    "инструмент и ответь на основе его результата. Никогда не выдумывай список файлов."
)

_INTENT_RE = re.compile(
    r"файл|структур|дерев|папк|директори|ветк|branch|коммит|commit|репозитори|repo",
    re.IGNORECASE,
)

_CITATION_RE = re.compile(r"(?m)^\s*>\s*\[([^\]]+)\]\s*(.+?)\s*$")
_PREVIEW_CHARS = 600


def _wants_repo_tools(text: str) -> bool:
    return bool(_INTENT_RE.search(text))


async def _repo_addendum(mcp: StdioMCPClient | None) -> str:
    cfg = config.load_config()["github"]
    owner, repo, fallback = cfg["owner"], cfg["repo"], cfg["branch"]
    branch = fallback
    if mcp is not None and mcp.status()["connected"]:
        try:
            branch = await repo_service.get_current_branch(mcp)
        except Exception:  # noqa: BLE001
            branch = fallback
    return _REPO_TOOL_HINTS.format(owner=owner, repo=repo, branch=branch)


def _build_tools(mcp: StdioMCPClient | None) -> list[dict]:
    if mcp is None or not mcp.status()["connected"]:
        return []
    whitelist = set(config.load_config()["agent"]["tools_whitelist"])
    tools: list[dict] = []
    for definition in mcp.tool_defs():
        if definition["name"] not in whitelist:
            continue
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": definition["name"],
                    "description": definition["description"],
                    "parameters": definition["input_schema"],
                },
            }
        )
    return tools


def _parse_arguments(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


async def _run_agent(
    messages: list[dict],
    mcp: StdioMCPClient | None,
    force_tools: bool = False,
) -> tuple[str, list[dict]]:
    agent_cfg = config.load_config()["agent"]
    max_iterations = int(agent_cfg["max_iterations"])
    max_chars = int(agent_cfg["tool_result_max_chars"])
    tools = _build_tools(mcp)
    events: list[dict] = []

    for iteration in range(max_iterations):
        if tools and force_tools and iteration == 0:
            tool_choice = "required"
        else:
            tool_choice = "auto" if tools else None
        result = await llm.chat_complete_raw(
            messages, tools=tools or None, tool_choice=tool_choice
        )
        calls = result["tool_calls"]
        if not calls:
            return result["content"], events
        messages.append(
            {
                "role": "assistant",
                "content": result["content"] or None,
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {"name": call["name"], "arguments": call["arguments"]},
                    }
                    for call in calls
                ],
            }
        )
        for call in calls:
            arguments = _parse_arguments(call["arguments"])
            try:
                raw = await mcp.call_tool(call["name"], arguments)
                text = result_text(raw)
                is_error = result_is_error(raw)
            except Exception as exc:  # noqa: BLE001
                text = f"Ошибка вызова инструмента {call['name']}: {exc}"
                is_error = True
            events.append(
                {
                    "name": call["name"],
                    "arguments": arguments,
                    "is_error": is_error,
                    "preview": text[:_PREVIEW_CHARS],
                    "text": text,
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": text[:max_chars] or "(пустой результат)",
                }
            )

    return "Превышен лимит вызовов инструментов — не удалось завершить ответ.", events


async def _collect_extra(events: list[dict], mcp: StdioMCPClient | None) -> dict:
    names = {event["name"] for event in events}
    extra: dict[str, Any] = {"repo_tree": None, "branch_graph": None}

    if "get_repository_tree" in names:
        for event in events:
            if event["name"] == "get_repository_tree" and not event["is_error"]:
                parsed = repo_service.parse_tree_result(event["text"])
                if parsed["files_count"]:
                    extra["repo_tree"] = parsed
                break

    if names & {"list_branches", "list_commits"} and mcp is not None:
        try:
            extra["branch_graph"] = await repo_service.build_branch_graph(mcp)
        except Exception:  # noqa: BLE001
            extra["branch_graph"] = None

    return extra


def _public_tools(events: list[dict]) -> list[dict]:
    return [
        {
            "name": event["name"],
            "arguments": event["arguments"],
            "is_error": event["is_error"],
            "preview": event["preview"],
        }
        for event in events
    ]


def _extract_citations(reply: str, chunk_ids: set[str]) -> tuple[str, list[dict]]:
    citations: list[dict] = []

    def collect(match: re.Match) -> str:
        citation_id = match.group(1).strip()
        quote = match.group(2).strip()
        if citation_id in chunk_ids:
            citations.append({"chunk_id": citation_id, "quote": quote})
            return f"> {quote}"
        return match.group(0)

    cleaned = _CITATION_RE.sub(collect, reply)
    for chunk_id in sorted(chunk_ids, key=len, reverse=True):
        cleaned = cleaned.replace(f"[{chunk_id}]", "")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"(?m)^[ \t]+", "", cleaned)
    return cleaned.strip(), citations


def _compose_rag_prompt(question: str, context: str | None, rag_error: str | None) -> str:
    if context:
        return (
            "Контекст из базы знаний проекта:\n"
            f"{context}\n\n"
            f"Вопрос пользователя: {question}"
        )
    if rag_error:
        return (
            f"Контекст из базы знаний недоступен ({rag_error}).\n\n"
            f"Вопрос пользователя: {question}"
        )
    return f"В базе знаний не найдено релевантных фрагментов.\n\nВопрос пользователя: {question}"


async def handle_message(
    chat_id: str,
    text: str,
    mcp: StdioMCPClient | None = None,
) -> dict:
    cfg = config.load_config()
    message = text.strip()
    started = time.perf_counter()
    history = chat_store.recent_history(chat_id, int(cfg["llm"]["history_limit"]))

    tools_available = mcp is not None and mcp.status()["connected"]
    addendum = await _repo_addendum(mcp) if tools_available else ""

    if message.startswith("/help"):
        question = message[len("/help"):].strip()
        if not question:
            elapsed = int((time.perf_counter() - started) * 1000)
            return _persist(chat_id, message, HELP_USAGE, elapsed_ms=elapsed)

        force_tools = tools_available and _wants_repo_tools(question)

        hits: list[dict] = []
        debug: dict | None = None
        context: str | None = None
        rag_error: str | None = None
        try:
            hits, debug, context = await rag.build_rag_context(
                question, history, int(cfg["rag"]["chat_top_k"])
            )
        except Exception as exc:  # noqa: BLE001
            rag_error = str(exc)

        system_prompt = f"{rag.RAG_SYSTEM_PROMPT}\n\n{RAG_TOOLS_EXCEPTION}\n\n{addendum}".strip()
        messages = (
            [{"role": "system", "content": system_prompt}]
            + history
            + [{"role": "user", "content": _compose_rag_prompt(question, context, rag_error)}]
        )
        events: list[dict] = []
        try:
            reply, events = await _run_agent(messages, mcp, force_tools=force_tools)
            reply, citations = _extract_citations(reply, {hit["chunk_id"] for hit in hits})
        except llm.LLMError as exc:
            reply, citations = str(exc), []

        sources = [
            {
                "chunk_id": hit["chunk_id"],
                "file": hit["file"],
                "title": hit["title"],
                "score": hit["score"],
                "excerpt": hit["text"][:400],
            }
            for hit in hits
        ]
        for citation in citations:
            for source in sources:
                if source["chunk_id"] == citation["chunk_id"]:
                    citation["file"] = source["file"]
                    citation["title"] = source["title"]

        extra = await _collect_extra(events, mcp)
        elapsed = int((time.perf_counter() - started) * 1000)
        return _persist(
            chat_id,
            message,
            reply,
            elapsed_ms=elapsed,
            sources=sources,
            debug=debug,
            tools=_public_tools(events),
            extra=extra,
        )

    free_system = f"{FREE_CHAT_SYSTEM_PROMPT}\n\n{FREE_TOOLS_ADDENDUM}\n\n{addendum}".strip()
    messages = (
        [{"role": "system", "content": free_system}]
        + history
        + [{"role": "user", "content": message}]
    )
    events = []
    try:
        reply, events = await _run_agent(
            messages, mcp, force_tools=tools_available and _wants_repo_tools(message)
        )
    except llm.LLMError as exc:
        reply = str(exc)
    extra = await _collect_extra(events, mcp)
    elapsed = int((time.perf_counter() - started) * 1000)
    return _persist(
        chat_id,
        message,
        reply,
        elapsed_ms=elapsed,
        tools=_public_tools(events),
        extra=extra,
    )


def _persist(
    chat_id: str,
    user_text: str,
    reply: str,
    *,
    elapsed_ms: int,
    sources: list | None = None,
    debug: dict | None = None,
    tools: list | None = None,
    extra: dict | None = None,
) -> dict:
    chat_store.add_message(chat_id, "user", user_text)
    stored = chat_store.add_message(
        chat_id,
        "assistant",
        reply,
        elapsed_ms=elapsed_ms,
        sources=sources,
        debug=debug,
        tools=tools,
        extra=extra,
    )
    return {
        "reply": reply,
        "elapsed_ms": elapsed_ms,
        "sources": sources or [],
        "debug": debug,
        "tools": tools or [],
        "extra": extra,
        "message_id": stored["id"],
    }
