"""Команды этапа 2: setup, migrate, next, history, task, hypothesis, search, review, request, agents, site publish, hooks."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import audit, migrations, site, workflow
from .store import REGISTERS, Case, KinError, find_case_dir, split_ids

SKILL_DIR = Path(__file__).resolve().parent.parent
ROLES_DIR = SKILL_DIR / "roles"
TEMPLATES_DIR = SKILL_DIR / "templates" / "tasks"
DENYLIST = Path(os.environ.get("KIN_DENYLIST", Path.home() / ".config" / "kinship-kit" / "denylist.txt"))

TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюяіїєґ",
                    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                     "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya", "i", "yi", "ye", "g"]))


def slug(text: str) -> str:
    out = "".join(TRANSLIT.get(ch, ch) for ch in text.casefold())
    return re.sub(r"[^a-z0-9]+", "-", out).strip("-") or "case"


def frontmatter(path: Path) -> tuple[dict, str]:
    """Простой разбор заголовка «ключ: значение» между --- (без YAML-библиотеки)."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    head, _, body = text[4:].partition("\n---\n")
    meta = {}
    for line in head.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, body.lstrip("\n")


def _case(args) -> Case:
    return Case(find_case_dir(getattr(args, "case", None) or getattr(args, "case_global", None)))


def _actor(args) -> str:
    return getattr(args, "actor", None) or os.environ.get("KIN_ACTOR") or "user"


def _out(args, data, text: str) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2) if getattr(args, "json", False) else text)


# ------------------------------------------------------------------ setup: первый шаг нового пользователя

SETUP_QUESTIONS = """Первый запуск kinship-kit. Ответьте на вопросы (Enter — значение в скобках).
Сведения сохраняются только у вас: в папке дела и в личном стоп-листе вне репозитория."""


def _ask(prompt: str, default: str = "", required: bool = True) -> str:
    while True:
        try:
            value = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip() or default
        except EOFError:
            value = default
        if value or not required:
            return value
        print("  Нужен ответ.")


