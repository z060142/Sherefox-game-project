# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Write the v2 demo D01 story recordings (M4a: S01 paper, S02 / S03 vn, S04 warm-up; docs/flows.md §4.14,
tests/README.md), clicked from the title's v2 entry (chapter 101), for tests/check_d1_story.py and tests/check_music.py:

- d1_story_clean.atrec: the warm-up without a mistake (W1, W2, W3), then the investigation; end of the search -> the
  carry screen (the music check's last cue);
- d1_story_pass.atrec: two mistakes (W2 on point 1; W1 again on point 3), then the investigation;
- d1_story_fail.atrec: three mistakes (W2, W3 on point 1, W1 right, W1 again on point 2), then the investigation.

Every shown line is marked (`marks`: [screen, line id, tick]); the warm-up's lines and picks come from the reference
model (ref sherefox_ref.v2.warmup.play). tests/gen_d1_m3.py plays the clean run with story().

Usage (from the project root):
    uv run tests/gen_d1_story.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "ref" / "src"))
import gen_d1_play as gd  # noqa: E402
from sherefox_ref.v2 import warmup as W  # noqa: E402

# board coordinates (1280x720; ui/boards/project/Title, Paper, Vn, D1Warm, D1Inv)
TITLE_V2 = (404, 643)          # Title #btn-v2 (chapter 101)
PAPER = (640, 360)             # anywhere on the paper
VN = (640, 300)                # Vn #hit
WARM_LINE = (640, 600)         # D1Warm #dlg
OBS = {"W1": (408, 380), "W2": (640, 380), "W3": (872, 380)}   # D1Warm #obs-1..3
INV_END = (1176, 678)          # D1Inv end of the search
WAIT = 30                      # ticks between clicks: the standees' 420 ms fade-in is over before the next one
RUNS = {"clean": ["W1", "W2", "W3"], "pass": ["W2", "W1", "W2", "W1", "W3"], "fail": ["W2", "W3", "W1", "W1"]}
POINTS = {p["line"] for p in W.PLAY["points"]}


def scene_lines(scene: str) -> list[str]:
    rows = json.loads((ROOT / "data" / "script.json").read_text(encoding="utf-8"))
    return [r["id"] for r in sorted((r for r in rows if r["sceneKey"] == f"D01_{scene}" and r["playable"]),
                                    key=lambda r: r["seq"])]


class Rec(gd.Rec):
    def __init__(self, game: str, seed: int = 1) -> None:
        super().__init__(game, seed)
        self.shown: list[list] = []

    def see(self, screen: str, line: str, after: int = 6) -> None:
        self.shown.append([screen, line, self.t + after])


def story(r: Rec, picks: list[str]) -> W.Result:
    """From the title: the D01 entry, the paper, S02, S03, the warm-up with `picks`; ends on the investigation."""
    r.click("title", TITLE_V2, 40)
    r.t += 30
    r.see("paper", "D01_OPEN")
    r.marks["paper"] = r.t + 6
    r.click("paper", PAPER, WAIT)
    for scene in ("S02", "S03"):
        for lid in scene_lines(scene):
            r.see("vn", lid)
            r.click("vn", VN, WAIT)
    res = W.play(picks)
    used = iter(picks)
    for short in res.shown:
        r.see("d1warm", W.line_id(short))
        if short in POINTS and short != res.shown[-1]:
            r.click("d1warm", OBS[next(used)], WAIT)
        else:
            r.click("d1warm", WARM_LINE, WAIT)
    r.t += 30
    r.marks["inv"] = r.t
    return res


def main() -> int:
    ticks = {}
    for name, picks in RUNS.items():
        r = Rec(".")
        res = story(r, picks)
        if name == "clean":
            r.click("d1inv", INV_END, 10)
            r.t += 30
            r.marks["carry"] = r.t
        end = r.write(f"d1_story_{name}", 40)
        ticks[name] = {"ticks": end, "marks": r.marks, "shown": r.shown, "outcome": res.outcome, "picks": picks}
    (TESTS / "d1_story_ticks.json").write_text(json.dumps(ticks, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
