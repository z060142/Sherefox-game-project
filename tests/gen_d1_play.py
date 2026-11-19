# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Write the v2 demo D01 debate recordings (docs/flows.md §4.12, tests/README.md) and their forced-opponent harnesses.

Every recording starts at the title, clicks the v2 entry and plays the D01 debate by clicking the d1debate screen
(action, evidence, claim, target, cover, lock; a click per playback record), then the outcome panel's back to title:

- tests/d1_routeA.atrec (tests/d1play_harnessA): ref route A (ch §12.1), the opponent's moves pinned by the harness
  (the engine's d1OppAct / d1OppCard test hook, debate-engine-v2 §2.1): a clean Break, grade 1 in 9 rounds.
- tests/d1_routeB.atrec, tests/d1_routeC.atrec (tests/d1play_harnessB, C): ref routes B (talking board, seize his
  words, guilt over the threshold: he gives up) and C (sophistry, Irene's parentage, the picked-up keys as his last
  card, a win after a second endgame).
- tests/d1_routeD.atrec (tests/d1play_harnessD): ref route D (ch §12.4: a Reverse Break and a failed last card, a
  loss in 8 rounds); the harness also replaces the dev entry's loadout with route D's (build_harness).
- tests/d1_bot.atrec (the game itself, run seed BOT_SEED): nothing pinned. The opponent is the engine's AI on the
  debate seed the debate UI draws from the run's rng (BOT_DEBATE_SEED, tests/check_debate_v2.py ui_debate_seed: the
  first atrium.rng value of the run); the player's moves are ref play.bot's against ref policy.decide on that seed,
  so the recording is valid only while the engine and ref draw the same numbers.
- tests/d1_shots.atrec (tests/d1play_harnessA, route A): no playback clicks in round 8 (the Break plays out), for the
  screenshots of tests/check_d1_play.py --shots.

Usage (from the project root):
    uv run tests/gen_d1_play.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "ref" / "src"))
import check_debate_v2 as CV  # noqa: E402
from sherefox_ref.v2 import known as K  # noqa: E402
from sherefox_ref.v2 import routes as RT  # noqa: E402
from sherefox_ref.v2.model import PA, initial_state  # noqa: E402
from sherefox_ref.v2.resolve import resolve_round  # noqa: E402

STEP = 1 / 60
GAP = 8
BOT_SEED = 3
BOT_DEBATE_SEED = CV.ui_debate_seed(BOT_SEED)  # no atrium.rng draw before the debate starts
# ui/boards/project/D1Debate.dc.html (1280x720 logical; the sheet is at 0, 0)
TITLE_V2 = (654, 624)                                   # Title.dc.html #btn-v2-dev (the dev shortcut to the debate)
ACT_XY = {1: (107, 664), 2: (295, 664), 3: (469, 664), 4: (657, 664), 5: (432, 664), 6: (642, 664), 7: (432, 664)}
GUARD_XY = (847, 664)
LOCK_XY = (1157, 664)
SKIP_XY = (900, 580)      # #hit during playback; nothing there while choosing
BACK_XY = (640, 422)      # #out-back
PA_ACT = {PA.ARGUE: 1, PA.INTERCEPT: 2, PA.DISMANTLE: 3, PA.STALL: 4, PA.CUT: 5, PA.ACCEPT: 6, PA.LAST_STAND: 7}
SKIPS = 45                # playback clicks per round (a click shows the next record)
SKIP_GAP = 5
ROUND_TAIL = 70           # after the last click: the hold (0.6 s) and the next round's lists


def ev_xy(i: int) -> tuple[int, int]:
    return 110, 188 + 22 * i + (10 if i < 9 else 4)      # #evs rows 20 + 2 gap; row 9 is clipped at 400


def claim_xy(j: int) -> tuple[int, int]:
    return 378, 188 + 52 * j + 24                          # #cls rows 48 + 4 gap


def chain_xy(k: int) -> tuple[int, int]:
    return 20 + 112 * k + 53, 114                          # #ochain chips 106 + 6 gap


