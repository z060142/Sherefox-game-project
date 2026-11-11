# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy"]
# ///
"""Compare the windowed renderer's edge quality at msaa 1 against msaa 4 (Windows only; opens real play windows).

Usage (from the project root):
    uv run tests/aa_compare.py OUTDIR [--screens title,debate,...]

For each screen it replays tests/full_run.atrec up to that screen's tick in `xtatrium play` (once with --msaa 1,
once with --msaa 4, same tick), lets it idle 5 s, and grabs the window's client area: OUTDIR/<screen>_m1.png and
_m4.png. It then writes OUTDIR/zoom_<screen>.png: the six 64 px cells where the two differ most in small amounts
(edge smoothing; large differences are animation and skipped), 3x nearest-neighbour, left msaa 1, right msaa 4.
Animated screens are not frame-identical between the two runs; judge edges, not content.
Not a pass/fail check: a report aid for the XTFrame mainline. Truncated recordings live in a temp dir that is deleted.
Keep the window unobstructed while it runs (~2 min).
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageGrab

sys.path.insert(0, str(Path(__file__).resolve().parent))
from xt_cli import EXE, XTFRAME  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCREENS = {"title": 0, "paper": 60, "vn": 200, "investigate": 380, "board": 480, "debate": 800, "result": 1300}
CELL, ZOOM, TOP = 64, 3, 6


def window_rect(pid: int) -> tuple[int, int, int, int] | None:
    from ctypes import wintypes as W
    u32 = ctypes.windll.user32
    found: list[int] = []

    def cb(h, _):
        p = W.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u32.IsWindowVisible(h):
            found.append(h)
        return True

    u32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, W.HWND, W.LPARAM)(cb), 0)
    if not found:
        return None
    h = found[0]
    r = W.RECT()
    u32.GetClientRect(h, ctypes.byref(r))
    pt = W.POINT(0, 0)
    u32.ClientToScreen(h, ctypes.byref(pt))
    u32.SetForegroundWindow(h)
    return pt.x, pt.y, pt.x + r.right, pt.y + r.bottom


def capture(out: Path, screens: list[str]) -> None:
    ctypes.windll.user32.SetProcessDPIAware()   # physical pixels, or the grab box is scaled on high-DPI displays
    lines = (ROOT / "tests" / "full_run.atrec").read_text(encoding="utf-8").splitlines()
    env = dict(os.environ, XTATRIUM_XTFRAME_DIR=str(XTFRAME))
    with tempfile.TemporaryDirectory(prefix="sherefox-aa-") as tmp:
        for name in screens:
            tick = SCREENS[name]
            head = [ln for ln in lines if not ln.startswith('{"t"') or json.loads(ln)["t"] <= tick]
            rec = Path(tmp) / f"{name}.atrec"
            rec.write_text("\n".join(head) + "\n", encoding="utf-8")
            for msaa in (1, 4):
                p = subprocess.Popen([str(EXE), "play", "--game", ".", "--replay", str(rec), "--msaa", str(msaa)],
                                     cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    time.sleep(tick / 60 + 5)
                    box = window_rect(p.pid)
                    if box is None:
                        raise SystemExit(f"FAIL {name} msaa {msaa}: no play window")
                    time.sleep(0.5)
                    ImageGrab.grab(box, all_screens=True).save(out / f"{name}_m{msaa}.png")
                    print(f"captured {name} msaa {msaa} ({box[2] - box[0]}x{box[3] - box[1]})", flush=True)
                finally:
                    p.kill()
                    p.wait()


def zoom(out: Path, name: str) -> None:
    a = Image.open(out / f"{name}_m1.png").convert("RGB")
    b = Image.open(out / f"{name}_m4.png").convert("RGB")
    d = np.abs(np.asarray(a, dtype=int) - np.asarray(b, dtype=int)).sum(2)
    edge = (d > 20) & (d < 300)
    h, w = d.shape
    cells = []
    for y in range(0, h - CELL + 1, CELL):
        for x in range(0, w - CELL + 1, CELL):
            if (d[y:y + CELL, x:x + CELL] >= 300).mean() > 0.05:
                continue
            cells.append((int(edge[y:y + CELL, x:x + CELL].sum()), x, y))
    cells.sort(key=lambda c: (-c[0], c[2], c[1]))
    top = cells[:TOP]
    side = CELL * ZOOM
    img = Image.new("RGB", (2 * side + 10, len(top) * (side + 20)), "white")
    dr = ImageDraw.Draw(img)
    for i, (n, x, y) in enumerate(top):
        oy = i * (side + 20)
        dr.text((2, oy + 2), f"{name} x{x} y{y} n{n}  left=msaa1 right=msaa4", fill="black")
        img.paste(a.crop((x, y, x + CELL, y + CELL)).resize((side, side), Image.NEAREST), (0, oy + 16))
        img.paste(b.crop((x, y, x + CELL, y + CELL)).resize((side, side), Image.NEAREST), (side + 10, oy + 16))
    img.save(out / f"zoom_{name}.png")
    print(f"zoom_{name}.png: " + ", ".join(f"x{x} y{y} n{n}" for n, x, y in top))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--screens", default=",".join(SCREENS))
    args = ap.parse_args()
    screens = [s for s in args.screens.split(",") if s]
    bad = [s for s in screens if s not in SCREENS]
    if bad:
        raise SystemExit(f"unknown screens {bad}; known: {', '.join(SCREENS)}")
    args.out.mkdir(parents=True, exist_ok=True)
    capture(args.out, screens)
    for s in screens:
        zoom(args.out, s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
