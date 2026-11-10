"""Данные сайта-схемы (tree.json) в формате страницы kin/web/index.html.

Строятся ТОЛЬКО из публикационного набора (publish.build: фильтр приватности уже применён) и сведений о тех же
видимых записях. Уровни доказанности (lv), прямая линия, колена, линии поиска, семьи по фамилии при рождении,
документы к фактам (файлы источников: в private — все, в public — только scan_publication=allow), внешние ссылки.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from . import __version__, edtf, feedback, site
from .store import Case, split_ids

FAMILY_KINDS = {"family-oral", "family-tree", "letter", "photo"}
DOC_KINDS = {".jpg": "img", ".jpeg": "img", ".png": "img", ".webp": "img", ".gif": "img", ".pdf": "pdf",
             ".txt": "txt", ".json": "txt", ".md": "txt"}
# активное содержимое (сохранённые веб-страницы, SVG, XML) не публикуется как есть: на сайте оно выполнилось бы от имени сайта —
# выкладывается текстом (.txt), просмотрщик показывает исходный код
ACTIVE = {".html", ".htm", ".xhtml", ".shtml", ".svg", ".svgz", ".xml", ".xsl", ".xslt", ".js", ".mjs", ".css"}
REL_T = {"parent-of": "parent", "spouse-of": "spouse", "sibling-of": "sibling", "other": "kinship"}
CLAIM_T = {"parentage": "parent", "sibling": "sibling", "kinship": "kinship", "identity": "identity"}
CAND = {"candidate", "hypothesis", "unlikely"}
GEN_NAME_EN = {-1: "Parents", -2: "Grandparents", -3: "Great-grandparents", -4: "2× great-grandparents",
               1: "Children", 2: "Grandchildren", 3: "Great-grandchildren"}
GEN_NAME = {-1: "Родители", -2: "Деды и бабушки", -3: "Прадеды", -4: "Прапрадеды", 1: "Дети", 2: "Внуки", 3: "Правнуки"}
PALETTE = ["#c2410c", "#1d4ed8", "#7c3aed", "#0f766e", "#b91c1c", "#15803d", "#a16207", "#be185d", "#0369a1",
           "#4d7c0f", "#92400e", "#0e7490"]
PATR = re.compile(r"(ович|евич|ьич|овна|евна|ична|инична)$")
SURN = re.compile(r"(ов|ев|ёв|ин|ын|ский|цкий|ова|ева|ёва|ина|ына|ская|цкая|енко|ко|ук|юк|их|ых|ич|ный|ная)$")


def clean_name(label: str) -> str:
    """Имя для схемы: без пометок в скобках (девичью «(Сомова)» оставить) и без пояснения после « — » или запятой."""
    s = re.split(r"\s+—\s+", label)[0].split(",")[0]
    s = re.sub(r"\s*\((?=[а-яёa-z\d])[^)]*\)", "", s)
    return re.sub(r"\s+", " ", s).strip()


def norm(s: str, aliases: dict) -> str:
    s = (s or "").lower().replace("ё", "е")
    for a, b in aliases.items():
        s = s.replace(a, b)
    return re.sub(r"[^\w\s-]", " ", s)


def _date(value: str, ok: bool, conflict: bool, lang: str) -> dict | None:
    if not value:
        return None
    a, b = edtf.years(value)
    d = edtf.parse(value) or {}
    approx = bool(d.get("interval")) or bool((d.get("start") or {}).get("approx")) or bool((d.get("start") or {}).get("uncertain"))
    t = edtf.human(value, lang)
    return {"t": t, "y": a or b, "approx": approx, "conflict": conflict, "raw": t, "ok": ok}


def _git_change(case: Case, public: bool) -> tuple[str, dict | None]:
    def git(*args):
        r = subprocess.run(["git", "-C", str(case.root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.stdout.strip() if r.returncode == 0 else ""
    log = git("log", "-1", "--format=%h%x1f%cI%x1f%s%x1f%B", "--", "registry", "case.json")
    if not log:
        return f"kinship-kit {__version__}", None
    commit, date, subject, body = (log.split("\x1f") + ["", "", "", ""])[:4]
    chats = re.findall(r"^Чат:\s*(.+?)\s*$", body, re.M)
    change = {"commit": commit, "date": date, "subject": "" if public else subject, "chat": chats[-1] if chats else ""}
    return f"kinship-kit {__version__}", change


DEFAULT_LINE_COLOR = "#8a7f6d"


def _color(value) -> str:
    """Цвет линии — только #hex: case.json можно править вручную, а значение попадает в атрибут style страницы."""
    return value if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{3,8}", value) else DEFAULT_LINE_COLOR


