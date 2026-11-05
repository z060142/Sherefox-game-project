"""Ch.3 皮爾斯 — 推薦路線, 常見失誤回合, 次級替代路線, 數值卡 (各章設計 Ch.3)."""

import pytest

from helpers import APPROX, OA, Clarity, E, can_tell, observe, of, opp, parry, played_full, removed_ids, solid, step
from sherefox_ref.fixtures import ch3_board, ch3_board_no_g01, ch3_case
from sherefox_ref.model import initial_state
from sherefox_ref.policy import possible_tells
from sherefox_ref.rules import IllegalAction, validate_board

MOVES = [
    (parry("E03_08"), opp(OA.CLAIM, "N1")),
    (observe(), opp(OA.CLAIM, "N3")),
    (solid("E03_07", "E03_06", target="N3"), opp(OA.REINFORCE, "N3")),
    (parry(segment=("E03_02", "E03_04", "G-01")), opp(OA.RUSH, "N2")),
    (parry(segment=("E03_05", "E03_03")), opp(OA.ALL_IN, "T3", scripted=True)),
]


def start(board=None):
    case = ch3_case()
    b = board or ch3_board()
    validate_board(case, b)
    return initial_state(case, b)


def run(moves, board=None):
    states, evs = [start(board)], [None]
    for pa, oa in moves:
        s, ev = step(states[-1], pa, oa)
        states.append(s)
        evs.append(ev)
    return states, evs


def test_route_hp_sequences():
    states, _ = run(MOVES)
    # 推薦路線對手主導權 100 -> 70 -> 70 -> 59.5 -> 1 -> 0 ; 我方剩餘 81
    assert [s.opp_hp for s in states] == pytest.approx([100, 70, 70, 59.5, 1, 0], abs=APPROX)
    assert [s.player_hp for s in states] == pytest.approx([100, 100, 81, 81, 81, 81], abs=APPROX)
    assert states[-1].outcome == "win"


def test_route_hachiku_sequence():
    states, _ = run(MOVES)
    # 破竹 0->1, 1->0, 0->1, 1->2, 2->2
    assert [s.hachiku for s in states] == [0, 1, 0, 1, 2, 2]


def test_route_round1():
    states, evs = run(MOVES[:1])
    assert removed_ids(evs[1], "parry") == ["N1"]
    assert states[1].parry_count == 1  # 第 1 次截斷


def test_route_round2():
    states, evs = run(MOVES[:2])
    assert [x.amount for x in of(evs[2], E.DamageToPlayer)] == pytest.approx([19.0])
    assert "N3" in states[2].node_ids()
    assert states[2].next_clear_basis == "observe"


def test_route_round3_scandal_shakes():
    states, evs = run(MOVES[:3])
    d = of(evs[3], E.DamageToOpponent)
    assert [x.amount for x in d] == pytest.approx([10.5])  # 14x1.5=21, halved
    assert d[0].breakdown[0] == ("base", 21.0)
    assert removed_ids(evs[3], "chain") == ["N3"]
    assert states[3].shaken == "armed"
    assert of(evs[3], E.OpponentHealed) == []
    assert "CUT_SHAKEN" in played_full(evs[3])


def test_route_round4_parry_break():
    states, evs = run(MOVES[:4])
    s3, s4 = states[3], states[4]
    d = of(evs[4], E.DamageToOpponent)
    assert [x.source for x in d] == ["counter", "break"]
    assert [x.amount for x in d] == pytest.approx([33.0, 70.0])  # 30 x 1.1 (破竹 1)
    assert d[0].hp_after == pytest.approx(26.5)
    assert s4.opp_hp == 1.0 and s4.in_tail
    assert of(evs[4], E.DamageToPlayer) == []
    # 第 2 次截斷＋首次 <= 30%, but same round as the break: no 困獸, condition not consumed
    assert s4.parry_count == 2
    assert s4.konju_left == 0 and not s4.konju_parry_used and not s4.konju_hp_used
    assert of(evs[4], E.StatusGained) == [] or all(g.status != "konju" for g in of(evs[4], E.StatusGained))
    br = of(evs[4], E.BreakResult)[0]
    assert br.success and br.label == "primary" and br.golden_used == ("G-01",)
    assert played_full(evs[4]) == ["CUT_RONPA"]


def test_route_round5_tail():
    states, evs = run(MOVES)
    assert of(evs[5], E.TailResult)[0].correct
    assert states[5].opp_hp == 0


def test_alternative_route_without_g01():
    """沒有 G-01: E03_02 -> E03_03 論破，數值相同、標記為替代論破。"""
    moves = MOVES[:3] + [
        (parry(segment=("E03_02", "E03_03")), opp(OA.RUSH, "N2")),
        (parry(segment=("E03_02", "E03_03")), opp(OA.ALL_IN, "T3", scripted=True)),
    ]
    states, evs = run(moves, ch3_board_no_g01())
    assert [s.opp_hp for s in states] == pytest.approx([100, 70, 70, 59.5, 1, 0], abs=APPROX)
    br = of(evs[4], E.BreakResult)[0]
    assert br.success and br.label == "alternative" and br.golden_used == ()


