"""Общее для модулей команд: дело, исполнитель, вывод."""
from __future__ import annotations

import json
import os

from .store import Case, find_case_dir


def _case(args) -> Case:
    return Case(find_case_dir(getattr(args, "case", None) or getattr(args, "case_global", None)))


def _actor(args) -> str:
    return " ".join((getattr(args, "actor", None) or os.environ.get("KIN_ACTOR") or "user").split())


def _out(args, data, text: str) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2) if getattr(args, "json", False) else text)
