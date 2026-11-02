"""CI: упавшие тесты unittest → аннотации GitHub (видны в PR и через публичный API без входа).

python tools/ci_annotate.py unittest.log
"""
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
blocks = re.split(r"^={50,}\n", text, flags=re.M)[1:]
items = []
for b in blocks:
    head, _, body = b.partition("\n")
    m = re.match(r"(FAIL|ERROR): (\S+) \(([\w.]+)\)", head)
    if not m:
        continue
    parts = re.split(r"^-{50,}$", body, flags=re.M)  # [пусто, трассировка, итог…]
    trace = parts[1] if len(parts) > 1 else body
    tail = [ln for ln in trace.strip().splitlines() if ln.strip()][-6:]
    name = m.group(3) if m.group(3).endswith("." + m.group(2)) else f"{m.group(3)}.{m.group(2)}"
    items.append((f"{m.group(1)} {name}", "\n".join(tail)))


def esc(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


for title, msg in items[:9]:
    print(f"::error title={esc(title)}::{esc(msg[:3000])}")
if len(items) > 9:
    print("::error title=ещё упавшие тесты::" + esc("\n".join(t for t, _ in items[9:])[:3000]))
summary = [ln for ln in text.splitlines() if ln.startswith(("Ran ", "OK", "FAILED"))]
print("::error title=итог::" + esc("\n".join(summary) or "нет итога unittest"))
