"""Хранилище дела: текстовые реестры CSV — единственный источник истины.

Все записи идут через Case.add / Case.update: проверка схемы и ссылок, блокировка для нескольких агентов,
атомарная запись файла, журнал действий journal.jsonl. Прямая правка CSV возможна, но `kin audit` её проверит.
"""
from __future__ import annotations

import contextlib
import csv
import datetime as dt
import hashlib
import json
import os
import re
import socket
import time
from pathlib import Path

from . import edtf

HERE = Path(__file__).resolve().parent
SCHEMA = json.loads((HERE / "schema.json").read_text(encoding="utf-8"))
SCHEMA_VERSION = SCHEMA["schema_version"]
REGISTERS = SCHEMA["registers"]
SEP = SCHEMA["id_list_separator"]
CASE_FILE = "case.json"
REGISTRY_DIR = "registry"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class KinError(Exception):
    """Ошибка, понятная пользователю (без трассировки)."""


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def split_ids(value: str) -> list[str]:
    return [p.strip() for p in (value or "").replace(",", SEP).split(SEP) if p.strip()]


def split_list(value: str) -> list[str]:
    """Списки свободного текста (имена, места) — только через «;»: запятая — часть значения («Саратов, Россия»)."""
    return [p.strip() for p in (value or "").split(SEP) if p.strip()]


def join_ids(items) -> str:
    return SEP.join(dict.fromkeys(i for i in items if i))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_source_path(value: str) -> bool:
    parts = Path(value).parts
    return bool(parts) and parts[0] == "sources" and len(parts) >= 2 and ".." not in parts \
        and not Path(value).is_absolute() and "\\" not in value


def register_by_prefix(identifier: str) -> str:
    for name, reg in REGISTERS.items():
        if identifier.startswith(reg["prefix"]) and identifier[len(reg["prefix"]):].isdigit():
            return name
    raise KinError(f"Не понимаю ID {identifier!r}: ожидается префикс " + ", ".join(r["prefix"] for r in REGISTERS.values()))


def field_names(register: str) -> list[str]:
    return [f["name"] for f in REGISTERS[register]["fields"]]


def find_case_dir(start: str | os.PathLike | None = None) -> Path:
    """--case, затем KIN_CASE, затем поиск case.json вверх от текущей папки."""
    if start:
        p = Path(start).expanduser().resolve()
        if not (p / CASE_FILE).is_file():
            raise KinError(f"{p}: не папка дела (нет {CASE_FILE}). Создать: kin init {p}")
        return p
    env = os.environ.get("KIN_CASE")
    if env:
        return find_case_dir(env)
    cur = Path.cwd().resolve()
    for d in (cur, *cur.parents):
        f = d / CASE_FILE
        if f.is_file():
            try:
                if json.loads(f.read_text(encoding="utf-8")).get("kin_case"):
                    return d
            except (OSError, ValueError):
                pass
    raise KinError("Папка дела не найдена: укажите --case DIR, переменную KIN_CASE или перейдите в папку дела.")


LOCK_STALE_SECONDS = 600


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _pid_alive(pid: int) -> bool | None:
    """Жив ли процесс; None — проверить нельзя (Windows: os.kill там завершает процесс, а не проверяет)."""
    if os.name == "nt" or pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # процесс есть, просто чужой
    except OSError:
        return None
    return True


def _lock_abandoned(lock: Path) -> bool:
    """Блокировка брошена: процесс-владелец на этой машине завершился. Живой долгий процесс (большой импорт)
    блокировку не теряет. Если проверить процесс нельзя (другая машина, Windows, файл ещё пишется) — по возрасту файла."""
    parts = _read_text(lock).split(" ")
    if len(parts) >= 3 and parts[0].isdigit() and parts[2] == socket.gethostname():
        alive = _pid_alive(int(parts[0]))
        if alive is not None:
            return not alive
    return time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS


