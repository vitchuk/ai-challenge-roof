from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from . import config, rag_pipeline

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…»)])\s+(?=[А-ЯЁA-Z«\"(„\d])")
HEADING_RE = re.compile(r"(?m)^#{1,6}\s+(.+)$")

RAG_SYSTEM_PROMPT = (
    "Ты — ассистент по документации проекта. Отвечай ТОЛЬКО на основе предоставленного контекста из базы знаний.\n\n"
    "Правила:\n"
    "1. Используй только факты из контекста. Не придумывай сведения, которых там нет.\n"
    "2. После ключевых утверждений приводи дословные цитаты из контекста отдельной строкой в формате:\n"
    "> [chunk_id] текст цитаты (до 200 символов)\n"
    "3. Каждый ответ завершай разделом «Источники:» со списком использованных фрагментов:\n"
    "- [chunk_id] название — путь к файлу\n"
    "4. Если в контексте нет ответа, ответь ровно фразой "
    "\"Ответить на вопрос, опираясь на базу знаний, невозможно. Или переформулируйте вопрос.\" "
    "и заверши строкой \"Источники: не найдены (нет релевантных фрагментов в базе знаний)\".\n"
    "5. Отвечай на русском языке, кратко и по делу."
)

NO_ANSWER_PHRASE = "Ответить на вопрос, опираясь на базу знаний, невозможно. Или переформулируйте вопрос."


def estimate_tokens(text: str, chars_per_token: float) -> int:
    return max(1, round(len(text) / chars_per_token))


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_SPLIT_RE.split(text) if part.strip()]


def _hard_split(sentence: str, max_chars: int) -> list[str]:
    if len(sentence) <= max_chars:
        return [sentence]
    words = sentence.split()
    pieces: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            pieces.append(current)
            current = word
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _units(text: str, params: dict) -> list[tuple[str, int]]:
    cpt = params["chars_per_token"]
    max_tokens = params["max_tokens"]
    units: list[tuple[str, int]] = []
    for sentence in split_sentences(text):
        tokens = estimate_tokens(sentence, cpt)
        if tokens > max_tokens:
            for piece in _hard_split(sentence, int(max_tokens * cpt)):
                units.append((piece, estimate_tokens(piece, cpt)))
        else:
            units.append((sentence, tokens))
    return units


