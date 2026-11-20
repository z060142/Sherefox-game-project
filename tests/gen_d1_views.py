# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Write the v2 demo D01 click-probe recording (tests/check_d1_views.py, tests/README.md): every clickable row of the
D01 lists clicked at several points (centre, near its left and right ends, near its top and bottom edges), with what
each click must select, and the private views (私下的看法) of the evidence list kept per evidence.

tests/d1_views.atrec plays, on tests/d1views_harness (tests/gen_d1_play.py's route A harness: the opponent pinned, so
the debate rounds are known):
- the story (tests/gen_d1_story.py story(), the clean warm-up) and every hotspot (tests/gen_d1_m3.py investigate());
- the place tabs: each tab at five points;
- the evidence list: each entry at five points; then, before any appraisal, every private-view row of every evidence
  at five points; then each evidence's planned view (PLAN_1) and a visit to each evidence (each keeps its own view);
- stray clicks inside the list (the entry column below the entries, the description, the heading, the gaps between the
  rows, the tab strip) and the pointer moved over the rows: nothing chosen changes;
- the two appraisals (E01, E04): the views stay, the rows they unlock are clicked at five points, PLAN_2 is set;
- E08's view changed twice and cleared;
- the notes tab and back, close and reopen, the language switched (settings) and back, the carry screen (every row
  at five points, taken and put down again) and Back: after each, a visit to each evidence;
- the carry screen again, route A's nine, confirm, the debate: Argue, every evidence chip at five points (the claim
  picker starts on the evidence's private view when it is in the picker), every claim row at five points; route A
  played to round 7, where his chain has two links: Dismantle and each chip at five points.

Every expectation is written to tests/d1_views_ticks.json ("checks": tick, kind, what to compare). The warm-up's
observation cards are probed by tests/check_d1_views.py with recordings of their own (warm_variants()).

Usage (from the project root):
    uv run tests/gen_d1_views.py
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
from gen_playthrough import KEY_ESC, KEY_F1, SET_LANG, key  # noqa: E402

HARNESS = TESTS / "d1views_harness"
GAME = "tests/d1views_harness"
CLAIMS = [r for r in json.loads((ROOT / "data" / "flow" / "d1iClaim.json").read_text(encoding="utf-8"))
          if r["evidence"] in gm.ITEMS]
ROUTE = "A"
CARRIED = list(gm.ROUTE_A.carried)
SETTLE = 30
# the views set before the appraisals (PLAN_1) and after them (PLAN_2: E01 and E04 move to a claim an appraisal
# unlocked; E08 is then changed twice and cleared, CLEAR)
PLAN_1 = {"E01": "01D", "E02": "02C", "E03": "03B", "E04": "04C", "E05": "05B", "E06": "06A", "E07": "07B",
          "E08": "08A", "E09": "09A", "E10": "10B", "E11": "11A", "E12": "12A", "P1": "P1B"}
PLAN_2 = dict(PLAN_1, E01="01C", E04="04B")
CLEAR = "E08"
ROUND_TARGET = 7          # route A's round whose state has two links on his chain


def rows(e: str, appraised: set[str]) -> list[str]:
    """The private-view rows of evidence `e` (gen_inv_v2: "-", then its claims unlocked now; every note is found)."""
    return ["-"] + [c["id"] for c in CLAIMS if c["evidence"] == e
                    and (c["unlock"] == "" or c["unlock"] in gm.NOTES or c["unlock"] in appraised)]


def five(x0: int, y0: int, w: int, h: int, inset: int = 2) -> dict[str, tuple[int, int]]:
    """Centre, near the left / right ends, near the top / bottom edges of the box x0, y0, w, h (board pixels)."""
    cx, cy = x0 + w // 2, y0 + h // 2
    return {"centre": (cx, cy), "left": (x0 + inset, cy), "right": (x0 + w - 1 - inset, cy),
            "top": (cx, y0 + inset), "bottom": (cx, y0 + h - 1 - inset)}


