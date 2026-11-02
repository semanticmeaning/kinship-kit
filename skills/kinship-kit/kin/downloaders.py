"""Скачиватели сканов из онлайн-архивов: сборка вставки для консоли браузера и загрузка результата в дело.

kin downloader list                       — какие сайты поддержаны
kin downloader build <адаптер> [--out f]  — одна вставка (ядро + адаптер) и инструкция для пользователя
kin source import-download <папка>        — сканы и расшифровки из папки выгрузки → источники дела (без дублей)

Ядро — downloaders/core.js, адаптеры — downloaders/adapters/*.js (заголовок «// @kin-adapter …»). Новый сайт:
пользователь присылает сохранённую страницу просмотрщика, агент пишет адаптер по образцу (references/downloaders.md).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path

from .store import Case, KinError, sha256_file

DL_DIR = Path(__file__).resolve().parent.parent / "downloaders"
JOURNAL = "_kinship-download.json"
SUMMARY = "_kinship-download.txt"


def adapters(extra_dir: Path | None = None) -> dict[str, dict]:
    """id → {id, title, site, version, start, path}. extra_dir — адаптеры дела (папка downloaders/ в деле)."""
    out = {}
    for d in [DL_DIR / "adapters"] + ([extra_dir] if extra_dir and extra_dir.is_dir() else []):
        for p in sorted(d.glob("*.js")):
            meta = {"path": p}
            for line in p.read_text(encoding="utf-8").splitlines():
                m = re.match(r"^//\s*@([\w-]+)\s+(.*)$", line)
                if not m:
                    if line.strip() and not line.startswith("//"):
                        break
                    continue
                key = {"kin-adapter": "id"}.get(m.group(1), m.group(1))
                meta[key] = m.group(2).strip()
            if meta.get("id"):
                out[meta["id"]] = meta
    return out


INSTRUCTIONS = """Как запустить ({title})
1. Откройте Chrome или Edge (в Firefox и Safari файлы уйдут в «Загрузки» по одному, без продолжения в ту же папку).
2. {start}
3. Нажмите F12 (или Ctrl+Shift+J; на Mac — Cmd+Option+J) → вкладка Console.
4. Если браузер предупредит о вставке кода — впишите  allow pasting  и нажмите Enter (вставляйте только скрипты из набора kinship-kit).
5. Вставьте скрипт целиком (Ctrl+V) и нажмите Enter. Слева вверху появится панель.
6. «Выбрать папку и начать» → выберите ПУСТУЮ папку (или папку прошлой выгрузки этого же сайта — тогда скрипт продолжит).
7. Ждите: панель показывает ход. Остановить можно в любой момент; повторный запуск в ту же папку докачает остальное.
   Если сайт попросит подтвердить «я не робот» или войти заново — сделайте это вручную и запустите снова.
