"""Known set and claim display (§3.2, §3.4, §6.5).

* 正論 / 詭辯 is decided by what the player knows: a claim whose conflict list holds any
  known item shows as 詭辯. Psych-card claims always show as 詭辯 (§3.2).
* Known = carried evidence + appraisals done + notes found (Loadout), plus two kinds of
  opponent speech (§3.2, R-06): a line he used to 駁倒 the player (``said:`` items of
  ch §6.6) and an unfavourable fact the player caught with 抓住他的話.
  SPEC-QUESTION: ch §5.2 (note under the table) says 04C also turns 詭辯 when he plays
  the picked-up handkerchief P07; rules §3.2 allow only the two cases above, so playing
  P07 does not make "said:鎖匠昨晚回來過" known here (rules win on how a rule works).
* Red crack: the claim is exclusive with a claim on the player's public record (§3.4).
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import CATCH, State


@dataclass(frozen=True)
class ClaimView:
    id: str
    issue: str
    available: bool  # shown in the list (evidence carried, unlocked, not void)
    soph: bool  # displayed as 詭辯
    red_crack: bool
    standing: bool  # already on the chain (cannot be attached again; can still refute)
    true: bool
    psych_card: bool = False


def is_catch(claim_id: str | None) -> bool:
    return claim_id is not None and claim_id.startswith(CATCH)


def displayed_soph(s: State, claim_id: str) -> bool:
    if is_catch(claim_id):
        return False  # §6.5: counts as 正論
    c = s.ch.claims[claim_id]
    if c.psych_card:
        return True
    return any(k in s.known for k in c.conflicts)


def red_crack(s: State, claim_id: str) -> bool:
    if is_catch(claim_id):
        return False
    excl = set(s.ch.claims[claim_id].exclusive)
    return any(r.claim in excl for r in s.record)


def view(s: State, claim_id: str) -> ClaimView:
    if is_catch(claim_id):
        card = s.catch_card
        ok = card is not None and claim_id in (CATCH, f"{CATCH}:{card}")
        issue = s.ch.cards[card].issue if card else ""
        return ClaimView(claim_id, issue, ok, False, False, False, True)
    c = s.ch.claims[claim_id]
    available = (
        c.evidence in s.loadout.carried
        and all(u in s.known for u in c.unlock)
        and claim_id not in s.voided
    )
    return ClaimView(
        claim_id,
        c.issue,
        available,
        displayed_soph(s, claim_id),
        red_crack(s, claim_id),
        claim_id in s.chain_claims(),
        c.true,
        c.psych_card,
    )


def claim_list(s: State) -> list[ClaimView]:
    """The 說法選擇器 contents for this round, in data order (catch first, ch §13)."""
    out = []
    if s.catch_card is not None:
        out.append(view(s, f"{CATCH}:{s.catch_card}"))
    out += [v for v in (view(s, cid) for cid in s.ch.claims) if v.available]
    return out
