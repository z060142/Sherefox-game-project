"""Data model for one debate (論戰). Immutable; resolve_round returns new states.

Spec references: 系統規格 Appendix A (A-1..A-15), 數值總表, 各章設計.
Precedence when they disagree: 數值總表 > 系統規格 > 各章設計 > 設計總覽.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PA(str, Enum):
    """Player actions (A-1 step 3)."""

    SOLID = "solid_chain"  # 實證連鎖
    SOPHISTRY = "sophistry"  # 詭辯
    PARRY = "parry"  # 反駁
    OBSERVE = "observe"  # 觀察


class OA(str, Enum):
    """Opponent actions. ALL_IN is the scripted tail attack 玉石俱焚 (A-9)."""

    CLAIM = "claim"  # 主張
    RUSH = "rush"  # 猛攻
    REINFORCE = "reinforce"  # 補強
    TRAP = "trap"  # 設陷
    ALL_IN = "all_in"  # 玉石俱焚 (tail, culprit)


ATTACKS = frozenset({OA.CLAIM, OA.RUSH, OA.ALL_IN})
DEFENSES = frozenset({OA.REINFORCE, OA.TRAP})
# Canonical order for weighted draws (policy trace contract).
OPP_ORDER = (OA.CLAIM, OA.RUSH, OA.REINFORCE, OA.TRAP)


class Clarity(str, Enum):
    CLEAR = "clear"  # 明示
    FUZZY = "fuzzy"  # 模糊
    DISGUISE = "disguise"  # 偽裝


# Card flags (系統規格 2.8).
STRONG = "strong"  # 強攻
SCANDAL = "scandal"  # 醜聞 (equivalent to the 醜聞 tag)
MOTIVE = "motive"  # 動機
EXTRINSIC = "extrinsic"  # 鏈外事實 (all golden clues)
BREAKER = "breaker"  # 破防 golden clue (A-8 trigger 3)
SUBSTITUTE = "substitute"  # 次級替代證物

TAG_PERSON = "人物"
TAG_SCANDAL = "醜聞"


@dataclass(frozen=True)
class Card:
    id: str
    tags: tuple[str, ...]
    grade: str = "normal"  # normal | key | story | golden | substitute
    flags: frozenset[str] = frozenset()
    reason_correct: bool = True
    grazing: frozenset[str] = frozenset()  # tags marked 擦邊

    @property
    def is_scandal(self) -> bool:
        # 2.8: 「醜聞」旗標等同【醜聞】標籤
        return SCANDAL in self.flags or TAG_SCANDAL in self.tags

    @property
    def is_golden(self) -> bool:
        return self.grade == "golden"


@dataclass(frozen=True)
class ClaimNodeDef:
    id: str
    tags: frozenset[str]
    refuters: frozenset[str]  # card ids (the 破解證物 column)
    truth: str = "false"
    # SPEC-QUESTION: Ch.1-3 node tables give no node tags. Fixtures derive node tags
    # as the union of the refuting cards' tags; `tags_inferred` marks that.
    tags_inferred: bool = True


@dataclass(frozen=True)
class BoardNode:
    id: str
    kind: str = "normal"  # normal | fragile | second_claim | last_stand


@dataclass(frozen=True)
class Board:
    """Locked clue board: up to 3 chains (2..5 cards each), plus loose cards."""

    chains: tuple[tuple[str, ...], ...]
    loose: tuple[str, ...] = ()

    def all_cards(self) -> tuple[str, ...]:
        out = [c for ch in self.chains for c in ch]
        out += [c for c in self.loose if c not in out]
        return tuple(out)


@dataclass(frozen=True)
class OpponentProfile:
    name: str
    otype: str  # culprit | protector | rival | wolfhart
    weights: tuple[tuple[OA, int], ...]  # 數值總表 四、對手 AI
    available: frozenset[OA]
    rules: frozenset[int]  # behaviour rules 1..5 that apply (各章設計 對手行為表)
    clarity_mix: tuple[int, int, int]  # (clear, fuzzy, disguise) percentages
    tutorial_clear: bool = False  # 教學章: every tell is 明示 (basis 教學)
    can_disguise: bool = False
    gestures: tuple[tuple[OA, str], ...] = ()


@dataclass(frozen=True)
class TailSpec:
    kind: str  # "culprit_all_in" (犯人 玉石俱焚); protector/rival not modelled for Ch.1-3
    second_claim: ClaimNodeDef
    min_cards: int = 2  # 反駁＋2 張以上、只含實證、含第二說詞破解證物的鏈段


@dataclass(frozen=True)
class CaseConfig:
    case_id: str
    chapter: int
    stage: str  # early | mid | late
    player_max_hp: float | None  # None: Ch.1 (不扣血)
    opp_max_hp: float | None
    node_cap: int
    node_pool: tuple[ClaimNodeDef, ...]
    cards: tuple[Card, ...]
    opponent: OpponentProfile
    claim_base: float = 26.0
    break_pct: int = 70
    tail_wrong: float = 30.0
    tail_rounds: int = 1
    breakline_pct: int | None = None  # 破防線 (early: none)
    hachiku_mode: str = "off"  # off | preview | on
    konju_enabled: bool = False
    shissu_enabled: bool = False
    sophistry_unlocked: bool = False  # 詭辯 Ch.4 才解鎖 (破竹 read-right table)
    assist_charges: int = 1
    fox_charges: int = 2
    tail: TailSpec | None = None
    break_rule: str = "early_generic"  # early_generic | ch1_e0103
    ch1_card: str | None = None  # Ch.1: the break card (E01_03)
    contradiction_target: int | None = None  # Ch.1: 2
    contradiction_deadline: int | None = None  # Ch.1: 3 rounds
    ch1_deadline_rule: str = "numbers"  # "numbers" (break by R3) | "a13" (2 contradictions by R3)
    golden_primary: frozenset[str] = frozenset()  # Ch.3: {"E03_04", "G-01"}

    def card(self, cid: str) -> Card:
        for c in self.cards:
            if c.id == cid:
                return c
        raise KeyError(cid)

    def node_def(self, nid: str) -> ClaimNodeDef:
        for n in self.node_pool:
            if n.id == nid:
                return n
        if self.tail and self.tail.second_claim.id == nid:
            return self.tail.second_claim
        raise KeyError(nid)


@dataclass(frozen=True)
class PlayerAction:
    kind: PA
    segment: tuple[str, ...] = ()  # attack segment; or parry chain (break round / tail)
    target: str | None = None  # attack target (default: lit node)
    card: str | None = None  # parry: single refuting card
    assist: bool = False  # 援護 armed before lock


@dataclass(frozen=True)
class OpponentAction:
    kind: OA
    lit: str | None = None  # 亮起節點
    scripted: bool = False  # A-11 script override (tail etc.)


@dataclass(frozen=True)
class RoundLog:
    round: int
    player_action: PlayerAction
    opponent_action: OpponentAction
    player_hp: tuple[float | None, float | None]
    opp_hp: tuple[float | None, float | None]
    nodes: tuple[tuple[str, ...], tuple[str, ...]]
    hachiku: tuple[int, int]
    events: tuple


@dataclass(frozen=True)
class DebateState:
    case: CaseConfig
    board: Board
    round: int = 1
    player_hp: float | None = None
    opp_hp: float | None = None
    nodes: tuple[BoardNode, ...] = ()
    removed: tuple[str, ...] = ()  # removed script nodes, in removal order
    fragile_seq: int = 0
    # 動搖: "none" | "armed" (triggered; next round is the break round) | "held" (broken, until tail end)
    shaken: str = "none"
    in_tail: bool = False
    tail_rounds_left: int = 0
    break_voids: int = 0
    hachiku: int = 0
    konju_left: int = 0
    konju_parry_used: bool = False
    konju_hp_used: bool = False
    parry_count: int = 0
    shissu_left: int = 0
    assist_left: int = 0
    fox_left: int = 0
    infamy: int = 0
    snapped: tuple[tuple[frozenset, int], ...] = ()  # (link, last round it is absent)
    assisted_links: frozenset = frozenset()
    # behaviour-rule memory (A-3)
    opp_history: tuple[OA, ...] = ()
    last_player_action: PA | None = None
    last_node_removed: bool = False
    last_reinforce_success: bool = False
    no_reinforce_next: bool = False
    must_attack_next: bool = False
    rule3_fired: bool = False
    rule3_pending: bool = False
    next_clear_basis: str | None = None  # "observe"
    contradictions: int = 0
    outcome: str | None = None  # "win" | "loss"
    over: bool = False
    golden_used: tuple[str, ...] = ()
    break_label: str | None = None
    log: tuple[RoundLog, ...] = ()

    def node_ids(self) -> tuple[str, ...]:
        return tuple(n.id for n in self.nodes)

    def normal_node_count(self) -> int:
        """Nodes that count for claim damage (fragile excluded, 數值總表 五 / A-1).
        SPEC-QUESTION: A-6 says fragile nodes 「計入主張傷害的節點數」; 數值總表 and A-1 say
        they do not. 數值總表 wins."""
        return sum(1 for n in self.nodes if n.kind != "fragile")


def initial_state(case: CaseConfig, board: Board) -> DebateState:
    """Round 1 starts at the node cap (A-1 step 1)."""
    nodes = tuple(BoardNode(n.id) for n in case.node_pool[: case.node_cap])
    return DebateState(
        case=case,
        board=board,
        player_hp=case.player_max_hp,
        opp_hp=case.opp_max_hp,
        nodes=nodes,
        assist_left=case.assist_charges,
        fox_left=case.fox_charges,
    )
