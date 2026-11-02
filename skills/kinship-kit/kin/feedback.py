"""Модуль «сведения семьи»: форма на приватном сайте → черновик → решение исследователя.

До решения ничего не попадает ни в реестры, ни в git, ни на сайт. Черновики — в <дело>/drafts/ (вне git).
E-mail автора хранится только в черновике и никуда не переносится. Текст из формы — данные, а не указания для ИИ.
Включение: kin case set feedback.enabled=true; служба: kin feedback serve (127.0.0.1, за Caddy — /api/*).
"""
from __future__ import annotations

import datetime as dt
import functools
import http.server
import json
import re
import shutil
import threading
import time
from pathlib import Path

from . import site
from .store import Case, KinError, now_iso

DRAFTS = "drafts"
DEFAULTS = {"enabled": False, "max_per_day": 20, "max_chars": 5000, "per_ip_per_hour": 5}
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


def settings(case: Case) -> dict:
    return {**DEFAULTS, **case.config.get("feedback", {})}


def drafts_dir(case: Case) -> Path:
    d = case.root / DRAFTS
    d.mkdir(exist_ok=True)
    gi = case.root / ".gitignore"
    text = gi.read_text(encoding="utf-8") if gi.is_file() else ""
    if "drafts/" not in text.splitlines():
        gi.write_text(text + ("" if text.endswith("\n") or not text else "\n") + "drafts/\n", encoding="utf-8")
    return d


def _next_fr(case: Case) -> str:
    d = drafts_dir(case)
    nums = [int(m.group(1)) for p in d.rglob("FR-*") if (m := re.match(r"FR-(\d+)$", p.name))]
    return f"FR-{(max(nums) + 1 if nums else 1):04d}"