def _git_global(key: str) -> str:
    try:
        return subprocess.run(["git", "config", "--global", key], capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def cmd_setup(args) -> int:
    """Первый шаг: фамилия (линия поиска), название и папка дела, автор коммитов — указывает сам пользователь."""
    interactive = sys.stdin.isatty() and not args.yes
    if interactive:
        print(SETUP_QUESTIONS)
    surname = args.surname or (interactive and _ask("1. Основная фамилия исследования (линия поиска)")) or ""
    if not surname:
        raise KinError("Укажите --surname (основная фамилия исследования)")
    title = args.title or (interactive and _ask("2. Название дела", f"Род {surname}")) or f"Род {surname}"
    default_dir = str(Path.home() / "kinship-cases" / slug(surname))
    case_dir = args.dir or (interactive and _ask("3. Папка дела (приватная, вне репозитория набора)", default_dir)) or default_dir
    name, email = args.author_name, args.author_email
    if args.anonymous_author:
        name, email = "Исследователь", "researcher@example.invalid"
    if not (name and email) and interactive:
        g_name, g_email = _git_global("user.name"), _git_global("user.email")
        print("4. Автор коммитов в git-истории дела. Виден всем, кому вы дадите копию дела.\n"
              "   Можно псевдоним. " + (f"Глобальные настройки git: {g_name} <{g_email}> — используются, только если вы их введёте." if g_name else ""))
        name = _ask("   Имя автора", "Исследователь")
        email = _ask("   E-mail автора", "researcher@example.invalid")
    if not (name and email):
        raise KinError("Укажите автора коммитов: --author-name и --author-email, либо --anonymous-author. "
                       "Автор не берётся из глобальных настроек git без вашего явного выбора.")
    lang = args.lang or (interactive and _ask("5. Язык дела (ru/en)", "ru")) or "ru"
    clients = args.agents or (interactive and _ask("6. Роли агентов для (claude, codex, both, none)", "both")) or "both"
    deny = not args.no_denylist
    if interactive and not args.no_denylist:
        deny = _ask(f"7. Добавить «{surname}» в личный стоп-лист ({DENYLIST}), чтобы фамилия не попала в публичный репозиторий набора? (да/нет)", "да").casefold().startswith(("д", "y"))

    from .cli import CASE_AGENTS_MD
    from .store import SCHEMA, init_case
    root = init_case(Path(case_dir), title, lang, git=True)
    (root / "AGENTS.md").write_text(CASE_AGENTS_MD.format(title=title, version=SCHEMA["schema_version"]), encoding="utf-8")
    (root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    if (root / ".git").exists():
        for key, value in (("user.name", name), ("user.email", email)):
            subprocess.run(["git", "-C", str(root), "config", key, value], check=True)
    case = Case(root)
    line_id = slug(surname)
    with case.lock():
        case.config["lines"] = [{"id": line_id, "title": surname, "surname": surname, "state": "начинаем", "color": "#b5651d"}]
        case.config["owner"] = {"author_name": name, "author_email": email, "set_up": dt.date.today().isoformat()}
        case.save_config(_actor(args), "setup", {"surname": surname, "title": title})
    installed = []
    if clients != "none":
        which = {"claude": ["claude"], "codex": ["codex"], "both": ["claude", "codex"]}.get(clients, ["claude", "codex"])
        installed = install_agents(root, "research", which)
    if deny:
        DENYLIST.parent.mkdir(parents=True, exist_ok=True)
        existing = DENYLIST.read_text(encoding="utf-8").splitlines() if DENYLIST.exists() else []
        if surname not in existing:
            with open(DENYLIST, "a", encoding="utf-8") as fh:
                fh.write(f"{surname}\n")
    kit = SKILL_DIR.parent.parent
    if args.kit_author and (kit / ".git").exists():
        for key, value in (("user.name", name), ("user.email", email)):
            subprocess.run(["git", "-C", str(kit), "config", key, value], check=True)
    if (root / ".git").exists():
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", f"Дело создано: {title}"], check=False)
    print(f"✓ Дело: {root}\n✓ Линия поиска: {surname} ({line_id})\n✓ Автор коммитов дела: {name} <{email}>"
          + (f"\n✓ Роли агентов: {len(installed)} файлов" if installed else "")
          + (f"\n✓ Стоп-лист: {DENYLIST}" if deny else "")
          + (f"\n✓ Автор коммитов набора: {name} <{email}>" if args.kit_author else "")
          + f"\nДальше: cd {root} && kin status")
    return 0


# ------------------------------------------------------------------ миграции, next, history


def cmd_migrate(args) -> int:
    root = find_case_dir(getattr(args, "case", None) or getattr(args, "case_global", None))
    steps = migrations.migrate(root, _actor(args), dry_run=args.dry_run)
    if not steps:
        print("Схема дела актуальна.")
    else:
        print(("План миграции:\n- " if args.dry_run else "Миграция выполнена (резервная копия — .kin/backup-…):\n- ") + "\n- ".join(steps))
    return 0


def cmd_next(args) -> int:
    case = _case(args)
    ranked, excluded = workflow.rank_tasks(case)
    nxt = workflow.next_summary(case)
    lines = [f"▶ {nxt['text']}" if nxt else "Нет доступных задач: поставьте новую (kin task new …) или разберите гипотезы."]
    if ranked:
        lines.append("\nОчередь (оценка — ценность, приоритет, гипотеза, стоимость, доступ, попытки):")
        lines += [f"- {t['id']} [{t['score']}] {t['goal']} — {', '.join(t['reasons'])}" for t in ranked[: args.limit]]
    if excluded:
        lines.append("\nНедоступно сейчас:")
        lines += [f"- {t['id']} {t['goal']} — {t['reason']}" for t in excluded]
    _out(args, {"next": nxt, "ranked": ranked, "excluded": excluded}, "\n".join(lines))
    return 0


def cmd_history(args) -> int:
    case = _case(args)
    items = workflow.history(case, args.id)
    text = "\n".join(f"{j.get('ts')} {j.get('actor')}: {j.get('op')} {j.get('id')} {json.dumps(j.get('data', {}), ensure_ascii=False)}"
                     for j in items) or "(нет записей)"
    _out(args, items, text)
    return 0


# ------------------------------------------------------------------ задачи


def cmd_task_new(args) -> int:
    case = _case(args)
    tpl = TEMPLATES_DIR / f"{args.type}.md"
    if not tpl.is_file():
        raise KinError(f"Нет шаблона {args.type!r}: {', '.join(sorted(p.stem for p in TEMPLATES_DIR.glob('*.md')))}")
    meta, body = frontmatter(tpl)
    values = {"task_type": args.type, "goal": args.goal, "hypothesis_id": args.hypothesis or "",
              "expected_result": args.expected or "", "sources_to_check": args.sources or "",
              "assignee": args.assignee or meta.get("assignee", ""), "priority": args.priority or "3",
              "evidential_value": args.value or meta.get("evidential_value", ""), "cost": args.cost or meta.get("cost", ""),
              "access": args.access or meta.get("access", ""), "external_service": meta.get("external_service", ""),
              "status": "ready" if not args.planned else "planned"}
    with case.lock():
        row = case.add("tasks", values, _actor(args))
        tid = row["task_id"]
        hyp = case.index("hypotheses").get(args.hypothesis or "", {})
        persons = case.index("persons")
        names = ", ".join(f"{p} {persons[p]['preferred_label']}" for p in split_ids(hyp.get("person_ids")) if p in persons)
        text = body.format_map(_Safe(task_id=tid, goal=args.goal, hypothesis=args.hypothesis or "—",
                                     hypothesis_statement=hyp.get("statement", "—"), persons=names or "—",
                                     sources_to_check=args.sources or "—", expected_result=args.expected or "—"))
        brief = case.root / "tasks" / f"{tid}.md"
        brief.parent.mkdir(exist_ok=True)
        brief.write_text(text, encoding="utf-8")
        case.update(tid, {"brief": f"tasks/{tid}.md"}, _actor(args))
    _out(args, row, f"{tid} создана ({meta.get('title', args.type)}); задание: tasks/{tid}.md")
    return 0


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def cmd_task_action(args) -> int:
    case = _case(args)
    if args.action == "consent":
        if args.granted == args.denied:
            raise KinError("Укажите --granted или --denied")
        row = workflow.consent(case, args.id, args.granted, args.by or "", args.reason or "")
    else:
        row = workflow.task_transition(case, args.id, args.action, _actor(args), args.reason or "",
                                       split_ids(args.evidence or ""), args.next or "")
    _out(args, row, f"{args.id}: {row['status']}" + (f" (согласие: {row['user_consent']})" if args.action == "consent" else ""))
    return 0


def cmd_hypothesis_status(args) -> int:
    case = _case(args)
    row = workflow.hypothesis_status(case, args.id, args.status, args.reason or "", _actor(args), args.reopen or "")
    _out(args, row, f"{args.id}: {row['status']}")
    return 0


# ------------------------------------------------------------------ поиск

SEARCH_MAP = {"date": "date", "task": "task_id", "persons": "target_person_ids", "source": "source", "query": "query",
              "variants": "variants", "period": "period", "limits": "source_limits", "result": "result",
              "artifacts": "artifact_ids", "allowed": "allowed_conclusions", "disallowed": "disallowed_conclusions",
              "repeat_when": "repeat_when", "new_basis": "new_basis", "next": "next_step"}


def cmd_search_add(args) -> int:
    case = _case(args)
    values = {f: getattr(args, o) for o, f in SEARCH_MAP.items() if getattr(args, o, None)}
    values.setdefault("date", dt.date.today().isoformat())
    with case.lock():
        workflow.guard_search(case, values)
        row = case.add("searches", values, _actor(args))
        if values.get("task_id"):
            case.update(values["task_id"], {}, _actor(args), append={"search_ids": row["search_id"]})
    _out(args, row, f"{row['search_id']} записан" + (f" (задача {values['task_id']})" if values.get("task_id") else ""))
    return 0


def cmd_search_check(args) -> int:
    case = _case(args)
    prev = workflow.similar_searches(case, args.source, args.query or "", args.period or "")
    _out(args, prev, "\n".join(f"- {s['search_id']} {s['date']} {s['source']}: {s.get('query', '')} → {s['result']}"
                               for s in prev) or "Похожих безрезультатных поисков нет.")
    return 0


# ------------------------------------------------------------------ ревью


def cmd_review(args) -> int:
    case = _case(args)
    if args.action == "checklist":
        items = workflow.checklist(case, args.id)
        _out(args, items, "\n".join(f"[{i['level']}] {i['text']}" for i in items) or "Автоматических замечаний нет.")
        return 0
    if args.action == "request":
        row = workflow.request_review(case, args.id, args.reviewer or "Evidence Reviewer", _actor(args))
        _out(args, row, f"{row['review_id']} запрошено для {args.id}. Исполнители: {row['authors'] or '—'}.\n"
                        f"Замечания чек-листа: {row['auto_findings'] or 'нет'}\n"
                        f"Проверяет другая роль: kin review submit {row['review_id']} --as \"Evidence Reviewer\" …")
        return 0
    if args.action == "submit":
        row = workflow.submit_review(case, args.id, args.verdict or "", args.findings or "",
                                     split_ids(args.checked or ""), _actor(args))
        _out(args, row, f"{args.id}: {row['status']}" + (" — нужно решение человека (kin review decide)" if row.get("human_required") == "yes" and row["status"] == "passed" else ""))
        return 0
    if args.action == "decide":
        if not args.by:
            raise KinError("Решение принимает человек: --by «Имя»")
        row = workflow.human_decide(case, args.id, args.by, not args.reject, args.note or "")
        _out(args, row, f"{args.id}: {row['human_decision']}")
        return 0
    raise KinError(args.action)


# ------------------------------------------------------------------ запросы в архивы


def cmd_request(args) -> int:
    case = _case(args)
    if args.action == "add":
        values = {"task_id": args.task or "", "recipient": args.recipient, "subject": args.subject,
                  "channel": args.channel or "", "text_file": args.text or "", "status": "draft" if not args.ready else "ready",
                  "cost": args.cost or ""}
        if values["text_file"] and not (case.root / values["text_file"]).is_file():
            raise KinError(f"Нет файла {values['text_file']} в папке дела")
        row = case.add("requests", values, _actor(args))
    elif args.action == "sent":
        sent = args.date or dt.date.today().isoformat()
        try:
            due = args.due or (dt.date.fromisoformat(sent) + dt.timedelta(days=30)).isoformat()
        except ValueError:
            raise KinError("--date в формате ГГГГ-ММ-ДД") from None
        row = case.update(args.id, {"status": "sent", "sent_date": sent, "due_date": due,
                                    "reference_number": args.number or ""}, _actor(args))
    elif args.action == "answer":
        row = case.update(args.id, {"status": "refused" if args.refused else "answered"}, _actor(args),
                          append={"response_artifact_ids": args.artifacts or ""})
    else:
        raise KinError(args.action)
    _out(args, row, f"{row['request_id']}: {row['status']}" + (f", срок ответа {row['due_date']}" if row.get("due_date") else ""))
    return 0


# ------------------------------------------------------------------ роли агентов


def _toml_str(text: str) -> str:
    return '"""\n' + text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"') + '"""'


def install_agents(target: Path, which_set: str, clients: list[str]) -> list[Path]:
    """roles/*.md → .claude/agents/<name>.md (Claude Code) и .codex/agents/<name>.toml (Codex)."""
    written = []
    for role in sorted(ROLES_DIR.glob("*.md")):
        meta, body = frontmatter(role)
        sets = {s.strip() for s in meta.get("set", "research").split(",")}
        if which_set != "all" and which_set not in sets:
            continue
        name, desc = meta["name"], meta["description"]
        header = f"<!-- Сгенерировано kin agents install из roles/{role.name}; правьте исходник роли. -->\n"
        if "claude" in clients:
            p = target / ".claude" / "agents" / f"{name}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"---\nname: {name}\ndescription: {desc}\ntools: {meta.get('tools', 'Read, Grep, Glob, Bash')}\n---\n"
                         f"{header}\n{body}", encoding="utf-8")
            written.append(p)
        if "codex" in clients:
            p = target / ".codex" / "agents" / f"{name}.toml"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"# Сгенерировано kin agents install из roles/{role.name}\nname = {json.dumps(name)}\n"
                         f"description = {json.dumps(desc, ensure_ascii=False)}\n"
                         f"developer_instructions = {_toml_str(body)}\n", encoding="utf-8")
            written.append(p)
    return written