PHOTO_KINDS = {".jpg", ".jpeg", ".png", ".webp"}
POT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,40}$")


def _warn(text: str) -> None:
    print(f"предупреждение: {text}", file=sys.stderr)


def _stories(case: Case, visible: set, public: bool, h) -> dict:
    """Рассказы: stories/P-….md в папке дела (абзацы через пустую строку; необязательная шапка --- … ---).
    В публичную версию — только по решению автора (privacy.public_stories=allow); утечки ловит проверка сборки."""
    out = {}
    if public and case.config.get("privacy", {}).get("public_stories") != "allow":
        return out
    for f in sorted((case.root / "stories").glob("P-*.md")):
        raw = f.read_text(encoding="utf-8")
        h.update(raw.encode())
        m = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
        head, body = (m.group(1), raw[m.end():]) if m else ("", raw)
        m = re.search(r"person_id:\s*(P-\d+)", head)
        pid = case.resolve_person(m.group(1) if m else f.stem)
        paras = [re.sub(r"\s*\n\s*", " ", t).strip() for t in re.split(r"\n\s*\n", body) if t.strip()]
        if pid in visible and paras:
            out[pid] = paras
    return out


def _portraits(case: Case, visible: set, public: bool, reg_arts: dict, manifest: list) -> dict:
    """Портреты: case.json → site.portraits {"P-…": {"artifact": "A-…", "crop": "x0,y0,x1,y1"}} (доли кадра, лицо).
    Файл — источник дела (фото); в публичной версии — только при scan_publication=allow, как и документы."""
    out = {}
    for pid0, spec in sorted((case.config.get("site", {}).get("portraits") or {}).items()):
        pid = case.resolve_person(pid0)
        spec = spec if isinstance(spec, dict) else {}
        aid, a = spec.get("artifact", ""), reg_arts.get(spec.get("artifact", ""), {})
        f = (case.root / a["file"]).resolve() if a.get("file") else None
        if pid not in visible:
            continue
        if not f or case.root / "sources" not in f.parents or not f.is_file() or f.suffix.lower() not in PHOTO_KINDS:
            _warn(f"site.portraits {pid0}: {aid or '—'} — нужен источник-изображение (jpg, png, webp) из sources/")
            continue
        if public and a.get("scan_publication") != "allow":
            continue
        crop = None
        if spec.get("crop"):
            try:
                crop = [float(x) for x in str(spec["crop"]).split(",")]
                assert len(crop) == 4 and 0 <= crop[0] < crop[2] <= 1 and 0 <= crop[1] < crop[3] <= 1
            except (ValueError, AssertionError):
                _warn(f"site.portraits {pid0}: crop — «x0,y0,x1,y1» в долях кадра (0…1)")
                crop = None
        name = f"photos/{aid}{f.suffix.lower()}"
        if (f, name) not in manifest:
            manifest.append((f, name))
        out[pid] = {"f": name, "crop": crop}
    return out


