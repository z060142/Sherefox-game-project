"""Executable reference model (golden oracle) of the 狐耳摩斯 debate rules, Ch.1-3."""

from .model import (  # noqa: F401
    OA,
    PA,
    Board,
    Card,
    CaseConfig,
    Clarity,
    DebateState,
    OpponentAction,
    PlayerAction,
    initial_state,
)
from .policy import RngChooser, decide_next, possible_tells, use_fox_instinct  # noqa: F401
from .resolve import resolve_round  # noqa: F401
from .rng import SplitMix64  # noqa: F401
from .rules import IllegalAction  # noqa: F401
