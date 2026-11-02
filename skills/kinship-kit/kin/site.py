"""Сайт-схема: статическая страница + tree.json, собранные ТОЛЬКО из публикационного набора.

kin site build [--profile private|public] → <дело>/site/<profile>/ (index.html, tree.json)
kin site serve → http://127.0.0.1:8080 (только локальный адрес)
"""
from __future__ import annotations

import functools
import http.server
import json
import shutil
from collections import deque
from pathlib import Path

from . import edtf, publish
from .store import Case, KinError

WEB = Path(__file__).resolve().parent / "web"
THEME_DIR = "theme"
CSS_STUB = """/* Личное оформление сайта этого дела. Подключается поверх общего шаблона kinship-kit.
   Пример: другие цвета (переменные — в начале skills/kinship-kit/kin/web/index.html).
:root { --accent: #2f6b8a; --bg: #f3f6f8; }
*/
"""


def theme_init(case: Case, full: bool) -> list[Path]:
    """Создать theme/custom.css (и с full — копию страницы theme/index.html) в папке дела."""
    theme = case.root / THEME_DIR
    theme.mkdir(exist_ok=True)
    made = []
    css = theme / "custom.css"
    if not css.exists():
        css.write_text(CSS_STUB, encoding="utf-8")
        made.append(css)
    if full:
        page = theme / "index.html"
        if page.exists():
            raise KinError(f"{page} уже есть — правьте его (kin site theme diff — отличия от общего шаблона)")
        shutil.copy(WEB / "index.html", page)
        made.append(page)
    return made


def theme_diff(case: Case) -> str:
    """Отличия страницы дела от общего шаблона — чтобы перенести удачные правки в набор."""
    import difflib
    page = case.root / THEME_DIR / "index.html"
    if not page.is_file():
        return "Своей страницы нет (только custom.css или общий шаблон)."
    a = (WEB / "index.html").read_text(encoding="utf-8").splitlines(keepends=True)
    b = page.read_text(encoding="utf-8").splitlines(keepends=True)
    return "".join(difflib.unified_diff(a, b, "kinship-kit/kin/web/index.html", f"{THEME_DIR}/index.html")) or "Отличий нет."
GEN_STEP = 27  # средний шаг поколения, лет — только для людей без связей с корнем


def generations(data: dict) -> dict[str, int | None]:
    """Колено относительно корня: родители −1, дети +1, супруги и братья/сёстры — то же колено.
    Не связанные с корнем — как у ближайшего по году рождения размещённого человека, иначе None («вне схемы»)."""
    ids = [p["id"] for p in data["persons"]]
    adj: dict[str, list[tuple[str, int]]] = {i: [] for i in ids}
    for r in data["relationships"]:
        if r["status"] in ("rejected", "superseded"):
            continue
        a, b = r["a"], r["b"]
        if r["type"] == "parent-of":
            adj[a].append((b, +1))
            adj[b].append((a, -1))
        elif r["type"] in ("spouse-of", "sibling-of"):
            adj[a].append((b, 0))
            adj[b].append((a, 0))
    # гипотезы родства (claim parentage/sibling с двумя людьми) тоже размещают человека по коленам;
    # соглашение: в parentage первый subject — родитель, второй — ребёнок
    for c in data["claims"]:
        if c["status"] != "hypothesis" or len(c["subjects"]) < 2 or c["type"] not in ("parentage", "sibling"):
            continue
        a, b = c["subjects"][:2]
        if a in adj and b in adj:
            d = 1 if c["type"] == "parentage" else 0
            adj[a].append((b, d))
            adj[b].append((a, -d))
    gen: dict[str, int | None] = {i: None for i in ids}
    roots = [data["meta"]["root"]] if data["meta"]["root"] else []
    offset = int(data["meta"].get("root_gen_offset") or 0)
    order = roots + sorted(ids, key=lambda i: (edtf.sort_year(_p(data, i)["birth"]) or 9999, i))
    for start in order:
        if gen[start] is not None:
            continue
        comp = {start: 0}
        q = deque([start])
        while q:
            cur = q.popleft()
            for nxt, d in adj[cur]:
                if nxt not in comp:
                    comp[nxt] = comp[cur] + d
                    q.append(nxt)
        if start in roots:
            shift = offset
        else:
            # колено несвязанной группы — как у ближайшего по году рождения уже размещённого человека
            y = edtf.sort_year(_p(data, start)["birth"])
            placed = [(abs(edtf.sort_year(_p(data, pid)["birth"]) - y), pid) for pid, g in gen.items()
                      if g is not None and y is not None and edtf.sort_year(_p(data, pid)["birth"]) is not None]
            if placed:
                shift = gen[min(placed)[1]]
            elif not roots and all(g is None for g in gen.values()):
                shift = 0  # корень не задан: первая (самая ранняя) группа — точка отсчёта
            else:
                continue  # опереться не на что — вся группа «вне схемы»
        for pid, g in comp.items():
            gen[pid] = g + shift
    return gen


