from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from . import config


class MCPError(RuntimeError):
    pass


def _item_text(item: Any) -> str:
    text = getattr(item, "text", None)
    if isinstance(text, str):
        return text
    resource = getattr(item, "resource", None)
    if resource is not None:
        resource_text = getattr(resource, "text", None)
        if isinstance(resource_text, str):
            return resource_text
        blob = getattr(resource, "blob", None)
        if isinstance(blob, str):
            try:
                return base64.b64decode(blob).decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                return ""
    return ""


def result_text(result: Any) -> str:
    parts = []
    for item in getattr(result, "content", None) or []:
        value = _item_text(item)
        if value:
            parts.append(value)
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if structured:
        rendered = json.dumps(structured, ensure_ascii=False)
        if rendered not in parts:
            parts.insert(0, rendered)
    return "\n".join(parts)


def result_is_error(result: Any) -> bool:
    for attr in ("is_error", "isError"):
        value = getattr(result, attr, None)
        if value is not None:
            return bool(value)
    return False


class StdioMCPClient:
    def __init__(
        self,
        name: str,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
        startup_timeout: float = 90,
        call_timeout: float = 120,
    ) -> None:
        self.name = name
        self.command = command
        self.args = args
        self.env = env
        self.startup_timeout = startup_timeout
        self.call_timeout = call_timeout
        self._requests: asyncio.Queue = asyncio.Queue()
        self._ready = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._connected = False
        self._error: str | None = None
        self._tool_defs: list[dict[str, Any]] = []

    @classmethod
    def github(cls) -> "StdioMCPClient":
        cfg = config.load_config()["mcp"]["github"]
        env = dict(os.environ)
        token = config.github_token()
        if token:
            env["GITHUB_PERSONAL_ACCESS_TOKEN"] = token
        return cls(
            name=cfg.get("name", "github"),
            command=str(config.resolve_path(cfg["command"])),
            args=list(cfg.get("args", [])),
            env=env,
            startup_timeout=float(cfg.get("startup_timeout_sec", 90)),
            call_timeout=float(cfg.get("call_timeout_sec", 120)),
        )

    async def _run(self) -> None:
        if not Path(self.command).exists():
            self._error = f"Не найден исполняемый файл MCP-сервера: {self.command}"
            self._ready.set()
            return
        try:
            params = StdioServerParameters(command=self.command, args=self.args, env=self.env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self._tool_defs = [
                        {
                            "name": tool.name,
                            "description": tool.description or "",
                            "input_schema": tool.input_schema or {"type": "object", "properties": {}},
                        }
                        for tool in tools.tools
                    ]
                    self._connected = True
                    self._error = None
                    self._ready.set()
                    while True:
                        request = await self._requests.get()
                        if request.get("stop"):
                            break
                        future: asyncio.Future = request["future"]
                        try:
                            result = await session.call_tool(
                                request["name"], request.get("arguments", {})
                            )
                            if not future.done():
                                future.set_result(result)
                        except Exception as exc:  # noqa: BLE001
                            if not future.done():
                                future.set_exception(exc)
        except Exception as exc:  # noqa: BLE001
            self._error = str(exc) or exc.__class__.__name__
            self._connected = False
            self._ready.set()
        finally:
            self._connected = False

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=self.startup_timeout)
        except asyncio.TimeoutError:
            self._error = f"Таймаут запуска MCP-сервера ({self.startup_timeout:.0f} с)"

    async def stop(self) -> None:
        if self._task is None:
            return
        await self._requests.put({"stop": True})
        try:
            await asyncio.wait_for(self._task, timeout=10)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._task.cancel()
        finally:
            self._task = None
            self._connected = False

    async def call_tool(self, name: str, arguments: dict | None = None) -> Any:
        if not self._connected:
            raise MCPError(self._error or "MCP-сервер не подключён")
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        await self._requests.put(
            {"name": name, "arguments": arguments or {}, "future": future}
        )
        return await asyncio.wait_for(future, timeout=self.call_timeout)

    def status(self) -> dict:
        return {
            "name": self.name,
            "connected": self._connected,
            "error": self._error,
            "tools_count": len(self._tool_defs),
            "tools": [tool["name"] for tool in self._tool_defs],
            "command": self.command,
        }

    def tool_defs(self) -> list[dict[str, Any]]:
        return list(self._tool_defs)

    def tool_names(self) -> list[str]:
        return [tool["name"] for tool in self._tool_defs]
