"""Warmup (A-13), formulas (A-1, A-15), RNG determinism, fox instinct, assist/trap (A-7)."""

from dataclasses import replace

import pytest

from helpers import OA, PA, Clarity, E, of, opp, step
from sherefox_ref.fixtures import ch2_board, ch2_case, ch3_warmup
from sherefox_ref.model import Board, PlayerAction, initial_state
from sherefox_ref.policy import RngChooser, Tell, decide_next, use_fox_instinct
from sherefox_ref.rng import SplitMix64
from sherefox_ref.rules import chain_damage_breakdown, claim_damage, counter_damage
from sherefox_ref.warmup import ch3_warmup_grants, resolve_warmup_round


# ---------------------------------------------------------------------- warmup


def test_warmup_single_card_zero_mistakes():
    ws, ev = resolve_warmup_round(ch3_warmup(), "parry", ("E03_05",))
    assert ws.over and ws.mistakes == 0
    assert ev[-1]["trust_delta"] == 1
    assert ch3_warmup_grants(3, ws) == {"effective_trust": 4, "E03_01": True, "deck_access": True}


def test_warmup_e0302_also_refutes():
    ws, _ = resolve_warmup_round(ch3_warmup(), "parry", ("E03_02",))
    assert ws.over and ws.mistakes == 0


def test_warmup_three_mistakes():
    ws = ch3_warmup()
    for _ in range(3):
        ws, ev = resolve_warmup_round(ws, "parry", ("E03_08",))
    assert ws.over and ws.auto_resolved and ev[-1]["trust_delta"] == -1 and not ev[-1]["reward"]


def test_warmup_one_mistake_then_right():
    ws, _ = resolve_warmup_round(ch3_warmup(), "parry", ("E03_08",))
    ws, ev = resolve_warmup_round(ws, "parry", ("E03_05",))
    assert ws.over and ev[-1]["trust_delta"] == 0 and ev[-1]["reward"]


def test_warmup_parry_only_and_chain_rule():
    with pytest.raises(ValueError):
        resolve_warmup_round(ch3_warmup(), "solid_chain", ("E03_05", "E03_02"))
    ws, _ = resolve_warmup_round(ch3_warmup(), "parry", ("E03_05", "E03_02"))
    assert ws.mistakes == 1  # A-13: single card
    ws, _ = resolve_warmup_round(ch3_warmup(), "parry", ("E03_05", "E03_02"), allow_chain=True)
    assert ws.over and ws.mistakes == 0


# ---------------------------------------------------------------------- formulas


def test_overview_example_and_ch4_route_formula():
    # 設計總覽: 3 段實證＋1 段詭辯打動搖中的對手 14 x 3.3 x 1.5 = 69.3
    d, _ = chain_damage_breakdown(3, 1, True, 0, False, False)
    assert d == pytest.approx(69.3)
    # Ch.4 R4: 14 x 2.5 x 1.5 x 1.1 = 57.75 (破竹 after 動搖)
    d, _ = chain_damage_breakdown(3, 0, True, 1, False, False)
    assert d == 57.75
    # Ch.4 R1: sophistry 14 x 1.8 = 25.2
    d, _ = chain_damage_breakdown(0, 1, False, 0, False, False)
    assert d == pytest.approx(25.2)


def test_counter_values():
    assert [counter_damage(s)[0] for s in range(4)] == [30, 33, 36, 39]


def test_claim_values():
    c = ch2_case()
    assert claim_damage(c, 3, False, False, 1, False)[0] == 38
    assert claim_damage(c, 3, True, False, 1, False)[0] == 47.5
    assert claim_damage(c, 3, True, False, 1, True)[0] == 23.75
    assert claim_damage(c, 3, False, False, 15, False)[0] == 43


def test_fragile_plus_10_after_matchup():
    d, steps = chain_damage_breakdown(1, 0, False, 0, True, True)
    assert d == pytest.approx(14 * 1.5 / 2 + 10)
    assert [s[0] for s in steps] == ["base", "matchup_x0.5", "fragile_+10"]


# ---------------------------------------------------------------------- RNG / policy determinism


