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

    def test_import_rejects_paths_outside_sources(self):
        out = Path(self.tmp.name) / "e.json"
        run("export", "--out", str(out), case=self.src)
        data = json.loads(out.read_text(encoding="utf-8"))
        data["registers"]["artifacts"].append({**data["registers"]["artifacts"][0], "artifact_id": "A-0099",
                                               "file": "sources/../../../etc/hostname", "sha256": ""})
        data["case"]["evil_key"] = "x"
        out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        dst = Path(self.tmp.name) / "dst"
        run("init", str(dst), "--no-git")
        res = run("import", str(out), case=dst, ok=False)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("sources/", res.stderr)
        self.assertNotIn("A-0099", Case(dst).index("artifacts"))

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
        for args in (["--lang", "en", "site", "serve"], ["--case", str(self.case), "feedback", "serve"], ["mcp", "serve"]):
            res = srv.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                              "params": {"name": "kin", "arguments": {"args": args}}})["result"]
            self.assertTrue(res["isError"] and "Недоступно" in res["content"][0]["text"], args)
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


class TestStage3ReviewFixes(Base):
    def test_gedcom_public_leak_through_conc_is_caught(self):
        a = self.add_source("svid", group="g1")
        vis = self.person("Ветлугин Сергей Петрович", "deceased", "identity-confirmed", "--birth", "1921")
        self.person("Корнев Дмитрий Андреевич", "living", "family-reported")
        self.kin("claim", "add", "--type", "residence", "--subject", vis, "--sources", a, "--status", "single-source",
                 "--statement", "x" * 190 + "Корнев Дмитрий Андреевич, живой внук")
        res = self.kin("gedcom", "export", "--out", str(Path(self.tmp.name) / "p.ged"), "--profile", "public", ok=False)
        self.assertIn("скрытое сведение", res.stderr)

    def test_gedcom_conc_keeps_spaces_and_bad_date_rolls_back(self):
        text = "a" * 199 + " word"
        lines = gedcom._lines(1, "NOTE", text)
        node = gedcom.parse("0 @I1@ INDI\n" + "\n".join(lines) + "\n")[0]
        self.assertEqual(node["children"][0]["value"], text)
        ged = Path(self.tmp.name) / "bad.ged"
        ged.write_text("0 HEAD\n0 @I1@ INDI\n1 NAME Иван /Петров/\n0 @I2@ INDI\n1 NAME Пётр /Петров/\n1 BIRT\n"
                       "2 DATE ABT 99 JAN 1901\n0 @F1@ FAM\n1 HUSB @I1@\n1 WIFE @I1@\n0 TRLR\n", encoding="utf-8")
        before = {p.name: p.read_bytes() for p in (self.case / "registry").iterdir()}
        res = self.kin("gedcom", "import", str(ged), ok=False)
        if res.returncode != 0:  # если упало — ничего не осталось
            self.assertEqual(before, {p.name: p.read_bytes() for p in (self.case / "registry").iterdir()})
            self.assertEqual(list((self.case / "sources").glob("A-*")), [])
        else:  # дата не распознана — в тексте утверждения, без поля date; самосупружества нет
            self.assertFalse(any(r["person_a_id"] == r["person_b_id"] for r in Case(self.case).rows("relationships")))
            self.assertEqual(json.loads(self.kin("audit", "--json").stdout)["errors"], [])

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

    def test_json_import_rejects_malformed(self):
        out = Path(self.tmp.name) / "e.json"
        self.person("Иван")
        self.kin("export", "--out", str(out))
        self.assertNotEqual(self.kin("export", "--out", str(out), ok=False).returncode, 0)  # не перезаписывает
        data = json.loads(out.read_text(encoding="utf-8"))
        dst = Path(self.tmp.name) / "d"
        run("init", str(dst), "--no-git")
        for mutate in (lambda d: d["registers"]["persons"].append(dict(d["registers"]["persons"][0])),
                       lambda d: d["journal"].append("x"),
                       lambda d: d["registers"]["persons"][0].update(notes=5)):
            bad = json.loads(json.dumps(data))
            mutate(bad)
            f = Path(self.tmp.name) / "bad.json"
            f.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
            res = run("import", str(f), case=dst, ok=False)
            self.assertNotEqual(res.returncode, 0)
            self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(Case(dst).rows("persons"), [])

    def test_restore_rejects_unlisted_files(self):
        arch = Path(self.tmp.name) / "b.tar.gz"
        self.kin("backup", "--out", str(arch))
        self.assertNotEqual(self.kin("backup", "--out", str(arch), ok=False).returncode, 0)
        bad = Path(self.tmp.name) / "bad.tar.gz"
        with tarfile.open(arch, "r:gz") as src, tarfile.open(bad, "w:gz") as out:
            for m in src.getmembers():
                out.addfile(m, src.extractfile(m) if m.isfile() else None)
            info = tarfile.TarInfo("case/.git/hooks/post-checkout")
            info.size = 5
            info.mode = 0o755
            out.addfile(info, io.BytesIO(b"echo!"))
        res = run("restore", str(bad), str(Path(self.tmp.name) / "r"), ok=False)
        self.assertIn("лишний файл", res.stderr)

    def test_mcp_invalid_messages(self):
        srv = mcp_server.Server(str(self.case))
        self.assertIsNone(srv.handle({"jsonrpc": "2.0", "id": 10, "result": {}}))
        self.assertEqual(srv.handle({"jsonrpc": "2.0", "id": 11})["error"]["code"], -32600)
        buf = io.StringIO()
        srv.serve(io.StringIO("[]\n5\n"), buf)
        self.assertEqual([json.loads(x)["error"]["code"] for x in buf.getvalue().splitlines()], [-32600, -32600])


