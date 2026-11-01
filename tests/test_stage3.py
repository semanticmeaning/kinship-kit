"""Этап 3: экспорт/импорт, резервная копия, GEDCOM, поиск, MCP, сведения семьи, двуязычность."""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_kin import KIN, REPO, Base, run  # noqa: E402

sys.path.insert(0, str(REPO / "skills" / "kinship-kit"))
from kin import exchange, feedback, gedcom, mcp_server  # noqa: E402
from kin.store import Case, KinError  # noqa: E402


def demo(tmp: str, name: str = "demo") -> Path:
    case = Path(tmp) / name
    subprocess.run([sys.executable, str(REPO / "examples" / "demo" / "build_demo.py"), str(case)], check=True,
                   capture_output=True)
    return case


def unlock(root: Path) -> None:
    for p in root.rglob("*"):
        if p.is_file():
            p.chmod(0o644)


class TestExchange(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = demo(self.tmp.name)

    def tearDown(self):
        for d in Path(self.tmp.name).iterdir():
            if d.is_dir():
                unlock(d)
        self.tmp.cleanup()

    def test_export_import_roundtrip_idempotent_and_reviews_survive(self):
        out = Path(self.tmp.name) / "e.json"
        run("export", "--out", str(out), "--with-files", case=self.src)
        dst = Path(self.tmp.name) / "copy"
        run("init", str(dst), "--no-git")
        run("import", str(out), case=dst)
        a, b = Case(self.src), Case(dst)
        for reg in ("persons", "claims", "reviews", "tasks"):
            self.assertEqual(a.rows(reg), b.rows(reg), reg)
        self.assertEqual(b.config["root_person"], "P-0005")
        before = (dst / "registry" / "persons.csv").read_text(encoding="utf-8")
        self.assertIn("Проверка", run("import", str(out), "--dry-run", case=dst).stdout)
        self.assertEqual(before, (dst / "registry" / "persons.csv").read_text(encoding="utf-8"))
        rep = json.loads(run("import", str(out), "--json", case=dst).stdout)
        self.assertEqual(rep["added"], {})
        self.assertEqual(rep["journal_added"], 0)
        self.assertEqual(json.loads(run("audit", "--json", case=dst).stdout)["errors"], [])

    def test_import_conflict_writes_nothing(self):
        out = Path(self.tmp.name) / "e.json"
        run("export", "--out", str(out), case=self.src)
        data = json.loads(out.read_text(encoding="utf-8"))
        data["registers"]["persons"][0]["preferred_label"] = "Другое имя"
        data["registers"]["persons"].append({**data["registers"]["persons"][1], "person_id": "P-0099"})
        out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        res = run("import", str(out), case=self.src, ok=False)
        self.assertNotEqual(res.returncode, 0)
        self.assertNotIn("P-0099", Case(self.src).index("persons"))

    def test_export_outside_case_only(self):
        self.assertNotEqual(run("export", "--out", str(self.src / "x.json"), case=self.src, ok=False).returncode, 0)

    def test_backup_restore_with_git_and_tamper_detection(self):
        subprocess.run(["git", "-C", str(self.src), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.src), "-c", "user.name=t", "-c", "user.email=t@example.org", "commit",
                        "-qm", "demo"], check=True)
        arch = Path(self.tmp.name) / "b" / "demo.tar.gz"
        run("backup", "--out", str(arch), case=self.src)
        dst = Path(self.tmp.name) / "restored"
        run("restore", str(arch), str(dst))
        self.assertEqual(Case(dst).rows("claims"), Case(self.src).rows("claims"))
        log = subprocess.run(["git", "-C", str(dst), "log", "--oneline"], capture_output=True, text=True).stdout
        self.assertIn("demo", log)
        self.assertNotEqual(run("restore", str(arch), str(dst), ok=False).returncode, 0)  # не в непустую папку
        # подмена файла внутри архива
        bad = Path(self.tmp.name) / "b" / "bad.tar.gz"
        with tarfile.open(arch, "r:gz") as src, tarfile.open(bad, "w:gz") as out:
            for m in src.getmembers():
                f = src.extractfile(m) if m.isfile() else None
                data = f.read() if f else None
                if m.name == "case/registry/persons.csv":
                    data = data.replace("Ветлугин".encode(), "Подмена".encode())
                    m.size = len(data)
                out.addfile(m, io.BytesIO(data) if data is not None else None)
        res = run("restore", str(bad), str(Path(self.tmp.name) / "r2"), ok=False)
        self.assertIn("контрольные суммы", res.stderr)
        # обход пути
        evil = Path(self.tmp.name) / "b" / "evil.tar.gz"
        with tarfile.open(evil, "w:gz") as out:
            for name, data in (("MANIFEST.json", b'{"files":{}}'), ("case/../../escape.txt", b"x")):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                out.addfile(info, io.BytesIO(data))
        self.assertIn("Небезопасный", run("restore", str(evil), str(Path(self.tmp.name) / "r3"), ok=False).stderr)


