# MCP-сервер

Для ИИ-клиентов без доступа к командной строке. Сервер — тонкая обёртка над CLI: каждый вызов — процесс `kin`
с той же проверкой схемы, блокировкой и журналом. Только стандартная библиотека Python, транспорт stdio.

Инструменты: `kin_status`, `kin_next`, `kin_audit`, `kin_show`, `kin_find`, `kin_schema` (чтение) и `kin` — команда
CLI массивом аргументов (запись).

**Белый список.** Через `kin` доступны только команды, которые читают дело или пишут внутрь него: источники, люди,
утверждения, связи, задачи, гипотезы, поиски, ревью, запросы, аудит, `publish`, `site build`, `site theme`, `migrate`,
`downloader list|build` (скрипт — на экран), `upgrade check`, `feedback list|show|accept|reject`, `doctor`.
Только человеком в терминале: `init`, `setup`, `export`, `import`, `backup`, `restore`, `gedcom`, `site publish`,
`site serve`, `feedback serve`, `hooks install`, `agents install`, `upgrade apply`, `mcp`. Ключи с путём вне дела
(`--out`, `--to`, `--target`, `--publish-to`, `--dir`) отклоняются у любой команды.

**Одно дело на сервер.** Если сервер запущен с `--case` (или `KIN_CASE`), другое дело через `--case` в аргументах или
параметр `case` инструмента не открыть. Без `--case` сервер работает с тем делом, которое назовёт клиент, — так
лучше не настраивать.

**Файлы источников.** `source add <файл>` и `source import-download <папка>` через MCP берут файлы только из папки
дела (например, `<дело>/inbox/`) и из папок, перечисленных в переменной `KIN_MCP_INBOX` (через `:`, в Windows — `;`),
с учётом символических ссылок. Иначе агент мог бы забрать в дело любой файл машины (ключи, пароли) и вместе с делом
отправить его в git. Источник по ссылке (`--url`) без файла добавляется без ограничений.

Настройка (печатает фрагмент с путями этой установки):
```bash
kin mcp config --client claude-code   --case ~/kinship-cases/ivanovy   # .mcp.json проекта или: claude mcp add …
kin mcp config --client claude-desktop --case ~/kinship-cases/ivanovy  # claude_desktop_config.json
kin mcp config --client codex          --case ~/kinship-cases/ivanovy  # ~/.codex/config.toml
```
Форматы конфигурации сверены с документацией клиентов на 2026-11-01.
