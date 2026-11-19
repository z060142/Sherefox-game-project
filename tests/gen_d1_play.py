# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Write the v2 demo D01 debate recordings (docs/flows.md §4.12, tests/README.md) and their forced-opponent harnesses.

Every recording starts at the title, clicks the v2 entry and plays the D01 debate by clicking the d1debate screen
(action, evidence, claim, target, cover, lock; a click per playback record), then (4.4) the S07 lines after it, the result
step (S08 lines, the result screen), the S09 paper, S10 Arthur's notes and the S11 placeholder's back to title:

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
- tests/d1_twiceA.atrec, tests/d1_twiceD.atrec (v2 demo E6): route A (a win) / D (a loss) as above, back to the title,
  then the dev entry again up to the second debate's round 1 (its first ticks: check_d1_play; its music:
  check_music).

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
RES_NEXT_XY = (1038, 650)  # D1Result #btn-next (繼續)
PAPER_XY = (640, 400)      # Paper: a click anywhere turns / ends the page
END_BACK_XY = (640, 640)   # D1End #btn-back (S11 L003)
PA_ACT = {PA.ARGUE: 1, PA.INTERCEPT: 2, PA.DISMANTLE: 3, PA.STALL: 4, PA.CUT: 5, PA.ACCEPT: 6, PA.LAST_STAND: 7}
VN_XY = (640, 300)        # Vn #hit (the S07 lines before and after the debate)
VN_WAIT = 30              # ticks between vn clicks (the standees' fade-in is over)
SKIPS = 60                # playback clicks per round (a click shows the next step)
NO_SKIP_WAIT = 2700      # a round played back at its own pace (every step its full dwell)
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

    def at(self, dt: int, events) -> None:
        """gen_playthrough.Recording's interface (its story steps: tests/gen_d1_full.py v1_first, v2 demo E6)."""
        self.t += dt
        self.lines.append(json.dumps({"t": self.t, "u": events}, ensure_ascii=False))

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


def opening(rec: Rec) -> None:
    """The d1debate step has begun: S07 L001-L003 on the vn (a click each), then the debate screen with S07 L004 (a
    click skips its dwell) before round 1 (v2 demo 4.3, docs/flows.md §4.12)."""
    from sherefox_ref.v2 import lines as LN
    for lid in LN.PRE_LINES:
        rec.marks[f"pre_{lid}"] = rec.t + 20
        rec.click("vn", VN_XY, VN_WAIT)
    rec.marks["start"] = rec.t
    rec.t += 20
    rec.click("d1debate", SKIP_XY, 0)
    rec.t += 60


def outro(rec: Rec, outcome: str | None) -> None:
    """After the last round: S07's lines after a win / a loss on the vn (a click each); the step ends after them."""
    from sherefox_ref.v2 import lines as LN
    if outcome is None:
        return
    rec.marks["post"] = rec.t
    for lid in LN.outro(outcome):
        rec.marks[f"post_{lid}"] = rec.t + 20
        rec.click("vn", VN_XY, VN_WAIT)
    rec.t += 30


def final_state(rounds: list):
    s, pa, oa = rounds[-1]
    return resolve_round(s, pa, oa)[0]


def epilogue(rec: Rec, final, back: bool = True) -> None:
    """After S07's lines (v2 demo 4.4, docs/flows.md §4.15): the result step's S08 lines on the vn (ref epilogue: the
    lines the engine picks), the result screen (mark `over`), 繼續, the S09 paper (one click), S10 Arthur's notes on
    the vn, the S11 placeholder and (back) its back to title (mark `back`)."""
    from sherefox_ref.v2.epilogue import epilogue as ep
    e = ep(final)
    for lid in e.s08:
        rec.marks[f"s08_{lid}"] = rec.t + 20
        rec.click("vn", VN_XY, VN_WAIT)
    rec.marks["over"] = rec.t + 40
    rec.t += 60
    rec.click("d1result", RES_NEXT_XY, 0)
    rec.marks["s09"] = rec.t + 40
    rec.t += 70
    rec.click("paper", PAPER_XY, 0)
    for lid in e.s10:
        rec.marks[f"s10_{lid}"] = rec.t + 20
        rec.click("vn", VN_XY, VN_WAIT)
    rec.marks["s11"] = rec.t + 80
    rec.t += 100
    if back:
        rec.click("d1end", END_BACK_XY, 0)
        rec.marks["back"] = rec.t + 30
        rec.t += 40