def cmd_agents_install(args) -> int:
    if args.target:
        target = Path(args.target).expanduser().resolve()
    else:
        target = find_case_dir(getattr(args, "case", None) or getattr(args, "case_global", None))
    clients = [c for c in ("claude", "codex") if getattr(args, c)] or ["claude", "codex"]
    written = install_agents(target, args.set, clients)
    print("\n".join(f"✓ {p.relative_to(target)}" for p in written) or "Нет ролей для набора " + args.set)
    return 0


# ------------------------------------------------------------------ публикация и хук


def cmd_site_publish(args) -> int:
    """Собрать (аудит + фильтр + проверка утечек) и скопировать в папку выкладки. Ничего не отправляет в сеть сам."""
    case = _case(args)
    target = Path(args.to or case.config.get("publish", {}).get(args.profile, "")).expanduser()
    if not str(target) or str(target) == ".":
        raise KinError("Укажите --to <папка выкладки> (или case.json → publish.<профиль>)")
    target = target.resolve()
    if args.profile == "private" and not args.password_protected:
        raise KinError("Приватная сборка содержит живых: выкладывайте только за паролем и подтвердите --password-protected "
                       "(рецепт Caddy + basic_auth — docs/deploy.md).")
    if case.root == target or case.root in target.parents:
        if target != case.root / "site" / args.profile:
            raise KinError("Папка выкладки внутри папки дела — укажите внешнюю папку веб-сервера")
    res = audit.run(case)
    if res["errors"]:
        raise KinError(f"Публикация остановлена: ошибок аудита {len(res['errors'])} (kin audit)")
    out = site.build(case, args.profile)
    files = sorted(p for p in out.rglob("*") if p.is_file())
    if args.dry_run:
        print(f"Проверка пройдена. Будет скопировано в {target}:\n" + "\n".join(f"- {p.relative_to(out)}" for p in files))
        return 0
    target.mkdir(parents=True, exist_ok=True)
    for old in target.iterdir():  # синхронизация: удалённое из сборки удаляется и с сайта
        if old.name not in {p.relative_to(out).parts[0] for p in files}:
            shutil.rmtree(old) if old.is_dir() else old.unlink()
    for p in files:
        dest = target / p.relative_to(out)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
    case.journal(_actor(args), "publish", args.profile, {"to": str(target), "files": len(files)})
    print(f"Опубликовано ({args.profile}): {len(files)} файлов → {target}")
    return 0


