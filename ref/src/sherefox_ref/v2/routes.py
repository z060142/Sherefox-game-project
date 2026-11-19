"""The four worked playthroughs of ch §12 (routes A-D), as forced-opponent replays.

SPEC-QUESTION (route tables vs rules / rulings; the tests mark these rows xfail):
* §12.1 R5 tell 周旋★/立論: decoy 立論 is unavailable (rule ⑤ after 立論 in R3, R4).
* §12.2 R5 and §12.4 R7: a third 立論 in a row breaks rule ⑤ (必定).
* §12.3 R7 and §12.4 R4: ★ on the decoy (ch §11 wording) vs the ruling (★ only on the
  true action).
* §12.3 R4: 06A is exclusive with 06C (said in R3); the red crack (−10, c = 3) is
  missing, so R4-R8 HP and the ending differ (rules-correct: he is at 21.05 after R8).
* §12.3 R6: 選項所剩無幾 (pressure −10) is missing; R6/R7 pressure differ.
* §12.3 R8: 破竹 stays 1 although 10A lands on his 周旋 (rules: 2).
* §12.4 R7: combo 3 after the reverse ronpa (rules §5.1: reset to 0).

Each round is (player action, opponent action, stated tell). The opponent's moves and
tells are taken from the route tables as written; ``replay`` feeds them straight into
resolve_round (the policy is bypassed) and records, per round, whether the policy could
have produced that move and tell (``policy.can_produce``).
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import OA, PA, Loadout, OpponentAction, PlayerAction, initial_state, tell
from .policy import can_produce
from .resolve import resolve_round

V, C = "vague", "clear"
AT, FO, RE, PR, LAST, NONE = OA.ATTACK, OA.FORCE, OA.REBUT, OA.PARRY, OA.LAST, OA.NONE


def argue(claim, guard=False):
    return PlayerAction(PA.ARGUE, claim, guard=guard)


def cut(claim, guard=False):
    return PlayerAction(PA.INTERCEPT, claim, guard=guard)


def stall(guard=False):
    return PlayerAction(PA.STALL, guard=guard)


def end_cut(claim):
    return PlayerAction(PA.CUT, claim)


def accept():
    return PlayerAction(PA.ACCEPT)


def last_stand(claim, target=None):
    return PlayerAction(PA.LAST_STAND, claim, target)


def opp(kind, card=None):
    return OpponentAction(kind, card)


@dataclass(frozen=True)
class Route:
    name: str
    loadout: Loadout
    rounds: tuple  # ((PlayerAction, OpponentAction, Tell | None), ...)


# ch §3.2: PN3 needs HS04 + HS05, and HS05 also gives OBS01, so OBS01 is known wherever
# the route says PN3 was seen.
ALL_NOTES = ("PN1", "PN2", "PN3", "PN4", "OBS01")

ROUTES = {
    # ch §12.1
    "A": Route("A", Loadout(("E01", "E02", "E04", "E05", "E06", "E07", "E08", "E10", "E11"),
                            ("A01", "A04"), ALL_NOTES), (
        (cut("11A"), opp(AT, "L1"), tell(V, (AT, FO), card="L1")),
        (argue("04A"), opp(PR), tell(V, (PR, AT), star=PR)),
        (argue("06A"), opp(AT, "F1"), tell(C, (AT,), card="F1")),
        (cut("01A"), opp(AT, "L2"), tell(V, (AT, FO), star=AT, card="L2")),
        (argue("08A"), opp(PR), tell(V, (PR, AT), star=PR)),
        (argue("10A"), opp(AT, "F2"), tell(C, (AT,), card="F2")),
        (cut("07A"), opp(FO, "L4"), tell(C, (FO,), card="L4")),
        (argue("11B"), opp(PR), tell(V, (PR, AT), star=PR)),
        (end_cut("04B"), opp(LAST, "K1"), tell(C, (LAST,), card="K1")),
    )),
    # ch §12.2
    "B": Route("B", Loadout(("E01", "E02", "E04", "E05", "E06", "E07", "E08", "E10", "P1"),
                            ("A01", "A02"), ALL_NOTES), (
        (argue("P1A"), opp(AT, "L1"), tell(V, (AT, FO), card="L1")),
        (stall(), opp(RE), tell(V, (RE, AT), star=RE)),
        (argue("02C"), opp(AT, "F1"), tell(C, (AT,), card="F1")),
        (argue("08B"), opp(AT, "U1"), tell(V, (AT, FO), star=AT, card="U1", partial=True)),
        (argue("CATCH"), opp(AT, "F2"), tell(V, (AT, FO), star=AT, card="F2")),
    )),
    # ch §12.3
    "C": Route("C", Loadout(("E01", "E02", "E03", "E04", "E06", "E07", "E08", "E09", "E10"),
                            ("A02", "A04"), ("PN1", "PN3", "OBS01")), (
        (cut("06B"), opp(AT, "L1"), tell(V, (AT, FO), card="L1")),
        (stall(), opp(RE), tell(V, (RE, PR), star=RE)),
        (cut("06C"), opp(AT, "F1"), tell(C, (AT,), card="F1")),
        (cut("06A"), opp(FO, "L2"), tell(C, (FO,), card="L2")),
        (accept(), opp(LAST, "P05"), tell(C, (LAST,), card="P05")),
        (argue("09A"), opp(FO, "F2"), tell(C, (FO,), card="F2")),
        (cut("07A"), opp(FO, "L4"), tell(V, (AT, FO), star=AT, card="L4")),
        (argue("10A"), opp(PR), tell(V, (PR, AT), star=PR)),
    )),
    # ch §12.4
    "D": Route("D", Loadout(("E01", "E02", "E03", "E04", "E06", "E08", "E10", "E11", "E12"),
                            ("A02",), (), warmup="fail"), (
        (cut("11A"), opp(AT, "L1"), tell(V, (AT, FO), card="L1")),
        (argue("04A"), opp(PR), tell(V, (PR, AT), star=PR)),
        (cut("01B"), opp(AT, "F1"), tell(C, (AT,), card="F1")),
        (argue("06B"), opp(RE), tell(V, (AT, RE), star=AT)),
        (argue("10A"), opp(AT, "L2"), tell(C, (AT,), card="L2")),
        (argue("08A"), opp(AT, "F2"), tell(C, (AT,), card="F2")),
        (argue("02A"), opp(AT, "L4"), tell(V, (AT, FO), star=AT, card="L4")),
        (last_stand("11B", "L1"), opp(NONE), None),
    )),
}


@dataclass
class Replay:
    states: list  # states[0] = initial, states[i] = after round i
    events: list  # events[i] = events of round i (events[0] = [])
    producible: list  # producible[i] = policy could produce round i's move + tell


def replay(route: Route | str) -> Replay:
    if isinstance(route, str):
        route = ROUTES[route]
    s = initial_state(route.loadout)
    states, events, prod = [s], [[]], [None]
    for pa, oa, t in route.rounds:
        if s.outcome:
            break
        prod.append(can_produce(s, oa, t))
        s, ev = resolve_round(s, pa, oa)
        states.append(s)
        events.append(ev)
    return Replay(states, events, prod)