def _windows(units: list[tuple[str, int]], params: dict) -> list[list[tuple[str, int]]]:
    min_tokens = params["min_tokens"]
    max_tokens = params["max_tokens"]
    overlap = params["overlap_tokens"]
    target = max(min_tokens, (min_tokens + max_tokens) // 2)

    chunks: list[list[tuple[str, int]]] = []
    current: list[tuple[str, int]] = []
    current_tokens = 0
    added = False

    for sentence, tokens in units:
        current.append((sentence, tokens))
        current_tokens += tokens
        added = True
        if current_tokens >= target:
            chunks.append(current)
            carry: list[tuple[str, int]] = []
            carry_tokens = 0
            for s2, t2 in reversed(current):
                if carry_tokens + t2 > overlap:
                    break
                carry.insert(0, (s2, t2))
                carry_tokens += t2
            current = carry
            current_tokens = carry_tokens
            added = False

    if added and current:
        if chunks:
            last_tokens = sum(t for _, t in chunks[-1])
            if current_tokens < min_tokens and last_tokens + current_tokens <= max_tokens:
                chunks[-1] = chunks[-1] + current
            else:
                chunks.append(current)
        else:
            chunks.append(current)

    return [chunk for chunk in chunks if chunk]


def chunk_document(doc: dict, params: dict) -> list[dict]:
    text = doc["text"].strip()
    if not text:
        return []
    units = _units(text, params)
    total = sum(tokens for _, tokens in units)
    if total <= params["min_chunk_tokens"]:
        return []
    raw = [units] if total <= params["max_tokens"] else _windows(units, params)

    chunks: list[dict] = []
    for index, group in enumerate(raw):
        body = " ".join(sentence for sentence, _ in group).strip()
        tokens = sum(tokens for _, tokens in group)
        if not body:
            continue
        chunks.append(
            {
                "file": doc["path"],
                "title": doc["title"],
                "chunk_index": index,
                "tokens": tokens,
                "text": body,
            }
        )
    return chunks


def build_chunks(documents: list[dict], params: dict) -> list[dict]:
    chunks: list[dict] = []
    counter = 0
    for doc in documents:
        for chunk in chunk_document(doc, params):
            counter += 1
            chunk["chunk_id"] = f"{params['strategy']}_{counter:03d}"
            chunks.append(chunk)
    return chunks


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


async def embed_texts(texts: list[str], params: dict) -> list[list[float]]:
    if not texts:
        return []
    base_url = config.ollama_base_url()
    batch_size = int(params.get("embed_batch_size", 16))
    timeout = float(params.get("embed_timeout_sec", 300))
    vectors: list[list[float]] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            try:
                response = await client.post(
                    f"{base_url}/api/embed",
                    json={"model": params["embedding_model"], "input": batch},
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise RuntimeError(
                    f"Не удалось получить эмбеддинги от Ollama ({base_url}): {exc}"
                ) from exc
            embeddings = response.json().get("embeddings")
            if not embeddings:
                raise RuntimeError("Ollama вернул пустой список эмбеддингов")
            vectors.extend(_normalize(vector) for vector in embeddings)
    return vectors


def _embed_input(chunk: dict) -> str:
    return f"{chunk['file']} — {chunk['title']}\n{chunk['text']}"


def index_path() -> Any:
    params = config.load_config()["rag"]
    return config.resolve_path(params["output_dir"]) / "index.json"


def index_exists() -> bool:
    return index_path().exists()


def load_index() -> dict:
    with index_path().open("r", encoding="utf-8") as f:
        return json.load(f)


async def build_index(documents: list[dict]) -> dict:
    params = config.load_config()["rag"]
    chunks = build_chunks(documents, params)
    if not chunks:
        raise RuntimeError("В документации не найдено ни одного фрагмента для индексации")
    vectors = await embed_texts([_embed_input(chunk) for chunk in chunks], params)
    digest = hashlib.sha256(
        "".join(f"{doc['path']}:{len(doc['text'])}" for doc in documents).encode("utf-8")
    ).hexdigest()
    index = {
        "strategy": params["strategy"],
        "description": (
            "fixed-чанкинг: скользящее окно по предложениям, целевой размер "
            f"{params['min_tokens']}–{params['max_tokens']} токенов, overlap {params['overlap_tokens']}"
        ),
        "params": params,
        "source": {
            "files": [doc["path"] for doc in documents],
            "files_count": len(documents),
            "sha256": digest,
        },
        "embedding": {
            "provider": "ollama",
            "base_url": config.ollama_base_url(),
            "model": params["embedding_model"],
            "dim": len(vectors[0]) if vectors else 0,
        },
        "built_at": datetime.now(timezone.utc).isoformat(),
        "vectors": vectors,
        "chunks": chunks,
    }
    path = index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    return index


def _cosine(query: list[float], vector: list[float]) -> float:
    return sum(a * b for a, b in zip(query, vector))


async def search(query: str, top_k: int) -> list[dict]:
    if not index_exists():
        raise RuntimeError("Индекс RAG-базы не построен")
    index = load_index()
    params = index.get("params") or config.load_config()["rag"]
    query_vector = (await embed_texts([query], params))[0]
    scored = [
        (round(_cosine(query_vector, vector), 4), chunk)
        for vector, chunk in zip(index["vectors"], index["chunks"])
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    hits: list[dict] = []
    for score, chunk in scored[: max(1, top_k)]:
        hits.append({**chunk, "score": score})
    return hits


def index_status() -> dict:
    from . import state

    status = {
        "strategy": "fixed",
        "exists": index_exists(),
        "build_status": state.BUILD["status"],
        "error": state.BUILD["error"],
        "chunks": state.BUILD["chunks"],
        "files": state.BUILD["files"],
        "built_at": state.BUILD["built_at"],
        "embedding_model": None,
        "dim": None,
    }
    if index_exists():
        try:
            index = load_index()
            status["built_at"] = index.get("built_at")
            status["chunks"] = len(index.get("chunks", []))
            status["files"] = index.get("source", {}).get("files_count", 0)
            status["embedding_model"] = index.get("embedding", {}).get("model")
            status["dim"] = index.get("embedding", {}).get("dim")
            if status["build_status"] in ("idle",):
                status["build_status"] = "ready"
        except Exception as exc:  # noqa: BLE001
            status["error"] = f"Не удалось прочитать индекс: {exc}"
    return status


def _format_context(hits: list[dict]) -> str:
    blocks = [
        f"[{hit['chunk_id']}] {hit['file']} — {hit['title']}\n{hit['text']}"
        for hit in hits
    ]
    return "\n\n---\n\n".join(blocks)


async def build_rag_context(
    question: str,
    history: list[dict],
    top_k: int,
) -> tuple[list[dict], dict, str | None]:
    hits, debug = await rag_pipeline.run_retrieval(question, history, top_k, search)
    context = _format_context(hits) if hits else None
    return hits, debug, context