def _p(data: dict, pid: str) -> dict:
    index = data.get("_by_id")
    if index is None:
        index = data["_by_id"] = {p["id"]: p for p in data["persons"]}
    if pid not in index:
        raise KinError(f"{pid} нет в публикационном наборе")
    return index[pid]


def build(case: Case, profile: str = "private") -> Path:
    out = case.root / "site" / profile
    if out.exists():  # удалить до сборки: при ошибке не должна остаться прежняя (возможно, устаревшая) версия
        shutil.rmtree(out)
    from . import tree_data  # локальный импорт: tree_data использует generations из этого модуля
    _, pub, hidden = publish.write(case, profile)
    data, manifest = tree_data.build(case, profile, pub)
    out.mkdir(parents=True)
    (out / "tree.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    for src, rel in manifest:  # файлы источников к фактам (в public — только scan_publication=allow)
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    theme = case.root / THEME_DIR
    page = theme / "index.html" if (theme / "index.html").is_file() else WEB / "index.html"
    html = page.read_text(encoding="utf-8")
    if (theme / "custom.css").is_file():  # личное оформление дела поверх общего шаблона
        shutil.copy(theme / "custom.css", out / "custom.css")
        html = html.replace("</head>", '<link rel="stylesheet" href="custom.css">\n</head>', 1)
    (out / "index.html").write_text(html, encoding="utf-8")
    for icons in (WEB / "icons", theme / "icons"):  # иконки страницы (пол на карточках); своя тема может их заменить
        if icons.is_dir():
            (out / "icons").mkdir(exist_ok=True)
            for f in icons.iterdir():
                if f.is_file() and f.suffix.lower() in (".png", ".webp", ".jpg", ".gif"):
                    shutil.copyfile(f, out / "icons" / f.name)
    if profile == "public":
        (out / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
    else:
        (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    # повторная проверка всей сборки (все маршруты = все файлы папки)
    terms = publish.forbidden_terms(case, {pid: "" for pid in hidden})
    files = sorted(p for p in out.rglob("*") if p.is_file())
    docs = [p for p in files if (out / "docs") in p.parents]
    # данные и страница — полная проверка; файлы документов выкладываются только по явному решению автора
    # (в public — scan_publication=allow), а в старых документах совпадения имён с живыми родственниками неизбежны:
    # в них проверяются только e-mail, телефоны и локальные пути
    problems = publish.check_leaks([p for p in files if p not in docs], terms) + publish.check_leaks(docs, [])
    if problems:
        shutil.rmtree(out)
        raise KinError("Сайт не собран — утечки в сборке:\n- " + "\n- ".join(problems))
    return out


class _Quiet(http.server.SimpleHTTPRequestHandler):
    allowed_hosts: frozenset = frozenset()

    def log_message(self, fmt, *args):  # без журнала запросов в консоли
        pass

    def _host_ok(self) -> bool:
        """Защита от DNS rebinding: чужой сайт не может читать localhost-сборку через свой домен."""
        return not self.allowed_hosts or (self.headers.get("Host") or "").lower() in self.allowed_hosts

    def do_GET(self):
        if not self._host_ok():
            self.send_error(421, "Misdirected Request")
            return
        super().do_GET()

    def do_HEAD(self):
        if not self._host_ok():
            self.send_error(421, "Misdirected Request")
            return
        super().do_HEAD()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Robots-Tag", "noindex")
        super().end_headers()


def serve(case: Case, profile: str = "private", port: int = 8080, host: str = "127.0.0.1") -> None:
    out = case.root / "site" / profile
    if not (out / "index.html").is_file():
        out = build(case, profile)
    loopback = host in ("127.0.0.1", "localhost", "::1")
    hosts = frozenset({f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}) if loopback else frozenset()
    handler_cls = type("_Handler", (_Quiet,), {"allowed_hosts": hosts})
    handler = functools.partial(handler_cls, directory=str(out))
    with http.server.ThreadingHTTPServer((host, port), handler) as httpd:
        print(f"Схема ({profile}): http://{host}:{port}/   (Ctrl+C — остановить)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