def play(rec: Rec, rounds: list, no_skip: set[int] = frozenset(), outcome: str | None = None, final=None) -> None:
    rec.click("title", TITLE_V2, 40)
    rec.t += 40
    opening(rec)
    for n, (s, pa, _) in enumerate(rounds, start=1):
        rec.round(s, pa, n, 0 if n in no_skip else SKIPS)
        if n in no_skip:
            rec.t += NO_SKIP_WAIT
    rec.marks["end"] = rec.t
    outro(rec, outcome)
    if outcome is not None:
        epilogue(rec, final or final_state(rounds))


def again(rec: Rec) -> None:
    """v2 demo E6: after a debate and back to the title, the dev entry again: S07 L001-L003, the new debate's first
    ticks (marks `again_start`, `again_pre_*`) and its round 1 shown (mark `again_r1`)."""
    before = dict(rec.marks)
    rec.click("title", TITLE_V2, 40)
    rec.t += 40
    opening(rec)
    for k in [k for k in rec.marks if k == "start" or k.startswith("pre_")]:
        rec.marks[f"again_{k}"] = rec.marks[k]
        rec.marks[k] = before[k]
    rec.marks["again_r1"] = rec.t + 20
    rec.t += 40


def outcome_of(rounds: list) -> str | None:
    s, pa, oa = rounds[-1]
    return resolve_round(s, pa, oa)[0].outcome


# ------------------------------------------------------------------------------------------------ harness

def harness_dir(route: str) -> Path:
    return TESTS / f"d1play_harness{route}"


def build_harness(route: str, rt=None, out: Path | None = None, pin: bool = True) -> None:
    """tests/d1play_harness<route>/ (or `out`): a copy of the game with one more flow (d1test, before the D01 engine)
    that writes the route's pinned opponent move of the round into the engine's test hook d1OppAct / d1OppCard
    (pin=False: nothing is pinned, his own AI plays; tests/check_d1_fuzz.py), and replaces the dev entry's loadout
    with the route's 20 ms after the title's v2 entry (the debate starts 100 ms after it, so the engine reads this
    loadout). Game paths may not leave the game directory, so it is a copy."""
    out = out or harness_dir(route)
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
    lo = rt.loadout
    nodes = [{"id": "late", "type": "timer", "params": {"interval": 0.02, "autostart": False, "repeat": False}}]
    edges = [{"from": "ui#title.v2dev", "to": "late.start"}]
    if pin:
        rows = [{"id": str(n), "act": oa.kind.value, "card": oa.card or ""}
                for n, (_, _, oa) in enumerate(forced(rt), start=1)]
        (out / "data" / "flow" / "d1test.json").write_text(
            "[\n" + ",\n".join(json.dumps(r) for r in rows) + "\n]\n", encoding="utf-8", newline="\n")
        game["tables"]["d1test"] = "data/flow/d1test.json"
        nodes += [
            {"id": "rnd", "type": "toString", "params": {"decimals": 0}},
            {"id": "row", "type": "atrium.table.find", "params": {"table": "d1test", "column": "id"}},
            {"id": "act", "type": "atrium.table.get", "params": {"table": "d1test", "column": "act", "type": "string"}},
            {"id": "card", "type": "atrium.table.get",
             "params": {"table": "d1test", "column": "card", "type": "string"}},
        ]
        edges += [
            {"from": "world.d1Round", "to": "rnd.in"},
            {"from": "rnd.out", "to": "row.value"},
            {"from": "row.row", "to": "act.row"},
            {"from": "row.row", "to": "card.row"},
            {"from": "act.value", "to": "world.d1OppAct"},
            {"from": "card.value", "to": "world.d1OppCard"},
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
TWICE = (("d1_twiceA", "A"), ("d1_twiceD", "D"))


def main() -> int:
    ticks = {}
    for route in ROUTES:
        build_harness(route)
    for name, route, no_skip in RECORDINGS:
        r = Rec(f"tests/d1play_harness{route}")
        play(r, forced(route), no_skip, outcome_of(forced(route)))
        ticks[name] = r.write(name, 60)
        ticks[name + "_marks"] = r.marks
    # v2 demo E6: a whole debate (a win, a loss), back to the title, the dev entry again (V1 first tick, V2 music)
    for name, route in TWICE:
        r = Rec(f"tests/d1play_harness{route}")
        play(r, forced(route), outcome=outcome_of(forced(route)))
        again(r)
        ticks[name] = r.write(name, 60)
        ticks[name + "_marks"] = r.marks
    bot = CV.play_debate("bot", RT.ROUTES["A"].loadout, BOT_DEBATE_SEED)
    r = Rec(".", BOT_SEED)
    play(r, [(st[2], st[0], None) for st in bot.steps], outcome=bot.steps[-1][3].outcome, final=bot.steps[-1][3])
    ticks["d1_bot"] = r.write("d1_bot", 60)
    ticks["d1_bot_marks"] = r.marks
    (TESTS / "d1_ticks.json").write_text(json.dumps(ticks, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