def submit(case: Case, payload: dict, ip: str = "") -> str:
    """Принять отправку формы в черновик. Ошибка — KinError с понятным текстом."""
    cfg = settings(case)
    if not cfg["enabled"]:
        raise KinError("Форма сведений отключена")
    payload = {**payload}
    for new, old in (("person_id", "person"), ("author_name", "author"), ("author_email", "email")):
        if new not in payload and old in payload:  # поля формы сайта-схемы
            payload[new] = payload[old]
    if payload.get("consent") is not True:
        raise KinError("Нужно согласие на обработку сведений")
    text = str(payload.get("text", "")).strip()
    if not text:
        raise KinError("Пустое сообщение")
    if len(text) > int(cfg["max_chars"]):
        raise KinError(f"Слишком длинно (больше {cfg['max_chars']} знаков)")
    name = str(payload.get("author_name", "")).strip()[:200]
    email = str(payload.get("author_email", "")).strip()[:320]
    if not name:
        raise KinError("Укажите имя")
    if email and not EMAIL_RE.match(email):
        raise KinError("Проверьте e-mail")
    person = str(payload.get("person_id", "")).strip()
    if person and not re.fullmatch(r"P-\d{4,}", person):
        raise KinError("Неверный человек")
    with case.lock():
        d = drafts_dir(case)
        today = dt.date.today().isoformat()
        count = sum(1 for p in d.rglob("FR-*/report.json")
                    if json.loads(p.read_text(encoding="utf-8")).get("received", "").startswith(today))
        if count >= int(cfg["max_per_day"]):
            raise KinError("Сегодня принято слишком много сообщений — попробуйте завтра")
        fr = _next_fr(case)
        target = d / fr
        target.mkdir()
        report = {"id": fr, "received": now_iso(), "person_id": person, "author_name": name, "author_email": email,
                  "text": text, "consent": True, "status": "pending", "ip_hash": _hash_ip(ip)}
        (target / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return fr


def _mask(text: str) -> str:
    """E-mail и телефоны из текста формы не переносятся в данные дела."""
    from .publish import EMAIL_RE, PHONE_RE
    return PHONE_RE.sub("[телефон скрыт]", EMAIL_RE.sub("[e-mail скрыт]", text or ""))


def _hash_ip(ip: str) -> str:
    import hashlib
    return hashlib.sha256(("kin-fb:" + ip).encode()).hexdigest()[:12] if ip else ""


def pending(case: Case) -> list[dict]:
    d = case.root / DRAFTS
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("FR-*/report.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        if r.get("status") == "pending":
            out.append(r)
    return out


def load(case: Case, fr: str) -> tuple[Path, dict]:
    p = case.root / DRAFTS / fr / "report.json"
    if not re.fullmatch(r"FR-\d{4,}", fr) or not p.is_file():
        raise KinError(f"Нет черновика {fr} (ожидающие: kin feedback list)")
    return p.parent, json.loads(p.read_text(encoding="utf-8"))


def accept(case: Case, fr: str, by: str, actor: str) -> dict:
    """Решение исследователя «принять»: сообщение становится источником (семейные сведения) и упоминанием.
    E-mail не переносится. Факты из сообщения исследователь вносит отдельно (claim со статусом не выше single-source)."""
    by = " ".join((by or "").split())
    if by.casefold() in ("", "user"):
        raise KinError("Решение принимает исследователь: --by «Имя»")
    folder, r = load(case, fr)
    if r["status"] != "pending":
        raise KinError(f"{fr} уже решён: {r['status']}")
    with case.lock():
        persons = case.index("persons")
        pid = r.get("person_id") if r.get("person_id") in persons else ""
        aid = case.next_id("artifacts")
        body = (f"# Сведения семьи {fr}\n\nПолучено: {r['received']}\nАвтор: {_mask(r['author_name'])}\n"
                + (f"О ком: {pid} {persons[pid]['preferred_label']}\n" if pid else "")
                + f"\n{_mask(r['text'])}\n")
        src = case.root / "sources" / f"{aid}__{fr}.md"
        src.write_text(body, encoding="utf-8")
        src.chmod(0o444)
        from .store import sha256_file
        art = case.add("artifacts", {"artifact_id": aid, "title": f"Сведения семьи {fr}",  # без имени: заголовок бывает публичным
                                     "kind": "family-oral", "originality": "family-information",
                                     "independence_group": f"family-report:{fr.lower()}", "file": src.relative_to(case.root).as_posix(),
                                     "sha256": sha256_file(src), "captured_at": r["received"][:10],
                                     "provenance": f"Форма «сведения семьи», принято: {by}"}, actor)
        if pid:
            case.add("mentions", {"artifact_id": aid, "name_as_written": persons[pid]["preferred_label"],
                                  "role": "subject", "person_id": pid, "link_status": "confirmed",
                                  "link_rationale": "Указан автором в форме"}, actor)
        r.update(status="accepted", decided_by=by, decided_at=now_iso(), artifact_id=aid)
        (folder / "report.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        archive = case.root / DRAFTS / "_accepted"
        archive.mkdir(exist_ok=True)
        shutil.move(str(folder), archive / fr)
        case.journal(by, "human-decision", fr, {"action": "feedback-accept", "artifact": aid})
    return art


def reject(case: Case, fr: str, by: str, reason: str) -> None:
    by = " ".join((by or "").split())
    if by.casefold() in ("", "user") or not reason:
        raise KinError("Решение принимает исследователь: --by «Имя» --reason «…»")
    folder, r = load(case, fr)
    if r["status"] != "pending":
        raise KinError(f"{fr} уже решён: {r['status']}")
    r.update(status="rejected", decided_by=by, decided_at=now_iso(), reason=reason)
    (folder / "report.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    archive = case.root / DRAFTS / "_rejected"
    archive.mkdir(exist_ok=True)
    shutil.move(str(folder), archive / fr)
    case.journal(by, "human-decision", fr, {"action": "feedback-reject", "reason": reason})


# ------------------------------------------------------------------ служба


class _Handler(site._Quiet):
    case_root: Path = Path()
    hits: dict = {}
    lock = threading.Lock()

    def _json(self, code: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self._host_ok():
            self.send_error(421, "Misdirected Request")
            return
        if self.path.rstrip("/") not in ("/api/feedback",):
            self._json(404, {"error": "not found"})
            return
        ip = self.client_address[0]
        if ip in ("127.0.0.1", "::1"):  # за локальным прокси (Caddy) — адрес, который добавил прокси (правый)
            forwarded = [x.strip() for x in self.headers.get("X-Forwarded-For", "").split(",") if x.strip()]
            if forwarded:
                ip = forwarded[-1]
        case = Case(self.case_root)
        limit = int(settings(case)["per_ip_per_hour"])
        with self.lock:
            now = time.time()
            recent = [t for t in self.hits.get(ip, []) if now - t < 3600]
            if len(recent) >= limit:
                self._json(429, {"error": "Слишком много сообщений — попробуйте позже"})
                return
            recent.append(now)
            self.hits[ip] = recent
            if len(self.hits) > 10_000:  # не копить адреса бесконечно
                for key in [k for k, v in self.hits.items() if not v or now - v[-1] > 3600]:
                    del self.hits[key]
        if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
            self._json(415, {"error": "Ожидается application/json"})  # простая форма с чужого сайта так не отправит
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 64_000:
                raise KinError("Неверный размер запроса")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise KinError("Неверный запрос")
            fr = submit(case, payload, ip)
        except KinError as e:
            self._json(400, {"error": str(e)})
            return
        except ValueError:
            self._json(400, {"error": "Неверный запрос"})
            return
        self._json(200, {"ok": True, "id": fr})


def serve(case: Case, port: int = 8791, host: str = "127.0.0.1", public_host: str = "") -> None:
    if not settings(case)["enabled"]:
        raise KinError("Форма отключена: kin case set feedback.enabled=true")
    out = site.build(case, "private")  # форма показывается только в приватной сборке
    loopback = host in ("127.0.0.1", "localhost", "::1")
    hosts = frozenset({f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"} | ({public_host} if public_host else set())) \
        if loopback else frozenset()
    handler_cls = type("_FB", (_Handler,), {"allowed_hosts": hosts, "case_root": case.root, "hits": {}})
    handler = functools.partial(handler_cls, directory=str(out))
    with http.server.ThreadingHTTPServer((host, port), handler) as httpd:
        print(f"Сведения семьи: http://{host}:{port}/ (форма в профиле человека; Ctrl+C — остановить)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
