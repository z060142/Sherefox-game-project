"""v2 demo chapter: the four worked routes of 11_demo_chapter.md §12 as golden traces.

Per route and round: both credibility values (to 0.01), combo, 破竹, the three psych
values, states, crack count where the table states it, and whether the opponent policy
could have produced the stated move and tell. xfail = the chapter differs from the rules
(reason given); the model keeps the rules-correct value.
"""

from copy import deepcopy

import pytest

from sherefox_ref.v2.model import OA
from sherefox_ref.v2.resolve import resolve_round
from sherefox_ref.v2.results import compute
from sherefox_ref.v2.routes import ROUTES, replay

TOL = 0.01

# round: (opp_hp, player_hp, combo, hachiku, psych P/G/A, extra state checks)
#   extra: brk=N -> 破防 through round N; brk=0 -> not broken going into the next round;
#          sh -> 失守; over -> stats over threshold; c -> crack count
EXPECTED = {
    "A": {  # ch §12.1
        1: (210, 140, 0, 1, (20, 20, 10), dict(brk=2, sh=False, over="")),
        2: (198.5, 140, 1, 2, (17, 19, 6), dict(brk=0, sh=False, over="")),
        3: (180.5, 124, 2, 2, (4, 18, 0), dict(brk=0, over="")),
        4: (160.5, 124, 2, 3, (21, 27, 0), dict(brk=5, over="")),
        5: (136.25, 124, 3, 3, (18, 26, 0), dict(brk=0)),
        6: (103.49, 108, 4, 3, (5, 25, 0), dict(brk=0, rule3=True)),
        7: (73.49, 108, 4, 3, (22, 34, 0), dict(brk=8)),
        8: (1, 108, 5, 3, (19, 33, 0), dict(c=0)),
        9: (None, 108, None, None, None, {}),
    },
    "B": {  # ch §12.2
        1: (214, 124, 1, 0, (10, 45, 2), dict(brk=0, over="", c=0)),
        2: (209, 124, 1, 1, (15, 44, 27), dict(brk=3, next_clear=True)),
        3: (184.25, 104, 2, 1, (7, 58, 15), dict(brk=0, over="")),
        4: (160.49, 104, 3, 1, (0, 72, 3), dict(brk=5, over="G")),
        5: (1, 76, 4, 1, None, dict(c=0)),
    },
    "C": {  # ch §12.3
        1: (210, 140, 0, 1, (12, 10, 22), dict(brk=2, c=1)),
        2: (205, 140, 0, 2, (17, 9, 45), dict(brk=3, next_clear=True, c=1)),
        3: (185, 140, 0, 3, (19, 8, 61), dict(brk=4, over="A", c=2)),
        4: (1, 140, 0, 3, (36, 17, 57), dict(over="A", c=2)),
        5: (55.2, 100, 0, 0, (23, 16, 45), dict(over="")),
        6: (43.2, 80, 1, 0, (20, 15, 48), {}),
        7: (13.2, 70, 1, 1, (37, 24, 44), dict(brk=8, c=3)),
        8: (0, 70, 2, 1, None, {}),
    },
    "D": {  # ch §12.4
        1: (210, 140, 0, 1, (20, 20, 10), dict(brk=2, sh=False)),
        2: (198.5, 140, 1, 2, (17, 19, 6), dict(brk=0, sh=False)),
        3: (198.5, 130, 1, 0, (4, 18, 0), dict(sh=False)),
        4: (198.5, 115, 0, 0, (0, 17, 0), dict(sh=True, known="said:鎖匠昨晚回來過")),
        5: (186.5, 90, 1, 0, (0, 16, 0), dict(sh=True)),
        6: (168.5, 60, 2, 0, (0, 15, 0), dict(sh=True)),
        7: (150.5, 1, 3, 0, (0, 14, 0), dict(sh=True, locked=True)),
        8: (None, 0, None, None, None, {}),
    },
}

RED_06A = ("ch §12.3 R4 omits the red crack: 06A is exclusive with 06C (ch §7, debate_data "
           "06A.exclusive), said in R3; rules §3.4 charge −10 and a crack (c = 3), so the last "
           "card hits for 55 and heals 36%; every later HP value shifts")
FEW = ("ch §12.3 R6 omits 選項所剩無幾 (§5.2/§8.2, ch §10: pressure −10, once): after F2 "
       "lands his usable cards are L4 and L3 (2 <= 2)")
