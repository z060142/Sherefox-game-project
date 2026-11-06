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


def zf(key: str, **values) -> str:
    """The zh-TW template `key` with its {name} placeholders filled (what atrium.textf shows)."""
    text = ZH[key]
    for name, v in values.items():
        text = text.replace("{" + name + "}", str(v))
    return text
PA_CODE = {"solid": 1, "sophistry": 2, "rebut": 3, "observe": 4}
OA_CODE = {"assert": 0, "rush": 1, "reinforce": 2, "trap": 3, "scorched": 4}


def run(rec: str, game: Path, ticks: int, trace: list | None = None):
    """`trace`: a list that receives the run's --trace lines (per tick, every flow's node values)."""
    dump = Path(tempfile.mkdtemp()) / "dump.json"
    args = [str(cp.EXE), "run", "--game", game.as_posix(), "--replay", str(TESTS / f"{rec}.atrec"),
            "--ticks", str(ticks), "--ports", "--dump", str(dump)]
    if trace is not None:
        args += ["--trace", str(dump.parent / "trace.txt")]
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
    if trace is not None:
        trace.extend((dump.parent / "trace.txt").read_text(encoding="utf-8").splitlines())
    shutil.rmtree(dump.parent, ignore_errors=True)
    return events, err, colls


def items(colls, name):
    c = colls.get(name, {})
    return c.get("items", [e["key"] for e in c.get("entries", [])])


class Play:
    """The trace cut into debate rounds: per lock, the reveal and the state shown when the next round starts."""

    def __init__(self, events, start: int = 0) -> None:
        """`start`: only the ticks from then on (a recording that plays an earlier debate first)."""
        self.tr = cp.Trace(events)
        self.start = start
        self.writes = [(t, rest) for t, kind, rest in events if kind == "write"]
        self.rounds = []      # (reveal (me, opp), ports when the next round is shown, nodes json then)
        self.cuts = []        # ("big" | "stamp", id) in order
        self.results = []     # ports when the result screen is shown
        self.lines = []       # vn lines shown
        self.papers = []      # paper result_head when a paper step shows
        self.vs = []          # debate.preview_vs when each round's reveal starts (the locked choice's forecast)
        self.reviews = []     # ticks the opponent notes are shown in the defeat review
        self.result_ticks = []
        prev, reveal = {}, None
        for t, ports, vis, ch in self.tr.ticks:
            if t < start:
                prev = {"vis": vis}
                continue
            if ch.get("cutin.big_seq", 0) > 0:
                self.cuts.append(("big", ports.get("cutin.big")))
            if ch.get("cutin.stamp_seq", 0) > 0:
                self.cuts.append(("stamp", ports.get("cutin.stamp")))
            if ch.get("debate.reveal_seq", 0) > 0:
                reveal = (ports.get("debate.reveal_me"), ports.get("debate.reveal_opp"))
                self.vs.append(ports.get("debate.preview_vs"))
            if "notes" in vis and ports.get("notes.review"):
                self.reviews.append(t)
            if ch.get("debate.phase") in (0, 3) and reveal is not None:
                self.rounds.append((reveal, dict(ports), self.nodes_before(t + 2)))
                reveal = None
            if "result" in vis and "result" not in prev.get("vis", set()):
                self.results.append(dict(ports))
                self.result_ticks.append(t)
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
            if t >= self.start and rest.startswith(port + " "):
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


def cue_lines(chapter: int, scene: str, cue: str) -> list:
    """The debate scene's lines played on the vn around the debate (script.cue)."""
    return [ZH[r["text"]] for r in gd.gc.load("script") if r["chapter"] == chapter and r["scene"] == scene
            and r["playable"] and r["cue"] == cue]


def in_order(seq: list, want: list) -> bool:
    """`want` is a contiguous run of `seq`."""
    return any(seq[i:i + len(want)] == want for i in range(len(seq) - len(want) + 1))


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


ACT_KEY = {"claim": "UI_ACT_CLAIM", "rush": "UI_ACT_RUSH", "reinforce": "UI_ACT_REINFORCE", "trap": "UI_ACT_TRAP"}


