"""Неполные и приблизительные даты (подмножество EDTF).

Допустимо: пусто (неизвестно), YYYY, YYYY-MM, YYYY-MM-DD, с суффиксом ~ (около) или ? (сомнительно);
интервал A/B, открытые ../B и A/.. («не позже», «не раньше»).
Расхождение двух документов — НЕ одна дата «1880/1882», а два конкурирующих утверждения.
"""
from __future__ import annotations

import re

_POINT = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?([~?%]?)$")


def _point(text: str) -> dict | None:
    m = _POINT.match(text)
    if not m:
        return None
    year, month, day, flag = m.groups()
    if month and not 1 <= int(month) <= 12:
        return None
    if day and not 1 <= int(day) <= 31:
        return None
    return {"year": int(year), "month": int(month) if month else None, "day": int(day) if day else None,
            "approx": flag in ("~", "%"), "uncertain": flag in ("?", "%")}


def parse(value: str) -> dict | None:
    """Строка → {'start': point|None, 'end': point|None, 'interval': bool}; None — если формат неверен.
    Пустая строка → {'unknown': True}."""
    value = (value or "").strip()
    if not value:
        return {"unknown": True}
    if "/" in value:
        left, _, right = value.partition("/")
        start = None if left == ".." else _point(left)
        end = None if right == ".." else _point(right)
        if (left != ".." and start is None) or (right != ".." and end is None) or (start is None and end is None):
            return None
        if start and end and start["year"] > end["year"]:
            return None
        return {"start": start, "end": end, "interval": True}
    p = _point(value)
    return {"start": p, "end": p, "interval": False} if p else None


def is_valid(value: str) -> bool:
    return parse(value) is not None


def sort_year(value: str) -> int | None:
    """Ранний известный год — для сортировки и колен."""
    d = parse(value)
    if not d or d.get("unknown"):
        return None
    for key in ("start", "end"):
        if d.get(key):
            return d[key]["year"]
    return None


def years(value: str) -> tuple[int | None, int | None]:
    d = parse(value)
    if not d or d.get("unknown"):
        return None, None
    s, e = d.get("start"), d.get("end")
    return (s["year"] if s else None), (e["year"] if e else None)


def human(value: str, lang: str = "ru") -> str:
    """Читаемая подпись: «ок. 1855», «1890–1905», «не позже 1910», «20.06.1885»."""
    d = parse(value)
    if d is None:
        return value
    if d.get("unknown"):
        return "?" if lang != "ru" else "неизв."

    def one(p: dict) -> str:
        if p["day"]:
            s = f"{p['day']:02d}.{p['month']:02d}.{p['year']}"
        elif p["month"]:
            s = f"{p['month']:02d}.{p['year']}"
        else:
            s = str(p["year"])
        if p["approx"]:
            s = ("ок. " if lang == "ru" else "c. ") + s
        if p["uncertain"]:
            s += "?"
        return s

    if not d["interval"]:
        return one(d["start"])
    s, e = d["start"], d["end"]
    if s and e:
        return f"{one(s)}–{one(e)}"
    if e:
        return ("не позже " if lang == "ru" else "before ") + one(e)
    return ("не раньше " if lang == "ru" else "after ") + one(s)
