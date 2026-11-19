"""The v2 demo D01 warm-up against Inspector Baskerville (M4a), imported by tools/gen_flows.py: flows/d01_warmup.xtflow
(the UI d1warm). See docs/flows.md §4.14 and docs/ui-contracts.md d1warm.

Design: v2/11_demo_chapter.md §2 S04 (L001-L015) and §3.2 (OBS_D01_W1-W3); the rule is the reference model's
(ref/src/sherefox_ref/v2/warmup.py, data d01_extra.json warmup_play): three points in order (L002, L006, L009); a pick
of the right observation (W1, W2, W3 for points 1-3) plays Sherefox's line and his concession, any other pick (an
observation already used correctly included) plays L005 and asks the same point again; the third mistake plays L014,
L015 instead; success L012, plus L013 with no mistake. world.d1Warmup = pass_clean / pass / fail is written when the
outcome is decided (the investigation reads its appraisal count from it).

The screen is a sequence of S04 lines, one per click, held as a number n (the line SCR_D01_S04_L<n>) in the map `w1`
with the point index pt (0-2) and the mistakes mis; n = 2, 6, 9 (a point) waits for a pick instead of a click. The
next n is an expression of (n, pt, mis); n = 0 ends the step. Same rules as gen_flows: the map is read back on the next
tick (a click never comes in the tick its line was written).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from gen_flows import Graph
from gen_debui import setter, truth

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ref" / "src"))
from sherefox_ref.v2.warmup import PLAY  # noqa: E402

UI = "d1warm"
P = f"ui#{UI}"
KIND = "d1warmup"


def num(short: str) -> int:
    return int(short[1:])


POINTS = [num(p["line"]) for p in PLAY["points"]]                 # 2, 6, 9
ANSWERS = [PLAY["observations"].index(p["answer"]) + 1 for p in PLAY["points"]]   # pick 1-3 per point
REPLY = [[num(x) for x in p["reply"]] for p in PLAY["points"]]    # (3, 4), (7, 8), (10, 11)
WRONG = num(PLAY["wrong"][0])                                      # 5
SUCCESS, CLEAN = num(PLAY["success"][0]), num(PLAY["clean"][0])    # 12, 13
FAIL = [num(x) for x in PLAY["failure"]]                            # 14, 15
OPEN = num(PLAY["opening"][0])                                     # 1
MAX_WRONG = PLAY["max_wrong"]
N_LINES = 15


def _checks() -> None:
    if ANSWERS != [1, 2, 3] or len(PLAY["wrong"]) != 1 or len(PLAY["success"]) != 1 or len(PLAY["clean"]) != 1 \
            or len(PLAY["failure"]) != 2 or any(len(r) != 2 for r in REPLY):
        raise SystemExit("warmup_play: the flow is written for three points answered W1, W2, W3, two reply lines each, "
                         "one wrong / success / clean line and two failure lines")


SIGNALS: dict = {}
COLLECTIONS = {"w1": {"kind": "map", "type": "number", "capacity": 4}}


def gen_d01warm() -> Graph:
    _checks()
    g = Graph()
    T = truth(g)
    seti = setter(g, "w1")
    for k in ("n", "pt", "mis"):
        g.mget(k, "w1", g.k(k))
    isK = g.cmp("isWarmK", "world.stepKind", g.k(KIND))
    g.n("isWarmN", isK)

    # the step begins: L001, point 1, no mistakes
    begin = g.when("begin", "world.stepBegin", isK)
    # a click on a line that is not a point: the next line (0 = the end)
    p2, p6, p9 = POINTS
    g.x("choosing", f"n == {p2} || n == {p6} || n == {p9}")
    nxt = " : ".join([
        f"n == {OPEN} ? {p2}",
        f"n == {REPLY[0][0]} ? {REPLY[0][1]}", f"n == {REPLY[0][1]} ? {p6}",
        f"n == {REPLY[1][0]} ? {REPLY[1][1]}", f"n == {REPLY[1][1]} ? {p9}",
        f"n == {REPLY[2][0]} ? {REPLY[2][1]}", f"n == {REPLY[2][1]} ? {SUCCESS}",
        f"n == {WRONG} ? (pt == 0 ? {p2} : pt == 1 ? {p6} : {p9})",
        f"n == {SUCCESS} ? (mis == 0 ? {CLEAN} : 0)",
        f"n == {FAIL[0]} ? {FAIL[1]}",
        "0"])
    g.x("nextN", nxt)
    adv = g.when("advG", g.when("advK", f"{P}.advance", isK), T("advOk", "n > 0 && !choosing"))
    show_next = g.when("showNextG", adv, T("nextOk", "nextN > 0"))
    g.edge(g.when("doneG", adv, T("nextEnd", "nextN == 0")), "world.stepDone")
    g.x("nextPt", f"nextN == {p6} ? 1 : nextN == {p9} ? 2 : pt")
    seti(show_next, "pt", "nextPt")
    seti(show_next, "n", "nextN")
    # a pick while a point waits: the right observation -> the reply; else a mistake (L005, or L014 on the third)
    pick = g.put("pick", f"{P}.pick")
    pk = g.when("pickG", g.when("pickK", f"{P}.pick.emitted", isK), "choosing_t")
    g.x("right", "pick == pt + 1")
    g.x("misN", "right ? mis : mis + 1")
    g.x("pickN", f"right ? (pt == 0 ? {REPLY[0][0]} : pt == 1 ? {REPLY[1][0]} : {REPLY[2][0]}) : "
                 f"(misN >= {MAX_WRONG} ? {FAIL[0]} : {WRONG})")
    seti(pk, "mis", "misN")
    seti(pk, "n", "pickN")
    # the outcome, when it is decided: the last point answered, or the last mistake
    g.x("passNow", f"right && pt == 2")
    g.x("failNow", f"!right && misN >= {MAX_WRONG}")
    g.x("outNow", "passNow || failNow")
    out = g.sel("outV", "failNow_t", g.k("fail"), g.sel("outP", T("cleanNow", "mis == 0"), g.k("pass_clean"),
                                                         g.k("pass")))
    g.edge(g.latch("outL", out, g.when("outG", pk, "outNow_t")), "world.d1Warmup")
    seti(begin, "n", g.k(OPEN))
    seti(begin, "pt", g.k(0))
    seti(begin, "mis", g.k(0))
    g.counter("lineSeq", initial=0)
    g.edge(g.merge("seqM", begin, show_next, pk), "lineSeq.increment")

    # the screen
    keys = [""] + [f"SCR_D01_S04_L{i:03d}" for i in range(1, N_LINES + 1)]
    g.lookup("lnKey", keys, "n")
    srow = g.tfind("lnRow", "script", "id", "lnKey")
    g.tget("lnSpk", "script", "speaker", srow)
    g.edge(g.text("lineT", "lnKey"), f"{P}.line")
    g.edge(g.sel("spkV", g.cmp("isSys", "lnSpk", g.k("SPK_SYSTEM"), "ne"), g.text("spkT", "lnSpk"), g.k("")),
           f"{P}.speaker")
    g.n("isShfN", g.cmp("isShf", "lnSpk", g.k("SPK_SHEREFOX")))
    g.n("isInsN", g.cmp("isIns", "lnSpk", g.k("SPK_INSPECTOR_BASKERVILLE")))
    g.edge(g.x("focusV", "isShfN ? 1 : isInsN ? 3 : 0"), f"{P}.focus")
    g.edge("lineSeq.value", f"{P}.line_seq")
    g.edge("choosing_t", f"{P}.choosing")
    g.lookup("ptKey", [f"SCR_D01_S04_L{p:03d}" for p in POINTS], "pt")
    g.edge(g.sel("pointV", T("pointOn", f"n != {OPEN}"), g.text("pointT", "ptKey"), g.k("")), f"{P}.point")
    g.edge(g.textf("missT", key="UI_WARMUP_MISS", n="mis"), f"{P}.miss_text")
    g.edge(g.text("titleT", g.k("SCR_D01_S04_TITLE")), f"{P}.title")
    for i, o in enumerate(PLAY["observations"], start=1):
        g.edge(g.text(f"obs{i}T", g.k(f"OBS_D01_{o}")), f"{P}.obs{i}")
    return g
