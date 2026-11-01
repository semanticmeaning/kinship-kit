"""Восстановление состояния исследования из данных дела (а не из контекста чата).

Отвечает на вопросы нового сеанса: какие гипотезы активны, какие задачи шли, что проверено и пусто,
что заблокировано, что делать дальше.
"""
from __future__ import annotations

import json

import datetime as dt

from . import audit, feedback, workflow
from .i18n import t
from .store import Case, split_ids

ACTIVE_H = ("open", "testing")
TASK_ORDER = ("in-progress", "in-review", "blocked", "ready", "planned")


def _prio(t: dict) -> int:
    try:
        return int(t.get("priority") or 9)
    except ValueError:
        return 9


def _journal_tail(case: Case, n: int) -> list[dict]:
    p = case.root / "journal.jsonl"
    if not p.is_file():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()[-n:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def collect(case: Case) -> dict:
    a = audit.run(case)
    hyps = [h for h in case.rows("hypotheses") if h["status"] in ACTIVE_H]
    tasks = case.rows("tasks")
    by_status = {s: sorted((t for t in tasks if t["status"] == s), key=_prio) for s in TASK_ORDER}
    negative = [s for s in case.rows("searches") if s["result"] in ("not-found", "blocked", "error", "partial")]
    open_claims = [c for c in case.rows("claims") if c["status"] in ("unresolved", "contradicted")]
    tasks_by_h = {}
    for t in tasks:
        if t.get("hypothesis_id"):
            tasks_by_h.setdefault(t["hypothesis_id"], []).append(t["task_id"])

    nxt = workflow.next_summary(case)
    today = dt.date.today().isoformat()
    requests = [r for r in case.rows("requests") if r["status"] in ("draft", "ready", "sent")]
    reviews = [r for r in case.rows("reviews") if r["status"] == "requested"
               or (r["status"] == "passed" and r.get("human_required") == "yes" and not r.get("human_decision"))]
    return {
        "case": case.config.get("title", ""),
        "path": str(case.root),
        "counts": a["counts"],
        "audit": {"errors": len(a["errors"]), "warnings": len(a["warnings"])},
        "active_hypotheses": [{"id": h["hypothesis_id"], "status": h["status"], "statement": h["statement"],
                               "tasks": tasks_by_h.get(h["hypothesis_id"], [])} for h in hyps],
        "tasks": {s: [{"id": t["task_id"], "goal": t["goal"], "priority": t.get("priority", ""),
                       "assignee": t.get("assignee", ""), "constraints": t.get("constraints", ""),
                       "next_step": t.get("next_step", "")} for t in by_status[s]] for s in TASK_ORDER},
        "checked_negative": [{"id": s["search_id"], "date": s["date"], "source": s["source"], "query": s.get("query", ""),
                              "period": s.get("period", ""), "result": s["result"],
                              "repeat_when": s.get("repeat_when", ""),
                              "persons": split_ids(s.get("target_person_ids"))} for s in negative],
        "open_contradictions": [{"id": c["claim_id"], "statement": c["statement"]} for c in open_claims],
        "recent_changes": [{"ts": j.get("ts"), "actor": j.get("actor"), "op": j.get("op"), "id": j.get("id")}
                           for j in _journal_tail(case, 8)],
        "reviews_pending": [{"id": r["review_id"], "target": r["target_id"], "status": r["status"],
                             "human": r.get("human_required") == "yes"} for r in reviews],
        "requests_open": [{"id": r["request_id"], "recipient": r["recipient"], "subject": r["subject"],
                           "status": r["status"], "due": r.get("due_date", ""),
                           "overdue": bool(r["status"] == "sent" and r.get("due_date") and r["due_date"] < today)}
                          for r in requests],
        "family_reports_pending": len(feedback.pending(case)),
        "next": nxt,
    }


def format_text(s: dict) -> str:
    out = [f"{t('Дело')}: {s['case']}  ({s['path']})",
           f"{t('Записей')}: " + ", ".join(f"{k}={v}" for k, v in s["counts"].items() if v),
           f"{t('Аудит: ошибок')} {s['audit']['errors']}, {t('предупреждений')} {s['audit']['warnings']}"]
    if s["next"]:
        out.append(f"\n▶ {t('СЛЕДУЮЩИЙ ШАГ')}: {s['next']['text']}")
    out.append(f"\n{t('Активные гипотезы')} ({len(s['active_hypotheses'])}):")
    out += [f"- {h['id']} [{h['status']}] {h['statement']}"
            + (f"  {t('→ задачи')} {', '.join(h['tasks'])}" if h['tasks'] else f"  {t('→ задач нет')}")
            for h in s["active_hypotheses"]] or [f"- {t('нет')}"]
    labels = {"in-progress": "В работе", "in-review": "На ревью", "blocked": "Заблокировано",
              "ready": "Готово к старту", "planned": "Запланировано"}
    for key, label in labels.items():
        items = s["tasks"][key]
        if items:
            out.append(f"\n{t(label)} ({len(items)}):")
            for task in items:
                extra = f" — {task['constraints']}" if key == "blocked" and task["constraints"] else ""
                out.append(f"- {task['id']} [p{task['priority'] or '—'}] {task['goal']}{extra}")
    if s["checked_negative"]:
        out.append(f"\n{t('Проверено без результата')} ({len(s['checked_negative'])}) — {t('не повторять без нового основания')}:")
        for n in s["checked_negative"]:
            rep = f"; {t('повторить, если')}: {n['repeat_when']}" if n["repeat_when"] else ""
            out.append(f"- {n['id']} {n['date']} {n['source']}: {n['query']} [{n['period']}] → {n['result']}{rep}")
    if s["reviews_pending"]:
        out.append(f"\n{t('Ревью ждут')} ({len(s['reviews_pending'])}):")
        out += [f"- {r['id']} → {r['target']}" + (f" — {t('нужно решение человека')}" if r["status"] == "passed" else "")
                for r in s["reviews_pending"]]
    if s["requests_open"]:
        out.append(f"\n{t('Запросы в архивы')} ({len(s['requests_open'])}):")
        out += [f"- {r['id']} [{r['status']}] {r['recipient']}: {r['subject']}"
                + (f" — {t('срок')} {r['due']}" if r["due"] else "") + (f" — {t('ПРОСРОЧЕН')}" if r["overdue"] else "")
                for r in s["requests_open"]]
    if s.get("family_reports_pending"):
        out.append(f"\n{t('Сведения семьи ждут решения')}: {s['family_reports_pending']} (kin feedback list)")
    if s["open_contradictions"]:
        out.append(f"\n{t('Нерешённые противоречия')} ({len(s['open_contradictions'])}):")
        out += [f"- {c['id']} {c['statement']}" for c in s["open_contradictions"]]
    if s["recent_changes"]:
        out.append(f"\n{t('Последние изменения')}:")
        out += [f"- {j['ts']} {j['actor']}: {j['op']} {j['id']}" for j in s["recent_changes"]]
    return "\n".join(out)