class TestGedcomAtomic(Base):
    def test_failure_midway_leaves_no_trace_and_retry_works(self):
        ged = Path(self.tmp.name) / "t.ged"
        ged.write_text("0 HEAD\n0 @I1@ INDI\n1 NAME Иван /Петров/\n1 BIRT\n2 DATE 1880\n0 @I2@ INDI\n1 NAME Пётр /Петров/\n"
                       "0 @F1@ FAM\n1 HUSB @I1@\n1 CHIL @I2@\n0 TRLR\n", encoding="utf-8")
        before = {p.name: p.read_bytes() for p in (self.case / "registry").iterdir()}
        journal = (self.case / "journal.jsonl").read_bytes()
        original = gedcom._add_rel

        def boom(*a, **k):
            raise RuntimeError("сбой посреди импорта")
        gedcom._add_rel = boom
        try:
            with self.assertRaises(RuntimeError):
                gedcom.import_file(Case(self.case), ged)
        finally:
            gedcom._add_rel = original
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.case / "registry").iterdir()})
        self.assertEqual(journal, (self.case / "journal.jsonl").read_bytes())
        self.assertEqual(list((self.case / "sources").glob("A-*")), [])
        rep = gedcom.import_file(Case(self.case), ged)  # повтор после сбоя проходит
        self.assertEqual((rep["persons_new"], rep["relationships"]), (2, 1))


class TestPublicationChoices(Base):
    def setUp(self):
        super().setUp()
        a = self.add_source("svid", group="g1")
        self.grand = self.person("Ветлугин Сергей Петрович", "deceased", "identity-confirmed", "--birth", "1921")
        self.user = self.person("Ветлугина Анна Сергеевна", "living", "identity-confirmed", "--birth", "1952")
        self.kin("claim", "add", "--type", "other", "--subject", self.grand, "--status", "hypothesis",
                 "--statement", "Со слов внучки Анны Сергеевны")

    def test_default_fails_redact_masks(self):
        self.assertNotEqual(self.kin("site", "build", "--profile", "public", ok=False).returncode, 0)
        self.kin("case", "set", "privacy.on_leak=redact")
        self.kin("site", "build", "--profile", "public")
        tree = (self.case / "site" / "public" / "tree.json").read_text(encoding="utf-8")
        self.assertIn("Со слов внучки [скрыто]", tree)
        self.assertNotIn("Анн", tree)
        self.assertNotEqual(self.kin("case", "set", "privacy.on_leak=maybe", ok=False).returncode, 0)

    def test_public_living_needs_human_decision(self):
        self.assertIn("--by", self.kin("case", "set", "privacy.public_living=allow", ok=False).stderr)
        self.kin("case", "set", "privacy.public_living=allow", "--by", "Автор Дела")
        self.kin("site", "build", "--profile", "public")
        tree = json.loads((self.case / "site" / "public" / "tree.json").read_text(encoding="utf-8"))
        self.assertIn(self.user, {p["id"] for p in tree["persons"]})
        self.assertIn("human-decision", (self.case / "journal.jsonl").read_text(encoding="utf-8"))
        self.kin("update", self.user, "publication=deny")  # личный запрет сильнее общего решения
        self.kin("site", "build", "--profile", "public", ok=False)  # теперь её имя в тексте — снова утечка

    def test_case_theme(self):
        self.kin("site", "theme", "init")
        (self.case / "theme" / "custom.css").write_text(":root{--accent:#123456}", encoding="utf-8")
        self.kin("update", "C-0001", "statement=Нейтральный текст")
        self.kin("site", "build")
        out = self.case / "site" / "private"
        self.assertIn('href="custom.css"', (out / "index.html").read_text(encoding="utf-8"))
        self.assertTrue((out / "custom.css").is_file())
        self.kin("site", "theme", "init", "--full")
        page = self.case / "theme" / "index.html"
        page.write_text(page.read_text(encoding="utf-8").replace("<title>Древо</title>", "<title>Наш род</title>"),
                        encoding="utf-8")
        self.assertIn("+<title>Наш род</title>", self.kin("site", "theme", "diff").stdout)
        self.kin("site", "build")
        self.assertIn("Наш род", (out / "index.html").read_text(encoding="utf-8"))