# board geometry (1280x720, as drawn: a box's children start inside its border, so D1Book's #book (2 px border)
# moves its rows 2 px right and down, D1Carry's #sheet (4 px top border) 4 px down, D1Debate's .paper boxes (3 px top
# border) 3 px down): D1Inv #locs, D1Book #cards / #opts, D1Carry #items, D1Debate #evs / #cls / #ochain, D1Warm
# #obs-1..3
def tab_box(i: int):
    return 232 + 173 * i, 10, 167, 56


def card_box(i: int):
    return 106, 118 + 40 * i, 330, 36


def opt_box(j: int):
    return 462, 492 + 34 * j, 716, 30


def item_box(i: int):
    return 56, 128 + 34 * i, 812, 31


def ev_box(i: int):
    return 20, 191 + 22 * i, 184, 20


def claim_box(j: int):
    return 218, 191 + 52 * j, 318, 48


def chip_box(k: int):
    return 20 + 112 * k, 83, 106, 68


def obs_box(i: int):
    return 300 + 232 * i, 288, 216, 184


PICK_CLIP = 403           # the claim picker's lists end at y 403 (a row past it is clipped)


class Rec(gm.Rec):
    def __init__(self, game: str) -> None:
        super().__init__(game)
        self.checks: list[dict] = []

    def expect(self, kind: str, what: str, after: int = 8, **kw) -> None:
        self.checks.append({"t": self.t + after, "kind": kind, "what": what, **kw})


class Views:
    """The private views as they must be: evidence -> claim ("" none)."""

    def __init__(self) -> None:
        self.v = {e: "" for e in gm.ITEMS}
        self.appraised: set[str] = set()
        self.card = ""

    def card_click(self, r: Rec, e: str, xy=None, what: str = "") -> None:
        r.click("d1book", xy or gm.card_xy(gm.ITEMS.index(e)), 12)
        self.card = e
        r.expect("cards", what or f"entry {e}", sel=[e])
        self.expect_opts(r, what or f"entry {e}")

    def expect_opts(self, r: Rec, what: str, after: int = 8) -> None:
        e = self.card
        r.expect("opts", what, after, rows=rows(e, self.appraised), sel=[self.v[e] or "-"], card=e)

    def pick(self, r: Rec, e: str, cid: str, point: str = "centre", what: str = "") -> None:
        assert self.card == e
        j = rows(e, self.appraised).index(cid)
        r.click("d1book", five(*opt_box(j))[point], 10)
        self.v[e] = "" if cid == "-" else cid
        self.expect_opts(r, what or f"{e} row {j} ({cid}) at {point}")

    def visit_all(self, r: Rec, when: str) -> None:
        for e in gm.ITEMS:
            self.card_click(r, e, what=f"{when}: {e}'s view")


def place_tabs(r: Rec) -> None:
    for i, scene in enumerate(gm.SCENES):
        for point, xy in five(*tab_box(i)).items():
            r.click("d1inv", xy, 12)
            r.expect("locs", f"place tab {scene} at {point}", sel=[scene])
    r.click("d1inv", gm.loc_xy(0), 12)
    r.t += 20


