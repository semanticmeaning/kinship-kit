"""Обмен данными: export/import, backup/restore, gedcom, скачиватели архивов и импорт их выгрузок."""
from __future__ import annotations

import json
from pathlib import Path

from . import downloaders, exchange, gedcom
from .cli_common import _actor, _case, _out
from .store import Case, KinError, find_case_dir


def cmd_export(args) -> int:
    path = exchange.write_export(_case(args), Path(args.out), args.with_files, args.force)
    print(f"Экспорт: {path}" + ("" if args.with_files else " (без файлов источников — они в резервной копии: kin backup)"))
    return 0

def cmd_import(args) -> int:
    data = json.loads(Path(args.file).expanduser().read_text(encoding="utf-8"))
    rep = exchange.import_data(_case(args), data, _actor(args), args.dry_run)
    if rep["conflicts"]:
        _out(args, rep, "Импорт НЕ выполнен — конфликты (записи с теми же ID отличаются):\n- " + "\n- ".join(rep["conflicts"]))
        return 1
    added = ", ".join(f"{k}={v}" for k, v in rep["added"].items()) or "нет"
    skipped = ", ".join(f"{k}={v}" for k, v in rep["skipped"].items()) or "нет"
    _out(args, rep, ("Проверка (без записи): " if args.dry_run else "Импорт: ")
         + f"добавлено {added}; уже были {skipped}; записей журнала {rep['journal_added']}; файлов {rep['files']}")
    return 0

def cmd_backup(args) -> int:
    path = exchange.backup(_case(args), Path(args.out) if args.out else None, with_git=not args.no_git)
    print(f"Резервная копия: {path}\nВосстановить: kin restore {path} <новая папка>")
    return 0

def cmd_restore(args) -> int:
    rep = exchange.restore(Path(args.archive), Path(args.dir))
    from . import audit
    res = audit.run(Case(Path(args.dir).expanduser().resolve()))
    print(f"Восстановлено в {Path(args.dir).expanduser().resolve()}: файлов {rep['files']}, схема v{rep['schema_version']}, "
          f"копия от {rep['created']}.\nАудит: ошибок {len(res['errors'])}, предупреждений {len(res['warnings'])}")
    return 1 if res["errors"] else 0

def cmd_gedcom_export(args) -> int:
    text = gedcom.export(_case(args), args.profile, args.include_hypotheses)
    out = Path(args.out).expanduser().resolve()
    case = _case(args)
    if case.root == out or case.root in out.parents:
        raise KinError("GEDCOM сохраняется вне папки дела")
    if out.exists() and not args.force:
        raise KinError(f"{out} уже существует — другое имя или --force")
    out.write_text(text, encoding="utf-8")
    print(f"GEDCOM ({args.profile}): {out} — лиц {text.count(' INDI')}, семей {text.count(' FAM')}. Ограничения — docs/GEDCOM.md")
    return 0

def cmd_gedcom_import(args) -> int:
    rep = gedcom.import_file(_case(args), Path(args.file), _actor(args), args.group or "", args.dry_run, args.allow_self)
    if rep.get("already"):
        print(f"Этот файл уже импортирован как {rep['already']} — ничего не добавлено.")
        return 0
    text = (("Проверка (без записи): " if args.dry_run else f"Импорт {rep.get('artifact', '')}: ")
            + f"новых людей {rep['persons_new']}, сопоставлено с существующими {rep['persons_matched']}"
            + ("" if args.dry_run else f", утверждений {rep['claims']}, связей {rep['relationships']}"))
    if rep["possible_duplicates"]:
        text += "\nВозможные дубликаты (не слиты — проверьте и при основаниях оформите identity):\n- " + "\n- ".join(rep["possible_duplicates"])
    _out(args, rep, text)
    return 0

def _maybe_case_dir(args) -> Path | None:
    try:
        return find_case_dir(getattr(args, "case", None) or getattr(args, "case_global", None))
    except KinError:
        return None