def _versions(case: Case, visible: set) -> dict:
    """Рамки версий: case.json → site.versions {version_groups, marriage_order, rank} (решение автора).
    Группа, где есть невидимый в этой версии человек, не выводится целиком — скрытые не раскрываются через рамки."""
    cfg = case.config.get("site", {}).get("versions") or {}
    seen = lambda ids: all(case.resolve_person(i) in visible for i in ids)  # noqa: E731
    groups = []
    for g in cfg.get("version_groups") or []:
        try:
            members = [i for v in g["versions"] for i in v]
            pot = g.get("pot")
            if pot:
                assert POT_ID.match(pot["id"]) and pot["of"] in members and pot.get("sex", "U") in ("M", "F", "U")
                pot = {"id": pot["id"], "of": pot["of"], "sex": pot.get("sex", "U"), "role": str(pot.get("role", ""))[:20]}
            real = [i for i in members if not (pot and i == pot["id"])]
            ids = list(g["slot"]) + real + list(g.get("after") or [])
        except (KeyError, TypeError, AssertionError):
            _warn("site.versions: группа версий не разобрана — нужны slot, versions, необязательно pot {id, of, sex, role} и after")
            continue
        missing = [i for i in ids if i not in case.index("persons")]
        if missing:
            _warn(f"site.versions: нет людей {', '.join(missing)}")
            continue
        if seen(ids):
            groups.append({"slot": list(g["slot"]), "versions": [list(v) for v in g["versions"]],
                           **({"pot": pot} if pot else {}), "after": list(g.get("after") or [])})
    order = {k: [x for x in v if case.resolve_person(x) in visible]
             for k, v in (cfg.get("marriage_order") or {}).items() if case.resolve_person(k) in visible and isinstance(v, list)}
    rank = {k: int(v) for k, v in (cfg.get("rank") or {}).items()
            if case.resolve_person(k) in visible and isinstance(v, int) and 0 <= v <= 3}
    return {"groups": groups, "marriage_order": order, "rank": rank}