HACHIKU_C8 = ("ch §12.3 R8 keeps 破竹 1, but 10A lands while he stalls: a correct read that "
              "adds a layer (§7.2, as ch §12.1 R2 does) -> 2")
COMBO_REV = ("ch §12.4 R7 shows combo 3 after the reverse ronpa; §5.1 resets the player's combo "
             "when 被論破")
STAR = ("★ on the decoy: ch §11 marks the rule's action even when it is the decoy; the "
        "design-owner ruling marks only the true action")
RULE5 = "rule ⑤ (ch §11, 必定): 立論 twice in a row, so a third 立論 is not available"
DECOY5 = ("decoy 立論 is unavailable (rule ⑤ after 立論 R3, R4); ruling: the decoy is drawn from "
          "the actions available that round")

XFAIL = {
    ("A", 5, "policy"): DECOY5,
    ("B", 5, "policy"): RULE5 + " (R3 F1, R4 U1)",
    ("C", 4, "hp"): RED_06A,
    ("C", 4, "state"): RED_06A,
    ("C", 5, "hp"): RED_06A,
    ("C", 6, "hp"): RED_06A,
    ("C", 6, "psych"): FEW,
    ("C", 7, "hp"): RED_06A,
    ("C", 7, "psych"): FEW,
    ("C", 7, "state"): RED_06A + " (c = 4 after R7)",
    ("C", 7, "policy"): STAR + " (ch §12.3 R7: true 強辯, ★ 立論)",
    ("C", 8, "hp"): RED_06A + " (he is at 21.05, not 0)",
    ("C", 8, "hachiku"): HACHIKU_C8,
    ("D", 4, "policy"): STAR + " (ch §12.4 R4: true 反駁, ★ 立論)",
    ("D", 7, "policy"): RULE5 + " (R5 L2, R6 F2)",
    ("D", 7, "combo"): COMBO_REV,
}
FINAL_XFAIL = {"C": RED_06A + "; the debate is still running after R8"}

_REPLAYS = {}


def _rp(name):
    if name not in _REPLAYS:
        _REPLAYS[name] = replay(name)
    return _REPLAYS[name]


def _cases():
    for route, rows in EXPECTED.items():
        for rnd in rows:
            for field in ("hp", "combo", "hachiku", "psych", "state", "policy"):
                reason = XFAIL.get((route, rnd, field))
                marks = [pytest.mark.xfail(reason=reason, strict=True)] if reason else []
                yield pytest.param(route, rnd, field, id=f"{route}-R{rnd}-{field}", marks=marks)


def check_row(s, row, field, producible=None):
    opp_hp, me_hp, combo, hachiku, psych, extra = row
    if field == "hp":
        if opp_hp is not None:
            assert s.opp_hp == pytest.approx(opp_hp, abs=TOL)
        assert s.player_hp == pytest.approx(me_hp, abs=TOL)
    elif field == "combo":
        if combo is not None:
            assert s.player_combo == combo
    elif field == "hachiku":
        if hachiku is not None:
            assert s.hachiku == hachiku
    elif field == "psych":
        if psych is not None:
            assert list(s.psych_end) == pytest.approx(list(psych), abs=TOL)
    elif field == "state":
        r = s.round - 1
        if "brk" in extra:
            if extra["brk"]:
                assert s.broken_until == extra["brk"]
            else:
                assert s.broken_until <= r
        if "sh" in extra:
            assert s.shisshu == extra["sh"]
        if "over" in extra:
            assert "".join(x for x, o in zip("PGA", s.over) if o) == extra["over"]
        if "c" in extra:
            assert s.cracks == extra["c"]
        if "next_clear" in extra:
            assert s.next_clear == extra["next_clear"]
        if "rule3" in extra:
            assert s.rule3_pending == extra["rule3"]
        if "known" in extra:
            assert extra["known"] in s.known
        if "locked" in extra:
            assert s.player_locked == extra["locked"]
    elif field == "policy":
        assert producible is not False


@pytest.mark.parametrize("route,rnd,field", list(_cases()))
def test_route_round(route, rnd, field):
    rp = _rp(route)
    assert len(rp.states) > rnd, "route ended early"
    check_row(rp.states[rnd], EXPECTED[route][rnd], field, rp.producible[rnd])


# ---------------------------------------------------------------------------- final results

