"""Ch.1 亞瑟布丁論戰 — 推薦路線 and 常見失誤回合 (各章設計 Ch.1, A-13)."""

import pytest

from helpers import OA, Clarity, E, can_tell, of, opp, parry, played_full, removed_ids, solid, step
from sherefox_ref.fixtures import ch1_board, ch1_case
from sherefox_ref.model import initial_state
from sherefox_ref.rules import validate_board

MOVES = [
    (parry("E01_06"), opp(OA.CLAIM, "N1")),
    (solid("E01_01", "E01_04", target="N2"), opp(OA.REINFORCE, "N2")),
    (parry(segment=("E01_03",)), opp(OA.CLAIM, "N3")),
]


def run(moves, rule="numbers"):
    case = ch1_case(rule)
    validate_board(case, ch1_board())
    states, evs = [initial_state(case, ch1_board())], [None]
    for pa, oa in moves:
        s, ev = step(states[-1], pa, oa)
        states.append(s)
        evs.append(ev)
    return states, evs


def test_route():
    states, evs = run(MOVES)
    # R1: 截斷 N1，第 1 個矛盾
    assert removed_ids(evs[1], "parry") == ["N1"]
    assert states[1].contradictions == 1
    # R2: 補強擋不住實證，移除 N2，第 2 個矛盾，亞瑟動搖
    assert removed_ids(evs[2], "chain") == ["N2"]
    assert states[2].contradictions == 2 and states[2].shaken == "armed"
    assert "CUT_SHAKEN" in played_full(evs[2])
    # R3: 反駁論破成立
    br = of(evs[3], E.BreakResult)
    assert br and br[0].success and br[0].via == "parry"
    assert states[3].over and states[3].outcome == "win"
    # no HP anywhere
    assert all(s.player_hp is None and s.opp_hp is None for s in states)
    assert of(evs[1] + evs[2] + evs[3], E.DamageToPlayer) == []


def test_route_hachiku_preview():
    states, evs = run(MOVES)
    # 破竹預覽 0->1, 1->0, 0->1 ; preview only: no stamps, no effect
    changes = [of(evs[i], E.HachikuChanged)[0] for i in (1, 2, 3)]
    assert [(c.before, c.after, c.preview) for c in changes] == [(0, 1, True), (1, 0, True), (0, 1, True)]
    assert not any(e.id.startswith(("STAMP_HACHIKU", "CUT_HACHIKU")) for i in (1, 2, 3) for e in of(evs[i], E.CutIn))


def test_route_tells_reachable():
    states, _ = run(MOVES)
    assert can_tell(states[0], Clarity.CLEAR, {OA.CLAIM}, None, "tutorial", OA.CLAIM)
    assert can_tell(states[1], Clarity.CLEAR, {OA.REINFORCE}, None, "tutorial", OA.REINFORCE)
    assert can_tell(states[2], Clarity.CLEAR, {OA.CLAIM}, None, "tutorial", OA.CLAIM)


MISTAKE = [
    (parry("E01_06"), opp(OA.CLAIM, "N1")),
    (parry("E01_01"), opp(OA.REINFORCE, "N2")),  # 看到拉袖子卻選了反駁
    (parry("E01_06"), opp(OA.CLAIM, "N1")),  # 規則 4 -> 主張; 讀對，第 2 個矛盾
    (parry(segment=("E01_03",)), opp(OA.CLAIM, "N3")),
]


def test_mistake_round2_parry_whiff():
    states, evs = run(MISTAKE[:2])
    s = states[2]
    assert "N2" in s.node_ids() and s.contradictions == 1
    assert s.last_reinforce_success and not s.last_node_removed
    from sherefox_ref.policy import possible_tells

    # Ch.1 tells are all clear: rule 4 shows up as the applied rule, not a ★
    tells = possible_tells(s)
    assert any(t[4] == OA.CLAIM for t in tells)


def test_mistake_path_contradictions_by_round3():
    states, _ = run(MISTAKE[:3], rule="a13")
    assert states[3].contradictions == 2 and states[3].shaken == "armed" and not states[3].over


def test_mistake_path_wins_under_a13_reading():
    states, _ = run(MISTAKE, rule="a13")
    assert states[-1].outcome == "win"


@pytest.mark.xfail(
    strict=True,
    reason="數值總表 Ch.1 「3 回合破解 3 個節點」 (implemented as: break by round 3) makes the "
    "documented one-mistake path a loss, while 各章設計 Ch.1 「讀錯 1 次仍可在時限內完成」 and A-13 "
    "「3 回合內指出 2 個矛盾即勝利」 make it a win.",
)
def test_mistake_path_wins_under_numbers_reading():
    states, _ = run(MISTAKE, rule="numbers")
    assert states[-1].outcome == "win"


def test_two_misreads_lose():
    moves = [
        (parry("E01_06"), opp(OA.REINFORCE, "N1")),
        (parry("E01_06"), opp(OA.REINFORCE, "N1")),
        (parry("E01_06"), opp(OA.CLAIM, "N1")),
    ]
    states, _ = run(moves, rule="a13")
    assert states[-1].over and states[-1].outcome == "loss"