def expected_vs(route_name: str) -> list:
    """preview_vs of each round of a ref route whose tells are clear (the play_harness script): 「若{action}：{result}」
    for the opponent's actual action, from the ref resolution of that round (docs/flows.md §4.8); "" for an
    observe or a tail round."""
    from sherefox_ref import events as E
    from sherefox_ref.model import OA, PA, initial_state
    from sherefox_ref.resolve import resolve_round
    route = next(rt for rt in R.ROUTES if rt.name == route_name)
    st = initial_state(route.case_fn(), route.board)
    out = []
    for p, o in route.moves:
        nxt, evs = resolve_round(st, p, o)
        if p.kind == PA.OBSERVE or st.in_tail:
            out.append("")
        else:
            opp = sum(e.amount for e in evs if isinstance(e, E.DamageToOpponent) and e.source in ("chain", "counter"))
            me = sum(e.amount for e in evs if isinstance(e, E.DamageToPlayer) and e.source in ("claim", "rush",
                                                                                                  "trap_crit"))
            atk = o.kind in (OA.CLAIM, OA.RUSH)
            if p.kind == PA.PARRY:
                res = zf("MSG_DEB_PARRY", n=R.g6(opp)) if atk else ZH["MSG_DEB_PARRY_WHIFF"]
            elif atk:
                res = f"{ZH['MSG_DEB_CLASH']}{R.g6(opp)}／−{R.g6(me)}"
            elif p.kind == PA.SOPHISTRY and o.kind == OA.TRAP:
                res = f"{ZH['MSG_DEB_TRAP_HIT']}0／−{R.g6(me)}"
            else:
                res = R.g6(opp)
            out.append(zf("UI_DEB_PREVIEW_VS", action=ZH[ACT_KEY[o.kind.value]], result=res))
        st = nxt
    return out


def check_reads(fail, label: str, play: Play, k: int, hit: int, total: int) -> None:
    """The result's 讀對預兆 row (UI_RES_READS {hit} / {total}, M5c)."""
    stats = play.list_write("result document.stats")
    row = {"label": zf("UI_RES_READS", hit=hit, total=total), "value": ""}
    fail.check(len(stats) > k and row in stats[k], f"{label}: reads row {row} not in {stats[k] if len(stats) > k else None}")


def bgm_sequence(trace: list) -> list:
    """The BGM ids the music flow wrote, in order (world.bgm: the flowBgm id in the music flow's trace values)."""
    out = []
    for line in trace:
        seg = line.split("flows/music.xtflow:")[-1]
        ids = [x for x in seg.split() if x.startswith("BGM")]
        if ids and (not out or out[-1] != ids[-1]):
            out.append(ids[-1])
    return out


