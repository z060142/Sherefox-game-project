"""The v2 demo D01's ending screens (4.4), imported by tools/gen_flows.py: flows/d01_end.xtflow (the UI d1result; the
S11 placeholder d1end needs no flow: its texts are string keys on the board and main handles its back to title).
See docs/flows.md §4.15 and docs/ui-contracts.md d1result.

Design: v2/11_demo_chapter.md §13 結算畫面 (the grade, one of five; the reputation changes item by item; the favour
changes; the truth score is never shown, it only picks Arthur's notes) and the hidden-value ruling of the v2 demo plan
(§2.4, ticket 4.4): no reputation total, no truth score or band. Every fact comes from the engine
(tools/gen_debate_v2.py, ref results.py / epilogue.py): d1Grade, d1Outcome, d1Round, d1EpRep (the reputation items'
names, in ref order), d1Cracks / d1Privates / d1Denials (the counts in the item labels), d1Fav<Who> (the favour
changes). The direction of each item (UI_V2_REP_UP / DOWN, no number: design string note) is the sign of its ref
constant (model.REP_*).

The result step (main, dialogue): its S08 lines play on the vn first; when they end, dialogue sends world.d1ResScreen
and main shows d1result. This flow writes the lists on that pulse (and again on a language change while the step is
on); the screen's 繼續 ends the step.
"""

from __future__ import annotations

import sys
from pathlib import Path

from gen_flows import Graph, lang_changed

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ref" / "src"))
sys.path.insert(0, str(ROOT / "tools"))
from sherefox_ref.v2 import model as M  # noqa: E402
import gen_debate_v2 as E  # noqa: E402

UI = "d1result"
P = f"ui#{UI}"
KIND = "d1result"

# reputation item (ref results.py names) -> (label key, count signal or None, its ref delta's sign > 0)
REP_GRADE_KEYS = {1: "UI_V2_REP_CLEAN", 2: "UI_V2_REP_HELD", 3: "UI_V2_REP_COUNTERED", 4: "UI_V2_REP_GRIND",
                  5: "UI_V2_REP_LOSS"}
REP_ITEMS = [(f"grade_{g}", k, None, M.REP_GRADE[g] > 0) for g, k in REP_GRADE_KEYS.items()] + [
    ("cracks", "UI_V2_REP_CRACKS", "world.d1Cracks", M.REP_PER_CRACK > 0),
    ("private", "UI_V2_REP_PRIVATE", "world.d1Privates", M.REP_PRIVATE > 0),
    ("psych_card", "UI_V2_REP_PSYCH", None, M.REP_PSYCH_CARD > 0),
    ("stalls", "UI_V2_REP_STALL", None, M.REP_STALLS > 0),
    ("denials", "UI_V2_REP_DENY", "world.d1Denials", M.REP_DENIAL > 0),
]
# favour: who -> the name plate key
FAV_NAMES = {"inspector": "SPK_INSPECTOR_BASKERVILLE", "mrs_hyde": "SPK_MRS_HYDE"}

SIGNALS = {"d1ResScreen": {"type": "pulse"}}   # dialogue -> main, d01_end: S08's lines are over, the result screen
COLLECTIONS = {
    "e1Rep": {"kind": "list", "type": "string", "capacity": 16},   # the reputation rows' labels (localized)
    "e1RepUp": {"kind": "map", "type": "number", "capacity": 16},  # label -> 1 up / 0 down
    "e1Fav": {"kind": "list", "type": "string", "capacity": 8},    # the favour rows (localized)
}


def _checks() -> None:
    names = [n for n, *_ in REP_ITEMS]
    if any(f"grade_{g}" not in names for g in M.REP_GRADE):
        raise SystemExit("gen_end_v2: a grade without a reputation label")
    missing = [w for w in E.FAV_WHO if w not in FAV_NAMES]
    if missing:
        raise SystemExit(f"gen_end_v2: no name plate for favour of {missing}")


def gen_d01end() -> Graph:
    _checks()
    g = Graph()
    isK = g.cmp("isResK", "world.stepKind", g.k(KIND))
    langP = g.when("langResG", lang_changed(g), isK)
    fill = g.merge("fillM", "world.d1ResScreen", langP)

    # the grade, the outcome, the rounds (live values)
    g.n("winN", g.cmp("isWin", "world.d1Outcome", g.k("win")))
    g.edge("winN", f"{P}.win")
    g.edge(g.text("gradeT", g.sel("gradeSel", g.cmp("gradeOn", "world.d1Grade", g.k(0), "gt"),
                                  g.fmt("gradeK", "UI_V2_GRADE_{a}", "world.d1Grade"), g.k(""))), f"{P}.grade_text")
    g.put("rnd", "world.d1Round")
    g.edge(g.textf("roundsT", key="UI_V2_RESULT_ROUNDS", n=g.x("roundsN", "rnd - 1")), f"{P}.rounds_text")

    # reputation rows: the engine's items in its order (ref results: grade, cracks, private, psych card, stalls,
    # denials), each its label (with its count) and direction; never a number or a total
    g.edge(fill, g.eff("repClr", "atrium.coll.clear", "e1Rep"))
    g.edge(fill, g.eff("repUpClr", "atrium.map.clear", "e1RepUp"))
    for i, (name, key, count, up) in enumerate(REP_ITEMS):
        has = g.contains(f"repHas{i}", "d1EpRep", g.k(name))
        lab = g.textf(f"repT{i}", key=key, n=count) if count else g.text(f"repT{i}", g.k(key))
        go = g.when(f"repG{i}", fill, has)
        g.edge(go, g.eff(f"repAdd{i}", "atrium.coll.add", "e1Rep", value=lab))
        g.edge(go, g.eff(f"repUp{i}", "atrium.map.set", "e1RepUp", key=lab, value=g.k(1 if up else 0)))
    g.edge(fill, g.ui_list("repList", f"ui.{UI}.rep", "e1Rep", {"label": "item", "up": "map:e1RepUp"}))

    # favour rows: who and the change (+1 / −1); nobody changed -> the empty mark
    g.edge(fill, g.eff("favClr", "atrium.coll.clear", "e1Fav"))
    ons = []
    for i, who in enumerate(E.FAV_WHO):
        v = g.put(f"fv{i}", f"world.{E.fav_signal(who)}")
        g.x(f"fvAbs{i}", f"abs(fv{i})")
        sign = g.sel(f"fvS{i}", g.cmp(f"fvPos{i}", v, g.k(0), "gt"), g.fmt(f"fvP{i}", "+{a}", f"fvAbs{i}"),
                     g.fmt(f"fvM{i}", "−{a}", f"fvAbs{i}"))
        line = g.textf(f"fvT{i}", key="UI_V2_FAVOR_LINE", name=g.text(f"fvN{i}", g.k(FAV_NAMES[who])), delta=sign)
        on = g.cmp(f"fvOn{i}", v, g.k(0), "ne")
        g.edge(g.when(f"fvG{i}", fill, on), g.eff(f"fvAdd{i}", "atrium.coll.add", "e1Fav", value=line))
        g.n(f"fvOnN{i}", on)
        ons.append(f"fvOnN{i}")
    g.edge(fill, g.ui_list("favList", f"ui.{UI}.fav", "e1Fav", {"text": "item"}))
    g.x("favOn", " || ".join(ons))
    g.edge("favOn_t", f"{P}.fav_on")

    # 繼續: the step is done (S09's paper follows)
    g.edge(g.when("nextG", f"{P}.next", isK), "world.stepDone")
    return g
