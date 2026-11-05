# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Replay the debate recordings (tests/gen_debate_play.py) headless and check the debate UI, the cut-ins, the result
screen and the consequences (docs/flows.md §4.8, §4.9, §6; tests/README.md).

Usage (from the project root):
    uv run tests/check_debate_play.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS))
import check_playthrough as cp  # noqa: E402
import debate_routes as R  # noqa: E402
import gen_debate_play as gd  # noqa: E402

S = {}
for lang in ("zh-TW", "en"):
    import csv
    with open(ROOT / "strings" / f"{lang}.csv", encoding="utf-8-sig", newline="") as f:
        S[lang] = {r[0]: r[1] for r in list(csv.reader(f))[1:]}
ZH = S["zh-TW"]
PA_CODE = {"solid": 1, "sophistry": 2, "rebut": 3, "observe": 4}
OA_CODE = {"assert": 0, "rush": 1, "reinforce": 2, "trap": 3, "scorched": 4}


def run(rec: str, game: Path, ticks: int):
    dump = Path(tempfile.mkdtemp()) / "dump.json"
    args = [str(cp.EXE), "run", "--game", game.as_posix(), "--replay", str(TESTS / f"{rec}.atrec"),
            "--ticks", str(ticks), "--ports", "--dump", str(dump)]
    env = dict(os.environ, XTATRIUM_XTFRAME_DIR=cp.XTFRAME)
    old_cp = None
    if os.name == "nt":   # .NET writes redirected output in the console code page: UTF-8 for the child
        import ctypes
        old_cp = ctypes.windll.kernel32.GetConsoleOutputCP()
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    try:
        p = subprocess.run(args, capture_output=True, env=env)
    finally:
        if old_cp:
            ctypes.windll.kernel32.SetConsoleOutputCP(old_cp)
    out = p.stdout.decode("utf-8").replace("\r\n", "\n")
    err = p.stderr.decode("utf-8").replace("\r\n", "\n")
    if p.returncode != 0:
        raise SystemExit(f"error: xtatrium run exited {p.returncode}\n{err}")
    events = []
    for raw in out.split("\n"):
        m = cp.LINE.match(raw)
        if m:
            events.append((-1 if m.group(1) == "load" else int(m.group(1)), m.group(2), m.group(3)))
        elif raw and events:
            t, kind, rest = events[-1]
            events[-1] = (t, kind, rest + "\n" + raw)
    colls = json.loads(dump.read_text(encoding="utf-8"))["collections"]
    shutil.rmtree(dump.parent, ignore_errors=True)
    return events, err, colls


def items(colls, name):
    c = colls.get(name, {})
    return c.get("items", [e["key"] for e in c.get("entries", [])])


class Play:
    """The trace cut into debate rounds: per lock, the reveal and the state shown when the next round starts."""

    def __init__(self, events) -> None:
        self.tr = cp.Trace(events)
        self.writes = [(t, rest) for t, kind, rest in events if kind == "write"]
        self.rounds = []      # (reveal (me, opp), ports when the next round is shown, nodes json then)
        self.cuts = []        # ("big" | "stamp", id) in order
        self.results = []     # ports when the result screen is shown
        self.lines = []       # vn lines shown
        self.papers = []      # paper result_head when a paper step shows
        prev, reveal = {}, None
        for t, ports, vis, ch in self.tr.ticks:
            if ch.get("cutin.big_seq", 0) > 0:
                self.cuts.append(("big", ports.get("cutin.big")))
            if ch.get("cutin.stamp_seq", 0) > 0:
                self.cuts.append(("stamp", ports.get("cutin.stamp")))
            if ch.get("debate.reveal_seq", 0) > 0:
                reveal = (ports.get("debate.reveal_me"), ports.get("debate.reveal_opp"))
            if ch.get("debate.phase") in (0, 3) and reveal is not None:
                self.rounds.append((reveal, dict(ports), self.nodes_before(t + 2)))
                reveal = None
            if "result" in vis and "result" not in prev.get("vis", set()):
                self.results.append(dict(ports))
            if "vn.line" in ch and "vn" in vis:
                self.lines.append(ports["vn.line"])
            if "paper" in vis and "paper" not in prev.get("vis", set()):
                self.papers.append(ports.get("paper.result_head"))
            prev = {"vis": vis}

    def nodes_before(self, tick: int) -> list:
        last = None
        for t, rest in self.writes:
            if t > tick:
                break
            if rest.startswith("debate document.nodes "):
                last = json.loads(json.loads(rest[len("debate document.nodes "):]))
        return [n["id"] for n in last] if last else []

    def list_write(self, port: str) -> list:
        out = []
        for t, rest in self.writes:
            if rest.startswith(port + " "):
                out.append(json.loads(json.loads(rest[len(port) + 1:])))
        return out


