# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Write the v2 demo D01 chapter recording (M3: investigation, evidence list, notes, appraisal, carry screen, debate;
docs/flows.md §4.13, tests/README.md) and its harness.

tests/d1_m3.atrec clicks, from the title's v2 entry (chapter 101), through the story steps (S01 paper, S02 / S03 vn,
a clean warm-up: tests/gen_d1_story.py story()), then:
- the investigation: every place by its tab, every hotspot of it (data/d01/d1Hotspot.json), closing each note;
- the evidence list: appraise E01 and E04 (A01, A04: the two appraisals), the private view of E01 set to 01A, the
  notes page, close;
- end of the search -> the carry screen, Ask Arthur once (L008); back to the investigation (the appraisal count
  stays) and end again (a second visit, where Arthur may say L008 again); Ask Arthur with nothing chosen, then with P1, E12, E09, E03 chosen (seven presses: the S06 priority order, L012 repeating), then
  route A's nine (ref routes.py), a tenth click (no room), Ask Arthur once more, confirm (the list of what stays),
  yes (E6: no L010, route A carries everything he could pick up), a click on (lands nowhere);
- the debate: route A clicked the M2 way (tests/gen_d1_play.py), the opponent pinned by the harness; rounds 2 and 3
  play back without clicks (for the review screenshots).

tests/d1m3_harness: tests/gen_d1_play.py's route A harness (opponent moves pinned through the engine's test hook) plus
a flow that mirrors what reaches the debate's collections into world signals (t1c<item> d1Carry, t1a<id>
d1Appraised, t1n<id> d1Notes, t1pE01 the private view of E01), read with `xtatrium trace`.

Usage (from the project root):
    uv run tests/gen_d1_m3.py
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
import gen_d1_play as gd  # noqa: E402
import gen_d1_story as gs  # noqa: E402
from sherefox_ref.v2 import routes as RT  # noqa: E402

SPOTS = json.loads((ROOT / "data" / "d01" / "d1Hotspot.json").read_text(encoding="utf-8"))
SCENES = ["PARLOR", "STUDY", "BASEMENT", "ATTIC", "BEDROOM", "HALL"]
ITEMS = [f"E{n:02d}" for n in range(1, 13)] + ["P1"]          # the carry screen's rows (all found), data order
NOTES = ["PN1", "PN2", "PN3", "PN4", "OBS01"]
APPRS = ["A01", "A02", "A04"]
ROUTE_A = RT.ROUTES["A"].loadout
HARNESS = TESTS / "d1m3_harness"
NO_SKIP = {2, 3}           # debate rounds played back without clicks
ASK_LINES = ["L003", "L004", "L006", "L007", "L008", "L011", "L012"]   # S06 Ask Arthur lines

# board coordinates (1280x720; ui/boards/project/D1Inv, D1Book, D1Carry, Title)
TITLE_V2 = (404, 643)                                  # Title #btn-v2 (chapter 101)
SHADE = (60, 400)                                      # d1inv #pop-shade (only while a note is open)
BOOK_BTN, NOTES_BTN, END_BTN = (792, 678), (984, 678), (1176, 678)
TAB_EV, TAB_PN, BOOK_X = (214, 76), (442, 76), (1160, 76)
APPRAISE = (570, 300)
ASK, BACK, CONFIRM = (1080, 386), (1000, 543), (1156, 543)
YES, NO, ON = (861, 443), (685, 443), (640, 300)   # the carry confirm box's buttons (centre)


def loc_xy(i: int) -> tuple[int, int]:
    return 232 + i * 173 + 83, 38


def spot_xy(s: dict) -> tuple[int, int]:
    return s["x"] + s["w"] // 2, s["y"] + s["h"] // 2


def card_xy(i: int) -> tuple[int, int]:
    return 269, 116 + i * 40 + 18


def opt_xy(j: int) -> tuple[int, int]:
    return 818, 490 + j * 34 + 15


def item_xy(i: int) -> tuple[int, int]:
    return 400, 124 + i * 34 + 15


