from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from . import config


class LLMError(RuntimeError):
    pass


def _client(cfg: dict) -> AsyncOpenAI:
    api_key = config.deepseek_api_key()
    if not api_key:
        raise LLMError("DEEPSEEK_API_KEY не задан. Укажите ключ в файле .env и перезапустите сервер.")
    return AsyncOpenAI(
        api_key=api_key,
        base_url=cfg["llm"].get("base_url"),
        timeout=120,
        max_retries=2,
    )


async def chat_complete(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    cfg = config.load_config()
    llm_cfg = cfg["llm"]
    client = _client(cfg)
    try:
        response = await client.chat.completions.create(
            model=model or llm_cfg["model"],
            messages=messages,
            temperature=llm_cfg["answer_temperature"] if temperature is None else temperature,
            max_tokens=llm_cfg["answer_max_tokens"] if max_tokens is None else max_tokens,
        )
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"Ошибка обращения к DeepSeek: {exc}") from exc
    return response.choices[0].message.content or ""


async def complete_text(
    system: str,
    user: str,
    *,
    temperature: float = 0.0,
    max_tokens: int = 200,
) -> str:
    return await chat_complete(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )


async def chat_complete_raw(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    cfg = config.load_config()
    llm_cfg = cfg["llm"]
    client = _client(cfg)
    kwargs: dict[str, Any] = {
        "model": model or llm_cfg["model"],
        "messages": messages,
        "temperature": llm_cfg["answer_temperature"] if temperature is None else temperature,
        "max_tokens": llm_cfg["answer_max_tokens"] if max_tokens is None else max_tokens,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice or "auto"
    try:
        response = await client.chat.completions.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        if tools and kwargs.get("tool_choice") == "required":
            kwargs["tool_choice"] = "auto"
            try:
                response = await client.chat.completions.create(**kwargs)
            except Exception as retry_exc:  # noqa: BLE001
                raise LLMError(f"Ошибка обращения к DeepSeek: {retry_exc}") from retry_exc
        else:
            raise LLMError(f"Ошибка обращения к DeepSeek: {exc}") from exc

    message = response.choices[0].message
    tool_calls = []
    for call in message.tool_calls or []:
        tool_calls.append(
            {
                "id": call.id,
                "name": call.function.name,
                "arguments": call.function.arguments,
            }
        )
    return {"content": message.content or "", "tool_calls": tool_calls}


def is_configured() -> bool:
    return config.deepseek_api_key() is not None
