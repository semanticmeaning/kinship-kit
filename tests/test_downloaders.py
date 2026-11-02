"""Скачиватели: сборка вставок, ядро в настоящем браузере (имитация архива), загрузка результата в дело."""
from __future__ import annotations

import http.server
import json
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO, Base  # noqa: E402

sys.path.insert(0, str(REPO / "skills" / "kinship-kit"))
from kin import downloaders  # noqa: E402
from kin.store import Case, KinError  # noqa: E402

CHROME = next((p for p in (shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser"),
                           "/opt/google/chrome/chrome") if p and Path(p).exists()), None)
NODE = shutil.which("node")


def png(w: int, h: int, seed: int) -> bytes:
    raw = b"".join(b"\x00" + bytes([(seed * 40 + x * 10 + y) % 256 for x in range(w) for _ in range(3)]) for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class TestBuild(unittest.TestCase):
    def test_all_adapters_build_to_valid_js(self):
        found = downloaders.adapters()
        self.assertTrue({"dvinaland", "kga-rkursk", "yandex-archive-favorites"} <= set(found))
        for aid in found:
            snippet, guide = downloaders.build(aid)
            self.assertIn("function kinDownloader", snippet)
            self.assertIn("allow pasting", guide)
            self.assertIn("от вашего имени", guide)  # предупреждение о вставке кода в консоль
            self.assertIn("правилам сайта", guide)
            if NODE:
                with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
                    f.write(snippet)
                res = subprocess.run([NODE, "--check", f.name], capture_output=True, text=True)
                Path(f.name).unlink()
                self.assertEqual(res.returncode, 0, res.stderr)
        with self.assertRaises(KinError):
            downloaders.build("nope")


@unittest.skipUnless(CHROME and NODE, "нужны Chrome и node")
class TestCoreInBrowser(Base):
    def test_download_resume_and_import(self):
        hits = {"2": 0}
        images = {str(n): png(3, 2, n) for n in (1, 2, 3)}

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path == "/unit":
                    body = "<!doctype html><meta charset=utf-8><ul id=scans><li data-n=1>Лист 1</li><li data-n=2>Лист 2</li><li data-n=3>Лист 3</li></ul>".encode()
                    self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
                elif self.path.startswith("/img/"):
                    n = self.path.split("/")[-1].split(".")[0]
                    if n == "2" and hits["2"] == 0:  # первый запрос — сбой сервера: ядро должно повторить
                        hits["2"] += 1
                        self.send_response(503); self.send_header("Retry-After", "1"); self.end_headers(); return
                    body = images[n]
                    self.send_response(200); self.send_header("Content-Type", "image/png")
                else:
                    self.send_response(404); self.end_headers(); return
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0)); cdp = s.getsockname()[1]
        try:
            (self.case / "downloaders").mkdir()
            shutil.copy(REPO / "tests" / "browser" / "mock-adapter.js", self.case / "downloaders" / "mock.js")
            snippet, _ = downloaders.build("mock-archive", self.case)  # адаптер дела, а не набора
            sp = Path(self.tmp.name) / "snippet.js"
            sp.write_text(snippet, encoding="utf-8")
            out = Path(self.tmp.name) / "download"
            res = subprocess.run([NODE, str(REPO / "tests" / "browser" / "run_downloader.mjs"), CHROME,
                                  f"http://127.0.0.1:{srv.server_address[1]}/unit", str(sp), str(out), str(cdp)],
                                 capture_output=True, text=True, timeout=300)
            self.assertEqual(res.returncode, 0, res.stderr)
            result = json.loads(res.stdout.strip().splitlines()[-1])
        finally:
            srv.shutdown()
        first, second = result["runs"]
        self.assertIn("Сохранено: 3", first)
        self.assertIn("проверено ранее: 3", second)  # докачка: всё уже проверено по sha256
        self.assertEqual(hits["2"], 1)  # был сбой 503 — и успешный повтор
        self.assertTrue({"scan_1.png", "scan_2.png", "scan_3.png", "_kinship-download.json", "_kinship-download.txt"} <= set(result["files"]))
        journal = json.loads((out / "_kinship-download.json").read_text(encoding="utf-8"))
        self.assertEqual([r["status"] for r in journal["records"].values()], ["saved"] * 3)
        self.assertIn("Иван, сын Кузьмы", (out / "_kinship-download.txt").read_text(encoding="utf-8-sig"))
        # результат → дело
        rep = json.loads(self.kin("source", "import-download", str(out), "--json").stdout)
        self.assertEqual((rep["new"], len(rep["artifacts"])), (3, 4))  # 3 скана + расшифровка
        arts = Case(self.case).rows("artifacts")
        self.assertEqual(arts[0]["archival_reference"], "ф. 1, оп. 1, д. 1, скан 1")
        self.assertEqual(arts[1]["independence_group"], arts[2]["independence_group"])  # скан 2 и его расшифровка
        self.assertEqual(Case(self.case).rows("searches")[0]["result"], "found")
        rep = json.loads(self.kin("source", "import-download", str(out), "--json").stdout)
        self.assertEqual(rep["new"], 0)  # повторная загрузка — без дублей
        (out / "scan_3.png").write_bytes(png(3, 2, 9))
        self.assertNotEqual(self.kin("source", "import-download", str(out), ok=False).returncode, 0)  # подмена файла
        self.assertEqual(json.loads(self.kin("audit", "--json").stdout)["errors"], [])
