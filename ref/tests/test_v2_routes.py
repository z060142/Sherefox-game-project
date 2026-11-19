"""v2 demo chapter: the four worked routes of 11_demo_chapter.md §12 as golden traces.

Per route and round: both credibility values (to 0.01), combo, 破竹, the three psych
values, states, crack count where the table states it, and whether the opponent policy
could have produced the stated move and tell. Tables as corrected in design commit ea48cc1.
A row that disagrees with the rules goes into XFAIL (strict) with its reason; the model
keeps the rules-correct value.
"""


import pytest

from sherefox_ref.v2.model import OA
from sherefox_ref.v2.results import compute
from sherefox_ref.v2.routes import ROUTES, replay

TOL = 0.01

# round: (opp_hp, player_hp, combo, hachiku, psych P/G/A, extra state checks)
#   extra: brk=N -> 破防 through round N; brk=0 -> not broken going into the next round;
#          sh -> 失守; over -> stats over threshold at the end of the round; c -> cracks;
#          few -> 選項所剩無幾 has fired
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
        5: (1, 69, 4, 1, None, dict(c=0)),
    },
    "C": {  # ch §12.3
        1: (210, 140, 0, 1, (12, 10, 22), dict(brk=2, c=1)),
        2: (205, 140, 0, 2, (17, 9, 45), dict(brk=3, next_clear=True, c=1)),
        3: (185, 140, 0, 3, (19, 8, 61), dict(brk=4, over="A", c=2)),
        4: (1, 130, 0, 3, (36, 17, 57), dict(over="A", c=3)),
        5: (82.8, 75, 0, 0, (23, 16, 45), dict(over="")),
        6: (70.8, 55, 1, 0, (10, 15, 48), dict(few=True)),
        7: (40.8, 45, 1, 1, (27, 24, 44), dict(brk=8, c=4)),
        8: (21.05, 45, 2, 2, (24, 23, 40), {}),
        9: (1.05, 45, 2, 3, (41, 32, 36), dict(brk=10)),
        10: (0, 45, 3, 3, None, {}),
    },
    "D": {  # ch §12.4
        1: (210, 140, 0, 1, (20, 20, 10), dict(brk=2, sh=False)),
        2: (198.5, 140, 1, 2, (17, 19, 6), dict(brk=0, sh=False)),
        3: (198.5, 130, 1, 0, (4, 18, 0), dict(sh=False)),
        4: (198.5, 115, 0, 0, (0, 17, 0), dict(sh=True, known="said:鎖匠昨晚回來過")),
        5: (186.5, 90, 1, 0, (0, 16, 0), dict(sh=True)),
        6: (168.5, 60, 2, 0, (0, 15, 0), dict(sh=True)),
        7: (150.5, 1, 0, 0, (0, 14, 0), dict(sh=True, locked=True)),
        8: (None, 0, None, None, None, {}),
    },
}

XFAIL = {}
FINAL_XFAIL = {}

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
            # over at the end of the round (ch §12 心理 column), before the next decay
            thr = s.ch.psych_threshold
            assert "".join(x for x, v, h in zip("PGA", s.psych_end, thr) if v >= h) == extra["over"]
        if "c" in extra:
            assert s.cracks == extra["c"]
        if "next_clear" in extra:
            assert s.next_clear == extra["next_clear"]
        if "rule3" in extra:
            assert s.rule3_pending == extra["rule3"]
        if "known" in extra:
            assert extra["known"] in s.known
        if "few" in extra:
            assert s.few_fired == extra["few"]
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
    "B": (1, 5, 69, 85, {"grade_1": 6, "psych_card": -2}, 54, 0.8, {}),
    "C": (3, 10, 45, 50, {"grade_3": 3, "cracks": -4, "private": -3, "denials": -2}, 44, -1.2,
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
