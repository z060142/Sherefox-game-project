"""Known set and claim display (§3.2, §3.4, §6.5).

* 正論 / 詭辯 is decided by what the player knows: a claim whose conflict list holds any
  known item shows as 詭辯. Psych-card claims always show as 詭辯 (§3.2).
* Known = carried evidence + appraisals done + notes found (Loadout), plus two kinds of
  opponent speech (§3.2, R-06): a line he used to 駁倒 the player (``said:`` items of
  ch §6.6) and an unfavourable fact the player caught with 抓住他的話.
  Playing the picked-up handkerchief P07 does not make "said:鎖匠昨晚回來過" known
  (design ruling, rules 0.6; ch §5.2 corrected in ea48cc1).
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


# --------------------------------------------------------------------------- E8 picker tags


def restate(s: State, claim_id: str) -> bool:
    """UI_V2_CLAIM_RESTATE (E8): the claim was knocked off her chain and may be raised again at x0.5 (§3.4): in the
    picker, not standing, not void. 抓住他的話 never is."""
    if is_catch(claim_id):
        return False
    v = view(s, claim_id)
    return v.available and not v.standing and claim_id in s.knocked_claims


def void_rows(s: State) -> list[str]:
    """UI_V2_CLAIM_VOID (E8): claims refuted this debate (void, §3.4 / R-21) whose evidence is carried and unlocked: the
    picker lists them greyed with the tag, after the available ones of their evidence (data order). Never selectable."""
    out = []
    for cid in s.voided:
        c = s.ch.claims[cid]
        if c.evidence in s.loadout.carried and all(u in s.known for u in c.unlock):
            out.append(cid)
    order = list(s.ch.claims)
    return sorted(out, key=order.index)
