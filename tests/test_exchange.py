"""Обмен данными: экспорт/импорт, резервная копия, GEDCOM."""
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
from helpers import REPO, Base, demo, run, unlock  # noqa: E402

sys.path.insert(0, str(REPO / "skills" / "kinship-kit"))
from kin import gedcom  # noqa: E402
from kin.store import Case  # noqa: E402


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
        log = subprocess.run(["git", "-C", str(dst), "log", "--oneline"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
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



class TestExchangeRegressions(Base):
    """Найденное ревью: утечки и откат в GEDCOM, испорченный импорт и архив."""

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