def picker(s) -> list[tuple[str, list[str]]]:
    """The claim picker as the UI shows it: (evidence, its claims) in d1ClaimList order (抓住他的話 first)."""
    out: list[tuple[str, list[str]]] = []
    for v in K.claim_list(s):
        ev = "CATCH" if K.is_catch(v.id) else s.ch.claims[v.id].evidence
        if not out or out[-1][0] != ev:
            if any(e == ev for e, _ in out):
                raise SystemExit(f"picker: evidence {ev} is not contiguous")
            out.append((ev, []))
        out[-1][1].append(v.id)
    return out


class Rec:
    def __init__(self, game: str, seed: int = 1) -> None:
        self.lines = [json.dumps({"atrec": 1, "step": STEP, "seed": seed, "game": game})]
        self.t = 0
        self.marks: dict[str, int] = {}

    def click(self, ui: str, xy, wait: int = GAP) -> None:
        self.t += wait
        x, y = xy
        self.lines.append(json.dumps({"t": self.t, "u": [[ui, "pd", x, y, 0, 1], [ui, "pu", x, y, 0]]}))

    def round(self, s, pa, n: int, skips: int = SKIPS) -> None:
        act = PA_ACT[pa.kind]
        self.click("d1debate", ACT_XY[act], 12)
        if pa.claim is not None:
            pk = picker(s)
            claim = f"CATCH:{s.catch_card}" if pa.claim == "CATCH" else pa.claim
            ev = "CATCH" if claim.startswith("CATCH") else s.ch.claims[claim].evidence
            i = [e for e, _ in pk].index(ev)
            self.click("d1debate", ev_xy(i))
            self.click("d1debate", claim_xy(pk[i][1].index(claim)))
        chain = [nd.card for nd in s.opp_chain]
        if pa.target in chain:   # route D's last card names L1, which is no longer on his chain: no target (same loss)
            self.click("d1debate", chain_xy(chain.index(pa.target)))
        if pa.guard:
            self.click("d1debate", GUARD_XY)
        self.marks[f"chosen{n}"] = self.t + 4
        self.click("d1debate", LOCK_XY)
        self.marks[f"lock{n}"] = self.t
        for _ in range(skips):
            self.click("d1debate", SKIP_XY, SKIP_GAP)
        self.t += ROUND_TAIL

    def write(self, name: str, tail: int) -> int:
        (TESTS / f"{name}.atrec").write_text("\n".join(self.lines) + "\n", encoding="utf-8", newline="\n")
        return self.t + tail


def forced(route) -> list:
    """(state before, player action, opponent action) per round of a ref route (forced replay); `route` is a name
    of ref routes.py or a Route (tests/check_d1_lines.py's scenarios)."""
    rt = RT.ROUTES[route] if isinstance(route, str) else route
    s = initial_state(rt.loadout)
    out = []
    for pa, oa, _ in rt.rounds:
        if s.outcome:
            break
        out.append((s, pa, oa))
        s, _ = resolve_round(s, pa, oa)
    return out


def play(rec: Rec, rounds: list, no_skip: set[int] = frozenset()) -> None:
    rec.click("title", TITLE_V2, 40)
    rec.t += 40
    for n, (s, pa, _) in enumerate(rounds, start=1):
        rec.round(s, pa, n, 0 if n in no_skip else SKIPS)
        if n in no_skip:
            rec.t += 900
    rec.marks["over"] = rec.t
    rec.click("d1debate", BACK_XY, 30)
    rec.marks["back"] = rec.t


# ------------------------------------------------------------------------------------------------ harness

def harness_dir(route: str) -> Path:
    return TESTS / f"d1play_harness{route}"