def main() -> int:
    subprocess.run([sys.executable, str(TESTS / "gen_debate_play.py")], check=True, capture_output=True)
    # the game's flows compile with their endpoints resolved before anything is replayed (AT-036)
    cp.compile_game()
    ticks = json.loads((TESTS / "debate_ticks.json").read_text(encoding="utf-8"))
    fail = cp.Failures()

    # Ch.1: the G2 scripted rounds and the recommended route
    events, err, colls = run("ch1_debate", ROOT, ticks["ch1_debate"])
    play = Play(events)
    common(fail, "ch1_debate", err)
    check_route(fail, "ch1_debate", play, "ch1_route")
    fail.check([p["debate.counter_text"] for _, p, _ in play.rounds[:2]] ==
               [zf("UI_CH1_CONTRA", n=1, r=2), zf("UI_CH1_CONTRA", n=2, r=4)], "ch1_debate: contradiction counter")
    # Arthur's confession (S05 L027-L035, script.cue postWin) plays on the vn before the result, so the result does
    # not show his closing line again (flowDebCase.winPlayed)
    check_result(fail, "ch1_debate", play, 0, 1, "ART_RES_CLEAN", "")
    fail.check(in_order(play.lines, cue_lines(1, "S05", "pre")), "ch1_debate: the opening line before the debate")
    want = cue_lines(1, "S05", "postWin") + scene_lines(1, "S06", "win") + scene_lines(1, "S07", "")
    fail.check(len(want) > 12 and play.lines[-len(want):] == want,
               "ch1_debate: the confession, the result scene's win lines and the notes")
    fail.check(play.papers[-1:] == [ZH["NEWS_01_END"]], f"ch1_debate: Ch.2 paper strip {play.papers[-1:]}")
    route = next(rt for rt in R.ROUTES if rt.name == "ch1_route")
    check_reads(fail, "ch1_debate", play, 0, R.build([route])[2][0].after[-1]["debReads"], len(route.moves))

    # Ch.2: the recommended route against the scripted opponent (tests/play_harness)
    events, err, colls = run("ch2_debate", gd.HARNESS, ticks["ch2_debate"])
    play = Play(events)
    common(fail, "ch2_debate", err)
    check_route(fail, "ch2_debate", play, "ch2_route")
    check_result(fail, "ch2_debate", play, 0, 1, "ART_RES_CLEAN", "SCR_CH02_S05_L046")
    fail.check(in_order(play.lines, cue_lines(2, "S05", "pre")), "ch2_debate: the opening line before the debate")
    want = cue_lines(2, "S05", "postWin") + scene_lines(2, "S06", "win") + scene_lines(2, "S07", "")
    fail.check(len(want) > 2 and play.lines[-len(want):] == want,
               "ch2_debate: Wolfhart's cup, the result scene's win lines and the notes")
    fail.check(play.papers[-1:] == [ZH["NEWS_02_WIN"]], f"ch2_debate: Ch.3 paper strip {play.papers[-1:]}")
    fail.check("E02_08" in items(colls, "held"), "ch2_debate: E02_08 not granted (ruling F3)")
    fail.check("G-01" in items(colls, "golden"), "ch2_debate: G-01 missing")
    fail.check(play.list_write("result document.costs")[-1:] == [[]], "ch2_debate: costs on a win")
    want_vs = expected_vs("ch2_route")
    fail.check(play.vs == want_vs, f"ch2_debate: preview_vs {play.vs} != {want_vs}")
    route = next(rt for rt in R.ROUTES if rt.name == "ch2_route")
    check_reads(fail, "ch2_debate", play, 0, R.build([route])[2][0].after[-1]["debReads"], len(route.moves))

    # Ch.2 R5 (the tail) answered wrong: the 「（若尾聲出錯牌）」 line is the round's result line (M5c)
    events, err, colls = run("ch2_tailwrong", gd.HARNESS, ticks["ch2_tailwrong"])
    play = Play(events)
    common(fail, "ch2_tailwrong", err)
    fail.check([r[0] for r in play.rounds][4:5] == [(4, 4)], f"ch2_tailwrong: R5 reveal {[r[0] for r in play.rounds]}")
    rl = [p.get("debate.result_line") for _, p, _, ch in play.tr.ticks if "debate.result_line" in ch]
    fail.check(ZH["SCR_CH02_S05_L047"] in rl, f"ch2_tailwrong: result lines {rl[-6:]}")
    fail.check(ZH["MSG_TAIL_WRONG"].split("{")[0] not in "".join(rl), "ch2_tailwrong: MSG_TAIL_WRONG still shown")

    # Ch.3: Ch.2 won first (G-01 earned), then the warmup, the three scenes, the ref board and ch3_route against the
    # scripted opponent (tests/play_harness)
    events, err, colls = run("ch3_debate", gd.HARNESS, ticks["ch3_debate"])
    full = Play(events)
    play = Play(events, start=ticks["ch3_debate_from"])
    common(fail, "ch3_debate", err)
    check_route(fail, "ch3_debate", play, "ch3_route")
    check_result(fail, "ch3_debate", play, 0, 1, "ART_RES_CLEAN", "SCR_CH03_S06_L045", trust=(3, 4))
    fail.check(in_order(full.lines, cue_lines(3, "S04", "pre")) and in_order(full.lines, cue_lines(3, "S04", "postWin"))
               and not any(x in full.lines for x in cue_lines(3, "S04", "postLose")),
               "ch3_debate: the warmup's opening and wrap-up lines (passed: L006-L009)")
    route = next(rt for rt in R.ROUTES if rt.name == "ch3_route")
    check_reads(fail, "ch3_debate", play, 0, R.build([route])[2][0].after[-1]["debReads"], len(route.moves))

    fail.check(in_order(full.lines, cue_lines(3, "S06", "pre")), "ch3_debate: the opening line before the debate")
    want = scene_lines(3, "S07", "win") + scene_lines(3, "S08", "")
    fail.check(play.lines[-len(want):] == want, "ch3_debate: the result scene's win lines and the notes")
    fail.check(play.papers[-1:] == [ZH["NEWS_03_WIN"]], f"ch3_debate: final paper strip {play.papers[-1:]}")
    areas = []
    for _, p, vis, ch in full.tr.ticks:
        a = p.get("investigate.area_name")
        if "investigate" in vis and a and (not areas or areas[-1] != a):
            areas.append(a)
    want_areas = [ZH[k] for k in ("SCENE_CH03_BOILER", "SCENE_CH03_DECK", "SCENE_CH03_DOCK")]
    fail.check(areas[-3:] == want_areas, f"ch3_debate: scene names {areas}")
    msgs = [p.get("investigate.popup_body") for _, p, _, ch in full.tr.ticks if ch.get("investigate.popup_kind") == 4]
    fail.check(msgs == [ZH["MSG_INV_MISSED_NONE"]] * 2, f"ch3_debate: missed-cards messages {msgs}")
    fail.check("G-01" in items(colls, "golden"), "ch3_debate: G-01 missing")
    fail.check(items(colls, "oppHand") == [], f"ch3_debate: opponent hand {items(colls, 'oppHand')}")

    # Ch.3 warmup failed (tests/warmfail_harness: mistake limit 0): S04 F001-F004 instead of L006-L009, the case's
    # trust 2 (no police report: ART_NO_REPORT), and the music moments up to the investigation (rulings H1-H3)
    trace = []
    events, err, colls = run("ch3_warmfail", gd.WARMFAIL, ticks["ch3_warmfail"], trace)
    play = Play(events)
    common(fail, "ch3_warmfail", err)
    fail_lines = cue_lines(3, "S04", "postLose")
    fail.check(len(fail_lines) == 4 and in_order(play.lines, cue_lines(3, "S04", "pre") + fail_lines),
               f"ch3_warmfail: the failure wrap-up {play.lines[-6:]}")
    fail.check(not any(x in play.lines for x in cue_lines(3, "S04", "postWin")), "ch3_warmfail: L006-L009 played")
    hints = [p.get("investigate.hint") for _, p, _, ch in play.tr.ticks if ch.get("investigate.hint_seq", 0) != 0]
    fail.check(hints[:1] == [ZH["ART_NO_REPORT"]], f"ch3_warmfail: investigation opens with {hints[:1]}")
    bgm = bgm_sequence(trace)
    fail.check(bgm == ["BGM01", "BGM02", "BGM07", "BGM05"], f"ch3_warmfail: music {bgm}")

    # Ch.2 lost (observe every round, the seeded AI), retried, lost again
    events, err, colls = run("ch2_lose", ROOT, ticks["ch2_lose"])
    play = Play(events)
    common(fail, "ch2_lose", err)
    for k in (0, 1):
        check_result(fail, f"ch2_lose[{k}]", play, k, 0, "ART_RES_LOSE", "")
    costs = play.list_write("result document.costs")
    fail.check(costs[-1:] == [[{"text": zf("UI_RES_COST_SEIZE", name=ZH["E02_01_NAME"])}]], f"ch2_lose: costs {costs[-1:]}")
    rounds1 = [p.get("debate.round_text") for _, p, _ in play.rounds]
    fail.check(rounds1.count(zf("UI_DEB_ROUND", n=2)) >= 2, "ch2_lose: the retried debate starts at round 1 again")
    pre = cue_lines(2, "S05", "pre")
    fail.check(sum(play.lines.count(x) for x in pre) == len(pre), "ch2_lose: the retry plays the opening line again")
    # 臨場硬接 in R1 (M5c): sophistry on E02_03 -> E02_02, the button, the only candidate E02_04 (wrong reason: a
    # sophistry link by the board's rule, ref link_kind), the chain grows, the damage is the ref chain damage
    from sherefox_ref.fixtures import ch2_case as ref_ch2
    from sherefox_ref.rules import chain_damage_breakdown, link_kind
    from dataclasses import replace as dc_replace
    cards = {c.id: c for c in ref_ch2().cards}
    kind = link_kind(cards["E02_02"], dc_replace(cards["E02_04"], reason_correct=False))
    fail.check(kind == "sophistry", f"ch2_lose: ref link E02_02 - E02_04 {kind}")
    t0, t1 = ticks["ch2_lose_prompt"], ticks["ch2_lose_picked"]
    fail.check(any(p.get("debate.improv_ok") for t, p, _, _ in play.tr.ticks if t0 - 2 <= t <= t0 + 4),
               "ch2_lose: 臨場硬接 not offered")
    picks = [(t, json.loads(json.loads(rest.split(" ", 2)[2]))) for t, rest in play.writes
             if rest.startswith("debate document.parry_cards ") and t0 <= t <= t1]
    fail.check([x for _, x in picks if x][:1] == [[{"id": "E02_04", "name": ZH["E02_04_NAME"]}]],
               f"ch2_lose: 臨場硬接 candidates {picks}")
    fail.check(any(p.get("debate.picker_title") == ZH["BTN_DEB_SOPH_NEW"] for t, p, _, _ in play.tr.ticks
                   if t0 <= t <= t1), "ch2_lose: picker title")
    chains = [(t, json.loads(json.loads(rest.split(" ", 2)[2]))) for t, rest in play.writes
              if rest.startswith("debate document.chains ") and t1 <= t <= t1 + 20]
    want_ch = [(0, 0, "E02_03", 1), (0, 1, "E02_02", 2), (0, 2, "E02_04", 0)]
    fail.check(bool(chains) and [(c["chain"], c["pos"], c["id"], c["link"]) for c in chains[-1][1]] == want_ch,
               f"ch2_lose: chain after 臨場硬接 {chains[-1:]}")
    me, opp = play.rounds[0][0]
    fail.check(me == 2, f"ch2_lose: R1 reveal {play.rounds[0][0]}")
    dmg = 0.0 if opp == 3 else chain_damage_breakdown(1, 1, False, 0, opp in (0, 1), False)[0]
    got = [p.get("debate.float_opp") for t, p, _, ch in play.tr.ticks if "debate.float_opp" in ch and t1 < t]
    fail.check((dmg == 0 and "" in got[:1]) or f"−{R.g6(dmg)}" in got[:2], f"ch2_lose: R1 damage {got[:2]} != {dmg}")
    # retry: the board as it was locked (the improvised link undone)
    board = items(colls, "debBoard")
    fail.check(board[:3] == ["E02_03", "E02_02", "-"] and "E02_04" in board[15:], f"ch2_lose: board after retry {board}")
    # the opponent notes (§4.4): the defeat review before each result (tab 2), one log row a round, the misread rows
    # marked; their count agrees with the result's 讀對預兆; R1 (sophistry) is misread with Arthur's review line
    for k, rt in enumerate(play.result_ticks[:2]):
        before = play.result_ticks[k - 1] if k else 0
        fail.check(any(before < t < rt for t in play.reviews), f"ch2_lose[{k}]: no review before the result")
    logs = [(t, json.loads(json.loads(rest.split(" ", 2)[2]))) for t, rest in play.writes
            if rest.startswith("notes document.log ")]
    stats = play.list_write("result document.stats")
    for k, rt in enumerate(play.result_ticks[:2]):
        rows = [x for t, x in logs if t < rt][-1:] or [[]]
        rows = rows[0]
        total = len(rows)
        hit = sum(1 for x in rows if not x["mark"])
        fail.check(total > 3 and all(x["text"].startswith(zf("UI_NOTES_LOG_ROW", n=i + 1, tell="").split("：")[0])
                                     for i, x in enumerate(rows)), f"ch2_lose[{k}]: log rows {rows[:2]}")
        check_reads(fail, f"ch2_lose[{k}]", play, k, hit, total)
    rows = [x for t, x in logs if t < play.result_ticks[0]][-1]
    review = {0: "ART_REVIEW_CLASH", 1: "ART_REVIEW_CLASH", 2: "ART_REVIEW_HEAL", 3: "ART_REVIEW_TRAP"}[opp]
    fail.check(rows[0]["mark"] and rows[0]["note"] == ZH[review], f"ch2_lose: R1 log row {rows[0]}")
    gest = play.list_write("notes document.gestures")
    fail.check(bool(gest) and len(gest[-1]) == 4 and all(g["text"] for g in gest[-1]), f"ch2_lose: gestures {gest[-1:]}")
    fail.check(any(p.get("notes.tab") == 2 for _, p, _, _ in play.tr.ticks), "ch2_lose: notes tab")
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
