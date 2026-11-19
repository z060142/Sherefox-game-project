"""The player's legal moves in a state: every complete command the player may lock in this round.

The engine does not reject an illegal command (docs/debate-engine-v2.md §4), so the debate UI must offer exactly
these (v2 demo plan §2 decision 3, tests/check_d1_fuzz.py). Written from the rules (§x = 00_core_rules.md) and the
checks resolve.py makes (IllegalAction), not from the UI:

* Normal round (§5.3, §6.1): 議論 with a claim in the picker that is not on the chain (§3.4; 抓住他的話 included,
  an argue option only, §6.5); 截斷 with an evidence claim of the picker (a claim on the chain may still refute,
  §3.4 R-35); 拆台 with an evidence claim and a link on his chain as the target (§6.1); 打迷糊仗. Each with or
  without 援護 while it is unused (§5.3 step 2: once per debate).
* Endgame round (§7.4, R-03): 截斷 his last card with an evidence claim, or 承受.
* §7.5 round: the player's own last card, an evidence claim with a link on his chain or no target (the ref then
  tries his whole chain), or 放棄 (accept).
* Debate over: nothing.

Choices this module makes where resolve.py alone would accept more (each a rule, not a UI reading):
- 抓住他的話 is not a §7.5 last card: §6.5 adds it to the 議論 list only (resolve.py rejects it in every other use but
  §7.5, where it would simply fail).
- A §7.5 target is a link on his chain (§7.5 「對手鏈上某個謊言」); resolve.py treats an unknown target as a miss.
- 援護 is part of a normal-round command only (§5.3); resolve.py ignores it in the other rounds.
- Actions without a claim or target carry none (resolve.py ignores what they carry).
A claim with a red crack, a 詭辯 or a claim his link does not break is legal: the cost is the rule's (§3.4, §6.4).
"""

from __future__ import annotations

from . import known as K
from .model import CATCH, PA, PlayerAction, State


def picker_claims(s: State) -> list[str]:
    """The claim ids the picker lists this round (known.claim_list order; 抓住他的話 as CATCH:<card>)."""
    return [v.id for v in K.claim_list(s)]


def legal_moves(s: State) -> list[PlayerAction]:
    """Every legal command of this round, in a fixed order (by action, claim in picker order, target in chain
    order, guard off before on)."""
    if s.outcome:
        return []
    views = K.claim_list(s)
    evidence = [v.id for v in views if not K.is_catch(v.id)]
    chain = [n.card for n in s.opp_chain]
    if s.player_locked:
        out = [PlayerAction(PA.LAST_STAND, c, t) for c in evidence for t in [None] + chain]
        return out + [PlayerAction(PA.ACCEPT)]
    if s.endgame:
        return [PlayerAction(PA.CUT, c) for c in evidence] + [PlayerAction(PA.ACCEPT)]
    guards = (False,) if s.guard_used else (False, True)
    out: list[PlayerAction] = []
    for g in guards:
        out += [PlayerAction(PA.ARGUE, v.id, guard=g) for v in views if not v.standing]
        out += [PlayerAction(PA.INTERCEPT, c, guard=g) for c in evidence]
        out += [PlayerAction(PA.DISMANTLE, c, t, guard=g) for c in evidence for t in chain]
        out.append(PlayerAction(PA.STALL, guard=g))
    order = {k: i for i, k in enumerate((PA.ARGUE, PA.INTERCEPT, PA.DISMANTLE, PA.STALL))}
    return sorted(out, key=lambda pa: (order[pa.kind], pa.guard))


def is_legal(s: State, pa: PlayerAction) -> bool:
    """`pa` is one of legal_moves(s); 抓住他的話 may be named CATCH or CATCH:<card>."""
    if pa.claim == CATCH and s.catch_card is not None:
        pa = PlayerAction(pa.kind, f"{CATCH}:{s.catch_card}", pa.target, pa.guard)
    return pa in legal_moves(s)