class TestGedcom(unittest.TestCase):
    def test_dates(self):
        for e, g in (("1885-03-02", "2 MAR 1885"), ("1885-03", "MAR 1885"), ("1855~", "ABT 1855"), ("1882?", "EST 1882"),
                     ("1890/1905", "BET 1890 AND 1905"), ("../1917", "BEF 1917"), ("1900/..", "AFT 1900")):
            self.assertEqual(gedcom.edtf_to_ged(e), g)
            self.assertEqual(gedcom.ged_to_edtf(g)[0], e if not e.endswith("?") else e)
        self.assertEqual(gedcom.ged_to_edtf("@#DJULIAN@ 2 MAR 1885"), ("1885-03-02", "по юлианскому календарю (ст. ст.)"))
        self.assertEqual(gedcom.ged_to_edtf("около весны")[0], "")

    def test_roundtrip_reimport_and_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = demo(tmp)
            ged = Path(tmp) / "out" / "tree.ged"
            ged.parent.mkdir()
            run("gedcom", "export", "--out", str(ged), case=src)
            text = ged.read_text(encoding="utf-8")
            self.assertIn("2 DATE ABT 1855", text)
            self.assertIn("1 NAME Мария Фёдоровна /Сомова/", text)
            res = run("gedcom", "import", str(ged), case=src, ok=False)
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("этого же дела", res.stderr)
            pub = Path(tmp) / "out" / "pub.ged"
            run("gedcom", "export", "--out", str(pub), "--profile", "public", case=src)
            self.assertNotIn("Корнев", pub.read_text(encoding="utf-8"))
            dst = Path(tmp) / "new"
            run("init", str(dst), "--no-git")
            rep = json.loads(run("gedcom", "import", str(ged), "--json", case=dst).stdout)
            self.assertEqual((rep["persons_new"], rep["relationships"]), (10, 7))
            self.assertIn("уже импортирован", run("gedcom", "import", str(ged), case=dst).stdout)
            v2 = Path(tmp) / "out" / "v2" / "tree.ged"
            v2.parent.mkdir()
            v2.write_text(text.replace("0 TRLR", "0 @P9999@ INDI\n1 NAME Новый /Родственник/\n0 TRLR"), encoding="utf-8")
            rep = json.loads(run("gedcom", "import", str(v2), "--json", case=dst).stdout)
            self.assertEqual((rep["persons_new"], rep["persons_matched"], rep["claims"], rep["relationships"]), (1, 10, 0, 0))
            self.assertEqual(len(Case(dst).rows("persons")), 11)
            self.assertEqual(json.loads(run("audit", "--json", case=dst).stdout)["errors"], [])
            unlock(src)
            unlock(dst)


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
        # через настоящий stdio
        proc = subprocess.run([sys.executable, str(KIN), "mcp", "serve", "--case", str(self.case)],
                              input='{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n', capture_output=True, text=True)
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


if __name__ == "__main__":
    unittest.main()