def cmd_downloader(args) -> int:
    case_dir = _maybe_case_dir(args)
    if args.action == "list":
        found = downloaders.adapters(case_dir / "downloaders" if case_dir else None)
        _out(args, {k: {x: str(y) for x, y in v.items()} for k, v in found.items()},
             "\n".join(f"{k} — {v.get('title', '')} (v{v.get('version', '?')}, {v.get('site', '')})" for k, v in sorted(found.items()))
             + "\nСборка: kin downloader build <адаптер> --out скрипт.js")
        return 0
    snippet, guide = downloaders.build(args.adapter, case_dir)
    if args.out:
        out = Path(args.out).expanduser().resolve()
        if out.exists() and not args.force:
            raise KinError(f"{out} уже существует — другое имя или --force")
        out.write_text(snippet, encoding="utf-8")
        print(f"Скрипт: {out} ({len(snippet)} знаков)\n\n{guide}")
    else:
        print(snippet)
        print("/*\n" + guide + "*/")
    return 0

def cmd_import_download(args) -> int:
    rep = downloaders.import_download(_case(args), Path(args.folder), _actor(args), args.task or "", args.dry_run)
    text = (("Проверка (без записи): " if args.dry_run else "Загружено: ") + f"новых файлов {rep['new']}"
            + (f", источники {rep['artifacts'][0]}…{rep['artifacts'][-1]}" if rep["artifacts"] else "")
            + f"; уже были в деле {rep['skipped_known']}; не скачалось на сайте {rep['errors_on_site']} (см. _kinship-download.txt).")
    if rep["artifacts"]:
        text += "\nДальше: разобрать сканы — kin task new metric-books … (упоминания, утверждения)."
    _out(args, rep, text)
    return 0


def add_commands(sub, common) -> None:
    g = sub.add_parser("downloader", help="Скачиватели сканов из онлайн-архивов (вставка в консоль браузера)").add_subparsers(dest="sub", required=True)
    p = g.add_parser("list", help="Поддержанные сайты")
    common(p)
    p.set_defaults(fn=cmd_downloader, action="list")
    p = g.add_parser("build", help="Собрать скрипт для консоли и инструкцию")
    p.add_argument("adapter")
    p.add_argument("--out", help="Сохранить скрипт в файл (иначе — вывод на экран)")
    p.add_argument("--force", action="store_true")
    common(p)
    p.set_defaults(fn=cmd_downloader, action="build")

    p = sub.add_parser("export", help="Полный экспорт дела (собственный формат JSON, docs/EXPORT.md)")
    p.add_argument("--out", required=True)
    p.add_argument("--with-files", action="store_true", help="Включить файлы источников (base64)")
    p.add_argument("--force", action="store_true", help="Перезаписать существующий файл")
    common(p)
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("import", help="Импорт экспорта kinship-kit (повторный импорт не создаёт дублей)")
    p.add_argument("file")
    p.add_argument("--dry-run", action="store_true")
    common(p)
    p.set_defaults(fn=cmd_import)

    p = sub.add_parser("backup", help="Резервная копия дела (tar.gz с манифестом контрольных сумм)")
    p.add_argument("--out")
    p.add_argument("--no-git", action="store_true", help="Без истории git")
    common(p)
    p.set_defaults(fn=cmd_backup)

    p = sub.add_parser("restore", help="Восстановить дело из резервной копии в новую папку")
    p.add_argument("archive")
    p.add_argument("dir")
    p.set_defaults(fn=cmd_restore)

    g = sub.add_parser("gedcom", help="GEDCOM 5.5.1: экспорт и импорт").add_subparsers(dest="sub", required=True)
    p = g.add_parser("export")
    p.add_argument("--out", required=True)
    p.add_argument("--profile", default="private", choices=["private", "public"])
    p.add_argument("--include-hypotheses", action="store_true")
    p.add_argument("--force", action="store_true", help="Перезаписать существующий файл")
    common(p)
    p.set_defaults(fn=cmd_gedcom_export)
    p = g.add_parser("import")
    p.add_argument("file")
    p.add_argument("--group", help="Группа независимости древа (по умолчанию family-tree:<имя файла>)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--allow-self", action="store_true", help="Разрешить импорт экспорта этого же дела")
    common(p)
    p.set_defaults(fn=cmd_gedcom_import)