class Case:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.config = json.loads((self.root / CASE_FILE).read_text(encoding="utf-8"))
        version = self.config.get("schema_version")
        if version != SCHEMA_VERSION:
            raise KinError(f"Версия схемы дела v{version}, версия kin v{SCHEMA_VERSION}: обновите дело — kin migrate "
                           "(сначала можно kin migrate --dry-run; резервная копия создаётся автоматически).")
        self._cache: dict[str, list[dict]] = {}
        self._lock_depth = 0

    # ---------- чтение ----------
    def path(self, register: str) -> Path:
        return self.root / REGISTRY_DIR / REGISTERS[register]["file"]

    def rows(self, register: str) -> list[dict]:
        if register not in self._cache:
            self._cache[register] = self._read(register)
        return self._cache[register]

    def _read(self, register: str) -> list[dict]:
        p = self.path(register)
        if not p.is_file():
            raise KinError(f"Нет реестра {p.relative_to(self.root)}")
        with open(p, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            expected = field_names(register)
            if reader.fieldnames != expected:
                raise KinError(f"{p.name}: заголовок не совпадает со схемой v{SCHEMA_VERSION}. "
                               f"Лишние: {sorted(set(reader.fieldnames or []) - set(expected))}, "
                               f"нет: {sorted(set(expected) - set(reader.fieldnames or []))}")
            out = []
            for row in reader:
                if None in row:
                    raise KinError(f"{p.name}: строка {reader.line_num} — лишние поля (незакавыченная запятая?)")
                out.append({k: (v or "").strip() for k, v in row.items()})
            return out

    def index(self, register: str) -> dict[str, dict]:
        key = REGISTERS[register]["id"]
        return {r[key]: r for r in self.rows(register)}

    def get(self, identifier: str) -> tuple[str, dict]:
        register = register_by_prefix(identifier)
        row = self.index(register).get(identifier)
        if row is None:
            raise KinError(f"{identifier} не найден в {REGISTERS[register]['file']}")
        return register, row

    def resolve_person(self, person_id: str) -> str:
        """Следует по merged_into: ссылки на исходные записи сохраняются, личность — итоговая."""
        persons = self.index("persons")
        seen = set()
        while person_id in persons and persons[person_id].get("merged_into") and person_id not in seen:
            seen.add(person_id)
            person_id = persons[person_id]["merged_into"]
        return person_id

    # ---------- проверка ----------
    def validate(self, register: str, row: dict, *, new_ids: dict[str, set] | None = None) -> list[str]:
        """Ошибки строки по схеме: обязательность, словари, даты, ссылки."""
        errors = []
        reg = REGISTERS[register]
        rid = row.get(reg["id"], "?")
        for f in reg["fields"]:
            name = f["name"]
            ftype, value = f.get("type", "text"), row.get(name, "")
            if f.get("required") and not value:
                errors.append(f"{rid}: не заполнено обязательное поле {name}")
                continue
            if not value:
                continue
            if "\n" in value or "\r" in value:
                errors.append(f"{rid}.{name}: перевод строки в значении")
            if ftype == "enum" and value not in f["enum"]:
                errors.append(f"{rid}.{name}: {value!r} не из словаря ({', '.join(v for v in f['enum'] if v)})")
            elif ftype == "date" and not edtf.is_valid(value):
                errors.append(f"{rid}.{name}: дата {value!r} не в формате YYYY[-MM[-DD]][~?] или A/B")
            elif ftype == "int" and not value.lstrip("-").isdigit():
                errors.append(f"{rid}.{name}: ожидается целое число")
            elif name == "file" and register == "artifacts" and not _safe_source_path(value):
                errors.append(f"{rid}.file: путь {value!r} должен вести внутрь sources/ (без «..» и абсолютных путей)")
            elif ftype == "sha256" and not SHA_RE.match(value):
                errors.append(f"{rid}.{name}: неверная контрольная сумма")
            elif ftype in ("ref", "refs"):
                target = f["ref"]
                known = set(self.index(target)) | (new_ids or {}).get(target, set())
                values = [value] if ftype == "ref" else split_ids(value)
                for v in values:
                    if v not in known:
                        errors.append(f"{rid}.{name}: ссылка на несуществующий {v}")
        return errors

    # ---------- запись ----------
    @contextlib.contextmanager
    def lock(self, timeout: float = 30.0):
        """Межпроцессная блокировка дела: два агента не пишут реестры одновременно.
        Повторно входимая: составная операция (копия файла + запись) держит её целиком."""
        if self._lock_depth:
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1
            return
        lock_dir = self.root / ".kin"
        lock_dir.mkdir(exist_ok=True)
        lock = lock_dir / "write.lock"
        deadline = time.monotonic() + timeout
        while True:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {now_iso()} {socket.gethostname()}".encode())
                os.close(fd)
                break
            except FileExistsError:
                try:
                    if _lock_abandoned(lock):
                        # переименование атомарно: снять чужую брошенную блокировку сможет только один процесс
                        os.rename(lock, lock_dir / f"write.lock.stale-{os.getpid()}")
                        (lock_dir / f"write.lock.stale-{os.getpid()}").unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() > deadline:
                    owner = _read_text(lock).split(" ")[0] or "?"
                    raise KinError(f"Дело занято другой записью ({lock}, процесс {owner}). "
                                   "Если процесс завис — завершите его или удалите файл.") from None
                time.sleep(0.1)
        self._lock_depth = 1
        try:
            self._cache.clear()  # перечитать актуальное под блокировкой
            self.config = json.loads((self.root / CASE_FILE).read_text(encoding="utf-8"))
            yield
        finally:
            self._lock_depth = 0
            with contextlib.suppress(FileNotFoundError):
                lock.unlink()

    @contextlib.contextmanager
    def transaction(self):
        """Всё или ничего: снимок реестров, журнала и case.json; при любой ошибке — откат. Держит блокировку."""
        with self.lock():
            files = [self.path(n) for n in REGISTERS] + [self.root / "journal.jsonl", self.root / CASE_FILE]
            snapshot = {f: (f.read_bytes() if f.exists() else None) for f in files}
            try:
                yield
            except BaseException:
                for f, data in snapshot.items():
                    if data is None:
                        f.unlink(missing_ok=True)
                    else:  # через временный файл: сбой посреди отката не оставит реестр полузаписанным
                        tmp = f.with_name(f.name + ".rollback.tmp")
                        tmp.write_bytes(data)
                        os.replace(tmp, f)
                self._cache.clear()
                self.config = json.loads((self.root / CASE_FILE).read_text(encoding="utf-8"))
                raise

    def save_config(self, actor: str, op: str, data: dict) -> None:
        """Атомарная запись case.json; вызывать под lock() после изменения self.config."""
        path = self.root / CASE_FILE
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        self.journal(actor, op, CASE_FILE, data)

    def _write(self, register: str, rows: list[dict]) -> None:
        p = self.path(register)
        tmp = p.with_suffix(".csv.tmp")
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, field_names(register), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, p)
        self._cache[register] = rows

    def journal(self, actor: str, op: str, identifier: str, data: dict) -> None:
        entry = {"ts": now_iso(), "actor": actor, "op": op, "id": identifier, "data": data}
        with open(self.root / "journal.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def next_id(self, register: str) -> str:
        reg = REGISTERS[register]
        nums = [int(r[reg["id"]][len(reg["prefix"]):]) for r in self.rows(register)
                if r[reg["id"]].startswith(reg["prefix"]) and r[reg["id"]][len(reg["prefix"]):].isdigit()]
        return f"{reg['prefix']}{(max(nums) + 1 if nums else 1):04d}"

    def _clean(self, register: str, values: dict) -> dict:
        unknown = set(values) - set(field_names(register))
        if unknown:
            raise KinError(f"{REGISTERS[register]['file']}: неизвестные поля {sorted(unknown)}. "
                           f"Допустимо: {', '.join(field_names(register))}")
        return {k: ("" if v is None else str(v).strip()) for k, v in values.items()}

    def add(self, register: str, values: dict, actor: str = "user") -> dict:
        values = self._clean(register, values)
        reg = REGISTERS[register]
        with self.lock():
            rows = list(self.rows(register))
            rid = values.get(reg["id"]) or self.next_id(register)
            if rid in self.index(register):
                raise KinError(f"{rid} уже существует")
            row = {k: values.get(k, "") for k in field_names(register)}
            row[reg["id"]] = rid
            errors = self.validate(register, row, new_ids={register: {rid}})
            if errors:
                raise KinError("Запись не сохранена:\n- " + "\n- ".join(errors))
            rows.append(row)
            self._write(register, rows)
            self.journal(actor, "add", rid, {k: v for k, v in row.items() if v and k != reg["id"]})
        return row

    def update(self, identifier: str, changes: dict, actor: str = "user", append: dict | None = None,
               op: str = "update") -> dict:
        """Изменить поля; append — добавить ID в списки (читается и пишется под одной блокировкой)."""
        register = register_by_prefix(identifier)
        changes = self._clean(register, changes)
        append = self._clean(register, append or {})
        list_fields = {f["name"] for f in REGISTERS[register]["fields"] if f.get("type") in ("refs", "list")}
        if set(append) - list_fields:
            raise KinError(f"--append только для списков: {', '.join(sorted(list_fields))}")
        id_field = REGISTERS[register]["id"]
        if id_field in changes:
            raise KinError("ID не меняется. Для исправления отождествления — merge/split.")
        if register == "artifacts" and ({"sha256", "file"} & set(changes)):
            raise KinError("Файл и контрольная сумма источника неизменяемы: добавьте новый источник.")
        with self.lock():
            rows = [dict(r) for r in self.rows(register)]
            for row in rows:
                if row[id_field] == identifier:
                    for k, v in append.items():
                        changes[k] = join_ids(split_ids(row.get(k, "")) + split_ids(v))
                    if not changes:
                        raise KinError("Нечего менять: укажите поле=значение")
                    before = {k: row[k] for k in changes}
                    row.update(changes)
                    errors = self.validate(register, row)
                    if errors:
                        raise KinError("Изменение не сохранено:\n- " + "\n- ".join(errors))
                    self._write(register, rows)
                    self.journal(actor, op, identifier, {"before": before, "after": changes})
                    return row
        raise KinError(f"{identifier} не найден")


def init_case(root: Path, title: str, language: str = "ru", git: bool = True) -> Path:
    root = Path(root).expanduser().resolve()
    if (root / CASE_FILE).exists():
        raise KinError(f"{root}: дело уже создано")
    if root.exists() and any(root.iterdir()):
        raise KinError(f"{root}: папка не пуста — дело создаётся в новой или пустой папке (чужие файлы не попадут в историю дела)")
    kit_root = HERE.parent.parent.parent  # корень репозитория набора (если запущено из него)
    with contextlib.suppress(ValueError):
        root.relative_to(HERE.parent)
        raise KinError("Нельзя создавать дело внутри папки навыка: код и данные хранятся раздельно.")
    if (kit_root / ".git").exists() and (kit_root / "skills" / "kinship-kit").exists():
        with contextlib.suppress(ValueError):
            root.relative_to(kit_root)
            raise KinError(f"Нельзя создавать дело внутри публичного репозитория набора ({kit_root}).")
    for sub in (REGISTRY_DIR, "sources", "publish", ".kin", "tasks", "requests"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    for name in REGISTERS:
        p = root / REGISTRY_DIR / REGISTERS[name]["file"]
        with open(p, "w", encoding="utf-8", newline="") as fh:
            csv.writer(fh, lineterminator="\n").writerow(field_names(name))
    config = {
        "kin_case": True,
        "case_id": __import__("uuid").uuid4().hex,
        "schema_version": SCHEMA_VERSION,
        "title": title,
        "language": language,
        "created": now_iso(),
        "root_person": "",
        "lines": [],
        "privacy": {
            "living_cutoff_years": 100,
            "note": "Публичный профиль скрывает живых и лиц с неизвестным статусом моложе cutoff лет, если нет publication=allow"
        },
        "limits": {"max_attempts_per_task": 3, "paid_requires_consent": True, "external_services_require_consent": True},
    }
    (root / CASE_FILE).write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / ".gitignore").write_text(
        "# производное — пересобирается командами kin\n.kin/\npublish/\nsite/\n*.tmp\n", encoding="utf-8")
    (root / "journal.jsonl").touch()
    (root / "sources" / "README.md").write_text(
        "Неизменяемые оригиналы. Добавлять только через `kin source add` (копия + sha256).\n", encoding="utf-8")
    if git:
        import subprocess
        with contextlib.suppress(OSError, subprocess.CalledProcessError):
            subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root
