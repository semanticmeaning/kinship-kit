"""kin — командная строка дела генеалогического исследования. Вся логика набора — здесь."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__, audit, publish, site, status
from .store import (REGISTERS, SCHEMA, Case, KinError, field_names, find_case_dir, init_case, join_ids,
                    register_by_prefix, sha256_file, split_ids)

# ---------------------------------------------------------------- помощники


def _out(args, data, text: str | None = None) -> None:
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(text if text is not None else data)


def _case(args) -> Case:
    return Case(find_case_dir(getattr(args, "case", None) or getattr(args, "case_global", None)))


def _actor(args) -> str:
    return args.actor or os.environ.get("KIN_ACTOR") or "user"


def _pairs(items: list[str] | None) -> dict:
    out = {}
    for item in items or []:
        if "=" not in item:
            raise KinError(f"Ожидается поле=значение, получено {item!r}")
        k, v = item.split("=", 1)
        out[k.strip()] = v
    return out


def _collect(args, mapping: dict[str, str]) -> dict:
    """Опции команды → поля реестра; --set k=v дополняет и перекрывает."""
    values = {field: getattr(args, opt) for opt, field in mapping.items() if getattr(args, opt, None) is not None}
    values.update(_pairs(getattr(args, "set", None)))
    return values


def _print_row(args, row: dict, verb: str = "добавлено") -> None:
    rid = next(iter(row.values()))
    _out(args, row, f"{rid} {verb}")


# ---------------------------------------------------------------- init

CASE_AGENTS_MD = """# Дело: {title}

Папка дела генеалогического исследования (kinship-kit, схема данных v{version}). Приватные данные — не публиковать.

## В начале каждого сеанса
1. `kin status` — активные гипотезы, задачи, отрицательные поиски, следующий шаг (состояние — из данных, не из чата).
2. `kin audit` — 0 ошибок перед любыми выводами и публикацией.

