"""Сайт-схема: выбор публикации, данные дерева, документы, иконки, языки, проверка раскладки."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO, Base, demo, run, unlock  # noqa: E402

sys.path.insert(0, str(REPO / "skills" / "kinship-kit"))


class TestPublicationChoices(Base):
    def setUp(self):
        super().setUp()
        self.add_source("svid", group="g1")
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


class TestActiveDocs(Base):
    def test_html_source_published_as_text(self):
        page = Path(self.tmp.name) / "archive-page.html"
        page.write_text("<script>alert(1)</script><p>Страница каталога</p>", encoding="utf-8")
        aid = json.loads(self.kin("source", "add", str(page), "--title", "Страница каталога", "--kind", "web-page",
                                  "--group", "g1", "--json").stdout)["artifact_id"]
        p = self.person("Ветлугин Сергей")
        self.kin("claim", "add", "--type", "residence", "--subject", p, "--statement", "Жил в Кленовке", "--sources", aid,
                 "--status", "single-source")
        self.kin("site", "build")
        docs = [x.name for x in (self.case / "site" / "private" / "docs" / aid).iterdir()]
        self.assertEqual(docs, ["archive-page.html.txt"])
        tree = json.loads((self.case / "site" / "private" / "tree.json").read_text(encoding="utf-8"))
        self.assertEqual(tree["arts"][aid]["files"], [{"n": "archive-page.html.txt", "k": "txt"}])


class TestSiteAssets(Base):
    def test_line_color_cannot_break_out_of_style(self):
        """case.json правят и вручную: цвет линии попадает в атрибут style — только #hex."""
        self.person("Ветлугин Сергей")
        cfg_path = self.case / "case.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["lines"] = [{"id": "a", "title": "A", "color": 'red" onmouseover="alert(1)'}, {"id": "b", "title": "B", "color": "#2f6b8a"}]
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        self.kin("site", "build")
        data = json.loads((self.case / "site" / "private" / "tree.json").read_text(encoding="utf-8"))
        self.assertEqual([ln["color"] for ln in data["lines"]], ["#8a7f6d", "#2f6b8a"])
        html = (self.case / "site" / "private" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("--lc:${l.color}", html)
        self.assertNotIn("--fc:${f.color}", html)

    def test_page_assets_are_built(self):
        """Всё, на что ссылается страница (иконки и т. п.), должно оказаться в сборке."""
        import re
        self.person("Ветлугин Сергей")
        self.kin("site", "build")
        out = self.case / "site" / "private"
        html = (out / "index.html").read_text(encoding="utf-8")
        refs = set(re.findall(r"""(?:src|href)=["']([^"':#?]+\.(?:png|svg|webp|jpg|gif|css|js))["']""", html))
        refs |= set(re.findall(r"""url\(["']?([^"')#?:]+\.(?:png|svg|webp|jpg|gif))""", html))
        self.assertTrue(refs, "страница должна ссылаться на иконки")
        missing = [r for r in refs if not (out / r).is_file() and r != "custom.css"]
        self.assertEqual(missing, [])


class TestSiteLanguages(Base):
    def test_dictionary_matches_template_and_both_versions_built(self):
        web = REPO / "skills" / "kinship-kit" / "kin" / "web"
        page = (web / "index.html").read_text(encoding="utf-8")
        pairs = json.loads((web / "i18n-en.json").read_text(encoding="utf-8"))
        self.assertEqual([a[:60] for a, b in pairs if a not in page], [])  # шаблон изменили — обновите словарь
        self.person("Ветлугин Сергей")
        self.kin("site", "build")
        out = self.case / "site" / "private"
        ru, en, default = ((out / n).read_text(encoding="utf-8") for n in ("index.ru.html", "index.en.html", "index.html"))
        self.assertIn("const PAGE_LANG = 'en';", en)
        self.assertIn(">RU<", en)
        self.assertIn(">EN<", ru)
        self.assertEqual(default, ru)  # язык дела — ru

    def test_english_page_has_no_russian_ui(self):
        import html as htmllib
        import re
        import shutil as sh
        chrome = next((p for p in (sh.which("google-chrome"), "/opt/google/chrome/chrome") if p and Path(p).exists()), None)
        if not chrome:
            self.skipTest("нужен Chrome")
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp) / "en"
            subprocess.run([sys.executable, str(REPO / "examples" / "demo" / "build_demo_en.py"), str(case)], check=True,
                           capture_output=True)
            run("site", "build", case=case)
            page = case / "site" / "private" / "index.en.html"
            dom = subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--virtual-time-budget=5000",
                                  f"--user-data-dir={tmp}/chrome", "--allow-file-access-from-files", "--dump-dom",
                                  page.as_uri() + "#P-0002"], capture_output=True, text=True, timeout=120).stdout
            dom = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", dom, flags=re.S)
            text = htmllib.unescape(re.sub(r"<[^>]+>", " ", dom)) + " " + " ".join(re.findall(r'(?:title|aria-label|placeholder)="([^"]*)"', dom))
            self.assertIn("Facts and their evidence", text)  # профиль отрисован
            russian = sorted({x.strip() for x in re.findall(r"[А-Яа-яЁё][А-Яа-яЁё ]*", text)} - {"Русская версия"})
            self.assertEqual(russian, [])
            unlock(case)


class TestLayoutCheck(Base):
    def test_many_unlinked_people_still_laid_out(self):
        """70 человек без связей: раньше раскладка оставляла пустые координаты и схема была пустой."""
        import shutil as sh
        if not sh.which("node"):
            self.skipTest("нужен node")
        for i in range(70):
            self.kin("person", "add", "--label", f"Одиночкин Кандидат{i}", "--living", "deceased", "--status", "candidate",
                     "--birth", str(1850 + i))
        root = self.person("Корнев Корень", "deceased", "identity-confirmed", "--birth", "1950")
        self.kin("case", "set", f"root_person={root}")
        res = self.kin("site", "build")
        self.assertNotIn("предупреждение", res.stderr)
        sys.path.insert(0, str(REPO / "skills" / "kinship-kit"))
        from kin import site as site_mod
        out = self.case / "site" / "private"
        self.assertEqual(site_mod.check_layout(out), [])
        # и английская версия страницы тоже
        res = subprocess.run(["node", str(REPO / "skills/kinship-kit/kin/web/check_layout.js"), str(out / "index.en.html"),
                              str(out / "tree.json")], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_demo_layout(self):
        import shutil as sh
        if not sh.which("node"):
            self.skipTest("нужен node")
        with tempfile.TemporaryDirectory() as tmp:
            case = demo(tmp)
            res = run("site", "build", case=case)
            self.assertNotIn("предупреждение", res.stderr)
            unlock(case)
