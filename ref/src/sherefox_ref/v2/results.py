"""End-of-debate results: grade, truth score (§9), reputation (§10), favour, ch §2 S08-S10 tiers."""

from __future__ import annotations

from dataclasses import dataclass

from . import known as K
from .model import (
    REP_CRACK_CAP, REP_DENIAL, REP_GRADE, REP_PER_CRACK, REP_PRIVATE, REP_PSYCH_CARD,
    REP_STALLS, REP_STALLS_AT, TRUTH_DENIAL, TRUTH_FALSE_CLAIM, TRUTH_KEY_LEFT, State,
)


@dataclass(frozen=True)
class Result:
    outcome: str
    grade: int
    reason: str
    rounds: int
    player_hp: float
    opp_hp: float
    cracks: int
    denials: int
    truth: int  # percent (§9, R-12: from the public record)
    false_claims: tuple[str, ...]
    key_left: tuple[str, ...]
    reputation: tuple[tuple[str, int], ...]  # §10 line items
    reputation_delta: int
    reputation_after: int
    next_start_hp: float  # §10: (reputation − 50) / 5, clamped to ±10
    favour: tuple[tuple[str, int], ...]
    note_version: str  # ch §2 S10: full / half / wrong
    newspaper: str  # ch §2 S09: decent / normal / ugly

    def to_dict(self) -> dict:
        return {k: (list(map(list, v)) if k in ("reputation", "favour") else
                    list(v) if isinstance(v, tuple) else v)
                for k, v in self.__dict__.items()}


def compute(s: State) -> Result:
    if not s.outcome:
        raise ValueError("debate not over")
    ch = s.ch
    false_claims = []
    for r in s.record:
        if not r.true and r.claim not in false_claims:
            false_claims.append(r.claim)  # SPEC-QUESTION: each distinct false claim once
    key_left = tuple(e.id for e in ch.evidence.values() if e.key and e.id not in s.loadout.carried)
    truth = 100 - TRUTH_FALSE_CLAIM * len(false_claims) - TRUTH_DENIAL * s.denials - TRUTH_KEY_LEFT * len(key_left)
    truth = max(0, truth)

    rep = [(f"grade_{s.grade}", REP_GRADE[s.grade])]
    if s.cracks:
        rep.append(("cracks", max(REP_CRACK_CAP, REP_PER_CRACK * s.cracks)))
    if s.privates:
        rep.append(("private", REP_PRIVATE * s.privates))
    if s.psych_card_uses:
        # SPEC-QUESTION: §10 "使用心理牌 −2" read as once per debate
        rep.append(("psych_card", REP_PSYCH_CARD))
    if s.stalls >= REP_STALLS_AT:
        rep.append(("stalls", REP_STALLS))
    if s.denials:
        rep.append(("denials", REP_DENIAL * s.denials))
    delta = sum(d for _, d in rep)
    after = max(0, min(100, ch.reputation_start + delta))
    next_hp = max(-10.0, min(10.0, (after - 50) / 5))

    favour = []
    w = ch.warmup[s.loadout.warmup]["inspector"]
    if w:
        favour.append(("inspector", w))
    priv = {}
    for r in s.record:
        if not K.is_catch(r.claim) and r.claim in ch.private_favour:
            who, d = ch.private_favour[r.claim]
            priv[who] = priv.get(who, 0) + d
    favour += sorted(priv.items())

    note = "full" if truth >= 70 else "half" if truth >= 40 else "wrong"
    paper = "decent" if s.grade in (1, 2) else "normal" if s.grade in (3, 4) else "ugly"
    return Result(s.outcome, s.grade, s.end_reason, s.round - 1, s.player_hp, s.opp_hp,
                  s.cracks, s.denials, truth, tuple(false_claims), key_left, tuple(rep), delta,
                  after, next_hp, tuple(favour), note, paper)
