"""v2 unit tests: data, claim display, tricky rules, policy draws, determinism, traces."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from sherefox_ref.rng import ScriptedRng
from sherefox_ref.v2 import known as K
from sherefox_ref.v2.data import load_chapter
from sherefox_ref.v2.model import (
    OA, PA, Clarity, IllegalAction, Loadout, OpponentAction, PlayerAction, initial_state,
    pickups_for,
)
from sherefox_ref.v2.play import play
from sherefox_ref.v2.policy import RngChooser, available_actions, decide, possible_decisions
from sherefox_ref.v2.resolve import resolve_round
from sherefox_ref.v2.routes import ROUTES, replay
from sherefox_ref.v2.trace import run_route

CH = load_chapter()
TRACE_DIR = Path(__file__).resolve().parents[1] / "traces" / "v2"


def states(route):
    return replay(route).states


# ---------------------------------------------------------------------------- data


def test_data_relations_match_the_chapter():
    # ch §7: 11 exclusive pairs
    pairs = {tuple(sorted((c.id, o))) for c in CH.claims.values() for o in c.exclusive}
    assert len(pairs) == 11
    # ch §4 / §6: who breaks which card (both sides of the JSON agree)
    assert CH.breakers["L1"] == {"11A", "11B", "03A"}
    assert CH.breakers["L2"] == {"01A", "06A"}
    assert CH.breakers["L3"] == {"07B", "09A", "08A", "06B"}
    assert CH.breakers["L4"] == {"04B", "07A", "04C"}
    assert CH.breakers["P05"] == {"01A", "01C"}
    assert CH.breakers["K1"] == {"04B"}
    assert CH.cards["L2"].keystone
    assert {c.id for c in CH.cards.values() if c.frames} == {"L2", "L3", "L4", "F1", "P05", "P06", "P07"}
    # ch §8: 7 continuation entries (4 both ways)
    assert len(CH.continuations) == 11
    assert ("02C", "08B") in CH.continuations and ("08B", "02C") not in CH.continuations
    assert CH.player_max_hp == 140 and CH.opp_max_hp == 230 and CH.opp_base_damage == 16
    assert CH.max_rounds == 20 and CH.ronpa_len == 4
    assert CH.flags["S06_L008"] is False


@pytest.mark.parametrize("left,expected", [
    ((), ()),
    (("E05", "E06", "E07"), ("P05", "P07")),
    (("E06", "E07"), ("P07", "P06")),
    (("E06",), ("P06",)),
    (("E03", "E12"), ()),
])
def test_pickup_order(left, expected):
    carried = tuple(e for e in CH.evidence if e not in left)
    assert pickups_for(CH, carried) == expected


def test_pickup_reserve_is_the_first_picked():
    lo = Loadout(("E01", "E02", "E03", "E04", "E05", "E08", "E09", "E10", "E11"))
    s = initial_state(lo)
    assert s.reserved_last == "P07" and "P06" in s.hand and "P07" not in s.hand


def test_loadout_limits():
    with pytest.raises(IllegalAction):
        initial_state(Loadout(tuple(CH.evidence)[:10]))
    with pytest.raises(IllegalAction):
        initial_state(Loadout(("E01",), ("A01", "A02"), warmup="fail"))


# ---------------------------------------------------------------------------- claim display


def test_display_depends_on_what_the_player_knows():
    d0 = states("D")[0]  # no A01, no E05 / E07
    assert K.view(d0, "01B").available and not K.view(d0, "01B").soph
    assert not K.view(d0, "01A").available  # needs A01
    assert not K.view(d0, "04C").soph
    assert K.view(d0, "06C").soph  # its own evidence conflicts: always 詭辯
    b0 = states("B")[0]
    assert K.view(b0, "01B").soph  # A01 done
    assert K.view(b0, "P1A").soph and K.view(b0, "P1A").psych_card
    assert K.view(b0, "02C").available  # PN3 seen
    c0 = states("C")[0]
    assert K.view(c0, "06B").soph  # E07 carried


def test_said_item_flips_04c_and_refute_voids_06b():
    d = states("D")
    assert not K.view(d[3], "04C").soph
    assert K.view(d[4], "04C").soph  # ch §12.4 R7 note
    assert "06B" in d[4].voided and not K.view(d[4], "06B").available


def test_red_crack_from_the_public_record():
    d = states("D")
    assert not K.view(d[2], "06A").red_crack
    assert K.view(d[3], "06A").red_crack  # 01B was said as an intercept in R3
    c = states("C")
    assert K.view(c[6], "07A").red_crack  # 06B said in R1


def test_catch_only_the_next_round():
    b = states("B")
    assert b[4].catch_card == "U1"
    assert [v.id for v in K.claim_list(b[4])][0] == "CATCH:U1"
    s5 = b[5]
    assert "U1" in s5.known


# ---------------------------------------------------------------------------- tricky rules


def _set(s, **kw):
    s = deepcopy(s)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_continuation_by_script_pair():
    ev = replay("B").events[4]
    att = next(e for e in ev if e["kind"] == "player_attach")
    assert att["factors"]["continuation"] == 1.2  # 02C -> 08B, different issues


def test_keystone_shortcut_needs_break_or_half_hp():
    ra, rc = replay("A"), replay("C")
    assert not any(e["kind"] == "ronpa" for e in ra.events[4])
    assert any(e["kind"] == "ronpa" and e["via"] == "keystone" for e in rc.events[4])
    # same cut at <= 50% HP without 破防 also ronpas
    s = _set(states("A")[3], opp_hp=110.0)
    s2, ev = resolve_round(s, PlayerAction(PA.INTERCEPT, "01A"), OpponentAction(OA.ATTACK, "L2"))
    assert s2.endgame is not None and s2.ronpa_done


def test_repeated_stall_loses_its_effect():
    s = states("B")[1]
    s1, _ = resolve_round(s, PlayerAction(PA.STALL), OpponentAction(OA.REBUT))
    assert s1.broken_until == 3 and s1.next_clear
    s2, _ = resolve_round(s1, PlayerAction(PA.STALL), OpponentAction(OA.REBUT))
    assert s2.broken_until == 3  # no new 破防 on the 2nd stall in a row
    assert not s2.next_clear
    assert s2.player_hp == pytest.approx(s1.player_hp - 3)
    assert s2.opp_hp == pytest.approx(s1.opp_hp - 5)


def test_stall_vs_attack_halves_damage():
    s = states("A")[0]
    s1, _ = resolve_round(s, PlayerAction(PA.STALL), OpponentAction(OA.ATTACK, "L1"))
    assert s1.player_hp == pytest.approx(140 - 8)
    assert s1.psych_end == pytest.approx((0, 10, 17))  # stalled +15, hit −10/−8 (clamped)


def test_intercept_on_parry_blocks_next_cut():
    s = states("A")[0]
    s1, _ = resolve_round(s, PlayerAction(PA.INTERCEPT, "11A"), OpponentAction(OA.PARRY))
    assert s1.player_hp == 135 and s1.no_intercept_round == 2
    s2, _ = resolve_round(s1, PlayerAction(PA.INTERCEPT, "11A"), OpponentAction(OA.ATTACK, "L1"))
    assert s2.opp_chain[-1].card == "L1"
    assert s2.player_hp == pytest.approx(135 - 5 - 16)


def test_exposed_sophistry_cracks_and_shisshu():
    s = states("C")[0]
    s1, _ = resolve_round(s, PlayerAction(PA.ARGUE, "06B"), OpponentAction(OA.REBUT))
    assert s1.player_hp == 115 and s1.cracks == 1 and s1.shisshu
    # 失守 +25% on his next 論證, cleared by a correct read
    s2, _ = resolve_round(s1, PlayerAction(PA.ARGUE, "08A"), OpponentAction(OA.ATTACK, "L1"))
    assert s2.player_hp == pytest.approx(115 - 16 * 1.25) and s2.shisshu
    s3, _ = resolve_round(s2, PlayerAction(PA.ARGUE, "10A"), OpponentAction(OA.PARRY))
    assert not s3.shisshu


def test_guard_cancels_damage_and_shisshu():
    s = states("C")[0]
    s1, ev = resolve_round(s, PlayerAction(PA.ARGUE, "06B", guard=True), OpponentAction(OA.REBUT))
    assert s1.player_hp == 140 and not s1.shisshu and s1.cracks == 1 and s1.guard_used
    with pytest.raises(IllegalAction):
        resolve_round(s1, PlayerAction(PA.STALL, guard=True), OpponentAction(OA.REBUT))


def test_few_options_fires_once():
    c = replay("C")
    fired = [i for i, ev in enumerate(c.events) if any(e.get("event") == "few_options" for e in ev)]
    assert fired == [6]


def test_last_card_with_zero_cracks_and_a_pickup():
    s = _set(states("C")[3], cracks=0)
    s1, _ = resolve_round(s, PlayerAction(PA.INTERCEPT, "06A"), OpponentAction(OA.FORCE, "L2"))
    # 06A is a red crack here (06C said): c = 1 after this round
    assert s1.cracks == 1
    s = _set(states("C")[4], cracks=0)
    s2, _ = resolve_round(s, PlayerAction(PA.ACCEPT), OpponentAction(OA.LAST, "P05"))
    assert s2.player_hp == pytest.approx(s.player_hp - 30)
    assert s2.opp_hp == pytest.approx(23)


def test_dying_gasp_hit_keeps_the_grade():
    s = states("A")[8]
    s2, _ = resolve_round(s, PlayerAction(PA.ACCEPT), OpponentAction(OA.LAST, "K1"))
    assert s2.outcome == "win" and s2.grade == 1 and s2.player_hp == 98


def test_bad_endgame_cut_costs_5_more():
    s = states("C")[4]
    s2, _ = resolve_round(s, PlayerAction(PA.CUT, "04B"), OpponentAction(OA.LAST, "P05"))
    assert s2.player_hp == pytest.approx(s.player_hp - 5 - (15 * 3 + 10))


def test_last_stand_success_with_red_crack():
    s = states("D")[7]  # after the reverse ronpa: his chain F1, L2, F2, L4
    s2, ev = resolve_round(s, PlayerAction(PA.LAST_STAND, "06A", "L2"), OpponentAction(OA.NONE))
    assert s2.outcome is None and not s2.player_locked
    assert s2.player_hp == pytest.approx(32)  # ch §12.4 結算: back to 30%, −10 for the red crack
    assert [n.card for n in s2.opp_chain] == ["F1"]


def test_round_limit():
    s = _set(states("A")[2], round=20, opp_hp=200.0, player_hp=130.0)
    s2, ev = resolve_round(s, PlayerAction(PA.STALL), OpponentAction(OA.PARRY))
    assert s2.outcome == "win" and s2.grade == 4 and s2.end_reason == "round_limit"
    s = _set(states("A")[2], round=20, opp_hp=230.0, player_hp=50.0)
    s3, _ = resolve_round(s, PlayerAction(PA.STALL), OpponentAction(OA.PARRY))
    assert s3.outcome == "loss"


def test_illegal_actions():
    s = states("A")[0]
    with pytest.raises(IllegalAction):
        resolve_round(s, PlayerAction(PA.ARGUE, "09A"), OpponentAction(OA.ATTACK, "L1"))  # E09 not carried
    with pytest.raises(IllegalAction):
        resolve_round(s, PlayerAction(PA.ARGUE, "11A"), OpponentAction(OA.ATTACK, "P05"))  # not in hand


# ---------------------------------------------------------------------------- policy


def test_rule3_forces_a_clear_force():
    s = states("A")[6]
    assert s.rule3_pending
    assert possible_decisions(s) == {(OA.FORCE, "L4", (Clarity.CLEAR, frozenset({OA.FORCE}), None, "L4", False))}


def test_rage_only_force_or_rebut_and_clear():
    s = states("C")[3]
    assert s.over[2]
    outs = possible_decisions(s)
    # anger 57 is also in the floating band: the 30% slip still applies (U1)
    assert {(k, c) for k, c, _ in outs} == {(OA.FORCE, "L2"), (OA.FORCE, "U1"), (OA.REBUT, None)}
    assert all(t[0] == Clarity.CLEAR for _, _, t in outs)
    assert available_actions(s) == [OA.FORCE, OA.REBUT]


def test_rule5_and_star_only_on_the_true_action():
    s = states("A")[4]  # 立論 in R3 and R4
    assert OA.ATTACK not in available_actions(s)
    for kind, card, t in possible_decisions(s):
        if t[0] == Clarity.VAGUE:
            star = t[2]
            assert star is None or star == kind


def test_draw_order_trace_contract():
    s = states("A")[0]  # no tendency rule: clarity, base weights, decoy
    rng = ScriptedRng([50, 0, 0])
    d = decide(s, RngChooser(rng))
    assert [n for n, _ in rng.calls] == [100, 100, 3]
    assert d.action == OpponentAction(OA.ATTACK, "L1") and d.tell.clarity == Clarity.VAGUE
    assert d.tell.shown == (OA.ATTACK, OA.FORCE)
    s4 = states("B")[3]  # rule ④ applies; guilt in the floating band: follow, clarity, slip
    rng = ScriptedRng([0, 0, 0])
    d = decide(s4, RngChooser(rng))
    assert [n for n, _ in rng.calls] == [100, 100, 100]
    assert d.action == OpponentAction(OA.ATTACK, "U1") and d.tell.partial
    # vague would draw a decoy too
    rng = ScriptedRng([0, 99, 0, 0])
    d = decide(s4, RngChooser(rng))
    assert [n for n, _ in rng.calls] == [100, 100, 100, 3]
    assert d.tell.star == OA.ATTACK


def test_seeded_full_policy_run_is_deterministic():
    lo = ROUTES["A"].loadout
    a = json.dumps(play(lo, 20261119), ensure_ascii=False, sort_keys=True)
    b = json.dumps(play(lo, 20261119), ensure_ascii=False, sort_keys=True)
    assert a == b
    t = json.loads(a)
    assert t[-1]["after"]["outcome"] in ("win", "loss")


# ---------------------------------------------------------------------------- traces


@pytest.mark.parametrize("name", list(ROUTES))
def test_golden_trace_matches_committed_file(name):
    fresh = json.loads(json.dumps(run_route(name), ensure_ascii=False))
    committed = json.loads((TRACE_DIR / f"route_{name}.json").read_text(encoding="utf-8"))
    assert fresh == committed
