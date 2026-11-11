# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy"]
# ///
"""Measure the GPU renderer's edge quality (msaa 1 and msaa 4) against the software renderer, frame-exact.

Usage (from the project root):
    uv run tests/aa_compare.py OUTDIR [--screens title,debate,...] [--zoom N]

`xtatrium shot` renders tests/full_run.atrec's frame at each screen's tick three times, with no window and no wall
clock: OUTDIR/sw (software renderer, the reference), OUTDIR/m1 (wgpu --msaa 1) and OUTDIR/m4 (wgpu --msaa 4). For
each tick it prints, per GPU mode against sw: the number of pixels whose largest channel difference exceeds 16, and
the largest channel difference. The same numbers go to OUTDIR/report.json. OUTDIR/zoom_<screen>.png shows the N
64 px cells where msaa 1 or msaa 4 differs most from sw, as sw | m1 | m4 at an integer nearest-neighbour scale,
each labelled with its source pixel range. OUTDIR/lib-log.txt keeps the wgpu run's library log (adapter,
wgpu-native version, memory policy) for reports.
Not a pass/fail check: a report aid for the XTFrame mainline. The numbers decide; the zooms only illustrate.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from xt_cli import EXE, XTFRAME  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCREENS = {"title": 0, "paper": 60, "vn": 200, "investigate": 380, "board": 480, "debate": 800, "result": 1300}
MODES = {"sw": ["--renderer", "sw"], "m1": ["--renderer", "wgpu", "--msaa", "1"],
         "m4": ["--renderer", "wgpu", "--msaa", "4"]}
THRESHOLD = 16
CELL, SCALE = 64, 3


def shoot(out: Path, ticks: list[int]) -> None:
    env = dict(os.environ, XTATRIUM_XTFRAME_DIR=str(XTFRAME))
    at = ",".join(str(t) for t in ticks)
    for mode, flags in MODES.items():
        cmd = [str(EXE), "shot", "--game", ".", "--replay", "tests/full_run.atrec", "--at", at,
               "--out", str(out / mode), *flags]
        p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
        if p.returncode != 0:
            raise SystemExit(f"FAIL xtatrium shot {mode} (exit {p.returncode})\n{p.stderr}")


def load(out: Path, mode: str, tick: int) -> np.ndarray:
    return np.asarray(Image.open(out / mode / f"shot-{tick:06d}.png").convert("RGB"), dtype=np.int16)


def metrics(ref: np.ndarray, img: np.ndarray) -> tuple[np.ndarray, int, int]:
    d = np.abs(img - ref).max(axis=2)
    return d, int((d > THRESHOLD).sum()), int(d.max())


def zoom(out: Path, name: str, imgs: dict[str, np.ndarray], diffs: list[np.ndarray], n: int) -> None:
    over = sum((d > THRESHOLD).astype(np.int32) for d in diffs)
    h, w = over.shape
    cells = sorted(((int(over[y:y + CELL, x:x + CELL].sum()), x, y)
                    for y in range(0, h - CELL + 1, CELL) for x in range(0, w - CELL + 1, CELL)),
                   key=lambda c: (-c[0], c[2], c[1]))
    cells = [c for c in cells if c[0] > 0][:n]
    if not cells:
        return
    side = CELL * SCALE
    sheet = Image.new("RGB", (3 * side + 20, len(cells) * (side + 18)), "white")
    dr = ImageDraw.Draw(sheet)
    for i, (_, x, y) in enumerate(cells):
        oy = i * (side + 18)
        dr.text((2, oy + 2), f"{name} src x{x}..{x + CELL - 1} y{y}..{y + CELL - 1}  sw | m1 | m4  x{SCALE}",
                fill="black")
        for j, mode in enumerate(MODES):
            crop = Image.fromarray(imgs[mode][y:y + CELL, x:x + CELL].astype(np.uint8))
            sheet.paste(crop.resize((side, side), Image.NEAREST), (j * (side + 10), oy + 16))
    sheet.save(out / f"zoom_{name}.png")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--screens", default=",".join(SCREENS))
    ap.add_argument("--zoom", type=int, default=4, help="cells per zoom sheet (0 = none)")
    args = ap.parse_args()
    screens = [s for s in args.screens.split(",") if s]
    bad = [s for s in screens if s not in SCREENS]
    if bad:
        raise SystemExit(f"unknown screens {bad}; known: {', '.join(SCREENS)}")
    args.out.mkdir(parents=True, exist_ok=True)
    shoot(args.out, sorted({SCREENS[s] for s in screens}))
    report = {}
    print(f"{'screen':12} {'tick':>5}  {'m1 >16':>8} {'m1 max':>6}  {'m4 >16':>8} {'m4 max':>6}")
    for name in screens:
        tick = SCREENS[name]
        imgs = {m: load(args.out, m, tick) for m in MODES}
        d1, n1, x1 = metrics(imgs["sw"], imgs["m1"])
        d4, n4, x4 = metrics(imgs["sw"], imgs["m4"])
        report[name] = {"tick": tick, "m1": {"over16": n1, "max": x1}, "m4": {"over16": n4, "max": x4}}
        print(f"{name:12} {tick:>5}  {n1:>8} {x1:>6}  {n4:>8} {x4:>6}")
        if args.zoom:
            zoom(args.out, name, imgs, [d1, d4], args.zoom)
    (args.out / "report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
