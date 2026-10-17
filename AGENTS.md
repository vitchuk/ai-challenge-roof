# AGENTS.md

Навигатор по проекту для AI-агентов.

## Карта документации

- `README.md` — обзор, требования, запуск.
- `server/app/rag.py` — fixed-чанкинг, эмбеддинги Ollama, JSON-индекс, косинусный поиск, RAG-контекст.
- `server/app/rag_pipeline.py` — стратегия Query Rewrite (переписывание вопроса) и retrieval.
- `server/app/repo_service.py` — текущая ветка, список ветвей, дерево файлов, граф ветвей (Mermaid), кэш.
- `server/app/indexer.py` — получение документов через GitHub MCP и сборка индекса.
- `server/app/mcp_client.py` — stdio-клиент MCP (официальный Python SDK), схемы инструментов.
- `server/app/chat.py` — маршрутизация `/help` (RAG) и обычных сообщений, агентный цикл с инструментами MCP, цитаты.
- `server/app/chat_store.py` — SQLite: чаты и сообщения (время ответа, источники, вызовы инструментов); таблица `pr_seen` — «просмотрено» для PR-центра.
- `server/app/pr_service.py` — GitHub REST: список/детали PR, diff, комментарий AI-ревью, check-runs, `workflow_dispatch`.
- `server/scripts/pr_review.py` — AI-ревью PR целевого репо: diff + RAG (доки+код) → комментарий и вердикт; запускается из GitHub Actions.
- `server/config.json` — все настройки, кроме секретов (в т.ч. `agent.tools_whitelist`, `repo`).
- `client/src/` — Vue-клиент: `views/ChatView.vue`, `views/SettingsView.vue`, `components/` (в т.ч. `RepoTreeView.vue`, `BranchGraph.vue`, `ToolCallsPanel.vue`, `PrPanel.vue`).

## Запуск и проверки

- Полный запуск: `start.bat` (создаёт venv, ставит зависимости, скачивает MCP-бинарник).
- Только бэкенд: `.venv\Scripts\python -m uvicorn app.main:app --port 8000` из `server/`.
- Клиент: `npm run dev` из `client/`; проверка типов и сборка: `npm run build`.
- Переиндексация: кнопка в «Настройках» или `POST /api/rag/rebuild`.
- Статус: `GET /api/status`.
- Локальный dry-run AI-ревью PR (нужны Ollama и `DEEPSEEK_API_KEY`):
  `server\scripts\pr_review.py --repo-dir <клон> --base <sha> --head <sha> --pr-number <n> --repo owner/name --dry-run --index-dir <tmp>`.

## Gotchas

- На PATH `python` — заглушка Microsoft Store, печатающая `Python ` без версии. Используйте `py`
  или `.venv\Scripts\python.exe`.
- PowerShell 5.1 читает `.ps1` без BOM как ANSI — не кладите кириллицу в `.ps1`/`.bat`.
- `mcp` SDK v2: клиент — `from mcp import ClientSession` и `mcp.client.stdio`; не импортируйте
  `mcp.server.fastmcp`.
- DeepSeek (OpenAI-совместимый API) не принимает параметр `top_k` генерации — не отправляйте его.
  `Top_K` в этом проекте — это число фрагментов RAG, а не параметр сэмплирования.
- DeepSeek `tool_choice="required"` не поддерживается в thinking-режиме (400) — в `llm.py` есть
  fallback на `auto`; `deepseek-chat` — это non-thinking режим.
- Mermaid `gitGraph`: ветка `main` существует неявно — нельзя эмитить `branch main`
  (ошибка «Trying to create an existing branch»); см. `repo_service._build_mermaid`.
- `github-mcp-server` требует `GITHUB_PERSONAL_ACCESS_TOKEN`; без него открывается браузерный OAuth
  (для публичных репозиториев чтение при этом всё равно работает).
- `github-mcp-server` v2: `get_file_contents` принимает `ref` (не `branch`); `get_repository_tree`
  живёт в toolset `git` (подключается через `--toolsets repos,context,git`); поля моделей SDK — snake_case.
- `@grapoza/vue-tree` не объявляет `types` в `exports` — путь к типам прописан в `tsconfig.json`
  (`paths`), стили импортируются как `@grapoza/vue-tree/css`.
- Mermaid подключается динамическим `import()` только при отрисовке графа ветвей.
- Секреты только в `.env` (не в git); клиенту они не отдаются.
- Данные о PR идут напрямую через GitHub REST (`pr_service.py`), минуя MCP; для кнопки «Перезапустить
  ревью» PAT должен иметь право `actions:write` (классический PAT — scope `repo`).
- Опрос PR инициирует клиент (`App.vue`), период — `pr.poll_interval_sec` (сек); «просмотрено»
  фиксирует `GET /api/prs/{n}` в таблицу `pr_seen`; первый опрос при пустой `pr_seen` — тихий baseline.
- `ai-review.yml` (в целевом репо) чекаутит этот репо по `ref:` — сейчас `day32`, менять при переносе на стабильную ветку.
- `server/data/` и `tools/` в gitignore.
