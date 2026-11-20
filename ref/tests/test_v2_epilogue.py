"""v2 demo chapter: the ending after the debate (11_demo_chapter.md §2 S08-S10, §12 route endings).

One test per condition row of S08, S09 and S10 (on the pure line functions over Facts), the facts as the chapter
defines them from the public record, and the four routes' endings as §12.1-§12.4 state them.
"""

import copy
from dataclasses import replace

import pytest

from sherefox_ref.v2.epilogue import (
    Facts, epilogue, facts, note_addenda, note_lines, paper_addenda, s08_lines, PAPER_LINES, NOTE_LINES)
from sherefox_ref.v2.model import RecordEntry
from sherefox_ref.v2.routes import replay

WIN = Facts(win=True, parentage_public=False, briggs_explained=False, said_06b=False, board_used=False,
            denials=0, cracks=0, truth=100)
LOSS = replace(WIN, win=False)


def s08(n):
    return f"SCR_D01_S08_L{n:03d}"


def s09(n):
    return f"SCR_D01_S09_L{n:03d}"


def s10(n):
    return f"SCR_D01_S10_L{n:03d}"


# ------------------------------------------------------------------ S08 (one test per condition)

def test_s08_win_lines():  # 〔勝利〕 L001, L007, L008
    out = s08_lines(WIN)
    assert out[0] == s08(1) and s08(7) in out and s08(8) in out
    assert out.index(s08(7)) + 1 == out.index(s08(8))
    assert not set(out) & {s08(11), s08(12)}


def test_s08_parentage():  # 〔勝利・公開過艾琳的身世〕 L002, L003
    assert s08(2) not in s08_lines(WIN)
    out = s08_lines(replace(WIN, parentage_public=True))
    assert out[:3] == [s08(1), s08(2), s08(3)]
    assert s08(2) not in s08_lines(replace(LOSS, parentage_public=True))


def test_s08_briggs_explained():  # 〔勝利・說過 07A 或 07B〕 L004, L005
    out = s08_lines(replace(WIN, briggs_explained=True))
    assert s08(4) in out and s08(5) in out and s08(6) not in out
    assert s08(4) not in s08_lines(replace(LOSS, briggs_explained=True))


def test_s08_briggs_silent():  # 〔勝利・沒說過 07A、07B〕 L006
    out = s08_lines(WIN)
    assert s08(6) in out and s08(4) not in out and s08(5) not in out
    assert s08(6) not in s08_lines(LOSS)


def test_s08_board():  # 〔勝利・用過通靈板〕 L009, L010
    assert s08(9) not in s08_lines(WIN)
    assert s08_lines(replace(WIN, board_used=True))[-2:] == [s08(9), s08(10)]
    assert s08(9) not in s08_lines(replace(LOSS, board_used=True))


def test_s08_loss():  # 〔敗北〕 L011, L012 only
    every = replace(LOSS, parentage_public=True, briggs_explained=True, board_used=True)
    assert s08_lines(LOSS) == s08_lines(every) == [s08(11), s08(12)]


def test_s08_all_on_order():
    f = replace(WIN, parentage_public=True, briggs_explained=True, board_used=True)
    assert s08_lines(f) == [s08(n) for n in (1, 2, 3, 4, 5, 7, 8, 9, 10)]


# ------------------------------------------------------------------ S09

@pytest.mark.parametrize("grade,version", [(1, "decent"), (2, "decent"), (3, "normal"), (4, "normal"), (5, "ugly")])
def test_s09_version_by_grade(grade, version):
    s = copy.deepcopy(replay("A").states[-1])
    s.grade = grade
    s.outcome = "loss" if grade == 5 else "win"
    e = epilogue(s)
    assert e.paper == version and list(e.paper_lines) == PAPER_LINES[version]
    assert PAPER_LINES == {"decent": [s09(1), s09(2)], "normal": [s09(3), s09(4)], "ugly": [s09(5), s09(6)]}


def test_s09_parentage_any_version():  # L007 公開過艾琳的身世（任何版本）
    assert paper_addenda(WIN) == []
    assert paper_addenda(replace(WIN, parentage_public=True)) == [s09(7)]
    assert paper_addenda(replace(LOSS, parentage_public=True)) == [s09(7)]


@pytest.mark.parametrize("den,cr,win,expect", [
    (1, 0, True, True), (0, 3, True, True), (0, 2, True, False), (0, 0, True, False),
    (2, 5, False, False),  # 勝利時 only
])
def test_s09_denials_or_cracks(den, cr, win, expect):  # L008 否定事實 ≥ 1 或裂紋 ≥ 3（勝利時）
    f = replace(WIN, win=win, denials=den, cracks=cr)
    assert (s09(8) in paper_addenda(f)) is expect


