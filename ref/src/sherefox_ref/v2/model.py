"""v2 debate model: rule constants, actions, loadout and the debate state.

Section numbers: "§x.y" = 00_core_rules.md (rules 0.5); "ch §x" = 11_demo_chapter.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .data import Chapter, load_chapter

# --------------------------------------------------------------------------- rule constants
# §7.1 / ch §0.1
BASE_PROPER = 12.0
BASE_SOPH = 16.0
BASE_CATCH = 18.0  # §6.5: already includes the bonus; combo etc. still apply (V-05)
COMBO_STEP = 0.25
COMBO_CAP = 5
CONTINUATION = 1.2
RERAISE_MULT = 0.5  # §3.4: a knocked-off claim raised again
HACHIKU_STEP = 0.10
HACHIKU_MAX = 3
BROKEN_BONUS = 1.25  # only on 論證, not on fixed damage (R-26)
# §6.3 / ch §0.1
INTERCEPT_DMG = 20.0
INTERCEPT_FORCE_EXTRA = 10.0
DISMANTLE_DMG = 10.0
WHIFF = 5.0
FACT_MISS = 10.0
EXPOSED = 25.0
REFUTED = 15.0
STALEMATE = 3.0
STALL_REPEAT_EXTRA = 3.0
CONTRADICTION = 10.0  # §3.4 red crack
FORCE_MULT = 1.25
RAGE_FORCE_MULT = 1.25  # §8.3
SHISSHU_MULT = 1.25  # §7.2
HEAL = 5.0
# §7.4 / §7.5
LAST_PER_CRACK = 15.0
LAST_PICKED_EXTRA = 10.0
LAST_HEAL_PER_CRACK = 0.12
LAST_HEAL_CAP = 0.45
LAST_ZERO_C_DMG = 20.0
LAST_ZERO_C_HEAL = 0.10
DYING_DMG = 10.0
LAST_BAD_CUT = 5.0
COMEBACK_RATIO = 0.30
KEY_HP_RATIO = 0.5  # §7.3 抓漏洞: his credibility <= 50% (at round start, R-25 / ASSUMPTION-30)
# §8
FLOAT_BAND = 15.0
SLIP_PCT = 30
FEW_OPTIONS_AT = 2
# §9 / §10
TRUTH_FALSE_CLAIM = 15
TRUTH_DENIAL = 20
TRUTH_KEY_LEFT = 10
REP_GRADE = {1: 6, 2: 4, 3: 3, 4: 1, 5: -4}
REP_PER_CRACK = -1
REP_CRACK_CAP = -5
REP_PRIVATE = -3
REP_PSYCH_CARD = -2
REP_STALLS = -1
REP_STALLS_AT = 3
REP_DENIAL = -2

P, G, A = 0, 1, 2
CATCH = "CATCH"  # pseudo evidence/claim prefix for 抓住他的話


class PA(str, Enum):
    ARGUE = "argue"  # 議論 (正論 / 詭辯 / 心理牌 / 抓住他的話: claim "CATCH")
    INTERCEPT = "intercept"  # 反駁・截斷
    DISMANTLE = "dismantle"  # 反駁・拆台
    STALL = "stall"  # 打迷糊仗
    CUT = "cut"  # endgame: 截斷 his last card (§7.4)
    ACCEPT = "accept"  # endgame: 承受; 7.5: give up
    LAST_STAND = "last_stand"  # §7.5 the player's own last card


class OA(str, Enum):
    ATTACK = "attack"  # 立論
    FORCE = "force"  # 強辯
    REBUT = "rebut"  # 反駁
    PARRY = "parry"  # 周旋
    LAST = "last"  # §7.4 last card / dying gasp (scripted)
    NONE = "none"  # §7.5 round: he does not act


ACTIONS = (OA.ATTACK, OA.FORCE, OA.REBUT, OA.PARRY)  # canonical order for draws
ACTION_BY_NAME = {"attack": OA.ATTACK, "force": OA.FORCE, "rebut": OA.REBUT, "parry": OA.PARRY,
                  "立論": OA.ATTACK, "強辯": OA.FORCE, "反駁": OA.REBUT, "周旋": OA.PARRY}


class Clarity(str, Enum):
    CLEAR = "clear"
    VAGUE = "vague"


@dataclass(frozen=True)
class PlayerAction:
    kind: PA
    claim: str | None = None  # claim id, or "CATCH"
    target: str | None = None  # dismantle / last stand: card id on his chain
    guard: bool = False  # 援護 (§5.3 step 2)


@dataclass(frozen=True)
class OpponentAction:
    kind: OA
    card: str | None = None


@dataclass(frozen=True)
class Tell:
    clarity: Clarity
    shown: tuple  # canonical-order tuple of OA (1 for clear, 2 for vague)
    star: OA | None = None  # 較可能★
    card: str | None = None  # the line he is about to say (attack only)
    partial: bool = False  # slip: only the first half is shown (V-02)

    def key(self):
        return (self.clarity, frozenset(self.shown), self.star, self.card, self.partial)


def tell(clarity, shown, star=None, card=None, partial=False) -> Tell:
    """Build a Tell with `shown` normalised to canonical order."""
    order = {a: i for i, a in enumerate((*ACTIONS, OA.LAST))}
    return Tell(Clarity(clarity), tuple(sorted(set(shown), key=order.__getitem__)), star, card, partial)


class IllegalAction(ValueError):
    pass


@dataclass(frozen=True)
class Loadout:
    carried: tuple[str, ...]
    appraisals: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()  # observations / person notes the player found
    warmup: str = "pass"  # pass_clean / pass / fail (ch §2 S04)


# --------------------------------------------------------------------------- state


@dataclass
class PNode:
    claim: str
    issue: str
    soph: bool
    cracked: bool
    psych_card: bool = False


@dataclass
class ONode:
    card: str
    issue: str | None


@dataclass
class RecordEntry:
    """One line of the player's public record (§2 公開紀錄)."""

    round: int
    claim: str
    use: str  # argue / intercept / dismantle / cut / last_stand
    soph: bool
    crack: bool
    true: bool