class TestUpgrade(unittest.TestCase):
    def test_versions_consistent_and_changelog(self):
        from kin import __version__, updates
        skill = (REPO / "skills" / "kinship-kit" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(f'version: "{__version__}"', skill)
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


class TestPython310Compat(unittest.TestCase):
    def test_no_backslash_in_fstring_expressions(self):
        """Python 3.10–3.11: обратный слэш внутри {…} f-строки — синтаксическая ошибка (CI проверяет 3.10)."""
        import re
        rx = [re.compile(r'\bf"[^"]*\{[^}"]*\\'), re.compile(r"\bf'[^']*\{[^}']*\\")]
        bad = [f"{path.relative_to(REPO)}:{i}" for path in [*(REPO / "skills").rglob("*.py"), *(REPO / "tools").rglob("*.py")]
               for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if any(r.search(line) for r in rx)]
        self.assertEqual(bad, [])


class TestTreeData(unittest.TestCase):
    def test_demo_tree_format_docs_and_privacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = demo(tmp)
            run("site", "build", case=case)
            run("site", "build", "--profile", "public", case=case)
            priv = json.loads((case / "site" / "private" / "tree.json").read_text(encoding="utf-8"))
            pub = json.loads((case / "site" / "public" / "tree.json").read_text(encoding="utf-8"))
            for key in ("persons", "edges", "claims", "arts", "gens", "lines", "families", "feedback", "meta"):
                self.assertIn(key, priv)
            edges = {e["id"]: e for e in priv["edges"]}
            self.assertEqual(edges["R-0005"]["lv"], "doc2")          # Сомов → Мария: две группы
            self.assertEqual(edges["C-0008"]["t"], "identity")       # «возможно, одно лицо» из утверждения
            self.assertEqual(edges["C-0009"]["lv"], "research")      # гипотеза отцовства
            self.assertIn("Ветлугин", {f["key"] for f in priv["families"]})
            p2 = next(p for p in priv["persons"] if p["id"] == "P-0002")
            self.assertTrue(p2["direct"] and p2["b"]["ok"] and p2["d"]["conflict"])
            # файлы источников: приватно — все использованные, публично — только scan_publication=allow
            priv_docs = {p.parent.name for p in (case / "site" / "private" / "docs").rglob("*") if p.is_file()}
            pub_docs = {p.parent.name for p in (case / "site" / "public" / "docs").rglob("*") if p.is_file()}
            self.assertIn("A-0004", priv_docs)       # извещение (семейный архив) — только приватно
            self.assertNotIn("A-0004", pub_docs)
            self.assertIn("A-0001", pub_docs)        # метрика с разрешением на публикацию
            self.assertEqual(pub["arts"]["A-0002"]["urls"], ["https://example.org/olhov-metriki/55102"])
            self.assertEqual(pub["feedback"], [])
            self.assertTrue(all(c["next"] == "" for c in pub["claims"]))  # рабочие планы — не публикуются
            self.assertNotIn("P-0005", json.dumps(pub, ensure_ascii=False))
            unlock(case)
