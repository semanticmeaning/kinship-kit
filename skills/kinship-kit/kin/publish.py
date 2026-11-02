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
from .store import SCHEMA_VERSION, Case, KinError, now_iso, split_ids, split_list

PROFILES = ("private", "public")
FAMILY_KINDS = {"family-oral", "family-tree", "letter", "photo"}  # владелец/ссылка часто указывают на живых
PUBLIC_LINE_FIELDS = ("id", "title", "state", "color")  # where/focus/surname — рабочие заметки, наружу не идут
CLOSED = {"rejected", "superseded"}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(
    r"(?<![\w-])(?:"
    r"\+\d[\d\s()-]{8,}\d"                                               # +7 916 123-45-67, +49 … (check_repo: allow)
    r"|[78][\s-]?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}"            # 8 (916) 123-45-67, 8-916-…, 7 916 … (check_repo: allow)
    r"|\(\d{3,5}\)\s?\d{1,3}[\s-]?\d{2}[\s-]?\d{2}"                        # (495) 123-45-67 (check_repo: allow)
    r")(?![\w-])")
PATH_RE = re.compile(r"(?:/root/|/home/|/Users/|[A-Za-z]:\\\\|journal\.jsonl|\bsources/|\.kin/)")


def latest_birth_year(value: str) -> int | None:
    """Самый поздний возможный год рождения; None, если верхней границы нет («1900/..», пусто) — тогда скрываем."""
    d = edtf.parse(value)
    if not d or d.get("unknown") or not d.get("end"):
        return None
    return d["end"]["year"]


def person_visible(p: dict, profile: str, cutoff_years: int, this_year: int | None = None,
                   public_living: str = "hide") -> tuple[bool, str]:
    """(видно ли, причина). При сомнении — скрыть. public_living=allow — решение автора дела показывать живых."""
    this_year = this_year or dt.date.today().year
    if p["status"] == "duplicate":
        return False, "дубликат"
    if p.get("publication") == "deny":
        return False, "publication=deny"
    if profile == "private":
        return True, ""
    if p.get("publication") == "allow":
        return True, "publication=allow"
    if public_living == "allow":
        return True, "privacy.public_living=allow"
    if p["living_status"] == "living":
        return False, "живой"
    if p["living_status"] == "deceased":
        return True, ""
    if p.get("death_estimate"):
        return True, ""
    by = latest_birth_year(p.get("birth_estimate", ""))
    if by is not None and by < this_year - cutoff_years:
        return True, ""
    return False, f"статус жизни неизвестен и рождение не раньше чем {cutoff_years} лет назад"


def build(case: Case, profile: str) -> dict:
    if profile not in PROFILES:
        raise KinError(f"Профиль {profile!r}: допустимо {', '.join(PROFILES)}")
    try:
        cutoff = int(case.config.get("privacy", {}).get("living_cutoff_years", 100))
    except (TypeError, ValueError):
        raise KinError("case.json: privacy.living_cutoff_years должно быть целым числом") from None
    lang = case.config.get("language", "ru")
    public_living = case.config.get("privacy", {}).get("public_living", "hide")
    public = profile == "public"
    persons_all = case.index("persons")
    visible, hidden = {}, {}
    for pid, p in persons_all.items():
        ok, why = person_visible(p, profile, cutoff, public_living=public_living)
        (visible if ok else hidden)[pid] = why

    def vis(pid: str) -> bool:
        return case.resolve_person(pid) in visible

    persons = []
    for pid in sorted(visible):
        p = persons_all[pid]
        item = {"id": pid, "label": p["preferred_label"], "sex": p.get("sex", ""), "status": p["status"],
                "birth": p.get("birth_estimate", ""), "death": p.get("death_estimate", ""),
                "birth_h": edtf.human(p.get("birth_estimate", ""), lang) if p.get("birth_estimate") else "",
                "death_h": edtf.human(p.get("death_estimate", ""), lang) if p.get("death_estimate") else "",
                "variants": split_list(p.get("name_variants")), "places": split_list(p.get("places")),
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
                       "date": c.get("date", ""), "date_h": edtf.human(c["date"], lang) if c.get("date") else "",
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
        family = public and a["kind"] in FAMILY_KINDS
        url = a.get("url", "")
        sources.append({"id": aid, "title": a["title"], "kind": a["kind"],
                        "repository": "" if family else a.get("repository", ""),
                        "reference": a.get("archival_reference", ""), "date": a.get("record_date", ""),
                        "url": url if url.startswith(("http://", "https://")) and not family else "",
                        "group": a.get("independence_group", "") if not public else ""})

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
                 "lines": [{k: ln.get(k, "") for k in PUBLIC_LINE_FIELDS} for ln in case.config.get("lines", [])]
                 if public else case.config.get("lines", []),
                 "hidden_persons": None if public else len(hidden),
                 "feedback": bool(not public and case.config.get("feedback", {}).get("enabled"))},
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


def _fold(text: str) -> str:
    """Нормализация для сравнения: регистр, ё→е, пунктуация → пробел."""
    return re.sub(r"[^\w]+", " ", text.casefold().replace("ё", "е")).strip()


