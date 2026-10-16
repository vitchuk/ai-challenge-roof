from __future__ import annotations

from . import config, llm

REWRITE_SYSTEM_PROMPT = (
    "Ты — оптимизатор поисковых запросов для векторного поиска по базе знаний проекта. "
    "Перепиши вопрос пользователя в ОДИН самодостаточный поисковый запрос на русском языке: "
    "раскрой местоимения и указательные слова («это», «он», «такой») на основе истории диалога, "
    "добавь ключевые термины. Верни ТОЛЬКО переписанный запрос — без пояснений, кавычек и префиксов."
)


class PipelineError(RuntimeError):
    pass


def _clean(text: str) -> str:
    cfg = config.load_config()["llm"]
    value = text.strip().strip('"').strip("«»").strip()
    return value[: cfg["rewrite_max_chars"]]


def _build_user_prompt(question: str, history: list[dict]) -> str:
    cfg = config.load_config()["llm"]
    lines: list[str] = []
    if history:
        lines.append("История диалога:")
        for message in history[-cfg["rewrite_history_limit"]:]:
            role = "Пользователь" if message["role"] == "user" else "Ассистент"
            lines.append(f"{role}: {message['content'][:300]}")
    lines.append(f"Вопрос пользователя: {question}")
    lines.append("Переписанный поисковый запрос:")
    return "\n".join(lines)


async def rewrite_query(question: str, history: list[dict]) -> tuple[str, bool]:
    cfg = config.load_config()["llm"]
    prompt = _build_user_prompt(question, history)
    try:
        result = await llm.complete_text(
            REWRITE_SYSTEM_PROMPT,
            prompt,
            temperature=cfg["rewrite_temperature"],
            max_tokens=cfg["rewrite_max_tokens"],
        )
        rewritten = _clean(result)
        if not rewritten:
            raise PipelineError("Модель вернула пустой запрос")
        return rewritten, False
    except Exception:  # noqa: BLE001
        return question, True


async def run_retrieval(
    question: str,
    history: list[dict],
    top_k: int,
    retriever,
) -> tuple[list[dict], dict]:
    rewritten, fallback = await rewrite_query(question, history)
    hits = await retriever(rewritten, top_k)
    debug = {
        "strategy": "query-rewrite",
        "original_query": question,
        "rewritten_query": rewritten,
        "rewrite_fallback": fallback,
        "top_k": top_k,
        "retrieved": len(hits),
    }
    return hits, debug
