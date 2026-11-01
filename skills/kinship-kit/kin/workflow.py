"""Исследовательский процесс: выбор следующего действия, жизненный цикл задач и гипотез,
независимое ревью, защита от повторных поисков, история решений.

Логика — здесь; команды CLI только вызывают эти функции.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from . import audit
from .i18n import t
from .store import Case, KinError, split_ids

DEFAULT_POLICY = {
    # какие решения требуют пройденного независимого ревью
    "required_for": ["hypothesis:accepted", "hypothesis:rejected", "claim:strongly-corroborated", "merge"],
}
DEFAULT_LIMITS = {"max_attempts_per_task": 3, "paid_requires_consent": True, "external_services_require_consent": True}
OPEN_TASK = ("planned", "ready", "in-progress")
TODAY = lambda: dt.date.today().isoformat()  # noqa: E731


def policy(case: Case) -> dict:
    return {**DEFAULT_POLICY, **case.config.get("review", {})}


def limits(case: Case) -> dict:
    return {**DEFAULT_LIMITS, **case.config.get("limits", {})}


def requires_review(case: Case, key: str) -> bool:
    return key in policy(case)["required_for"]


# ------------------------------------------------------------------ журнал и история


def journal(case: Case) -> list[dict]:
    p = case.root / "journal.jsonl"
    out = []
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def history(case: Case, identifier: str) -> list[dict]:
    return [j for j in journal(case) if j.get("id") == identifier or identifier in json.dumps(j.get("data", {}), ensure_ascii=False)
            and j.get("op") in ("decision", "review")]


def norm_actor(name: str) -> str:
    return " ".join((name or "").split()).casefold()


def authors(case: Case, identifier: str) -> set[str]:
    """Кто создавал и менял запись (по журналу), в нормализованном виде."""
    return {norm_actor(j.get("actor", "")) for j in journal(case)
            if j.get("id") == identifier and j.get("op") in ("add", "update", "decision", "status-decision")}


DECISIONS = {"hypotheses": ("accepted", "rejected"), "claims": ("strongly-corroborated", "merge")}


def decision_key(case: Case, target: str, short: str) -> str:
    """«accepted» для H- → «hypothesis:accepted»; «merge» для C- → «merge»."""
    if not short:
        return ""
    register, _ = case.get(target)
    if short not in DECISIONS.get(register, ()):
        raise KinError(f"Для {target} проверяемое решение: {', '.join(DECISIONS.get(register, ())) or 'нет'}")
    if short == "merge":
        return "merge"
    return {"hypotheses": "hypothesis", "claims": "claim"}[register] + ":" + short


def decision(case: Case, actor: str, identifier: str, data: dict) -> None:
    case.journal(actor, "decision", identifier, data)


# ------------------------------------------------------------------ чек-лист ревью


def _related_artifacts(case: Case, register: str, row: dict) -> set[str]:
    claims = case.index("claims")
    ids: set[str] = set()
    if register == "claims":
        ids |= set(split_ids(row.get("artifact_ids")) + split_ids(row.get("contradicting_artifact_ids")))
        for mid in split_ids(row.get("mention_ids")):
            m = case.index("mentions").get(mid)
            if m:
                ids.add(m["artifact_id"])
    elif register == "relationships":
        ids |= set(split_ids(row.get("supporting_artifact_ids")) + split_ids(row.get("contradicting_artifact_ids")))
        for cid in split_ids(row.get("claim_ids")):
            ids |= _related_artifacts(case, "claims", claims.get(cid, {}))
    elif register == "hypotheses":
        ids |= set(split_ids(row.get("supporting_artifact_ids")) + split_ids(row.get("contradicting_artifact_ids")))
        for cid in split_ids(row.get("claim_ids")):
            ids |= _related_artifacts(case, "claims", claims.get(cid, {}))
    elif register == "persons":
        for c in claims.values():
            if row["person_id"] in split_ids(c["subject_person_ids"]):
                ids |= _related_artifacts(case, "claims", c)
    elif register == "tasks":
        ids |= set(split_ids(row.get("evidence_artifact_ids")))
    return {i for i in ids if i}


def _persons_of(case: Case, register: str, row: dict) -> set[str]:
    if register == "claims":
        return set(split_ids(row.get("subject_person_ids")))
    if register == "relationships":
        return {row["person_a_id"], row["person_b_id"]}
    if register == "hypotheses":
        return set(split_ids(row.get("person_ids")))
    if register == "persons":
        return {row["person_id"]}
    return set()


def possibly_living(case: Case, person_id: str) -> bool:
    """Тот же критерий, что у публичной сборки: живой или «возможно живой» (нет смерти и рождение не раньше cutoff)."""
    from . import publish
    p = case.index("persons").get(case.resolve_person(person_id))
    if not p:
        return False
    cutoff = int(case.config.get("privacy", {}).get("living_cutoff_years", 100))
    return not publish.person_visible({**p, "publication": ""}, "public", cutoff)[0] and p["status"] != "duplicate"


def checklist(case: Case, target: str, decision: str = "") -> list[dict]:
    """Автоматические замечания к выводу. level: block — пройти ревью нельзя; warn — разобрать; human — нужен человек.
    decision — проверяемое решение: запись оценивается так, будто оно уже принято (например, статус strongly-corroborated)."""
    register, row = case.get(target)
    if register == "reviews":  # kin review checklist V-… — проверяем цель ревью и её решение
        return checklist(case, row["target_id"], row.get("decision", ""))
    if decision and decision != "merge":
        row = {**row, "status": decision.split(":", 1)[1]}
    arts = case.index("artifacts")
    found: list[dict] = []

    def add(level, text):
        found.append({"level": level, "text": text})

    groups = lambda ids: {arts[a]["independence_group"].casefold() for a in ids  # noqa: E731
                          if a in arts and arts[a].get("independence_group")}
    if register == "hypotheses":
        claims = case.index("claims")
        sup = split_ids(row.get("supporting_artifact_ids"))
        linked = [claims[c] for c in split_ids(row.get("claim_ids")) if c in claims]
        sourced = [c for c in linked if split_ids(c.get("artifact_ids"))]
        if not sup and not sourced:
            add("block", "Нет ни одного источника «за»: ни в гипотезе, ни в её утверждениях — вывод ни на чём не основан")
        if linked and all(c["status"] == "hypothesis" for c in linked):
            add("block", "Все проверяемые утверждения гипотезы сами в статусе hypothesis")
        if not row.get("alternatives"):
            add("warn", "Не рассмотрены альтернативные объяснения")
        if row.get("open_contradictions"):
            add("block", f"Есть нерешённые противоречия: {row['open_contradictions']}")
        if not row.get("test_plan"):
            add("warn", "Нет плана проверки")
        tasks = [t for t in case.rows("tasks") if t.get("hypothesis_id") == target]
        if not tasks:
            add("warn", "По гипотезе не было задач — проверка не проводилась")
        elif all(t["status"] == "closed-without-finding" for t in tasks) and row["status"] in ("supported", "accepted"):
            add("block", "Все задачи закрыты без находок, а гипотеза отмечена как подтверждённая")
        if sup and len(groups(sup)) < 2:
            add("warn", f"Источники «за» из одной группы независимости ({len(groups(sup))})")
        con = split_ids(row.get("contradicting_artifact_ids"))
        if con:
            add("warn", f"Есть источники «против»: {', '.join(con)} — объясните, почему они не опровергают")
    elif register in ("claims", "relationships"):
        sup = split_ids(row.get("artifact_ids") if register == "claims" else row.get("supporting_artifact_ids"))
        if register == "relationships":
            for cid in split_ids(row.get("claim_ids")):
                sup += split_ids(case.index("claims").get(cid, {}).get("artifact_ids"))
        con = split_ids(row.get("contradicting_artifact_ids"))
        if not sup:
            add("block", "Нет источников «за»")
        g = groups(sup)
        if row["status"] in ("corroborated", "strongly-corroborated") and len(g) < 2:
            add("block", f"Статус {row['status']}, а независимых групп {len(g)}")
        kinds = {arts[a].get("originality") for a in sup if a in arts}
        if sup and kinds <= {"derivative", "index", "family-information", "transcript", ""}:
            add("warn", "Все источники производные (индексы, пересказы, семейные сведения) — нужен первичный документ")
        if con:
            add("warn" if row.get("rationale") else "block",
                f"Есть источники «против» ({', '.join(con)})" + ("" if row.get("rationale") else " без объяснения в rationale"))
        if register == "claims" and split_ids(row.get("competing_claim_ids")):
            add("warn", f"Есть конкурирующие версии: {row['competing_claim_ids']}")
        if register == "claims":
            for mid in split_ids(row.get("mention_ids")):
                m = case.index("mentions").get(mid, {})
                if m.get("link_status") in ("possible", "probable"):
                    add("warn", f"{mid}: отождествление упоминания только {m['link_status']}")
    elif register == "persons":
        ident = [c for c in case.rows("claims") if c["claim_type"] == "identity"
                 and target in split_ids(c["subject_person_ids"])]
        if not any(c["status"] in ("corroborated", "strongly-corroborated") for c in ident):
            add("block", "Нет identity-утверждения в статусе corroborated для слияния")
    living = [p for p in _persons_of(case, register, row) if possibly_living(case, p)]
    if living:
        add("human", f"Касается живых или возможно живых: {', '.join(sorted(living))} — нужно решение человека")
    return found


# ------------------------------------------------------------------ ревью


def _linked_ids(case: Case, target: str) -> set[str]:
    """Записи, изменение которых делает ревью устаревшим: сама запись, её утверждения и источники."""
    register, row = case.get(target)
    ids = {target}
    if register == "hypotheses":
        ids |= set(split_ids(row.get("claim_ids")))
    elif register == "relationships":
        ids |= set(split_ids(row.get("claim_ids")))
    ids |= _related_artifacts(case, register, row)
    return ids


def request_review(case: Case, target: str, reviewer: str, actor: str, decision: str = "") -> dict:
    case.get(target)
    checks = checklist(case, target, decision)
    return case.add("reviews", {
        "target_id": target, "decision": decision,
        "authors": ";".join(sorted(a for a in authors(case, target) if a)),
        "reviewer": reviewer, "status": "requested",
        "auto_findings": " | ".join(f"[{c['level']}] {c['text']}" for c in checks),
        "human_required": "yes" if any(c["level"] == "human" for c in checks) else "no",
        "requested_at": TODAY()}, actor)


def submit_review(case: Case, review_id: str, verdict: str, findings: str, checked: list[str], actor: str) -> dict:
    if verdict not in ("passed", "failed", "needs-work"):
        raise KinError("Вердикт: passed, failed или needs-work")
    actor = " ".join((actor or "").split())
    _, rev = case.get(review_id)
    if rev["status"] != "requested":
        raise KinError(f"{review_id} уже завершено ({rev['status']}); для повторной проверки — новый запрос")
    target, decision = rev["target_id"], rev.get("decision", "")
    done_by = authors(case, target) | {norm_actor(a) for a in split_ids(rev.get("authors"))}
    if norm_actor(actor) in done_by or norm_actor(actor) in ("", "user"):
        raise KinError(f"Проверяющий «{actor}» должен быть другой ролью/человеком, чем исполнители "
                       f"({', '.join(sorted(a for a in done_by if a)) or '—'}). Укажите --as \"Evidence Reviewer\".")
    register, row = case.get(target)
    related = _related_artifacts(case, register, row)
    unknown = set(checked) - related
    if unknown:
        raise KinError(f"Проверенные источники {sorted(unknown)} не относятся к {target}. Относятся: {sorted(related) or 'нет'}")
    if related and not checked:
        raise KinError("Ревьюер проверяет первичные источники, а не резюме: перечислите прочитанные --checked A-…")
    checks = checklist(case, target, decision)
    blocking = [c["text"] for c in checks if c["level"] == "block"]
    if verdict == "passed" and blocking:
        raise KinError("Нельзя пройти ревью при блокирующих замечаниях:\n- " + "\n- ".join(blocking))
    if verdict != "passed" and not findings:
        raise KinError("Для failed/needs-work опишите недостатки в --findings")
    human = "yes" if any(c["level"] == "human" for c in checks) else rev.get("human_required", "no")
    row = case.update(review_id, {
        "status": verdict, "reviewer": actor, "findings": findings, "checked_artifact_ids": ";".join(checked),
        "auto_findings": " | ".join(f"[{c['level']}] {c['text']}" for c in checks),
        "human_required": human, "completed_at": TODAY()}, actor, op="review-record")
    # засчитывается именно эта запись журнала, а не поля строки реестра
    case.journal(actor, "review", target, {"review": review_id, "verdict": verdict, "decision": decision,
                                           "human_required": human, "checked": checked})
    return row


def human_decide(case: Case, review_id: str, by: str, accept: bool, note: str) -> dict:
    by = " ".join((by or "").split())
    if norm_actor(by) in ("", "user"):
        raise KinError("Решение принимает человек: --by «Имя»")
    _, rev = case.get(review_id)
    if rev["status"] != "passed":
        raise KinError("Решение человека принимается по пройденному ревью")
    text = f"{by}: {'принять' if accept else 'отклонить'}" + (f" — {note}" if note else "")
    row = case.update(review_id, {"human_decision": text} if accept else {"human_decision": text, "status": "failed"},
                      by, op="review-record")
    case.journal(by, "human-decision", rev["target_id"], {"review": review_id, "accept": accept, "note": note})
    return row


def review_ok(case: Case, target: str, decision: str) -> tuple[bool, str]:
    """Можно ли принять решение decision по target.

    Засчитывается запись журнала «review» (не строка реестра): вердикт passed по этому target и этому решению,
    поставленный не исполнителем, ПОСЛЕ последнего содержательного изменения записи и связанных с ней
    утверждений и источников (решение по статусу — не содержательное изменение). Для «нужен человек» —
    запись «human-decision» после ревью. Дополнительно чек-лист решения перепроверяется сейчас."""
    blocking = [c["text"] for c in checklist(case, target, decision) if c["level"] == "block"]
    if blocking:
        return False, "блокирующие замечания: " + "; ".join(blocking)
    entries = journal(case)
    linked = _linked_ids(case, target)
    last_change = max((i for i, j in enumerate(entries)
                       if j.get("id") in linked and j.get("op") in ("add", "update")), default=-1)
    done_by = authors(case, target)
    for i in range(len(entries) - 1, last_change, -1):
        j = entries[i]
        d = j.get("data", {})
        if j.get("op") != "review" or j.get("id") != target or d.get("decision", "") != decision:
            continue
        if d.get("verdict") != "passed" or norm_actor(j.get("actor", "")) in done_by:
            continue
        if d.get("human_required") == "yes":
            human = any(k.get("op") == "human-decision" and k.get("data", {}).get("review") == d.get("review")
                        and k.get("data", {}).get("accept") for k in entries[i + 1:])
            if not human:
                return False, f"{d.get('review')} пройдено, но нужно решение человека: kin review decide {d.get('review')} --by «Имя»"
        return True, d.get("review", "")
    short = decision.split(":")[-1]
    return False, (f"нет пройденного ревью решения «{decision}» после последних изменений {target} и связанных записей: "
                   f"kin review request {target} --for {short}, затем проверка другой ролью")


# ------------------------------------------------------------------ задачи


def _attempts(task: dict) -> int:
    return len(split_ids(task.get("search_ids")))


def task_gate(case: Case, task: dict) -> str | None:
    """Почему задачу нельзя выполнять сейчас (None — можно)."""
    lim = limits(case)
    tid = task["task_id"]
    if task.get("user_consent") == "denied":
        return t("пользователь отказал")
    if task.get("cost") == "paid" and lim["paid_requires_consent"] and task.get("user_consent") != "granted":
        return f"{t('платно — нужно согласие пользователя')} (kin task consent {tid} --granted --by «…»)"
    if task.get("external_service") == "yes" and lim["external_services_require_consent"] and task.get("user_consent") != "granted":
        return f"{t('передача сведений стороннему сервису — нужно согласие')} (kin task consent {tid} --granted --by «…»)"
    if _attempts(task) >= int(lim["max_attempts_per_task"]):
        return f"{t('исчерпан лимит попыток')} ({_attempts(task)}/{lim['max_attempts_per_task']}) — {t('нужен пересмотр задачи')}"
    return None


def rank_tasks(case: Case) -> tuple[list[dict], list[dict]]:
    """(рекомендуемые по убыванию оценки, исключённые с причиной)."""
    hyps = case.index("hypotheses")
    ranked, excluded = [], []
    for task in case.rows("tasks"):
        if task["status"] not in OPEN_TASK:
            continue
        gate = task_gate(case, task)
        if gate:
            excluded.append({"id": task["task_id"], "goal": task["goal"], "reason": gate})
            continue
        reasons, score = [], 0.0
        try:
            value = int(task.get("evidential_value") or 3)
        except ValueError:
            value = 3
        score += 2 * value
        reasons.append(f"{t('ценность')} {value}")
        try:
            prio = int(task.get("priority") or 3)
        except ValueError:
            prio = 3
        score += 6 - prio
        reasons.append(f"{t('приоритет')} {prio}")
        h = hyps.get(task.get("hypothesis_id", ""))
        if h and h["status"] in ("open", "testing"):
            score += 2
            reasons.append(t("активная гипотеза"))
            if h.get("open_contradictions"):
                score += 1
                reasons.append(t("снимает противоречие"))
        cost = {"free": 0, "": -0.5, "unknown": -1, "paid": -3}.get(task.get("cost", ""), 0)
        access = {"online": 0, "": -0.5, "unknown": -1, "request": -1, "onsite": -2}.get(task.get("access", ""), 0)
        score += cost + access
        if cost:
            reasons.append(f"{t('стоимость')} {task.get('cost') or '?'}")
        if access:
            reasons.append(f"{t('доступ')} {task.get('access') or '?'}")
        if _attempts(task):
            score -= _attempts(task)
            reasons.append(f"{t('попыток')} {_attempts(task)}")
        if task["status"] == "in-progress":
            score += 5
            reasons.append(t("уже начата"))
        elif task["status"] == "planned":
            score -= 1
            reasons.append(t("ещё не готова"))
        ranked.append({"id": task["task_id"], "goal": task["goal"], "status": task["status"], "score": round(score, 1),
                       "reasons": reasons, "assignee": task.get("assignee", "")})
    ranked.sort(key=lambda x: (x["status"] != "in-progress", -x["score"], x["id"]))  # начатое — первым
    return ranked, excluded


TRANSITIONS = {
    "start": ({"planned", "ready", "blocked", "in-review"}, "in-progress"),
    "ready": ({"planned", "blocked"}, "ready"),
    "block": ({"planned", "ready", "in-progress"}, "blocked"),
    "review": ({"in-progress"}, "in-review"),
    "done": ({"in-progress", "in-review"}, "completed"),
    "close": ({"planned", "ready", "in-progress", "in-review", "blocked"}, "closed-without-finding"),
}


def task_transition(case: Case, task_id: str, action: str, actor: str, reason: str = "",
                    evidence: list[str] | None = None, next_step: str = "") -> dict:
    _, task = case.get(task_id)
    allowed, new = TRANSITIONS[action]
    if task["status"] not in allowed:
        raise KinError(f"{task_id}: из статуса {t['status']} действие {action} невозможно")
    changes: dict = {"status": new}
    if action == "start":
        gate = task_gate(case, task)
        if gate:
            raise KinError(f"{task_id} нельзя начать: {gate}")
        changes["assignee"] = actor
    if action == "block":
        if not reason:
            raise KinError("Укажите причину блокировки --reason")
        changes["constraints"] = "; ".join(x for x in (task.get("constraints"), reason) if x)
    if action in ("done", "close"):
        if not reason:
            raise KinError("Укажите причину завершения --reason")
        changes["close_reason"] = reason
    if action == "close" and not split_ids(task.get("search_ids")):
        raise KinError(f"{task_id}: закрыть без находки можно только после записанного поиска "
                       "(kin search add … --task …) — иначе следующий исполнитель повторит работу")
    if evidence:
        changes["evidence_artifact_ids"] = ";".join(dict.fromkeys(split_ids(task.get("evidence_artifact_ids")) + evidence))
    if next_step:
        changes["next_step"] = next_step
    row = case.update(task_id, changes, actor)
    decision(case, actor, task_id, {"action": action, "from": task["status"], "to": new, "reason": reason})
    return row


def consent(case: Case, task_id: str, granted: bool, by: str, note: str = "") -> dict:
    if not by or by.casefold() in ("user", ""):
        raise KinError("Согласие даёт человек: укажите --by «Имя»")
    row = case.update(task_id, {"user_consent": "granted" if granted else "denied"}, by)
    decision(case, by, task_id, {"action": "consent", "granted": granted, "note": note})
    return row


# ------------------------------------------------------------------ гипотезы


def hypothesis_status(case: Case, hid: str, new: str, reason: str, actor: str, reopen: str = "") -> dict:
    _, h = case.get(hid)
    if not reason:
        raise KinError("Решение по гипотезе требует обоснования --reason")
    changes = {"status": new}
    if reopen:
        changes["reopen_conditions"] = reopen
    if new in ("rejected", "parked") and not (reopen or h.get("reopen_conditions")):
        raise KinError(f"Для {new} укажите условия повторного открытия --reopen")
    if new == "rejected" and not split_ids(h.get("contradicting_artifact_ids")):
        raise KinError("Опровержение требует источников «против» (contradicting_artifact_ids): "
                       "отсутствие находки — не опровержение. Возможно, подходит parked.")
    if new in ("accepted", "rejected") and requires_review(case, f"hypothesis:{new}"):
        ok, why = review_ok(case, hid, f"hypothesis:{new}")
        if not ok:
            raise KinError(f"{hid} → {new}: {why}")
    row = case.update(hid, changes, actor, op="status-decision")
    decision(case, actor, hid, {"action": "status", "from": h["status"], "to": new, "reason": reason})
    return row


# ------------------------------------------------------------------ поиск: не повторять без основания


def _norm(text: str) -> set[str]:
    """Слова длиннее 2 букв и все числа (номера фондов, описей, дел различают источники)."""
    words = re.findall(r"\w+", (text or "").casefold().replace("ё", "е"))
    return {w for w in words if len(w) > 2 or w.isdigit()}


def _overlap(a: str, b: str) -> bool:
    from . import edtf
    if not a or not b:
        return True
    a1, a2 = edtf.years(a)
    b1, b2 = edtf.years(b)
    a1, a2 = a1 or -9999, a2 or 9999
    b1, b2 = b1 or -9999, b2 or 9999
    return a1 <= b2 and b1 <= a2


def similar_searches(case: Case, source: str, query: str, period: str = "", persons: str = "") -> list[dict]:
    """Прежние безрезультатные поиски того же: похожий источник (с теми же номерами), похожий запрос,
    пересекающийся период и те же люди (если указаны в обоих). Транслитерацию и синонимы не распознаёт —
    перед поиском агент смотрит kin status → «Проверено без результата»."""
    src, q = _norm(source), _norm(query)
    who = {case.resolve_person(p) for p in split_ids(persons)}
    out = []
    for s in case.rows("searches"):
        if s["result"] not in ("not-found", "partial", "blocked", "error"):
            continue
        s_src, s_q = _norm(s["source"]), _norm(s.get("query", ""))
        nums, s_nums = {w for w in src if w.isdigit()}, {w for w in s_src if w.isdigit()}
        if nums and s_nums and nums != s_nums:
            continue  # другой фонд/опись/дело
        s_who = {case.resolve_person(p) for p in split_ids(s.get("target_person_ids"))}
        if who and s_who and not (who & s_who):
            continue  # искали других людей
        src_sim = len(src & s_src) / max(1, len(src | s_src))
        q_sim = len(q & s_q) / max(1, len(q | s_q)) if (q or s_q) else 1.0
        if src_sim >= 0.5 and q_sim >= 0.6 and _overlap(period, s.get("period", "")):
            out.append(s)
    return out


def guard_search(case: Case, values: dict) -> None:
    if values.get("new_basis"):
        return
    prev = similar_searches(case, values.get("source", ""), values.get("query", ""), values.get("period", ""),
                            values.get("target_person_ids", ""))
    if prev:
        lines = [f"{s['search_id']} {s['date']} {s['source']}: {s.get('query', '')} [{s.get('period', '')}] → {s['result']}"
                 + (f"; повторить, если: {s['repeat_when']}" if s.get("repeat_when") else "") for s in prev]
        raise KinError("Такой поиск уже был без результата:\n- " + "\n- ".join(lines)
                       + "\nПовторять — только с новым основанием: --set new_basis=\"…\" (новый источник, вариант написания, открылся доступ).")


def next_summary(case: Case) -> dict | None:
    a = audit.run(case)
    if a["errors"]:
        return {"kind": "fix-audit", "text": f"{t('Исправить ошибки аудита')} ({len(a['errors'])}): kin audit"}
    pending = [r for r in case.rows("reviews") if r["status"] == "requested"]
    ranked, _ = rank_tasks(case)
    if ranked and ranked[0]["status"] == "in-progress":
        top = ranked[0]
        return {"kind": "continue-task", "id": top["id"], "text": f"{t('Продолжить')} {top['id']}: {top['goal']}"}
    if pending:
        r = pending[0]
        return {"kind": "review", "id": r["review_id"], "text": f"{t('Независимое ревью')} {r['review_id']} ({r['target_id']}) — {t('роль')} {r.get('reviewer') or 'Evidence Reviewer'}"}
    if ranked:
        top = ranked[0]
        return {"kind": "start-task", "id": top["id"],
                "text": f"{t('Начать')} {top['id']} ({t('оценка')} {top['score']}: {', '.join(top['reasons'])}): {top['goal']}"}
    return None
