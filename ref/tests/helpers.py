from __future__ import annotations

from sherefox_ref import events as E
from sherefox_ref.model import OA, PA, OpponentAction, PlayerAction
from sherefox_ref.policy import possible_tells
from sherefox_ref.model import Clarity
from sherefox_ref.resolve import resolve_round

APPROX = 1e-9


def step(state, pa, oa):
    return resolve_round(state, pa, oa)


def parry(card=None, segment=()):
    return PlayerAction(PA.PARRY, card=card, segment=tuple(segment))


def solid(*segment, target=None, assist=False):
    return PlayerAction(PA.SOLID, segment=tuple(segment), target=target, assist=assist)


def observe():
    return PlayerAction(PA.OBSERVE)


def opp(kind, lit=None, scripted=False):
    return OpponentAction(kind, lit, scripted)


def of(events, cls):
    return [e for e in events if isinstance(e, cls)]


def removed_ids(events, cause=None):
    return [e.node_id for e in of(events, E.NodeRemoved) if cause is None or e.cause == cause]


def played_full(events):
    return [e.id for e in of(events, E.CutIn) if e.played_full]


def tell_key(clarity, shown, star=None, basis=None, actual=None):
    return (clarity, frozenset(shown), star, basis, actual)


def can_tell(state, clarity, shown, star, basis, actual):
    return tell_key(clarity, shown, star, basis, actual) in possible_tells(state)


__all__ = [
    "APPROX", "step", "parry", "solid", "observe", "opp", "of", "removed_ids", "played_full",
    "can_tell", "OA", "PA", "Clarity", "E",
]
