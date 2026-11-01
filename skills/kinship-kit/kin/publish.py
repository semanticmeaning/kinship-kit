"""Publication Dataset: отдельный производный набор только из разрешённых сведений.

Профили:
- private — для себя и семьи (сайт за паролем или localhost): живые видны, кроме publication=deny;
- public  — для всех: живые и «возможно живые» скрыты, служебные поля (notes, provenance, пути к файлам) не попадают.
После сборки — проверка на утечки: имена скрытых людей, их ID, e-mail, телефоны, локальные пути. Нарушение = сборка падает.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from . import edtf
from .store import SCHEMA_VERSION, Case, KinError, now_iso, split_ids

PROFILES = ("private", "public")
CLOSED = {"rejected", "superseded"}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<![\w-])(?:\+\d[\d\s()-]{8,}\d|8\s?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2})(?!\w)")
PATH_RE = re.compile(r"(?:/root/|/home/|/Users/|[A-Za-z]:\\\\|journal\.jsonl|\bsources/|\.kin/)")


def latest_birth_year(value: str) -> int | None:
    """Самый поздний возможный год рождения; None, если верхней границы нет («1900/..», пусто) — тогда скрываем."""
    d = edtf.parse(value)
    if not d or d.get("unknown") or not d.get("end"):
        return None
    return d["end"]["year"]


def person_visible(p: dict, profile: str, cutoff_years: int, this_year: int | None = None) -> tuple[bool, str]:
    """(видно ли, причина). При сомнении — скрыть."""
    this_year = this_year or dt.date.today().year
    if p["status"] == "duplicate":
        return False, "дубликат"
    if p.get("publication") == "deny":
        return False, "publication=deny"
    if profile == "private":
        return True, ""
    if p.get("publication") == "allow":
        return True, "publication=allow"
    if p["living_status"] == "living":
        return False, "живой"
    if p["living_status"] == "deceased":
        return True, ""
    if p.get("death_estimate"):
        return True, ""
    by = latest_birth_year(p.get("birth_estimate", ""))
    if by is not None and by < this_year - cutoff_years:
        return True, ""
    return False, "статус жизни неизвестен и рождение не раньше чем {} лет назад".format(cutoff_years)


def build(case: Case, profile: str) -> dict:
    if profile not in PROFILES:
        raise KinError(f"Профиль {profile!r}: допустимо {', '.join(PROFILES)}")
    cutoff = int(case.config.get("privacy", {}).get("living_cutoff_years", 100))
    public = profile == "public"
    persons_all = case.index("persons")
    visible, hidden = {}, {}
    for pid, p in persons_all.items():
        ok, why = person_visible(p, profile, cutoff)
        (visible if ok else hidden)[pid] = why

    def vis(pid: str) -> bool:
        return case.resolve_person(pid) in visible

    persons = []
    for pid in sorted(visible):
        p = persons_all[pid]
        item = {"id": pid, "label": p["preferred_label"], "sex": p.get("sex", ""), "status": p["status"],
                "birth": p.get("birth_estimate", ""), "death": p.get("death_estimate", ""),
                "birth_h": edtf.human(p.get("birth_estimate", ""), case.config.get("language", "ru")) if p.get("birth_estimate") else "",
                "death_h": edtf.human(p.get("death_estimate", ""), case.config.get("language", "ru")) if p.get("death_estimate") else "",
                "variants": split_ids(p.get("name_variants")), "places": split_ids(p.get("places")),
                "line": p.get("line", "")}
        if not public:
            item["living"] = p["living_status"]
        persons.append(item)

    claims, used_sources = [], set()
    for c in case.rows("claims"):
        subjects = [case.resolve_person(s) for s in split_ids(c["subject_person_ids"])]
        if not subjects or not all(s in visible for s in subjects):
            continue
        if public and c["status"] in CLOSED:
            continue
        sup, con = split_ids(c.get("artifact_ids")), split_ids(c.get("contradicting_artifact_ids"))
        used_sources.update(sup + con)
        claims.append({"id": c["claim_id"], "type": c["claim_type"], "subjects": subjects, "statement": c["statement"],
                       "date": c.get("date", ""), "date_h": edtf.human(c["date"]) if c.get("date") else "",
                       "place": c.get("place", ""), "status": c["status"], "confidence": c.get("confidence", ""),
                       "sources": sup, "against": con, "competing": split_ids(c.get("competing_claim_ids")),
                       "rationale": c.get("rationale", "")})
    visible_claims = {c["id"] for c in claims}
    for c in claims:
        c["competing"] = [x for x in c["competing"] if x in visible_claims]

    rels = []
    for r in case.rows("relationships"):
        a, b = case.resolve_person(r["person_a_id"]), case.resolve_person(r["person_b_id"])
        if a not in visible or b not in visible or a == b:
            continue
        if public and r["status"] in CLOSED:
            continue
        sup = split_ids(r.get("supporting_artifact_ids"))
        used_sources.update(sup + split_ids(r.get("contradicting_artifact_ids")))
        rels.append({"id": r["relationship_id"], "a": a, "type": r["relationship_type"], "b": b, "status": r["status"],
                     "claims": [x for x in split_ids(r.get("claim_ids")) if x in visible_claims], "sources": sup,
                     "rationale": r.get("rationale", "")})

    artifacts = case.index("artifacts")
    sources = []
    for aid in sorted(used_sources):
        a = artifacts.get(aid)
        if not a:
            continue
        sources.append({"id": aid, "title": a["title"], "kind": a["kind"], "repository": a.get("repository", ""),
                        "reference": a.get("archival_reference", ""), "date": a.get("record_date", ""),
                        "url": a.get("url", ""), "group": a.get("independence_group", "") if not public else ""})

    hypotheses = []
    if not public:
        for h in case.rows("hypotheses"):
            if h["status"] in ("open", "testing") and all(vis(p) for p in split_ids(h.get("person_ids"))):
                hypotheses.append({"id": h["hypothesis_id"], "statement": h["statement"], "status": h["status"],
                                   "persons": [case.resolve_person(p) for p in split_ids(h.get("person_ids"))]})

    root, root_offset = _visible_root(case, visible)
    return {
        "meta": {"title": case.config.get("title", ""), "profile": profile, "built_at": now_iso(),
                 "schema_version": SCHEMA_VERSION, "root": root, "root_gen_offset": root_offset, "language": case.config.get("language", "ru"),
                 "lines": case.config.get("lines", []), "hidden_persons": len(hidden)},
        "persons": persons, "claims": claims, "relationships": rels, "sources": sources, "hypotheses": hypotheses,
    }, hidden


def _visible_root(case: Case, visible: dict) -> tuple[str, int]:
    """Корень схемы. Если он скрыт (обычно — живой автор исследования), берём ближайшего видимого
    по связям и смещение колена, чтобы подписи колен остались верными. Наружу уходит только число."""
    root = case.config.get("root_person", "")
    if not root:
        return "", 0
    root = case.resolve_person(root)
    if root in visible:
        return root, 0
    adj: dict[str, list[tuple[str, int]]] = {}
    for r in case.rows("relationships"):
        if r["status"] in CLOSED:
            continue
        a, b = case.resolve_person(r["person_a_id"]), case.resolve_person(r["person_b_id"])
        d = 1 if r["relationship_type"] == "parent-of" else 0
        adj.setdefault(a, []).append((b, d))
        adj.setdefault(b, []).append((a, -d))
    seen, queue = {root: 0}, [root]
    while queue:  # BFS: ближайший видимый; при равенстве — предок (меньшее колено)
        nxt = []
        for cur in queue:
            for other, d in adj.get(cur, ()):
                if other not in seen:
                    seen[other] = seen[cur] + d
                    nxt.append(other)
        found = sorted((seen[x], x) for x in nxt if x in visible)
        if found:
            g, pid = found[0]
            return pid, g
        queue = nxt
    return "", 0


def _stem(word: str) -> str:
    """Грубая основа для русских падежей: «Сергеевна/Сергеевны/Сергеевной» → «Сергеевн»."""
    w = word.strip(".,;:()«»\"'")
    return w[:-2] if len(w) > 5 else (w[:-1] if len(w) > 3 else w)


def forbidden_terms(case: Case, hidden: dict) -> list[str]:
    """Регулярные выражения того, чего не должно быть в сборке: ID скрытых людей и их имена
    в любом падеже — пары «Имя Отчество», «Фамилия Имя», «Имя Фамилия»."""
    terms = set()
    persons = case.index("persons")
    for pid in hidden:
        p = persons[pid]
        if p["status"] == "duplicate" and case.resolve_person(pid) not in hidden:
            continue  # дубликат видимого человека показан под ID основной записи — это не утечка
        terms.add(r"(?<![\w-])" + re.escape(pid) + r"(?!\d)")
        for name in [p["preferred_label"]] + split_ids(p.get("name_variants")):
            words = [w for w in re.sub(r"\([^)]*\)", " ", name).split() if len(w) > 1]
            stems = [_stem(w) for w in words]
            pairs = []
            if len(stems) >= 3:
                pairs += [(stems[1], stems[2]), (stems[0], stems[1]), (stems[1], stems[0])]
            elif len(stems) == 2:
                pairs += [(stems[0], stems[1]), (stems[1], stems[0])]
            elif len(stems) == 1 and len(words[0]) >= 5:
                pairs.append((stems[0], None))
            for a, b in pairs:
                rx = r"\b" + re.escape(a) + r"\w*"
                if b:
                    rx += r"\s+" + re.escape(b) + r"\w*"
                terms.add(rx)
    return sorted(terms)


def check_leaks(paths: list[Path], terms: list[str]) -> list[str]:
    problems = []
    compiled = [re.compile(t, re.IGNORECASE) for t in terms]
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for rx in compiled:
            m = rx.search(text)
            if m:
                problems.append(f"{path.name}: найдено скрытое сведение «{m.group(0)}»")
        for rx, label in ((EMAIL_RE, "e-mail"), (PHONE_RE, "телефон"), (PATH_RE, "локальный путь")):
            m = rx.search(text)
            if m:
                problems.append(f"{path.name}: {label} «{m.group(0)}»")
    return problems


def write(case: Case, profile: str) -> tuple[Path, dict, list[str]]:
    data, hidden = build(case, profile)
    out = case.root / "publish" / profile
    out.mkdir(parents=True, exist_ok=True)
    path = out / "data.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    problems = check_leaks([path], forbidden_terms(case, hidden))
    if problems:
        path.unlink()
        raise KinError("Публикационный набор не собран — найдены утечки:\n- " + "\n- ".join(problems)
                       + "\nИсправьте текст утверждений/обоснований или решение о публикации (persons.publication).")
    return path, data, sorted(hidden)
