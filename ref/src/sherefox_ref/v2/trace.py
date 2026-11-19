"""Golden traces of the ch §12 routes A-D (forced-opponent replays).

    uv run python -m sherefox_ref.v2.trace [out_dir]     (default: ./traces/v2)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .model import State
from .results import compute
from .routes import ROUTES, replay


def snapshot(s: State) -> dict:
    return {
        "round": s.round - 1,
        "player_hp": s.player_hp,
        "opp_hp": s.opp_hp,
        "player_chain": [[n.claim, n.issue, n.cracked] for n in s.player_chain],
        "opp_chain": [n.card for n in s.opp_chain],
        "player_combo": s.player_combo,
        "opp_combo": s.opp_combo,
        "hachiku": s.hachiku,
        "broken_until": s.broken_until,
        "shisshu": s.shisshu,
        "psych_end": list(s.psych_end),
        "psych_next": list(s.psych),
        "over": list(s.over),
        "cracks": s.cracks,
        "denials": s.denials,
        "known": sorted(s.known),
        "hand": list(s.hand),
        "knocked": list(s.knocked),
        "reserved_last": s.reserved_last,
        "endgame": s.endgame,
        "player_locked": s.player_locked,
        "outcome": s.outcome,
        "grade": s.grade,
    }


def _act(a) -> dict:
    return {k: (v.value if hasattr(v, "value") else v) for k, v in a.__dict__.items()}


def _tell(t) -> dict | None:
    if t is None:
        return None
    return {"clarity": t.clarity.value, "shown": [a.value for a in t.shown],
            "star": t.star.value if t.star else None, "card": t.card, "partial": t.partial}


def run_route(name: str) -> dict:
    route = ROUTES[name]
    rp = replay(route)
    rounds = []
    for i, (pa, oa, t) in enumerate(route.rounds[: len(rp.states) - 1], start=1):
        rounds.append({
            "tell": _tell(t),
            "policy_can_produce": rp.producible[i],
            "opponent_action": _act(oa),
            "player_action": _act(pa),
            "events": rp.events[i],
            "after": snapshot(rp.states[i]),
        })
    last = rp.states[-1]
    return {
        "route": name,
        "loadout": {"carried": list(route.loadout.carried), "appraisals": list(route.loadout.appraisals),
                    "notes": list(route.loadout.notes), "warmup": route.loadout.warmup},
        "start": snapshot(rp.states[0]),
        "rounds": rounds,
        "result": compute(last).to_dict() if last.outcome else None,
    }


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    out = Path(argv[0]) if argv else Path("traces") / "v2"
    out.mkdir(parents=True, exist_ok=True)
    for name in ROUTES:
        p = out / f"route_{name}.json"
        p.write_text(json.dumps(run_route(name), ensure_ascii=False, indent=1) + "\n",
                     encoding="utf-8", newline="\n")
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
