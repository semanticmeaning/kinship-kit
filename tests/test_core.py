"""Ядро: даты, хранилище, доказательность, состояние исследования, публикация и приватность, блокировка, doctor, демо."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO, Base, run  # noqa: E402
from kin import edtf, publish  # noqa: E402
from kin.store import Case, KinError, init_case  # noqa: E402


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
        text = "".join(p.read_text(encoding="utf-8") for p in out.rglob("*")
                       if p.is_file() and p.suffix in (".html", ".json", ".txt", ".css", ".js"))  # иконки — двоичные
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


class TestAuditConsistency(Base):
    """Эвристики согласованности (предупреждения) — по опыту ревью схемы реального дела."""

    def warns(self, text):
        return [w for w in self.audit()["warnings"] if text in w]

    def rel(self, a, kind, b, *extra):
        return json.loads(self.kin("rel", "add", a, kind, b, *extra, "--json").stdout)["relationship_id"]

    def claim(self, *args):
        return json.loads(self.kin("claim", "add", *args, "--json").stdout)["claim_id"]

    def test_people_and_relationships(self):
        a = self.add_source("svid", group="g1")
        father = self.person("Ветлугин Павел Иванович", "deceased", "identity-confirmed", "--sex", "m", "--birth", "1880", "--death", "1910")
        son = self.person("Ветлугин Иван Афанасьевич", "deceased", "identity-confirmed", "--sex", "m", "--birth", "1925")
        wife = self.person("Сомов Пётр Ильич", "deceased", "identity-confirmed", "--sex", "m", "--birth", "1882")
        cand = self.person("Ветлугин Кандидат", "deceased", "candidate", "--sex", "m")
        r1 = self.rel(father, "parent-of", son, "--sources", a, "--status", "single-source")
        r2 = self.rel(father, "spouse-of", wife, "--sources", a, "--status", "single-source")
        r3 = self.rel(cand, "sibling-of", son, "--sources", a, "--status", "single-source")
        self.assertTrue(self.warns(f"{r1}: отчество"))           # Афанасьевич при отце Павле
        self.assertTrue(self.warns(f"{r1}: {son} родился(ась) позже смерти"))  # 1925 при смерти отца в 1910
        self.assertTrue(self.warns(f"{r2}: супруги одного пола"))
        self.assertTrue(self.warns(f"{r3}: связь single-source, а {cand} ещё candidate"))
        young = self.person("Ветлугин Внук Павлович", "deceased", "identity-confirmed", "--sex", "m", "--birth", "1885")
        r4 = self.rel(father, "parent-of", young, "--sources", a, "--status", "single-source")
        self.assertTrue(self.warns(f"{r4}: {young} родился(ась) раньше, чем {father} исполнилось 12"))
        self.assertFalse(self.warns(f"{r4}: отчество"))           # Павлович при отце Павле — без тревоги
        self.assertEqual(self.audit()["errors"], [])               # только предупреждения

    def test_claims(self):
        a = self.add_source("svid", group="g1")
        m = self.person("Ветлугин Иван", "deceased", "identity-confirmed", "--sex", "m", "--birth", "1880")
        f = self.person("Ветлугина Мария", "deceased", "identity-confirmed", "--sex", "f")
        x = self.person("Ветлугин Пётр", "deceased", "candidate", "--sex", "m")
        c1 = self.claim("--type", "identity", "--subject", f"{m};{f};{x}", "--statement", "Возможно, одно лицо", "--status", "hypothesis")
        self.assertTrue(self.warns(f"{c1}: identity на 3 лиц"))
        self.assertTrue(self.warns(f"{c1}: identity объединяет мужчину и женщину"))
        self.rel(m, "parent-of", x, "--sources", a, "--status", "single-source")
        c2 = self.claim("--type", "parentage", "--subject", f"{m};{x}", "--statement", "Иван — отец Петра", "--status", "hypothesis")
        self.assertTrue(self.warns(f"{c2}: гипотеза, а связь"))
        c3 = self.claim("--type", "birth", "--subject", m, "--date", "1890", "--statement", "Родился в 1890 году в Кленовке",
                        "--sources", a, "--status", "single-source")
        self.assertTrue(self.warns(f"{c3}: дата 1890 не сходится с карточкой"))
        c4 = self.claim("--type", "residence", "--subject", m, "--statement", "Жил в деревне Кленовка до войны", "--status", "hypothesis")
        c5 = self.claim("--type", "residence", "--subject", f, "--statement", "Жил в  деревне Кленовка до войны", "--status", "hypothesis")
        self.assertTrue(self.warns(f"{c4}, {c5}: одинаковый текст"))

    def test_stale_reference_to_merged_person(self):
        a = self.add_source("svid", group="g1")
        p1 = self.person("Ветлугин Иван", "deceased", "identity-confirmed")
        p2 = self.person("Ветлугин Иван Петрович", "deceased", "candidate")
        c = self.claim("--type", "residence", "--subject", p1, "--statement", "Жил в Кленовке", "--sources", a,
                       "--status", "single-source", "--rationale", f"Как и у {p2}, двор 14", "--next", f"Сверить с {p2}")
        self.kin("person", "merge", p2, p1, "--force", "--by", "Тест", "--reason", "одно лицо")
        self.assertTrue(self.warns(f"{c}.rationale: упоминается {p2}, слитый с {p1}"))
        self.assertTrue(self.warns(f"{c}.next_action: упоминается {p2}"))

    def test_family_tree_counts_only_near_living(self):
        doc = self.add_source("svid", group="g1")
        story = Path(self.tmp.name) / "story.txt"
        story.write_text("рассказ семьи", encoding="utf-8")
        oral = json.loads(self.kin("source", "add", str(story), "--title", "Рассказ", "--kind", "family-oral",
                                   "--group", "fam", "--json").stdout)["artifact_id"]
        me = self.person("Ветлугина Анна", "living", "identity-confirmed", "--birth", "1952")
        dad = self.person("Ветлугин Сергей", "deceased", "identity-confirmed", "--birth", "1921")
        grand = self.person("Ветлугин Пётр", "deceased", "identity-confirmed", "--birth", "1885")
        near = self.claim("--type", "parentage", "--subject", f"{dad};{me}", "--statement", "Сергей — отец Анны",
                          "--sources", f"{doc};{oral}", "--status", "corroborated", "--rationale", "свидетельство и рассказ")
        self.rel(dad, "parent-of", me, "--claims", near, "--status", "corroborated", "--rationale", "две группы")
        far = self.claim("--type", "parentage", "--subject", f"{grand};{dad}", "--statement", "Пётр — отец Сергея",
                         "--sources", f"{doc};{oral}", "--status", "corroborated", "--rationale", "метрика и рассказ")
        self.assertFalse(self.warns(f"{near}: corroborated держится на семейном дереве"))
        self.assertTrue(self.warns(f"{far}: corroborated держится на семейном дереве"))
        self.kin("update", far, "status=single-source")
        self.assertFalse(self.warns(f"{far}: независимых групп"))  # семейный рассказ о деде не считается второй группой


class TestLockAndRollback(Base):
    def _lock_file(self, content: str, age: float = 0) -> Path:
        lock = self.case / ".kin" / "write.lock"
        lock.parent.mkdir(exist_ok=True)
        lock.write_text(content, encoding="utf-8")
        if age:
            t = time.time() - age
            os.utime(lock, (t, t))
        return lock

    def test_dead_owner_lock_is_taken_at_once(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        self._lock_file(f"{dead.pid} 2026-01-01T00:00:00 {socket.gethostname()} t0")
        with Case(self.case).lock(timeout=0.5):
            pass

    def test_live_owner_keeps_old_lock(self):
        """В том числе в Windows: проверка процесса через OpenProcess, а не по возрасту файла."""
        lock = self._lock_file(f"{os.getpid()} 2026-01-01T00:00:00 {socket.gethostname()} t0", age=3600)
        with self.assertRaises(KinError) as err, Case(self.case).lock(timeout=0.3):
            pass
        self.assertIn(str(os.getpid()), str(err.exception))
        self.assertTrue(lock.exists())

    def test_unverifiable_or_foreign_owner_is_never_taken_by_age(self):
        from kin import store
        self._lock_file(f"{os.getpid()} 2026-01-01T00:00:00 {socket.gethostname()} t0", age=3600)
        with mock.patch.object(store, "_pid_alive", return_value=None), self.assertRaises(KinError), \
                Case(self.case).lock(timeout=0.3):
            pass
        self._lock_file("12345 2026-01-01T00:00:00 another-host t0", age=3600)
        with self.assertRaises(KinError) as err, Case(self.case).lock(timeout=0.3):
            pass
        self.assertIn("another-host", str(err.exception))

    def test_ownerless_lock_falls_back_to_age(self):
        for content in ("", "12345 2026-01-01T00:00:00"):  # пустой после сбоя; формат до 0.5.0
            self._lock_file(content, age=3600)
            with Case(self.case).lock(timeout=0.5):
                pass
        self._lock_file("")
        with self.assertRaises(KinError), Case(self.case).lock(timeout=0.3):
            pass

    def test_release_keeps_someone_elses_lock(self):
        lock = self.case / ".kin" / "write.lock"
        with Case(self.case).lock():
            lock.write_text(f"{os.getpid()} 2026-01-01T00:00:00 {socket.gethostname()} other", encoding="utf-8")
        self.assertTrue(lock.exists(), "чужая блокировка удалена при выходе")
        lock.unlink()
        with Case(self.case).lock():
            pass
        self.assertFalse(lock.exists())

    def test_rollback_restores_files_without_temp_leftovers(self):
        case = Case(self.case)
        persons = case.path("persons")
        before = persons.read_bytes()
        with self.assertRaises(RuntimeError), case.transaction():
            persons.write_text("испорчено", encoding="utf-8")
            raise RuntimeError("сбой посреди операции")
        self.assertEqual(persons.read_bytes(), before)
        self.assertEqual(list(self.case.rglob("*.rollback.tmp")), [])


class TestDoctor(Base):
    def test_merge_conflict_in_registry_is_reported(self):
        self.person("Иван Тестов")
        self.assertIn("✓ Реестры без следов конфликта", self.kin("doctor", ok=False).stdout)
        with open(self.case / "registry" / "persons.csv", "a", encoding="utf-8") as fh:
            fh.write("<<<<<<< HEAD\nP-0002,x\n=======\nP-0002,y\n>>>>>>> other\n")
        res = self.kin("doctor", ok=False)
        self.assertEqual(res.returncode, 1)
        self.assertIn("Конфликт в persons.csv", res.stdout)


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
