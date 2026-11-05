"""Pure rule helpers: link judging, segment checks, damage formulas, break threshold.

Arithmetic contract (for bit-identical ports): every multiplier that is not a power of
two is applied as integer-numerator / integer-denominator in the order written here,
e.g. 破竹 is ``x * (10 + stacks) / 10`` and the chain coefficient is
``14 * (10 + 5*solid + 8*soph) / 10``. Damage keeps decimals (no rounding).
"""

from __future__ import annotations

from .model import (
    STRONG,
    SUBSTITUTE,
    Board,
    Card,
    CaseConfig,
    DebateState,
)

SOLID_LINK = "solid"
SOPH_LINK = "sophistry"


class IllegalAction(ValueError):
    """The action could not have been locked in (button disabled in the UI)."""


def link_kind(a: Card, b: Card) -> str | None:
    """系統規格 2.4 / A-2. Tags are compared by category (SPEC-QUESTION: Ch.1-3 tables
    list tag categories only, no 類別：值 values)."""
    shared = set(a.tags) & set(b.tags)
    if not shared:
        return None
    firm = shared - set(a.grazing) - set(b.grazing)
    if (
        firm
        and a.reason_correct
        and b.reason_correct
        and SUBSTITUTE not in a.flags
        and SUBSTITUTE not in b.flags
        and a.grade != "substitute"
        and b.grade != "substitute"
    ):
        return SOLID_LINK
    return SOPH_LINK


def validate_board(case: CaseConfig, board: Board) -> None:
    """系統規格 2.5: <=3 chains, 2..5 cards, one chain per card, no invalid links."""
    if len(board.chains) > 3:
        raise IllegalAction("MSG_CHAIN_MAX: more than 3 chains")
    seen: set[str] = set()
    for ch in board.chains:
        if not 2 <= len(ch) <= 5:
            raise IllegalAction(f"chain length {len(ch)} outside 2..5")
        for cid in ch:
            if cid in seen:
                raise IllegalAction(f"card {cid} in two chains")
            seen.add(cid)
        for a, b in zip(ch, ch[1:]):
            if link_kind(case.card(a), case.card(b)) is None:
                raise IllegalAction(f"invalid link {a}-{b}")


def segment_links(state: DebateState, segment: tuple[str, ...]) -> list[tuple[str, str, str]]:
    """Return [(a, b, kind)] for a segment, validating that it is a contiguous run of one
    board chain (either direction) or a single card on the board / in the evidence book.
    A snapped sophistry link splits the chain (A-7) so a segment may not span it."""
    if not segment:
        raise IllegalAction("empty segment")
    board = state.board
    if len(segment) == 1:
        if segment[0] not in board.all_cards():
            raise IllegalAction(f"card {segment[0]} not available")
        return []
    for ch in board.chains:
        for seq in (ch, tuple(reversed(ch))):
            n = len(segment)
            for i in range(len(seq) - n + 1):
                if seq[i : i + n] == segment:
                    out = []
                    for a, b in zip(segment, segment[1:]):
                        k = link_kind(state.case.card(a), state.case.card(b))
                        if is_snapped(state, a, b):
                            raise IllegalAction(f"link {a}-{b} is snapped this round")
                        out.append((a, b, k))
                    return out
    raise IllegalAction(f"segment {segment} is not a contiguous run of a board chain")


def is_snapped(state: DebateState, a: str, b: str) -> bool:
    key = frozenset((a, b))
    return any(link == key and state.round <= until for link, until in state.snapped)


def count_links(links) -> tuple[int, int]:
    s = sum(1 for _, _, k in links if k == SOLID_LINK)
    p = sum(1 for _, _, k in links if k == SOPH_LINK)
    return s, p


def segment_tags(case: CaseConfig, segment) -> set[str]:
    out: set[str] = set()
    for cid in segment:
        out |= set(case.card(cid).tags)
    return out


