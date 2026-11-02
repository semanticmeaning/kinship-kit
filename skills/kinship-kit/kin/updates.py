"""Версии и обновления набора: kin upgrade check | apply.

Проверка — по меткам vX.Y.Z репозитория на GitHub (KIN_UPSTREAM, по умолчанию semanticmeaning/kinship-kit) и разделам
CHANGELOG.md новее установленной версии. Обновление — git pull --ff-only в клоне набора; данные дел не затрагиваются,
схема дел обновляется отдельно: kin migrate. Результат последней проверки кэшируется (kin status показывает его без сети).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__
from .store import KinError

UPSTREAM = os.environ.get("KIN_UPSTREAM", "semanticmeaning/kinship-kit")
KIT_ROOT = Path(__file__).resolve().parent.parent.parent  # клон набора (если навык поставлен ссылкой или запущен из клона)
CACHE = Path(os.environ.get("KIN_CACHE", Path.home() / ".cache" / "kinship-kit")) / "update.json"
TIMEOUT = 8


def parse_version(text: str) -> tuple[int, int, int] | None:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (text or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"kinship-kit/{__version__}",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 — только https-адреса GitHub ниже
        return r.read()


def fetch_latest(upstream: str = UPSTREAM) -> str:
    """Самая новая метка vX.Y.Z на GitHub."""
    data = json.loads(_get(f"https://api.github.com/repos/{upstream}/tags?per_page=100"))
    versions = [t["name"] for t in data if isinstance(t, dict) and parse_version(t.get("name", ""))]
    if not versions:
        raise KinError(f"В {upstream} нет меток версий vX.Y.Z")
    return max(versions, key=parse_version)


def fetch_changes(tag: str, since: str, upstream: str = UPSTREAM) -> str:
    """Разделы CHANGELOG.md с версиями новее since (по состоянию метки tag)."""
    try:
        text = _get(f"https://raw.githubusercontent.com/{upstream}/{tag}/CHANGELOG.md").decode("utf-8", "replace")
    except (urllib.error.URLError, OSError):
        return ""
    return changes_since(text, since)


def changes_since(changelog: str, since: str) -> str:
    cur = parse_version(since) or (0, 0, 0)
    out, keep = [], False
    for line in changelog.splitlines():
        m = re.match(r"^##\s+\[?v?(\d+\.\d+\.\d+)", line)
        if m:
            keep = parse_version(m.group(1)) > cur
        if keep:
            out.append(line)
    return "\n".join(out).strip()


def _save_cache(data: dict) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # кэш — удобство, без него всё работает


def cached() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def check(upstream: str = UPSTREAM) -> dict:
    """{'current', 'latest', 'newer', 'changes', 'checked'}; без сети — KinError с понятным текстом."""
    try:
        latest = fetch_latest(upstream)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise KinError(f"Не удалось проверить обновления ({upstream}): {e}. Без сети работа продолжается на версии {__version__}.") from None
    newer = parse_version(latest) > (parse_version(__version__) or (0, 0, 0))
    result = {"current": __version__, "latest": latest.lstrip("v"), "newer": newer,
              "changes": fetch_changes(latest, __version__, upstream) if newer else "",
              "checked": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "upstream": upstream}
    _save_cache({k: v for k, v in result.items() if k != "changes"})
    return result


def notice() -> str:
    """Строка для kin status по последней проверке (без сети)."""
    c = cached()
    latest = parse_version(c.get("latest", ""))
    if latest and latest > (parse_version(__version__) or (0, 0, 0)):
        return f"Доступна новая версия kinship-kit {c['latest']} (установлена {__version__}): kin upgrade check"
    return ""


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(KIT_ROOT), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")


def apply() -> str:
    """Обновить клон набора: git pull --ff-only. Локальные правки и расхождения — отказ без изменений."""
    if not (KIT_ROOT / ".git").exists() or not (KIT_ROOT / "skills" / "kinship-kit").is_dir():
        raise KinError("Навык установлен копией, а не из клона. Обновление: git clone https://github.com/"
                       f"{UPSTREAM}.git (или git pull в своём клоне) → sh install.sh")
    if _git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        raise KinError(f"В {KIT_ROOT} есть незакоммиченные правки набора — закоммитьте или отложите их (git stash), затем повторите.")
    before = _git("rev-parse", "HEAD").stdout.strip()
    res = _git("pull", "--ff-only", "--tags")
    if res.returncode != 0:
        raise KinError("git pull не выполнен (ветки разошлись или нет сети):\n" + (res.stderr or res.stdout).strip()
                       + "\nВаши коммиты в наборе — через git rebase или Pull Request в общий репозиторий.")
    after = _git("rev-parse", "HEAD").stdout.strip()
    if before == after:
        return "Набор уже на последней версии."
    return (f"Набор обновлён ({before[:7]} → {after[:7]}). Данные дел не затронуты.\n"
            "Дальше в каждом деле: kin migrate --dry-run (если схема изменилась — kin migrate, резервная копия создаётся сама).\n"
            "Если навык ставился копией, а не ссылкой (--link), повторите: sh install.sh")
