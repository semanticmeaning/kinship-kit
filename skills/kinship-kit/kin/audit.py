"""Аудит дела: целостность схемы и ссылок, правила доказательности, неизменяемость источников.

Не присваивает истинность — проверяет, что выводы оформлены так, чтобы их можно было проверить.
Ошибки — нарушение правил (сборка/публикация должны остановиться). Предупреждения — что проверить человеку.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from . import edtf
from .store import REGISTERS, Case, sha256_file, split_ids

CORROBORATED = {"corroborated", "strongly-corroborated"}
CLOSED_CLAIM = {"rejected", "superseded"}
UNSOURCED_OK = {"hypothesis", "rejected", "superseded"}  # остальные статусы требуют источников
DATE_FACTS = {"birth", "baptism", "death", "burial", "marriage"}
FAMILY_KINDS = {"family-tree", "family-oral"}  # семейное дерево и рассказы родственников
ACTIVE = {"single-source", "corroborated", "strongly-corroborated"}  # связь или утверждение стоит на источнике
WEAK_PERSON = {"candidate", "hypothesis", "unlikely"}
PATR = re.compile(r"(ович|евич|ьич|ич|овна|евна|ична|инична)$")
PID = re.compile(r"\bP-\d{4,}\b")
FAMILY_ONLY = "держится на семейном дереве, а оно подтверждает только сведения о живых и на одно поколение от них"


def _groups(artifact_ids, artifacts) -> set[str]:
    """Независимые группы; артефакт без группы не засчитывается в кроссподтверждение."""
    return {artifacts[a]["independence_group"].casefold() for a in artifact_ids
            if a in artifacts and artifacts[a].get("independence_group")}


def _has_direct_record(artifact_ids, artifacts) -> bool:
    for a in artifact_ids:
        r = artifacts.get(a, {})
        if (r.get("directness") == "direct"
                and r.get("originality") in {"original", "image-of-original", "official-extract"}
                and r.get("provenance") and (r.get("archival_reference") or r.get("url") or r.get("file"))):
            return True
    return False


def _span(value: str) -> tuple[int | None, int | None]:
    """Годы из EDTF; у приблизительных («~», «?») — запас ±5 лет, чтобы эвристики не тревожили зря."""
    lo, hi = edtf.years(value or "")
    pad = 5 if (value or "").rstrip().endswith(("~", "?", "%")) else 0
    return (lo - pad if lo is not None else None), (hi + pad if hi is not None else None)


def _names(label: str) -> tuple[str, str]:
    """(имя, отчество) из «Фамилия Имя Отчество»; пустые — если не разобрать."""
    words = re.findall(r"[А-Яа-яЁё]+", re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", label or "").split(",")[0])
    words = [w.lower().replace("ё", "е") for w in words]
    pi = next((i for i, w in enumerate(words) if i and PATR.search(w)), None)
    if pi is not None:
        return words[pi - 1], words[pi]
    return (words[1] if len(words) == 2 else ""), ""


def _near_living(case: Case, persons: dict) -> set[str]:
    """Живые и одно поколение от них (их родители и дети): о них семейные сведения — независимое подтверждение."""
    living = {pid for pid, p in persons.items() if p.get("living_status") == "living" and p.get("status") != "duplicate"}
    near = set(living)
    for r in case.rows("relationships"):
        if r["relationship_type"] == "parent-of" and r["status"] not in CLOSED_CLAIM:
            a, b = case.resolve_person(r["person_a_id"]), case.resolve_person(r["person_b_id"])
            if a in living:
                near.add(b)  # ребёнок живого
            if b in living:
                near.add(a)  # родитель живого
    return near


def _doc_groups(arts: list[str], artifacts: dict) -> set[str]:
    """Группы без семейных источников (дерева и рассказов)."""
    return _groups([a for a in arts if artifacts.get(a, {}).get("kind") not in FAMILY_KINDS], artifacts)


def _consistency(case: Case, persons: dict, claims: dict, artifacts: dict, warnings: list[str]) -> None:
    """Согласованность данных — эвристики по опыту ревью схемы: что проверить человеку (не ошибки)."""
    rels = [r for r in case.rows("relationships") if r["status"] not in CLOSED_CLAIM]
    parents, children = defaultdict(set), defaultdict(set)
    for r in rels:
        if r["relationship_type"] == "parent-of":
            parents[r["person_b_id"]].add(r["person_a_id"])
            children[r["person_a_id"]].add(r["person_b_id"])

    # люди и связи
    for r in rels:
        a, b, rid = persons.get(r["person_a_id"], {}), persons.get(r["person_b_id"], {}), r["relationship_id"]
        if r["relationship_type"] == "spouse-of" and a.get("sex") == b.get("sex") and a.get("sex") in ("m", "f"):
            warnings.append(f"{rid}: супруги одного пола ({r['person_a_id']}, {r['person_b_id']}) — проверьте пол или связь")
        if r["relationship_type"] == "parent-of":
            pb, pe = _span(a.get("birth_estimate")), _span(b.get("birth_estimate"))
            if pb[0] is not None and pe[1] is not None and pe[1] < pb[0] + 12:
                warnings.append(f"{rid}: {r['person_b_id']} родился(ась) раньше, чем {r['person_a_id']} исполнилось 12 лет")
            dd = _span(a.get("death_estimate"))
            if dd[1] is not None and pe[0] is not None and pe[0] > dd[1] + 1:
                warnings.append(f"{rid}: {r['person_b_id']} родился(ась) позже смерти родителя {r['person_a_id']}")
            if a.get("sex") == "m":
                father, _ = _names(a.get("preferred_label", ""))
                _, patr = _names(b.get("preferred_label", ""))
                if len(father) >= 3 and len(patr) >= 5 and father[:3] != patr[:3]:
                    warnings.append(f"{rid}: отчество {r['person_b_id']} не сходится с именем отца {r['person_a_id']} — проверьте отцовство")
        if r["status"] in ACTIVE:
            for pid in (r["person_a_id"], r["person_b_id"]):
                if persons.get(pid, {}).get("status") in WEAK_PERSON:
                    warnings.append(f"{rid}: связь {r['status']}, а {pid} ещё {persons[pid]['status']} — повысить личность или понизить связь")

    pair_rel = {}
    for r in rels:
        if r["status"] in ACTIVE:
            key = (r["relationship_type"], r["person_a_id"], r["person_b_id"])
            pair_rel[key] = r["relationship_id"]
            if r["relationship_type"] != "parent-of":
                pair_rel[(r["relationship_type"], r["person_b_id"], r["person_a_id"])] = r["relationship_id"]

    texts = defaultdict(list)
    for cid, c in claims.items():
        if c["status"] in CLOSED_CLAIM:
            continue
        subj = split_ids(c["subject_person_ids"])
        if c["claim_type"] == "identity":
            if len(subj) > 2:
                warnings.append(f"{cid}: identity на {len(subj)} лиц — тождество проверяется попарно, разделите на утверждения по два")
            sexes = {persons.get(x, {}).get("sex") for x in subj} - {"u", "", None}
            if len(sexes) > 1:
                warnings.append(f"{cid}: identity объединяет мужчину и женщину ({', '.join(subj)})")
        if c["status"] == "hypothesis" and len(subj) >= 2 and c["claim_type"] in ("parentage", "sibling"):
            key = ("parent-of" if c["claim_type"] == "parentage" else "sibling-of", subj[0], subj[1])
            if key in pair_rel:
                warnings.append(f"{cid}: гипотеза, а связь {pair_rel[key]} той же пары уже стоит на источнике — закройте или понизьте одно из двух")
        if c["claim_type"] in ("birth", "baptism", "death", "burial") and c.get("date"):
            field = "birth_estimate" if c["claim_type"] in ("birth", "baptism") else "death_estimate"
            lo, hi = _span(c["date"])
            for pid in subj[:1]:
                plo, phi = _span(persons.get(pid, {}).get(field, ""))
                if None not in (lo, hi, plo, phi) and (hi < plo or lo > phi) and c["status"] in ACTIVE:
                    warnings.append(f"{cid}: дата {c['date']} не сходится с карточкой {pid} ({field}={persons[pid][field]})")
        # устаревшие доводы: упомянут человек, слитый с другим (identity-утверждения о слиянии — исключение)
        if c["claim_type"] != "identity":
            for field in ("rationale", "next_action"):
                for pid in sorted(set(PID.findall(c.get(field) or ""))):
                    if persons.get(pid, {}).get("status") == "duplicate":
                        warnings.append(f"{cid}.{field}: упоминается {pid}, слитый с {case.resolve_person(pid)} — довод не устарел?")
        norm = " ".join((c.get("statement") or "").casefold().split())
        if len(norm) > 20:
            texts[norm].append(cid)
    for r in rels:
        for pid in sorted(set(PID.findall(r.get("rationale") or ""))):
            if persons.get(pid, {}).get("status") == "duplicate":
                warnings.append(f"{r['relationship_id']}.rationale: упоминается {pid}, слитый с {case.resolve_person(pid)} — довод не устарел?")
    for ids in texts.values():
        if len(ids) > 1:
            warnings.append(f"{', '.join(ids)}: одинаковый текст утверждений — дубли или разные факты с одной формулировкой")

    # семейное дерево — независимое подтверждение только о живых и на одно поколение от них (себя, детей, родителей)
    near = _near_living(case, persons)
    doc_groups = lambda arts: _doc_groups(arts, artifacts)  # noqa: E731

    for cid, c in claims.items():
        subj = {case.resolve_person(x) for x in split_ids(c["subject_person_ids"])}
        arts = split_ids(c.get("artifact_ids"))
        if c["status"] in CORROBORATED and not subj <= near and len(_groups(arts, artifacts)) >= 2 > len(doc_groups(arts)):
            warnings.append(f"{cid}: {c['status']} {FAMILY_ONLY}")
    for r in rels:
        arts = split_ids(r.get("supporting_artifact_ids"))
        for xc in split_ids(r.get("claim_ids")):
            if claims.get(xc, {}).get("status") not in CLOSED_CLAIM:
                arts += split_ids(claims.get(xc, {}).get("artifact_ids"))
        subj = {case.resolve_person(r["person_a_id"]), case.resolve_person(r["person_b_id"])}
        if r["status"] in CORROBORATED and not subj <= near and len(_groups(arts, artifacts)) >= 2 > len(doc_groups(arts)):
            warnings.append(f"{r['relationship_id']}: {r['status']} {FAMILY_ONLY}")


def run(case: Case) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Схема и ссылки
    for name, reg in REGISTERS.items():
        rows = case.rows(name)
        ids = Counter(r[reg["id"]] for r in rows)
        for rid, n in ids.items():
            if n > 1:
                errors.append(f"{reg['file']}: ID {rid} повторяется {n} раз")
            if not rid.startswith(reg["prefix"]) or not rid[len(reg["prefix"]):].isdigit():
                errors.append(f"{reg['file']}: ID {rid!r} не в формате {reg['prefix']}NNNN")
        for r in rows:
            errors.extend(case.validate(name, r))

    artifacts = case.index("artifacts")
    persons = case.index("persons")
    claims = case.index("claims")

    # 2. Источники неизменяемы
    for aid, a in artifacts.items():
        f = a.get("file")
        if f:
            p = (case.root / f).resolve()
            if case.root / "sources" not in p.parents:
                errors.append(f"{aid}: файл {f} вне папки sources/")
            elif not p.is_file():
                errors.append(f"{aid}: файл {f} отсутствует")
            elif a.get("sha256") and sha256_file(p) != a["sha256"]:
                errors.append(f"{aid}: файл {f} изменён после регистрации (sha256 не совпадает)")
            elif not a.get("sha256"):
                errors.append(f"{aid}: у файла нет sha256 (добавляйте через kin source add)")
        if not a.get("independence_group"):
            warnings.append(f"{aid}: не указан independence_group — не засчитывается в кроссподтверждение")

    # 3. Люди: слияния
    for pid, p in persons.items():
        if p["status"] == "duplicate" and not p.get("merged_into"):
            errors.append(f"{pid}: status=duplicate, но не указан merged_into")
        if p.get("merged_into"):
            if p["status"] != "duplicate":
                errors.append(f"{pid}: указан merged_into, но status={p['status']} (нужно duplicate)")
            if not p.get("merge_rationale"):
                errors.append(f"{pid}: слияние без merge_rationale")
            if case.resolve_person(pid) == pid or persons.get(case.resolve_person(pid), {}).get("merged_into"):
                errors.append(f"{pid}: цикл в merged_into")

    # 4. Утверждения
    near = _near_living(case, persons)
    for cid, c in claims.items():
        status = c["status"]
        sup = split_ids(c.get("artifact_ids"))
        con = split_ids(c.get("contradicting_artifact_ids"))
        groups = _groups(sup, artifacts)
        if status not in UNSOURCED_OK and not sup:
            errors.append(f"{cid}: статус {status} без источников (artifact_ids); без источника — только hypothesis/rejected/superseded")
        if set(sup) & set(con):
            errors.append(f"{cid}: один источник одновременно «за» и «против»: {sorted(set(sup) & set(con))}")
        if status in CORROBORATED and len(groups) < 2:
            errors.append(f"{cid}: {status} требует ≥2 независимых групп источников, найдено {len(groups)}")
        if status in CORROBORATED and not c.get("rationale"):
            errors.append(f"{cid}: {status} без rationale")
        if status in CORROBORATED and con:
            warnings.append(f"{cid}: {status}, но есть источники «против» — объясните разрешение конфликта в rationale")
        if status == "strongly-corroborated" and not _has_direct_record(sup, artifacts):
            warnings.append(f"{cid}: strongly-corroborated без прямой записи с происхождением и шифром/адресом")
        counted = groups if {case.resolve_person(x) for x in split_ids(c["subject_person_ids"])} <= near \
            else _doc_groups(sup, artifacts)  # семейные сведения о дальних предках не засчитываются
        if status == "single-source" and len(counted) > 1:
            warnings.append(f"{cid}: независимых групп {len(counted)}, а статус single-source — пересмотрите")
        if c["claim_type"] == "identity" and len(split_ids(c["subject_person_ids"])) < 2:
            errors.append(f"{cid}: identity требует двух subject_person_ids")
        if c.get("supersedes") == cid:
            errors.append(f"{cid}: supersedes ссылается на себя")
        if status == "superseded" and not any(o.get("supersedes") == cid for o in claims.values()):
            warnings.append(f"{cid}: superseded, но нет утверждения, которое его заменяет (supersedes={cid})")

    # 4а. Противоречия по датам должны быть видны: одинаковый факт, разные даты, без взаимной ссылки
    by_fact = defaultdict(list)
    for c in claims.values():
        if c["claim_type"] in DATE_FACTS and c.get("date") and c["status"] not in CLOSED_CLAIM:
            for pid in split_ids(c["subject_person_ids"]):
                by_fact[(case.resolve_person(pid), c["claim_type"])].append(c)
    for (pid, ctype), items in by_fact.items():
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if a["date"] == b["date"]:
                    continue
                linked = (b["claim_id"] in split_ids(a.get("competing_claim_ids"))
                          or a["claim_id"] in split_ids(b.get("competing_claim_ids")))
                if not linked:
                    warnings.append(f"{pid}: {ctype} — {a['claim_id']} ({a['date']}) и {b['claim_id']} ({b['date']}) "
                                    "расходятся, но не связаны competing_claim_ids")

    # 5. Связи — только из источника
    parents = defaultdict(set)
    for r in case.rows("relationships"):
        rid, status = r["relationship_id"], r["status"]
        if r["person_a_id"] == r["person_b_id"]:
            errors.append(f"{rid}: связь человека с самим собой")
        backing = split_ids(r.get("supporting_artifact_ids"))
        for cid in split_ids(r.get("claim_ids")):
            if claims.get(cid, {}).get("status") not in CLOSED_CLAIM:  # отвергнутое не подкрепляет связь
                backing += split_ids(claims.get(cid, {}).get("artifact_ids"))
        if status not in UNSOURCED_OK and not backing:
            errors.append(f"{rid}: статус {status} без источников — связь вносится, только если родство названо в источнике")
        groups = _groups(backing, artifacts)
        if status in CORROBORATED and len(groups) < 2:
            errors.append(f"{rid}: {status} требует ≥2 независимых групп, найдено {len(groups)}")
        if status in CORROBORATED and not r.get("rationale"):
            errors.append(f"{rid}: {status} без rationale")
        if r["relationship_type"] == "parent-of" and status not in CLOSED_CLAIM:
            parents[r["person_b_id"]].add(r["person_a_id"])
    for child, ps in parents.items():
        if len(ps) > 2:
            warnings.append(f"{child}: больше двух родителей ({', '.join(sorted(ps))}) — возможны конкурирующие версии")
    # цикл «предок сам себе»
    def ancestors(pid, seen):
        for par in parents.get(pid, ()):
            if par in seen:
                continue
            seen.add(par)
            ancestors(par, seen)
        return seen
    for pid in list(parents):
        if pid in ancestors(pid, set()):
            errors.append(f"{pid}: цикл в связях parent-of")

    # 5а. Согласованность (эвристики по опыту ревью схемы)
    _consistency(case, persons, claims, artifacts, warnings)

    # 6. Упоминания
    for m in case.rows("mentions"):
        if m.get("person_id") and m.get("link_status") in ("", "unlinked"):
            warnings.append(f"{m['mention_id']}: указан person_id, но link_status пуст/unlinked")
        if m.get("link_status") in ("probable", "confirmed") and not m.get("link_rationale"):
            warnings.append(f"{m['mention_id']}: отождествление {m['link_status']} без link_rationale")

    # 7. Гипотезы, задачи, поиск
    for h in case.rows("hypotheses"):
        if h["status"] == "rejected" and not split_ids(h.get("contradicting_artifact_ids")):
            errors.append(f"{h['hypothesis_id']}: rejected без источников «против» — отсутствие находки не опровержение")
        if h["status"] in ("rejected", "parked") and not h.get("reopen_conditions"):
            warnings.append(f"{h['hypothesis_id']}: {h['status']} без reopen_conditions")
    for t in case.rows("tasks"):
        if t["status"] in ("completed", "closed-without-finding") and not t.get("close_reason"):
            warnings.append(f"{t['task_id']}: {t['status']} без close_reason")
        if t["status"] == "blocked" and not t.get("constraints"):
            warnings.append(f"{t['task_id']}: blocked без описания причины в constraints")
    for s in case.rows("searches"):
        if s["result"] == "found" and not s.get("artifact_ids"):
            warnings.append(f"{s['search_id']}: found, но находка не зарегистрирована как источник")
        if s["result"] == "not-found" and not s.get("disallowed_conclusions"):
            warnings.append(f"{s['search_id']}: отрицательный поиск без disallowed_conclusions (что из него нельзя выводить)")

    # 8. Независимое ревью (политика дела: case.json → review.required_for)
    from . import workflow  # локальный импорт: workflow сам использует аудит
    for h in case.rows("hypotheses"):
        if h["status"] in ("accepted", "rejected") and workflow.requires_review(case, f"hypothesis:{h['status']}"):
            ok, why = workflow.review_ok(case, h["hypothesis_id"], f"hypothesis:{h['status']}")
            if not ok:
                errors.append(f"{h['hypothesis_id']}: {h['status']} без действующего независимого ревью — {why}")
    for cid, c in claims.items():
        if c["status"] == "strongly-corroborated" and workflow.requires_review(case, "claim:strongly-corroborated"):
            ok, why = workflow.review_ok(case, cid, "claim:strongly-corroborated")
            if not ok:
                errors.append(f"{cid}: strongly-corroborated без действующего независимого ревью — {why}")
    if workflow.requires_review(case, "merge"):
        entries = workflow.journal(case)
        forced = {j.get("data", {}).get("person") for j in entries
                  if j.get("op") == "human-decision" and j.get("data", {}).get("action") == "merge-force"}
        for pid, p in persons.items():
            if not p.get("merged_into") or pid in forced:
                continue
            basis = [c["claim_id"] for c in claims.values() if c["claim_type"] == "identity"
                     and {pid, p["merged_into"]} <= set(split_ids(c["subject_person_ids"]))]
            if not any(workflow.review_ok(case, b, "merge")[0] for b in basis):
                errors.append(f"{pid}: слит в {p['merged_into']} без ревью identity-утверждения и без решения человека")
    review_log, rejected_by_human = {}, set()
    for j in workflow.journal(case):
        d = j.get("data", {})
        if j.get("op") == "review":
            review_log[d.get("review")] = j
        if j.get("op") == "human-decision" and d.get("review") and not d.get("accept"):
            rejected_by_human.add(d.get("review"))
    for r in case.rows("reviews"):
        j = review_log.get(r["review_id"])
        if r["status"] == "requested":
            if j:
                errors.append(f"{r['review_id']}: в журнале есть вердикт, а строка снова «requested» (правка в обход kin review?)")
            continue
        verdict = j.get("data", {}).get("verdict") if j else None
        expected = "failed" if verdict == "passed" and r["review_id"] in rejected_by_human else verdict
        if not j or r["status"] != expected or j.get("id") != r["target_id"] \
                or j.get("data", {}).get("decision", "") != r.get("decision", ""):
            errors.append(f"{r['review_id']}: строка ревью не совпадает с записью в журнале (правка в обход kin review?)")
        if r["status"] in ("passed", "failed", "needs-work"):
            if workflow.norm_actor(r.get("reviewer", "")) in {workflow.norm_actor(a) for a in split_ids(r.get("authors"))}:
                errors.append(f"{r['review_id']}: проверяющий совпадает с исполнителем ({r['reviewer']})")
            if r["status"] == "passed" and not split_ids(r.get("checked_artifact_ids")):
                warnings.append(f"{r['review_id']}: пройдено без проверки первичных источников")
    for q in case.rows("requests"):
        if q["status"] == "sent" and not q.get("sent_date"):
            warnings.append(f"{q['request_id']}: отправлен, но нет sent_date")
        if q["status"] == "answered" and not split_ids(q.get("response_artifact_ids")):
            warnings.append(f"{q['request_id']}: ответ получен, но не зарегистрирован как источник")

    counts = {name: len(case.rows(name)) for name in REGISTERS}
    summary = {
        "claims_by_status": dict(Counter(c["status"] for c in claims.values())),
        "relationships_by_status": dict(Counter(r["status"] for r in case.rows("relationships"))),
        "persons_by_status": dict(Counter(p["status"] for p in persons.values())),
    }
    return {"case": str(case.root), "counts": counts, "summary": summary, "errors": errors, "warnings": warnings}


def format_text(result: dict) -> str:
    from .i18n import t
    c = result["counts"]
    lines = [f"{t('Дело')}: {result['case']}",
             f"{t('Записей')}: " + ", ".join(f"{k}={v}" for k, v in c.items())]
    s = result["summary"]
    lines.append(f"{t('Утверждения')}: " + (", ".join(f"{k}={v}" for k, v in sorted(s["claims_by_status"].items())) or t("нет")))
    lines.append(f"{t('Связи')}: " + (", ".join(f"{k}={v}" for k, v in sorted(s["relationships_by_status"].items())) or t("нет")))
    if result["errors"]:
        lines.append(f"\n{t('ОШИБКИ')} ({len(result['errors'])}):")
        lines += [f"- {e}" for e in result["errors"]]
    if result["warnings"]:
        lines.append(f"\n{t('ПРЕДУПРЕЖДЕНИЯ')} ({len(result['warnings'])}):")
        lines += [f"- {w}" for w in result["warnings"]]
    if not result["errors"] and not result["warnings"]:
        lines.append(t("Ошибок и предупреждений нет."))
    return "\n".join(lines)
