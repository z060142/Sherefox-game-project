"""Opponent policy for the v2 debate (ch §11 behaviour table, §8.3, §6.5, §7.4).

``decide(state, chooser)`` returns his action and tell for the round ``state.round``;
``state`` is the between-rounds state returned by resolve_round (decay already applied).

Trace contract: the order of random draws (each through the chooser, tagged with its name), every draw made
only when its condition holds:

  1. tendency rule followed?  percent(50)         a tendency rule (②>①>④) applies and no
                                                   必定 rule / 怒氣 fixes the action
  2. tell clarity             weighted(clear 40, vague 60)
                                                   not forced clear (rule ③, 怒氣, 困獸,
                                                   打迷糊仗 baited a rebuttal)
  3. base action              weighted(立論 35, 強辯 10, 反駁 35, 周旋 20) over the
                              available actions; while angry weighted(強辯 60, 反駁 40)
                                                   the action is still open
  4. slip                     percent(30)          he really speaks (立論/強辯), the floating
                                                   band holds (any value >= threshold − 15),
                                                   an unfavourable fact and a normal card are
                                                   in hand, and no 困獸 forced slip is pending
                                                   (00_core_rules §15〔M2〕: the slip is judged
                                                   only when he really speaks)
  5. decoy                    uniform(other available actions, canonical order)
                                                   vague tell

This is the order of the design-owner ruling's list, with the 怒氣 split taking the place
of the base weights and the slip after the action (§15〔M2〕). RngChooser maps weighted() to
roll(sum of weights) over the items in canonical order (立論, 強辯, 反駁, 周旋), percent(p) to
roll(100) < p and uniform(xs) to xs[roll(len(xs))]; with a DebateRng (rng.py) each draw rolls
its own stream, otherwise every draw rolls the one rng given. Cards are never random: they
follow ch §11 出牌順序, so the vague tell's card ("he would say if he speaks", §15〔M2〕)
needs no draw.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import (
    ACTION_BY_NAME, ACTIONS, FLOAT_BAND, SLIP_PCT, A, Clarity, G, OA, OpponentAction, P,
    State, Tell, tell,
)


# --------------------------------------------------------------------------- choosers


class RngChooser:
    """Draws through `rng`: a DebateRng (one stream per draw name) or any object with roll(n)."""

    def __init__(self, rng):
        self.rng = rng

    def _roll(self, draw: str, n: int) -> int:
        src = self.rng.for_draw(draw) if hasattr(self.rng, "for_draw") else self.rng
        return src.roll(n)

    def weighted(self, items, draw: str):
        items = [(v, w) for v, w in items if w > 0]
        total = sum(w for _, w in items)
        r = self._roll(draw, total)
        for v, w in items:
            if r < w:
                return v
            r -= w
        raise AssertionError("unreachable")

    def percent(self, p: int, draw: str) -> bool:
        return self._roll(draw, 100) < p

    def uniform(self, xs, draw: str):
        return xs[self._roll(draw, len(xs))]


class _EnumChooser:
    """Walks one path of choice indices (0 beyond the given prefix); records branching."""

    def __init__(self, path):
        self.path = list(path)
        self.taken: list[int] = []
        self.branching: list[int] = []

    def _pick(self, options):
        i = len(self.taken)
        k = self.path[i] if i < len(self.path) else 0
        self.taken.append(k)
        self.branching.append(len(options))
        return options[k]

    def weighted(self, items, draw=None):
        return self._pick([v for v, w in items if w > 0])

    def percent(self, p, draw=None):
        return self._pick([o for o, ok in ((True, p > 0), (False, p < 100)) if ok])

    def uniform(self, xs, draw=None):
        return self._pick(list(xs))


# --------------------------------------------------------------------------- helpers


@dataclass(frozen=True)
class Decision:
    action: OpponentAction
    tell: Tell | None
    rule: int | None = None  # tendency rule that applied (followed or not)
    forced: str | None = None  # rule3 / rage / endgame / none


def _unfav_in_hand(s: State) -> list[str]:
    return [u for u in s.ch.unfav_order if u in s.hand]


def normal_cards(s: State) -> list[str]:
    """Lies / favourable facts / held pickups in ch §11 出牌順序. While guilt is over, the
    栽贓 cards are skipped (§8.3)."""
    ch = s.ch
    out = []
    for slot in ch.play_order:
        if slot == "@pickups":
            ids = [ch.evidence[e].opponent_use for e in ch.pickup_priority]
            ids = [c for c in ids if c in s.hand and c not in s.reraised]
        elif slot == "@reraised":
            ids = [c for c in s.reraised if c in s.hand]
        else:
            ids = [slot] if slot in s.hand and slot not in s.reraised else []
        out += ids
    # any normal card the order does not name goes last, in hand order
    out += [c for c in s.hand if c not in out and ch.cards[c].kind != "unfav"]
    if s.over[G]:
        out = [c for c in out if not ch.cards[c].frames]
    return out


def floating(s: State) -> bool:
    thr = s.ch.psych_threshold
    return any(s.psych[i] >= thr[i] - FLOAT_BAND for i in range(3))


def choose_card(s: State, slip: bool) -> str | None:
    unfav = _unfav_in_hand(s)
    normal = normal_cards(s)
    if s.next_unfav and unfav:  # §8.3 困獸: the next 立論 is an unfavourable fact
        # SPEC-QUESTION: rules say "下一次立論"; sim/engine.py plays one every attack while
        # pressure is over (ASSUMPTION-22). Rules followed.
        return unfav[0]
    if slip and unfav:
        return unfav[0]
    if normal:
        return normal[0]
    return unfav[0] if unfav else None  # 有利的牌與謊言用盡 (§5.2)


def available_actions(s: State) -> list[OA]:
    acts = list(ACTIONS)
    if not normal_cards(s) and not _unfav_in_hand(s):
        acts = [a for a in acts if a not in (OA.ATTACK, OA.FORCE)]
    if s.over[A]:
        # §8.3 怒氣: only 強辯 / 反駁, "忽略原本的行為表". SPEC-QUESTION: rule ⑤ is part of
        # that table, so it is ignored while angry.
        return [a for a in acts if a in (OA.FORCE, OA.REBUT)]
    h = [x for x in s.opp_history]
    if len(h) >= 2 and h[-1] == h[-2] and h[-1] in acts and len(acts) > 1:
        # rule ⑤ (必定). SPEC-QUESTION: an endgame round (he plays his last card) and a
        # §7.5 round count as rounds in the history, so they break a streak.
        acts.remove(h[-1])
    return acts


def _tendency(s: State, avail) -> tuple[int, OA] | None:
    flags = {
        "player_soph_last_round": s.flag_player_soph,
        # SPEC-QUESTION: rule ① needs a knocked lie (only lies can be re-raised, §6.2).
        "own_lie_knocked_last_round": s.flag_knocked_lie is not None,
        "hit_player_last_round": s.flag_hit_player,
    }
    for rule, when, action in s.ch.tendencies:  # stored in priority order ② > ① > ④
        a = ACTION_BY_NAME[action]
        if flags[when] and a in avail:
            return rule, a
    return None


# --------------------------------------------------------------------------- decide


def decide(s: State, chooser) -> Decision:
    if s.outcome:
        raise ValueError("the debate is over")
    if s.player_locked:
        return Decision(OpponentAction(OA.NONE), None, forced="none")
    if s.endgame:
        card = s.endgame["card"]
        return Decision(OpponentAction(OA.LAST, card), tell(Clarity.CLEAR, (OA.LAST,), card=card),
                        forced="endgame")
    ch = s.ch
    avail = available_actions(s)
    rage = s.over[A]
    action = None
    forced = None
    rule = None
    can_attack = bool(normal_cards(s)) or bool(_unfav_in_hand(s))
    if s.rule3_pending and can_attack:
        # rule ③ (必定): 強辯 with a clear tell. SPEC-QUESTION: it overrides rule ⑤ and the
        # 怒氣 split (both are compatible with 強辯 except ⑤ after two 強辯).
        action, forced = OA.FORCE, "rule3"
    elif rage:
        forced = "rage"
    # the card he would say if he speaks (§15〔M2〕): the 立論 card rule without a slip, chosen
    # at the start of the round whatever he then does; it stays in his hand if he does not speak
    would_say = choose_card(s, False) if can_attack else None
    # 1. tendency
    if action is None and not rage:
        t = _tendency(s, avail)
        if t is not None:
            rule = t[0]
            if chooser.percent(ch.follow_pct, "tendency"):
                action = t[1]
    # 2. clarity
    clear_forced = forced is not None or s.over[P] or s.next_clear
    if clear_forced:
        clarity = Clarity.CLEAR
    else:
        c, v = ch.tell_clarity
        clarity = chooser.weighted([(Clarity.CLEAR, c), (Clarity.VAGUE, v)], "clarity")
    # 3. base action
    if action is None:
        if rage:
            f, r = ch.rage_split
            action = chooser.weighted([(a, w) for a, w in ((OA.FORCE, f), (OA.REBUT, r)) if a in avail],
                                      "base")
        else:
            w = {ACTION_BY_NAME[k]: v for k, v in ch.weights.items()}
            action = chooser.weighted([(a, w[a]) for a in avail], "base")
    speaks = action in (OA.ATTACK, OA.FORCE)
    # 4. slip (R-18), judged only when he really speaks (§15〔M2〕). SPEC-QUESTION: the floating
    # band includes values over the threshold and applies while angry too (ASSUMPTION-28 for the
    # clash with "心理狀態好時不會打").
    slip = False
    if speaks and floating(s) and _unfav_in_hand(s) and normal_cards(s) and not s.next_unfav:
        slip = chooser.percent(SLIP_PCT, "slip")
    card = choose_card(s, slip) if speaks else None
    partial = card is not None and ch.cards[card].kind == "unfav"
    # 5. decoy
    if clarity == Clarity.VAGUE:
        pool = [a for a in avail if a != action]
        if not pool:
            # SPEC-QUESTION: no legal decoy; the tell falls back to clear.
            t = tell(Clarity.CLEAR, (action,), card=card, partial=partial)
        else:
            decoy = chooser.uniform(pool, "decoy")
            # SPEC-QUESTION (ch §11 vs ruling): design-owner ruling: ★ only on the true action, and only when a behaviour
            # rule points to it. (ch §11 puts ★ on the rule's action even when it is the
            # decoy; see ch §12.3 R7, §12.4 R4.)
            star = action if (rule is not None and _rule_action(ch, rule) == action) else None
            # §15〔M2〕: a vague tell always shows the card he would say if he speaks; when he
            # speaks it is the card he plays (a slip shows its first half, so 欲言又止 still
            # appears only in rounds where he really speaks). SPEC-QUESTION: when he stays silent
            # and the would-say card is an unfavourable fact (his normal cards are used up), it is
            # shown partial, as it would be if he spoke.
            shown = card if speaks else would_say
            shown_partial = shown is not None and ch.cards[shown].kind == "unfav"
            t = tell(Clarity.VAGUE, (action, decoy), star=star, card=shown, partial=shown_partial)
    else:
        t = tell(Clarity.CLEAR, (action,), card=card, partial=partial)
    return Decision(OpponentAction(action, card), t, rule, forced)


def _rule_action(ch, rule: int) -> OA:
    for r, _, a in ch.tendencies:
        if r == rule:
            return ACTION_BY_NAME[a]
    raise KeyError(rule)


def possible_decisions(s: State) -> set:
    """Every (action kind, card, tell key) the policy can produce in this state."""
    out = set()
    stack = [[]]
    while stack:
        path = stack.pop()
        ch = _EnumChooser(path)
        d = decide(s, ch)
        out.add((d.action.kind, d.action.card, d.tell.key() if d.tell else None))
        for depth in range(len(path), len(ch.branching)):
            for k in range(1, ch.branching[depth]):
                stack.append(ch.taken[:depth] + [k])
    return out


def can_produce(s: State, action: OpponentAction, t: Tell | None) -> bool:
    return (action.kind, action.card, t.key() if t else None) in possible_decisions(s)
