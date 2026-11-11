# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy"]
# ///
"""Measure the GPU renderer's edge quality (msaa 1 and msaa 4) against the software renderer, frame-exact.

Usage (from the project root):
    uv run tests/aa_compare.py OUTDIR [--screens title,debate,...] [--zoom N]

`xtatrium shot` renders tests/full_run.atrec's frame at each screen's tick (some screens on a copy cut short, see
SCREENS) three times, with no window and no wall
clock: OUTDIR/sw/<screen>.png (software renderer, the reference), OUTDIR/m1 (wgpu --msaa 1) and OUTDIR/m4 (wgpu --msaa 4). For
each tick it prints, per GPU mode against sw: the number of pixels whose largest channel difference exceeds 16, and
the largest channel difference and the mean absolute error (all channels, 0..255). The same numbers go to OUTDIR/report.json. OUTDIR/zoom_<screen>.png shows the N
64 px cells where msaa 1 or msaa 4 differs most from sw, as sw | m1 | m4 at an integer nearest-neighbour scale,
each labelled with its source pixel range. OUTDIR/lib-log.txt keeps the wgpu run's library log (adapter,
wgpu-native version, memory policy) for reports.
Not a pass/fail check: a report aid for the XTFrame mainline. The numbers decide; the zooms only illustrate.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from xt_cli import EXE, XTFRAME  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# screen -> (tick, cut): cut = drop the recording's inputs after that tick (None = whole recording), so a screen the
# recording leaves quickly can be shot after its intro settles (paper: intro 700 ms, shown from t41, left at t64).
SCREENS = {"title": (0, None), "paper": (60, None), "paper_settled": (120, 60), "vn": (200, None),
           "investigate": (380, None), "board": (480, None), "debate": (800, None), "result": (1300, None)}
MODES = {"sw": ["--renderer", "sw"], "m1": ["--renderer", "wgpu", "--msaa", "1"],
         "m4": ["--renderer", "wgpu", "--msaa", "4"]}
THRESHOLD = 16
CELL, SCALE = 64, 3


def shoot(out: Path, screens: list[str]) -> None:
    """Writes OUTDIR/<mode>/<screen>.png; truncated recordings and raw shot output live in a deleted temp dir."""
    env = dict(os.environ, XTATRIUM_XTFRAME_DIR=str(XTFRAME))
    lines = (ROOT / "tests" / "full_run.atrec").read_text(encoding="utf-8").splitlines()
    groups: dict[int | None, list[str]] = {}
    for s in screens:
        groups.setdefault(SCREENS[s][1], []).append(s)
    with tempfile.TemporaryDirectory(prefix="sherefox-aa-") as tmp:
        for cut, names in groups.items():
            rec = Path(tmp) / f"cut{cut}.atrec"
            rec.write_text("\n".join(ln for ln in lines if cut is None or not ln.startswith('{"t"')
                                     or json.loads(ln)["t"] <= cut) + "\n", encoding="utf-8")
            at = ",".join(str(t) for t in sorted({SCREENS[n][0] for n in names}))
            for mode, flags in MODES.items():
                raw = Path(tmp) / f"cut{cut}-{mode}"
                cmd = [str(EXE), "shot", "--game", ".", "--replay", str(rec), "--at", at, "--out", str(raw), *flags]
                if mode == "m1":
                    cmd.append("--lib-log")
                p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
                if p.returncode != 0:
                    raise SystemExit(f"FAIL xtatrium shot {mode} (exit {p.returncode})\n{p.stderr}")
                if mode == "m1" and cut is None:
                    (out / "lib-log.txt").write_text(p.stderr, encoding="utf-8")
                (out / mode).mkdir(exist_ok=True)
                for n in names:
                    shutil.copyfile(raw / f"shot-{SCREENS[n][0]:06d}.png", out / mode / f"{n}.png")


def load(out: Path, mode: str, name: str) -> np.ndarray:
    return np.asarray(Image.open(out / mode / f"{name}.png").convert("RGB"), dtype=np.int16)


def metrics(ref: np.ndarray, img: np.ndarray) -> tuple[np.ndarray, int, int, float]:
    """Per-pixel largest channel difference; pixels over THRESHOLD; largest difference; mean absolute error over all
    channels of all pixels (0..255)."""
    a = np.abs(img - ref)
    d = a.max(axis=2)
    return d, int((d > THRESHOLD).sum()), int(d.max()), round(float(a.mean()), 4)


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
    shoot(args.out, screens)
    report = {}
    print(f"{'screen':14} {'tick':>5}  {'m1 >16':>8} {'max':>4} {'mae':>7}  {'m4 >16':>8} {'max':>4} {'mae':>7}")
    for name in screens:
        tick = SCREENS[name][0]
        imgs = {m: load(args.out, m, name) for m in MODES}
        d1, n1, x1, e1 = metrics(imgs["sw"], imgs["m1"])
        d4, n4, x4, e4 = metrics(imgs["sw"], imgs["m4"])
        report[name] = {"tick": tick, "m1": {"over16": n1, "max": x1, "mae": e1},
                        "m4": {"over16": n4, "max": x4, "mae": e4}}
        print(f"{name:14} {tick:>5}  {n1:>8} {x1:>4} {e1:>7.4f}  {n4:>8} {x4:>4} {e4:>7.4f}")
        if args.zoom:
            zoom(args.out, name, imgs, [d1, d4], args.zoom)
    (args.out / "report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
