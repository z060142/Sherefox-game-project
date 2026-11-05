# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Write the debate recordings (docs/flows.md §6, tests/README.md) and the scripted-opponent harness:

- tests/ch1_debate.atrec (the game): tests/ch1_case's route to the debate, then the Ch.1 recommended route against
  the scripted rounds of ruling G2 (R1 rebut E01_06, R2 solid E01_01 -> E01_04, R3 rebut E01_03 = the break), the
  result (continue), the result scene's win lines and the notes, up to the Ch.2 paper.
- tests/ch2_debate.atrec (tests/play_harness: the game with a test-only debScript that plays the opponent moves of
  the ref route ch2_route, docs/debate-engine.md §2.4): Ch.2 with every evidence spot, E02_02 / E02_01 / E02_07
  appraised on the board, the recommended chains (ref fixtures ch2_board), the five rounds of the ref route, the
  result, the win lines, the notes, up to the Ch.3 paper.
- tests/ch2_lose.atrec (the game, its seeded AI): tests/ch2_case's route, then 「觀察」 every round until the debate is
  lost; the result's retry; the same again; continue, the lose lines, the notes, up to the Ch.3 paper.

Usage (from the project root):
    uv run tests/gen_debate_play.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS))
import gen_case as gc  # noqa: E402
import gen_playthrough as gp  # noqa: E402
import debate_routes as R  # noqa: E402

HARNESS = TESTS / "play_harness"
GAP = 8
ROUND_WAIT = 720         # ticks after a lock: the reveal, the records, the hold (01-systems §4.4: 3-6 s; 論破 4 s)
CYCLE_WAIT = 64          # observe cycles: lock -> skip -> next
KEY = {"1": 30, "2": 31, "3": 32, "4": 33, "Enter": 40, "R": 21}
SKIP_XY = (640, 400)     # ui/boards/project/Debate.dc.html #reveal-hit (phase 1 skip, phase >= 2 next)


def seg_xy(slot: int) -> tuple[int, int]:
    chain, pos = divmod(slot, 5)      # #chains at (240, 448), cell k: left 36 + 146 pos, top 5 + 44 chain, 122 x 38
    return 337 + 146 * pos, 472 + 44 * chain


