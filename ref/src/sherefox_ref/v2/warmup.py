"""The v2 demo D01 warm-up (11_demo_chapter.md §2 S04, §3.2): Inspector Baskerville makes three points in order; for
each the player picks one of the three warm-up observations (all known from the start). The right one plays
Sherefox's line and his concession and moves to the next point; a wrong one (another observation, or one already used
correctly: design 3689f6d) plays L005 and the same point is asked again. No credibility is lost. Three mistakes in
total end it as failed (the third plays L014 and L015 straight away: SPEC-QUESTION, the chapter does not say whether
L005 comes first). Success: L012, plus L013 with no mistake.

Outcome (world.d1Warmup): pass_clean (no mistakes), pass, fail; ch.warmup[outcome] has the appraisal limit and the
inspector's favour change.

Data: d01_extra.json `warmup_play` (line ids are short: L001 = SCR_D01_S04_L001).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sherefox_ref.v2.data import DATA_DIR

PLAY = {k: v for k, v in json.loads((DATA_DIR / "d01_extra.json").read_text(encoding="utf-8"))["warmup_play"].items()
        if k != "ref"}


@dataclass(frozen=True)
class Result:
    shown: tuple[str, ...]   # the lines in the order they are shown; a point line again after each L005
    outcome: str             # pass_clean / pass / fail
    mistakes: int
    used: int                # picks consumed (picks after the end are ignored)


def line_id(short: str) -> str:
    return f"SCR_D01_S04_{short}"


def play(picks: list[str]) -> Result:
    """Run the warm-up for a sequence of picks (W1 / W2 / W3). Raises ValueError when the picks run out first."""
    shown = list(PLAY["opening"])
    points = PLAY["points"]
    mistakes, used, done = 0, 0, set()
    p = 0
    shown.append(points[0]["line"])
    while True:
        if used >= len(picks):
            raise ValueError(f"warm-up not finished after {used} picks")
        pick = picks[used]
        used += 1
        if pick not in PLAY["observations"]:
            raise ValueError(f"unknown observation {pick!r}")
        pt = points[p]
        if pick == pt["answer"] and pick not in done:
            done.add(pick)
            shown += pt["reply"]
            p += 1
            if p == len(points):
                shown += PLAY["success"] + (PLAY["clean"] if mistakes == 0 else [])
                return Result(tuple(shown), "pass_clean" if mistakes == 0 else "pass", mistakes, used)
            shown.append(points[p]["line"])
            continue
        mistakes += 1
        if mistakes >= PLAY["max_wrong"]:
            shown += PLAY["failure"]
            return Result(tuple(shown), "fail", mistakes, used)
        shown += PLAY["wrong"]
        shown.append(pt["line"])
