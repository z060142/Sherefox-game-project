# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Check the investigation's area arrows both ways (docs/ui-contracts.md investigate, nav_prev / nav_next).

Usage (from the project root):
    uv run tests/check_nav.py

It replays tests/ch3_warmfail.atrec (which ends in Ch.3's investigation, first scene) plus four clicks appended in
a temporary copy: ◀▶ bar at y 38, ▶ (x 860) twice, then ◀ (x 420) twice, and traces ui.investigate.*. The ▶ clicks
must reach nav-next and the ◀ clicks nav-prev, each emitting nav (+1 / -1). Regression: the area name was
absolutely positioned against the bar instead of its plate, so it covered ◀ and swallowed its clicks.
The temporary recording is deleted.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from xt_cli import EXE, XTFRAME, compile_game  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CLICKS = [(1600, 860), (1660, 860), (1720, 420), (1780, 420)]   # after the recording's last input (t 1500)


def main() -> int:
    compile_game(ROOT)
    src = (ROOT / "tests" / "ch3_warmfail.atrec").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="sherefox-nav-") as tmp:
        rec = Path(tmp) / "nav.atrec"
        lines = [src.rstrip("\n")]
        for t, x in CLICKS:
            lines.append(f'{{"t": {t}, "u": [["investigate", "pd", {x}, 38, 0, 1], ["investigate", "pu", {x}, 38, 0]]}}')
        rec.write_text("\n".join(lines) + "\n", encoding="utf-8")
        p = subprocess.run([str(EXE), "trace", "--game", ".", "--replay", str(rec), "--ticks", "1840",
                            "--signals", "ui.investigate.*"], capture_output=True, text=True, encoding="utf-8",
                           cwd=ROOT, env=dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME))
    if p.returncode != 0:
        raise SystemExit(f"FAIL xtatrium trace (exit {p.returncode})\n{p.stderr}")
    clicks: dict[int, set[str]] = {}
    for line in p.stdout.splitlines():
        tok = line.split()
        if len(tok) >= 3 and tok[2] == "pulse" and tok[1].endswith(".Click"):
            clicks.setdefault(int(tok[0][1:]), set()).add(tok[1].split(".")[2])
    fails = []
    for t, x in CLICKS:
        want = "nav-next" if x == 860 else "nav-prev"
        if want not in clicks.get(t, set()):
            fails.append(f"t{t}: click at x {x} hit {sorted(clicks.get(t, set()))}, expected {want}")
    if "t1720 ui.investigate.nav 1 -> -1" not in p.stdout:
        fails.append("◀ did not set nav to -1")
    for f in fails:
        print("FAIL " + f)
    if fails:
        return 1
    print("nav: ▶ x2 reaches nav-next, ◀ x2 reaches nav-prev (nav 1 -> -1); ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