def pick_xy(k: int) -> tuple[int, int]:
    return 328 + 142 * (k % 2), 256 + 58 * (k // 2)   # #picker list: 136 x 52 cards, gap 6, two columns


class Rec(gc.Rec):
    def key(self, ui: str, name: str, wait: int = GAP) -> None:
        code = KEY[name]
        self.at(wait, [[ui, "kd", code, 0], [ui, "ku", code, 0]])

    def round(self, act: int, segs=(), pick: int | None = None, wait: int = GAP) -> None:
        self.key("debate", str(act), wait)
        for s in segs:
            self.click("debate", seg_xy(s))
        if pick is not None:
            self.click("debate", pick_xy(pick))
        self.key("debate", "Enter")
        self.t += ROUND_WAIT

    def vn_lines(self, chapter: int, scene: str, branch: str, wait: int) -> None:
        rows = [r for r in gc.load("script") if r["chapter"] == chapter and r["scene"] == scene and r["playable"]
                and r["branch"] == branch]
        for k in range(len(rows)):
            self.click("vn", gp.VN_CLICK, wait if k == 0 else GAP)


def result_and_notes(r: Rec, chapter: int, branch: str) -> None:
    steps = [s for s in gc.load("steps") if s["chapter"] == chapter]
    res = next(s for s in steps if s["kind"] == "result")
    notes = next(s for s in steps if s["kind"] == "vn" and s["idx"] > res["idx"])
    r.key("result", "Enter", 120)
    r.vn_lines(chapter, res["scene"], branch, gp.SETTLE)
    r.vn_lines(chapter, notes["scene"], "", gp.SETTLE)


def ch1() -> int:
    r = Rec()
    gc.story(r, 1)
    gc.investigate(r, [f"HS_CH01_{i:02d}" for i in range(1, 11)])
    r.click("investigate", gc.INV_END, gc.FLY_WAIT)
    b = gc.Board(r, gc.drawer_of(1, {e["id"] for e in gc.EV.values() if e["chapter"] == 1}))
    for card, slot in (("E01_01", 0), ("E01_04", 1)):
        b.select(card)
        b.correct(card)
        b.place(slot)
    for card in ("E01_02", "E01_03", "E01_05", "E01_06"):
        b.select(card)
        b.correct(card)
    b.debate(16)
    r.t += 40
    r.round(3, pick=1)              # R1: rebut, the picker lists E01_05, E01_06 (refuters of N1)
    r.round(1, segs=(0, 1))         # R2: solid E01_01 -> E01_04 at the lit N2
    r.round(3, pick=0)              # R3: rebut E01_03 (the break card, a one-card segment)
    result_and_notes(r, 1, "win")
    return r.write("ch1_debate", 120)


CH2_ALL = ["HS_CH02_01", "HS_CH02_02", "HS_CH02_03", "HS_CH02_04", "HS_CH02_05", "HS_CH02_06", "HS_CH02_07"]


def ch2_route() -> int:
    r = Rec()
    gc.story(r, 2)
    gc.investigate(r, CH2_ALL)
    r.click("investigate", gc.INV_END, gc.FLY_WAIT)
    held = {e["id"] for e in gc.EV.values() if e["chapter"] == 2} - {"E02_08"}
    b = gc.Board(r, gc.drawer_of(2, held))
    for card, slot in (("E02_03", 0), ("E02_02", 1), ("E02_04", 2), ("E02_05", 3), ("E02_06", 5), ("E02_01", 6),
                       ("E02_07", 7)):
        b.select(card)
        if card in ("E02_02", "E02_01", "E02_07"):
            b.appraise(card)
        b.correct(card)
        b.place(slot)
    b.debate(16)
    r.t += 40
    r.round(3, pick=1)                  # R1 rebut E02_02 (picker: E02_03, E02_02, E02_04)
    r.round(4)                          # R2 observe
    r.round(1, segs=(0, 3))             # R3 solid E02_03 .. E02_05 at N1
    r.round(3, segs=(5, 6))             # R4 rebut break E02_06 -> E02_01
    r.round(3, segs=(7, 6))             # R5 the tail: rebut E02_07 -> E02_01
    result_and_notes(r, 2, "win")
    r.lines[0] = json.dumps({"atrec": 1, "step": gp.STEP, "seed": 1, "game": HARNESS.as_posix()})
    return r.write("ch2_debate", 120)


def observe_until_over(r: Rec, cycles: int) -> None:
    for _ in range(cycles):
        r.key("debate", "4", 24)
        r.key("debate", "Enter")
        r.click("debate", SKIP_XY, 12)       # skip: the records without dwell
        r.click("debate", SKIP_XY, CYCLE_WAIT)   # next: the hold ends (or the finished debate closes)


LOSE_CYCLES = 30


def ch2_lose() -> int:
    r = Rec()
    gc.story(r, 2)
    gc.investigate(r, gc.CH2_SPOTS)
    r.click("investigate", gc.INV_BOOK, gc.FLY_WAIT)
    r.click("evbook", gc.book_card_xy(0), 20)
    r.click("evbook", gc.BOOK_APPRAISE, gc.GAP)
    r.click("evbook", gc.BOOK_CLOSE, 20)
    r.click("investigate", gc.INV_END, 30)
    held = {e["id"] for e in gc.EV.values() if e["chapter"] == 2} - {"E02_05", "E02_08"}
    b = gc.Board(r, gc.drawer_of(2, held), appraised={"E02_01"})
    for card, slot in (("E02_03", 0), ("E02_02", 1)):
        b.select(card)
        if card == "E02_02":
            b.appraise(card)
        b.correct(card)
        b.place(slot)
    b.debate(16)
    b.debate(16)                             # the first press only warns (cards left to appraise, §2.7)
    r.t += 40
    observe_until_over(r, LOSE_CYCLES)
    r.key("result", "R", 120)                # retry (A-14): the debate from its start, the board as it was
    r.t += 40
    observe_until_over(r, LOSE_CYCLES)
    result_and_notes(r, 2, "lose")
    return r.write("ch2_lose", 120)


# The story playthroughs (tests/gen_playthrough.py) go through the debates the shortest sure way: the warmup's
# first card (E03_05, right); 「觀察」 every round of a debate until it ends (Ch.1: unachieved after R3; Ch.2 / Ch.3:
# lost, the seeded AI); the result's continue and its lose lines.
MINIMAL_BRANCH = "lose"
MINIMAL_CYCLES = {1: 8, 2: LOSE_CYCLES, 3: LOSE_CYCLES}


def minimal(r, kind: str, chapter: int) -> None:
    rr = Rec.__new__(Rec)
    rr.__dict__ = r.__dict__   # share the recording's lines and clock
    if kind == "warmup":
        rr.key("debate", "3", 40)
        rr.click("debate", pick_xy(0))
        rr.key("debate", "Enter")
        for _ in range(3):
            rr.click("debate", SKIP_XY, CYCLE_WAIT)
        rr.t += 60
    elif kind == "debate":
        rr.t += 40
        observe_until_over(rr, MINIMAL_CYCLES[chapter])
    elif kind == "result":
        step = next(s for s in gc.load("steps") if s["chapter"] == chapter and s["kind"] == "result")
        rr.key("result", "Enter", 120)
        rr.vn_lines(chapter, step["scene"], MINIMAL_BRANCH, gp.SETTLE)


# ------------------------------------------------------------------------------------------------ harness

def harness_script() -> list[dict]:
    """The game's debScript rows plus the ch2_route opponent moves keyed CH02_MAIN:<round> (scripted 0: the
    behaviour-rule memory runs as in the ref route, docs/debate-engine.md §6)."""
    rows = json.loads((ROOT / "data" / "debScript.json").read_text(encoding="utf-8"))
    route = next(rt for rt in R.ROUTES if rt.name == "ch2_route")
    _, script, _ = R.build([route])
    for row in script:
        rnd = row["key"].split(":")[1]
        rows.append({**row, "key": f"CH02_MAIN:{rnd}", "clarity": "clear", "shown1": row["action"]})
    return rows


def build_harness() -> None:
    """tests/play_harness/: a copy of the game (game.json, flows, data, strings, the UI bundle) whose debScript
    also plays the ch2_route opponent (game paths may not leave the game directory, so it is a copy)."""
    for sub in ("flows", "data", "strings", "ui"):
        shutil.rmtree(HARNESS / sub, ignore_errors=True)
    HARNESS.mkdir(exist_ok=True)
    shutil.copytree(ROOT / "flows", HARNESS / "flows")
    shutil.copytree(ROOT / "data", HARNESS / "data")
    shutil.copytree(ROOT / "strings", HARNESS / "strings")
    shutil.copytree(ROOT / "ui" / "bundle", HARNESS / "ui" / "bundle")
    shutil.copyfile(ROOT / "game.json", HARNESS / "game.json")
    (HARNESS / "data" / "debScript.json").write_text(
        "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in harness_script()) + "\n]\n", encoding="utf-8")


RECORDINGS = {"ch1_debate": ch1, "ch2_debate": ch2_route, "ch2_lose": ch2_lose}


def main() -> int:
    build_harness()
    ticks = {name: fn() for name, fn in RECORDINGS.items()}
    (TESTS / "debate_ticks.json").write_text(json.dumps(ticks, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
