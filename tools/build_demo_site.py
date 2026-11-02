#!/usr/bin/env python3
"""Собрать демонстрационный сайт (GitHub Pages) из вымышленных демо-дел: русское и английское, публичный и приватный вид.

python3 tools/build_demo_site.py <папка-вывода>

Дела строятся во временной папке командами kin (как у пользователя), в вывод попадают только собранные сайты.
Все люди, места, архивы и документы вымышлены.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIN = ROOT / "skills" / "kinship-kit" / "kin.py"

LANDING = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>kinship-kit — демо</title>
<meta name="description" content="Демонстрация сайта-схемы рода kinship-kit на вымышленной семье">
<style>
:root{--bg:#f6f4ef;--panel:#fffdf8;--ink:#23201b;--muted:#6f685c;--line:#d9cfbd;--accent:#7a4b1d}
@media (prefers-color-scheme:dark){:root{--bg:#191714;--panel:#221f1b;--ink:#ece6da;--muted:#a59d8f;--line:#4a443b;--accent:#e0a868}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:860px;margin:0 auto;padding:40px 16px 64px}
h1{font-size:28px;margin:0 0 6px}
.lead{color:var(--muted);margin:0 0 28px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}
a.card{display:block;padding:16px 18px;border:1px solid var(--line);border-radius:12px;background:var(--panel);
  color:inherit;text-decoration:none;transition:transform .12s ease,border-color .12s ease}
a.card:hover{transform:translateY(-2px);border-color:var(--accent)}
a.card b{display:block;font-size:17px;margin-bottom:4px}
a.card span{color:var(--muted);font-size:14px}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:32px 0 10px}
ul{padding-left:20px}li{margin:4px 0}
footer{margin-top:40px;color:var(--muted);font-size:14px}
a{color:var(--accent)}
@media (prefers-reduced-motion:reduce){a.card{transition:none}}
</style>
</head>
<body>
<main>
<h1>kinship-kit — демо сайта-схемы рода</h1>
<p class="lead">Вымышленная семья Ветлугиных: все люди, деревни, архивы и документы выдуманы.
Так выглядит результат исследования, которое ведёт ИИ-агент с навыком kinship-kit.<br>
<em>Demo of the family-tree site on a fictional family — everything here is made up.</em></p>

<h2>Русский</h2>
<div class="grid">
  <a class="card" href="ru/public/"><b>Публичная версия</b><span>Для всех: живые родственники скрыты автоматически</span></a>
  <a class="card" href="ru/private/"><b>Приватная версия</b><span>Для семьи (обычно за паролем): видны и живые — здесь вымышленные</span></a>
</div>
<h2>English</h2>
<div class="grid">
  <a class="card" href="en/public/"><b>Public version</b><span>For everyone: living relatives are hidden automatically</span></a>
  <a class="card" href="en/private/"><b>Private version</b><span>For the family (normally password-protected): living people shown — fictional here</span></a>
</div>

<h2>Что посмотреть / What to look at</h2>
<ul>
  <li>Колена рода сверху вниз; гипотезы — штрихом, «возможно одно лицо» — точками.</li>
  <li>Пётр Иванович: две конкурирующие даты смерти (1941 и 1942) — обе сохранены с источниками «за» и «против».</li>
  <li>Два кандидата «Иван Петрович» — не слиты без оснований; гипотеза о тождестве ждёт проверки.</li>
  <li>Кузьма — предок, выведенный только по отчеству: ревьюер вернул гипотезу на доработку.</li>
  <li>Сравните публичную и приватную версии: в публичной нет живых и служебных пометок.</li>
  <li>Click a person to see claims, sources (archive references) and competing versions; switch RU/EN at the top.</li>
</ul>
<footer>Исходный код и инструкция: <a href="https://github.com/semanticmeaning/kinship-kit">github.com/semanticmeaning/kinship-kit</a> ·
сборка: {built}</footer>
</main>
</body>
</html>
"""


def kin(case: Path, *args: str) -> None:
    res = subprocess.run([sys.executable, str(KIN), "--case", str(case), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        sys.exit(f"kin {' '.join(args)}:\n{res.stderr}")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = Path(sys.argv[1]).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        for lang, builder in (("ru", "build_demo.py"), ("en", "build_demo_en.py")):
            case = Path(tmp) / lang
            subprocess.run([sys.executable, str(ROOT / "examples" / "demo" / builder), str(case)], check=True,
                           capture_output=True)
            for profile in ("public", "private"):
                kin(case, "site", "build", "--profile", profile)
                shutil.copytree(case / "site" / profile, out / lang / profile)
            for p in case.rglob("*"):
                if p.is_file():
                    p.chmod(0o644)
    import datetime as dt
    (out / "index.html").write_text(LANDING.replace("{built}", dt.date.today().isoformat()), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Демо-сайт: {out}")


if __name__ == "__main__":
    main()