FINAL = {
    # grade, rounds, player hp, truth %, reputation items, reputation after, next start hp, favour
    "A": (1, 9, 108, 100, {"grade_1": 6}, 56, 1.2, {}),
    "B": (1, 5, 76, 85, {"grade_1": 6, "psych_card": -2}, 54, 0.8, {}),
    "C": (3, 8, 70, 50, {"grade_3": 3, "cracks": -3, "private": -3, "denials": -2}, 45, -1.0,
          {"mrs_hyde": -1}),
    "D": (5, 8, 0, 60, {"grade_5": -4}, 46, -0.8, {"inspector": -1}),
}


def _final_cases():
    for r in FINAL:
        marks = [pytest.mark.xfail(reason=FINAL_XFAIL[r], strict=True)] if r in FINAL_XFAIL else []
        yield pytest.param(r, id=r, marks=marks)


@pytest.mark.parametrize("route", list(_final_cases()))
def test_route_result(route):
    s = _rp(route).states[-1]
    assert s.outcome is not None
    grade, rounds, hp, truth, rep, rep_after, next_hp, favour = FINAL[route]
    res = compute(s)
    assert res.grade == grade
    assert res.outcome == ("loss" if grade == 5 else "win")
    assert res.rounds == rounds
    assert res.player_hp == pytest.approx(hp, abs=TOL)
    assert res.truth == truth
    assert dict(res.reputation) == rep
    assert res.reputation_after == rep_after
    assert res.next_start_hp == pytest.approx(next_hp, abs=1e-9)
    assert dict(res.favour) == favour


def test_route_endings():
    a, b, d = _rp("A").states[-1], _rp("B").states[-1], _rp("D").states[-1]
    assert a.end_reason == "dying_cut" and a.ronpa_done and not a.reversed
    assert b.end_reason == "surrender" and b.over[1]
    assert d.end_reason == "last_stand_failed"
    assert compute(a).note_version == "full" and compute(a).newspaper == "decent"
    assert compute(d).note_version == "half" and compute(d).newspaper == "ugly"


# ---------------------------------------------------------------------------- route C what-if

def test_route_c_without_the_06a_red_crack():
    """Route C from R5 on, starting from the state the chapter assumed after R4 (no red
    crack: 140 HP, c = 2). Everything then matches the chapter except the two slips
    already listed (few options in R6/R7, 破竹 in R8)."""
    route = ROUTES["C"]
    s = deepcopy(_rp("C").states[4])
    s.player_hp, s.cracks = 140.0, 2
    rows = EXPECTED["C"]
    for i in range(5, 9):
        pa, oa, _ = route.rounds[i - 1]
        s, _ = resolve_round(s, pa, oa)
        check_row(s, rows[i], "hp")
        check_row(s, rows[i], "combo")
        if i < 8:
            check_row(s, rows[i], "hachiku")
        if i == 5:
            check_row(s, rows[i], "psych")
    assert s.outcome == "win" and s.grade == 3
    res = compute(s)
    assert res.truth == 50
    assert s.cracks == 3
    assert res.reputation_after == 45
    assert dict(res.favour) == {"mrs_hyde": -1}


def test_route_c_rules_correct_continuation():
    """Rules-correct route C after R8: still running, he is at 21.05, c = 4."""
    s = _rp("C").states[-1]
    assert s.outcome is None
    assert s.opp_hp == pytest.approx(21.05, abs=TOL)
    assert s.player_hp == pytest.approx(45, abs=TOL)
    assert s.cracks == 4
    assert s.last_card_used and s.reversed


# ---------------------------------------------------------------------------- carry / pickup

@pytest.mark.parametrize("route,reserved,held,picked", [
    ("A", None, [], ()),
    ("B", None, [], ()),
    ("C", "P05", [], ("E05",)),
    ("D", "P05", ["P07"], ("E05", "E07")),
])
def test_route_pickups(route, reserved, held, picked):
    s = _rp(route).states[0]
    assert s.reserved_last == reserved
    assert [c for c in s.hand if s.ch.cards[c].kind == "pickup"] == held
    assert s.picked == picked


def test_route_tells_are_kept_in_traces():
    """The routes state their tells; every round of every route carries one (except §7.5)."""
    for name, route in ROUTES.items():
        for pa, oa, t in route.rounds:
            assert (t is None) == (oa.kind == OA.NONE), name