def build_harness(route: str, rt=None) -> None:
    """tests/d1play_harness<route>/: a copy of the game with one more flow (d1test, before the D01 engine) that
    writes the route's pinned opponent move of the round into the engine's test hook d1OppAct / d1OppCard, and
    replaces the dev entry's loadout with the route's 20 ms after the title's v2 entry (the debate starts 100 ms
    after it, so the engine reads this loadout). Game paths may not leave the game directory, so it is a copy."""
    out = harness_dir(route)
    for sub in ("flows", "data", "strings", "ui", "audio"):
        shutil.rmtree(out / sub, ignore_errors=True)
    out.mkdir(exist_ok=True)
    shutil.copytree(ROOT / "flows", out / "flows")
    shutil.copytree(ROOT / "data", out / "data")
    shutil.copytree(ROOT / "strings", out / "strings")
    shutil.copytree(ROOT / "ui" / "bundle", out / "ui" / "bundle")
    shutil.copytree(ROOT / "audio", out / "audio")
    game = json.loads((ROOT / "game.json").read_text(encoding="utf-8"))
    rt = rt or RT.ROUTES[route]
    rows = [{"id": str(n), "act": oa.kind.value, "card": oa.card or ""}
            for n, (_, _, oa) in enumerate(forced(rt), start=1)]
    (out / "data" / "flow" / "d1test.json").write_text("[\n" + ",\n".join(json.dumps(r) for r in rows) + "\n]\n",
                                                       encoding="utf-8", newline="\n")
    game["tables"]["d1test"] = "data/flow/d1test.json"
    lo = rt.loadout
    nodes = [
        {"id": "rnd", "type": "toString", "params": {"decimals": 0}},
        {"id": "row", "type": "atrium.table.find", "params": {"table": "d1test", "column": "id"}},
        {"id": "act", "type": "atrium.table.get", "params": {"table": "d1test", "column": "act", "type": "string"}},
        {"id": "card", "type": "atrium.table.get", "params": {"table": "d1test", "column": "card", "type": "string"}},
        {"id": "late", "type": "timer", "params": {"interval": 0.02, "autostart": False, "repeat": False}},
    ]
    edges = [
        {"from": "world.d1Round", "to": "rnd.in"},
        {"from": "rnd.out", "to": "row.value"},
        {"from": "row.row", "to": "act.row"},
        {"from": "row.row", "to": "card.row"},
        {"from": "act.value", "to": "world.d1OppAct"},
        {"from": "card.value", "to": "world.d1OppCard"},
        {"from": "ui#title.v2dev", "to": "late.start"},
    ]
    for coll, items in (("d1Carry", lo.carried), ("d1Appraised", lo.appraisals), ("d1Notes", lo.notes)):
        nodes.append({"id": f"k_{coll}", "type": "constant", "params": {"value": ",".join(items)}})
        nodes.append({"id": f"clr_{coll}", "type": "atrium.coll.clear", "params": {"name": coll}})
        nodes.append({"id": f"add_{coll}", "type": "atrium.coll.addAll", "params": {"name": coll, "separator": ","}})
        edges.append({"from": "late.tick", "to": f"clr_{coll}.trigger"})
        edges.append({"from": f"k_{coll}.out", "to": f"add_{coll}.text"})
        edges.append({"from": "late.tick", "to": f"add_{coll}.trigger"})
    (out / "flows" / "d1test.xtflow").write_text(json.dumps({"version": 1, "nodes": nodes, "edges": edges},
                                                            indent=1) + "\n", encoding="utf-8", newline="\n")
    flows = game["flows"]
    flows.insert(flows.index("flows/d01_debate_engine.xtflow"), "flows/d1test.xtflow")
    (out / "game.json").write_text(json.dumps(game, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
                                   newline="\n")


RECORDINGS = (("d1_routeA", "A", set()), ("d1_routeB", "B", set()), ("d1_routeC", "C", set()),
              ("d1_routeD", "D", set()), ("d1_shots", "A", {8}))
ROUTES = ("A", "B", "C", "D")


def main() -> int:
    ticks = {}
    for route in ROUTES:
        build_harness(route)
    for name, route, no_skip in RECORDINGS:
        r = Rec(f"tests/d1play_harness{route}")
        play(r, forced(route), no_skip)
        ticks[name] = r.write(name, 60)
        ticks[name + "_marks"] = r.marks
    bot = CV.play_debate("bot", RT.ROUTES["A"].loadout, BOT_DEBATE_SEED)
    r = Rec(".", BOT_SEED)
    play(r, [(st[2], st[0], None) for st in bot.steps])
    ticks["d1_bot"] = r.write("d1_bot", 60)
    ticks["d1_bot_marks"] = r.marks
    (TESTS / "d1_ticks.json").write_text(json.dumps(ticks, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