class Rec(gs.Rec):
    def mark(self, name: str, after: int = 4) -> None:
        self.marks[name] = self.t + after


def investigate(r: Rec) -> None:
    gs.story(r, gs.RUNS["clean"])   # the title's v2 entry, S01-S03 and a clean warm-up (M4a) -> the investigation
    for i, scene in enumerate(SCENES):
        if i:
            r.click("d1inv", loc_xy(i), 10)
        r.t += 20
        for s in [s for s in SPOTS if s["scene"] == scene]:
            r.click("d1inv", spot_xy(s), 10)
            r.mark(f"pop_{s['id']}", 8)
            r.t += 10
            r.click("d1inv", SHADE, 8)
        r.mark(f"scene_{scene}", 30)
        r.t += 40


def book(r: Rec) -> None:
    r.click("d1inv", BOOK_BTN, 10)
    r.mark("book_open", 20)
    r.t += 10
    r.click("d1book", card_xy(ITEMS.index("E01")), 10)
    r.click("d1book", APPRAISE, 10)
    r.mark("appr_A01", 10)
    r.click("d1book", card_xy(ITEMS.index("E04")), 12)
    r.click("d1book", APPRAISE, 10)
    r.mark("appr_A04", 10)
    r.click("d1book", card_xy(ITEMS.index("E02")), 12)
    r.mark("book_E02", 10)
    r.click("d1book", card_xy(ITEMS.index("E01")), 12)
    r.mark("book_E01", 10)
    r.click("d1book", opt_xy(1), 10)                 # "-", 01A, 01B, 01C, 01D -> 01A
    r.mark("note_E01", 10)
    r.t += 20
    r.click("d1book", TAB_PN, 10)
    r.mark("notes_page", 20)
    r.t += 30
    r.click("d1book", BOOK_X, 10)
    r.t += 10


def carry(r: Rec) -> list[tuple[str, str]]:
    """The carry screen; returns (mark, expected Ask Arthur line) for every press."""
    asks: list[tuple[str, str]] = []
    r.mark("before_carry", 0)
    r.click("d1inv", END_BTN, 10)
    r.mark("carry1", 20)
    r.t += 20
    r.click("d1carry", ASK, 10)          # ruling 4: Arthur's line on the first visit (L008) may come again on the next
    r.mark("ask_v1", 6)
    r.t += 6
    r.click("d1carry", BACK, 10)
    r.mark("back_inv", 10)
    r.t += 10
    r.click("d1inv", END_BTN, 10)
    r.mark("carry2", 20)
    r.t += 20

    def ask(want: str) -> None:
        r.click("d1carry", ASK, 10)
        r.mark(f"ask{len(asks)}", 6)
        asks.append((f"ask{len(asks)}", want))
    ask("L008")
    for e in ("P1", "E12", "E09", "E03"):
        r.click("d1carry", item_xy(ITEMS.index(e)), 10)
    r.t += 6
    for want in ("L004", "L003", "L006", "L007", "L011", "L012", "L012"):
        ask(want)
    r.mark("carry_board", 0)
    for e in ("P1", "E12", "E09", "E03"):
        r.click("d1carry", item_xy(ITEMS.index(e)), 10)
    for e in ROUTE_A.carried:
        r.click("d1carry", item_xy(ITEMS.index(e)), 10)
    r.mark("carry_nine", 8)
    r.click("d1carry", item_xy(ITEMS.index("E03")), 10)
    r.mark("carry_full", 6)
    ask("L012")
    r.click("d1carry", CONFIRM, 10)
    r.mark("confirm", 10)
    r.t += 20
    r.click("d1carry", YES, 10)
    r.mark("l010", 10)
    r.t += 20
    r.click("d1carry", ON, 10)
    r.mark("go", 2)
    r.t += 40
    return asks