@dataclass
class State:
    ch: Chapter
    loadout: Loadout
    round: int = 1  # the round about to be played
    player_hp: float = 0.0
    opp_hp: float = 0.0
    player_chain: list = field(default_factory=list)
    opp_chain: list = field(default_factory=list)
    player_combo: int = 0
    opp_combo: int = 0
    hachiku: int = 0
    broken_until: int = 0  # 破防 lasts through the end of this round number
    shisshu: bool = False  # 失守 active (§7.2)
    psych: list = field(default_factory=lambda: [0.0, 0.0, 0.0])  # current (after decay)
    psych_end: tuple = (0.0, 0.0, 0.0)  # after the last round's events, before decay
    over: list = field(default_factory=lambda: [False, False, False])
    known: set = field(default_factory=set)
    record: list = field(default_factory=list)
    cracks: int = 0
    denials: int = 0
    voided: set = field(default_factory=set)  # claims 駁倒'd: void for this debate
    knocked_claims: set = field(default_factory=set)  # removed from the chain: re-raise x0.5
    psych_used: set = field(default_factory=set)  # once-per-debate claim effects already fired
    hand: list = field(default_factory=list)  # his cards in hand (normal + unfav + held pickups)
    reraised: list = field(default_factory=list)  # cards returned by 周旋, in order
    knocked: list = field(default_factory=list)  # his knocked lies (re-raisable), in order
    picked: tuple = ()  # evidence ids he picked up
    reserved_last: str | None = None  # picked-up card kept as his last card
    scripted_last: str | None = None  # K1
    last_card_used: bool = False
    endgame: dict | None = None  # pending endgame round: {"trigger", "card", "dying"}
    ronpa_done: bool = False
    reversed: bool = False
    player_locked: bool = False  # §7.5 round pending
    rule3_fired: bool = False
    rule3_pending: bool = False
    next_clear: bool = False  # 打迷糊仗 baited a rebuttal: next tell clear
    no_intercept_round: int = 0  # §6.3: his 立論 cannot be intercepted in this round
    stall_streak: int = 0
    stalls: int = 0
    catch_card: str | None = None  # 抓住他的話 available this round (the unfav card)
    catch_next: str | None = None
    next_unfav: bool = False  # §8.3 pressure crossing: next 立論 plays an unfavourable fact
    few_fired: bool = False
    opp_history: list = field(default_factory=list)
    flag_player_soph: bool = False  # rule ② condition (last round)
    flag_knocked_lie: str | None = None  # rule ① condition (last round)
    flag_hit_player: bool = False  # rule ④ condition (last round)
    guard_used: bool = False
    privates: int = 0
    psych_card_uses: int = 0
    both_zero: bool = False
    crossed: list = field(default_factory=lambda: [False, False, False])
    outcome: str | None = None  # win / loss
    grade: int | None = None
    end_reason: str | None = None

    # -- helpers
    def chain_claims(self) -> list[str]:
        return [n.claim for n in self.player_chain]

    def said(self) -> list[str]:
        return [r.claim for r in self.record]

    def broken_now(self) -> bool:
        return self.broken_until >= self.round

    def opp_locked(self) -> bool:
        return self.endgame is not None


