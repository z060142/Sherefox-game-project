"""UI_V2_DMG_PREVIEW (v2 demo E8, design ruling): the argument a claim would deal if her link lands this round.

Computed from the round-start state and only from what the player sees (plan §2 decision 4): her combo (the next link
makes it combo + 1), 破竹 layers, his 破防 (guard down), whether the claim follows her chain's last link (same issue or a
scripted 承接 pair, 延續加成 x1.2) and whether it is a restated claim (x0.5); a red-crack claim first withdraws the
claims of her chain it contradicts, so the link it follows is the one left last. It never reads his hidden gauges, his
hand or his coming action: when his action changes what happens (he rebuts: blocked, exposed or refuted; the link does
not land) the preview is simply not dealt. When the link lands it equals resolve._player_attach's damage exactly
(00_core_rules §7.1: base x combo x continuation x re-raise x 破竹 x 破防; tests/test_v2_preview.py).
"""

from __future__ import annotations

from . import known as K
from .model import BASE_CATCH, BASE_PROPER, BASE_SOPH, BROKEN_BONUS, CONTINUATION, HACHIKU_STEP, RERAISE_MULT, State
from .resolve import combo_mult


def preview(s: State, claim_id: str) -> float | None:
    """The argument of 議論 with `claim_id` (CATCH / CATCH:<card> for 抓住他的話) at the start of this normal round;
    None when it cannot be argued (not in the picker, standing, not a normal round)."""
    if s.outcome or s.endgame is not None or s.player_locked:
        return None
    v = K.view(s, claim_id)
    if not v.available or v.standing:
        return None
    catch = K.is_catch(claim_id)
    if catch:
        claim_id = f"{claim_id.split(':')[0]}:{s.catch_card}"
        base = BASE_CATCH
    else:
        base = BASE_SOPH if v.soph else BASE_PROPER
    chain = list(s.player_chain)
    if v.red_crack:
        excl = set(s.ch.claims[claim_id].exclusive)
        chain = [n for n in chain if n.claim not in excl]
    d = base * combo_mult(s.player_combo + 1)
    prev = chain[-1] if chain else None
    if prev is not None and (prev.issue == v.issue or (prev.claim, claim_id) in s.ch.continuations):
        d *= CONTINUATION
    if not catch and claim_id in s.knocked_claims:
        d *= RERAISE_MULT
    d *= 1.0 + HACHIKU_STEP * s.hachiku
    if s.broken_now():
        d *= BROKEN_BONUS
    return d