def debate(r: Rec) -> None:
    """Route A clicked the M2 way; marks the picker right after the evidence of each claim is chosen."""
    rounds = gd.forced("A")
    gd.opening(r)             # S07 L001-L003 on the vn, then L004 (v2 demo 4.3)
    for n, (s, pa, _) in enumerate(rounds, start=1):
        act = gd.PA_ACT[pa.kind]
        r.click("d1debate", gd.ACT_XY[act], 12)
        if pa.claim is not None:
            pk = gd.picker(s)
            claim = f"CATCH:{s.catch_card}" if pa.claim == "CATCH" else pa.claim
            ev = "CATCH" if claim.startswith("CATCH") else s.ch.claims[claim].evidence
            i = [e for e, _ in pk].index(ev)
            r.click("d1debate", gd.ev_xy(i))
            r.mark(f"ev{n}", 6)
            r.click("d1debate", gd.claim_xy(pk[i][1].index(claim)))
        chain = [nd.card for nd in s.opp_chain]
        if pa.target in chain:
            r.click("d1debate", gd.chain_xy(chain.index(pa.target)))
        if pa.guard:
            r.click("d1debate", gd.GUARD_XY)
        r.marks[f"chosen{n}"] = r.t + 4
        r.click("d1debate", gd.LOCK_XY)
        r.marks[f"lock{n}"] = r.t
        if n in NO_SKIP:          # the playback runs at its own pace (screenshots of a full line and of a stamp)
            r.t += gd.NO_SKIP_WAIT
        else:
            for _ in range(gd.SKIPS):
                r.click("d1debate", gd.SKIP_XY, gd.SKIP_GAP)
        r.t += gd.ROUND_TAIL
    r.marks["end"] = r.t
    gd.outro(r, gd.outcome_of(rounds))     # S07 L012-L015 on the vn
    gd.epilogue(r, gd.final_state(rounds))  # 4.4: S08, the result screen (mark `over`), S09, S10, S11, back to title


def build_harness() -> None:
    """tests/d1m3_harness: gen_d1_play's route A harness (its loadout swap answers only the dev shortcut, unused
    here) plus the mirror flow t1mirror."""
    gd.build_harness("A")
    shutil.rmtree(HARNESS, ignore_errors=True)
    shutil.move(str(gd.harness_dir("A")), str(HARNESS))
    game = json.loads((HARNESS / "game.json").read_text(encoding="utf-8"))
    nodes, edges = [], []
    for coll, pre, ids in (("d1Carry", "t1c", ITEMS), ("d1Appraised", "t1a", APPRS), ("d1Notes", "t1n", NOTES)):
        for i in ids:
            nid = f"{pre}{i}"
            nodes.append({"id": nid, "type": "atrium.coll.contains", "params": {"name": coll}})
            nodes.append({"id": nid + "_k", "type": "constant", "params": {"value": i}})
            edges.append({"from": nid + "_k.out", "to": nid + ".value"})
            edges.append({"from": nid + ".has", "to": f"world.{nid}"})
            game["signals"][nid] = {"type": "bool", "initial": False}
    nodes.append({"id": "t1pE01", "type": "atrium.map.get", "params": {"name": "d1PrivNote"}})
    nodes.append({"id": "t1p_k", "type": "constant", "params": {"value": "E01"}})
    edges.append({"from": "t1p_k.out", "to": "t1pE01.key"})
    edges.append({"from": "t1pE01.value", "to": "world.t1pE01"})
    game["signals"]["t1pE01"] = {"type": "string", "initial": ""}
    (HARNESS / "flows" / "t1mirror.xtflow").write_text(json.dumps({"version": 1, "nodes": nodes, "edges": edges},
                                                                  indent=1) + "\n", encoding="utf-8", newline="\n")
    game["flows"].append("flows/t1mirror.xtflow")
    (HARNESS / "game.json").write_text(json.dumps(game, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
                                       newline="\n")


def main() -> int:
    build_harness()
    r = Rec("tests/d1m3_harness")
    investigate(r)
    book(r)
    asks = carry(r)
    debate(r)
    end = r.write("d1_m3", 60)
    (TESTS / "d1_m3_ticks.json").write_text(json.dumps({"ticks": end, "marks": r.marks, "asks": asks}, indent=1) + "\n",
                                            encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
