"""Миграции схемы дела: kin migrate.

Каждая версия схемы сохраняется в kin/schemas/v<N>.json (текущая — kin/schema.json).
Шаг N→N+1: проверить, что заголовки реестров совпадают со схемой N; сделать резервную копию registry/ и case.json
в .kin/backup-v<N>-<время>/; переписать реестры по схеме N+1 (переименования — из RENAMES, новые поля — пустые);
создать новые реестры; записать schema_version. Данные не удаляются: поле, исчезнувшее из схемы без
переименования, останавливает миграцию.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import shutil
from pathlib import Path

from .store import CASE_FILE, REGISTRY_DIR, SCHEMA, SCHEMA_VERSION, KinError

HERE = Path(__file__).resolve().parent

# {версия_откуда: {реестр: {старое_поле: новое_поле}}}
RENAMES: dict[int, dict[str, dict[str, str]]] = {1: {}}
NOTES = {1: "v1→v2: задачи — тип, ценность, стоимость, доступ, внешний сервис, согласие, файл задания; "
            "поиск — основание повтора; новые реестры reviews (V-) и requests (Q-)."}


def schema_of(version: int) -> dict:
    if version == SCHEMA_VERSION:
        return SCHEMA
    path = HERE / "schemas" / f"v{version}.json"
    if not path.is_file():
        raise KinError(f"Нет описания схемы v{version} — миграция невозможна")
    return json.loads(path.read_text(encoding="utf-8"))


def _fields(schema: dict, register: str) -> list[str]:
    return [f["name"] for f in schema["registers"][register]["fields"]]


def plan(root: Path) -> tuple[int, list[int]]:
    config = json.loads((root / CASE_FILE).read_text(encoding="utf-8"))
    current = int(config.get("schema_version", 1))
    if current > SCHEMA_VERSION:
        raise KinError(f"Дело в схеме v{current}, а kin знает только до v{SCHEMA_VERSION}: обновите навык.")
    return current, list(range(current, SCHEMA_VERSION))


def _step(root: Path, version: int) -> str:
    old, new = schema_of(version), schema_of(version + 1)
    renames = RENAMES.get(version, {})
    reg_dir = root / REGISTRY_DIR
    staged: dict[Path, list[list[str]]] = {}
    for name, reg in new["registers"].items():
        new_fields = _fields(new, name)
        old_reg = old["registers"].get(name)
        path = reg_dir / reg["file"]
        if old_reg is None:
            if path.exists():
                raise KinError(f"{path.name} уже существует, хотя в схеме v{version} его нет — разберитесь вручную")
            staged[path] = [new_fields]
            continue
        old_path = reg_dir / old_reg["file"]
        with open(old_path, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        header = rows[0] if rows else []
        if header != _fields(old, name):
            raise KinError(f"{old_path.name}: заголовок не совпадает со схемой v{version} — миграция остановлена")
        mapping = {renames.get(name, {}).get(h, h): i for i, h in enumerate(header)}
        lost = set(mapping) - set(new_fields)
        if lost:
            raise KinError(f"{name}: поля {sorted(lost)} исчезают в v{version + 1} без переименования — миграция остановлена")
        out = [new_fields] + [[row[mapping[f]] if f in mapping else "" for f in new_fields] for row in rows[1:]]
        staged[path] = out
    # запись только после успешной проверки всех реестров
    for path, rows in staged.items():
        tmp = path.with_suffix(".csv.tmp")
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            csv.writer(fh, lineterminator="\n").writerows(rows)
        os.replace(tmp, path)
    return NOTES.get(version, f"v{version}→v{version + 1}")


def migrate(root: Path, actor: str = "user", dry_run: bool = False) -> list[str]:
    root = Path(root)
    current, steps = plan(root)
    if not steps:
        return []
    if dry_run:
        return [NOTES.get(v, f"v{v}→v{v + 1}") for v in steps]
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = root / ".kin" / f"backup-v{current}-{stamp}"
    backup.mkdir(parents=True)
    shutil.copytree(root / REGISTRY_DIR, backup / REGISTRY_DIR)
    shutil.copy2(root / CASE_FILE, backup / CASE_FILE)
    done = []
    try:
        for v in steps:
            done.append(_step(root, v))
            config = json.loads((root / CASE_FILE).read_text(encoding="utf-8"))
            config["schema_version"] = v + 1
            (root / CASE_FILE).write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        # откат к резервной копии: дело остаётся в исходной версии
        shutil.rmtree(root / REGISTRY_DIR)
        shutil.copytree(backup / REGISTRY_DIR, root / REGISTRY_DIR)
        shutil.copy2(backup / CASE_FILE, root / CASE_FILE)
        raise
    (root / "requests").mkdir(exist_ok=True)
    (root / "tasks").mkdir(exist_ok=True)
    with open(root / "journal.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "actor": actor,
                             "op": "migrate", "id": CASE_FILE,
                             "data": {"from": current, "to": SCHEMA_VERSION, "backup": str(backup.relative_to(root))}},
                            ensure_ascii=False) + "\n")
    return done
