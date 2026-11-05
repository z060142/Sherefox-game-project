# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Write the investigation / clue-board recordings (docs/flows.md §5, tests/README.md):

- tests/ch1_case.atrec: Ch.1 from the title through its paper and vn steps; every one of the 10 hotspots (each
  popup dismissed), Sherefox's hint, end of the investigation; on the board the recommended chain
  E01_01 -> E01_04 (ref fixtures ch1_board), the correct reason for every card, to the debate (debate stub).
- tests/ch2_case.atrec: Ch.2 the same way up to the investigation; six evidence spots and one inspect spot
  (HS_CH02_05 / E02_05 is missed), E02_01 appraised in the evidence book, Arthur's hint; on the board E02_02 and
  E02_07 appraised, chain I E02_03 -> E02_02 -> E02_04 with a wrong reason for E02_04 (sophistry), an invalid try
  (E02_06 next to E02_04, bounced), chain II E02_06 -> E02_01 -> E02_07, correct reasons otherwise, to the debate.

Board and evidence-book clicks go to the element positions of ui/boards/project/Board.dc.html / Evbook.dc.html;
the detail panel's reason rows move with the text above them, so their position is computed from the strings
(`reason_xy`, a line-count model of the panel's flex column). The expected results are in tests/check_case.py
(`ROUTES`).

Usage (from the project root):
    uv run tests/gen_case.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS))
import gen_playthrough as gp  # noqa: E402

GAP = 8
POP_WAIT = 12      # ticks after a spot click before the popup is dismissed
FLY_WAIT = 36      # ticks after the dismiss click (a card popup flies to the book first: 420 ms)
BOUNCE_WAIT = 45   # an invalid card bounces back after 0.35 s

# investigate (Investigate.dc.html)
INV_END = (1160, 674)
INV_BOOK = (980, 674)
INV_HINT = (68, 656)
INV_DISMISS = (640, 360)
# evbook (Evbook.dc.html): dock at (80, 40)
BOOK_CLOSE = (1108, 73)
BOOK_APPRAISE = (980, 604)
# board (Board.dc.html)
BOARD_DEBATE = (1178, 38)
BOARD_APPRAISE = (1108, 669)


def load(name: str):
    return json.loads((ROOT / "data" / f"{name}.json").read_text(encoding="utf-8"))


def strings(lang: str = "zh-TW") -> dict[str, str]:
    with open(ROOT / "strings" / f"{lang}.csv", encoding="utf-8-sig", newline="") as f:
        return {r[0]: r[1] for r in list(csv.reader(f))[1:]}


EV = {e["id"]: e for e in load("evidence")}
TAGS = {t["id"]: t for t in load("tags")}
S = strings()
S_EN = strings("en")


def spot_xy(spot_id: str) -> tuple[int, int]:
    h = next(h for h in load("hotspots") if h["id"] == spot_id)
    return h["x"] + h["w"] // 2, h["y"] + h["h"] // 2


def slot_xy(slot: int) -> tuple[int, int]:
    chain, pos = divmod(slot, 5)
    return 344 + 132 * pos, 168 + 140 * chain


def drawer_xy(index: int) -> tuple[int, int]:
    return 128, 138 + 58 * index


def book_card_xy(index: int) -> tuple[int, int]:
    row, col = divmod(index, 4)
    return 114 + 126 * col + 58, 140 + 154 * row + 70


def lines(text: str, font: float, width: float) -> int:
    n, w = 1, 0.0
    for ch in text:
        cw = font if ord(ch) > 0x2E80 else font * 0.55
        if w + cw > width:
            n, w = n + 1, cw
        else:
            w += cw
    return n


def reason_xy(card: str, which: int, revealed: bool, lang: str = "zh-TW") -> tuple[int, int]:
    """Centre of the first line of reason row `which` (1..3) while no reason is chosen (UI_BOARD_REASON_NONE shown).
    The detail body is a flex column from y 122 with 8 px gaps (Board.dc.html #detail-body); the text is measured
    in the recording's language."""
    return 1108, reason_span(card, which, revealed, S_EN if lang == "en" else S)[0] + 18