def build(case: Case, profile: str, pub: dict) -> tuple[dict, list[tuple[Path, str]]]:
    """(tree.json, [(файл источника, путь в сайте)]). pub — результат publish.build (уже отфильтрован)."""
    public = profile == "public"
    lang = case.config.get("language", "ru")
    reg_persons = case.index("persons")
    reg_claims = case.index("claims")
    reg_arts = case.index("artifacts")
    aliases = {k.lower(): v.lower() for k, v in (case.config.get("site", {}).get("search_aliases") or {}).items()}
    visible = {p["id"] for p in pub["persons"]}
    pmap = {p["id"]: p for p in pub["persons"]}
    sources = {s["id"]: s for s in pub["sources"]}

    # --- файлы источников, доступные в этом профиле
    files_of, manifest = {}, []
    for aid in sources:
        a = reg_arts.get(aid, {})
        f = a.get("file", "")
        if not f or (public and a.get("scan_publication") != "allow") or a.get("kind") == "family-tree":
            continue
        p = (case.root / f).resolve()
        if case.root / "sources" not in p.parents or not p.is_file():
            continue
        name = re.sub(r"^A-\d+__", "", p.name)
        if p.suffix.lower() in ACTIVE or p.suffix.lower() not in DOC_KINDS:
            name += ".txt"  # только как текст
        files_of[aid] = [name]
        manifest.append((p, f"docs/{aid}/{name}"))

    def fam_src(aid):
        return sources.get(aid, {}).get("kind") in FAMILY_KINDS

    def has_doc(arts):
        return any(a in sources and not fam_src(a) for a in arts)

    def docs_for(arts):
        return [{"a": a, "f": files_of[a]} for a in arts if a in files_of]

    # --- утверждения
    claims, by_person = {}, defaultdict(list)
    for c in pub["claims"]:
        st, arts = c["status"], c["sources"]
        lv = ("rejected" if st in ("rejected", "superseded") else "open" if st in ("contradicted", "unresolved")
              else "hyp" if st == "hypothesis" else "family" if not has_doc(arts)
              else "doc2" if st in ("corroborated", "strongly-corroborated") else "doc1")
        claims[c["id"]] = {"id": c["id"], "text": c["statement"], "type": c["type"], "st": st, "lv": lv, "subj": c["subjects"],
                           "next": "" if public else reg_claims.get(c["id"], {}).get("next_action", ""),  # планы — не для публики
                           "why": c.get("rationale", ""),
                           "arts": arts, "docs": docs_for(arts)}
        for s in c["subjects"]:
            by_person[s].append(c["id"])

    # --- связи
    edges, seen = [], set()

    def add_edge(e):
        key = (e["t"], *sorted((e["a"], e["b"])))
        if key in seen or e["a"] not in visible or e["b"] not in visible or e["a"] == e["b"]:
            return
        seen.add(key)
        edges.append(e)

    def need_for(cids, a, b):
        for cid in cids:
            if claims.get(cid, {}).get("next"):
                return claims[cid]["next"]
        for cid in by_person[a]:
            c = claims[cid]
            if c["lv"] in ("hyp", "open") and {a, b} <= set(c["subj"]) and c["next"]:
                return c["next"]
        return ""

    cand = lambda pid: reg_persons.get(pid, {}).get("status") in CAND  # noqa: E731
    for r in pub["relationships"]:
        t = REL_T.get(r["type"])
        arts = list(dict.fromkeys(r["sources"] + [a for cid in r["claims"] for a in claims.get(cid, {}).get("arts", [])]))
        st = r["status"]
        lv = ("rejected" if st in ("rejected", "superseded") else
              "research" if st in ("hypothesis", "contradicted", "unresolved") or cand(r["a"]) or cand(r["b"]) else
              "family" if not has_doc(arts) else "doc2" if st in ("corroborated", "strongly-corroborated") else "doc1")
        e = {"id": r["id"], "a": r["a"], "b": r["b"], "t": t, "lv": lv, "st": st, "claims": r["claims"], "arts": arts,
             "why": r.get("rationale", ""), "docs": docs_for(arts)}
        if lv in ("research", "rejected"):
            e["need"] = need_for(r["claims"], r["a"], r["b"])
        if lv == "rejected":
            e["reason"] = r.get("rationale", "")
        add_edge(e)
    for c in claims.values():  # гипотезы родства и «возможно, одно лицо» — из утверждений
        t = CLAIM_T.get(c["type"])
        s = [x for x in c["subj"] if x in visible]
        if not t or len(s) < 2 or (t != "identity" and c["lv"] not in ("hyp", "open", "rejected")):
            continue
        a, b = s[0], s[1]  # в parentage первый — родитель
        add_edge({"id": c["id"], "a": a, "b": b, "t": t, "lv": "rejected" if c["lv"] == "rejected" else "research",
                  "st": c["st"], "claims": [c["id"]], "arts": c["arts"], "why": c["text"], "need": c["next"],
                  "docs": c["docs"], **({"reason": c["why"] or c["text"]} if c["lv"] == "rejected" else {})})
    for c in claims.values():  # окончание брака
        if c["type"] in ("divorce", "widowhood") and len(c["subj"]) >= 2:
            for e in edges:
                if e["t"] == "spouse" and {e["a"], e["b"]} == set(c["subj"][:2]):
                    e["end"] = {"kind": "divorce" if c["type"] == "divorce" else "widow", "claim": c["id"], "text": c["text"], "lv": c["lv"]}
    edges.sort(key=lambda e: (e["t"], e["a"], e["b"], e["id"]))

    # --- колена (как в site.generations) и прямая линия
    gen = site.generations(pub)
    root = pub["meta"]["root"]
    known = [g for g in gen.values() if g is not None]
    floor = (min(known) - 1) if known else -2
    for pid in gen:
        if gen[pid] is None:
            gen[pid] = floor  # без опоры — над всеми, чтобы не смешивать с прямой линией
    par, kids = defaultdict(list), defaultdict(list)
    for e in edges:
        if e["t"] == "parent" and e["lv"] != "rejected":
            par[e["b"]].append(e["a"])
            kids[e["a"]].append(e["b"])
    direct = {root} if root else set()
    for graph in (par, kids):
        stack = [root] if root else []
        while stack:
            x = stack.pop()
            for y in graph[x]:
                if y not in direct:
                    direct.add(y)
                    stack.append(y)
    for e in edges:
        if e["t"] == "spouse" and root in (e["a"], e["b"]):
            direct.add(e["b"] if e["a"] == root else e["a"])

    # --- линии поиска (case.json → lines; focus — ID людей через «;»)
    lines = []
    for ln in case.config.get("lines", []):
        focus = [x for x in split_ids(ln.get("focus", "")) if x in visible] if isinstance(ln.get("focus", ""), str) else \
            [x for x in ln.get("focus", []) if x in visible]
        lines.append({"id": ln["id"], "title": ln.get("title", ln["id"]), "state": ln.get("state", ""),
                      "where": "" if public else ln.get("where", ""), "color": _color(ln.get("color")),
                      "surname": ln.get("surname", ""), "focus": focus})

    def own_line(pid):
        label = re.sub(r"\([^)]*\)", "", pmap[pid]["label"]).split(",")[0]
        for ln in lines:
            if ln["surname"] and re.search(re.escape(ln["surname"]), label, re.I):
                return ln["id"]
        return reg_persons.get(pid, {}).get("line") or None
    line_of = {pid: own_line(pid) for pid in visible}
    for pid in sorted(visible):
        if not line_of[pid]:
            for e in edges:
                if e["t"] in ("spouse", "parent") and pid in (e["a"], e["b"]):
                    o = e["b"] if e["a"] == pid else e["a"]
                    if line_of.get(o):
                        line_of[pid] = line_of[o]
                        break

    # --- семьи по фамилии при рождении
    variants = {}
    for base, alts in (case.config.get("family_variants") or {}).items():
        for v in [base] + list(alts):
            variants[v.lower().replace("ё", "е")] = base

    def base_form(w):
        w = w.replace("ё", "е")
        w = re.sub(r"(ов|ев|ин|ын)а$", r"\1", w)
        w = re.sub(r"(с|ц)кая$", r"\1кий", w)
        w = re.sub(r"(н|т|л)ая$", r"\1ый", w)
        return variants.get(w.lower(), w)

    def surname_of(pid):
        label = pmap[pid]["label"]
        m = re.search(r"урожд\.?\s*([А-ЯЁ][а-яё]+)", label) or re.search(r"\(([А-ЯЁ][а-яё]+)\)", label)
        if m and SURN.search(m.group(1)) and reg_persons.get(pid, {}).get("sex") == "f":
            return base_form(m.group(1))  # девичья фамилия в скобках у женщины
        words = re.findall(r"[А-ЯЁA-Z][а-яёa-z]+", re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", label).split(",")[0])
        pi = next((i for i, w in enumerate(words) if PATR.search(w)), None)
        if pi == 2:
            w = words[0]
        elif pi == 1 and len(words) > 2:
            w = words[2]
        else:
            cands = [x for x in words if SURN.search(x) and not PATR.search(x)]
            if not cands:
                return None
            w = cands[0]
        return base_form(w) if SURN.search(w) and not PATR.search(w) else None
    fam_of = {pid: surname_of(pid) for pid in visible}
    sex_of = {pid: {"m": "M", "f": "F"}.get(reg_persons.get(pid, {}).get("sex", ""), "U") for pid in visible}
    for _ in range(2):
        for pid in sorted(fam_of):
            if fam_of[pid]:
                continue
            sp = [e["b"] if e["a"] == pid else e["a"] for e in edges if e["t"] == "spouse" and pid in (e["a"], e["b"])]
            pa = sorted((e["a"] for e in edges if e["t"] == "parent" and e["b"] == pid), key=lambda x: sex_of.get(x) != "M")
            fam_of[pid] = next((fam_of[x] for x in sp + pa if fam_of.get(x)), None)
    counts = defaultdict(int)
    for f in fam_of.values():
        if f:
            counts[f] += 1

    def plural(f):
        return re.sub(r"ий$", "ие", f) if re.search(r"(ский|цкий)$", f) else (f + "ы" if re.search(r"(ов|ев|ин|ын)$", f) else f)
    families = [{"key": f, "name": plural(f), "count": n, "color": PALETTE[i]}
                for i, (f, n) in enumerate(sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:len(PALETTE)])]

    # --- люди
    written = defaultdict(list)
    for m in case.rows("mentions"):
        pid = case.resolve_person(m.get("person_id", "")) if m.get("person_id") else ""
        if pid in visible and m.get("artifact_id") in sources and m.get("link_status") in ("probable", "confirmed"):
            written[pid].append(m["name_as_written"])
    persons = []
    for pid in sorted(visible):
        p, r = pmap[pid], reg_persons.get(pid, {})
        pc = [claims[c] for c in by_person[pid] if c in claims]
        arts = list(dict.fromkeys(a for c in pc for a in c["arts"]))
        for e in edges:
            if pid in (e["a"], e["b"]):
                arts += [a for a in e["arts"] if a not in arts]
        ok = lambda types, pc=pc: any(c["type"] in types and c["lv"] in ("doc1", "doc2") for c in pc)  # noqa: E731
        conflict = lambda types, pc=pc: len({reg_claims.get(c["id"], {}).get("date") for c in pc  # noqa: E731
                                      if c["type"] in types and c["lv"] != "rejected" and reg_claims.get(c["id"], {}).get("date")}) > 1
        b = _date(p["birth"], ok({"birth", "baptism"}), conflict({"birth"}), lang)
        d = _date(p["death"], ok({"death", "burial"}), conflict({"death"}), lang)
        places = p.get("places") or []
        living = r.get("living_status", "unknown")
        persons.append({
            "id": pid, "gen": gen.get(pid, 0), "sex": sex_of[pid],
            "living": {"living": "living", "deceased": "deceased"}.get(living, "unknown"),
            "cand": r.get("status", "candidate"), "direct": pid in direct, "line": line_of.get(pid), "comp": None,
            "name": clean_name(p["label"]), "full": p["label"], "written": "; ".join(dict.fromkeys(written[pid])),
            "variants": "; ".join(p.get("variants") or []), "nameOk": has_doc(arts), "b": b, "d": d,
            "place": {"t": places[0] if places else "", "ok": ok({"birth", "baptism"})}, "places": "; ".join(places),
            "juris": "", "occ": "; ".join(c["text"] for c in pc if c["type"] == "occupation"), "conf": "", "reported": "",
            "merge": "", "notes": "", "arts": arts, "docs": sum(1 for a in arts if a in sources and not fam_src(a)),
            "claims": [c["id"] for c in pc],
            "q": norm(" ".join([p["label"], "; ".join(p.get("variants") or []), " ".join(written[pid])]), aliases),
            "fam": fam_of.get(pid),
        })

    out_claims = []
    for cid in sorted(claims):
        c = claims[cid]
        out_claims.append({**c, "line": next((line_of.get(s) for s in c["subj"] if line_of.get(s)), None)})

    arts_out = {}
    for aid, s in sources.items():
        arts_out[aid] = {"title": s["title"], "repo": s.get("repository", ""), "ref": s.get("reference", ""),
                         "date": s.get("date", ""), "type": s.get("kind", ""), "fam": fam_src(aid), "where": "",
                         "urls": [s["url"]] if str(s.get("url", "")).startswith(("http://", "https://")) else [],
                         "files": [{"n": n, "k": DOC_KINDS.get(Path(n).suffix.lower(), "file")} for n in files_of.get(aid, [])]}

    # --- колена: подписи и годы
    years = defaultdict(list)
    for p in persons:
        if p["b"] and p["b"]["y"]:
            years[p["gen"]].append(p["b"]["y"])
    root_given = ""
    if root in pmap:
        words = clean_name(pmap[root]["label"]).split()
        root_given = words[1] if len(words) > 1 else (words[0] if words else "")
    gens = {}
    for g in sorted({p["gen"] for p in persons}):
        ys = sorted(years.get(g, []))
        if len(ys) >= 3:
            lo, hi = ys[len(ys) // 10], ys[-1 - len(ys) // 10]
        elif ys:
            lo, hi = ys[0] - 10, ys[-1] + 10
        else:
            lo = hi = 0
        name = (("Поколение: " + root_given) if root_given else "Поколение корня") if g == 0 else \
            GEN_NAME.get(g) or (f"{-g - 2}× прадеды" if g < 0 else f"{g - 1}× правнуки")
        name_en = (("Generation: " + root_given) if root_given else "Root generation") if g == 0 else \
            GEN_NAME_EN.get(g) or (f"{-g - 2}× great-grandparents" if g < 0 else f"{g - 1}× great-grandchildren")
        gens[str(g)] = {"name": name, "name_en": name_en, "from": lo // 5 * 5, "to": -(-hi // 5) * 5}

    # --- сведения семьи (принятые исследователем; только приватная версия; e-mail не выводится)
    fb_items = []
    if not public:
        for rp in sorted((case.root / feedback.DRAFTS / "_accepted").glob("FR-*/report.json")):
            try:
                rr = json.loads(rp.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if rr.get("person_id") in visible:
                fb_items.append({"id": rr["id"], "person": rr["person_id"], "other": "", "relation": "", "kind": "person",
                                 "author": feedback._mask(rr.get("author_name", "")), "date": rr.get("received", "")[:10],
                                 "text": feedback._mask(rr.get("text", "")), "status": "принято (со слов)", "claims": []})

    h = hashlib.sha256()
    for name in ("persons", "claims", "relationships", "artifacts"):
        h.update(case.path(name).read_bytes())
    h.update(json.dumps(case.config.get("lines", []), sort_keys=True, ensure_ascii=False).encode())
    h.update(json.dumps(case.config.get("site", {}), sort_keys=True, ensure_ascii=False).encode())

    # --- рассказы, портреты, рамки версий (решения автора дела)
    stories = _stories(case, visible, public, h)
    portraits = _portraits(case, visible, public, reg_arts, manifest)
    versions = _versions(case, visible)
    for x in persons:
        if x["id"] in stories:
            x["story"] = stories[x["id"]]
        if x["id"] in portraits:
            x["photo"] = portraits[x["id"]]
        if x["id"] in versions["rank"]:
            x["rank"] = versions["rank"][x["id"]]
    schema, change = _git_change(case, public)
    asof = max((a.get("captured_at", "")[:10] for a in reg_arts.values() if a.get("captured_at")), default="")
    living_shown = not public or case.config.get("privacy", {}).get("public_living") == "allow"
    data = {"meta": {"title": case.config.get("title", ""), "version": h.hexdigest()[:12], "asof": asof or dt.date.today().isoformat(), "root": root,
                     "show_living": living_shown, "schema": schema, "change": change, "profile": profile,
                     "language": lang, "feedback": bool(pub["meta"].get("feedback")),
                     "hidden_persons": pub["meta"].get("hidden_persons"), "aliases": sorted(aliases.items())},
            "lines": lines, "gens": gens, "persons": persons, "edges": edges, "claims": out_claims,
            "arts": arts_out, "feedback": fb_items, "families": families,
            "versions": {"groups": versions["groups"], "marriage_order": versions["marriage_order"]}}
    return data, manifest
