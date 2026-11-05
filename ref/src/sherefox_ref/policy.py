"""Opponent policy (系統規格 A-3, 數值總表 四): action choice, tell, fox instinct.

Kept apart from resolve.py so scripted rounds (tail, route replays) can bypass it.

Trace contract — the order of random draws in decide_next (each through a Chooser):
  1. tendency rule follow?      percent(80)                 (only if a tendency rule applies)
  2. action                     weighted(personality)       (if not forced and rule not followed)
     forced "must attack"       weighted(attacks only)
  3. clarity                    weighted(clarity mix)       (only if not fixed by tutorial/basis)
  4. fuzzy decoy                weighted(personality of the remaining actions)  (if needed)
  5. fuzzy left/right order     uniform([0, 1])
  6. lit node                   uniform(visible claim nodes)
RngChooser maps weighted() to rng.roll(sum of weights) over the items in canonical
order (claim, rush, reinforce, trap), percent(p) to rng.roll(100) < p, and uniform(xs)
to xs[rng.roll(len(xs))].
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from . import events as E
from .model import ATTACKS, OA, OPP_ORDER, PA, Clarity, DebateState, OpponentAction

FOLLOW_PCT = 80  # 數值總表 四: 「傾向」約等於 80% 照做


# --------------------------------------------------------------------------- choosers


class RngChooser:
    def __init__(self, rng):
        self.rng = rng

    def weighted(self, items):
        items = [(v, w) for v, w in items if w > 0]
        total = sum(w for _, w in items)
        r = self.rng.roll(total)
        for v, w in items:
            if r < w:
                return v
            r -= w
        raise AssertionError("unreachable")

    def percent(self, p: int) -> bool:
        return self.rng.roll(100) < p

    def uniform(self, xs):
        return xs[self.rng.roll(len(xs))]


class _EnumChooser:
    """Explores every distinct outcome (used by possible_tells)."""

    def __init__(self, path):
        self.path = list(path)
        self.i = 0
        self.branching: list[int] = []

    def _pick(self, options):
        k = self.path[self.i] if self.i < len(self.path) else 0
        self.branching.append(len(options))
        self.i += 1
        return options[k]

    def weighted(self, items):
        return self._pick([v for v, w in items if w > 0])

    def percent(self, p):
        opts = [o for o, ok in ((True, p > 0), (False, p < 100)) if ok]
        return self._pick(opts)

    def uniform(self, xs):
        return self._pick(list(xs))


# --------------------------------------------------------------------------- tell


@dataclass(frozen=True)
class Tell:
    clarity: Clarity
    shown: tuple[OA, ...]  # 1 action (clear/disguise) or 2 candidates left->right (fuzzy)
    star: OA | None  # ★ candidate (fuzzy only)
    star_rule: int | None
    basis: str | None  # 依據小銅牌: tutorial | observe | rule3 | konju | fox | script
    lit: str | None
    gesture: str | None  # always the TRUE action's gesture (A-3)
    rule_applied: int | None = None  # for the opponent notes (行為規則 記錄)

    def key(self):
        return (self.clarity, frozenset(self.shown), self.star, self.basis)


def _weights(state: DebateState, allowed) -> list:
    w = dict(state.case.opponent.weights)
    return [(a, w.get(a, 0)) for a in OPP_ORDER if a in allowed]


def _gesture(state: DebateState, a: OA) -> str | None:
    return dict(state.case.opponent.gestures).get(a)


def decide_next(state: DebateState, chooser) -> tuple[DebateState, OpponentAction, Tell]:
    """Decide the opponent's next action and its tell (A-1 step 6). `state` is the state
    returned by resolve_round (already restated for the coming round)."""
    case = state.case
    prof = case.opponent

    if state.in_tail:
        sc = case.tail.second_claim.id
        act = OA.ALL_IN
        tell = Tell(Clarity.CLEAR, (act,), None, None, "script", sc, _gesture(state, act))
        return state, OpponentAction(act, sc, scripted=True), tell

    available = [a for a in OPP_ORDER if a in prof.available]
    banned: set[OA] = set()
    if state.no_reinforce_next:
        banned.add(OA.REINFORCE)
    if case.konju_enabled and state.konju_left > 0:
        banned.add(OA.REINFORCE)
    rule5_ban = None
    if 5 in prof.rules and len(state.opp_history) >= 2 and state.opp_history[-1] == state.opp_history[-2]:
        rule5_ban = state.opp_history[-1]
        banned.add(rule5_ban)
    allowed = [a for a in available if a not in banned]

    basis = None
    rule_target = None
    rule_no = None
    forced = False
    new_state = state

    if 3 in prof.rules and state.rule3_pending and OA.RUSH in available:
        act, basis, forced = OA.RUSH, "rule3", True
        new_state = replace(new_state, rule3_pending=False)
        rule_no = 3
    elif state.must_attack_next:
        atk = [a for a in available if a in ATTACKS and a != rule5_ban] or [
            a for a in available if a in ATTACKS
        ]
        act = chooser.weighted(_weights(state, atk))
        basis, forced = "observe", True
    else:
        # tendency rules 1, 2, 4 — lowest number wins (A-3)
        cand = []
        if 1 in prof.rules and state.last_node_removed:
            cand.append((1, OA.REINFORCE))
        if 2 in prof.rules and state.last_player_action == PA.SOPHISTRY:
            cand.append((2, OA.TRAP))
        if 4 in prof.rules and state.last_reinforce_success:
            cand.append((4, OA.CLAIM))
        if cand:
            no, tgt = cand[0]
            # SPEC-QUESTION: when the winning tendency rule points at a banned action
            # (A-14: 「不能補強」與規則 1 衝突 → 改依性格傾向) the model drops tendencies
            # entirely rather than falling through to the next rule.
            if tgt in allowed:
                rule_target, rule_no = tgt, no
        if rule_target is not None and chooser.percent(FOLLOW_PCT):
            act = rule_target
        else:
            # SPEC-QUESTION: 「其餘依性格傾向」— the 20% personality draw includes the
            # rule's own action (effective follow rate 80% + 20%·w). Not stated either way.
            act = chooser.weighted(_weights(state, allowed))

    # ---- clarity (A-3 table) ----------------------------------------------------------
    if prof.tutorial_clear:
        clarity, basis = Clarity.CLEAR, "tutorial"
    elif forced:
        clarity = Clarity.CLEAR
    elif state.next_clear_basis == "observe":
        clarity, basis = Clarity.CLEAR, "observe"
    else:
        c, f, d = prof.clarity_mix
        if not prof.can_disguise:
            d = 0
        clarity = chooser.weighted([(Clarity.CLEAR, c), (Clarity.FUZZY, f), (Clarity.DISGUISE, d)])
    if case.konju_enabled and state.konju_left > 0 and basis is None:
        if clarity == Clarity.FUZZY:
            clarity, basis = Clarity.CLEAR, "konju"
        elif clarity == Clarity.DISGUISE:
            clarity = Clarity.FUZZY

    shown: tuple
    star = None
    if clarity == Clarity.FUZZY:
        # SPEC-QUESTION: A-3 says ★ also appears when a 「強制刪去規則」 (rule 5 / 不能補強)
        # applies, but a deletion rule points at no action. Implemented: ★ only for the
        # tendency rules 1/2/4. A-3's example that Fitch's decoys stay within 主張/猛攻 or
        # 補強/設陷 is not in 各章設計 Ch.2 (and its R2 route tell breaks it): not modelled.
        if rule_target is not None:
            star = rule_target
            other = act if act != rule_target else None
        else:
            other = None
        if other is None:
            pool = [a for a in allowed if a != act]
            if not pool:
                # SPEC-QUESTION: no legal decoy exists (A-3 says fuzzy always shows one).
                clarity = Clarity.CLEAR
            else:
                other = chooser.weighted(_weights(state, pool))
        if clarity == Clarity.FUZZY:
            pair = [act, other]
            if chooser.uniform([0, 1]) == 1:
                pair.reverse()
            shown = tuple(pair)
        else:
            shown = (act,)
    elif clarity == Clarity.DISGUISE:
        raise NotImplementedError("disguise tells (Victor/Wolfhart) are outside Ch.1-3")
    else:
        shown = (act,)

    lit_pool = [n.id for n in new_state.nodes if n.kind in ("normal", "last_stand", "second_claim")]
    # SPEC-QUESTION: how the lit node is chosen is not specified (route tables script it).
    # Implemented: uniform over visible non-fragile nodes.
    lit = chooser.uniform(lit_pool) if lit_pool else None

    tell = Tell(
        clarity,
        shown,
        star if clarity == Clarity.FUZZY else None,
        rule_no if (clarity == Clarity.FUZZY and star is not None) else None,
        basis if clarity == Clarity.CLEAR else None,
        lit,
        _gesture(state, act),
        rule_applied=rule_no,
    )
    return new_state, OpponentAction(act, lit), tell


def possible_tells(state: DebateState) -> set:
    """Every (clarity, frozenset(shown), star, basis, actual) the policy can produce."""
    out = set()
    stack = [[]]
    while stack:
        path = stack.pop()
        ch = _EnumChooser(path)
        _, oa, tell = decide_next(state, ch)
        out.add(tell.key() + (oa.kind,))
        # branch on every choice point beyond the given path
        if len(ch.branching) > len(path):
            for depth in range(len(path), len(ch.branching)):
                for k in range(1, ch.branching[depth]):
                    stack.append(path + [0] * (depth - len(path)) + [k])
    return out


# --------------------------------------------------------------------------- fox instinct


def use_fox_instinct(state: DebateState, tell: Tell, actual: OpponentAction):
    """A-3 狐耳直覺. Returns (state, tell, events). Raises ValueError when unusable."""
    prof = state.case.opponent
    if state.fox_left <= 0:
        raise ValueError("no fox instinct left")
    if tell.basis == "script":
        raise ValueError("script-locked round")
    if tell.clarity == Clarity.CLEAR and (tell.basis is not None or not prof.can_disguise):
        raise ValueError("clear tell with a basis badge / from a non-disguiser")
    st = replace(state, fox_left=state.fox_left - 1)
    if tell.clarity == Clarity.CLEAR:
        return st, tell, [E.Message("FOX_CONFIRM")]
    new = Tell(Clarity.CLEAR, (actual.kind,), None, None, "fox", actual.lit, tell.gesture, tell.rule_applied)
    return st, new, [E.CutIn("STAMP_SEEN", "stamp", None, "player")]
