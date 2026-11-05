"""Ch.2 費奇 — 推薦路線 and 常見失誤回合 (各章設計 Ch.2 主論戰)."""

import pytest

from helpers import APPROX, OA, Clarity, E, can_tell, observe, of, opp, parry, played_full, removed_ids, solid, step
from sherefox_ref.fixtures import ch2_board, ch2_case
from sherefox_ref.model import initial_state
from sherefox_ref.rules import validate_board


def start():
    case = ch2_case()
    validate_board(case, ch2_board())
    return initial_state(case, ch2_board())


def route_until(n):
    """Replay the recommended route up to and including round n; returns states[0..n]."""
    s0 = start()
    moves = [
        (parry("E02_02"), opp(OA.CLAIM, "N1")),
        (observe(), opp(OA.CLAIM, "N2")),
        (solid("E02_03", "E02_02", "E02_04", "E02_05", target="N1"), opp(OA.REINFORCE, "N1")),
        (parry(segment=("E02_06", "E02_01")), opp(OA.RUSH, "N3")),
        (parry(segment=("E02_07", "E02_01")), opp(OA.ALL_IN, "T2", scripted=True)),
    ]
    states, evs = [s0], [None]
    for pa, oa in moves[:n]:
        s, ev = step(states[-1], pa, oa)
        states.append(s)
        evs.append(ev)
    return states, evs


def test_route_hp_sequences():
    states, _ = route_until(5)
    # 推薦路線對手主導權 100 -> 70 -> 70 -> 52.5 -> 1 -> 0 ; 我方剩餘 81
    assert [s.opp_hp for s in states] == pytest.approx([100, 70, 70, 52.5, 1, 0], abs=APPROX)
    assert [s.player_hp for s in states] == pytest.approx([100, 100, 81, 81, 81, 81], abs=APPROX)
    assert states[-1].over and states[-1].outcome == "win"


def test_route_round1_parry():
    states, evs = route_until(1)
    s0, s1 = states[0], states[1]
    assert s0.node_ids() == ("N1", "N2", "N3")
    assert removed_ids(evs[1], "parry") == ["N1"]
    dmg = of(evs[1], E.DamageToOpponent)
    assert [d.amount for d in dmg] == [30.0]
    assert (s0.hachiku, s1.hachiku) == (0, 1)
    assert of(evs[1], E.DamageToPlayer) == []


def test_route_round2_observe():
    states, evs = route_until(2)
    s1, s2 = states[1], states[2]
    assert s1.normal_node_count() == 3  # restate brought N1 back
    d = of(evs[2], E.DamageToPlayer)
    assert [x.amount for x in d] == pytest.approx([19.0])  # (26+4x3)/2
    assert "N2" in s2.node_ids()
    assert (s1.hachiku, s2.hachiku) == (1, 0)
    assert s2.next_clear_basis == "observe"


def test_route_round3_four_chain_vs_reinforce():
    states, evs = route_until(3)
    s2, s3 = states[2], states[3]
    d = of(evs[3], E.DamageToOpponent)
    assert [x.amount for x in d] == pytest.approx([17.5])  # 14x2.5=35, halved
    assert d[0].breakdown[0] == ("base", 35.0)
    assert "N1" in removed_ids(evs[3], "chain")
    assert s3.shaken == "armed"  # 4-card chain, early: no breakline
    assert of(evs[3], E.OpponentHealed) == []  # reinforce was hit
    assert (s2.hachiku, s3.hachiku) == (0, 0)
    assert "CUT_SHAKEN" in played_full(evs[3])


def test_route_round4_parry_break():
    states, evs = route_until(4)
    s3, s4 = states[3], states[4]
    d = of(evs[4], E.DamageToOpponent)
    assert [x.source for x in d] == ["counter", "break"]
    assert [x.amount for x in d] == pytest.approx([30.0, 70.0])
    assert d[0].hp_after == pytest.approx(22.5)
    assert s4.opp_hp == 1.0
    assert of(evs[4], E.DamageToPlayer) == []
    assert (s3.hachiku, s4.hachiku) == (0, 1)
    assert s4.in_tail and s4.tail_rounds_left == 1
    assert played_full(evs[4]) == ["CUT_RONPA"]
    br = of(evs[4], E.BreakResult)
    assert br and br[0].success and br[0].via == "parry"


