"""Golden traces: replay the recommended routes and dump per-round JSON.

    uv run python -m sherefox_ref.trace [out_dir]     (default: ./traces)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .fixtures import ch1_board, ch1_case, ch2_board, ch2_case, ch3_board, ch3_case
from .model import OA, PA, DebateState, OpponentAction, PlayerAction, initial_state
from .resolve import resolve_round


def _pa(kind, card=None, segment=(), target=None):
    return PlayerAction(kind, segment=tuple(segment), target=target, card=card)


ROUTES = {
    "ch1_route": (
        ch1_case,
        ch1_board,
        [
            (_pa(PA.PARRY, card="E01_06"), OpponentAction(OA.CLAIM, "N1")),
            (_pa(PA.SOLID, segment=("E01_01", "E01_04"), target="N2"), OpponentAction(OA.REINFORCE, "N2")),
            (_pa(PA.PARRY, segment=("E01_03",)), OpponentAction(OA.CLAIM, "N3")),
        ],
    ),
    "ch2_route": (
        ch2_case,
        ch2_board,
        [
            (_pa(PA.PARRY, card="E02_02"), OpponentAction(OA.CLAIM, "N1")),
            (_pa(PA.OBSERVE), OpponentAction(OA.CLAIM, "N2")),
            (
                _pa(PA.SOLID, segment=("E02_03", "E02_02", "E02_04", "E02_05"), target="N1"),
                OpponentAction(OA.REINFORCE, "N1"),
            ),
            (_pa(PA.PARRY, segment=("E02_06", "E02_01")), OpponentAction(OA.RUSH, "N3")),
            (_pa(PA.PARRY, segment=("E02_07", "E02_01")), OpponentAction(OA.ALL_IN, "T2", True)),
        ],
    ),
    "ch3_route": (
        ch3_case,
        ch3_board,
        [
            (_pa(PA.PARRY, card="E03_08"), OpponentAction(OA.CLAIM, "N1")),
            (_pa(PA.OBSERVE), OpponentAction(OA.CLAIM, "N3")),
            (_pa(PA.SOLID, segment=("E03_07", "E03_06"), target="N3"), OpponentAction(OA.REINFORCE, "N3")),
            (_pa(PA.PARRY, segment=("E03_02", "E03_04", "G-01")), OpponentAction(OA.RUSH, "N2")),
            (_pa(PA.PARRY, segment=("E03_05", "E03_03")), OpponentAction(OA.ALL_IN, "T3", True)),
        ],
    ),
}


def snapshot(s: DebateState) -> dict:
    return {
        "round": s.round,
        "player_hp": s.player_hp,
        "opp_hp": s.opp_hp,
        "nodes": [[n.id, n.kind] for n in s.nodes],
        "shaken": s.shaken,
        "in_tail": s.in_tail,
        "hachiku": s.hachiku,
        "konju_left": s.konju_left,
        "shissu_left": s.shissu_left,
        "parry_count": s.parry_count,
        "contradictions": s.contradictions,
        "infamy": s.infamy,
        "assist_left": s.assist_left,
        "over": s.over,
        "outcome": s.outcome,
    }


def _action(a) -> dict:
    d = {"kind": a.kind.value}
    for k in ("segment", "target", "card", "assist", "lit", "scripted"):
        if hasattr(a, k):
            v = getattr(a, k)
            d[k] = list(v) if isinstance(v, tuple) else v
    return d


def run_route(name: str) -> dict:
    case_f, board_f, moves = ROUTES[name]
    s = initial_state(case_f(), board_f())
    rounds = []
    start = snapshot(s)
    for pa, oa in moves:
        s, ev = resolve_round(s, pa, oa)
        rounds.append(
            {
                "player_action": _action(pa),
                "opponent_action": _action(oa),
                "events": [e.to_dict() for e in ev],
                "after": snapshot(s),
            }
        )
    return {"route": name, "start": start, "rounds": rounds}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    out = Path(argv[0]) if argv else Path("traces")
    out.mkdir(parents=True, exist_ok=True)
    for name in ROUTES:
        p = out / f"{name}.json"
        p.write_text(json.dumps(run_route(name), ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
