"""Chapter data for the v2 debate model: d01_debate.json + d01_extra.json.

Both files live in ``ref/data/`` and are located relative to this package, never by an
absolute path. ``loc`` fields in d01_debate.json are presentation only and ignored here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data"

PGA = tuple[float, float, float]


def _pga(d) -> PGA:
    if d is None:
        return (0.0, 0.0, 0.0)
    if isinstance(d, (list, tuple)):
        return (float(d[0]), float(d[1]), float(d[2]))
    return (float(d.get("P", 0)), float(d.get("G", 0)), float(d.get("A", 0)))


@dataclass(frozen=True)
class Evidence:
    id: str
    name: str
    appraisal: str | None
    opponent_use: str | None
    key: bool
    psych_card: bool


@dataclass(frozen=True)
class Claim:
    id: str
    evidence: str
    issue: str
    unlock: tuple[str, ...]
    conflicts: tuple[str, ...]
    true: bool
    exclusive: tuple[str, ...]  # both directions merged
    breaks: tuple[str, ...]  # merged with cards[].breakable_by
    opp_refute: tuple[tuple[str, str], ...]  # (via, line_id)
    psych: PGA | None
    psych_kind: str | None  # heart_knot / weakness / private
    psych_once: bool
    private: bool
    psych_card: bool


@dataclass(frozen=True)
class Card:
    id: str
    kind: str  # lie / fav / unfav / pickup / last
    issue: str | None
    keystone: bool
    frames: bool
    as_: str | None  # pickup: lie / fav
    source: str | None

    @property
    def is_lie(self) -> bool:
        return self.kind == "lie" or (self.kind == "pickup" and self.as_ == "lie") or self.kind == "last"

    @property
    def is_fact(self) -> bool:
        return self.kind in ("fav", "unfav") or (self.kind == "pickup" and self.as_ == "fav")


@dataclass(frozen=True)
class Chapter:
    id: str
    issues: tuple[str, ...]
    evidence: dict
    claims: dict  # id -> Claim, in file order
    cards: dict  # id -> Card, in file order
    breakers: dict  # card id -> frozenset of claim ids
    appraisals: dict  # appraisal id -> target evidence
    optional_known: dict  # note id -> tuple of hotspots
    carry_limit: int
    appraisal_limit: int
    max_pickup: int
    pickup_priority: tuple[str, ...]
    opp_max_hp: float
    opp_base_damage: float
    ronpa_len: int
    # personality (§10)
    psych_start: PGA
    psych_threshold: PGA
    psych_decay: PGA
    psych_events: dict  # event -> PGA (§10 actual increments)
    weights: dict  # action name -> weight
    # extra (d01_extra.json)
    player_max_hp: float
    reputation_start: int
    inspector_favour_start: int
    ronpa_issues: int
    max_rounds: int
    tell_clarity: tuple[int, int]
    continuations: frozenset  # (from, to) pairs, directions expanded
    refute_lines: dict  # line id -> reveals
    follow_pct: int
    tendencies: tuple  # ((rule, when, action), ...) in priority order
    rule3_hp_ratio: float
    rage_split: tuple[int, int]
    play_order: tuple[str, ...]
    unfav_order: tuple[str, ...]
    last_card_order: tuple[str, ...]
    private_favour: dict
    warmup: dict
    flags: dict

    def __deepcopy__(self, memo):  # immutable; shared by every state
        return self

    def card(self, cid: str) -> Card:
        return self.cards[cid]

    def claim(self, cid: str) -> Claim:
        return self.claims[cid]


def _load_json(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def load_chapter(debate: str = "d01_debate.json", extra: str = "d01_extra.json") -> Chapter:
    d = _load_json(debate)
    x = _load_json(extra)
    opp = d["opponent"]
    per = opp["personality"]

    evidence = {
        e["id"]: Evidence(e["id"], e["name"], e.get("appraisal"), e.get("opponent_use"),
                          bool(e.get("key")), bool(e.get("psych_card")))
        for e in d["evidence"]
    }

    # exclusives are written on one side or both; merge to both directions
    excl: dict[str, set] = {c["id"]: set(c["exclusive"]) for c in d["claims"]}
    for c in d["claims"]:
        for o in c["exclusive"]:
            excl.setdefault(o, set()).add(c["id"])

    # breaks (claim side) merged with breakable_by (card side)
    brk: dict[str, set] = {cd["id"]: set(cd.get("breakable_by", [])) for cd in opp["cards"]}
    for c in d["claims"]:
        for cid in c["breaks"]:
            brk.setdefault(cid, set()).add(c["id"])

    cpsy = x["claim_psych"]
    claims = {}
    for c in d["claims"]:
        refute = c.get("opp_refute") or []
        if isinstance(refute, dict):
            refute = [refute]
        meta = cpsy.get(c["id"], {})
        claims[c["id"]] = Claim(
            id=c["id"],
            evidence=c["evidence"],
            issue=c["issue"],
            unlock=tuple(c["unlock"]),
            conflicts=tuple(c["conflicts"]),
            true=bool(c["true"]),
            exclusive=tuple(sorted(excl[c["id"]])),
            breaks=tuple(sorted(k for k, v in brk.items() if c["id"] in v)),
            opp_refute=tuple((r["via"], r["line_id"]) for r in refute),
            psych=_pga(c["psych"]) if c.get("psych") else None,
            psych_kind=meta.get("kind"),
            psych_once=bool(meta.get("once", False)),
            private=bool(c.get("private")),
            psych_card=bool(c.get("psych_card")),
        )

    cards = {
        cd["id"]: Card(cd["id"], cd["kind"], cd.get("issue"), bool(cd.get("keystone")),
                       bool(cd.get("frames")), cd.get("as"), cd.get("source"))
        for cd in opp["cards"]
    }

    events = {k: _pga(v) for k, v in x["psych_events"].items() if k != "ref"}
    for c in claims.values():
        if c.psych is not None and c.psych_kind is None and not c.psych_card:
            raise ValueError(f"claim {c.id} has psych but no claim_psych entry")

    cont = set()
    for a, b, both in x["continuations"]["pairs"]:
        cont.add((a, b))
        if both:
            cont.add((b, a))

    beh = x["behavior"]
    nums = x["numbers"]
    stage_len = {"early": 3, "mid": 4, "late": 4}
    return Chapter(
        id=d["id"],
        issues=tuple(i["id"] for i in d["issues"]),
        evidence=evidence,
        claims=claims,
        cards=cards,
        breakers={k: frozenset(v) for k, v in brk.items()},
        appraisals={a["id"]: a["target"] for a in d.get("appraisals", [])},
        optional_known={n["id"]: tuple(n["hotspots"]) for n in d.get("optional_known", [])},
        carry_limit=int(d["carry_limit"]),
        appraisal_limit=int(d["appraisal_limit"]),
        max_pickup=int(d.get("max_pickup", 2)),
        pickup_priority=tuple(opp.get("pickup_priority", [])),
        opp_max_hp=float(opp["hp"]),
        opp_base_damage=float(opp["base_damage"]),
        ronpa_len=int(d.get("ronpa_len", stage_len[d["stage"]])),
        psych_start=_pga(per["start"]),
        psych_threshold=_pga(per["threshold"]),
        psych_decay=_pga(per["decay"]),
        psych_events=events,
        weights=dict(opp["behavior"]["weights"]),
        player_max_hp=float(nums["player_max_hp"]),
        reputation_start=int(nums["reputation_start"]),
        inspector_favour_start=int(nums["inspector_favour_start"]),
        ronpa_issues=int(nums["ronpa_issues"]),
        max_rounds=int(nums["max_rounds"]),
        tell_clarity=(int(nums["tell_clarity"]["clear"]), int(nums["tell_clarity"]["vague"])),
        continuations=frozenset(cont),
        refute_lines={k: v["reveals"] for k, v in x["refute_lines"].items() if k != "ref"},
        follow_pct=round(float(opp["behavior"]["tendency"]) * 100),  # ch §11, JSON behavior.tendency
        tendencies=tuple((t["rule"], t["when"], t["action"]) for t in beh["tendencies"]),
        rule3_hp_ratio=float(beh["rule3_hp_ratio"]),
        rage_split=(int(beh["rage_split"]["force"]), int(beh["rage_split"]["rebut"])),
        play_order=tuple(beh["play_order"]),
        unfav_order=tuple(beh["unfav_order"]),
        last_card_order=tuple(x["last_card_order"]["order"]),
        private_favour={k: (v["who"], int(v["delta"])) for k, v in x["private_favour"].items() if k != "ref"},
        warmup={k: dict(v) for k, v in x["warmup"].items() if k != "ref"},
        flags={k: v for k, v in x["flags"].items() if k != "ref"},
    )
