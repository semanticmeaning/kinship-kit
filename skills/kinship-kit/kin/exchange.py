"""Полный экспорт/импорт дела (собственный формат без потерь), резервная копия и восстановление.

Формат kinship-kit-export (docs/EXPORT.md): настройки дела, все реестры, журнал, манифест источников
(и, по желанию, сами файлы в base64). Импорт идемпотентен: та же запись — пропуск, другая запись с тем же ID —
конфликт (ничего не пишется), новая — добавляется. Повторный импорт не размножает дубликаты.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import io
import json
import os
import shutil
import tarfile
from pathlib import Path

from . import __version__
from .store import CASE_FILE, REGISTERS, REGISTRY_DIR, SCHEMA_VERSION, Case, KinError, field_names, now_iso, sha256_file

FORMAT = "kinship-kit-export"
FORMAT_VERSION = 1
BACKUP_EXCLUDE = {".kin/write.lock", ".kin/index.sqlite"}
BACKUP_EXCLUDE_DIRS = {"site", "publish", ".kin/tmp"}
CONFIG_KEYS = {"title", "language", "created", "case_id", "root_person", "lines", "privacy", "limits", "review",
               "feedback", "owner", "publish"}


# ------------------------------------------------------------------ экспорт / импорт JSON


def export_data(case: Case, with_files: bool = False) -> dict:
    sources = []
    for a in case.rows("artifacts"):
        if not a.get("file"):
            continue
        path = (case.root / a["file"]).resolve()
        if case.root / "sources" not in path.parents:
            raise KinError(f"{a['artifact_id']}: файл {a['file']} вне sources/ — экспорт остановлен (kin audit)")
        item = {"artifact_id": a["artifact_id"], "file": a["file"], "sha256": a.get("sha256", ""),
                "size": path.stat().st_size if path.is_file() else None}
        if with_files and path.is_file():
            item["content_base64"] = base64.b64encode(path.read_bytes()).decode("ascii")
        sources.append(item)
    journal = []
    jp = case.root / "journal.jsonl"
    if jp.is_file():
        for line in jp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    journal.append(json.loads(line))
                except ValueError:
                    continue
    return {
        "format": FORMAT, "format_version": FORMAT_VERSION, "schema_version": SCHEMA_VERSION,
        "kin_version": __version__, "exported_at": now_iso(),
        "case": case.config,
        "registers": {name: case.rows(name) for name in REGISTERS},
        "journal": journal,
        "sources": sources,
    }


def write_export(case: Case, out: Path, with_files: bool = False, overwrite: bool = False) -> Path:
    out = Path(out).expanduser().resolve()
    if case.root == out or case.root in out.parents:
        raise KinError("Экспорт сохраняется вне папки дела (иначе он попадёт в историю и следующие копии)")
    if out.exists() and not overwrite:
        raise KinError(f"{out} уже существует — укажите другое имя или --force")
    data = export_data(case, with_files)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


def _entry_key(entry: dict) -> str:
    return json.dumps(entry, ensure_ascii=False, sort_keys=True)


def import_data(case: Case, data: dict, actor: str = "user", dry_run: bool = False) -> dict:
    """Импорт экспорта в дело. Возвращает отчёт {added, skipped, conflicts, journal_added, files}."""
    if data.get("format") != FORMAT:
        raise KinError("Это не экспорт kinship-kit (поле format)")
    if data.get("format_version") != FORMAT_VERSION:
        raise KinError(f"Версия формата {data.get('format_version')} не поддерживается (нужна {FORMAT_VERSION})")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise KinError(f"Экспорт в схеме v{data.get('schema_version')}, kin — v{SCHEMA_VERSION}. Импортируйте в дело "
                       "той же версии и выполните kin migrate, затем экспортируйте снова.")
    report = {"added": {}, "skipped": {}, "conflicts": [], "journal_added": 0, "files": 0}
    with case.lock():
        empty_case = all(not case.rows(name) for name in REGISTERS)
        new_rows: dict[str, list[dict]] = {}
        for name, rows in data.get("registers", {}).items():
            if name not in REGISTERS:
                raise KinError(f"Неизвестный реестр в экспорте: {name}")
            key = REGISTERS[name]["id"]
            fields = field_names(name)
            have = case.index(name)
            seen_ids = set()
            if not isinstance(rows, list):
                raise KinError(f"{name}: ожидается список строк")
            for row in rows:
                if not isinstance(row, dict) or not all(isinstance(v, str) for v in row.values()):
                    raise KinError(f"{name}: строка должна быть объектом со строковыми значениями")
                if row.get(key) in seen_ids:
                    raise KinError(f"{name}: ID {row.get(key)} повторяется в экспорте")
                seen_ids.add(row.get(key))
                if set(row) != set(fields):
                    raise KinError(f"{name}: поля строки {row.get(key)} не совпадают со схемой v{SCHEMA_VERSION}")
                rid = row[key]
                if rid in have:
                    if have[rid] == row:
                        report["skipped"][name] = report["skipped"].get(name, 0) + 1
                    else:
                        diff = sorted(k for k in fields if have[rid].get(k) != row.get(k))
                        report["conflicts"].append(f"{rid}: отличаются поля {', '.join(diff)}")
                    continue
                new_rows.setdefault(name, []).append(row)
        if report["conflicts"]:
            return report  # ничего не пишем: конфликты разбирает человек
        # проверка схемы и ссылок по объединённому набору
        new_ids = {name: {r[REGISTERS[name]["id"]] for r in rows} for name, rows in new_rows.items()}
        errors = []
        for name, rows in new_rows.items():
            for r in rows:
                errors += case.validate(name, r, new_ids=new_ids)
        if errors:
            raise KinError("Импорт не выполнен — ошибки в данных:\n- " + "\n- ".join(errors[:30]))
        # файлы источников
        files_to_write = []
        for s in data.get("sources", []):
            dest = (case.root / s["file"]).resolve()
            if case.root / "sources" not in dest.parents:
                raise KinError(f"Путь источника вне sources/: {s['file']}")
            if dest.exists():
                if s.get("sha256") and sha256_file(dest) != s["sha256"]:
                    report["conflicts"].append(f"{s['file']}: файл уже есть и отличается")
                continue
            if "content_base64" in s:
                content = base64.b64decode(s["content_base64"])
                if s.get("sha256") and hashlib.sha256(content).hexdigest() != s["sha256"]:
                    raise KinError(f"{s['file']}: содержимое не совпадает с sha256 в экспорте")
                files_to_write.append((dest, content))
        if report["conflicts"]:
            return report
        existing_journal = set()
        jp = case.root / "journal.jsonl"
        if jp.is_file():
            existing_journal = {_entry_key(json.loads(line)) for line in jp.read_text(encoding="utf-8").splitlines() if line.strip()}
        bad = [e for e in data.get("journal", []) if not (isinstance(e, dict) and isinstance(e.get("op"), str)
                                                          and isinstance(e.get("id", ""), str) and isinstance(e.get("data", {}), dict))]
        if bad:
            raise KinError(f"Журнал экспорта повреждён: {len(bad)} записей не в формате {{ts, actor, op, id, data}}")
        journal_new = [e for e in data.get("journal", []) if _entry_key(e) not in existing_journal]
        report["added"] = {name: len(rows) for name, rows in new_rows.items()}
        report["journal_added"] = len(journal_new)
        report["files"] = len(files_to_write)
        if dry_run:
            return report
        for dest, content in files_to_write:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            os.chmod(dest, 0o444)
        for name, rows in new_rows.items():
            case._write(name, list(case.rows(name)) + rows)
        if journal_new:
            with open(jp, "a", encoding="utf-8") as fh:
                for e in journal_new:
                    fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        if empty_case:  # восстановление: известные настройки из экспорта (кроме версии схемы)
            imported = {k: v for k, v in (data.get("case") or {}).items() if k in CONFIG_KEYS}
            cfg = {**case.config, **imported, "schema_version": SCHEMA_VERSION, "kin_case": True}
            case.config = cfg
            case.save_config(actor, "import-config", {})
        case.journal(actor, "import", "export", {k: report[k] for k in ("added", "journal_added", "files")})
    return report


# ------------------------------------------------------------------ резервная копия


def _backup_members(root: Path, with_git: bool, dirs: bool = False) -> list[Path]:
    """Файлы (или, при dirs=True, папки — нужны пустые служебные папки git) для резервной копии."""
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink() or (p.is_dir() != dirs):
            continue
        if rel in BACKUP_EXCLUDE or any(rel == d or rel.startswith(d + "/") for d in BACKUP_EXCLUDE_DIRS):
            continue
        if rel.startswith(".kin/backup-"):
            continue  # резервные копии миграций — не нужны в каждой копии
        if not with_git and (rel == ".git" or rel.startswith(".git/")):
            continue
        out.append(p)
    return out


def backup(case: Case, out: Path | None = None, with_git: bool = True) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(out).expanduser() if out else Path.home() / "kinship-backups" / f"{case.root.name}-{stamp}.tar.gz"
    out = out.resolve()
    if case.root == out or case.root in out.parents:
        raise KinError("Резервная копия сохраняется вне папки дела")
    if out.exists():
        raise KinError(f"{out} уже существует — резервные копии не перезаписываются")
    out.parent.mkdir(parents=True, exist_ok=True)
    with case.lock():  # согласованный снимок: никто не пишет во время копирования
        members = _backup_members(case.root, with_git)
        manifest = {"format": "kinship-kit-backup", "version": 1, "created": now_iso(), "kin_version": __version__,
                    "schema_version": SCHEMA_VERSION, "case": case.root.name,
                    "files": {p.relative_to(case.root).as_posix(): sha256_file(p) for p in members}}
        tmp = out.with_suffix(".tmp")
        with tarfile.open(tmp, "w:gz") as tar:
            data = json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8")
            info = tarfile.TarInfo("MANIFEST.json")
            info.size = len(data)
            info.mtime = int(dt.datetime.now().timestamp())
            tar.addfile(info, io.BytesIO(data))
            for p in _backup_members(case.root, with_git, dirs=True) + members:
                tar.add(p, arcname="case/" + p.relative_to(case.root).as_posix(), recursive=False)
        os.replace(tmp, out)
    os.chmod(out, 0o600)
    return out


def restore(archive: Path, target: Path) -> dict:
    archive, target = Path(archive).expanduser().resolve(), Path(target).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        raise KinError(f"{target} не пуста — восстанавливайте в новую папку")
    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
        if "MANIFEST.json" not in names:
            raise KinError("В архиве нет MANIFEST.json — это не резервная копия kinship-kit")
        manifest = json.loads(tar.extractfile("MANIFEST.json").read().decode("utf-8"))
        for m in tar.getmembers():
            if m.name == "MANIFEST.json":
                continue
            if not m.name.startswith("case/") or ".." in Path(m.name).parts or m.issym() or m.islnk() or m.isdev():
                raise KinError(f"Небезопасный элемент архива: {m.name}")
        tmp = target.parent / f".{target.name}.restore-tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        try:
            members = [m for m in tar.getmembers() if m.name.startswith("case/")]
            if hasattr(tarfile, "data_filter"):
                tar.extractall(tmp, members=members, filter="data")
            else:  # Python 3.10/3.11 без фильтров — элементы уже проверены выше
                tar.extractall(tmp, members=members)
            restored = tmp / "case"
            bad = [rel for rel, digest in manifest["files"].items()
                   if not (restored / rel).is_file() or sha256_file(restored / rel) != digest]
            listed = set(manifest["files"])
            bad += [f"лишний файл {p.relative_to(restored).as_posix()}" for p in restored.rglob("*")
                    if p.is_file() and p.relative_to(restored).as_posix() not in listed]
            if bad:
                raise KinError("Архив повреждён — не совпадают контрольные суммы:\n- " + "\n- ".join(bad[:20]))
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target.rmdir()
            os.replace(restored, target)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    for sub in ("site", "publish", ".kin"):
        (target / sub).mkdir(exist_ok=True)
    return {"files": len(manifest["files"]), "schema_version": manifest.get("schema_version"), "created": manifest.get("created")}


__all__ = ["export_data", "write_export", "import_data", "backup", "restore", "CASE_FILE", "REGISTRY_DIR"]
