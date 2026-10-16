from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import chat_store, config, indexer, rag, state
from .api import router
from .mcp_client import StdioMCPClient


async def _boot(mcp: StdioMCPClient) -> None:
    await mcp.start()
    if rag.index_exists():
        return
    if not mcp.status()["connected"]:
        state.BUILD.update(
            status="error",
            error="GitHub MCP не подключён — индекс не построен",
        )
        return
    try:
        await indexer.build(mcp)
    except Exception:  # noqa: BLE001
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    chat_store.init_db()
    mcp = StdioMCPClient.github()
    app.state.mcp = mcp
    asyncio.create_task(_boot(mcp))
    yield
    await mcp.stop()


app = FastAPI(title="AI Challenge Roof", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

dist_dir = config.PROJECT_ROOT / "client" / "dist"
if (dist_dir / "assets").exists():
    app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")


@app.get("/")
async def index():
    index_file = dist_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"detail": "Клиент не собран. Запустите npm run dev в папке client."}
