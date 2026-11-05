"""熱身小論戰 (系統規格 A-13). No HP, no statuses, parry only.

The inspector states 1..3 wrong claims in order, each with a clear 主張 tell. The player
parries with ONE card; a card in the claim's refute list corrects it. A wrong card is a
mistake. 3 mistakes -> remaining claims auto-corrected, reward cancelled, effective trust
-1. Zero mistakes -> effective trust +1.

SPEC-QUESTION: Ch.3 (各章設計 and its 數值卡) says the player must show the chain
E03_05 + E03_02 (solid link: 地點); A-13 (higher precedence) says a single card from the
refute list. Implemented per A-13 with refute list {E03_05, E03_02}; a two-card
presentation is accepted only if every card is in the list (`allow_chain=True`).
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class WarmupClaim:
    id: str
    refuters: frozenset[str]


@dataclass(frozen=True)
class WarmupState:
    claims: tuple[WarmupClaim, ...]
    index: int = 0
    mistakes: int = 0
    round: int = 1
    over: bool = False
    auto_resolved: bool = False
    log: tuple = ()

    @property
    def current(self) -> WarmupClaim | None:
        return self.claims[self.index] if self.index < len(self.claims) else None


def resolve_warmup_round(
    ws: WarmupState, action: str, cards: tuple[str, ...], allow_chain: bool = False
) -> tuple[WarmupState, list[dict]]:
    if ws.over:
        raise ValueError("warmup is over")
    if action != "parry":
        # A-13: 只開放反駁（其他三個按鈕變灰）
        raise ValueError("only parry is available in the warmup")
    claim = ws.current
    ok = bool(cards) and (len(cards) == 1 or allow_chain) and all(c in claim.refuters for c in cards)
    ev = [{"kind": "WarmupReveal", "round": ws.round, "claim": claim.id, "cards": list(cards)}]
    idx, mistakes, auto = ws.index, ws.mistakes, False
    if ok:
        ev.append({"kind": "WarmupCorrected", "claim": claim.id})
        idx += 1
    else:
        mistakes += 1
        ev.append({"kind": "WarmupMistake", "count": mistakes})
        if mistakes >= 3:
            auto = True
            for c in ws.claims[idx:]:
                ev.append({"kind": "WarmupAutoCorrected", "claim": c.id})
            idx = len(ws.claims)
    over = idx >= len(ws.claims)
    if over:
        ev.append({"kind": "WarmupEnded", **warmup_result(replace(ws, mistakes=mistakes, auto_resolved=auto))})
    ns = replace(ws, index=idx, mistakes=mistakes, round=ws.round + 1, over=over, auto_resolved=auto,
                 log=ws.log + (tuple(ev),))
    return ns, ev


def warmup_result(ws: WarmupState) -> dict:
    """Effective-trust delta and reward flag. Infamy from warmup mistakes is 0 (3.2)."""
    if ws.auto_resolved or ws.mistakes >= 3:
        return {"trust_delta": -1, "reward": False, "mistakes": ws.mistakes}
    if ws.mistakes == 0:
        return {"trust_delta": +1, "reward": True, "mistakes": 0}
    return {"trust_delta": 0, "reward": True, "mistakes": ws.mistakes}


def ch3_warmup_grants(base_trust: int, ws: WarmupState) -> dict:
    """Ch.3 熱身獲得的情報: trust >= 3 -> E03_01 + deck access; else deck access only.
    SPEC-QUESTION: whether the check uses the trust after the warmup's +-1 (本案有效信任度)
    or the trust before it is not stated. Implemented: after (effective trust)."""
    res = warmup_result(ws)
    # SPEC-QUESTION: 「熱身獎勵取消」 after 3 mistakes — whether that also withholds the deck
    # access granted at low trust is unstated. Implemented: nothing is granted.
    if not res["reward"]:
        return {"effective_trust": base_trust + res["trust_delta"], "E03_01": False, "deck_access": False}
    eff = base_trust + res["trust_delta"]
    return {"effective_trust": eff, "E03_01": eff >= 3, "deck_access": True}
