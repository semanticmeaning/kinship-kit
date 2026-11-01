"""MCP-сервер kinship-kit (stdio, JSON-RPC 2.0, только стандартная библиотека) — тонкая обёртка над CLI kin.

Запуск: kin mcp serve [--case DIR]   (или KIN_CASE). Настройка клиентов: kin mcp config --client claude-code|claude-desktop|codex.
Каждый вызов инструмента — отдельный процесс kin: та же проверка схемы, блокировка дела и журнал, что и в CLI.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from . import __version__

KIN_PY = Path(__file__).resolve().parent.parent / "kin.py"
SUPPORTED = ["2025-06-18", "2025-03-26", "2024-11-05"]
BLOCKED = {("site", "serve"): "site serve блокирует сервер — смотрите сайт командой в терминале",
           ("mcp",): "вложенный MCP-сервер не нужен",
           ("feedback", "serve"): "служба формы запускается в терминале или как сервис"}
INSTRUCTIONS = ("kinship-kit: дело генеалогического исследования. Начинайте с kin_status и kin_next. "
                "Изменения — инструментом kin (args — как в командной строке, например "
                "[\"claim\",\"add\",\"--type\",\"birth\",…]); указывайте исполнителя: \"--as\", \"<роль>\". "
                "Правила доказательности, ревью и приватности — в навыке kinship-kit (SKILL.md). "
                "Согласие на платное и решения человека (--by) принимает только человек. Первый шаг нового пользователя — "
                "сначала спросить фамилию, название дела и автора коммитов, затем kin setup --yes … (автор — явно).")


def _tool(name: str, description: str, props: dict | None = None, required: list | None = None, readonly=True) -> dict:
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": props or {}, "required": required or []},
            "annotations": {"readOnlyHint": readonly}}


CASE_PROP = {"case": {"type": "string", "description": "Папка дела (если сервер запущен без --case)"}}
TOOLS = [
    _tool("kin_status", "Состояние исследования: гипотезы, задачи, отрицательные поиски, ревью, запросы, следующий шаг.", CASE_PROP),
    _tool("kin_next", "Ранжированный список следующих задач с причинами и недоступные задачи (нужно согласие, лимит).", CASE_PROP),
    _tool("kin_audit", "Аудит целостности и доказательности дела (ошибки и предупреждения).", CASE_PROP),
    _tool("kin_show", "Запись по ID (P-, A-, C-, R-, M-, H-, T-, S-, V-, Q-, L-) и ссылки на неё.",
          {**CASE_PROP, "id": {"type": "string"}}, ["id"]),
    _tool("kin_find", "Полнотекстовый поиск по делу (имена в любом падеже, утверждения, источники, поиски).",
          {**CASE_PROP, "query": {"type": "string"}, "register": {"type": "string"}}, ["query"]),
    _tool("kin_schema", "Поля и словари реестров (как правильно записывать).",
          {"register": {"type": "string"}}),
    _tool("kin", "Любая команда CLI kin (запись тоже). args — массив аргументов, как в терминале, без слова kin. "
                 "Пример: [\"search\",\"add\",\"--task\",\"T-0001\",\"--source\",\"…\",\"--result\",\"not-found\",\"--as\",\"Archive Researcher\"].",
          {**CASE_PROP, "args": {"type": "array", "items": {"type": "string"}}}, ["args"], readonly=False),
]


class Server:
    def __init__(self, case: str | None):
        self.case = case or os.environ.get("KIN_CASE") or ""

    def run_kin(self, args: list[str], case: str | None = None) -> tuple[str, bool]:
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args) or not args:
            return "args должен быть непустым массивом строк", True
        for prefix, why in BLOCKED.items():
            if tuple(args[:len(prefix)]) == prefix:
                return f"Недоступно через MCP: {why}", True
        cmd = [sys.executable, str(KIN_PY)]
        chosen = case or self.case
        if chosen and "--case" not in args:
            cmd += ["--case", chosen]
        try:
            res = subprocess.run(cmd + args, capture_output=True, text=True, encoding="utf-8", timeout=300,
                                 stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return "kin: превышено время выполнения (300 с)", True
        text = (res.stdout or "") + (("\n" + res.stderr) if res.stderr else "")
        return text.strip() or "(нет вывода)", res.returncode != 0

    def call(self, name: str, a: dict) -> tuple[str, bool]:
        case = a.get("case")
        if name == "kin_status":
            return self.run_kin(["status"], case)
        if name == "kin_next":
            return self.run_kin(["next"], case)
        if name == "kin_audit":
            return self.run_kin(["audit"], case)
        if name == "kin_show":
            return self.run_kin(["show", str(a.get("id", ""))], case)
        if name == "kin_find":
            args = ["find", str(a.get("query", ""))]
            if a.get("register"):
                args += ["--register", str(a["register"])]
            return self.run_kin(args, case)
        if name == "kin_schema":
            return self.run_kin(["schema"] + ([str(a["register"])] if a.get("register") else []), case)
        if name == "kin":
            return self.run_kin(a.get("args"), case)
        return f"Нет инструмента {name}", True

    def handle(self, msg: dict) -> dict | None:
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:
            return None  # уведомление (notifications/initialized и др.)
        if method == "initialize":
            requested = (msg.get("params") or {}).get("protocolVersion")
            return self._ok(mid, {"protocolVersion": requested if requested in SUPPORTED else SUPPORTED[0],
                                  "capabilities": {"tools": {"listChanged": False}},
                                  "serverInfo": {"name": "kinship-kit", "version": __version__},
                                  "instructions": INSTRUCTIONS})
        if method == "ping":
            return self._ok(mid, {})
        if method == "tools/list":
            return self._ok(mid, {"tools": TOOLS})
        if method == "tools/call":
            params = msg.get("params") or {}
            text, is_error = self.call(params.get("name", ""), params.get("arguments") or {})
            return self._ok(mid, {"content": [{"type": "text", "text": text}], "isError": is_error})
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Метод не поддерживается: {method}"}}

    @staticmethod
    def _ok(mid, result) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def serve(self, stdin=None, stdout=None) -> None:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                         "error": {"code": -32700, "message": "Parse error"}}) + "\n")
                stdout.flush()
                continue
            batch = msg if isinstance(msg, list) else [msg]
            for m in batch:
                try:
                    reply = self.handle(m) if isinstance(m, dict) else None
                except Exception as e:  # сервер не должен падать от одного запроса
                    reply = {"jsonrpc": "2.0", "id": m.get("id") if isinstance(m, dict) else None,
                             "error": {"code": -32603, "message": f"Внутренняя ошибка: {e}"}}
                if reply is not None:
                    stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
                    stdout.flush()


def client_config(client: str, case: str) -> str:
    """Фрагмент настроек клиента MCP (проверено по документации на 2026-11-01)."""
    args = [str(KIN_PY), "mcp", "serve"] + (["--case", case] if case else [])
    if client == "codex":
        return ("# ~/.codex/config.toml (или .codex/config.toml доверенного проекта)\n"
                "[mcp_servers.kinship-kit]\n"
                f"command = {json.dumps(sys.executable)}\n"
                f"args = {json.dumps(args, ensure_ascii=False)}\n")
    entry = {"mcpServers": {"kinship-kit": {"command": sys.executable, "args": args}}}
    where = (".mcp.json в папке проекта (Claude Code спросит подтверждение) или: claude mcp add kinship-kit -- "
             + " ".join([sys.executable] + args)) if client == "claude-code" else \
        "claude_desktop_config.json (Настройки → Разработчик → Изменить конфигурацию)"
    return f"# {where}\n" + json.dumps(entry, ensure_ascii=False, indent=2) + "\n"
