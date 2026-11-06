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
- tests/ch3_debate.atrec (tests/play_harness, whose debScript also plays the ref route ch3_route's opponent): the
  ch2_debate route (a win: G-01 is earned), then Ch.3: its paper and vn steps, the warmup (E03_05, its opening and
  wrap-up lines), the investigation across the three scenes (E03_07, E03_04 / E03_03, E03_08 / E03_06), the ref
  board ch3_board (E03_02 and E03_04 appraised on the board), the five rounds of ch3_route, the result, the win
  lines, the notes, up to the final paper and the end card.
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
KEY = {"1": 30, "2": 31, "3": 32, "4": 33, "Enter": 40, "R": 21, "E": 8}
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

    def cue_lines(self, chapter: int, kind: str, cue: str, wait: int) -> None:
        """The lines of the debate / warmup step's scene with script.cue `cue` (pre / post / postWin / postLose)."""
        scene = next(s["scene"] for s in gc.load("steps") if s["chapter"] == chapter and s["kind"] == kind)
        rows = [r for r in gc.load("script") if r["chapter"] == chapter and r["scene"] == scene and r["playable"]
                and r["cue"] == cue]
        for k in range(len(rows)):
            self.click("vn", gp.VN_CLICK, wait if k == 0 else GAP)

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
    gc.end(r, 1, False, gc.FLY_WAIT)
    b = gc.Board(r, gc.drawer_of(1, {e["id"] for e in gc.EV.values() if e["chapter"] == 1}))
    for card, slot in (("E01_01", 0), ("E01_04", 1)):
        b.select(card)
        b.correct(card)
        b.place(slot)
    for card in ("E01_02", "E01_03", "E01_05", "E01_06"):
        b.select(card)
        b.correct(card)
    b.debate(16)
    r.cue_lines(1, "debate", "pre", gp.SETTLE)
    r.t += 40
    r.round(3, pick=1)              # R1: rebut, the picker lists E01_05, E01_06 (refuters of N1)
    r.round(1, segs=(0, 1))         # R2: solid E01_01 -> E01_04 at the lit N2
    r.round(3, pick=0)              # R3: rebut E01_03 (the break card, a one-card segment)
    r.cue_lines(1, "debate", "postWin", 0)     # Arthur's confession (S05 L027-L035)
    result_and_notes(r, 1, "win")
    return r.write("ch1_debate", 120)


CH2_ALL = ["HS_CH02_01", "HS_CH02_02", "HS_CH02_03", "HS_CH02_04", "HS_CH02_05", "HS_CH02_06", "HS_CH02_07"]


def ch2_route() -> int:
    r = Rec()
    ch2_play(r)
    r.lines[0] = json.dumps({"atrec": 1, "step": gp.STEP, "seed": 1, "game": HARNESS.as_posix()})
    return r.write("ch2_debate", 120)


def ch2_play(r: Rec) -> None:
    """From the title: Ch.2 won along ch2_route, up to the Ch.3 paper."""
    gc.story(r, 2)
    gc.investigate(r, CH2_ALL)
    gc.end(r, 2, True, gc.FLY_WAIT)
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
    r.cue_lines(2, "debate", "pre", gp.SETTLE)
    r.t += 40
    r.round(3, pick=1)                  # R1 rebut E02_02 (picker: E02_03, E02_02, E02_04)
    r.round(4)                          # R2 observe
    r.round(1, segs=(0, 3))             # R3 solid E02_03 .. E02_05 at N1
    r.round(3, segs=(5, 6))             # R4 rebut break E02_06 -> E02_01
    r.round(3, segs=(7, 6))             # R5 the tail: rebut E02_07 -> E02_01
    r.cue_lines(2, "debate", "postWin", 0)     # Wolfhart's cup (S05 L041-L042)
    result_and_notes(r, 2, "win")


# Ch.3 (ref fixtures ch3_case / ch3_board; the moves of debate_routes CH3): the spots that give the board's cards,
# scene by scene (nav E), and the board's chains in slot order.
CH3_SCENES = [["HS_CH03_02", "HS_CH03_04"], ["HS_CH03_05", "HS_CH03_06"], ["HS_CH03_08"]]
CH3_PLACE = [("E03_07", 0), ("E03_06", 1), ("E03_02", 5), ("E03_04", 6), ("G-01", 7), ("E03_05", 10), ("E03_03", 11)]
CH3_START = {}     # ch3_debate: the tick the Ch.3 debate step's pre line is clicked away (the debate starts)


def ch3_route() -> int:
    r = Rec()
    ch2_play(r)
    steps = [s for s in gc.load("steps") if s["chapter"] == 3]
    for s in steps:
        if s["kind"] == "paper" and s["idx"] == 0:
            r.click("paper", gp.PAPER_CLICK, gp.SETTLE)
            r.click("paper", gp.PAPER_CLICK, GAP)
        elif s["kind"] == "vn" and s["sub"] != "notes":
            r.vn_lines(3, s["scene"], "", gp.SETTLE)
        elif s["kind"] == "warmup":
            minimal(r, "warmup", 3)                # E03_05 at once: no mistake
        elif s["kind"] == "investigate":
            for k, spots in enumerate(CH3_SCENES):
                if k:
                    r.key("investigate", "E", gc.FLY_WAIT)
                    r.t += 4
                gc.investigate(r, spots)
            gc.end(r, 3, True, gc.FLY_WAIT)
        elif s["kind"] == "board":
            held = {"E03_01", "E03_02", "E03_05", "E03_07", "E03_04", "E03_03", "E03_08", "E03_06", "G-01"}
            b = gc.Board(r, gc.drawer_of(3, held), appraised={"E03_01"})   # E03_01: revealed by the police report
            for card, slot in CH3_PLACE:
                if card == "G-01":
                    # the ninth drawer card is below the drawer's visible 476 px: scroll it to the bottom (the list
                    # is 9 x 58 = 522 px, so 46 px), pick G-01 there, place it, scroll back
                    r.at(GAP, [["board", "wh", 128, 400, 0, 5]])     # (wheel y > 0 scrolls down)
                    x, y = gc.drawer_xy(b.drawer.index(card))
                    r.click("board", (x, y - 46), 20)
                    b.place(slot)
                    r.at(GAP, [["board", "wh", 128, 400, 0, -5]])
                    r.t += 20
                    continue
                b.select(card)
                if card in ("E03_02", "E03_04"):
                    b.appraise(card)
                b.correct(card)
                b.place(slot)
            for card in ("E03_08", "E03_01"):
                b.select(card)
                b.correct(card)
            b.debate(16)
            b.debate(16)            # (only in case the first press warns, §2.7)
        elif s["kind"] == "debate":
            r.cue_lines(3, "debate", "pre", gp.SETTLE)
            CH3_START["tick"] = r.t
            r.t += 40
            r.round(3, pick=1)                  # R1 rebut E03_08 (picker: E03_06, E03_08)
            r.round(4)                          # R2 observe
            r.round(1, segs=(0, 1))             # R3 solid E03_07 -> E03_06 at N3
            r.round(3, segs=(5, 7))             # R4 rebut break E03_02 -> E03_04 -> G-01
            r.t += 1200                         # the break round plays out longer (論破, the tail's claim)
            r.round(3, segs=(10, 11))           # R5 the tail: rebut E03_05 -> E03_03
            r.t += 600
            r.cue_lines(3, "debate", "postWin", 0)    # none in Ch.3
        elif s["kind"] == "result":
            result_and_notes(r, 3, "win")
        elif s["kind"] == "paper":
            r.click("paper", gp.PAPER_CLICK, gp.SETTLE)    # the final paper (CH04_OPEN), then the end card
            r.click("paper", gp.PAPER_CLICK, GAP)
    r.lines[0] = json.dumps({"atrec": 1, "step": gp.STEP, "seed": 1, "game": HARNESS.as_posix()})
    return r.write("ch3_debate", 120)


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
    gc.end(r, 2, True, 30)
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
    r.cue_lines(2, "debate", "pre", gp.SETTLE)
    r.t += 40
    observe_until_over(r, LOSE_CYCLES)
    r.key("result", "R", 120)                # retry (A-14): the debate from its start, the board as it was
    r.cue_lines(2, "debate", "pre", gp.SETTLE)    # the step begins again with its opening line
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
        rr.cue_lines(chapter, kind, "pre", gp.SETTLE)
        rr.key("debate", "3", 40)
        rr.click("debate", pick_xy(0))
        rr.key("debate", "Enter")
        for _ in range(3):
            rr.click("debate", SKIP_XY, CYCLE_WAIT)
        rr.t += 60
        rr.cue_lines(chapter, kind, "post", gp.SETTLE)
    elif kind == "debate":
        rr.cue_lines(chapter, kind, "pre", gp.SETTLE)
        rr.t += 40
        observe_until_over(rr, MINIMAL_CYCLES[chapter])
        rr.cue_lines(chapter, kind, "postLose", gp.SETTLE)   # none in Ch.1-3
    elif kind == "result":
        step = next(s for s in gc.load("steps") if s["chapter"] == chapter and s["kind"] == "result")
        rr.key("result", "Enter", 120)
        rr.vn_lines(chapter, step["scene"], MINIMAL_BRANCH, gp.SETTLE)


# ------------------------------------------------------------------------------------------------ harness

def harness_script() -> list[dict]:
    """The game's debScript rows plus the ch2_route / ch3_route opponent moves keyed CH02_MAIN:<round> /
    CH03_MAIN:<round> (scripted 0: the behaviour-rule memory runs as in the ref route, docs/debate-engine.md §6)."""
    rows = json.loads((ROOT / "data" / "debScript.json").read_text(encoding="utf-8"))
    for name, case in (("ch2_route", "CH02_MAIN"), ("ch3_route", "CH03_MAIN")):
        route = next(rt for rt in R.ROUTES if rt.name == name)
        _, script, _ = R.build([route])
        for row in script:
            rnd = row["key"].split(":")[1]
            rows.append({**row, "key": f"{case}:{rnd}", "clarity": "clear", "shown1": row["action"]})
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


RECORDINGS = {"ch1_debate": ch1, "ch2_debate": ch2_route, "ch3_debate": ch3_route, "ch2_lose": ch2_lose}


def main() -> int:
    build_harness()
    ticks = {name: fn() for name, fn in RECORDINGS.items()}
    ticks["ch3_debate_from"] = CH3_START["tick"]
    (TESTS / "debate_ticks.json").write_text(json.dumps(ticks, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