def _stem(word: str) -> str:
    """Грубая основа для русских падежей: «сергеевна/сергеевны/сергеевной» → «сергеевн»."""
    return word[:-2] if len(word) > 5 else (word[:-1] if len(word) > 3 else word)


NAME_WINDOW = 3  # сколько посторонних слов допускается между частями имени


def forbidden_terms(case: Case, hidden: dict) -> list[str]:
    """Регулярные выражения (по нормализованному тексту, см. _fold) того, чего не должно быть в сборке:
    ID скрытых людей и их имена в любом падеже и порядке — любые две части ФИО (включая девичью фамилию
    из скобок и варианты), разделённые не более чем NAME_WINDOW словами. Одиночное слово не проверяется:
    фамилия и имя у видимых родственников часто те же (см. ограничения в docs/ARCHITECTURE.md)."""
    terms = set()
    persons = case.index("persons")
    for pid in hidden:
        p = persons[pid]
        if p["status"] == "duplicate" and case.resolve_person(pid) not in hidden:
            continue  # дубликат видимого человека показан под ID основной записи — это не утечка
        terms.add(r"(?<![\w-])" + re.escape(pid.casefold()).replace("\\-", "[ -]") + r"(?!\d)")
        for name in [p["preferred_label"]] + split_list(p.get("name_variants")):
            words = [w for w in _fold(name).split() if len(w) > 1 and not w.isdigit()]
            stems = list(dict.fromkeys(_stem(w) for w in words))
            gap = rf"\w*(?:\s+\w+){{0,{NAME_WINDOW}}}\s+"
            for i, a in enumerate(stems):
                for b in stems[i + 1:]:
                    for x, y in ((a, b), (b, a)):
                        terms.add(r"\b" + re.escape(x) + gap + re.escape(y) + r"\w*")
            if len(stems) == 1 and len(words[0]) >= 5:
                terms.add(r"\b" + re.escape(stems[0]) + r"\w*")
    return sorted(terms)


def check_leaks_text(text: str, terms: list[str], name: str = "текст") -> list[str]:
    problems = []
    folded = _fold(text)
    for t in terms:
        m = re.search(t, folded)
        if m:
            problems.append(f"{name}: найдено скрытое сведение «{m.group(0)}»")
    for rx, label in ((EMAIL_RE, "e-mail"), (PHONE_RE, "телефон"), (PATH_RE, "локальный путь")):
        m = rx.search(text)
        if m:
            problems.append(f"{name}: {label} «{m.group(0)}»")
    return problems


def check_leaks(paths: list[Path], terms: list[str]) -> list[str]:
    problems = []
    for path in paths:
        problems += check_leaks_text(path.read_text(encoding="utf-8", errors="replace"), terms, path.name)
    return problems


def redact_text(text: str, terms: list[str], mark: str = "[скрыто]") -> tuple[str, int]:
    """Заменить в тексте скрытые сведения (имена в любом падеже, ID, e-mail, телефоны) на mark.
    Совпадения ищутся по нормализованному тексту и переносятся на исходные слова."""
    count = 0
    text, n = EMAIL_RE.subn(mark, text)
    count += n
    text, n = PHONE_RE.subn(mark, text)
    count += n
    compiled = [re.compile(t) for t in terms]
    for _ in range(50):  # каждое совпадение — одна замена; ограничение на всякий случай
        words = list(re.finditer(r"\w+", text))
        folded, spans = [], []
        pos = 0
        for w in words:
            f = w.group(0).casefold().replace("ё", "е")
            spans.append((pos, pos + len(f), w.start(), w.end()))
            folded.append(f)
            pos += len(f) + 1
        joined = " ".join(folded)
        hit = None
        for rx in compiled:
            m = rx.search(joined)
            if m:
                hit = m
                break
        if not hit:
            break
        covered = [s for s in spans if s[1] > hit.start() and s[0] < hit.end()]
        if not covered:
            break
        text = text[:covered[0][2]] + mark + text[covered[-1][3]:]
        count += 1
    return text, count


def _redact_data(data, terms: list[str]) -> int:
    total = 0
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, str) and k not in ("id", "type", "status", "kind", "profile", "language", "built_at"):
                data[k], n = redact_text(v, terms)
                total += n
            else:
                total += _redact_data(v, terms)
    elif isinstance(data, list):
        for i, v in enumerate(data):
            if isinstance(v, str):
                data[i], n = redact_text(v, terms)
                total += n
            else:
                total += _redact_data(v, terms)
    return total


def write(case: Case, profile: str) -> tuple[Path, dict, list[str]]:
    out = case.root / "publish" / profile
    path = out / "data.json"
    path.unlink(missing_ok=True)  # старый набор не должен пережить неудачную сборку
    data, hidden = build(case, profile)
    if case.config.get("privacy", {}).get("on_leak") == "redact":  # решение автора: закрывать, а не падать
        data["meta"]["redacted"] = _redact_data({k: v for k, v in data.items() if k != "meta"},
                                                forbidden_terms(case, hidden))
    out.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    problems = check_leaks([path], forbidden_terms(case, hidden))
    if problems:
        path.unlink()
        raise KinError("Публикационный набор не собран — найдены утечки:\n- " + "\n- ".join(problems)
                       + "\nИсправьте текст утверждений/обоснований или решение о публикации (persons.publication).")
    return path, data, sorted(hidden)
