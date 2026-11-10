"""Общее для тестов: запуск kin, базовый класс с временным делом, демо-дело."""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skills" / "kinship-kit"
KIN = SKILL / "kin.py"
sys.path.insert(0, str(SKILL))
# сборки сайта в тестах — без проверки раскладки в Chrome (долго); её проверяют отдельные тесты (test_site.TestLayoutCheck)
os.environ.setdefault("KIN_SKIP_LAYOUT_CHECK", "1")

# вывод тестов — в UTF-8, как у самого kin (cli.main): в Windows консоль по умолчанию в cp1252/cp1251,
# и print русского текста из кода набора внутри теста (например, сервер в потоке) падал бы
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, ValueError):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def run(*args, case: Path | None = None, ok: bool = True) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(KIN), *args]
    if case is not None:
        cmd += ["--case", str(case)]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)  # kin не ждёт ввода
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


def demo(tmp: str, name: str = "demo") -> Path:
    case = Path(tmp) / name
    res = subprocess.run([sys.executable, str(REPO / "examples" / "demo" / "build_demo.py"), str(case)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise AssertionError(f"демо-дело не построено ({res.returncode}):\n{res.stdout[-1500:]}\n{res.stderr[-1500:]}")
    return case


def unlock(root: Path) -> None:
    for p in root.rglob("*"):
        if p.is_file():
            p.chmod(0o644)

