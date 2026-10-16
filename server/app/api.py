from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import chat, chat_store, config, indexer, llm, rag, repo_service, state

router = APIRouter(prefix="/api")

COMMANDS = [
    {
        "name": "/help",
        "description": "Задать вопрос по документации проекта (ответ из RAG-базы)",
        "usage": "/help <вопрос>",
    }
]


class ChatRequest(BaseModel):
    chat_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=4000)


class SettingsPatch(BaseModel):
    top_k: int | None = None
    model: str | None = None


def _mcp(request: Request):
    return getattr(request.app.state, "mcp", None)


@router.get("/commands")
async def commands() -> dict:
    return {"commands": COMMANDS}


async def _ollama_status() -> dict:
    base_url = config.ollama_base_url()
    model = config.load_config()["rag"]["embedding_model"]
    status = {"connected": False, "base_url": base_url, "model": model, "model_present": False}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{base_url}/api/tags")
            response.raise_for_status()
            names = [item.get("name", "") for item in response.json().get("models", [])]
        status["connected"] = True
        status["models"] = names
        status["model_present"] = any(name == model or name.startswith(f"{model}") for name in names)
    except Exception as exc:  # noqa: BLE001
        status["error"] = str(exc)
    return status


@router.get("/status")
async def status(request: Request) -> dict:
    cfg = config.load_config()
    mcp = _mcp(request)
    return {
        "rag": rag.index_status(),
        "ollama": await _ollama_status(),
        "deepseek": {"configured": llm.is_configured(), "model": cfg["llm"]["model"]},
        "mcp": mcp.status() if mcp is not None else {"connected": False, "name": "github", "error": "не инициализирован"},
        "top_k": cfg["rag"]["chat_top_k"],
        "ui": cfg["ui"],
        "github": {"owner": cfg["github"]["owner"], "repo": cfg["github"]["repo"], "branch": cfg["github"]["branch"]},
    }


@router.get("/settings")
async def get_settings() -> dict:
    cfg = config.load_config()
    return {
        "top_k": cfg["rag"]["chat_top_k"],
        "model": cfg["llm"]["model"],
        "allowed_models": cfg["llm"]["allowed_models"],
        "ui": cfg["ui"],
        "rag_params": cfg["rag"],
    }


@router.patch("/settings")
async def patch_settings(patch: SettingsPatch) -> dict:
    cfg = config.load_config()
    if patch.top_k is not None:
        if not (cfg["ui"]["top_k_min"] <= patch.top_k <= cfg["ui"]["top_k_max"]):
            raise HTTPException(
                status_code=400,
                detail=f"Top_K должен быть в диапазоне {cfg['ui']['top_k_min']}–{cfg['ui']['top_k_max']}",
            )
        cfg["rag"]["chat_top_k"] = patch.top_k
    if patch.model is not None:
        if patch.model not in cfg["llm"]["allowed_models"]:
            raise HTTPException(status_code=400, detail="Недопустимая модель")
        cfg["llm"]["model"] = patch.model
    config.save_config(cfg)
    return {"top_k": cfg["rag"]["chat_top_k"], "model": cfg["llm"]["model"]}


@router.post("/rag/rebuild")
async def rebuild_index(request: Request) -> dict:
    if state.BUILD["status"] == "building":
        return {"started": False, "status": "building"}
    mcp = _mcp(request)
    if mcp is None or not mcp.status()["connected"]:
        raise HTTPException(status_code=400, detail="GitHub MCP не подключён")

    async def run() -> None:
        try:
            await indexer.build(mcp)
        except Exception:  # noqa: BLE001
            pass

    asyncio.create_task(run())
    return {"started": True, "status": "building"}


@router.get("/chats")
async def list_chats() -> dict:
    return {"chats": chat_store.list_chats()}


@router.post("/chats")
async def create_chat() -> dict:
    return chat_store.create_chat()


@router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str) -> dict:
    chat_store.delete_chat(chat_id)
    return {"ok": True}


@router.get("/chats/{chat_id}/messages")
async def get_messages(chat_id: str) -> dict:
    if chat_store.get_chat(chat_id) is None:
        raise HTTPException(status_code=404, detail="Чат не найден")
    return {"messages": chat_store.get_messages(chat_id)}


@router.post("/chat")
async def send_message(payload: ChatRequest, request: Request) -> dict:
    if chat_store.get_chat(payload.chat_id) is None:
        raise HTTPException(status_code=404, detail="Чат не найден")
    return await chat.handle_message(payload.chat_id, payload.message, _mcp(request))


@router.get("/repo")
async def repo(request: Request, refresh: bool = False) -> dict:
    mcp = _mcp(request)
    if mcp is None or not mcp.status()["connected"]:
        raise HTTPException(status_code=400, detail="GitHub MCP не подключён")
    try:
        return await repo_service.repo_overview(mcp, refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"Не удалось получить данные репозитория: {exc}"
        ) from exc