def test_s09_addenda_order():
    f = replace(WIN, parentage_public=True, denials=1)
    assert paper_addenda(f) == [s09(7), s09(8)]


# ------------------------------------------------------------------ S10

@pytest.mark.parametrize("false_claims,denials,truth,version", [
    (0, 0, 100, "full"), (2, 0, 70, "full"), (1, 1, 65, "half"), (4, 0, 40, "half"), (3, 1, 35, "wrong"),
    (6, 0, 10, "wrong")])
def test_s10_version_by_truth(false_claims, denials, truth, version):  # ≥ 70 / 40～69 / ＜ 40
    s = copy.deepcopy(replay("A").states[-1])
    s.denials = denials
    for c in [c for c in s.ch.claims.values() if not c.true][:false_claims]:
        s.record.append(RecordEntry(99, c.id, "argue", False, False, False))
    e = epilogue(s)
    assert e.facts.truth == truth
    assert e.notes == version and list(e.note_lines) == note_lines(e.facts, version)
    assert e.note_lines[0] == NOTE_LINES[version][0]
    assert NOTE_LINES == {"full": [s10(1), s10(2), s10(3)], "half": [s10(4), s10(5)], "wrong": [s10(6)]}


@pytest.mark.parametrize("version,head", [("full", 1), ("half", 4), ("wrong", 6)])
@pytest.mark.parametrize("win", [True, False])
def test_s10_version_head_win_or_loss(version, head, win):  # L001 / L004 / L006 勝敗都播
    assert note_lines(replace(WIN, win=win), version)[0] == s10(head)


@pytest.mark.parametrize("win,a07,b07,expect", [
    (True, True, False, True),  # 07A only
    (True, False, True, True),  # 07B only
    (True, True, True, True),
    (True, False, False, False),  # neither
    (False, True, False, False),  # a loss
    (False, False, True, False),
])
def test_s10_l002_win_and_07a_or_07b(win, a07, b07, expect):  # L002 知道全貌：勝利且說過 07A 或 07B
    f = replace(WIN, win=win, briggs_explained=a07 or b07)
    out = note_lines(f, "full")
    assert (s10(2) in out) is expect
    assert out == ([s10(1), s10(2), s10(3)] if expect else [s10(1), s10(3)])


def test_s10_l002_from_record():  # 07A only / 07B only / neither, from the public record
    a = replay("A").states[-1]
    s = copy.deepcopy(a)
    s.record = [r for r in s.record if r.claim not in ("07A", "07B")]
    assert s10(2) not in epilogue(s).note_lines
    assert s10(2) in epilogue(_rec(s, "07A")).note_lines
    assert s10(2) in epilogue(_rec(s, "07B")).note_lines


def test_s10_l003_full_always():  # L003 知道全貌（無條件）
    for f in (WIN, LOSS, replace(WIN, briggs_explained=True)):
        assert s10(3) in note_lines(f, "full")


@pytest.mark.parametrize("win,cracks,expect", [
    (True, 0, False), (True, 1, True), (True, 4, True),  # boundary c = 0 / 1
    (False, 0, False), (False, 1, False), (False, 4, False),  # a loss
])
def test_s10_l005_win_and_cracked(win, cracks, expect):  # L005 只知道一半：勝利且裂紋 c ≥ 1
    out = note_lines(replace(WIN, win=win, cracks=cracks), "half")
    assert out == ([s10(4), s10(5)] if expect else [s10(4)])


def test_s10_conditions_stay_in_their_version():
    every = replace(WIN, briggs_explained=True, cracks=3)
    assert note_lines(every, "full") == [s10(1), s10(2), s10(3)]
    assert note_lines(every, "half") == [s10(4), s10(5)]
    assert note_lines(every, "wrong") == [s10(6)]


def test_s10_no_07a_07b_any_version():  # L007 論戰中沒有說過 07A、07B（任何版本）
    assert s10(7) in note_addenda(WIN)
    assert s10(7) in note_addenda(LOSS)
    assert s10(7) in note_addenda(replace(WIN, truth=20))
    assert s10(7) not in note_addenda(replace(WIN, briggs_explained=True))


@pytest.mark.parametrize("win,said06b,explained,truth,expect", [
    (True, True, False, 69, True),
    (True, True, False, 70, False),  # truth < 70 only
    (True, False, False, 50, False),  # 06B must be said
    (True, True, True, 50, False),  # 07A / 07B said (route C)
    (False, True, False, 60, False),  # a loss (route D)
])
def test_s10_said_06b_low_truth(win, said06b, explained, truth, expect):  # L008 勝利、說過 06B、沒說過 07A／07B、＜ 70%
    f = replace(WIN, win=win, said_06b=said06b, briggs_explained=explained, truth=truth)
    assert (s10(8) in note_addenda(f)) is expect