def common(fail: cp.Failures, label: str, err: str) -> None:
    for line in err.splitlines():
        fail.check(not line.startswith(("warning:", "error:")), f"{label}: stderr: {line}")


def expected_cuts(route_events) -> list:
    out = []
    for recs in route_events:
        for rec in recs:
            f = rec.split("|")
            if f[0] != "cutin":
                continue
            if f[2] == "full" and f[5] == "1":
                out.append(("big", f[1]))
            elif f[1].startswith("STAMP_HACHIKU") and f[1][-1].isdigit():
                out.append(("stamp", "STAMP_HACHIKU"))
            elif f[1].startswith("STAMP_"):
                out.append(("stamp", f[1]))
            elif f[1] == "CUT_HACHIKU3":
                out.append(("stamp", "STAMP_HACHIKU"))
    return out


def scene_lines(chapter: int, scene: str, branch: str) -> list:
    return [ZH[r["text"]] for r in gd.gc.load("script") if r["chapter"] == chapter and r["scene"] == scene
            and r["playable"] and r["branch"] == branch]


def check_route(fail, label: str, play: Play, route_name: str) -> None:
    route = next(rt for rt in R.ROUTES if rt.name == route_name)
    _, _, (exp,) = R.build([route])
    want = [(PA_CODE[R.PA_NAME[p.kind]], OA_CODE[R.OA_NAME[o.kind]]) for p, o in route.moves]
    got = [r[0] for r in play.rounds]
    fail.check(got == want, f"{label}: reveals {got} != {want}")
    for i, (after, (_, ports, nodes)) in enumerate(zip(exp.after, play.rounds), start=1):
        if after["debOver"]:
            continue    # the last round: checked on the result screen
        for port, key in (("debate.hp_opp", "debOppHp"), ("debate.hp_me", "debPlayerHp")):
            if exp.route.chapter > 1:
                fail.check(abs(ports.get(port, 0) - after[key]) < 1e-9,
                           f"{label}: R{i} {port} {ports.get(port)} != ref {after[key]}")
        fail.check(nodes == after["nodes"], f"{label}: R{i} nodes {nodes} != ref {after['nodes']}")
        fail.check(ports.get("debate.st_hachiku") == after["debHachiku"],
                   f"{label}: R{i} hachiku {ports.get('debate.st_hachiku')} != {after['debHachiku']}")
        fail.check(bool(ports.get("debate.st_shaken")) == bool(after["debShaken"]),
                   f"{label}: R{i} shaken {ports.get('debate.st_shaken')} != {after['debShaken']}")
        fail.check(ports.get("debate.st_tail") == (after["debTailLeft"] if after["debInTail"] else 0),
                   f"{label}: R{i} tail {ports.get('debate.st_tail')}")
    want_cuts = expected_cuts(exp.events)
    fail.check(play.cuts == want_cuts, f"{label}: cut-ins {play.cuts} != {want_cuts}")


def check_result(fail, label, play: Play, k: int, win: int, comment: str, opp_line: str, trust=(-1, -1)) -> None:
    if len(play.results) <= k:
        fail.check(False, f"{label}: result screen {k + 1} not shown")
        return
    p = play.results[k]
    fail.check(p.get("result.win") == win, f"{label}: result win {p.get('result.win')} != {win}")
    fail.check(p.get("result.comment") == ZH[comment], f"{label}: comment {p.get('result.comment')!r}")
    fail.check(p.get("result.opp_line") == (ZH[opp_line] if opp_line else ""), f"{label}: opp_line")
    fail.check((p.get("result.trust_from"), p.get("result.trust_to")) == trust,
               f"{label}: trust {p.get('result.trust_from')} -> {p.get('result.trust_to')} != {trust}")
    fail.check(p.get("result.can_retry") == (win == 0), f"{label}: can_retry {p.get('result.can_retry')}")


