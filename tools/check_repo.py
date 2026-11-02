#!/usr/bin/env python3
"""Проверка публичного репозитория набора: нет данных дел, секретов и личных сведений.

python3 tools/check_repo.py            # все отслеживаемые и подготовленные файлы
python3 tools/check_repo.py --staged   # только подготовленные к коммиту (pre-commit)

Личный стоп-лист (фамилии своей семьи, адреса и т. п.) держите ВНЕ репозитория:
файл из переменной KIN_DENYLIST или ~/.config/kinship-kit/denylist.txt — по строке на термин.
Не полагается только на .gitignore: проверяется содержимое, а не имена.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
EMAIL_OK = re.compile(r"@(example\.(org|com|net|invalid)|anthropic\.com)$")
PHONE = re.compile(r"(?<![\w-])(?:\+\d[\d\s()-]{8,}\d|8\s?\(\d{3}\)\s?\d{3}[\s-]?\d{2}[\s-]?\d{2})(?!\w)")
SECRETS = [re.compile(p) for p in (r"-----BEGIN [A-Z ]*PRIVATE KEY", r"\bghp_[A-Za-z0-9]{20,}", r"\bsk-ant-[\w-]{10,}",
                                    r"\bAKIA[0-9A-Z]{16}\b", r"\bxox[bp]-[\w-]{10,}")]
PRIVATE_PATH = re.compile(r"/root/[\w.-]+/|/home/[a-z][\w-]*/|/Users/[A-Za-z][\w-]*/|[A-Z]:\\\\Users\\\\")
ALLOW = "check_repo: allow"  # пометка в строке с намеренными тестовыми данными
DEMO_DOCS = ("examples/demo/documents/", "examples/demo/documents_en/")
SKIP = {"tools/check_repo.py"}  # содержит сами шаблоны


def files(staged: bool) -> list[str]:
    cmd = ["git", "-C", str(ROOT), "diff", "--cached", "--name-only", "--diff-filter=ACMR"] if staged else \
          ["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard"]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout
    return [f for f in out.splitlines() if f]


def denylist() -> list[str]:
    path = Path(os.environ.get("KIN_DENYLIST", Path.home() / ".config" / "kinship-kit" / "denylist.txt"))
    if not path.is_file():
        return []
    if ROOT in path.resolve().parents:
        sys.exit("Стоп-лист лежит внутри репозитория — перенесите его наружу.")
    return [t.strip() for t in path.read_text(encoding="utf-8").splitlines() if t.strip() and not t.startswith("#")]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows: консоль по умолчанию не в UTF-8, русский вывод падал бы
        stream.reconfigure(encoding="utf-8", errors="replace")
    staged = "--staged" in sys.argv
    deny = [(t, re.compile(re.escape(t), re.IGNORECASE)) for t in denylist()]
    problems = []
    for rel in files(staged):
        path = ROOT / rel
        if rel in SKIP or not path.is_file():
            continue
        parts = Path(rel).parts
        if path.name == "case.json" or path.name == "journal.jsonl" or ("registry" in parts and rel.endswith(".csv")):
            problems.append(f"{rel}: похоже на файл дела — данные дел не хранятся в репозитории набора")
        if "sources" in parts and not rel.startswith(DEMO_DOCS):
            problems.append(f"{rel}: папка sources/ — оригиналы документов дела")
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if rel.startswith(DEMO_DOCS) and "СИНТЕТИЧЕСКИЙ" not in text and "SYNTHETIC" not in text:
            problems.append(f"{rel}: демо-документ без пометки [СИНТЕТИЧЕСКИЙ ДОКУМЕНТ]")
        text = "\n".join(line for line in text.splitlines() if ALLOW not in line)
        for m in EMAIL.finditer(text):
            if not EMAIL_OK.search(m.group(0)) and m.group(0) != "git@github.com":  # SSH-адрес, не почта
                problems.append(f"{rel}: e-mail {m.group(0)}")
        for rx, label in [(PHONE, "телефон"), (PRIVATE_PATH, "приватный путь")] + [(s, "секрет") for s in SECRETS]:
            m = rx.search(text)
            if m:
                problems.append(f"{rel}: {label} «{m.group(0)[:40]}»")
        for term, rx in deny:
            if rx.search(text):
                problems.append(f"{rel}: термин из личного стоп-листа «{term}»")
    if problems:
        print("Проверка репозитория НЕ пройдена:\n- " + "\n- ".join(problems))
        return 1
    print("Проверка репозитория: ок")
    return 0


if __name__ == "__main__":
    sys.exit(main())