Результат: в папке сканы + _kinship-download.json (журнал с реквизитами и контрольными суммами) + _kinship-download.txt (итог).
Пришлите папку агенту (архивом или на сервер) — он выполнит: kin source import-download <папка>
"""


def build(adapter_id: str, case_dir: Path | None = None) -> tuple[str, str]:
    """(текст вставки, инструкция)."""
    found = adapters(case_dir / "downloaders" if case_dir else None)
    if adapter_id not in found:
        raise KinError(f"Нет адаптера {adapter_id!r}. Есть: {', '.join(sorted(found)) or 'нет'}")
    meta = found[adapter_id]
    core = (DL_DIR / "core.js").read_text(encoding="utf-8")
    body = meta["path"].read_text(encoding="utf-8")
    snippet = (f"/* kinship-kit · скачиватель «{meta.get('title', adapter_id)}» · адаптер {adapter_id} v{meta.get('version', '?')}"
               f" · собран {dt.date.today().isoformat()}. Открытый код: https://github.com/semanticmeaning/kinship-kit */\n"
               "(() => {\n" + core + "\n" + body + "\n})();\n")
    guide = INSTRUCTIONS.format(title=meta.get("title", adapter_id), start=meta.get("start", "Откройте нужное дело на сайте архива."))
    return snippet, guide


# ------------------------------------------------------------------ загрузка результата в дело


def _group(rec: dict) -> str:
    """Группа независимости — физический лист: один и тот же лист с разных сайтов попадёт в одну группу."""
    ref = (rec.get("reference") or "").casefold().replace("ё", "е")
    ref = re.sub(r"скан\s*\d+", "", ref)
    norm = re.sub(r"[^\w]+", "-", ref).strip("-")
    sheet = re.sub(r"[^\w]+", "-", str(rec.get("sheet") or rec.get("fileName") or "")).strip("-")
    return f"scan:{norm}:{sheet}"[:160] if norm else f"scan:{rec.get('sha256', '')[:16]}"


def import_download(case: Case, folder: Path, actor: str = "user", task: str = "", dry_run: bool = False) -> dict:
    folder = Path(folder).expanduser().resolve()
    jp = folder / JOURNAL
    if not jp.is_file():
        raise KinError(f"В {folder} нет {JOURNAL} — это не папка выгрузки kinship-kit")
    try:
        j = json.loads(jp.read_text(encoding="utf-8"))
    except ValueError:
        raise KinError(f"{JOURNAL} повреждён") from None
    if j.get("format") != "kinship-kit-download" or j.get("version") != 1 or not isinstance(j.get("records"), dict):
        raise KinError(f"{JOURNAL}: неизвестный формат")
    adapter = j.get("adapter") or {}
    known = {a.get("sha256") for a in case.rows("artifacts") if a.get("sha256")}
    plan, problems = [], []
    for key in j.get("order") or list(j["records"]):
        rec = j["records"].get(key) or {}
        if rec.get("status") != "saved":
            continue
        name = rec.get("fileName", "")
        f = (folder / name).resolve()
        if not re.fullmatch(r"[^/\\]+", name) or folder not in f.parents or not f.is_file():
            problems.append(f"{name or key}: файла нет в папке")
            continue
        if sha256_file(f) != rec.get("sha256"):
            problems.append(f"{name}: содержимое не совпадает с журналом (файл изменён или повреждён)")
            continue
        if rec["sha256"] in known:
            continue
        known.add(rec["sha256"])
        plan.append((key, rec, f))
    report = {"adapter": adapter.get("id", ""), "new": len(plan), "problems": problems,
              "skipped_known": sum(1 for r in j["records"].values() if r.get("status") == "saved") - len(plan) - len(problems),
              "errors_on_site": sum(1 for r in j["records"].values() if r.get("status") == "error"), "artifacts": []}
    if problems:
        raise KinError("Выгрузка не загружена — проверьте файлы:\n- " + "\n- ".join(problems[:20]))
    if dry_run or not plan:
        return report
    created: list[Path] = []
    try:
        with case.transaction():
            if task:
                case.get(task)
            for _key, rec, f in plan:
                aid = case.next_id("artifacts")
                safe = re.sub(r"[^\w.-]+", "_", f.name)[:120]
                dest = case.root / "sources" / f"{aid}__{safe}"
                shutil.copy2(f, dest)
                created.append(dest)
                dest.chmod(0o444)
                quality = rec.get("quality", "original")
                prov = (f"Выгрузка скриптом kinship-kit «{adapter.get('title', '')}» (адаптер {adapter.get('id', '')} "
                        f"v{adapter.get('version', '')}) с {j.get('site', '')}, {rec.get('saved', '')[:10]}"
                        + ("; УМЕНЬШЕННАЯ КОПИЯ: " + rec.get("reason", "") if quality == "preview" else ""))
                group = _group(rec)
                case.add("artifacts", {"artifact_id": aid, "title": (rec.get("title") or f.stem)[:300], "kind": "document-image",
                                       "file": dest.relative_to(case.root).as_posix(), "sha256": rec["sha256"],
                                       "url": rec.get("page", "") if str(rec.get("page", "")).startswith("http") else "",
                                       "repository": rec.get("archive", ""), "archival_reference": rec.get("reference", ""),
                                       "originality": "image-of-original", "independence_group": group, "provenance": prov,
                                       "captured_at": rec.get("saved", "")[:10] if re.match(r"\d{4}-\d{2}-\d{2}", rec.get("saved", "")) else "",
                                       "summary": f"{rec.get('width', '?')}×{rec.get('height', '?')} px"}, actor)
                report["artifacts"].append(aid)
                if rec.get("text"):  # расшифровка сайта — отдельный источник той же группы (не независима от скана)
                    tid = case.next_id("artifacts")
                    stem = re.sub(r"[^\w.-]+", "_", f.stem)[:110]
                    tdest = case.root / "sources" / f"{tid}__{stem}_text.txt"
                    tdest.write_text(rec["text"], encoding="utf-8")
                    created.append(tdest)
                    tdest.chmod(0o444)
                    case.add("artifacts", {"artifact_id": tid, "title": ("Расшифровка сайта: " + (rec.get("title") or f.stem))[:300],
                                           "kind": "transcript", "file": tdest.relative_to(case.root).as_posix(),
                                           "sha256": sha256_file(tdest), "url": rec.get("page", "") if str(rec.get("page", "")).startswith("http") else "",
                                           "repository": rec.get("archive", ""), "archival_reference": rec.get("reference", ""),
                                           "originality": "transcript", "independence_group": group,
                                           "provenance": prov + "; текст расшифровки с сайта, без исправлений"}, actor)
                    report["artifacts"].append(tid)
            case.add("searches", {"date": dt.date.today().isoformat(), "task_id": task,
                                  "source": f"{adapter.get('title', '')} ({j.get('site', '')})",
                                  "query": f"Выгрузка сканов скриптом kinship-kit ({len(plan)} файлов)", "result": "found",
                                  "artifact_ids": ";".join(report["artifacts"]),
                                  "allowed_conclusions": "Сканы сохранены с реквизитами; содержание ещё нужно прочитать и разобрать",
                                  "next_step": "Разобрать сканы: упоминания, утверждения (шаблон metric-books)"}, actor)
            if task:
                s_id = case.rows("searches")[-1]["search_id"]
                case.update(task, {}, actor, append={"search_ids": s_id, "evidence_artifact_ids": ";".join(report["artifacts"])})
    except BaseException:
        for p in created:
            p.chmod(0o644)
            p.unlink(missing_ok=True)
        raise
    return report
