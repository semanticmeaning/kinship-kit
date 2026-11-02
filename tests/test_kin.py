"""Тесты kinship-kit: только стандартная библиотека (python3 -m unittest discover -s tests)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skills" / "kinship-kit"
KIN = SKILL / "kin.py"
sys.path.insert(0, str(SKILL))

from kin import edtf, publish  # noqa: E402
from kin.store import Case, KinError, init_case  # noqa: E402


def run(*args, case: Path | None = None, ok: bool = True) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(KIN), *args]
    if case is not None:
        cmd += ["--case", str(case)]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if ok and res.returncode != 0:
        raise AssertionError(f"kin {' '.join(args)} → {res.returncode}\n{res.stdout}\n{res.stderr}")
    return res


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.case = Path(self.tmp.name) / "case"
        run("init", str(self.case), "--title", "Тест", "--no-git")
        self.doc = Path(self.tmp.name) / "doc.txt"
        self.doc.write_text("синтетический документ", encoding="utf-8")

    def tearDown(self):
        for p in self.case.rglob("*"):
            if p.is_file():
                p.chmod(0o644)
        self.tmp.cleanup()

    def kin(self, *args, ok=True):
        return run(*args, case=self.case, ok=ok)

    def add_source(self, name="doc", group=None, text=None):
        f = Path(self.tmp.name) / f"{name}.txt"
        f.write_text(text or f"документ {name}", encoding="utf-8")
        args = ["source", "add", str(f), "--title", name, "--kind", "document-image", "--json"]
        if group:
            args += ["--group", group]
        return json.loads(self.kin(*args).stdout)["artifact_id"]

    def person(self, label, living="deceased", status="identity-probable", *extra):
        out = self.kin("person", "add", "--label", label, "--living", living, "--status", status, *extra, "--json")
        return json.loads(out.stdout)["person_id"]

    def audit(self):
        return json.loads(self.kin("audit", "--json", ok=False).stdout)


class TestDates(unittest.TestCase):
    def test_formats(self):
        for good in ["", "1885", "1885-03", "1885-03-02", "1855~", "1882?", "1890/1905", "../1917", "1900/.."]:
            self.assertTrue(edtf.is_valid(good), good)
        for bad in ["ок. 1855", "1880 / 1882", "1885-13", "1905/1890", "../..", "1885.03.02"]:
            self.assertFalse(edtf.is_valid(bad), bad)

    def test_human(self):
        self.assertEqual(edtf.human("1855~"), "ок. 1855")
        self.assertEqual(edtf.human("1885-03-02"), "02.03.1885")
        self.assertEqual(edtf.human("../1917"), "не позже 1917")
        self.assertEqual(edtf.human("1890/1905"), "1890–1905")
        self.assertEqual(edtf.sort_year("../1835"), 1835)


class TestStorage(Base):
    def test_init_layout(self):
        for p in ["case.json", "registry/persons.csv", "registry/searches.csv", "sources", "AGENTS.md", "journal.jsonl"]:
            self.assertTrue((self.case / p).exists(), p)
        self.assertIn(".kin/", (self.case / ".gitignore").read_text(encoding="utf-8"))

    def test_init_refused_inside_kit_repo(self):
        if not (REPO / ".git").exists():
            self.skipTest("нет git-репозитория набора")
        with self.assertRaises(KinError):
            init_case(REPO / "examples" / "should-not-exist", "x", git=False)

    def test_source_immutable_and_dedup(self):
        aid = self.add_source("a")
        row = Case(self.case).index("artifacts")[aid]
        f = self.case / row["file"]
        self.assertTrue(f.is_file())
        self.assertEqual(len(row["sha256"]), 64)
        # повторная регистрация того же файла — отказ (нет размножения дубликатов)
        same = Path(self.tmp.name) / "a.txt"
        self.assertNotEqual(self.kin("source", "add", str(same), ok=False).returncode, 0)
        # изменение оригинала — ошибка аудита
        f.chmod(0o644)
        f.write_text("подмена", encoding="utf-8")
        self.assertTrue(any("изменён" in e for e in self.audit()["errors"]))
        # файл и sha256 через update не меняются
        self.assertNotEqual(self.kin("update", aid, "sha256=" + "0" * 64, ok=False).returncode, 0)

    def test_schema_validation(self):
        bad = [
            ("person", "add", "--label", "X", "--living", "maybe", "--status", "candidate"),
            ("person", "add", "--label", "X", "--living", "deceased", "--status", "candidate", "--birth", "ок. 1855"),
            ("claim", "add", "--type", "birth", "--subject", "P-0099", "--statement", "x", "--status", "hypothesis"),
        ]
        for args in bad:
            res = self.kin(*args, ok=False)
            self.assertNotEqual(res.returncode, 0, args)
        self.assertEqual(Case(self.case).rows("persons"), [])

    def test_journal_and_actor(self):
        self.kin("person", "add", "--label", "Иванов Иван", "--living", "deceased", "--status", "candidate",
                 "--as", "Data Curator")
        entry = json.loads((self.case / "journal.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((entry["actor"], entry["op"], entry["id"]), ("Data Curator", "add", "P-0001"))

    def test_parallel_writers_get_unique_ids(self):
        def add(i):
            return run("person", "add", "--label", f"Агент {i}", "--living", "deceased", "--status", "candidate",
                       case=self.case)
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(add, range(16)))
        ids = [r["person_id"] for r in Case(self.case).rows("persons")]
        self.assertEqual(len(ids), 16)
        self.assertEqual(len(set(ids)), 16)


class TestEvidence(Base):
    def test_corroboration_needs_two_independent_groups(self):
        a1 = self.add_source("metrika", group="g1")
        a2 = self.add_source("index", group="g1")  # индекс той же записи
        p = self.person("Петров Пётр")
        self.kin("claim", "add", "--type", "birth", "--subject", p, "--statement", "Родился 1885", "--date", "1885",
                 "--sources", f"{a1};{a2}", "--status", "corroborated", "--rationale", "две записи")
        self.assertTrue(any("≥2 независимых" in e for e in self.audit()["errors"]))
        a3 = self.add_source("ispoved", group="g2")
        self.kin("update", "C-0001", "--append", f"artifact_ids={a3}")
        self.assertEqual(self.audit()["errors"], [])

    def test_relationship_requires_source(self):
        p1, p2 = self.person("Отец"), self.person("Сын")
        self.kin("rel", "add", p1, "parent-of", p2, "--status", "single-source")
        self.assertTrue(any("без источников" in e for e in self.audit()["errors"]))
        self.kin("update", "R-0001", "status=hypothesis")
        self.assertEqual(self.audit()["errors"], [])

    def test_contradiction_keeps_both_versions(self):
        a1, a2 = self.add_source("izv", group="g1"), self.add_source("kniga", group="g2")
        p = self.person("Петров Пётр")
        self.kin("claim", "add", "--type", "death", "--subject", p, "--statement", "Погиб 1941", "--date", "1941-11",
                 "--sources", a1, "--against", a2, "--status", "contradicted")
        self.kin("claim", "add", "--type", "death", "--subject", p, "--statement", "Умер 1942", "--date", "1942-02",
                 "--sources", a2, "--against", a1, "--status", "contradicted")
        self.assertTrue(any("расходятся" in w for w in self.audit()["warnings"]))
        self.kin("update", "C-0002", "competing_claim_ids=C-0001")
        result = self.audit()
        self.assertFalse(any("расходятся" in w for w in result["warnings"]))
        data, _ = publish.build(Case(self.case), "public")
        self.assertEqual({c["date"] for c in data["claims"]}, {"1941-11", "1942-02"})
        status = json.loads(self.kin("status", "--json").stdout)
        self.assertEqual(len(status["open_contradictions"]), 2)

    def test_ambiguous_identity_not_merged_without_basis(self):
        a1, a2 = self.add_source("m1880", group="g1"), self.add_source("p1903", group="g2")
        p1 = self.person("Иван Петров (1880)", "deceased", "candidate")
        p2 = self.person("Иван Петров (1903)", "unknown", "candidate")
        self.kin("claim", "add", "--type", "identity", "--subject", f"{p1};{p2}", "--statement", "Возможно одно лицо",
                 "--sources", f"{a1};{a2}", "--status", "hypothesis")
        res = self.kin("person", "merge", p2, p1, ok=False)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Нет основания", res.stderr)
        self.assertEqual(Case(self.case).index("persons")[p2]["status"], "candidate")
        # с основанием — слияние, исходные записи сохраняются
        self.kin("update", "C-0001", "status=corroborated", "rationale=две независимые группы")
        # слияние — значимый вывод: нужно независимое ревью identity-утверждения
        self.assertIn("ревью", self.kin("person", "merge", p2, p1, ok=False).stderr)
        self.kin("review", "request", "C-0001", "--for", "merge")
        self.kin("review", "submit", "V-0001", "--verdict", "passed", "--checked", f"{a1};{a2}",
                 "--findings", "Обе записи прочитаны", "--as", "Evidence Reviewer")
        self.assertIn("решение человека", self.kin("person", "merge", p2, p1, ok=False).stderr)  # P-2 возможно жив
        self.kin("review", "decide", "V-0001", "--by", "Тестовый Пользователь")
        self.kin("person", "merge", p2, p1)
        case = Case(self.case)
        self.assertEqual(case.resolve_person(p2), p1)
        self.assertIn(p2, case.index("claims")["C-0001"]["subject_person_ids"])
        self.assertEqual(self.audit()["errors"], [])
        self.kin("person", "unmerge", p2, "--reason", "найден второй Иван")
        self.assertEqual(Case(self.case).resolve_person(p2), p2)

    def test_hypothesis_rejection_needs_counter_evidence(self):
        self.kin("add", "hypotheses", "--set", "statement=Кузьма — отец Ивана", "--set", "status=rejected",
                 "--set", "reopen_conditions=новые метрики")
        self.assertTrue(any("отсутствие находки не опровержение" in e for e in self.audit()["errors"]))


class TestResearchState(Base):
    def test_status_restores_state_in_new_process(self):
        p = self.person("Ветлугин Иван")
        self.kin("add", "hypotheses", "--set", "statement=Отец — Кузьма", "--set", f"person_ids={p}", "--set", "status=open")
        self.kin("add", "searches", "--set", "date=2026-10-20", "--set", "source=Архив, ф. 15",
                 "--set", "query=рождение Ивана", "--set", "period=1853/1857", "--set", "result=not-found",
                 "--set", "disallowed_conclusions=нельзя считать, что не родился", "--set", "repeat_when=найдутся дубликаты")
        self.kin("add", "tasks", "--set", "hypothesis_id=H-0001", "--set", "goal=Запросить дубликаты",
                 "--set", "status=blocked", "--set", "constraints=платно")
        self.kin("add", "tasks", "--set", "hypothesis_id=H-0001", "--set", "goal=Ревизская сказка 1850",
                 "--set", "status=ready", "--set", "priority=1")
        s = json.loads(self.kin("status", "--json").stdout)  # новый процесс: только данные дела
        self.assertEqual([h["id"] for h in s["active_hypotheses"]], ["H-0001"])
        self.assertEqual(s["checked_negative"][0]["repeat_when"], "найдутся дубликаты")
        self.assertEqual(s["tasks"]["blocked"][0]["id"], "T-0001")
        self.assertEqual(s["next"]["id"], "T-0002")

    def test_negative_search_needs_disallowed_conclusions(self):
        self.kin("add", "searches", "--set", "date=2026-10-20", "--set", "source=Архив", "--set", "result=not-found")
        self.assertTrue(any("disallowed_conclusions" in w for w in self.audit()["warnings"]))


class TestPublication(Base):
    def setUp(self):
        super().setUp()
        a = self.add_source("svid", group="g1")
        self.grand = self.person("Ветлугин Сергей Петрович", "deceased", "identity-confirmed", "--birth", "1921")
        self.user = self.person("Ветлугина Анна Сергеевна", "living", "identity-confirmed", "--birth", "1952")
        self.unknown = self.person("Ветлугин Олег Сергеевич", "unknown", "candidate", "--birth", "1960")
        self.kin("rel", "add", self.grand, "parent-of", self.user, "--sources", a, "--status", "single-source")
        self.kin("case", "set", f"root_person={self.user}")

    def test_public_hides_living_and_possibly_living(self):
        data, hidden = publish.build(Case(self.case), "public")
        ids = {p["id"] for p in data["persons"]}
        self.assertEqual(ids, {self.grand})
        self.assertEqual(set(hidden), {self.user, self.unknown})
        self.assertEqual(data["meta"]["root"], self.grand)
        self.assertEqual(data["meta"]["root_gen_offset"], -1)
        self.assertEqual(data["relationships"], [])
        priv, _ = publish.build(Case(self.case), "private")
        self.assertIn(self.user, {p["id"] for p in priv["persons"]})

    def test_site_build_has_no_private_data(self):
        self.kin("site", "build", "--profile", "public")
        out = self.case / "site" / "public"
        text = "".join(p.read_text(encoding="utf-8") for p in out.rglob("*") if p.is_file())
        for secret in ("Анна Сергеевна", "Олег Сергеевич", self.user, self.unknown, "1952", "sha256"):
            self.assertNotIn(secret, text, secret)
        tree = json.loads((out / "tree.json").read_text(encoding="utf-8"))
        self.assertTrue(all(p["notes"] == "" and p["merge"] == "" for p in tree["persons"]))  # служебные заметки не выводятся
        self.assertIn("Сергей Петрович", text)

    def _leaks(self, statement):
        self.kin("claim", "add", "--type", "other", "--subject", self.grand, "--status", "hypothesis",
                 "--statement", statement)
        res = self.kin("site", "build", "--profile", "public", ok=False)
        self.assertFalse((self.case / "site" / "public" / "tree.json").exists())
        return res

    def test_leak_of_living_name_in_any_case_breaks_build(self):
        res = self._leaks("Со слов внучки Анны Сергеевны")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("скрытое сведение", res.stderr)

    def test_leak_checker_catches_realistic_variants(self):
        hidden = self.person("Иванова (Сидорова) Мария Фёдоровна", "living", "identity-confirmed")
        terms = publish.forbidden_terms(Case(self.case), {hidden: "", self.user: ""})
        rx = [__import__("re").compile(t) for t in terms]
        for text in ("Мария Сидорова, урождённая", "Иванова, Мария", "Марии Федоровны", "у Сидоровой Марии",
                     "Мария, в девичестве Сидорова"):
            self.assertTrue(any(r.search(publish._fold(text)) for r in rx), text)
        for text in ("Сергей Петрович", "Мария Петровна Ветлугина"):
            self.assertFalse(any(r.search(publish._fold(text)) for r in rx), text)
        for phone in ("8-916-123-45-67", "(495) 123-45-67", "7 916 123 45 67", "+7 (916) 123-45-67"):  # check_repo: allow
            self.assertTrue(publish.PHONE_RE.search(phone), phone)
        for not_phone in ("02.03.1885", "1885-03-02 1921-07-10", "ф. 15, оп. 2, д. 41, л. 7"):
            self.assertFalse(publish.PHONE_RE.search(not_phone), not_phone)

    def test_family_source_owner_not_public(self):
        a = json.loads(self.kin("source", "add", "--url", "https://disk.example.org/s/abc", "--title", "Письмо",
                                "--kind", "letter", "--repository", "Архив семьи Ветлугиных", "--group", "l1",
                                "--json").stdout)["artifact_id"]
        self.kin("claim", "add", "--type", "residence", "--subject", self.grand, "--statement", "Жил в Кленовке",
                 "--sources", a, "--status", "single-source")
        data, _ = publish.build(Case(self.case), "public")
        src = next(s for s in data["sources"] if s["id"] == a)
        self.assertEqual((src["repository"], src["url"]), ("", ""))
        self.assertIsNone(data["meta"]["hidden_persons"])

    def test_merge_cannot_bypass_via_update(self):
        p = self.person("Дубль")
        res = self.kin("update", p, "status=duplicate", f"merged_into={self.grand}", "merge_rationale=x", ok=False)
        self.assertNotEqual(res.returncode, 0)

    def test_stale_public_build_removed_on_failure(self):
        self.kin("site", "build", "--profile", "public")
        tree = self.case / "site" / "public" / "tree.json"
        self.assertIn(self.grand, tree.read_text(encoding="utf-8"))
        self.kin("update", self.grand, "publication=deny")
        self.kin("rel", "add", self.grand, "sibling-of", self.unknown, "--status", "single-source")  # ошибка аудита
        self.assertNotEqual(self.kin("site", "build", "--profile", "public", ok=False).returncode, 0)
        self.assertFalse(tree.exists())
        self.assertFalse((self.case / "publish" / "public" / "data.json").exists())

    def test_leak_of_phone_breaks_build(self):
        res = self._leaks("Сведения от родственника, тел. +7 900 123-45-67")  # check_repo: allow
        self.assertIn("телефон", res.stderr)

    def test_no_false_leak_for_visible_person(self):
        self.kin("claim", "add", "--type", "other", "--subject", self.grand, "--status", "hypothesis",
                 "--statement", "Сергей Петрович служил в 1941")
        self.kin("site", "build", "--profile", "public")

    def test_publication_deny_hides_everywhere(self):
        self.kin("update", self.grand, "publication=deny")
        priv, _ = publish.build(Case(self.case), "private")
        self.assertNotIn(self.grand, {p["id"] for p in priv["persons"]})

    def test_build_stops_on_audit_errors(self):
        p = self.person("X")
        self.kin("rel", "add", self.grand, "sibling-of", p, "--status", "single-source")
        self.assertNotEqual(self.kin("site", "build", ok=False).returncode, 0)


class TestPrivacyEdgeCases(Base):
    def test_open_ended_birth_is_hidden(self):
        p = self.person("Ветлугин Олег", "unknown", "candidate", "--birth", "1900/..")
        q = self.person("Ветлугин Павел", "unknown", "candidate", "--birth", "1890/1910")
        _, hidden = publish.build(Case(self.case), "public")
        self.assertIn(p, hidden)
        self.assertNotIn(q, hidden)

    def test_duplicate_of_hidden_person_is_leak_checked(self):
        main = self.person("Корнев Дмитрий Андреевич", "living", "identity-confirmed")
        dup = self.person("Корнев Дмитрий (анкета)", "living", "candidate")
        self.kin("person", "merge", dup, main, "--force", "--reason", "тест", "--by", "Тестовый Пользователь")
        terms = publish.forbidden_terms(Case(self.case), dict.fromkeys([main, dup], ""))
        import re
        self.assertTrue(any(re.search(t, publish._fold(f"id {dup}")) for t in terms))
        self.assertTrue(any(re.search(t, publish._fold("Корнева Дмитрия")) for t in terms))

    def test_serve_refuses_private_on_external_host(self):
        res = self.kin("site", "serve", "--host", "0.0.0.0", "--i-know-its-public", ok=False)
        self.assertNotEqual(res.returncode, 0)

    def test_serve_rejects_foreign_host_header(self):
        import http.client
        import socket
        import threading
        import time
        from kin import site as site_mod
        self.kin("site", "build")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        threading.Thread(target=site_mod.serve, args=(Case(self.case), "private", port), daemon=True).start()
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)

        def get(host):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", "/tree.json", headers={"Host": host})
            r = c.getresponse()
            r.read()
            return r.status
        self.assertEqual(get(f"127.0.0.1:{port}"), 200)
        self.assertEqual(get(f"evil.example:{port}"), 421)


class TestDemo(unittest.TestCase):
    """Сценарий переносимости: демо-дело строится с нуля только командами kin."""

    def test_demo_case_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp) / "demo"
            res = subprocess.run([sys.executable, str(REPO / "examples" / "demo" / "build_demo.py"), str(case)],
                                 capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(res.returncode, 0, res.stderr)
            audit = json.loads(run("audit", "--json", case=case).stdout)
            self.assertEqual(audit["errors"], [])
            status = json.loads(run("status", "--json", case=case).stdout)
            self.assertEqual(status["next"]["id"], "T-0001")
            run("site", "build", "--profile", "public", case=case)
            run("site", "build", "--profile", "private", case=case)
            pub = (case / "site" / "public" / "tree.json").read_text(encoding="utf-8")
            for secret in ("Корнев", "Анна Сергеевна", "P-0005", "P-0006"):
                self.assertNotIn(secret, pub)
            tree = json.loads(pub)
            gens = {p["id"]: p["gen"] for p in tree["persons"]}
            self.assertEqual((gens["P-0004"], gens["P-0002"], gens["P-0009"]), (-1, -2, -4))
            for p in case.rglob("*"):
                if p.is_file():
                    p.chmod(0o644)


if __name__ == "__main__":
    unittest.main()