def test_route_round5_tail():
    states, evs = route_until(5)
    s4, s5 = states[4], states[5]
    assert of(evs[5], E.TailResult)[0].correct
    assert s5.opp_hp == 0 and s5.outcome == "win"
    assert (s4.hachiku, s5.hachiku) == (1, 1)


# ---------------------------------------------------------------------- tells (policy)


def test_route_tell_round1_reachable():
    s0 = start()
    assert can_tell(s0, Clarity.FUZZY, {OA.CLAIM, OA.RUSH}, None, None, OA.CLAIM)


def test_route_tell_round2_reachable():
    """Ruling A1: 模糊「補強★1／主張」 (rule 1 applies after R1 removed N1)."""
    states, _ = route_until(1)
    assert can_tell(states[1], Clarity.FUZZY, {OA.REINFORCE, OA.CLAIM}, OA.REINFORCE, None, OA.CLAIM)
    # the old 「主張或設陷，無標記」 tell is no longer producible
    assert not can_tell(states[1], Clarity.FUZZY, {OA.CLAIM, OA.TRAP}, None, None, OA.CLAIM)


def test_route_tell_round3_reachable():
    states, _ = route_until(2)
    assert can_tell(states[2], Clarity.CLEAR, {OA.REINFORCE}, None, "observe", OA.REINFORCE)


def test_route_tell_round4_reachable():
    states, _ = route_until(3)
    assert can_tell(states[3], Clarity.CLEAR, {OA.RUSH}, None, None, OA.RUSH)


# ---------------------------------------------------------------------- 常見失誤回合


def test_mistake_round4_solid_break_takes_rush():
    states, _ = route_until(3)
    s, ev = step(states[3], solid("E02_06", "E02_01", target="N3"), opp(OA.RUSH, "N3"))
    # 我方吃下猛攻 (26+4x3)x1.25 = 47.5 (81 -> 33.5); 論破照樣成立
    p = of(ev, E.DamageToPlayer)
    assert [x.amount for x in p] == pytest.approx([47.5])
    assert s.player_hp == pytest.approx(33.5)
    assert s.opp_hp == 1.0 and s.in_tail
    assert of(ev, E.BreakResult)[0].success


def test_mistake_round3_parry_whiffs_vs_reinforce():
    states, _ = route_until(2)
    s, ev = step(states[2], parry("E02_02"), opp(OA.REINFORCE, "N1"))
    # 空過，N1 補強成功、費奇回復 10（70 -> 80），不觸發動搖，依規則 4 下一手改主張
    assert s.opp_hp == pytest.approx(80.0)
    assert "N1" in s.node_ids() and s.normal_node_count() == 3
    assert s.shaken == "none"
    assert s.last_reinforce_success and not s.last_node_removed
    from sherefox_ref.policy import possible_tells

    fuzzy = [t for t in possible_tells(s) if t[0] == Clarity.FUZZY]
    assert fuzzy and all(t[2] == OA.CLAIM for t in fuzzy)  # ★ = rule 4 target


# ---------------------------------------------------------------------- 數值卡 讀錯代價


def test_numbers_card_misread_costs():
    s0 = start()
    s, ev = step(s0, solid("E02_03", "E02_02", target="N1"), opp(OA.CLAIM, "N1"))
    assert [x.amount for x in of(ev, E.DamageToPlayer)] == pytest.approx([38.0])
    s, ev = step(s0, solid("E02_03", "E02_02", target="N1"), opp(OA.RUSH, "N1"))
    assert [x.amount for x in of(ev, E.DamageToPlayer)] == pytest.approx([47.5])
    s, ev = step(s0, observe(), opp(OA.CLAIM, "N1"))
    assert [x.amount for x in of(ev, E.DamageToPlayer)] == pytest.approx([19.0])
    s, ev = step(s0, parry("E02_02"), opp(OA.REINFORCE, "N1"))
    assert s.opp_hp == pytest.approx(100.0)  # heal capped at max
    states, _ = route_until(4)
    s, ev = step(states[4], observe(), opp(OA.ALL_IN, "T2", scripted=True))
    assert [x.amount for x in of(ev, E.DamageToPlayer)] == pytest.approx([30.0])
    # tail used up -> break voided: back to 25% of max
    assert s.opp_hp == pytest.approx(25.0) and not s.in_tail and s.break_voids == 1