## Правила
- Реестры (`registry/*.csv`) меняются только командами `kin` (`kin add`, `kin update`, `kin claim add` …): проверка схемы, блокировка, журнал.
- Каждый документ — `kin source add <файл>`: копия в `sources/` + sha256; оригиналы не правятся.
- Документ ≠ человек: запись о человеке в источнике — `mention`; отождествление с `person` — отдельное решение с обоснованием.
- Связь — только если родство названо в источнике; иначе гипотеза (`claim` со статусом `hypothesis`).
- Разные даты в разных документах — два утверждения с `competing_claim_ids`, обе версии сохраняются.
- Безрезультатный поиск — запись в `searches` (где, что, варианты, период, что нельзя выводить, когда повторить).
- Живых не искать; их данные — минимально; в публичную сборку они не попадают.
- Платные действия и передача данных сторонним сервисам — только с согласия пользователя.
- Методика: навык `kinship-kit` (SKILL.md).
"""


def cmd_init(args) -> int:
    root = init_case(Path(args.dir), args.title or Path(args.dir).name, args.lang, git=not args.no_git)
    text = CASE_AGENTS_MD.format(title=args.title or root.name, version=SCHEMA["schema_version"])
    (root / "AGENTS.md").write_text(text, encoding="utf-8")
    (root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    print(f"Дело создано: {root}\nДальше: cd {root} && kin status")
    return 0


# ---------------------------------------------------------------- source

SOURCE_MAP = {"title": "title", "kind": "kind", "url": "url", "repository": "repository", "ref": "archival_reference",
              "date": "record_date", "place": "place_as_written", "lang": "language_script", "directness": "directness",
              "originality": "originality", "group": "independence_group", "provenance": "provenance",
              "summary": "summary", "notes": "notes", "scan_publication": "scan_publication", "captured": "captured_at"}


def _safe_name(name: str) -> str:
    stem = re.sub(r"[^\w.-]+", "_", name, flags=re.UNICODE).strip("._") or "file"
    return stem[:80]


def cmd_source_add(args) -> int:
    case = _case(args)
    values = _collect(args, SOURCE_MAP)
    src = Path(args.file).expanduser() if args.file else None
    if src is None and not values.get("url") and not values.get("archival_reference"):
        raise KinError("Нужен файл, --url или --ref: источник без происхождения не регистрируется.")
    if src is not None:
        if not src.is_file():
            raise KinError(f"Файл не найден: {src}")
        digest = sha256_file(src)
        for a in case.rows("artifacts"):
            if a.get("sha256") == digest:
                raise KinError(f"Этот файл уже зарегистрирован как {a['artifact_id']} ({a['file']})")
        values.setdefault("title", src.stem)
        values["sha256"] = digest
    with case.lock():
        aid = case.next_id("artifacts")
    if src is not None:
        dest = case.root / "sources" / f"{aid}__{_safe_name(src.name)}"
        if dest.exists():
            raise KinError(f"{dest.name} уже существует — повторите команду")
        shutil.copy2(src, dest)
        os.chmod(dest, 0o444)
        values["file"] = dest.relative_to(case.root).as_posix()
    values["artifact_id"] = aid
    if not values.get("independence_group"):
        values["independence_group"] = aid  # по умолчанию — своя группа; копии того же документа укажите явно
    try:
        row = case.add("artifacts", values, _actor(args))
    except KinError:
        if src is not None:
            Path(case.root / values["file"]).chmod(0o644)
            Path(case.root / values["file"]).unlink(missing_ok=True)
        raise
    _print_row(args, row)
    return 0


# ---------------------------------------------------------------- person / mention / claim / rel

PERSON_MAP = {"label": "preferred_label", "sex": "sex", "living": "living_status", "variants": "name_variants",
              "birth": "birth_estimate", "death": "death_estimate", "places": "places", "status": "status",
              "line": "line", "publication": "publication", "notes": "notes"}
MENTION_MAP = {"artifact": "artifact_id", "name": "name_as_written", "role": "role", "age": "age_as_written",
               "date": "date_as_written", "place": "place_as_written", "details": "details", "person": "person_id",
               "link_status": "link_status", "rationale": "link_rationale", "notes": "notes"}
CLAIM_MAP = {"type": "claim_type", "subject": "subject_person_ids", "statement": "statement", "date": "date",
             "place": "place", "sources": "artifact_ids", "mentions": "mention_ids",
             "against": "contradicting_artifact_ids", "competing": "competing_claim_ids", "status": "status",
             "confidence": "confidence", "rationale": "rationale", "supersedes": "supersedes",
             "reviewed_by": "reviewed_by", "next": "next_action"}
REL_MAP = {"nature": "nature", "claims": "claim_ids", "sources": "supporting_artifact_ids",
           "against": "contradicting_artifact_ids", "status": "status", "rationale": "rationale"}


def _add(register: str, mapping: dict):
    def run(args) -> int:
        case = _case(args)
        values = _collect(args, mapping)
        if register == "mentions" and values.get("person_id") and not values.get("link_status"):
            values["link_status"] = "possible"
        row = case.add(register, values, _actor(args))
        _print_row(args, row)
        return 0
    return run


def cmd_rel_add(args) -> int:
    case = _case(args)
    values = _collect(args, REL_MAP)
    values.update({"person_a_id": args.a, "relationship_type": args.type, "person_b_id": args.b})
    row = case.add("relationships", values, _actor(args))
    _print_row(args, row)
    return 0


def cmd_add(args) -> int:
    case = _case(args)
    if args.register not in REGISTERS:
        raise KinError(f"Нет реестра {args.register!r}: {', '.join(REGISTERS)}")
    values = json.loads(args.json_data) if args.json_data else {}
    values.update(_pairs(args.set))
    row = case.add(args.register, values, _actor(args))
    _print_row(args, row)
    return 0


def cmd_update(args) -> int:
    case = _case(args)
    changes = _pairs(args.pairs)
    for item in args.append or []:
        k, v = item.split("=", 1)
        _, row = case.get(args.id)
        changes[k] = join_ids(split_ids(row.get(k, "")) + split_ids(v))
    if not changes:
        raise KinError("Нечего менять: укажите поле=значение")
    row = case.update(args.id, changes, _actor(args))
    _print_row(args, row, "обновлено")
    return 0


def cmd_show(args) -> int:
    case = _case(args)
    register, row = case.get(args.id)
    related = {}
    for name, reg in REGISTERS.items():
        for f in reg["fields"]:
            if f.get("ref") == register:
                for r in case.rows(name):
                    if args.id in split_ids(r.get(f["name"], "")):
                        related.setdefault(name, []).append(r[reg["id"]])
    data = {"register": register, "row": row, "referenced_by": {k: sorted(set(v)) for k, v in related.items()}}
    if register == "persons" and row.get("merged_into"):
        data["resolved_to"] = case.resolve_person(args.id)
    text = [f"{args.id} ({REGISTERS[register]['file']})"]
    text += [f"  {k}: {v}" for k, v in row.items() if v]
    if data.get("resolved_to"):
        text.append(f"  → слит в {data['resolved_to']}")
    for name, ids in data["referenced_by"].items():
        text.append(f"  ссылаются из {name}: {', '.join(ids)}")
    _out(args, data, "\n".join(text))
    return 0


def cmd_list(args) -> int:
    case = _case(args)
    if args.register not in REGISTERS:
        raise KinError(f"Нет реестра {args.register!r}: {', '.join(REGISTERS)}")
    rows = case.rows(args.register)
    for k, v in _pairs(args.where).items():
        rows = [r for r in rows if r.get(k, "") == v or v in split_ids(r.get(k, ""))]
    reg = REGISTERS[args.register]
    names = field_names(args.register)
    title_field = next((n for n in ("title", "preferred_label", "name_as_written", "statement", "name", "goal", "query")
                        if n in names), names[1])
    lines = []
    for r in rows:
        st = r.get("status") or r.get("result") or r.get("link_status") or ""
        lines.append(f"{r[reg['id']]}  {('[' + st + '] ') if st else ''}{r.get(title_field, '')}")
    _out(args, rows, "\n".join(lines) or "(пусто)")
    return 0


def cmd_schema(args) -> int:
    regs = [args.register] if args.register else list(REGISTERS)
    out = []
    for name in regs:
        if name not in REGISTERS:
            raise KinError(f"Нет реестра {name!r}")
        reg = REGISTERS[name]
        out.append(f"{name} ({reg['file']}, {reg['prefix']}NNNN) — {reg['title']}")
        for f in reg["fields"][1:]:
            kind = f.get("type", "text")
            extra = f" [{'|'.join(v for v in f['enum'] if v)}]" if kind == "enum" else (f" → {f['ref']}" if "ref" in f else "")
            req = " *" if f.get("required") else ""
            doc = f" — {f['doc']}" if f.get("doc") else ""
            out.append(f"  {f['name']}{req}: {kind}{extra}{doc}")
    if not args.register:
        out.append(f"\nДаты: {SCHEMA['date_format']}\nСписки ID — через «{SCHEMA['id_list_separator']}». * — обязательно.")
    _out(args, {k: REGISTERS[k] for k in regs}, "\n".join(out))
    return 0


# ---------------------------------------------------------------- merge


def cmd_merge(args) -> int:
    """Слияние ошибочно разделённых людей — только с основанием: identity-утверждение ≥ corroborated или --force."""
    case = _case(args)
    dup, into = args.duplicate, args.into
    for pid in (dup, into):
        case.get(pid)
    if case.resolve_person(into) == dup:
        raise KinError("Слияние создаст цикл")
    basis = None
    for c in case.rows("claims"):
        if (c["claim_type"] == "identity" and {dup, into} <= set(split_ids(c["subject_person_ids"]))
                and c["status"] in ("corroborated", "strongly-corroborated")):
            basis = c["claim_id"]
    if not basis and not args.force:
        raise KinError(f"Нет основания слить {dup} и {into}: нужно утверждение identity с обоими ID в статусе corroborated "
                       "(две независимые группы источников). Пока — отметьте возможное тождество "
                       "(claim identity со статусом hypothesis) и держите записи раздельно. "
                       "Осознанно вопреки правилу — --force --reason «…».")
    reason = args.reason or (f"Тождество подтверждено {basis}" if basis else "")
    if not reason:
        raise KinError("--force требует --reason")
    case.update(dup, {"status": "duplicate", "merged_into": into,
                      "merge_rationale": f"Дубликат {into}: {reason}" + (" [принудительно]" if not basis else "")},
                _actor(args))
    print(f"{dup} слит в {into}. Упоминания, утверждения и связи {dup} сохранены и читаются как {into}. "
          f"Отменить: kin person unmerge {dup} --reason «…»")
    return 0


def cmd_unmerge(args) -> int:
    case = _case(args)
    _, row = case.get(args.id)
    if not row.get("merged_into"):
        raise KinError(f"{args.id} не слит")
    case.update(args.id, {"status": args.status, "merged_into": "",
                          "merge_rationale": f"Разделён с {row['merged_into']}: {args.reason} (было: {row['merge_rationale']})"},
                _actor(args))
    print(f"{args.id} снова отдельная личность (status={args.status})")
    return 0


# ---------------------------------------------------------------- настройки дела

CASE_KEYS = {"title": str, "language": str, "root_person": str, "privacy.living_cutoff_years": int}
LINE_FIELDS = ("id", "title", "surname", "state", "where", "focus", "color")


def _save_config(case: Case, actor: str, op: str, data: dict) -> None:
    with case.lock():
        path = case.root / "case.json"
        path.write_text(json.dumps(case.config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        case.journal(actor, op, "case.json", data)


def cmd_case_set(args) -> int:
    case = _case(args)
    changes = _pairs(args.pairs)
    for key, value in changes.items():
        if key not in CASE_KEYS:
            raise KinError(f"Ключ {key!r}: допустимо {', '.join(CASE_KEYS)}")
        if key == "root_person" and value:
            case.get(value)
        if key == "language" and value not in ("ru", "en"):
            raise KinError("language: ru или en")
        target, leaf = case.config, key
        if "." in key:
            head, leaf = key.split(".", 1)
            target = case.config.setdefault(head, {})
        target[leaf] = CASE_KEYS[key](value)
    _save_config(case, _actor(args), "case-set", changes)
    print("case.json обновлён: " + ", ".join(changes))
    return 0


def cmd_line(args) -> int:
    """Линии поиска (ветви) для схемы: состояние, где ищем, цвет."""
    case = _case(args)
    lines = case.config.setdefault("lines", [])
    values = _pairs(args.pairs)
    unknown = set(values) - set(LINE_FIELDS)
    if unknown:
        raise KinError(f"Поля линии: {', '.join(LINE_FIELDS)}")
    if args.action == "list":
        _out(args, lines, "\n".join(f"{l['id']}: {l.get('title', '')} — {l.get('state', '')}" for l in lines) or "(нет линий)")
        return 0
    if not re.fullmatch(r"[a-z0-9-]+", args.id or ""):
        raise KinError("ID линии — латиница, цифры, дефис")
    existing = next((l for l in lines if l["id"] == args.id), None)
    if args.action == "add":
        if existing:
            raise KinError(f"Линия {args.id} уже есть")
        lines.append({"id": args.id, **values})
    else:
        if not existing:
            raise KinError(f"Нет линии {args.id}")
        existing.update(values)
    _save_config(case, _actor(args), f"line-{args.action}", {"id": args.id, **values})
    print(f"Линия {args.id}: сохранено")
    return 0


# ---------------------------------------------------------------- audit / status / site / doctor


def cmd_audit(args) -> int:
    result = audit.run(_case(args))
    _out(args, result, audit.format_text(result))
    if result["errors"] or (args.strict and result["warnings"]):
        return 1
    return 0


def cmd_status(args) -> int:
    s = status.collect(_case(args))
    _out(args, s, status.format_text(s))
    return 0


def cmd_publish(args) -> int:
    case = _case(args)
    _require_clean_audit(case, args)
    path, data, hidden = publish.write(case, args.profile)
    _out(args, {"path": str(path), "persons": len(data["persons"]), "hidden": hidden},
         f"Публикационный набор ({args.profile}): {path}\nЛюдей: {len(data['persons'])}, скрыто: {len(hidden)}")
    return 0


def _require_clean_audit(case: Case, args) -> None:
    result = audit.run(case)
    if result["errors"] and not getattr(args, "allow_errors", False):
        raise KinError(f"Сборка остановлена: в аудите {len(result['errors'])} ошибок (kin audit). "
                       "Посмотреть черновик всё равно — --allow-errors (только profile private).")
    if result["errors"] and args.profile == "public":
        raise KinError("Публичная сборка невозможна при ошибках аудита.")


def cmd_site_build(args) -> int:
    case = _case(args)
    _require_clean_audit(case, args)
    out = site.build(case, args.profile)
    _out(args, {"path": str(out)}, f"Сайт ({args.profile}) собран: {out}\nПросмотр: kin site serve --profile {args.profile}")
    return 0


def cmd_site_serve(args) -> int:
    case = _case(args)
    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.i_know_its_public:
        raise KinError("serve слушает только localhost. Для внешнего адреса — --i-know-its-public и profile public.")
    if args.rebuild or not (case.root / "site" / args.profile / "index.html").is_file():
        _require_clean_audit(case, args)
        site.build(case, args.profile)
    site.serve(case, args.profile, args.port, args.host)
    return 0


def _inside_git_repo_root(path: Path) -> Path | None:
    try:
        out = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    except OSError:
        return None
    return Path(out.stdout.strip()) if out.returncode == 0 else None


def cmd_doctor(args) -> int:
    checks = []

    def check(ok: bool, text: str, hint: str = ""):
        checks.append({"ok": ok, "text": text, "hint": hint})

    check(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]} (нужно ≥ 3.10)")
    try:
        case = _case(args)
    except KinError as e:
        check(False, "Папка дела", str(e))
        case = None
    if case:
        check(True, f"Дело: {case.root} (схема v{case.config['schema_version']})")
        top = _inside_git_repo_root(case.root)
        if top is None:
            check(False, "Дело не под git", "git init в папке дела — история изменений и перенос (git clone)")
        else:
            is_kit = (top / "skills" / "kinship-kit" / "kin").is_dir()
            check(not is_kit, f"Git-репозиторий дела: {top}",
                  "Дело внутри публичного репозитория набора — перенесите папку дела!" if is_kit else "")
            remote = subprocess.run(["git", "-C", str(top), "remote", "-v"], capture_output=True, text=True).stdout
            if "github.com" in remote or "gitlab.com" in remote:
                check(True, "У репозитория дела есть внешний remote — убедитесь, что он ПРИВАТНЫЙ",
                      remote.splitlines()[0] if remote else "")
        res = audit.run(case)
        check(not res["errors"], f"Аудит: ошибок {len(res['errors'])}, предупреждений {len(res['warnings'])}",
              "kin audit" if res["errors"] else "")
        gi = (case.root / ".gitignore")
        check(gi.is_file() and ".kin/" in gi.read_text(encoding="utf-8"), ".gitignore дела исключает производные папки")
    bad = [c for c in checks if not c["ok"]]
    text = "\n".join(("✓ " if c["ok"] else "✗ ") + c["text"] + (f"\n    {c['hint']}" if c["hint"] else "") for c in checks)
    _out(args, checks, text)
    return 1 if bad else 0


# ---------------------------------------------------------------- парсер


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--case", help="Папка дела (иначе KIN_CASE или поиск case.json вверх)")
    p.add_argument("--as", dest="actor", help="Кто вносит изменение (роль/человек), в журнал")
    p.add_argument("--json", action="store_true", help="Вывод JSON")


def _opts(p: argparse.ArgumentParser, mapping: dict, required: tuple = ()) -> None:
    for opt in mapping:
        if opt == "file":
            continue
        p.add_argument("--" + opt.replace("_", "-"), dest=opt, required=opt in required)
    p.add_argument("--set", action="append", metavar="ПОЛЕ=ЗНАЧЕНИЕ", help="Любое поле реестра")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="kin", description="kinship-kit: дело генеалогического исследования")
    ap.add_argument("--version", action="version", version=f"kin {__version__} (схема v{SCHEMA['schema_version']})")
    ap.add_argument("--case", dest="case_global", help="Папка дела (можно и после команды)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="Создать папку дела (приватную, отдельно от набора)")
    p.add_argument("dir")
    p.add_argument("--title")
    p.add_argument("--lang", default="ru", choices=["ru", "en"])
    p.add_argument("--no-git", action="store_true")
    p.set_defaults(fn=cmd_init)

    src = sub.add_parser("source", help="Источники").add_subparsers(dest="sub", required=True)
    p = src.add_parser("add", help="Зарегистрировать источник: копия в sources/ + sha256")
    p.add_argument("file", nargs="?")
    _opts(p, SOURCE_MAP)
    _common(p)
    p.set_defaults(fn=cmd_source_add)

    per = sub.add_parser("person", help="Люди").add_subparsers(dest="sub", required=True)
    p = per.add_parser("add")
    _opts(p, PERSON_MAP, required=("label", "living", "status"))
    _common(p)
    p.set_defaults(fn=_add("persons", PERSON_MAP))
    p = per.add_parser("merge", help="Слить дубликат (нужно основание)")
    p.add_argument("duplicate")
    p.add_argument("into")
    p.add_argument("--reason")
    p.add_argument("--force", action="store_true")
    _common(p)
    p.set_defaults(fn=cmd_merge)
    p = per.add_parser("unmerge", help="Отменить слияние")
    p.add_argument("id")
    p.add_argument("--reason", required=True)
    p.add_argument("--status", default="candidate")
    _common(p)
    p.set_defaults(fn=cmd_unmerge)

    for name, register, mapping, req in (("mention", "mentions", MENTION_MAP, ("artifact", "name")),
                                         ("claim", "claims", CLAIM_MAP, ("type", "subject", "statement", "status"))):
        g = sub.add_parser(name, help=REGISTERS[register]["title"]).add_subparsers(dest="sub", required=True)
        p = g.add_parser("add")
        _opts(p, mapping, required=req)
        _common(p)
        p.set_defaults(fn=_add(register, mapping))

    g = sub.add_parser("rel", help="Связи").add_subparsers(dest="sub", required=True)
    p = g.add_parser("add", help="kin rel add P-0001 parent-of P-0002 --sources A-0001 --status single-source")
    p.add_argument("a")
    p.add_argument("type", choices=["parent-of", "spouse-of", "sibling-of", "other"])
    p.add_argument("b")
    _opts(p, REL_MAP, required=("status",))
    _common(p)
    p.set_defaults(fn=cmd_rel_add)

    p = sub.add_parser("add", help="Добавить запись в любой реестр (hypotheses, tasks, searches, places …)")
    p.add_argument("register", choices=list(REGISTERS))
    p.add_argument("--data", dest="json_data", help="JSON-объект полей")
    p.add_argument("--set", action="append", metavar="ПОЛЕ=ЗНАЧЕНИЕ")
    _common(p)
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("update", help="Изменить поля записи: kin update C-0003 status=corroborated rationale=…")
    p.add_argument("id")
    p.add_argument("pairs", nargs="*")
    p.add_argument("--append", action="append", metavar="ПОЛЕ=ID", help="Добавить ID в список")
    _common(p)
    p.set_defaults(fn=cmd_update)

    p = sub.add_parser("show", help="Запись и ссылки на неё")
    p.add_argument("id")
    _common(p)
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("list", help="Список записей реестра")
    p.add_argument("register", choices=list(REGISTERS))
    p.add_argument("--where", action="append", metavar="ПОЛЕ=ЗНАЧЕНИЕ")
    _common(p)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("schema", help="Поля реестров и словари")
    p.add_argument("register", nargs="?")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_schema)

    g = sub.add_parser("case", help="Настройки дела (case.json)").add_subparsers(dest="sub", required=True)
    p = g.add_parser("set", help="kin case set root_person=P-0001 title=…")
    p.add_argument("pairs", nargs="+")
    _common(p)
    p.set_defaults(fn=cmd_case_set)
    p = g.add_parser("line", help="Линии поиска: kin case line add vetluginy title=… color=#b5651d")
    p.add_argument("action", choices=["add", "update", "list"])
    p.add_argument("id", nargs="?")
    p.add_argument("pairs", nargs="*")
    _common(p)
    p.set_defaults(fn=cmd_line)

    p = sub.add_parser("audit", help="Проверка целостности и доказательности")
    p.add_argument("--strict", action="store_true", help="Код 1 и при предупреждениях")
    _common(p)
    p.set_defaults(fn=cmd_audit)

    p = sub.add_parser("status", help="Состояние исследования и следующий шаг")
    _common(p)
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("publish", help="Публикационный набор (фильтр приватности + проверка утечек)")
    p.add_argument("--profile", default="private", choices=publish.PROFILES)
    p.add_argument("--allow-errors", action="store_true")
    _common(p)
    p.set_defaults(fn=cmd_publish)

    g = sub.add_parser("site", help="Сайт-схема").add_subparsers(dest="sub", required=True)
    p = g.add_parser("build")
    p.add_argument("--profile", default="private", choices=publish.PROFILES)
    p.add_argument("--allow-errors", action="store_true")
    _common(p)
    p.set_defaults(fn=cmd_site_build)
    p = g.add_parser("serve")
    p.add_argument("--profile", default="private", choices=publish.PROFILES)
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--rebuild", action="store_true")
    p.add_argument("--allow-errors", action="store_true")
    p.add_argument("--i-know-its-public", action="store_true")
    _common(p)
    p.set_defaults(fn=cmd_site_serve)

    p = sub.add_parser("doctor", help="Проверка окружения, размещения дела и приватности")
    _common(p)
    p.set_defaults(fn=cmd_doctor)
    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except KinError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"Ошибка JSON: {e}", file=sys.stderr)
        return 1