def test_s10_loss_any_version():  # L009 敗北（任何版本）
    assert s10(9) in note_addenda(LOSS)
    assert s10(9) in note_addenda(replace(LOSS, truth=100, briggs_explained=True))
    assert s10(9) not in note_addenda(WIN)


def test_s10_addenda_order():
    assert note_addenda(replace(WIN, said_06b=True, truth=50)) == [s10(7), s10(8)]
    assert note_addenda(LOSS) == [s10(7), s10(9)]


# ------------------------------------------------------------------ facts from the public record

def _rec(state, claim, use="argue", true=True):
    s = copy.deepcopy(state)
    s.record.append(RecordEntry(99, claim, use, False, False, true))
    return s


def test_facts_parentage_is_09a_in_any_use():
    a = replay("A").states[-1]
    assert not facts(a).parentage_public
    assert facts(_rec(a, "09A")).parentage_public
    assert facts(_rec(a, "09A", use="intercept")).parentage_public
    assert not facts(_rec(a, "09B", true=False)).parentage_public


def test_facts_briggs_and_06b_and_board():
    a = replay("A").states[-1]
    s = copy.deepcopy(a)
    s.record = [r for r in s.record if r.claim not in ("07A", "07B")]
    assert facts(a).briggs_explained and not facts(s).briggs_explained
    assert facts(_rec(s, "07B")).briggs_explained
    assert not facts(a).said_06b and facts(_rec(a, "06B", "intercept", False)).said_06b
    assert not facts(a).board_used
    assert facts(_rec(a, "P1B", true=False)).board_used
    assert not facts(_rec(a, "CATCH:U1")).board_used


def test_l008_reachable_by_state():
    """S10 L008 from a debate state: route B's win (truth 85, no 07A / 07B) plus 06B said as a cut (false: −15 → 70
    is still full, so one more false claim → 55, half)."""
    b = replay("B").states[-1]
    s = _rec(_rec(b, "06B", "intercept", False), "01B", "intercept", False)
    e = epilogue(s)
    assert e.facts.truth == 55 and e.notes == "half"
    assert list(e.note_addenda) == [s10(7), s10(8)]


# ------------------------------------------------------------------ the four routes (ch §12)

ROUTE_END = {
    # S08, S09 version + addenda, S10 version + addenda, grade, rounds, reputation items, favour
    "A": ([1, 4, 5, 7, 8], "decent", [], "full", [], 1, 9, [("grade_1", 6, 0)], []),
    "B": ([1, 6, 7, 8, 9, 10], "decent", [], "full", [7], 1, 5, [("grade_1", 6, 0), ("psych_card", -2, 0)], []),
    "C": ([1, 2, 3, 4, 5, 7, 8], "normal", [7, 8], "half", [], 3, 10,
          [("grade_3", 3, 0), ("cracks", -4, 4), ("private", -3, 1), ("denials", -2, 1)], [("mrs_hyde", -1)]),
    "D": ([11, 12], "ugly", [], "half", [7, 9], 5, 8, [("grade_5", -4, 0)], [("inspector", -1)]),
}


# the version's lines on each route (design e62621f): B wins without 07A / 07B (no L002); D loses (no L005)
ROUTE_NOTES = {"A": [1, 2, 3], "B": [1, 3], "C": [4, 5], "D": [4]}


@pytest.mark.parametrize("route", list(ROUTE_END))
def test_route_ending(route):
    s08_, paper, padd, notes, nadd, grade, rounds, rep, fav = ROUTE_END[route]
    nlines = ROUTE_NOTES[route]
    e = epilogue(replay(route).states[-1])
    assert list(e.s08) == [s08(n) for n in s08_]
    assert e.paper == paper and list(e.paper_addenda) == [s09(n) for n in padd]
    assert list(e.s09) == PAPER_LINES[paper] + [s09(n) for n in padd]
    assert e.notes == notes and list(e.note_addenda) == [s10(n) for n in nadd]
    assert list(e.s10) == [s10(n) for n in nlines] + [s10(n) for n in nadd]
    assert e.grade == grade and e.rounds == rounds
    assert list(e.reputation) == rep
    assert list(e.favour) == fav


def test_route_facts():
    fa, fb, fc, fd = (epilogue(replay(r).states[-1]).facts for r in "ABCD")
    assert fa.briggs_explained and not fa.board_used and fa.truth == 100
    assert fb.board_used and not fb.briggs_explained and fb.truth == 85
    assert fc.parentage_public and fc.briggs_explained and fc.said_06b and fc.denials == 1 and fc.cracks == 4
    assert fc.truth == 50
    assert not fd.win and fd.said_06b and not fd.briggs_explained and fd.truth == 60
