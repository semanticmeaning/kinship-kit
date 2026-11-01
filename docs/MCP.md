# MCP-сервер

Для ИИ-клиентов без доступа к командной строке. Сервер — тонкая обёртка над CLI: каждый вызов — процесс `kin`
с той же проверкой схемы, блокировкой и журналом. Только стандартная библиотека Python, транспорт stdio.

Инструменты: `kin_status`, `kin_next`, `kin_audit`, `kin_show`, `kin_find`, `kin_schema` (чтение) и `kin` — любая команда
CLI массивом аргументов (запись). Через MCP недоступны блокирующие службы (`site serve`, `feedback serve`).

Настройка (печатает фрагмент с путями этой установки):
```bash
kin mcp config --client claude-code   --case ~/kinship-cases/ivanovy   # .mcp.json проекта или: claude mcp add …
kin mcp config --client claude-desktop --case ~/kinship-cases/ivanovy  # claude_desktop_config.json
kin mcp config --client codex          --case ~/kinship-cases/ivanovy  # ~/.codex/config.toml
```
Форматы конфигурации сверены с документацией клиентов на 2026-11-01.