def test_splitmix_known_sequence():
    r = SplitMix64(0)
    # reference values of SplitMix64 seeded with 0
    assert r.next_u64() == 0xE220A8397B1DCDAF
    assert r.next_u64() == 0x6E789E6AA1B965F4


def test_policy_deterministic_trace():
    s0 = initial_state(ch2_case(), ch2_board())

    def trace(seed):
        ch = RngChooser(SplitMix64(seed))
        out = []
        st = s0
        for _ in range(5):
            st, oa, tell = decide_next(st, ch)
            out.append((oa.kind, oa.lit, tell.clarity, tell.shown, tell.star))
        return out

    assert trace(42) == trace(42)


def test_rule3_forces_clear_rush():
    s = replace(initial_state(ch2_case(), ch2_board()), rule3_pending=True, rule3_fired=True)
    s2, oa, tell = decide_next(s, RngChooser(SplitMix64(1)))
    assert oa.kind == OA.RUSH and tell.clarity == Clarity.CLEAR and tell.basis == "rule3"
    assert not s2.rule3_pending


def test_rule5_bans_third_repeat():
    s = replace(initial_state(ch2_case(), ch2_board()), opp_history=(OA.CLAIM, OA.CLAIM))
    from sherefox_ref.policy import possible_tells

    assert all(t[4] != OA.CLAIM for t in possible_tells(s))
    assert all(OA.CLAIM not in t[1] for t in possible_tells(s))


def test_fox_instinct_on_fuzzy():
    s = initial_state(ch2_case(), ch2_board())
    tell = Tell(Clarity.FUZZY, (OA.CLAIM, OA.TRAP), None, None, None, "N1", "tug_cuff_bow")
    s2, t2, ev = use_fox_instinct(s, tell, opp(OA.TRAP, "N1"))
    assert s2.fox_left == 1 and t2.clarity == Clarity.CLEAR and t2.shown == (OA.TRAP,) and t2.basis == "fox"
    with pytest.raises(ValueError):
        use_fox_instinct(s, Tell(Clarity.CLEAR, (OA.CLAIM,), None, None, "observe", "N1", None), opp(OA.CLAIM, "N1"))


# ---------------------------------------------------------------------- sophistry / trap / assist (generic)


def _soph_state():
    case = replace(ch2_case(), sophistry_unlocked=True)
    case = replace(case, cards=tuple(replace(c, reason_correct=False) if c.id == "E02_04" else c for c in case.cards))
    board = Board(chains=(("E02_03", "E02_02", "E02_04"),))
    return initial_state(case, board)


def test_trap_crit_snaps_link_and_infamy():
    s0 = _soph_state()
    pa = PlayerAction(PA.SOPHISTRY, segment=("E02_03", "E02_02", "E02_04"), target="N1")
    s, ev = step(s0, pa, opp(OA.TRAP, "N1"))
    assert [x.amount for x in of(ev, E.DamageToPlayer)] == [25.0]
    assert of(ev, E.DamageToOpponent) == []
    assert s.infamy == 1 and of(ev, E.LinkSnapped)


def test_assist_blocks_crit():
    s0 = _soph_state()
    pa = PlayerAction(PA.SOPHISTRY, segment=("E02_03", "E02_02", "E02_04"), target="N1", assist=True)
    s, ev = step(s0, pa, opp(OA.TRAP, "N1"))
    assert of(ev, E.DamageToPlayer) == [] and s.infamy == 0 and s.assist_left == 0
    assert "STAMP_ASSIST" in [e.id for e in of(ev, E.CutIn)]


def test_assist_wasted_without_trap():
    s0 = _soph_state()
    pa = PlayerAction(PA.SOPHISTRY, segment=("E02_03", "E02_02", "E02_04"), target="N1", assist=True)
    s, ev = step(s0, pa, opp(OA.REINFORCE, "N1"))
    assert s.assist_left == 0 and of(ev, E.AssistSpent)[0].wasted
    # sophistry beats reinforce at full damage: 14 x (1 + 0.5 + 0.8) = 32.2
    assert [x.amount for x in of(ev, E.DamageToOpponent)] == pytest.approx([32.2])


