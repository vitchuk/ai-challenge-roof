from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "server" / "config.json"
DATA_DIR = PROJECT_ROOT / "server" / "data"

load_dotenv(PROJECT_ROOT / ".env")


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value


def deepseek_api_key() -> str | None:
    return get_env("DEEPSEEK_API_KEY")


def github_token() -> str | None:
    return get_env("GITHUB_PERSONAL_ACCESS_TOKEN") or get_env("GITHUB_TOKEN")


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def ollama_base_url() -> str:
    return (get_env("OLLAMA_BASE_URL") or load_config()["rag"]["ollama_base_url"]).rstrip("/")