HOOK = """#!/bin/sh
# kinship-kit: после коммита пересобрать сайт дела{publish_note}. Журнал: .kin/hook.log
cd "$(git rev-parse --show-toplevel)" || exit 0
{{ date; {cmd}; }} >> .kin/hook.log 2>&1 || echo "kin: сборка сайта не прошла — см. .kin/hook.log" >&2
"""


def cmd_hooks_install(args) -> int:
    case = _case(args)
    git_dir = case.root / ".git"
    if not git_dir.is_dir():
        raise KinError("Дело не под git: git init в папке дела")
    kin = f'python3 "{SKILL_DIR / "kin.py"}"'
    if args.publish_to:
        cmd = f'{kin} site publish --profile {args.profile} --to "{args.publish_to}"' + (" --password-protected" if args.profile == "private" else "")
        note = f" и выложить в {args.publish_to}"
    else:
        cmd, note = f"{kin} site build --profile {args.profile}", ""
    hook = git_dir / "hooks" / "post-commit"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(HOOK.format(cmd=cmd, publish_note=note), encoding="utf-8")
    hook.chmod(0o755)
    print(f"✓ {hook.relative_to(case.root)}: {cmd}")
    return 0


# ------------------------------------------------------------------ парсер


def add_commands(sub, common) -> None:
    p = sub.add_parser("setup", help="Первый шаг: фамилия, название дела, автор коммитов (вопросы или флаги)")
    p.add_argument("--surname")
    p.add_argument("--title")
    p.add_argument("--dir")
    p.add_argument("--author-name")
    p.add_argument("--author-email")
    p.add_argument("--anonymous-author", action="store_true", help="Автор коммитов — «Исследователь»")
    p.add_argument("--lang", choices=["ru", "en"])
    p.add_argument("--agents", choices=["claude", "codex", "both", "none"])
    p.add_argument("--no-denylist", action="store_true", help="Не добавлять фамилию в личный стоп-лист")
    p.add_argument("--kit-author", action="store_true", help="Того же автора задать и копии набора (для правок набора)")
    p.add_argument("--yes", action="store_true", help="Без вопросов: только флаги")
    p.add_argument("--as", dest="actor")
    p.set_defaults(fn=cmd_setup)

    p = sub.add_parser("migrate", help="Обновить схему дела (с резервной копией)")
    p.add_argument("--dry-run", action="store_true")
    common(p)
    p.set_defaults(fn=cmd_migrate)

    p = sub.add_parser("next", help="Следующее действие: ранжирование задач с причинами и ограничениями")
    p.add_argument("--limit", type=int, default=10)
    common(p)
    p.set_defaults(fn=cmd_next)

    p = sub.add_parser("history", help="История изменений и решений по записи")
    p.add_argument("id")
    common(p)
    p.set_defaults(fn=cmd_history)

    g = sub.add_parser("task", help="Исследовательские задачи").add_subparsers(dest="sub", required=True)
    p = g.add_parser("new", help="Задача по шаблону: " + ", ".join(sorted(x.stem for x in TEMPLATES_DIR.glob("*.md"))))
    p.add_argument("type")
    p.add_argument("--goal", required=True)
    p.add_argument("--hypothesis")
    p.add_argument("--expected")
    p.add_argument("--sources", help="Что проверить (архивы, базы, фонды)")
    p.add_argument("--assignee")
    p.add_argument("--priority")
    p.add_argument("--value", help="Доказательная ценность 1–5")
    p.add_argument("--cost", choices=["free", "paid", "unknown"])
    p.add_argument("--access", choices=["online", "request", "onsite", "unknown"])
    p.add_argument("--planned", action="store_true", help="Статус planned вместо ready")
    common(p)
    p.set_defaults(fn=cmd_task_new)
    for action, help_text in (("start", "Взять в работу"), ("ready", "Готова к старту"), ("block", "Заблокировать (--reason)"),
                              ("review", "На ревью"), ("done", "Завершить с результатом (--reason, --evidence)"),
                              ("close", "Закрыть без находки (нужен записанный поиск)"),
                              ("consent", "Решение пользователя по платному/внешнему (--granted|--denied --by)")):
        p = g.add_parser(action, help=help_text)
        p.add_argument("id")
        p.add_argument("--reason")
        p.add_argument("--evidence")
        p.add_argument("--next")
        p.add_argument("--granted", action="store_true")
        p.add_argument("--denied", action="store_true")
        p.add_argument("--by")
        common(p)
        p.set_defaults(fn=cmd_task_action, action=action)

    g = sub.add_parser("hypothesis", help="Гипотезы").add_subparsers(dest="sub", required=True)
    p = g.add_parser("status", help="Решение по гипотезе с обоснованием (accepted/rejected — после ревью)")
    p.add_argument("id")
    p.add_argument("status", choices=["open", "testing", "supported", "weakened", "rejected", "parked", "accepted"])
    p.add_argument("--reason", required=True)
    p.add_argument("--reopen", help="Условия повторного открытия")
    common(p)
    p.set_defaults(fn=cmd_hypothesis_status)

    g = sub.add_parser("search", help="Журнал поиска").add_subparsers(dest="sub", required=True)
    p = g.add_parser("add", help="Записать поиск (и пустой); повтор без --new-basis запрещён")
    for opt in SEARCH_MAP:
        p.add_argument("--" + opt.replace("_", "-"), dest=opt, required=opt in ("source", "result"))
    common(p)
    p.set_defaults(fn=cmd_search_add)
    p = g.add_parser("check", help="Был ли уже такой безрезультатный поиск")
    p.add_argument("--source", required=True)
    p.add_argument("--query")
    p.add_argument("--period")
    common(p)
    p.set_defaults(fn=cmd_search_check)

    g = sub.add_parser("review", help="Независимое ревью").add_subparsers(dest="sub", required=True)
    for action in ("request", "checklist", "submit", "decide"):
        p = g.add_parser(action)
        p.add_argument("id")
        p.add_argument("--reviewer")
        p.add_argument("--verdict", choices=["passed", "failed", "needs-work"])
        p.add_argument("--findings")
        p.add_argument("--checked", help="Прочитанные первичные источники A-…;A-…")
        p.add_argument("--by")
        p.add_argument("--reject", action="store_true")
        p.add_argument("--note")
        common(p)
        p.set_defaults(fn=cmd_review, action=action)

    g = sub.add_parser("request", help="Запросы в архивы").add_subparsers(dest="sub", required=True)
    p = g.add_parser("add")
    p.add_argument("--recipient", required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--task")
    p.add_argument("--channel", choices=["gov-portal", "archive-portal", "email", "post", "in-person", "other"])
    p.add_argument("--text", help="Файл с текстом в папке дела")
    p.add_argument("--cost")
    p.add_argument("--ready", action="store_true")
    common(p)
    p.set_defaults(fn=cmd_request, action="add")
    p = g.add_parser("sent")
    p.add_argument("id")
    p.add_argument("--date")
    p.add_argument("--number")
    p.add_argument("--due")
    common(p)
    p.set_defaults(fn=cmd_request, action="sent")
    p = g.add_parser("answer")
    p.add_argument("id")
    p.add_argument("--artifacts", help="Ответ, зарегистрированный как источник")
    p.add_argument("--refused", action="store_true")
    common(p)
    p.set_defaults(fn=cmd_request, action="answer")

    g = sub.add_parser("agents", help="Роли агентов").add_subparsers(dest="sub", required=True)
    p = g.add_parser("install", help="roles/*.md → .claude/agents и .codex/agents")
    p.add_argument("--target", help="Куда (по умолчанию — папка дела)")
    p.add_argument("--set", default="research", choices=["research", "dev", "all"])
    p.add_argument("--claude", action="store_true")
    p.add_argument("--codex", action="store_true")
    common(p)
    p.set_defaults(fn=cmd_agents_install)

    g = sub.add_parser("hooks", help="Git-хуки дела").add_subparsers(dest="sub", required=True)
    p = g.add_parser("install", help="post-commit: пересобрать сайт (и выложить, если --publish-to)")
    p.add_argument("--profile", default="private", choices=["private", "public"])
    p.add_argument("--publish-to")
    common(p)
    p.set_defaults(fn=cmd_hooks_install)


def add_site_publish(site_sub, common) -> None:
    p = site_sub.add_parser("publish", help="Собрать с проверками и скопировать в папку веб-сервера")
    p.add_argument("--profile", default="public", choices=["private", "public"])
    p.add_argument("--to")
    p.add_argument("--password-protected", action="store_true", help="Подтверждение: private выкладывается только за паролем")
    p.add_argument("--dry-run", action="store_true")
    common(p)
    p.set_defaults(fn=cmd_site_publish)


__all__ = ["add_commands", "add_site_publish", "install_agents", "REGISTERS", "argparse"]