# ---------------------------------------------------------------------- rule text 2026-11-06 (B8-B10, 數值總表 四)


def test_player_damage_order():
    """base -> 動搖 x1.5 -> 破竹 -> 交鋒/補強 x0.5 -> 脆弱 +10."""
    d, steps = chain_damage_breakdown(1, 0, True, 2, True, True)
    assert [s[0] for s in steps] == ["base", "shaken_x1.5", "hachiku_x2", "matchup_x0.5", "fragile_+10"]
    assert d == pytest.approx(14 * 1.5 * 1.5 * 1.2 / 2 + 10)


def test_opponent_damage_order():
    """B10: base -> 猛攻 x1.25 -> 困獸 x1.25 -> +5 聽眾不耐 -> 觀察 x0.5."""
    d, steps = claim_damage(ch2_case(), 3, True, True, 15, True)
    assert [s[0] for s in steps] == ["claim", "rush_x1.25", "konju_x1.25", "impatience_+5", "observe_x0.5"]
    assert d == pytest.approx((38 * 1.25 * 1.25 + 5) / 2)


def test_break_round_locks_at_1_attack_resolves_then_tail():
    """B8: chain alone takes the opponent below 0 in the break round -> locked at 1; the opponent's
    claim still hits the player; then the tail starts."""
    from helpers import solid

    s0 = initial_state(ch2_case(), ch2_board())
    s = replace(s0, shaken="armed", opp_hp=5.0)
    s2, ev = step(s, solid("E02_06", "E02_01", target="N3"), opp(OA.CLAIM, "N3"))
    assert of(ev, E.BreakResult)[0].success
    assert s2.opp_hp == 1.0 and s2.in_tail and not s2.over
    assert [x.amount for x in of(ev, E.DamageToPlayer)] == pytest.approx([38.0])


def test_rule3_threshold_is_at_most_half():
    """B9: the first time the opponent is at <= 50% (exactly 50 counts)."""
    from helpers import parry

    s0 = replace(initial_state(ch2_case(), ch2_board()), opp_hp=80.0)
    s1, _ = step(s0, parry("E02_02"), opp(OA.CLAIM, "N1"))
    assert s1.opp_hp == 50.0 and s1.rule3_fired and s1.rule3_pending


def test_deleted_rule_action_counts_as_not_applying():
    """數值總表 四: a rule whose action is deleted (不能補強 / rule 5) does not apply, so the next tendency
    rule wins its ★; with no other rule, no ★."""
    from sherefox_ref.policy import possible_tells

    base = initial_state(ch2_case(), ch2_board())
    s = replace(base, last_node_removed=True, last_reinforce_success=True, no_reinforce_next=True)
    fuzzy = [t for t in possible_tells(s) if t[0] == Clarity.FUZZY]
    assert fuzzy and all(t[2] == OA.CLAIM for t in fuzzy)  # rule 4 ★, rule 1 dropped
    assert all(t[4] != OA.REINFORCE for t in possible_tells(s))
    s = replace(base, last_node_removed=True, no_reinforce_next=True)
    fuzzy = [t for t in possible_tells(s) if t[0] == Clarity.FUZZY]
    assert fuzzy and all(t[2] is None for t in fuzzy)
    # rule 5 deleting reinforce (two reinforces in a row) also cancels rule 1
    s = replace(base, last_node_removed=True, opp_history=(OA.REINFORCE, OA.REINFORCE))
    fuzzy = [t for t in possible_tells(s) if t[0] == Clarity.FUZZY]
    assert fuzzy and all(t[2] is None for t in fuzzy)


def test_fuzzy_star_pair_shows_rule_target_and_actual():
    """A fuzzy tell with ★ shows the rule's action and the true action (when they differ)."""
    from sherefox_ref.policy import possible_tells

    s = replace(initial_state(ch2_case(), ch2_board()), last_node_removed=True)
    for clarity, shown, star, _basis, actual in possible_tells(s):
        if clarity == Clarity.FUZZY:
            assert star == OA.REINFORCE and len(shown) == 2 and {star, actual} <= shown
