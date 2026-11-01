"""GEDCOM 5.5.1: экспорт и импорт в объёме, который поддерживает модель kinship-kit (ограничения — docs/GEDCOM.md).

Экспорт: люди, имена и варианты, пол, события из утверждений (каждая версия — отдельное событие, статус — в NOTE),
семьи из связей, источники; идентификаторы kin — в REFN (TYPE kinship-kit). Профиль public — тот же фильтр,
что у публикации (живые и «возможно живые» не выгружаются).

Импорт: файл GEDCOM регистрируется как источник (семейное древо, производный); каждый INDI — упоминание этого
источника; люди сопоставляются по REFN kinship-kit и по xref прежних импортов того же древа, иначе создаются как
tree-entry-unverified. Тот же файл повторно не импортируется; события и связи, которые уже есть, не дублируются.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from . import __version__, edtf, publish
from .store import Case, KinError, sha256_file, split_ids, split_list

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
EVENT_TAGS = {"birth": "BIRT", "baptism": "CHR", "death": "DEAT", "burial": "BURI", "residence": "RESI",
              "occupation": "OCCU", "military": "EVEN", "migration": "EVEN", "repression": "EVEN", "name": "EVEN",
              "other": "EVEN"}
TAG_TO_TYPE = {"BIRT": "birth", "CHR": "baptism", "BAPM": "baptism", "DEAT": "death", "BURI": "burial",
               "RESI": "residence", "OCCU": "occupation", "MARR": "marriage", "DIV": "divorce"}
CLOSED = {"rejected", "superseded"}
EVIDENCED = {"single-source", "corroborated", "strongly-corroborated", "contradicted", "unresolved"}


# ------------------------------------------------------------------ даты


def _ged_point(p: dict) -> str:
    if p["day"]:
        return f"{p['day']} {MONTHS[p['month'] - 1]} {p['year']}"
    if p["month"]:
        return f"{MONTHS[p['month'] - 1]} {p['year']}"
    return str(p["year"])


def edtf_to_ged(value: str) -> str:
    d = edtf.parse(value)
    if not d or d.get("unknown"):
        return ""
    if not d["interval"]:
        p = d["start"]
        prefix = "ABT " if p["approx"] else ("EST " if p["uncertain"] else "")
        return prefix + _ged_point(p)
    s, e = d["start"], d["end"]
    if s and e:
        return f"BET {_ged_point(s)} AND {_ged_point(e)}"
    return f"BEF {_ged_point(e)}" if e else f"AFT {_ged_point(s)}"


_GPOINT = re.compile(r"^(?:(\d{1,2})\s+)?(?:([A-Z]{3})\s+)?(\d{3,4})$")


def _point_to_edtf(text: str) -> str | None:
    m = _GPOINT.match(text.strip().upper())
    if not m:
        return None
    day, mon, year = m.groups()
    if mon and mon not in MONTHS:
        return None
    out = f"{int(year):04d}"
    if mon:
        out += f"-{MONTHS.index(mon) + 1:02d}"
        if day:
            out += f"-{int(day):02d}"
    return out


def ged_to_edtf(value: str) -> tuple[str, str]:
    """(дата EDTF или "", пометка для текста: календарь, нераспознанное)."""
    text = (value or "").strip()
    note = ""
    if not text:
        return "", ""
    if text.upper().startswith("@#DJULIAN@"):
        text, note = text[10:].strip(), "по юлианскому календарю (ст. ст.)"
    elif text.startswith("@#"):
        return "", f"дата в другом календаре: {value}"
    up = text.upper()
    m = re.match(r"^(?:BET|FROM)\s+(.+?)\s+(?:AND|TO)\s+(.+)$", up)
    if m:
        a, b = _point_to_edtf(m.group(1)), _point_to_edtf(m.group(2))
        if a and b and edtf.is_valid(f"{a}/{b}"):
            return f"{a}/{b}", note
    m = re.match(r"^(BEF|AFT|ABT|EST|CAL|FROM|TO)\s+(.+)$", up)
    if m:
        p = _point_to_edtf(m.group(2))
        if p:
            kind = m.group(1)
            if kind in ("BEF", "TO"):
                out = f"../{p}"
            elif kind in ("AFT", "FROM"):
                out = f"{p}/.."
            else:
                out = p + ("?" if kind == "EST" else "~")
            if edtf.is_valid(out):
                return out, note
    p = _point_to_edtf(up)
    if p and edtf.is_valid(p):
        return p, note
    return "", (note + "; " if note else "") + f"дата не распознана: {value}"


# ------------------------------------------------------------------ имена


def split_label(label: str) -> tuple[str, str, list[str]]:
    """«Фамилия (Девичья) Имя Отчество (1880)» → (фамилия, «Имя Отчество», [девичья]). Скобки с цифрами — пометки."""
    alt = [x.strip() for x in re.findall(r"\(([^)]*)\)", label) if x.strip() and not re.search(r"\d", x)
           and len(x.split()) == 1]
    clean = re.sub(r"\([^)]*\)", " ", label).split()
    if not clean:
        return "", "", alt
    return clean[0], " ".join(clean[1:]), alt


def ged_name(given: str, surname: str) -> str:
    return f"{given} /{surname}/".strip()


def parse_ged_name(value: str) -> tuple[str, str]:
    m = re.match(r"^(.*?)/(.*?)/(.*)$", value or "")
    if not m:
        return value.strip(), ""
    given = " ".join((m.group(1) + " " + m.group(3)).split())
    return given, m.group(2).strip()


# ------------------------------------------------------------------ экспорт


def _lines(level: int, tag: str, value: str = "", xref: str = "") -> list[str]:
    """Строка GEDCOM с переносами CONT (новая строка) и CONC (длинная строка)."""
    head = f"{level} " + (f"{xref} " if xref else "") + tag
    parts = (value or "").split("\n")
    out = []
    for i, part in enumerate(parts):
        chunks = [part[j:j + 200] for j in range(0, len(part), 200)] or [""]
        for k, chunk in enumerate(chunks):
            if i == 0 and k == 0:
                out.append(head + (f" {chunk}" if chunk else ""))
            else:
                out.append(f"{level + 1} {'CONT' if k == 0 else 'CONC'}" + (f" {chunk}" if chunk else ""))
    return out


def _x(identifier: str) -> str:
    return "@" + identifier.replace("-", "") + "@"


def export(case: Case, profile: str = "private", include_hypotheses: bool = False) -> str:
    if profile not in publish.PROFILES:
        raise KinError(f"Профиль: {', '.join(publish.PROFILES)}")
    data, hidden = publish.build(case, profile)
    visible = {p["id"] for p in data["persons"]}
    persons = case.index("persons")
    artifacts = case.index("artifacts")
    claims = [c for c in case.rows("claims") if c["status"] not in CLOSED
              and (include_hypotheses or c["status"] in EVIDENCED)]
    used_sources: set[str] = set()
    out = ["0 HEAD", "1 SOUR KINSHIP-KIT", f"2 VERS {__version__}", "2 NAME kinship-kit", "1 GEDC", "2 VERS 5.5.1",
           "2 FORM LINEAGE-LINKED", "1 CHAR UTF-8", f"1 DATE {_ged_point({'day': dt.date.today().day, 'month': dt.date.today().month, 'year': dt.date.today().year})}",
           f"1 NOTE kinship-kit export, profile={profile}"]
    if case.config.get("case_id"):
        out.append(f"1 _KIN_CASE {case.config['case_id']}")

    def cite(level: int, ids: list[str]) -> list[str]:
        lines = []
        for a in ids:
            if a in artifacts:
                used_sources.add(a)
                lines += _lines(level, "SOUR", _x(a))
                if artifacts[a].get("archival_reference") and not (profile == "public" and artifacts[a]["kind"] in publish.FAMILY_KINDS):
                    lines += _lines(level + 1, "PAGE", artifacts[a]["archival_reference"])
        return lines

    for pid in sorted(visible):
        p = persons[pid]
        surname, given, alts = split_label(p["preferred_label"])
        out += _lines(0, "INDI", xref=_x(pid))
        out += _lines(1, "NAME", ged_name(given, surname))
        for alt in alts:
            out += _lines(1, "NAME", ged_name(given, alt))
            out += _lines(2, "TYPE", "maiden" if p.get("sex") == "f" else "aka")
        for v in split_list(p.get("name_variants")):
            out += _lines(1, "NAME", v)
            out += _lines(2, "TYPE", "aka")
        out += _lines(1, "SEX", {"m": "M", "f": "F"}.get(p.get("sex", ""), "U"))
        out += _lines(1, "REFN", pid)
        out += _lines(2, "TYPE", "kinship-kit")
        own = [c for c in claims if c["claim_type"] in EVENT_TAGS
               and [case.resolve_person(x) for x in split_ids(c["subject_person_ids"])][:1] == [pid]
               and all(case.resolve_person(x) in visible for x in split_ids(c["subject_person_ids"]))]
        has = {c["claim_type"] for c in own}
        for c in own:
            tag = EVENT_TAGS[c["claim_type"]]
            out += _lines(1, tag, c["statement"] if tag == "OCCU" else "")
            if tag == "EVEN":
                out += _lines(2, "TYPE", c["claim_type"])
            if c.get("date"):
                out += _lines(2, "DATE", edtf_to_ged(c["date"]))
            if c.get("place"):
                out += _lines(2, "PLAC", c["place"])
            out += cite(2, split_ids(c.get("artifact_ids")))
            out += _lines(2, "NOTE", f"{c['statement']} [kin {c['claim_id']}: {c['status']}]")
        for field, ctype, tag in (("birth_estimate", "birth", "BIRT"), ("death_estimate", "death", "DEAT")):
            if p.get(field) and ctype not in has:
                out += _lines(1, tag)
                out += _lines(2, "DATE", edtf_to_ged(p[field]))
                out += _lines(2, "NOTE", "Рабочая оценка исследования, без утверждения")
        out += _lines(1, "NOTE", f"kin status: {p['status']}")

    # семьи: пара супругов (или родители ребёнка) → FAM
    rels = [r for r in case.rows("relationships") if r["status"] not in CLOSED
            and (include_hypotheses or r["status"] in EVIDENCED)]
    families: dict[tuple, dict] = {}

    def fam(a: str, b: str | None) -> dict:
        key = tuple(sorted(x for x in (a, b) if x))
        return families.setdefault(key, {"partners": key, "children": [], "rels": []})

    for r in rels:
        a, b = case.resolve_person(r["person_a_id"]), case.resolve_person(r["person_b_id"])
        if a in visible and b in visible and r["relationship_type"] == "spouse-of":
            fam(a, b)["rels"].append(r)
    parents: dict[str, list[str]] = {}
    for r in rels:
        a, b = case.resolve_person(r["person_a_id"]), case.resolve_person(r["person_b_id"])
        if a in visible and b in visible and r["relationship_type"] == "parent-of":
            parents.setdefault(b, []).append(a)
    for child, ps in parents.items():
        ps = sorted(set(ps))[:2]
        f = fam(ps[0], ps[1] if len(ps) > 1 else None)
        f["children"].append(child)
    for i, (key, f) in enumerate(sorted(families.items()), start=1):
        out += _lines(0, "FAM", xref=f"@F{i:04d}@")
        partners = list(f["partners"])
        sexes = {p: persons[p].get("sex", "") for p in partners}
        husb = next((p for p in partners if sexes[p] == "m"), partners[0] if partners else None)
        wife = next((p for p in partners if p != husb), None)
        if husb:
            out += _lines(1, "HUSB", _x(husb))
        if wife:
            out += _lines(1, "WIFE", _x(wife))
        for ch in sorted(set(f["children"])):
            out += _lines(1, "CHIL", _x(ch))
        if len(partners) == 2:
            for c in claims:
                subj = {case.resolve_person(x) for x in split_ids(c["subject_person_ids"])}
                if c["claim_type"] in ("marriage", "divorce") and set(partners) <= subj and subj <= visible:
                    out += _lines(1, "MARR" if c["claim_type"] == "marriage" else "DIV")
                    if c.get("date"):
                        out += _lines(2, "DATE", edtf_to_ged(c["date"]))
                    if c.get("place"):
                        out += _lines(2, "PLAC", c["place"])
                    out += cite(2, split_ids(c.get("artifact_ids")))
                    out += _lines(2, "NOTE", f"[kin {c['claim_id']}: {c['status']}]")
    for a in sorted(used_sources):
        art = artifacts[a]
        family = profile == "public" and art["kind"] in publish.FAMILY_KINDS
        out += _lines(0, "SOUR", xref=_x(a))
        out += _lines(1, "TITL", art["title"])
        if art.get("repository") and not family:
            out += _lines(1, "PUBL", art["repository"])
        if art.get("url", "").startswith(("http://", "https://")) and not family:
            out += _lines(1, "NOTE", art["url"])
        out += _lines(1, "REFN", a)
        out += _lines(2, "TYPE", "kinship-kit")
    out.append("0 TRLR")
    text = "\n".join(out) + "\n"
    problems = []
    if profile == "public":  # проверяем и сам файл, и склеенные значения (CONC/CONT режут слова)
        terms = publish.forbidden_terms(case, hidden)

        def values(nodes):
            for n in nodes:
                yield n["value"]
                yield from values(n["children"])
        joined = "\n".join(values(parse(text)))
        problems = publish.check_leaks_text(text, terms, "GEDCOM") + publish.check_leaks_text(joined, terms, "GEDCOM")
    if problems:
        raise KinError("GEDCOM (public) не выгружен — утечки:\n- " + "\n- ".join(problems))
    return text


# ------------------------------------------------------------------ разбор


def parse(text: str) -> list[dict]:
    """Строки GEDCOM → дерево записей верхнего уровня: {xref, tag, value, children:[...]}."""
    roots: list[dict] = []
    stack: list[tuple[int, dict]] = []
    for raw in text.lstrip("\ufeff").splitlines():
        line = raw.rstrip("\r\n").lstrip()  # хвостовые пробелы — часть значения (CONC)
        if not line.strip():
            continue
        m = re.match(r"^(\d+)\s+(@[^@]+@\s+)?(\S+)(?: (.*))?$", line)
        if not m:
            continue
        level, xref, tag, value = int(m.group(1)), (m.group(2) or "").strip(), m.group(3).upper(), m.group(4) or ""
        if tag in ("CONT", "CONC") and stack:
            parent = stack[-1][1]
            parent["value"] += ("\n" if tag == "CONT" else "") + value
            continue
        node = {"xref": xref, "tag": tag, "value": value, "children": []}
        while stack and stack[-1][0] >= level:
            stack.pop()
        if stack:
            stack[-1][1]["children"].append(node)
        else:
            roots.append(node)
        stack.append((level, node))
    return roots


def _child(node: dict, tag: str) -> dict | None:
    return next((c for c in node["children"] if c["tag"] == tag), None)


def _val(node: dict | None, tag: str) -> str:
    c = _child(node, tag) if node else None
    return c["value"].strip() if c else ""


# ------------------------------------------------------------------ импорт


def import_file(case: Case, path: Path, actor: str = "user", group: str = "", dry_run: bool = False,
                allow_self: bool = False) -> dict:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise KinError(f"Нет файла {path}")
    digest = sha256_file(path)
    for a in case.rows("artifacts"):
        if a.get("sha256") == digest:
            return {"already": a["artifact_id"], "persons_new": 0, "persons_matched": 0, "claims": 0, "relationships": 0,
                    "possible_duplicates": []}
    records = parse(path.read_text(encoding="utf-8-sig", errors="replace"))
    indis = [r for r in records if r["tag"] == "INDI"]
    fams = [r for r in records if r["tag"] == "FAM"]
    head = next((r for r in records if r["tag"] == "HEAD"), None)
    same_case = bool(head and case.config.get("case_id") and _val(head, "_KIN_CASE") == case.config["case_id"])
    if same_case and not allow_self:
        raise KinError("Это экспорт этого же дела: импорт добавил бы копии утверждений. "
                       "Для обмена между делами — kin export/import; осознанно — --allow-self.")
    if not indis:
        raise KinError("В файле нет записей INDI — это не GEDCOM или он пуст")
    tree_name = re.sub(r"[^\w-]+", "-", path.stem.casefold())
    group = group or f"family-tree:{tree_name}"
    persons = case.index("persons")
    # прежние импорты того же древа: xref → person
    tree_artifacts = {a["artifact_id"] for a in case.rows("artifacts") if a.get("independence_group") == group}
    xref_map = {}
    for m in case.rows("mentions"):
        if m["artifact_id"] in tree_artifacts and m.get("person_id"):
            mx = re.search(r"GEDCOM (@[^@]+@)", m.get("details", ""))
            if mx:
                xref_map[mx.group(1)] = (m["person_id"], m["name_as_written"])
    plan = []
    possible_dups = []
    norm = lambda s: " ".join(re.sub(r"[^\w\s]", " ", s.casefold().replace("ё", "е")).split())  # noqa: E731
    by_name = {}
    for pid, p in persons.items():
        if p["status"] != "duplicate":
            by_name.setdefault(norm(re.sub(r"\([^)]*\)", " ", p["preferred_label"])), []).append(pid)
    for ind in indis:
        names = [c["value"] for c in ind["children"] if c["tag"] == "NAME"]
        given, surname = parse_ged_name(names[0] if names else "")
        label = " ".join(x for x in (surname, given) if x) or ind["xref"]
        refn = next((c["value"].strip() for c in ind["children"] if c["tag"] == "REFN"
                     and _val(c, "TYPE").casefold() == "kinship-kit"), "")
        match, how = None, ""
        if same_case and refn in persons:  # REFN — ID этого же дела; ID другого дела ничего не значат здесь
            match, how = case.resolve_person(refn), "REFN"
        elif ind["xref"] in xref_map and norm(xref_map[ind["xref"]][1]) == norm(names[0] if names else ""):
            match, how = case.resolve_person(xref_map[ind["xref"]][0]), "xref"
        if not match and norm(label) in by_name:
            possible_dups.append((label, by_name[norm(label)]))
        plan.append({"node": ind, "label": label, "names": names, "match": match, "how": how})
    report = {"already": "", "persons_new": sum(1 for p in plan if not p["match"]),
              "persons_matched": sum(1 for p in plan if p["match"]), "claims": 0, "relationships": 0,
              "possible_duplicates": [f"{lbl} ~ {', '.join(ids)}" for lbl, ids in possible_dups]}
    if dry_run:
        return report

    created: list[Path] = []
    try:
        report.update(_do_import(case, path, actor, group, digest, indis, fams, plan, created))
    except BaseException:
        for f in created:  # файл древа, скопированный в sources/, — тоже откатываем
            f.chmod(0o644)
            f.unlink(missing_ok=True)
        raise
    return report


def _do_import(case, path, actor, group, digest, indis, fams, plan, created) -> dict:
    report = {"claims": 0, "relationships": 0}
    with case.transaction():  # всё или ничего: при ошибке реестры и журнал откатываются
        aid = case.next_id("artifacts")
        safe = re.sub(r"[^\w.-]+", "_", path.name)
        dest = case.root / "sources" / f"{aid}__{safe}"
        dest.write_bytes(path.read_bytes())
        created.append(dest)
        dest.chmod(0o444)
        try:
            case.add("artifacts", {"artifact_id": aid, "title": f"Семейное древо GEDCOM: {path.name}",
                                   "kind": "family-tree", "originality": "derivative", "independence_group": group,
                                   "sha256": digest, "file": dest.relative_to(case.root).as_posix(),
                                   "provenance": f"Импорт GEDCOM ({dt.date.today().isoformat()})",
                                   "summary": f"{len(indis)} лиц, {len(fams)} семей"}, actor)
        except Exception:
            dest.chmod(0o644)
            dest.unlink(missing_ok=True)
            raise
        xref_to_pid = {}
        for item in plan:
            node = item["node"]
            sex = {"M": "m", "F": "f"}.get(_val(node, "SEX").upper(), "u")
            if item["match"]:
                pid = item["match"]
            else:
                deat = _child(node, "DEAT")
                variants = []
                for n in item["names"][1:]:
                    g, s = parse_ged_name(n)
                    variants.append(" ".join(x for x in (s, g) if x))
                row = case.add("persons", {"preferred_label": item["label"], "sex": sex,
                                           "living_status": "deceased" if deat is not None else "unknown",
                                           "name_variants": ";".join(v for v in variants if v),
                                           "status": "tree-entry-unverified"}, actor)
                pid = row["person_id"]
            xref_to_pid[node["xref"]] = pid
            case.add("mentions", {"artifact_id": aid, "name_as_written": (item["names"][0] if item["names"] else item["label"]).replace("/", ""),
                                  "role": "subject", "details": f"GEDCOM {node['xref']}", "person_id": pid,
                                  "link_status": "confirmed" if item["how"] in ("", "REFN") else "probable",
                                  "link_rationale": {"REFN": "REFN kinship-kit совпадает с ID дела",
                                                     "xref": "тот же xref и имя в прежней версии этого древа",
                                                     "": "создан при импорте древа"}[item["how"]]}, actor)
            added: dict[str, list[str]] = {}
            for ev in node["children"]:
                ctype = TAG_TO_TYPE.get(ev["tag"])
                if not ctype or ctype in ("marriage", "divorce"):
                    continue
                cid = _add_event(case, aid, group, [pid], ctype, ev, actor)
                if cid:
                    report["claims"] += 1
                    added.setdefault(ctype, []).append(cid)
        for f in fams:
            husb, wife = xref_to_pid.get(_val(f, "HUSB")), xref_to_pid.get(_val(f, "WIFE"))
            partners = [p for p in (husb, wife) if p]
            children = [xref_to_pid[c["value"].strip()] for c in f["children"] if c["tag"] == "CHIL"
                        and c["value"].strip() in xref_to_pid]
            if len(partners) == 2 and partners[0] == partners[1]:
                partners = partners[:1]  # ошибка древа: один человек в обеих ролях
            if len(partners) == 2:
                report["relationships"] += _add_rel(case, aid, partners[0], "spouse-of", partners[1], actor)
                for ev in f["children"]:
                    if ev["tag"] in ("MARR", "DIV"):
                        report["claims"] += bool(_add_event(case, aid, group, partners, TAG_TO_TYPE[ev["tag"]], ev, actor))
            for parent in partners:
                for ch in children:
                    report["relationships"] += _add_rel(case, aid, parent, "parent-of", ch, actor)
    report["artifact"] = aid
    return report


def _add_event(case: Case, aid: str, group: str, subjects: list[str], ctype: str, ev: dict, actor: str) -> str:
    date, note = ged_to_edtf(_val(ev, "DATE"))
    place = _val(ev, "PLAC")
    labels = {"birth": "рождение", "baptism": "крещение", "death": "смерть", "burial": "погребение",
              "residence": "проживание", "occupation": "занятие", "marriage": "брак", "divorce": "развод"}
    arts = case.index("artifacts")
    for c in case.rows("claims"):  # то же событие из того же древа уже есть
        if (c["claim_type"] == ctype and split_ids(c["subject_person_ids"]) == subjects and c.get("date", "") == date
                and c.get("place", "") == place and aid not in split_ids(c.get("artifact_ids"))
                and any(arts.get(a, {}).get("independence_group") == group for a in split_ids(c.get("artifact_ids")))):
            return ""
    statement = f"По семейному древу (GEDCOM): {labels.get(ctype, ctype)}"
    if ev.get("value") and ctype == "occupation":
        statement += f" — {ev['value']}"
    raw = _val(ev, "DATE")
    if raw:
        statement += f", {raw}"
    if place:
        statement += f", {place}"
    if note:
        statement += f" ({note})"
    row = case.add("claims", {"claim_type": ctype, "subject_person_ids": ";".join(subjects), "statement": statement,
                              "date": date, "place": place, "artifact_ids": aid, "status": "single-source",
                              "confidence": "low", "rationale": "Сведения семейного древа — наводка, нужна проверка по документам"},
                   actor)
    if ctype in ("birth", "baptism", "death", "burial", "marriage") and date:
        rivals = [c["claim_id"] for c in case.rows("claims") if c["claim_id"] != row["claim_id"]
                  and c["claim_type"] == ctype and split_ids(c["subject_person_ids"]) == subjects
                  and c.get("date") and c["date"] != date and c["status"] not in CLOSED]
        if rivals:  # другая дата того же события — конкурирующая версия, а не молчаливый дубль
            case.update(row["claim_id"], {}, actor, append={"competing_claim_ids": rivals[0]})
    return row["claim_id"]


def _add_rel(case: Case, aid: str, a: str, rtype: str, b: str, actor: str) -> int:
    for r in case.rows("relationships"):
        same = (r["relationship_type"] == rtype and
                ((case.resolve_person(r["person_a_id"]), case.resolve_person(r["person_b_id"])) == (a, b)
                 or (rtype != "parent-of" and (case.resolve_person(r["person_b_id"]), case.resolve_person(r["person_a_id"])) == (a, b))))
        if same:
            return 0
    case.add("relationships", {"person_a_id": a, "relationship_type": rtype, "person_b_id": b, "nature": "unknown",
                               "supporting_artifact_ids": aid, "status": "single-source",
                               "rationale": "Из семейного древа (GEDCOM) — требует проверки по документам"}, actor)
    return 1