def reason_span(card: str, which: int, revealed: bool, S: dict) -> tuple[int, int]:
    """(top, bottom) of reason row `which` in the language of the string table S."""
    e = EV[card]
    hidden = set(e["hiddenTags"].split(",")) - {""}
    tags = " ".join("？" if (t in hidden and not revealed) else S[TAGS[t]["nameKey"]] for t in e["tags"].split(","))
    y = 122
    y += min(2, lines(S[e["nameKey"]], 21, 264)) * 28 + 8
    y += lines(tags, 13, 264) * 20 + 8
    y += 3 + 8
    y += min(4, lines(S[e["descKey"]], 14, 264)) * 22 + 8
    y += 20 + 8      # kicker
    y += 20 + 8      # reason none
    for k in range(1, which):
        y += 18 + lines(S[e[f"reason{k - 1}Key"]], 14, 218) * 20 + 8
    return y + 4, y + 18 + lines(S[e[f"reason{which - 1}Key"]], 14, 218) * 20 - 4


class Rec(gp.Recording):
    def click(self, ui: str, xy, wait: int = GAP) -> None:
        self.at(wait, gp.click(ui, xy))


def story(r: Rec, chapter: int) -> None:
    """Title -> the chapter's paper and vn steps up to its investigation."""
    r.click("title", gp.TITLE_CH[chapter], 40)
    steps = {s["id"]: s for s in load("steps")}
    for step_id, ui, clicks in gp.plan(chapter):
        if steps[step_id]["kind"] == "investigate":
            return
        if ui is None:
            r.t += 2
            continue
        for k in range(clicks):
            r.click(ui, gp.PAPER_CLICK if ui == "paper" else gp.VN_CLICK, gp.SETTLE if k == 0 else GAP)


def investigate(r: Rec, spots: list[str]) -> None:
    for i, sid in enumerate(spots):
        r.click("investigate", spot_xy(sid), gp.SETTLE if i == 0 else FLY_WAIT)
        r.click("investigate", INV_DISMISS, POP_WAIT)


class Board:
    """Board actions on the drawer (card ids in drawer order)."""

    def __init__(self, r: Rec, drawer: list[str], appraised=()) -> None:
        self.r, self.drawer, self.appraised = r, drawer, set(appraised)
        self.first = True
        self.lang = "zh-TW"
        self.reason_set: set[str] = set()

    def select(self, card: str) -> None:
        self.r.click("board", drawer_xy(self.drawer.index(card)), 40 if self.first else GAP)
        self.first = False

    def reason(self, card: str, which: int) -> None:
        assert card not in self.reason_set, "the reason rows move once a reason is chosen"
        e = EV[card]
        revealed = not e["hiddenTags"] or card in self.appraised
        self.r.click("board", reason_xy(card, which, revealed, self.lang), GAP)
        self.reason_set.add(card)

    def correct(self, card: str) -> None:
        self.reason(card, EV[card]["correct"] + 1)

    def wrong(self, card: str) -> None:
        self.reason(card, (EV[card]["correct"] + 1) % 3 + 1)

    def appraise(self, card: str) -> None:
        self.r.click("board", BOARD_APPRAISE, GAP)
        self.appraised.add(card)

    def place(self, slot: int, wait: int = GAP) -> None:
        self.r.click("board", slot_xy(slot), wait)

    def debate(self, wait: int = GAP) -> None:
        self.r.click("board", BOARD_DEBATE, wait)


def drawer_of(chapter: int, held) -> list[str]:
    return [e["id"] for e in load("evidence")
            if str(chapter) in e["usable"].split(",") and e["onBoard"] and e["id"] in held]


def ch1() -> int:
    r = Rec()
    story(r, 1)
    spots = [f"HS_CH01_{i:02d}" for i in range(1, 11)]
    investigate(r, spots)
    r.click("investigate", INV_HINT, FLY_WAIT)
    r.click("investigate", INV_END, 30)
    b = Board(r, drawer_of(1, {e["id"] for e in EV.values() if e["chapter"] == 1}))
    for card, slot in (("E01_01", 0), ("E01_04", 1)):
        b.select(card)
        b.correct(card)
        b.place(slot)
    for card in ("E01_02", "E01_03", "E01_05", "E01_06"):
        b.select(card)
        b.correct(card)
    b.debate(16)
    return r.write("ch1_case", 60)