def chain_damage_breakdown(
    solid: int,
    soph: int,
    shaken: bool,
    stacks: int,
    matchup_half: bool,
    fragile_bonus: bool,
) -> tuple[float, tuple]:
    """A-1 modifier order with A-15 破竹 placement:
    base -> 動搖 x1.5 -> 破竹 x(1+0.1*stacks) -> 對決表 x0.5 -> 脆弱 +10."""
    steps = []
    d = 14 * (10 + 5 * solid + 8 * soph) / 10
    steps.append(("base", d))
    if shaken:
        d = d * 3 / 2
        steps.append(("shaken_x1.5", d))
    if stacks:
        d = d * (10 + stacks) / 10
        steps.append((f"hachiku_x{stacks}", d))
    if matchup_half:
        d = d / 2
        steps.append(("matchup_x0.5", d))
    if fragile_bonus:
        d = d + 10
        steps.append(("fragile_+10", d))
    return d, tuple(steps)


def counter_damage(stacks: int) -> tuple[float, tuple]:
    """Parry counter: fixed 30; the only modifier is 破竹 +10%/stack (數值總表 五)."""
    d = 30.0
    steps = [("counter", d)]
    if stacks:
        d = 30 * (10 + stacks) / 10
        steps.append((f"hachiku_x{stacks}", d))
    return d, tuple(steps)


def claim_damage(
    case: CaseConfig,
    n_nodes: int,
    rush: bool,
    konju: bool,
    round_no: int,
    observe_half: bool,
) -> tuple[float, tuple]:
    """Opponent claim = base + 4n (n at round start, fragile excluded); rush x1.25;
    困獸 x1.25; from round 15 +5; observe halves the result."""
    steps = []
    d = case.claim_base + 4 * n_nodes
    steps.append(("claim", d))
    if rush:
        d = d * 5 / 4
        steps.append(("rush_x1.25", d))
    if konju:
        # SPEC-QUESTION: A-15 says 困獸 x1.25 on claim/rush but not where it sits relative
        # to rush and the round-15 +5. Applied right after rush.
        d = d * 5 / 4
        steps.append(("konju_x1.25", d))
    if round_no >= 15:
        # SPEC-QUESTION: 數值總表 says flat "+5 from round 15"; A-1 says "每回合 +5 ... 加在
        # x1.5 之後" (x1.5 looks like the old rush multiplier). Implemented: flat +5 after
        # rush/konju multipliers, before observe halving.
        d = d + 5
        steps.append(("impatience_+5", d))
    if observe_half:
        d = d / 2
        steps.append(("observe_x0.5", d))
    return d, tuple(steps)


def break_threshold_met(state: DebateState, segment: tuple[str, ...], links) -> bool:
    """A-8 (前期 1 件強攻證物，或 2 張以上的實證連鎖), +1 card per voided break,
    -1 card at 破竹 3 (min 1). Ch.1 uses its own case rule (E01_03)."""
    case = state.case
    if case.break_rule == "ch1_e0103":
        # 各章設計 Ch.1: 用反駁或實證連鎖出示 E01_03 並選對理由 (A-8's table starts at Ch.2).
        return case.ch1_card in segment and case.card(case.ch1_card).reason_correct
    if case.stage != "early":
        raise NotImplementedError("mid/late break thresholds are outside Ch.1-3 scope")
    reduce = 1 if (case.hachiku_mode == "on" and state.hachiku >= 3) else 0
    extra = state.break_voids
    s, p = count_links(links)
    all_solid = p == 0
    # chain path: N cards, solid only
    need_chain = max(1, 2 + extra - reduce)
    if all_solid and len(segment) >= need_chain:
        return True
    # strong-card path
    # SPEC-QUESTION: how "論破條件張數 +1" (after a voided break) applies to the
    # "1 件強攻證物" path is not written. Implemented: segment must hold a strong card
    # with the correct reason and have >= 1 + voids - (破竹3) cards (min 1), solid only.
    need_strong = max(1, 1 + extra - reduce)
    has_strong = any(
        STRONG in case.card(c).flags and case.card(c).reason_correct for c in segment
    )
    return has_strong and all_solid and len(segment) >= need_strong
