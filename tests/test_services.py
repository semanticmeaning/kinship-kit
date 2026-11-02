"""Службы: поиск, MCP-сервер, сведения семьи, обновления, английский интерфейс, совместимость с Python 3.10."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import KIN, REPO, Base, run, unlock  # noqa: E402

sys.path.insert(0, str(REPO / "skills" / "kinship-kit"))
from kin import feedback, mcp_server  # noqa: E402
from kin.store import Case, KinError  # noqa: E402


class TestFindMcpFeedbackLang(Base):
    def setUp(self):
        super().setUp()
        self.p = self.person("Ветлугина (Сомова) Мария Фёдоровна")

    def test_find_declension_and_yo(self):
        out = self.kin("find", "Сомовой").stdout
        self.assertIn(self.p, out)
        self.assertIn(self.p, self.kin("find", "федоровна").stdout)
        self.kin("person", "add", "--label", "Ещё Человек", "--living", "deceased", "--status", "candidate")
        self.assertIn("P-0002", self.kin("find", "человеку").stdout)  # индекс обновился сам

    def test_mcp_protocol(self):
        srv = mcp_server.Server(str(self.case))
        init = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")
        self.assertIsNone(srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        names = {t["name"] for t in srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
        self.assertTrue({"kin", "kin_status", "kin_find"} <= names)
        res = srv.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                          "params": {"name": "kin_show", "arguments": {"id": self.p}}})["result"]
        self.assertFalse(res["isError"])
        self.assertIn("Сомова", res["content"][0]["text"])
        res = srv.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                          "params": {"name": "kin", "arguments": {"args": ["site", "serve"]}}})["result"]
        self.assertTrue(res["isError"])
        self.assertEqual(srv.handle({"jsonrpc": "2.0", "id": 5, "method": "nope"})["error"]["code"], -32601)
        for args in (["--lang", "en", "site", "serve"], ["--case", str(self.case), "feedback", "serve"], ["mcp", "serve"]):
            res = srv.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                              "params": {"name": "kin", "arguments": {"args": args}}})["result"]
            self.assertTrue(res["isError"] and "Недоступно" in res["content"][0]["text"], args)
        # через настоящий stdio
        proc = subprocess.run([sys.executable, str(KIN), "mcp", "serve", "--case", str(self.case)],
                              input='{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n', capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertIn("kin_status", proc.stdout)
        self.assertIn("mcp_servers.kinship-kit", self.kin("mcp", "config", "--client", "codex").stdout)

    def test_feedback_flow(self):
        case = Case(self.case)
        with self.assertRaises(KinError):
            feedback.submit(case, {"text": "x", "author_name": "a", "consent": True})  # выключено
        self.kin("case", "set", "feedback.enabled=true")
        case = Case(self.case)
        with self.assertRaises(KinError):
            feedback.submit(case, {"text": "x", "author_name": "a", "consent": False})
        fr = feedback.submit(case, {"person_id": self.p, "author_name": "Тётя", "author_email": "aunt@example.org",
                                    "text": "Работала учительницей", "consent": True}, "10.0.0.1")
        self.assertIn(fr, self.kin("feedback", "list").stdout)
        self.assertNotIn("aunt@example.org", self.kin("feedback", "show", fr).stdout)
        self.assertNotEqual(self.kin("feedback", "accept", fr, ok=False).returncode, 0)  # нужен --by
        self.kin("feedback", "accept", fr, "--by", "Исследователь")
        text = "".join(p.read_text(encoding="utf-8", errors="replace") for p in (self.case / "registry").iterdir())
        text += "".join(p.read_text(encoding="utf-8", errors="replace") for p in (self.case / "sources").glob("*.md"))
        self.assertNotIn("aunt@example.org", text)
        self.assertIn("drafts/", (self.case / ".gitignore").read_text(encoding="utf-8"))
        self.assertEqual(json.loads(self.kin("audit", "--json").stdout)["errors"], [])
        self.kin("site", "build")
        self.assertTrue(json.loads((self.case / "site" / "private" / "tree.json").read_text(encoding="utf-8"))["meta"]["feedback"])
        self.kin("site", "build", "--profile", "public")
        self.assertFalse(json.loads((self.case / "site" / "public" / "tree.json").read_text(encoding="utf-8"))["meta"]["feedback"])

    def test_english_labels_keep_data(self):
        self.kin("add", "hypotheses", "--set", "statement=Данных нет, срок не указан", "--set", "status=open")
        out = run("--lang", "en", "status", case=self.case).stdout
        self.assertIn("Active hypotheses", out)
        self.assertIn("Данных нет, срок не указан", out)  # данные дела не переводятся
        self.assertIn("No errors or warnings.", run("--lang", "en", "audit", case=self.case).stdout)



class TestServiceRegressions(Base):
    """Найденное ревью: маскировка контактов в сведениях семьи, белый список MCP, неверные сообщения."""

    def test_feedback_contacts_masked_and_title_anonymous(self):
        self.kin("case", "set", "feedback.enabled=true")
        p = self.person("Ветлугин Сергей")
        fr = feedback.submit(Case(self.case), {"person_id": p, "author_name": "Дима <dima@example.org>", "consent": True,
                                               "text": "Пишите на dima@example.org или +7 900 111-22-33"})  # check_repo: allow
        self.kin("feedback", "accept", fr, "--by", "Исследователь")
        art = Case(self.case).rows("artifacts")[-1]
        self.assertNotIn("Дима", art["title"])
        everything = "".join(f.read_text(encoding="utf-8", errors="replace") for f in self.case.rglob("*")
                             if f.is_file() and "drafts" not in f.parts and ".git" not in f.parts)
        self.assertNotIn("dima@example.org", everything)
        self.assertNotIn("111-22-33", everything)

    def test_mcp_whitelist(self):
        srv = mcp_server.Server(str(self.case))
        other = str(Path(self.tmp.name) / "other")
        denied = [["restore", "x.zip", other], ["import", "x.json"], ["export", "--out", "x.json"], ["backup"],
                  ["site", "publish", "--to", other], ["hooks", "install"], ["upgrade", "apply"], ["init", other],
                  ["agents", "install", "--target", other], ["downloader", "build", "dvinaland", "--out", "x.js"],
                  ["gedcom", "export", "--out", "x.ged"], ["--case", other, "status"], ["status", "--case", other]]
        for args in denied:  # запрет именно белым списком, а не ошибкой разбора
            why = srv._blocked(args)
            self.assertTrue(why and "неверные аргументы" not in why, (args, why))
        self.assertIn("неверные аргументы", srv._blocked(["restore", "x.zip"]))  # неразобранное не запускается
        for args in (["status"], ["audit"], ["next"], ["find", "Сомова"], ["--case", str(self.case), "status"],
                     ["site", "build"], ["upgrade", "check"], ["downloader", "list"]):
            self.assertEqual(srv._blocked(args), "", args)
        self.assertTrue(srv._blocked(["status"], case=other))  # параметр case инструмента тоже не уводит в чужое дело
        # файлы источников — только из папки дела или KIN_MCP_INBOX (иначе агент заберёт в дело любой файл машины)
        secret = Path(self.tmp.name) / "id_rsa"
        secret.write_text("ключ", encoding="utf-8")
        inbox = self.case / "inbox"
        inbox.mkdir()
        (inbox / "скан.txt").write_text("скан", encoding="utf-8")
        link = inbox / "ссылка.txt"
        cases = [["source", "add", str(secret), "--title", "x"], ["source", "import-download", self.tmp.name]]
        try:
            link.symlink_to(secret)
            cases.append(["source", "add", str(link), "--title", "x"])
        except OSError:  # Windows без права на символические ссылки (WinError 1314) — эту часть не проверить
            pass
        for args in cases:
            self.assertIn("KIN_MCP_INBOX", srv._blocked(args), args)
        self.assertEqual(srv._blocked(["source", "add", str(inbox / "скан.txt"), "--title", "x"]), "")
        self.assertEqual(srv._blocked(["source", "add", "--url", "https://example.org/x", "--title", "x"]), "")
        with mock.patch.dict(os.environ, {"KIN_MCP_INBOX": self.tmp.name}):
            self.assertEqual(srv._blocked(["source", "add", str(secret), "--title", "x"]), "")
        res = srv.call("kin_status", {"case": other})
        self.assertTrue(res[1] and "Недоступно" in res[0])

    def test_mcp_invalid_messages(self):
        srv = mcp_server.Server(str(self.case))
        self.assertIsNone(srv.handle({"jsonrpc": "2.0", "id": 10, "result": {}}))
        self.assertEqual(srv.handle({"jsonrpc": "2.0", "id": 11})["error"]["code"], -32600)
        buf = io.StringIO()
        srv.serve(io.StringIO("[]\n5\n"), buf)
        self.assertEqual([json.loads(x)["error"]["code"] for x in buf.getvalue().splitlines()], [-32600, -32600])



class TestUpgrade(unittest.TestCase):
    def test_versions_consistent_and_changelog(self):
        from kin import __version__, updates
        skill = (REPO / "skills" / "kinship-kit" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(f'version: "{__version__}"', skill)
        self.assertIn(f'version = "{__version__}"', (REPO / "pyproject.toml").read_text(encoding="utf-8"))
        log = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## [{__version__}]", log)
        self.assertEqual(updates.changes_since(log, __version__), "")
        self.assertIn(f"[{__version__}]", updates.changes_since(log, "0.0.1"))
        self.assertGreater(updates.parse_version("v0.10.0"), updates.parse_version("0.9.9"))

    def test_check_with_fake_github_and_status_notice(self):
        from kin import updates
        with tempfile.TemporaryDirectory() as tmp:
            old_cache, old_get = updates.CACHE, updates._get
            updates.CACHE = Path(tmp) / "u.json"

            def fake(url):
                if "tags" in url:
                    return json.dumps([{"name": "v9.0.0"}, {"name": "v0.1.0"}, {"name": "latest"}]).encode()
                return b"## [9.0.0] - x\n- big change\n## [0.1.0] - y\n- old\n"
            updates._get = fake
            try:
                r = updates.check()
                self.assertTrue(r["newer"])
                self.assertEqual(r["latest"], "9.0.0")
                self.assertIn("big change", r["changes"])
                self.assertNotIn("old", r["changes"])
                self.assertIn("9.0.0", updates.notice())

                def offline(url):
                    raise OSError("нет сети")
                updates._get = offline
                with self.assertRaises(KinError):
                    updates.check()
            finally:
                updates.CACHE, updates._get = old_cache, old_get


class TestTranslations(unittest.TestCase):
    """Подписи интерфейса переводятся по точному совпадению с русской строкой (kin/i18n.py, PHRASES).
    Правка русской подписи без словаря молча вернула бы её по-русски в --lang en — этот тест не даёт так сделать."""

    def test_every_label_has_translation(self):
        import ast

        from kin.i18n import PHRASES
        kin_dir = REPO / "skills" / "kinship-kit" / "kin"
        trees = {f.name: ast.parse(f.read_text(encoding="utf-8")) for f in sorted(kin_dir.glob("*.py"))}
        labels, unknown = [], []
        for name, tree in trees.items():
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "t" and n.args:
                    a = n.args[0]
                    if isinstance(a, ast.Constant) and isinstance(a.value, str):
                        labels.append((a.value, f"{name}:{n.lineno}"))
                    elif (name, ast.unparse(a)) not in {("cli.py", "verb"), ("status.py", "label")}:
                        unknown.append(f"{name}:{n.lineno} t({ast.unparse(a)})")
        # подписи, которые приходят в t() через переменную
        for n in ast.walk(trees["cli.py"]):
            if isinstance(n, ast.FunctionDef) and n.name == "_print_row":
                labels += [(d.value, "cli.py:_print_row") for d in n.args.defaults if isinstance(d, ast.Constant)]
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_print_row" and len(n.args) > 2:
                labels.append((n.args[2].value, f"cli.py:{n.lineno}"))
        for n in ast.walk(trees["status.py"]):
            if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "labels" and isinstance(n.value, ast.Dict):
                labels += [(v.value, f"status.py:{n.lineno}") for v in n.value.values]
        self.assertEqual(unknown, [], "t() с переменной: добавьте её значения в этот тест")
        self.assertGreater(len(labels), 50)
        missing = sorted({f"{where}: {text!r}" for text, where in labels if text not in PHRASES})
        self.assertEqual(missing, [], "нет перевода в kin/i18n.py → PHRASES")


class TestWindowsEncoding(unittest.TestCase):
    def test_text_subprocess_output_has_explicit_encoding(self):
        """В Windows текстовый вывод программ читается в кодировке системы (cp1252/cp1251), а kin, git и node пишут UTF-8:
        без encoding= чтение падает в фоновом потоке и вывод молча становится None."""
        import ast
        bad = []
        roots = [REPO / "skills" / "kinship-kit", REPO / "examples", REPO / "tools", REPO / "tests"]
        for f in sorted(p for r in roots for p in r.rglob("*.py")):
            for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("run", "check_output", "Popen") \
                        and getattr(n.func.value, "id", "") == "subprocess":
                    kws = {k.arg: k.value for k in n.keywords}
                    textual = any(isinstance(kws.get(k), ast.Constant) and kws[k].value is True for k in ("text", "universal_newlines"))
                    if textual and "encoding" not in kws:
                        bad.append(f"{f.relative_to(REPO)}:{n.lineno}")
        self.assertEqual(bad, [], "добавьте encoding=\"utf-8\", errors=\"replace\"")


class TestPython310Compat(unittest.TestCase):
    def test_no_backslash_in_fstring_expressions(self):
        """Python 3.10–3.11: обратный слэш внутри {…} f-строки — синтаксическая ошибка (CI проверяет 3.10)."""
        import re
        rx = [re.compile(r'\bf"[^"]*\{[^}"]*\\'), re.compile(r"\bf'[^']*\{[^}']*\\")]
        bad = [f"{path.relative_to(REPO)}:{i}" for path in [*(REPO / "skills").rglob("*.py"), *(REPO / "tools").rglob("*.py")]
               for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if any(r.search(line) for r in rx)]
        self.assertEqual(bad, [])


class TestEnglishDemo(unittest.TestCase):
    def test_english_demo(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp) / "en"
            subprocess.run([sys.executable, str(REPO / "examples" / "demo" / "build_demo_en.py"), str(case)], check=True,
                           capture_output=True)
            out = run("status", case=case).stdout
            self.assertIn("NEXT STEP", out)
            self.assertEqual(json.loads(run("audit", "--json", case=case).stdout)["errors"], [])
            run("site", "build", "--profile", "public", case=case)
            pub = (case / "site" / "public" / "tree.json").read_text(encoding="utf-8")
            self.assertNotIn("Kornev", pub)
            self.assertNotIn("Anna Sergeevna", pub)
            unlock(case)