CH2_SPOTS = ["HS_CH02_01", "HS_CH02_02", "HS_CH02_03", "HS_CH02_04", "HS_CH02_06", "HS_CH02_07", "HS_CH02_09"]


def ch2() -> int:
    r = Rec()
    story(r, 2)
    investigate(r, CH2_SPOTS)
    r.click("investigate", INV_BOOK, FLY_WAIT)        # evidence book: E02_01 (first card) -> appraise -> close
    r.click("evbook", book_card_xy(0), 20)
    r.click("evbook", BOOK_APPRAISE, GAP)
    r.click("evbook", BOOK_CLOSE, 20)
    r.click("investigate", INV_HINT, 20)
    r.click("investigate", INV_END, 30)
    held = {e["id"] for e in EV.values() if e["chapter"] == 2} - {"E02_05", "E02_08"}
    b = Board(r, drawer_of(2, held), appraised={"E02_01"})
    for card in ("E02_02", "E02_07"):
        b.select(card)
        b.appraise(card)
        b.correct(card)
    b.select("E02_03")
    b.correct("E02_03")
    b.place(0)
    b.select("E02_02")
    b.place(1)
    b.select("E02_04")
    b.wrong("E02_04")
    b.place(2)                                     # sophistry: E02_02 - E02_04 (wrong reason)
    b.select("E02_06")
    b.correct("E02_06")
    b.place(3, 30)                                 # invalid: E02_04 - E02_06 share nothing -> bounced
    b.place(5, BOUNCE_WAIT)
    b.select("E02_01")
    b.correct("E02_01")
    b.place(6)
    b.select("E02_07")
    b.place(7)
    b.debate(16)
    return r.write("ch2_case", 60)


# The shortest way through each chapter's investigation and board, for the story playthroughs
# (tests/gen_playthrough.py): the required spots (plus one card to chain with), end; one two-card chain with the
# right reasons, to the debate twice (the first press may only show the 「unappraised」 warning, 01-systems §2.7).
MINIMAL = {
    1: (["HS_CH01_02", "HS_CH01_07"], ["E01_01", "E01_03"]),
    2: (["HS_CH02_02", "HS_CH02_03", "HS_CH02_06"], ["E02_03", "E02_02"]),
    3: (["HS_CH03_02"], ["E03_02", "E03_05"]),
}


MINIMAL_LANG = "zh-TW"   # the language the story playthrough is replayed in (gen_playthrough.ch1_playthrough)


def minimal(r: gp.Recording, kind: str, chapter: int) -> None:
    """Inputs for an investigate or board step of a story playthrough (MINIMAL)."""
    spots, chain = MINIMAL[chapter]
    rr = Rec.__new__(Rec)
    rr.__dict__ = r.__dict__   # share the recording's lines and clock
    if kind == "investigate":
        investigate(rr, spots)
        rr.click("investigate", INV_END, FLY_WAIT)
        return
    held = {h["yields"] for h in load("hotspots") if h["id"] in spots}
    held |= {e["id"] for e in EV.values() if e["chapter"] == chapter and e["obtain"] == "event"}
    held |= {e["id"] for e in EV.values() if e["chapter"] == chapter and e["policeTags"]}   # trust 3: report
    b = Board(rr, drawer_of(chapter, held))
    b.lang = MINIMAL_LANG
    for slot, card in enumerate(chain):
        b.select(card)
        b.correct(card)     # a card without a reason links to nothing (01-systems §2.3)
        b.place(slot)
    b.debate(16)
    b.debate(16)


RECORDINGS = {"ch1_case": ch1, "ch2_case": ch2}


def main() -> int:
    ticks = {name: fn() for name, fn in RECORDINGS.items()}
    (TESTS / "case_ticks.json").write_text(json.dumps(ticks, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