def book(r: Rec, vw: Views) -> None:
    r.click("d1inv", gm.BOOK_BTN, 10)
    r.t += 20
    vw.card = gm.ITEMS[0]
    # the entries, each at five points
    for i, e in enumerate(gm.ITEMS):
        for point, xy in five(*card_box(i)).items():
            vw.card_click(r, e, xy, f"entry {e} at {point}")
    # every row of every evidence at five points, before any appraisal
    for e in gm.ITEMS:
        vw.card_click(r, e)
        for cid in rows(e, vw.appraised):
            for point in five(*opt_box(0)):
                vw.pick(r, e, cid, point)
    for e in gm.ITEMS:
        vw.card_click(r, e)
        vw.pick(r, e, PLAN_1[e], what=f"plan: {e} -> {PLAN_1[e]}")
    vw.visit_all(r, "views on every evidence")
    # stray clicks and the pointer over the rows: nothing chosen changes
    vw.card_click(r, "E06")
    n = len(rows("E06", vw.appraised))
    strays = {"below the entries": (269, 652), "the description": (818, 200), "the heading": (818, 480),
              "the remark area": (818, 300), "the tab strip": (700, 76), "the evidence kind": (600, 125)}
    strays |= {f"the gap under row {j}": (818, 492 + 34 * j + 32) for j in range(n)}
    strays |= {"below the last row": (818, 492 + 34 * n + 10)}
    for what, xy in strays.items():
        r.click("d1book", xy, 10)
        vw.expect_opts(r, f"stray click on {what}")
    for j in range(n):
        r.hover("d1book", five(*opt_box(j))["centre"], 6)
    r.hover("d1book", (269, 652), 6)
    vw.expect_opts(r, "the pointer over the rows")
    vw.visit_all(r, "after the stray clicks")
    # the appraisals: the views stay; the rows they unlock
    for e in ("E01", "E04"):
        vw.card_click(r, e)
        r.click("d1book", gm.APPRAISE, 10)
        vw.appraised.add({"E01": "A01", "E04": "A04"}[e])
        vw.expect_opts(r, f"{e} appraised: its view stays", after=10)
        r.t += 10
    vw.visit_all(r, "after the appraisals")
    for e in ("E01", "E04"):
        vw.card_click(r, e)
        for cid in rows(e, vw.appraised):
            for point in five(*opt_box(0)):
                vw.pick(r, e, cid, point, f"appraised {e} row {cid} at {point}")
        vw.pick(r, e, PLAN_2[e], what=f"plan: {e} -> {PLAN_2[e]}")
    # change twice and clear
    vw.card_click(r, CLEAR)
    for cid in ("08B", "08A", "-"):
        vw.pick(r, CLEAR, cid, what=f"{CLEAR} changed to {cid}")
    vw.visit_all(r, "after the change and the clear")
    # the notes tab and back
    r.click("d1book", gm.TAB_PN, 12)
    r.t += 20
    r.click("d1book", gm.TAB_EV, 12)
    vw.expect_opts(r, "back from the notes tab")
    vw.visit_all(r, "after the notes tab")
    # close and reopen
    r.click("d1book", gm.BOOK_X, 12)
    r.t += 20
    r.click("d1inv", gm.BOOK_BTN, 12)
    r.t += 20
    vw.expect_opts(r, "reopened")
    vw.visit_all(r, "after close and reopen")
    # the language switched and back (settings over the list)
    for lang in (1, 0):
        r.at(12, key("d1book", KEY_F1))
        r.t += SETTLE
        r.click("settings", SET_LANG[lang], 10)
        r.t += 10
        r.at(10, key("settings", KEY_ESC))
        r.t += SETTLE
        vw.expect_opts(r, f"after the language switch {('zh-TW', 'en')[lang]}")
        vw.visit_all(r, f"after the language switch {('zh-TW', 'en')[lang]}")
    r.click("d1book", gm.BOOK_X, 12)
    r.t += 20


def carry_probe(r: Rec, vw: Views) -> None:
    r.click("d1inv", gm.END_BTN, 10)
    r.t += 30
    for i, it in enumerate(gm.ITEMS):
        for point, xy in five(*item_box(i)).items():
            r.click("d1carry", xy, 10)
            r.expect("carry", f"carry row {it} at {point}: taken", sel=[it])
            r.click("d1carry", xy, 10)
            r.expect("carry", f"carry row {it} at {point}: put down", sel=[])
    r.click("d1carry", gm.BACK, 10)
    r.t += 30
    r.click("d1inv", gm.BOOK_BTN, 12)
    r.t += 20
    vw.expect_opts(r, "after the carry screen's Back")
    vw.visit_all(r, "after the carry screen's Back")
    r.click("d1book", gm.BOOK_X, 12)
    r.t += 20


