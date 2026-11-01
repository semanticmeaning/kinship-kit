"""Производный поисковый индекс: .kin/index.sqlite (SQLite FTS5). Не источник истины — пересобирается из реестров.

kin index — пересобрать; kin find «текст» — поиск (индекс обновляется сам, если реестры изменились).
Поиск нечувствителен к регистру и «ё/е», слова запроса сравниваются по основе (падежи): «Ветлугиной» найдёт «Ветлугина».
"""
from __future__ import annotations

import hashlib
import re
import sqlite3

from .store import REGISTERS, Case, KinError

INDEX_FILE = ".kin/index.sqlite"
TEXT_FIELDS = {
    "persons": ["preferred_label", "name_variants", "places", "notes"],
    "mentions": ["name_as_written", "details", "place_as_written", "date_as_written"],
    "claims": ["statement", "place", "rationale"],
    "relationships": ["rationale"],
    "artifacts": ["title", "repository", "archival_reference", "place_as_written", "summary"],
    "places": ["name", "name_variants", "jurisdictions", "modern_name"],
    "hypotheses": ["statement", "alternatives", "open_contradictions", "test_plan"],
    "tasks": ["goal", "sources_to_check", "next_step", "close_reason"],
    "searches": ["source", "query", "variants", "allowed_conclusions", "disallowed_conclusions"],
    "reviews": ["findings"],
    "requests": ["recipient", "subject"],
}


def fold(text: str) -> str:
    return " ".join(re.findall(r"\w+", (text or "").casefold().replace("ё", "е")))


def _stem(word: str) -> str:
    return word[:-2] if len(word) > 5 else (word[:-1] if len(word) > 4 else word)


def _fingerprint(case: Case) -> str:
    h = hashlib.sha256()
    for name in sorted(REGISTERS):
        p = case.path(name)
        st = p.stat()
        h.update(f"{name}:{st.st_size}:{st.st_mtime_ns}".encode())
    return h.hexdigest()


def _connect(case: Case) -> sqlite3.Connection:
    (case.root / ".kin").mkdir(exist_ok=True)
    return sqlite3.connect(case.root / INDEX_FILE)


def build(case: Case) -> int:
    con = _connect(case)
    try:
        con.executescript("DROP TABLE IF EXISTS docs; DROP TABLE IF EXISTS meta;"
                          "CREATE VIRTUAL TABLE docs USING fts5(rid UNINDEXED, register UNINDEXED, field UNINDEXED, "
                          "raw UNINDEXED, text, tokenize='unicode61 remove_diacritics 0');"
                          "CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);")
        n = 0
        for register, fields in TEXT_FIELDS.items():
            key = REGISTERS[register]["id"]
            for row in case.rows(register):
                for f in fields:
                    if row.get(f):
                        con.execute("INSERT INTO docs VALUES (?,?,?,?,?)", (row[key], register, f, row[f], fold(row[f])))
                        n += 1
        con.execute("INSERT INTO meta VALUES ('fingerprint', ?)", (_fingerprint(case),))
        con.commit()
        return n
    finally:
        con.close()


def is_fresh(case: Case) -> bool:
    if not (case.root / INDEX_FILE).is_file():
        return False
    con = _connect(case)
    try:
        row = con.execute("SELECT v FROM meta WHERE k='fingerprint'").fetchone()
        return bool(row and row[0] == _fingerprint(case))
    except sqlite3.Error:
        return False
    finally:
        con.close()


def find(case: Case, query: str, register: str = "", limit: int = 30) -> list[dict]:
    words = [w for w in fold(query).split() if w]
    if not words:
        raise KinError("Пустой запрос")
    if register and register not in TEXT_FIELDS:
        raise KinError(f"Реестр: {', '.join(TEXT_FIELDS)}")
    if not is_fresh(case):
        build(case)
    match = " AND ".join(f'"{_stem(w)}"*' for w in words)
    sql = ("SELECT rid, register, field, raw, bm25(docs) AS score FROM docs WHERE docs MATCH ?"
           + (" AND register = ?" if register else "") + " ORDER BY score LIMIT ?")
    con = _connect(case)
    try:
        rows = con.execute(sql, (match, register, limit) if register else (match, limit)).fetchall()
    finally:
        con.close()
    seen, out = set(), []
    for rid, reg, field, raw, _score in rows:
        if (rid, field) in seen:
            continue
        seen.add((rid, field))
        out.append({"id": rid, "register": reg, "field": field, "text": raw})
    return out
