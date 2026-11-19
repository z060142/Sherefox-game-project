"""Seeded full-policy play: the opponent policy draws from one SplitMix64 per playthrough;
the player is a simple deterministic bot (no randomness) that reads only the tell."""

from __future__ import annotations

from .. import rng as _rng
from . import known as K
from .model import CATCH, OA, PA, Clarity, Loadout, PlayerAction, State, initial_state
from .policy import RngChooser, decide
from .resolve import resolve_round


def bot(s: State, t) -> PlayerAction:
    ch = s.ch
    views = K.claim_list(s)
    proper = [v for v in views if v.available and not v.soph and not v.red_crack]
    if s.player_locked:
        for n in s.opp_chain:
            for v in proper:
                if ch.cards[n.card].is_lie and v.id in ch.breakers.get(n.card, ()):
                    return PlayerAction(PA.LAST_STAND, v.id, n.card)
        return PlayerAction(PA.ACCEPT)
    if s.endgame:
        card = s.endgame["card"]
        for v in views:
            if not K.is_catch(v.id) and v.id in ch.breakers.get(card, ()):
                return PlayerAction(PA.CUT, v.id)
        return PlayerAction(PA.ACCEPT)
    shown = set(t.shown)
    likely = t.star or (t.shown[0] if t.clarity == Clarity.CLEAR else None)
    if likely == OA.REBUT or shown == {OA.REBUT}:
        return PlayerAction(PA.STALL)
    if t.card and (likely in (OA.ATTACK, OA.FORCE) or shown <= {OA.ATTACK, OA.FORCE}):
        cd = ch.cards[t.card]
        if cd.is_lie:
            for v in proper:
                if not K.is_catch(v.id) and v.id in ch.breakers.get(t.card, ()):
                    return PlayerAction(PA.INTERCEPT, v.id)
    if s.catch_card is not None and OA.REBUT not in shown:
        return PlayerAction(PA.ARGUE, CATCH)
    have = {n.issue for n in s.player_chain}
    free = [v for v in proper if not v.standing and not K.is_catch(v.id)]
    free.sort(key=lambda v: (v.issue in have, v.id))
    if free and OA.REBUT not in shown:
        return PlayerAction(PA.ARGUE, free[0].id)
    return PlayerAction(PA.STALL)


def play(loadout: Loadout, seed: int, max_rounds: int = 40) -> list[dict]:
    """Play one debate to the end; returns a JSON-able trace."""
    rng = _rng.SplitMix64(seed)
    chooser = RngChooser(rng)
    s = initial_state(loadout)
    trace = []
    for _ in range(max_rounds):
        if s.outcome:
            break
        d = decide(s, chooser)
        pa = bot(s, d.tell)
        s, ev = resolve_round(s, pa, d.action)
        trace.append({
            "tell": None if d.tell is None else {
                "clarity": d.tell.clarity.value, "shown": [a.value for a in d.tell.shown],
                "star": d.tell.star.value if d.tell.star else None, "card": d.tell.card,
                "partial": d.tell.partial},
            "opponent": {"kind": d.action.kind.value, "card": d.action.card},
            "player": {"kind": pa.kind.value, "claim": pa.claim, "target": pa.target},
            "events": ev,
            "after": {"round": s.round - 1, "player_hp": s.player_hp, "opp_hp": s.opp_hp,
                      "psych": list(s.psych_end), "outcome": s.outcome, "grade": s.grade},
        })
    return trace
