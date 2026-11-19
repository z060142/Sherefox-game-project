# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Write the v2 demo D01 full-chapter recordings (v2 demo 4.4; tests/README.md, docs/flows.md §4.15) and their harnesses.

tests/d1_full<R>.atrec, one per route R of ch §12 (A-D), from the title's v2 entry (chapter 101) to the S11 placeholder
and back to the title, then the chapter started again:
- S01 paper, S02 / S03, the warm-up with the route's result (ref routes.py: A-C `pass`, passed with mistakes, so no
  inspector favour, as §12.1-§12.3 show none; route D fails it), tests/gen_d1_story.py story() and RUNS;
- the real investigation: every evidence hotspot (all 12 evidence and the talking board are found, as the routes say
  what is left behind) and only the hotspots of the route's notes (ref routes.py: A, B all five; C PN1, PN3 + OBS01;
  D none); the route's appraisals in the evidence list;
- the carry screen: the route's nine, confirm, yes (something is left), the click on after L010;
- the debate with the route's moves (tests/gen_d1_play.py), Cedric's moves pinned by the harness's test hook;
- S07's lines after it, S08, the result screen, the S09 paper, S10 and the S11 placeholder's back to title
  (gen_d1_play.epilogue);
- the chapter again from the title: the S01 paper, S02 / S03, a clean warm-up, the investigation (its first screen
  must show a fresh chapter).

tests/d1full_harness<R>: tests/gen_d1_play.py's harness for route R (its dev-entry loadout swap answers only the dev
chip, unused here). Ticks and marks in tests/d1_full_ticks.json.

Usage (from the project root):
    uv run tests/gen_d1_full.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(ROOT / "tools"))
import gen_d1_m3 as gm  # noqa: E402
import gen_d1_play as gd  # noqa: E402
import gen_d1_story as gs  # noqa: E402
from sherefox_ref.v2 import routes as RT  # noqa: E402

ROUTES = ("A", "B", "C", "D")
NOTE_SPOTS = {"PN1": ["HS03"], "PN2": ["HS22"], "PN3": ["HS04", "HS05"], "PN4": ["HS13"], "OBS01": ["HS05"]}
APPR_EV = {"A01": "E01", "A02": "E02", "A04": "E04"}


def harness_dir(route: str) -> Path:
    return TESTS / f"d1full_harness{route}"


def build_harness(route: str) -> None:
    gd.build_harness(route)
    shutil.rmtree(harness_dir(route), ignore_errors=True)
    shutil.move(str(gd.harness_dir(route)), str(harness_dir(route)))


def spots_for(route: str) -> list[dict]:
    lo = RT.ROUTES[route].loadout
    want = {h for n in lo.notes for h in NOTE_SPOTS[n]}
    return [s for s in gm.SPOTS if s["ev"] or s["id"] in want]


def investigate(r: gm.Rec, route: str, pre: str = "") -> None:
    spots = spots_for(route)
    for i, scene in enumerate(gm.SCENES):
        if i:
            r.click("d1inv", gm.loc_xy(i), 10)
        r.t += 20
        for s in [s for s in spots if s["scene"] == scene]:
            r.click("d1inv", gm.spot_xy(s), 10)
            r.mark(f"{pre}pop_{s['id']}", 8)
            r.t += 10
            r.click("d1inv", gm.SHADE, 8)
        r.t += 20
    r.click("d1inv", gm.BOOK_BTN, 10)
    r.t += 20
    for a in RT.ROUTES[route].loadout.appraisals:
        r.click("d1book", gm.card_xy(gm.ITEMS.index(APPR_EV[a])), 12)
        r.click("d1book", gm.APPRAISE, 10)
        r.mark(f"{pre}appr_{a}", 10)
    r.click("d1book", gm.BOOK_X, 10)
    r.t += 10


def carry(r: gm.Rec, route: str) -> None:
    r.click("d1inv", gm.END_BTN, 10)
    r.mark("carry", 20)
    r.t += 20
    for e in RT.ROUTES[route].loadout.carried:
        r.click("d1carry", gm.item_xy(gm.ITEMS.index(e)), 10)
    r.click("d1carry", gm.CONFIRM, 10)
    r.mark("confirm", 10)
    r.t += 20
    r.click("d1carry", gm.YES, 10)
    r.mark("l010", 10)
    r.t += 20
    r.click("d1carry", gm.ON, 10)
    r.mark("go", 2)
    r.t += 40


def debate(r: gm.Rec, route: str) -> None:
    rounds = gd.forced(route)
    gd.opening(r)
    for n, (s, pa, _) in enumerate(rounds, start=1):
        r.round(s, pa, n)
    r.marks["end"] = r.t
    outcome = gd.outcome_of(rounds)
    gd.outro(r, outcome)
    gd.epilogue(r, gd.final_state(rounds))


def restart(r: gm.Rec) -> None:
    """The chapter again from the title, up to its investigation (marks with the prefix `again_`)."""
    r.t += 30
    before = dict(r.marks)
    gs.story(r, gs.RUNS["clean"])
    for k in ("paper", "inv"):
        r.marks[f"again_{k}"] = r.marks[k]
        r.marks[k] = before[k]
    r.t += 30
    r.mark("again_inv_shown", 0)
    r.t += 30


def record(route: str) -> tuple[int, dict, list]:
    r = gm.Rec(f"tests/d1full_harness{route}")
    lo = RT.ROUTES[route].loadout
    gs.story(r, gs.RUNS[{"fail": "fail", "pass": "pass", "pass_clean": "clean"}[lo.warmup]])
    investigate(r, route)
    carry(r, route)
    debate(r, route)
    restart(r)
    end = r.write(f"d1_full{route}", 60)
    return end, r.marks, r.shown


def main() -> int:
    out = {}
    for route in ROUTES:
        build_harness(route)
        end, marks, shown = record(route)
        out[route] = {"ticks": end, "marks": marks, "shown": shown}
    (TESTS / "d1_full_ticks.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