def pickups_for(ch: Chapter, carried) -> tuple[str, ...]:
    """§4.2 / ch §3.4: cards he gets from left-behind evidence, by pickup priority, max N."""
    left = [e for e in ch.pickup_priority if e not in carried and ch.evidence[e].opponent_use]
    return tuple(ch.evidence[e].opponent_use for e in left[: ch.max_pickup])


def never_in_hand(ch: Chapter) -> str | None:
    """The picked-up card that is never in his hand (E8, class D of docs/d01-string-coverage.md): the card of the first
    evidence in pickup priority. Whenever it is picked up it is picked first, so initial_state keeps it as his last
    card (ch §3.4 / §6.5); it is never said as 立論 or 強辯 (its _PUSH line cannot show)."""
    if not (ch.last_card_order and ch.last_card_order[0] == "@pickup"):
        return None
    first = next((e for e in ch.pickup_priority if ch.evidence[e].opponent_use), None)
    return ch.evidence[first].opponent_use if first else None


def validate_loadout(ch: Chapter, lo: Loadout) -> None:
    if len(lo.carried) > ch.carry_limit:
        raise IllegalAction(f"carrying {len(lo.carried)} > {ch.carry_limit}")
    for e in lo.carried:
        if e not in ch.evidence:
            raise IllegalAction(f"unknown evidence {e}")
    limit = ch.warmup[lo.warmup]["appraisal_limit"]
    if len(lo.appraisals) > limit:
        raise IllegalAction(f"{len(lo.appraisals)} appraisals > {limit}")
    for a in lo.appraisals:
        if a not in ch.appraisals:
            raise IllegalAction(f"unknown appraisal {a}")
    for n in lo.notes:
        if n not in ch.optional_known:
            raise IllegalAction(f"unknown note {n}")


def initial_state(lo: Loadout, ch: Chapter | None = None) -> State:
    ch = ch or load_chapter()
    validate_loadout(ch, lo)
    s = State(ch=ch, loadout=lo)
    s.player_hp = ch.player_max_hp
    s.opp_hp = ch.opp_max_hp
    s.psych = list(ch.psych_start)
    s.psych_end = tuple(ch.psych_start)
    s.known = set(lo.carried) | set(lo.appraisals) | set(lo.notes)
    picked = pickups_for(ch, lo.carried)
    s.picked = tuple(ch.cards[c].source for c in picked)
    # ch §3.4 / §6.5: the highest-priority picked-up card is kept as the last card
    if picked and ch.last_card_order and ch.last_card_order[0] == "@pickup":
        s.reserved_last = picked[0]
        held = list(picked[1:])
    else:
        held = list(picked)
    s.scripted_last = next((c for c in ch.last_card_order if not c.startswith("@")), None)
    s.hand = [c.id for c in ch.cards.values() if c.kind in ("lie", "fav", "unfav")] + held
    return s
