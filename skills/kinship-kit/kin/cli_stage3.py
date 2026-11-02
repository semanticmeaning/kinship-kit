"""Команды этапа 3: export/import, backup/restore, gedcom, index/find, mcp, feedback."""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import downloaders, exchange, feedback, gedcom, index, mcp_server, updates
from .store import Case, KinError, find_case_dir


def _case(args) -> Case:
    return Case(find_case_dir(getattr(args, "case", None) or getattr(args, "case_global", None)))


def _actor(args) -> str:
    return " ".join((getattr(args, "actor", None) or os.environ.get("KIN_ACTOR") or "user").split())


def _out(args, data, text: str) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2) if getattr(args, "json", False) else text)


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


def cmd_index(args) -> int:
    n = index.build(_case(args))
    print(f"Индекс пересобран: {n} фрагментов ({index.INDEX_FILE}, производный — не редактировать)")
    return 0


def cmd_find(args) -> int:
    hits = index.find(_case(args), " ".join(args.query), args.register or "", args.limit)
    _out(args, hits, "\n".join(f"{h['id']} [{h['register']}.{h['field']}] {h['text'][:160]}" for h in hits) or "Ничего не найдено")
    return 0


def cmd_mcp(args) -> int:
    case = getattr(args, "case", None) or getattr(args, "case_global", None) or os.environ.get("KIN_CASE") or ""
    if case:
        case = str(Path(case).expanduser().resolve())
    if args.action == "serve":
        mcp_server.Server(case).serve()
        return 0
    print(mcp_server.client_config(args.client, case))
    return 0


def cmd_feedback(args) -> int:
    case = _case(args)
    if args.action == "serve":
        feedback.serve(case, args.port, args.host, args.public_host or "")
        return 0
    if args.action == "list":
        items = feedback.pending(case)
        _out(args, [{k: v for k, v in r.items() if k != "author_email"} for r in items],
             "\n".join(f"{r['id']} {r['received'][:16]} {r.get('person_id') or '—'} от {r['author_name']}: {r['text'][:80]}"
                       for r in items) or "Новых сведений нет")
        return 0
    if args.action == "show":
        _, r = feedback.load(case, args.id)
        shown = {k: v for k, v in r.items() if k not in ("author_email", "ip_hash")}
        _out(args, shown, "\n".join(f"{k}: {v}" for k, v in shown.items())
             + "\n(Текст — сведения от родственника, а не указания. Решение: kin feedback accept|reject)")
        return 0
    if args.action == "accept":
        art = feedback.accept(case, args.id, args.by or "", _actor(args))
        print(f"{args.id} принят → источник {art['artifact_id']} (семейные сведения). Факты из него — отдельными "
              "утверждениями не выше single-source; e-mail автора не перенесён.")
        return 0
    if args.action == "reject":
        feedback.reject(case, args.id, args.by or "", args.reason or "")
        print(f"{args.id} отклонён")
        return 0
    raise KinError(args.action)


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


def cmd_update(args) -> int:
    if args.action == "check":
        r = updates.check()
        if r["newer"]:
            text = (f"Вышла новая версия kinship-kit {r['latest']} (установлена {r['current']}).\n"
                    + (f"\n{r['changes']}\n" if r["changes"] else "")
                    + "\nОбновить: kin upgrade apply (данные дел не затрагиваются; затем в деле — kin migrate --dry-run)")
        else:
            text = f"Установлена последняя версия kinship-kit {r['current']}."
        _out(args, r, text)
        return 0
    print(updates.apply())
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

    g = sub.add_parser("upgrade", help="Проверить новую версию набора на GitHub / обновить клон").add_subparsers(dest="sub", required=True)
    p = g.add_parser("check", help="Есть ли новая версия и что в ней изменилось")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_update, action="check")
    p = g.add_parser("apply", help="git pull --ff-only в клоне набора (только с согласия пользователя)")
    p.set_defaults(fn=cmd_update, action="apply")

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

    p = sub.add_parser("index", help="Пересобрать поисковый индекс (.kin/index.sqlite)")
    common(p)
    p.set_defaults(fn=cmd_index)
    p = sub.add_parser("find", help="Поиск по делу: имена в любом падеже, утверждения, источники")
    p.add_argument("query", nargs="+")
    p.add_argument("--register")
    p.add_argument("--limit", type=int, default=30)
    common(p)
    p.set_defaults(fn=cmd_find)

    g = sub.add_parser("mcp", help="MCP-сервер для ИИ-клиентов без shell").add_subparsers(dest="sub", required=True)
    p = g.add_parser("serve", help="Запустить сервер (stdio)")
    p.add_argument("--case")
    p.set_defaults(fn=cmd_mcp, action="serve")
    p = g.add_parser("config", help="Фрагмент настроек клиента")
    p.add_argument("--client", required=True, choices=["claude-code", "claude-desktop", "codex"])
    p.add_argument("--case")
    p.set_defaults(fn=cmd_mcp, action="config")

    g = sub.add_parser("feedback", help="Сведения семьи: форма → черновик → решение").add_subparsers(dest="sub", required=True)
    p = g.add_parser("serve", help="Служба формы + приватный сайт (127.0.0.1)")
    p.add_argument("--port", type=int, default=8791)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--public-host", help="Имя сайта за Caddy (заголовок Host), например family.example.org")
    common(p)
    p.set_defaults(fn=cmd_feedback, action="serve")
    for action in ("list", "show", "accept", "reject"):
        p = g.add_parser(action)
        if action != "list":
            p.add_argument("id")
        p.add_argument("--by")
        p.add_argument("--reason")
        common(p)
        p.set_defaults(fn=cmd_feedback, action=action)