def main() -> int:
    subprocess.run([sys.executable, str(TESTS / "gen_debate_play.py")], check=True, capture_output=True)
    ticks = json.loads((TESTS / "debate_ticks.json").read_text(encoding="utf-8"))
    fail = cp.Failures()

    # Ch.1: the G2 scripted rounds and the recommended route
    events, err, colls = run("ch1_debate", ROOT, ticks["ch1_debate"])
    play = Play(events)
    common(fail, "ch1_debate", err)
    check_route(fail, "ch1_debate", play, "ch1_route")
    fail.check([p["debate.counter_text"] for _, p, _ in play.rounds[:2]] ==
               [ZH["UI_CH1_CONTRA__1_2"], ZH["UI_CH1_CONTRA__2_4"]], "ch1_debate: contradiction counter")
    check_result(fail, "ch1_debate", play, 0, 1, "ART_RES_CLEAN", "SCR_CH01_S05_L028")
    want = scene_lines(1, "S06", "win") + scene_lines(1, "S07", "")
    fail.check(play.lines[-len(want):] == want, "ch1_debate: the result scene's win lines and the notes")
    fail.check(play.papers[-1:] == [ZH["NEWS_01_END"]], f"ch1_debate: Ch.2 paper strip {play.papers[-1:]}")

    # Ch.2: the recommended route against the scripted opponent (tests/play_harness)
    events, err, colls = run("ch2_debate", gd.HARNESS, ticks["ch2_debate"])
    play = Play(events)
    common(fail, "ch2_debate", err)
    check_route(fail, "ch2_debate", play, "ch2_route")
    check_result(fail, "ch2_debate", play, 0, 1, "ART_RES_CLEAN", "SCR_CH02_S05_L046")
    want = scene_lines(2, "S06", "win") + scene_lines(2, "S07", "")
    fail.check(play.lines[-len(want):] == want, "ch2_debate: the result scene's win lines and the notes")
    fail.check(play.papers[-1:] == [ZH["NEWS_02_WIN"]], f"ch2_debate: Ch.3 paper strip {play.papers[-1:]}")
    fail.check("E02_08" in items(colls, "held"), "ch2_debate: E02_08 not granted (ruling F3)")
    fail.check("G-01" in items(colls, "golden"), "ch2_debate: G-01 missing")
    fail.check(play.list_write("result document.costs")[-1:] == [[]], "ch2_debate: costs on a win")

    # Ch.2 lost (observe every round, the seeded AI), retried, lost again
    events, err, colls = run("ch2_lose", ROOT, ticks["ch2_lose"])
    play = Play(events)
    common(fail, "ch2_lose", err)
    for k in (0, 1):
        check_result(fail, f"ch2_lose[{k}]", play, k, 0, "ART_RES_LOSE", "")
    costs = play.list_write("result document.costs")
    fail.check(costs[-1:] == [[{"text": ZH["UI_RES_COST_SEIZE__E02_01"]}]], f"ch2_lose: costs {costs[-1:]}")
    rounds1 = [p.get("debate.round_text") for _, p, _ in play.rounds]
    fail.check(rounds1.count(ZH["UI_DEB_ROUND__2"]) >= 2, "ch2_lose: the retried debate starts at round 1 again")
    for k, res in enumerate(play.results[:2]):
        fail.check(res.get("debate.hp_me") == 0, f"ch2_lose[{k}]: lost at {res.get('debate.hp_me')}")
    want = scene_lines(2, "S06", "lose") + scene_lines(2, "S07", "")
    fail.check(play.lines[-len(want):] == want, "ch2_lose: the result scene's lose lines and the notes")
    fail.check(play.papers[-1:] == [ZH["NEWS_02_LOSE"]], f"ch2_lose: Ch.3 paper strip {play.papers[-1:]}")
    fail.check("G-01" not in items(colls, "golden"), "ch2_lose: G-01 kept after the loss")
    fail.check("E02_08" not in items(colls, "held"), "ch2_lose: E02_08 granted on a loss")
    fail.check(play.rounds and play.rounds[0][1].get("debate.hand") == 1, "ch2_lose: missed card hand")
    fail.check(play.rounds and play.rounds[0][1].get("debate.hp_opp_max") == 110, "ch2_lose: missed card HP +10")

    for f in fail.items:
        print("FAIL", f)
    print("ok" if not fail.items else f"{len(fail.items)} failure(s)")
    return 0 if not fail.items else 1


if __name__ == "__main__":
    sys.exit(main())
