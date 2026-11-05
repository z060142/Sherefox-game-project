"""Typed event records emitted by resolve_round, in playback order.

Each record is a frozen dataclass; ``to_dict`` gives a stable, language-neutral
form for golden traces (``{"kind": ..., **fields}``).
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum


def _plain(v):
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, tuple):
        return [_plain(x) for x in v]
    if isinstance(v, frozenset):
        return sorted(_plain(x) for x in v)
    return v


@dataclass(frozen=True)
class Event:
    def to_dict(self) -> dict:
        d = {"kind": type(self).__name__}
        for f in fields(self):
            d[f.name] = _plain(getattr(self, f.name))
        return d


@dataclass(frozen=True)
class Reveal(Event):
    round: int
    player_action: str
    opponent_action: str
    staging: str  # "player_attack_vs_defense" | "defense_vs_attack" | "clash" | "standoff"


@dataclass(frozen=True)
class NodeRemoved(Event):
    node_id: str
    cause: str  # "chain" | "parry" | "fragile_hit" | "break" | "tail_void"


@dataclass(frozen=True)
class NodeAdded(Event):
    node_id: str
    node_kind: str
    cause: str  # "reinforce" | "restate" | "observe" | "tail_start"


@dataclass(frozen=True)
class DamageToOpponent(Event):
    amount: float
    source: str  # "chain" | "counter" | "break" | "tail_finish"
    hp_before: float
    hp_after: float
    breakdown: tuple = ()


@dataclass(frozen=True)
class DamageToPlayer(Event):
    amount: float
    source: str  # "claim" | "rush" | "trap_crit" | "tail_wrong"
    hp_before: float
    hp_after: float
    breakdown: tuple = ()


@dataclass(frozen=True)
class OpponentHealed(Event):
    amount: float
    hp_before: float
    hp_after: float


@dataclass(frozen=True)
class ContradictionCounted(Event):
    count: int
    node_id: str


@dataclass(frozen=True)
class StatusGained(Event):
    status: str  # "shaken" | "konju" | "shissu" | "tail"
    side: str  # "player" | "opponent"
    rounds: int


@dataclass(frozen=True)
class StatusLost(Event):
    status: str
    side: str
    reason: str


@dataclass(frozen=True)
class HachikuChanged(Event):
    before: int
    after: int
    preview: bool


@dataclass(frozen=True)
class InfamyChanged(Event):
    before: int
    after: int


@dataclass(frozen=True)
class AssistSpent(Event):
    wasted: bool


@dataclass(frozen=True)
class LinkSnapped(Event):
    a: str
    b: str
    until_round: int


@dataclass(frozen=True)
class BreakResult(Event):
    success: bool
    via: str  # "solid" | "parry"
    label: str | None = None  # "primary" | "alternative" | None (Ch.3 G-01 labelling)
    golden_used: tuple = ()


@dataclass(frozen=True)
class TailStarted(Event):
    rounds: int
    second_claim: str


@dataclass(frozen=True)
class TailResult(Event):
    correct: bool


@dataclass(frozen=True)
class BreakVoided(Event):
    opp_hp: float
    break_voids: int


@dataclass(frozen=True)
class Message(Event):
    id: str


@dataclass(frozen=True)
class CutIn(Event):
    id: str
    level: str  # "full" | "stamp"
    priority: int | None  # full-screen priority (4.7); None for stamps
    side: str | None  # "player" | "opponent" | None (unspecified)
    played_full: bool = False  # True only for the single full-screen cut-in played this round
    demoted: bool = False  # full-screen cut-in demoted to a stamp


@dataclass(frozen=True)
class DebateEnded(Event):
    result: str  # "win" | "loss"
    reason: str
