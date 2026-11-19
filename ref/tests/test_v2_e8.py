"""v2 demo E8 (design rulings on the strings E7 left unshown): Sherefox's cut opener SHF_D01_CUT_OPEN_1-3, the red-crack
last stand told in two steps, the damage preview UI_V2_DMG_PREVIEW and the restate / void tags of the claim picker.

The expectations are written from the plan's E8 rulings, not read off ref: the opener plays before her claim line when
her cut lands in a normal round, _3 for the keystone L2 once per debate, the others take _1 and _2 in turn from _1; no
opener on a failed cut, a dismantle or the endgame cut. The §7.5 success with a red-crack claim: SYS_D01_LASTSTAND_OK at
42 (30% of 140), then his catch of the contradiction, her hard sell and SYS_D01_REDCRACK at 32, the crack recorded. The
preview: 00_core_rules §7.1 from the round-start state and what the player sees only.
"""

from dataclasses import replace

import pytest

from sherefox_ref.v2 import known as K
from sherefox_ref.v2 import lines as LN
from sherefox_ref.v2.model import OA, PA, OpponentAction, PlayerAction, PNode, initial_state
from sherefox_ref.v2.preview import preview
from sherefox_ref.v2.resolve import resolve_round
from sherefox_ref.v2.routes import ROUTES, replay

KEYS = LN.package_keys()
O1, O2, O3 = "SHF_D01_CUT_OPEN_1", "SHF_D01_CUT_OPEN_2", "SHF_D01_CUT_OPEN_3"


def steps_of(name):
    rt = ROUTES[name]
    s = initial_state(rt.loadout)
    memo = LN.Memo()
    out = []
    for pa, oa, tl in rt.rounds:
        if s.outcome:
            break
        s2, ev = resolve_round(s, pa, oa)
        LN.tell_lines(s, tl, memo, KEYS)
        out.append((s, pa, ev, LN.round_steps(s, pa, oa, ev, s2, memo, KEYS)))
        s = s2
    return out


def normal_states():
    for name in "ABCD":
        for s in replay(name).states[:-1]:
            if not (s.outcome or s.endgame or s.player_locked):
                yield name, s


# route -> {round: opener}, from the routes' landed cuts: A R1 L1, R4 L2 (keystone), R7 L4; C R1 L1, R3 F1 (sophistry),
# R4 L2 (keystone), R7 L4, R9 L4; D R1 L1 (R3's cut on F1 fails). A R9 is the endgame cut: none.
OPENERS = {"A": {1: O1, 4: O3, 7: O2}, "B": {}, "C": {1: O1, 3: O2, 4: O3, 7: O1, 9: O2}, "D": {1: O1}}


@pytest.mark.parametrize("name", "ABCD")
def test_cut_opener_in_the_routes(name):
    got = {}
    for n, (s, pa, ev, steps) in enumerate(steps_of(name), start=1):
        ops = [i for i, st in enumerate(steps) if st.line.startswith("SHF_D01_CUT_OPEN_")]
        if ops:
            assert len(ops) == 1
            i = ops[0]
            assert steps[i].who == LN.SH and not steps[i].sys
            assert steps[i + 1].line == f"CLM_D01_{pa.claim}_LINE"      # right before her claim line
            got[n] = steps[i].line
    assert got == OPENERS[name]


def test_cut_opener_keystone_once_then_rotation():
    memo = LN.Memo()
    assert [LN.cut_open(memo, k) for k in (False, True, False, True, False)] == [O1, O3, O2, O1, O2]
    memo = LN.Memo()
    assert [LN.cut_open(memo, k) for k in (True, True, True)] == [O3, O1, O2]


def test_opener_only_on_a_landed_cut_in_a_normal_round():
    for name in "ABCD":
        for s, pa, ev, steps in steps_of(name):
            ok_cut = any(e["kind"] == "intercept" and e["ok"] for e in ev)
            has = any(st.line.startswith("SHF_D01_CUT_OPEN_") for st in steps)
            assert has == (ok_cut and s.endgame is None and not s.player_locked), (name, s.round)


def test_no_opener_on_a_dismantle_that_lands():
    for _, st in normal_states():
        for node in st.opp_chain:
            for v in K.claim_list(st):
                if K.is_catch(v.id) or v.soph or v.id not in st.ch.breakers.get(node.card, ()):
                    continue
                pa, oa = PlayerAction(PA.DISMANTLE, v.id, node.card), OpponentAction(OA.PARRY)
                s2, ev = resolve_round(st, pa, oa)
                assert any(e["kind"] == "dismantle" and e["ok"] for e in ev)
                steps = LN.round_steps(st, pa, oa, ev, s2, LN.Memo(), KEYS)
                assert not any(x.line.startswith("SHF_D01_CUT_OPEN_") for x in steps)
                return
    pytest.fail("no dismantle that knocks a lie down found in the routes")


