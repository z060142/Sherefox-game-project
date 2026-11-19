"""legal.legal_moves: the player's legal commands per state (the debate UI must offer exactly these; the UI fuzz
tests/check_d1_fuzz.py compares the screen with it round by round)."""

import random

from sherefox_ref.v2 import known as K
from sherefox_ref.v2.data import load_chapter
from sherefox_ref.v2.legal import is_legal, legal_moves
from sherefox_ref.v2.model import CATCH, PA, IllegalAction, PlayerAction, initial_state
from sherefox_ref.v2.policy import RngChooser, decide
from sherefox_ref.v2.resolve import resolve_round
from sherefox_ref.v2.rng import DebateRng
from sherefox_ref.v2.routes import ROUTES, replay

CH = load_chapter()
CLAIM_KINDS = (PA.ARGUE, PA.INTERCEPT, PA.DISMANTLE, PA.CUT, PA.LAST_STAND)
TARGET_KINDS = (PA.DISMANTLE, PA.LAST_STAND)


def route_steps():
    """(state, opponent action) of every round of routes A-D."""
    out = []
    for name in "ABCD":
        rp = replay(name)
        for s, (_, oa, _) in zip(rp.states, ROUTES[name].rounds):
            if s.outcome:
                break
            out.append((s, oa))
    return out


def random_steps(loadout, seed, rounds=40):
    """A debate with his real policy and the player choosing uniformly among legal_moves."""
    py = random.Random(seed)
    ch = RngChooser(DebateRng(seed))
    s = initial_state(loadout)
    out = []
    for _ in range(rounds):
        if s.outcome:
            break
        d = decide(s, ch)
        out.append((s, d.action))
        s, _ = resolve_round(s, py.choice(legal_moves(s)), d.action)
    return out


def all_steps():
    steps = route_steps()
    for i, name in enumerate("ABCD"):
        for seed in range(1, 6):
            steps += random_steps(ROUTES[name].loadout, seed * 10 + i)
    return steps


STEPS = all_steps()


def test_every_legal_move_resolves():
    n = 0
    for s, oa in STEPS:
        moves = legal_moves(s)
        assert moves, f"round {s.round}: no legal move"
        assert len(set(moves)) == len(moves)
        for pa in moves:
            resolve_round(s, pa, oa)   # raises IllegalAction if the ref rejects it
            n += 1
    assert n > 1000


def test_the_situations_are_covered():
    kinds = {pa.kind for s, _ in STEPS for pa in legal_moves(s)}
    assert kinds == set(PA)
    assert any(s.catch_card for s, _ in STEPS)            # 抓住他的話 offered
    assert any(s.guard_used and not s.endgame and not s.player_locked for s, _ in STEPS)
    assert any(s.player_locked for s, _ in STEPS) and any(s.endgame for s, _ in STEPS)


def normalized(s, pa):
    """pa without what resolve_round ignores: the claim of 打迷糊仗 / 承受, the target of an action that takes none,
    援護 outside a normal round."""
    normal = not s.endgame and not s.player_locked
    return PlayerAction(pa.kind, pa.claim if pa.kind in CLAIM_KINDS else None,
                        pa.target if pa.kind in TARGET_KINDS else None, pa.guard and normal)


def documented_extra(s, pa):
    """Commands resolve_round accepts that legal.py leaves out on purpose (its module docstring): 抓住他的話 or a
    target not on his chain as the §7.5 last card."""
    return s.player_locked and pa.kind == PA.LAST_STAND and (
        K.is_catch(pa.claim) or (pa.target is not None and pa.target not in [n.card for n in s.opp_chain]))


def candidates(s):
    chain = [n.card for n in s.opp_chain]
    off = [c for c in CH.cards if c not in chain][:1]
    claims = [None, CATCH, *(f"{CATCH}:{c}" for c in ("U1", "U2")), *CH.claims]
    for kind in PA:
        for claim in claims if kind in CLAIM_KINDS else [None, "01A"]:
            for target in [None, *chain, *off] if kind in TARGET_KINDS else [None, chain[0] if chain else "L1"]:
                for guard in (False, True):
                    yield PlayerAction(kind, claim, target, guard)


def test_outside_the_set_the_ref_rejects():
    """Every command outside legal_moves raises IllegalAction in resolve_round, apart from what it ignores and the
    documented §7.5 extras; every command inside resolves."""
    rng = random.Random(5)
    sample = rng.sample(STEPS, 14) + [st for st in STEPS if st[0].endgame][:3] + \
        [st for st in STEPS if st[0].player_locked][:3] + [st for st in STEPS if st[0].catch_card][:3]
    for s, oa in sample:
        for pa in candidates(s):
            try:
                resolve_round(s, pa, oa)
                ok = True
            except (IllegalAction, KeyError):   # KeyError: a §7.5 command without a claim
                ok = False
            legal = is_legal(s, normalized(s, pa))
            if legal:
                assert ok, f"R{s.round}: legal {pa} rejected"
            elif ok:
                assert documented_extra(s, pa), f"R{s.round}: {pa} accepted by the ref but not legal"


def test_specific_rules():
    s = replay("A").states[0]
    stand = next(st for st, _ in STEPS if st.player_chain and not st.endgame and not st.player_locked)
    c = stand.player_chain[0].claim
    assert not is_legal(stand, PlayerAction(PA.ARGUE, c))                      # §3.4 on the chain: not again
    assert is_legal(stand, PlayerAction(PA.INTERCEPT, c))                      # §3.4 R-35: may still refute
    assert not is_legal(s, PlayerAction(PA.ARGUE, "12A"))                      # E12 not carried by route A
    assert not is_legal(s, PlayerAction(PA.DISMANTLE, "01A", "L1"))            # his chain is empty in round 1
    assert is_legal(s, PlayerAction(PA.STALL, guard=True))
    assert not is_legal(s, PlayerAction(PA.CUT, "01A"))                        # endgame only
    used = next(st for st, _ in STEPS if st.guard_used and not st.endgame and not st.player_locked)
    assert not is_legal(used, PlayerAction(PA.STALL, guard=True))              # §5.3 once per debate
    caught = next(st for st, _ in STEPS if st.catch_card and not st.endgame and not st.player_locked)
    assert is_legal(caught, PlayerAction(PA.ARGUE, CATCH))
    assert not is_legal(caught, PlayerAction(PA.INTERCEPT, CATCH))             # §6.5 an argue option only
    eg = next(st for st, _ in STEPS if st.endgame)
    assert {pa.kind for pa in legal_moves(eg)} == {PA.CUT, PA.ACCEPT}
    assert not any(pa.guard for pa in legal_moves(eg))
    ls = next(st for st, _ in STEPS if st.player_locked)
    assert {pa.kind for pa in legal_moves(ls)} == {PA.LAST_STAND, PA.ACCEPT}
    assert PlayerAction(PA.LAST_STAND, legal_moves(ls)[0].claim, None) in legal_moves(ls)   # no target: allowed


def test_route_moves_are_legal():
    """Every move of routes A-D is legal; route D's last card names L1, no longer on his chain (the same loss as no
    target: the screen cannot pick it, tests/README.md route D)."""
    for name in "ABCD":
        rp = replay(name)
        for s, (pa, _, _) in zip(rp.states, ROUTES[name].rounds):
            if s.outcome:
                break
            if pa.kind == PA.LAST_STAND and pa.target not in [n.card for n in s.opp_chain]:
                pa = PlayerAction(pa.kind, pa.claim, None, pa.guard)
            assert is_legal(s, pa), f"route {name} R{s.round}: {pa}"
