"""Процесс исследования: setup, миграции, next, жизненный цикл задач и гипотез, ревью, поиск без повторов, роли, публикация."""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import KIN, REPO, Base, run  # noqa: E402

sys.path.insert(0, str(REPO / "skills" / "kinship-kit"))
from kin.store import Case  # noqa: E402

V1 = json.loads((REPO / "skills" / "kinship-kit" / "kin" / "schemas" / "v1.json").read_text(encoding="utf-8"))


class TestMigration(Base):
    def make_v1(self):
        reg = self.case / "registry"
        for _name, spec in V1["registers"].items():
            with open(reg / spec["file"], "w", encoding="utf-8", newline="") as fh:
                csv.writer(fh, lineterminator="\n").writerow([f["name"] for f in spec["fields"]])
        for extra in ("reviews.csv", "requests.csv"):
            (reg / extra).unlink()
        tasks = [f["name"] for f in V1["registers"]["tasks"]["fields"]]
        with open(reg / "tasks.csv", "a", encoding="utf-8", newline="") as fh:
            row = {k: "" for k in tasks}
            row.update(task_id="T-0001", goal="Старая задача, v1", status="ready", priority="1")
            csv.DictWriter(fh, tasks, lineterminator="\n").writerow(row)
            row.update(task_id="T-0002", goal="Платный запрос", constraints="Платный запрос — нужно согласие", priority="")
            csv.DictWriter(fh, tasks, lineterminator="\n").writerow(row)
        cfg = json.loads((self.case / "case.json").read_text(encoding="utf-8"))
        cfg["schema_version"] = 1
        (self.case / "case.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    def test_v1_case_requires_and_survives_migration(self):
        self.make_v1()
        res = self.kin("status", ok=False)
        self.assertIn("kin migrate", res.stderr)
        self.assertIn("v1→v2", self.kin("migrate", "--dry-run").stdout)
        self.kin("migrate")
        case = Case(self.case)
        self.assertEqual(case.config["schema_version"], 2)
        t = case.index("tasks")["T-0001"]
        self.assertEqual((t["goal"], t["priority"], t["cost"]), ("Старая задача, v1", "1", ""))
        self.assertEqual(case.rows("reviews"), [])
        self.assertEqual(case.index("tasks")["T-0002"]["cost"], "paid")  # платность из текста v1 сохранена
        self.assertTrue(list((self.case / ".kin").glob("backup-v1-*/registry/tasks.csv")))
        self.assertEqual(json.loads(self.kin("audit", "--json").stdout)["errors"], [])
        self.assertIn("актуальна", self.kin("migrate").stdout)

    def test_migration_stops_on_unexpected_header(self):
        self.make_v1()
        p = self.case / "registry" / "persons.csv"
        p.write_text(p.read_text(encoding="utf-8").replace("notes", "my_notes"), encoding="utf-8")
        self.assertNotEqual(self.kin("migrate", ok=False).returncode, 0)
        self.assertEqual(json.loads((self.case / "case.json").read_text(encoding="utf-8"))["schema_version"], 1)


class TestTasksAndNext(Base):
    def test_next_ranks_and_respects_consent_and_attempts(self):
        self.kin("task", "new", "online-database", "--goal", "Дешёвая онлайн", "--value", "3", "--priority", "2")
        self.kin("task", "new", "metric-books", "--goal", "Ценные метрики", "--value", "5", "--priority", "2",
                 "--cost", "free")
        self.kin("task", "new", "archive-request", "--goal", "Платный запрос", "--value", "5", "--cost", "paid")
        nxt = json.loads(self.kin("next", "--json").stdout)
        self.assertEqual(nxt["ranked"][0]["id"], "T-0002")
        excluded = {e["id"]: e["reason"] for e in nxt["excluded"]}
        self.assertIn("T-0001", excluded)  # онлайн-база = сторонний сервис → нужно согласие
        self.assertIn("T-0003", excluded)
        self.assertIn("согласие", self.kin("task", "start", "T-0003", ok=False).stderr)
        self.assertNotEqual(self.kin("update", "T-0003", "user_consent=granted", ok=False).returncode, 0)
        self.assertNotEqual(self.kin("update", "T-0003", "--append", "user_consent=granted", ok=False).returncode, 0)
        self.assertNotEqual(self.kin("add", "tasks", "--set", "goal=x", "--set", "status=ready",
                                     "--set", "user_consent=granted", ok=False).returncode, 0)
        for args in (("update", "T-0003", "cost=free"), ("update", "T-0003", "status=in-progress"),
                     ("update", "T-0003", "search_ids="),
                     ("add", "tasks", "--set", "goal=x", "--set", "cost=paid", "--set", "status=in-progress")):
            self.assertNotEqual(self.kin(*args, ok=False).returncode, 0, args)
        self.kin("task", "consent", "T-0003", "--granted", "--by", "Тестовый Пользователь")
        self.kin("task", "start", "T-0003", "--as", "Archive Researcher")
        self.assertEqual(Case(self.case).index("tasks")["T-0003"]["assignee"], "Archive Researcher")
        self.assertEqual(json.loads(self.kin("next", "--json").stdout)["next"]["id"], "T-0003")  # начатая — первой

    def test_close_without_finding_needs_logged_search_and_brief_exists(self):
        self.kin("task", "new", "metric-books", "--goal", "Рождение 1855")
        self.assertTrue((self.case / "tasks" / "T-0001.md").is_file())
        self.assertIn("T-0001", (self.case / "tasks" / "T-0001.md").read_text(encoding="utf-8"))
        self.kin("task", "start", "T-0001")
        self.assertIn("поиска", self.kin("task", "close", "T-0001", "--reason", "пусто", ok=False).stderr)
        self.kin("search", "add", "--task", "T-0001", "--source", "Архив ф. 15 метрики", "--query", "Иван 1855",
                 "--period", "1854/1856", "--result", "not-found", "--disallowed", "не значит, что не родился")
        self.kin("task", "close", "T-0001", "--reason", "книги утрачены")
        t = Case(self.case).index("tasks")["T-0001"]
        self.assertEqual((t["status"], t["search_ids"]), ("closed-without-finding", "S-0001"))
        hist = self.kin("history", "T-0001").stdout
        self.assertIn("close", hist)

    def test_attempt_limit(self):
        self.kin("task", "new", "library", "--goal", "Книги памяти")
        for src, q in (("РНБ каталог", "Ветлугин книга памяти"), ("РГБ электронный каталог", "Кленовка краеведение"),
                       ("Областная библиотека", "адрес-календарь Ольховской губернии")):
            self.kin("search", "add", "--task", "T-0001", "--source", src, "--query", q,
                     "--result", "not-found", "--disallowed", "—")
        nxt = json.loads(self.kin("next", "--json").stdout)
        self.assertIn("лимит попыток", nxt["excluded"][0]["reason"])
        res = self.kin("search", "add", "--task", "T-0001", "--source", "Ещё одна библиотека", "--query", "другое",
                       "--result", "not-found", ok=False)
        self.assertIn("лимит", res.stderr)


class TestSearchRepeat(Base):
    def test_repeat_needs_new_basis(self):
        args = ("search", "add", "--source", "ГАОО ф. 15 оп. 2 метрики", "--query", "рождение Ивана сына Кузьмы",
                "--period", "1853/1857", "--result", "not-found", "--disallowed", "нельзя считать, что не родился")
        self.kin(*args)
        res = self.kin("search", "add", "--source", "ГАОО, ф. 15, оп. 2 — метрики", "--query", "Рождение Ивана сына Кузьмы",
                       "--period", "1855", "--result", "not-found", ok=False)
        self.assertIn("уже был", res.stderr)
        res = self.kin("add", "searches", "--set", "date=2026-10-21", "--set", "source=ГАОО ф. 15 оп. 2 метрики",
                       "--set", "query=рождение Ивана сына Кузьмы", "--set", "result=not-found", ok=False)
        self.assertIn("уже был", res.stderr)
        self.kin("search", "add", "--source", "ГАОО ф. 15 оп. 2 метрики", "--query", "рождение Ивана сына Кузьмы",
                 "--period", "1855", "--result", "not-found", "--new-basis", "найден вариант написания Ветлюгин",
                 "--disallowed", "—")
        # другое дело (номера) и другие люди — не повтор
        self.kin("search", "add", "--source", "ГАОО ф. 20 оп. 1 метрики", "--query", "рождение Ивана сына Кузьмы",
                 "--period", "1855", "--result", "not-found", "--disallowed", "—")
        p1, p2 = self.person("Ветлугин Иван Петрович"), self.person("Ветлугин Иван Кузьмич")
        self.kin("search", "add", "--source", "Книга памяти", "--query", "Ветлугин Иван", "--persons", p1,
                 "--result", "not-found", "--disallowed", "—")
        self.kin("search", "add", "--source", "Книга памяти", "--query", "Ветлугин Иван", "--persons", p2,
                 "--result", "not-found", "--disallowed", "—")
        # другой период — не повтор
        self.kin("search", "add", "--source", "ГАОО ф. 15 оп. 2 метрики", "--query", "рождение Ивана сына Кузьмы",
                 "--period", "1880/1885", "--result", "not-found", "--disallowed", "—")


class TestReview(Base):
    def setUp(self):
        super().setUp()
        self.a1 = self.add_source("m1", group="g1")
        self.a2 = self.add_source("m2", group="g2")
        self.p = self.person("Ветлугин Иван Кузьмич")
        self.kin("add", "hypotheses", "--set", "statement=Отец — Кузьма", "--set", f"person_ids={self.p}",
                 "--set", "status=open", "--as", "Genealogy Researcher")

    def test_weak_hypothesis_cannot_pass(self):
        """Сценарий 5: гипотеза без источников — ревьюер не может её подтвердить."""
        self.kin("review", "request", "H-0001", "--as", "Genealogy Researcher")
        checks = self.kin("review", "checklist", "H-0001").stdout
        self.assertIn("[block]", checks)
        self.assertEqual(self.kin("review", "checklist", "V-0001").stdout, checks)  # по номеру ревью — то же
        res = self.kin("review", "submit", "V-0001", "--verdict", "passed", "--as", "Evidence Reviewer", ok=False)
        self.assertIn("блокирующих", res.stderr)
        self.kin("review", "submit", "V-0001", "--verdict", "needs-work", "--findings", "только отчество",
                 "--as", "Evidence Reviewer")
        self.assertEqual(Case(self.case).index("reviews")["V-0001"]["status"], "needs-work")
        res = self.kin("hypothesis", "status", "H-0001", "accepted", "--reason", "уверены", ok=False)
        self.assertIn("блокирующие", res.stderr)

    def test_self_review_and_unread_sources_refused(self):
        self.kin("claim", "add", "--type", "parentage", "--subject", self.p, "--statement", "x",
                 "--sources", f"{self.a1};{self.a2}", "--status", "corroborated", "--rationale", "две группы",
                 "--as", "Genealogy Researcher")
        self.kin("review", "request", "C-0001", "--for", "strongly-corroborated")
        for actor in ("Genealogy Researcher", "genealogy  researcher "):  # и с лишними пробелами
            res = self.kin("review", "submit", "V-0001", "--verdict", "passed", "--checked", self.a1, "--as", actor, ok=False)
            self.assertIn("другой ролью", res.stderr)
        res = self.kin("review", "submit", "V-0001", "--verdict", "passed", "--as", "Evidence Reviewer", ok=False)
        self.assertIn("первичные источники", res.stderr)
        other = self.add_source("other", group="g3")
        res = self.kin("review", "submit", "V-0001", "--verdict", "passed", "--checked", other,
                       "--as", "Evidence Reviewer", ok=False)
        self.assertIn("не относятся", res.stderr)
        self.kin("review", "submit", "V-0001", "--verdict", "passed", "--checked", f"{self.a1};{self.a2}",
                 "--findings", "ok", "--as", "Evidence Reviewer")
        self.kin("update", "C-0001", "status=strongly-corroborated")  # теперь разрешено
        self.assertEqual(json.loads(self.kin("audit", "--json").stdout)["errors"], [])  # и аудит согласен
        # изменение после ревью снимает его силу
        self.kin("update", "C-0001", "status=corroborated")
        self.kin("update", "C-0001", "rationale=пересмотрено")
        res = self.kin("update", "C-0001", "status=strongly-corroborated", ok=False)
        self.assertIn("ревью", res.stderr)

    def test_review_cannot_be_faked_or_reused(self):
        self.kin("claim", "add", "--type", "parentage", "--subject", self.p, "--statement", "x",
                 "--sources", f"{self.a1};{self.a2}", "--status", "corroborated", "--rationale", "две группы")
        self.kin("review", "request", "C-0001")  # общее ревью, без решения
        for args in (("update", "V-0001", "status=passed"), ("update", "V-0001", "human_decision=ok"),
                     ("add", "reviews", "--set", "target_id=C-0001", "--set", "status=passed")):
            self.assertNotEqual(self.kin(*args, ok=False).returncode, 0, args)
        self.kin("review", "submit", "V-0001", "--verdict", "passed", "--checked", self.a1, "--findings", "ok",
                 "--as", "Evidence Reviewer")
        # общее ревью не разрешает конкретное решение
        self.assertIn("ревью", self.kin("update", "C-0001", "status=strongly-corroborated", ok=False).stderr)
        # подделка строки в CSV — ловит аудит
        reg = self.case / "registry" / "reviews.csv"
        reg.write_text(reg.read_text(encoding="utf-8").replace("passed", "needs-work"), encoding="utf-8")
        self.assertTrue(any("журнал" in e for e in json.loads(self.kin("audit", "--json", ok=False).stdout)["errors"]))

    def test_stale_review_after_linked_claim_changes(self):
        self.kin("claim", "add", "--type", "parentage", "--subject", self.p, "--statement", "x",
                 "--sources", f"{self.a1};{self.a2}", "--status", "single-source", "--as", "Genealogy Researcher")
        self.kin("update", "H-0001", "claim_ids=C-0001", f"supporting_artifact_ids={self.a1};{self.a2}",
                 "alternatives=однофамилец", "test_plan=метрики", "--as", "Genealogy Researcher")
        self.kin("review", "request", "H-0001", "--for", "accepted", "--as", "Genealogy Researcher")
        self.kin("review", "submit", "V-0001", "--verdict", "passed", "--checked", self.a1, "--findings", "ok",
                 "--as", "Evidence Reviewer")
        self.kin("update", "C-0001", "rationale=пересмотрено после ревью", "--as", "Genealogy Researcher")  # связанное изменилось
        res = self.kin("hypothesis", "status", "H-0001", "accepted", "--reason", "ok", ok=False)
        self.assertIn("ревью", res.stderr)

    def test_hypothesis_lifecycle_rules(self):
        self.assertIn("kin hypothesis status", self.kin("update", "H-0001", "status=accepted", ok=False).stderr)
        res = self.kin("hypothesis", "status", "H-0001", "rejected", "--reason", "не нашли", "--reopen", "новые метрики",
                       ok=False)
        self.assertIn("отсутствие находки", res.stderr)
        self.kin("hypothesis", "status", "H-0001", "parked", "--reason", "источники утрачены", "--reopen", "дубликаты")
        hist = self.kin("history", "H-0001").stdout
        self.assertIn("источники утрачены", hist)


class TestHumanFlag(Base):
    def test_long_dead_unknown_does_not_need_human(self):
        a = self.add_source("p1903", group="g1")
        old = self.person("Иван Петров (1903)", "unknown", "candidate", "--birth", "1882~")
        young = self.person("Олег (1960)", "unknown", "candidate", "--birth", "1960")
        for p in (old, young):
            self.kin("claim", "add", "--type", "military", "--subject", p, "--statement", "Призыв", "--sources", a,
                     "--status", "single-source")
        self.assertNotIn("[human]", self.kin("review", "checklist", "C-0001").stdout)
        self.assertIn("[human]", self.kin("review", "checklist", "C-0002").stdout)


class TestRequestsAgentsPublish(Base):
    def test_request_due_and_overdue(self):
        (self.case / "requests" / "q.md").write_text("Текст запроса (вымышл.)", encoding="utf-8")
        self.kin("request", "add", "--recipient", "Архив", "--subject", "Метрики 1855", "--channel", "gov-portal",
                 "--text", "requests/q.md")
        self.kin("request", "sent", "Q-0001", "--date", "2020-01-10", "--number", "123")
        q = Case(self.case).index("requests")["Q-0001"]
        self.assertEqual(q["due_date"], "2020-02-09")
        st = json.loads(self.kin("status", "--json").stdout)
        self.assertTrue(st["requests_open"][0]["overdue"])

    def test_agents_install_formats(self):
        out = self.kin("agents", "install").stdout
        self.assertIn(".claude/agents/kin-evidence-reviewer.md", out)
        md = (self.case / ".claude" / "agents" / "kin-orchestrator.md").read_text(encoding="utf-8")
        self.assertTrue(md.startswith("---\nname: kin-orchestrator\ndescription: "))
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib — Python 3.11+")
        for p in (self.case / ".codex" / "agents").glob("*.toml"):
            data = tomllib.loads(p.read_text(encoding="utf-8"))
            self.assertTrue(data["name"] and data["description"] and data["developer_instructions"], p)
        self.assertFalse((self.case / ".claude" / "agents" / "kin-software-engineer.md").exists())

    def test_publish_copies_only_checked_build(self):
        p = self.person("Ветлугин Сергей", "deceased", "identity-confirmed", "--birth", "1921")
        self.person("Ветлугина Анна", "living", "identity-confirmed", "--birth", "1952")
        target = Path(self.tmp.name) / "www"
        self.assertIn("паролем", self.kin("site", "publish", "--profile", "private", "--to", str(target), ok=False).stderr)
        self.kin("site", "publish", "--profile", "public", "--to", str(target))
        text = (target / "tree.json").read_text(encoding="utf-8")
        self.assertIn(p, text)
        self.assertNotIn("Анна", text)
        # повторная выкладка удаляет только своё устаревшее, чужое не трогает
        (target / "robots.txt").unlink()
        (target / "extra.html").write_text("чужой файл", encoding="utf-8")
        self.kin("site", "publish", "--profile", "public", "--to", str(target))
        self.assertTrue((target / "extra.html").exists() and (target / "robots.txt").exists())

    def test_publish_refuses_dangerous_targets(self):
        foreign = Path(self.tmp.name) / "foreign"
        foreign.mkdir()
        (foreign / "important.txt").write_text("не удалять", encoding="utf-8")
        for bad in (str(foreign), str(Path(self.tmp.name)), str(self.case), "/"):
            self.assertNotEqual(self.kin("site", "publish", "--to", bad, ok=False).returncode, 0, bad)
        self.assertTrue((foreign / "important.txt").exists())

    def test_hook_install(self):
        subprocess.run(["git", "init", "-q", str(self.case)], check=True)
        self.kin("hooks", "install")
        hook = (self.case / ".git" / "hooks" / "post-commit").read_text(encoding="utf-8")
        self.assertIn("site build --profile private", hook)
        evil = str(Path(self.tmp.name) / "pub$(touch PWNED)")
        self.assertIn("паролем", self.kin("hooks", "install", "--publish-to", evil, ok=False).stderr)
        self.kin("hooks", "install", "--publish-to", evil, "--profile", "public")
        hook = (self.case / ".git" / "hooks" / "post-commit").read_text(encoding="utf-8")
        self.assertIn("'", hook)  # путь в одинарных кавычках shlex — без подстановки команд
        self.assertNotIn('"' + evil, hook)
        (self.case / ".git" / "hooks" / "post-commit").write_text("#!/bin/sh\necho мой хук\n", encoding="utf-8")
        self.assertNotEqual(self.kin("hooks", "install", ok=False).returncode, 0)

    def test_force_merge_needs_human(self):
        p1, p2 = self.person("Иван А"), self.person("Иван Б")
        self.assertIn("--by", self.kin("person", "merge", p2, p1, "--force", "--reason", "думаю", ok=False).stderr)
        self.kin("person", "merge", p2, p1, "--force", "--reason", "сверено с семьёй", "--by", "Тестовый Пользователь")
        self.assertEqual(json.loads(self.kin("audit", "--json").stdout)["errors"], [])


class TestSetup(unittest.TestCase):
    def test_setup_non_interactive(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "HOME": tmp, "KIN_DENYLIST": str(Path(tmp) / "deny.txt")}
            case = Path(tmp) / "cases" / "vetluginy"
            res = subprocess.run([sys.executable, str(KIN), "setup", "--yes", "--surname", "Ветлугин",
                                  "--title", "Род Ветлугиных", "--dir", str(case), "--anonymous-author"],
                                 capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
            self.assertEqual(res.returncode, 0, res.stderr)
            cfg = json.loads((case / "case.json").read_text(encoding="utf-8"))
            self.assertEqual(cfg["lines"][0]["id"], "vetlugin")
            name = subprocess.run(["git", "-C", str(case), "config", "user.name"], capture_output=True, text=True).stdout
            self.assertEqual(name.strip(), "Исследователь")
            self.assertIn("Ветлугин", (Path(tmp) / "deny.txt").read_text(encoding="utf-8"))
            self.assertTrue((case / ".claude" / "agents" / "kin-orchestrator.md").is_file())
            self.assertTrue((case / ".codex" / "agents" / "kin-orchestrator.toml").is_file())
            log = subprocess.run(["git", "-C", str(case), "log", "--format=%an"], capture_output=True, text=True).stdout
            self.assertEqual(log.strip(), "Исследователь")

    def test_setup_refuses_non_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "HOME": tmp, "KIN_DENYLIST": str(Path(tmp) / "deny.txt")}
            d = Path(tmp) / "docs"
            d.mkdir()
            (d / "mine.txt").write_text("личное", encoding="utf-8")
            res = subprocess.run([sys.executable, str(KIN), "setup", "--yes", "--surname", "Ветлугин", "--dir", str(d),
                                  "--anonymous-author"], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
            self.assertNotEqual(res.returncode, 0)
            self.assertFalse((d / ".git").exists())

    def test_setup_requires_explicit_author(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "HOME": tmp, "KIN_DENYLIST": str(Path(tmp) / "deny.txt")}
            res = subprocess.run([sys.executable, str(KIN), "setup", "--yes", "--surname", "Ветлугин",
                                  "--dir", str(Path(tmp) / "c")], capture_output=True, text=True, env=env,
                                 stdin=subprocess.DEVNULL)
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("автора", res.stderr)


class TestDemoWorkflow(unittest.TestCase):
    def test_demo_review_scenario(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp) / "demo"
            subprocess.run([sys.executable, str(REPO / "examples" / "demo" / "build_demo.py"), str(case)],
                           check=True, capture_output=True)
            rev = Case(case).index("reviews")["V-0001"]
            self.assertEqual((rev["target_id"], rev["status"], rev["reviewer"]), ("H-0001", "needs-work", "Evidence Reviewer"))
            self.assertIn("[block]", rev["auto_findings"])
            nxt = json.loads(run("next", "--json", case=case).stdout)
            self.assertEqual(nxt["next"]["id"], "T-0001")
            self.assertIn("T-0002", {e["id"] for e in nxt["excluded"]})
            for p in case.rglob("*"):
                if p.is_file():
                    p.chmod(0o644)


if __name__ == "__main__":
    unittest.main()