# ---------------------------------------------------------------------- tells


def test_route_tell_round1_reachable():
    assert can_tell(start(), Clarity.FUZZY, {OA.CLAIM, OA.RUSH}, None, None, OA.CLAIM)


@pytest.mark.xfail(
    strict=True,
    reason="Ch.3 R2 tell 「主張或設陷，無標記」: R1 removed N1, so rule 1 applies and A-3 puts "
    "補強★1 among the fuzzy candidates.",
)
def test_route_tell_round2_reachable():
    states, _ = run(MOVES[:1])
    assert can_tell(states[1], Clarity.FUZZY, {OA.CLAIM, OA.TRAP}, None, None, OA.CLAIM)


def test_route_tell_round3_reachable():
    states, _ = run(MOVES[:2])
    assert can_tell(states[2], Clarity.CLEAR, {OA.REINFORCE}, None, "observe", OA.REINFORCE)


@pytest.mark.xfail(
    strict=True,
    reason="Ch.3 R4 tell 「模糊（主張或猛攻）」 without ★: R3 removed N3 (rule 1), so A-3 requires "
    "補強★1 as one candidate.",
)
def test_route_tell_round4_reachable():
    states, _ = run(MOVES[:3])
    assert can_tell(states[3], Clarity.FUZZY, {OA.CLAIM, OA.RUSH}, None, None, OA.RUSH)


# ---------------------------------------------------------------------- 常見失誤回合


def test_mistake_round3_parry_vs_reinforce():
    states, _ = run(MOVES[:2])
    s, ev = step(states[2], parry("E03_07"), opp(OA.REINFORCE, "N3"))
    # 空過：N3 補強成功、回復 10（70 -> 80），場上 3 個節點，沒有動搖
    assert s.opp_hp == pytest.approx(80.0)
    assert s.normal_node_count() == 3 and "N3" in s.node_ids()
    assert s.shaken == "none"
    fuzzy = [t for t in possible_tells(s) if t[0] == Clarity.FUZZY]
    assert fuzzy and all(t[2] == OA.CLAIM for t in fuzzy)  # 規則 4 -> 主張★
    # 若玩家再讀錯就吃 38
    s2, ev2 = step(s, solid("E03_07", "E03_06", target="N3"), opp(OA.CLAIM, "N1"))
    assert [x.amount for x in of(ev2, E.DamageToPlayer)] == pytest.approx([38.0])


# ---------------------------------------------------------------------- 數值卡 讀錯代價 / statuses


def test_full_rush_taken_causes_shissu():
    s0 = start()
    s, ev = step(s0, solid("E03_02", "E03_04", target="N2"), opp(OA.RUSH, "N1"))
    assert [x.amount for x in of(ev, E.DamageToPlayer)] == pytest.approx([47.5])
    assert s.shissu_left == 1 and s.hachiku == 0
    assert "CUT_SHISSHU" in played_full(ev)
    with pytest.raises(IllegalAction):
        step(s, parry("E03_08"), opp(OA.CLAIM, "N1"))
    # 失守中對攻擊觀察算讀對 (破竹 +1), and 失守 expires at the end of that round
    s2, _ = step(s, observe(), opp(OA.CLAIM, "N1"))
    assert s2.hachiku == 1 and s2.shissu_left == 0


def test_konju_on_second_intercept():
    s0 = start()
    s1, _ = step(s0, parry("E03_08"), opp(OA.CLAIM, "N1"))
    s2, ev = step(s1, parry("E03_07"), opp(OA.CLAIM, "N3"))
    assert s2.konju_left == 2 and s2.konju_parry_used
    assert "CUT_KONJU" in played_full(ev)
    # 困獸: claim x1.25, no reinforce in the policy
    s3, ev3 = step(s2, observe(), opp(OA.CLAIM, "N2"))
    n = s2.normal_node_count()
    assert [x.amount for x in of(ev3, E.DamageToPlayer)] == pytest.approx([(26 + 4 * n) * 1.25 / 2])
    assert all(t[4] != OA.REINFORCE for t in possible_tells(s3))


def test_cutin_priority_shaken_over_hachiku3():
    """4.7 example: 截斷猛攻造成動搖並同時讓破竹疊到 3 層 -> 播放「動搖」，「破竹」改蓋印章."""
    from dataclasses import replace

    s0 = replace(start(), hachiku=2)
    s, ev = step(s0, parry("E03_08"), opp(OA.RUSH, "N1"))
    assert s.hachiku == 3 and s.shaken == "armed"
    assert played_full(ev) == ["CUT_SHAKEN"]
    demoted = [e.id for e in of(ev, E.CutIn) if e.demoted]
    assert demoted == ["CUT_HACHIKU3"]
    assert "STAMP_PARRY" in [e.id for e in of(ev, E.CutIn)]