def test_no_opener_on_a_failed_cut():
    s = replay("D").states[2]                                # before D3: 01B on F1 fails
    pa, oa = ROUTES["D"].rounds[2][0], ROUTES["D"].rounds[2][1]
    s2, ev = resolve_round(s, pa, oa)
    assert any(e["kind"] == "intercept" and not e["ok"] for e in ev)
    assert not any(x.line.startswith("SHF_D01_CUT_OPEN_") for x in LN.round_steps(s, pa, oa, ev, s2, LN.Memo(), KEYS))


def test_red_crack_last_stand_two_steps():
    s = replay("D").states[7]                              # after the Reverse Break; 06A contradicts her record
    assert s.player_locked and K.view(s, "06A").red_crack
    pa, oa = PlayerAction(PA.LAST_STAND, "06A", "L2"), OpponentAction(OA.NONE)
    s2, ev = resolve_round(s, pa, oa)
    ls = next(i for i, e in enumerate(ev) if e["kind"] == "last_stand")
    assert ev[ls]["ok"] and ev[ls]["hp"] == pytest.approx(42)
    dm = next(i for i, e in enumerate(ev) if e["kind"] == "player_damage")
    assert dm > ls and ev[dm]["cause"] == "contradiction"
    assert ev[dm]["amount"] == pytest.approx(10) and ev[dm]["hp"] == pytest.approx(32)
    assert s2.player_hp == pytest.approx(32) and s2.cracks == s.cracks + 1
    steps = LN.round_steps(s, pa, oa, ev, s2, LN.Memo(), KEYS)
    seq = [x.sys or x.line for x in steps]
    other = LN.excl_other(s, "06A")
    ck, sk = LN.excl_keys("06A", other)
    i = seq.index("SYS_D01_LASTSTAND_OK")
    assert seq[i + 1:i + 4] == [ck, sk, "SYS_D01_REDCRACK"]


def test_plain_last_stand_has_no_red_crack():
    s = replay("D").states[7]
    excl = set(s.ch.claims["06A"].exclusive)
    s = replace(s, record=[r for r in s.record if r.claim not in excl])     # 06A without the contradiction
    assert not K.view(s, "06A").red_crack
    s2, ev = resolve_round(s, PlayerAction(PA.LAST_STAND, "06A", "L2"), OpponentAction(OA.NONE))
    assert s2.player_hp == pytest.approx(42) and s2.cracks == s.cracks
    assert not any(e["kind"] == "player_damage" for e in ev)


# ---------------------------------------------------------------------------- the damage preview


@pytest.mark.parametrize("name", "ABCD")
def test_preview_equals_the_argument_dealt(name):
    n = 0
    for s, pa, ev, _ in steps_of(name):
        att = [e for e in ev if e["kind"] == "player_attach"]
        if pa.kind == PA.ARGUE and att:
            assert preview(s, pa.claim) == pytest.approx(att[0]["damage"]), (name, s.round)
            n += 1
    assert n >= 2


def test_preview_for_every_claim_whatever_harmless_move_he_makes():
    """Every claim of the picker in every normal round of the routes: when he sidesteps or speaks the link lands and
    deals exactly the preview (his move does not change it); a standing claim has none."""
    for name, s in normal_states():
        for v in K.claim_list(s):
            if v.standing:
                assert preview(s, v.id) is None
                continue
            for oa in [OpponentAction(OA.PARRY)] + [OpponentAction(k, c) for c in s.hand[:1] for k in (OA.ATTACK,
                                                                                                      OA.FORCE)]:
                _, ev = resolve_round(s, PlayerAction(PA.ARGUE, v.id), oa)
                att = [e for e in ev if e["kind"] == "player_attach"]
                assert att and preview(s, v.id) == pytest.approx(att[0]["damage"]), (name, s.round, v.id)