def to_debate(r: Rec) -> None:
    r.click("d1inv", gm.END_BTN, 10)
    r.t += 30
    for e in CARRIED:
        r.click("d1carry", gm.item_xy(gm.ITEMS.index(e)), 10)
    r.expect("carry", "route A's nine", sel=sorted(CARRIED, key=gm.ITEMS.index))
    r.click("d1carry", gm.CONFIRM, 10)
    r.t += 20
    r.click("d1carry", gm.YES, 10)
    r.t += 20
    r.click("d1carry", gm.ON, 10)
    r.t += 40
    gd.opening(r)


def ev_points(i: int) -> dict[str, tuple[int, int]]:
    pts = five(*ev_box(i))
    return {k: xy for k, xy in pts.items() if xy[1] < PICK_CLIP}


def debate(r: Rec, vw: Views) -> None:
    rounds = gd.forced(ROUTE)
    s0 = rounds[0][0]
    pk = gd.picker(s0)
    r.click("d1debate", gd.ACT_XY[1], 12)
    first = pk[0][0]
    pre = vw.v[first] if vw.v[first] in pk[0][1] else ""
    r.expect("claims", f"Argue: the picker starts on {first}'s view", sel=[pre] if pre else [], ev=first)
    for i, (ev, cls) in enumerate(pk):
        pre = vw.v[ev] if vw.v[ev] in cls else ""
        for point, xy in ev_points(i).items():
            r.click("d1debate", xy, 12)
            r.expect("evs", f"chip {ev} at {point}", sel=[ev])
            r.expect("claims", f"chip {ev} at {point}: the picker starts on its view {pre or '(none)'}",
                     sel=[pre] if pre else [], ev=ev)
        for j, c in enumerate(cls):
            for point, xy in five(*claim_box(j)).items():
                if xy[1] >= PICK_CLIP:
                    continue
                r.click("d1debate", xy, 12)
                r.expect("claims", f"{ev} claim {c} at {point}", sel=[c], ev=ev)
    # route A to round ROUND_TARGET (gen_d1_m3 debate(): the M2 way, playback skipped)
    for n, (s, pa, _) in enumerate(rounds[:ROUND_TARGET - 1], start=1):
        r.round(s, pa, n)
    s = rounds[ROUND_TARGET - 1][0]
    chain = [nd.card for nd in s.opp_chain]
    r.click("d1debate", gd.ACT_XY[3], 12)
    for k, card in enumerate(chain):
        for point, xy in five(*chip_box(k)).items():
            r.click("d1debate", xy, 12)
            r.expect("chain", f"round {ROUND_TARGET}: his link {card} at {point}", sel=[card])
    r.t += 30


def build_harness() -> None:
    gd.build_harness(ROUTE)
    shutil.rmtree(HARNESS, ignore_errors=True)
    shutil.move(str(gd.harness_dir(ROUTE)), str(HARNESS))


def warm_variants() -> dict[str, tuple[gs.Rec, int]]:
    """The clean warm-up with the observation cards clicked at each of the five points (gen_d1_story.OBS: the card
    centres); check_d1_views compares each run's warm-up with the centre's. Not written: the check writes them."""
    out = {}
    for point in five(*obs_box(0)):
        saved = dict(gs.OBS)
        try:
            for i, w in enumerate(("W1", "W2", "W3")):
                gs.OBS[w] = five(*obs_box(i))[point]
            r = gs.Rec(".")
            gs.story(r, gs.RUNS["clean"])
            out[point] = (r, r.t + 30)
        finally:
            gs.OBS.update(saved)
    return out


def main() -> int:
    build_harness()
    r = Rec(GAME)
    vw = Views()
    gm.investigate(r)
    place_tabs(r)
    book(r, vw)
    carry_probe(r, vw)
    final = dict(vw.v)
    to_debate(r)
    debate(r, vw)
    end = r.write("d1_views", 30)
    (TESTS / "d1_views_ticks.json").write_text(json.dumps({"ticks": end, "views": final, "checks": r.checks},
                                                          ensure_ascii=False, indent=0) + "\n",
                                               encoding="utf-8", newline="\n")
    print(f"d1_views: {end} ticks, {len(r.checks)} checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