def test_preview_factors():
    s = replay("A").states[1]
    c = next(v for v in K.claim_list(s) if not v.soph and not K.is_catch(v.id) and not v.standing)
    plain = replace(s, player_chain=[], player_combo=0, hachiku=0, broken_until=0, knocked_claims=set())
    assert preview(plain, c.id) == pytest.approx(12)
    assert preview(replace(plain, player_combo=2), c.id) == pytest.approx(12 * 1.5)              # combo 3
    assert preview(replace(plain, player_combo=9), c.id) == pytest.approx(12 * 2.0)              # capped at 5
    assert preview(replace(plain, hachiku=2), c.id) == pytest.approx(12 * 1.2)                   # 破竹 2
    assert preview(replace(plain, broken_until=plain.round), c.id) == pytest.approx(12 * 1.25)   # guard down
    assert preview(replace(plain, knocked_claims={c.id}), c.id) == pytest.approx(12 * 0.5)       # restated
    other = next(cid for cid, cl in s.ch.claims.items() if cl.issue == c.issue and cid != c.id)
    same = replace(plain, player_chain=[PNode(other, c.issue, False, False, False)], player_combo=1)
    assert preview(same, c.id) == pytest.approx(12 * 1.25 * 1.2)                               # follow-up
    diff = next(cid for cid, cl in s.ch.claims.items() if cl.issue != c.issue
                and (cid, c.id) not in s.ch.continuations)
    nofol = replace(plain, player_chain=[PNode(diff, s.ch.claims[diff].issue, False, False, False)], player_combo=1)
    assert preview(nofol, c.id) == pytest.approx(12 * 1.25)
    everything = replace(same, player_combo=3, hachiku=3, broken_until=plain.round, knocked_claims={c.id})
    assert preview(everything, c.id) == pytest.approx(12 * 1.75 * 1.2 * 0.5 * 1.3 * 1.25)   # combo 4


def test_preview_catch_and_sophistry():
    s = replay("B").states[4]                                # before B5: 抓住他的話 on U1
    assert s.catch_card is not None
    assert preview(s, "CATCH") == preview(s, f"CATCH:{s.catch_card}")
    plain = replace(s, player_chain=[], player_combo=0, hachiku=0, broken_until=0)
    assert preview(plain, "CATCH") == pytest.approx(18)
    soph = next(v for _, st in normal_states() for v in K.claim_list(st)
                if v.soph and not v.psych_card and not v.standing and not v.red_crack)
    st = next(st for _, st in normal_states() if soph in K.claim_list(st))
    assert preview(replace(st, player_chain=[], player_combo=0, hachiku=0, broken_until=0,
                           knocked_claims=set()), soph.id) == pytest.approx(16)


def test_preview_red_crack_follows_what_is_left():
    s = replay("C").states[3]                                # before C4: 06C on her record
    assert K.view(s, "06A").red_crack
    for oa in (OpponentAction(OA.PARRY), OpponentAction(OA.ATTACK, s.hand[0])):
        _, ev = resolve_round(s, PlayerAction(PA.ARGUE, "06A"), oa)
        att = next(e for e in ev if e["kind"] == "player_attach")
        assert preview(s, "06A") == pytest.approx(att["damage"])


def test_preview_none_outside_a_normal_round():
    for name in "ACD":
        for s in replay(name).states[:-1]:
            if s.endgame or s.player_locked:
                for v in K.claim_list(s):
                    assert preview(s, v.id) is None


# ---------------------------------------------------------------------------- restate / void tags


def test_void_tag_after_a_refute():
    s = replay("D").states[4]                                # after D4: 06B refuted
    assert "06B" in s.voided and K.void_rows(s) == ["06B"]
    assert "06B" not in [v.id for v in K.claim_list(s)] and not K.restate(s, "06B")


def test_restate_tag_rule():
    for name in "ABCD":
        for s in replay(name).states:
            for v in K.claim_list(s):
                assert K.restate(s, v.id) == (not K.is_catch(v.id) and not v.standing and v.id in s.knocked_claims)
            assert all(c in s.voided for c in K.void_rows(s))
    s = replay("A").states[3]                                # after A3: 04A and 06A stand on her chain
    c = s.player_chain[0].claim
    t = replace(s, player_chain=s.player_chain[1:], knocked_claims={c})      # knocked off: restated
    assert K.restate(t, c) and not K.restate(s, c)
    assert preview(t, c) == pytest.approx(preview(replace(t, knocked_claims=set()), c) * 0.5)


def test_the_first_pickup_is_never_in_his_hand():
    from itertools import combinations
    from sherefox_ref.v2.model import Loadout, never_in_hand
    s0 = replay("A").states[0]
    ch = s0.ch
    card = never_in_hand(ch)
    assert card == "P05"
    ev = list(ch.evidence)
    for left in combinations(ev, len(ev) - ch.carry_limit):
        carried = tuple(e for e in ev if e not in left)
        s = initial_state(Loadout(carried, (), (), warmup="pass"))
        assert card not in s.hand
        if any(ch.evidence[e].opponent_use == card for e in left):
            assert s.reserved_last == card
