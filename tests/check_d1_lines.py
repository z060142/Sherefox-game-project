# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Scripted D01 debates that reach the playback lines the four ref routes do not (v2 demo E3: review findings R2-R7,
ruling 7), replayed headless; what the d1debate screen shows is checked against the ref model (docs/flows.md §4.12,
tests/README.md).

Each scenario is a forced-opponent replay like tests/gen_d1_play.py's routes: a harness copy of the game pins his
move of every round through the engine's test hook (d1OppAct / d1OppCard) and loads the scenario's loadout on the dev
shortcut. The recording clicks the screen the M2 way. Per round, tests/check_d1_play.py check_lines compares the
system lines with the ref's events (every line ch §12.0 calls for, with its numbers; no other line under test) and the
斷 stamp with the ref's combo.

- S1 (route A's loadout): 截斷 vs his 反駁 (BOTH_REBUT, no FOOLED), a clash (CLASH), a 正論 拆台 on his fact F1
  (TOPPLE_MISS_FACT, −10), 打迷糊仗 vs 立論, a 拆台 whose claim does not break L1 (TOPPLE_MISS_WRONG, −5), 打迷糊仗 vs
  反駁 twice (FOOLED, then FOG_REPEAT and no FOOLED), a sophistry 截斷 on his fact F2 (DENY_FACT), a failed 截斷 that
  drops 破竹 with the combo kept (no 斷), a sophistry exposed with combo 1 (斷). The text language is switched to
  English in round 4 through the settings overlay (F1) before choosing: lines, the round counter, 破竹 and the public
  record's rounds follow. Every round after the first starts with no evidence chosen (R4).
- S2 (route A's loadout): a sophistry on the chain, a Break with one crack, his last card K1 taken: it hits, removes
  the cracked link and the debate goes on (LASTCARD_HIT with his recovery, LASTCARD_REMOVE), then a second zero
  (ZERO_WIN). The Break round's playback is clicked on the cut-in surface as well as the screen while the cut-in plays.
- S3 (route A's loadout): both sides stall to the round limit: round 20 ends as the ref says (a loss on credibility,
  UI_V2_TIME_UP).

Usage (from the project root):
    uv run tests/check_d1_lines.py [--shots DIR]    --shots also writes a failed-拆台 line and a LASTCARD_HIT line
                                                    (zh-TW and en) to DIR
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS))
import check_d1_m3 as cm  # noqa: E402
import check_d1_play as cd  # noqa: E402
import check_playthrough as cp  # noqa: E402
import gen_d1_play as gd  # noqa: E402
import gen_playthrough as gp  # noqa: E402
from sherefox_ref.v2 import routes as RT  # noqa: E402
from sherefox_ref.v2.model import PA, PlayerAction  # noqa: E402
from xt_cli import compile_game  # noqa: E402

S = cd.S
A, R, P = RT.AT, RT.RE, RT.PR


def dis(claim: str, target: str) -> PlayerAction:
    return PlayerAction(PA.DISMANTLE, claim, target)


def route(name: str, rounds: list) -> RT.Route:
    return RT.Route(name, RT.ROUTES["A"].loadout, tuple((pa, oa, None) for pa, oa in rounds))


op = RT.opp
SCENARIOS = {
    "S1": route("S1", [(RT.cut("11A"), op(R)), (RT.argue("04A"), op(A, "F1")), (dis("06A", "F1"), op(P)),
                       (RT.stall(), op(A, "L1")), (dis("04B", "L1"), op(P)), (RT.stall(), op(R)), (RT.stall(), op(R)),
                       (RT.cut("06B"), op(A, "F2")), (RT.cut("11B"), op(A, "L3")), (RT.argue("01B"), op(R))]),
    "S2": route("S2", [(RT.argue("01B"), op(P)), (RT.argue("04A"), op(P)), (RT.argue("08A"), op(P)),
                       (RT.cut("11A"), op(A, "L1")), (RT.argue("10A"), op(P)), (RT.accept(), op(RT.LAST, "K1")),
                       (RT.argue("01A"), op(P)), (RT.argue("06A"), op(P)), (RT.argue("11B"), op(P))]),
    "S3": route("S3", [(RT.stall(), op(P))] * 20),
}
LANG_SWITCH = ("S1", 4)        # (scenario, round): English chosen in the settings overlay before that round's choice
CUTIN_CLICKS = ("S2", 5)       # (scenario, round): the playback is clicked on ui#cutin and ui#d1debate
NO_SKIP = {("S1", 3), ("S2", 6)}   # rounds played back without clicks (the failed 拆台, his last card)


def record(name: str, rt: RT.Route) -> tuple[int, dict]:
    rec = gd.Rec(f"tests/d1play_harness{name}")
    rec.click("title", gd.TITLE_V2, 40)
    rec.t += 40
    for n, (s, pa, _) in enumerate(gd.forced(rt), start=1):
        if (name, n) == LANG_SWITCH:
            rec.lines.append(cp_json({"t": rec.t + 10, "u": gp.key("d1debate", gp.KEY_F1)}))
            rec.t += 10 + gp.SETTLE
            rec.click("settings", gp.SET_LANG[1], 0)
            rec.t += gp.GAP
            rec.lines.append(cp_json({"t": rec.t, "u": gp.key("settings", gp.KEY_ESC)}))
            rec.t += gp.SETTLE
        rec.marks[f"shown{n}"] = rec.t + 6
        act = gd.PA_ACT[pa.kind]
        rec.click("d1debate", gd.ACT_XY[act], 12)
        if pa.claim is not None:
            pk = gd.picker(s)
            claim = f"CATCH:{s.catch_card}" if pa.claim == "CATCH" else pa.claim
            ev = "CATCH" if claim.startswith("CATCH") else s.ch.claims[claim].evidence
            i = [e for e, _ in pk].index(ev)
            rec.click("d1debate", gd.ev_xy(i))
            rec.click("d1debate", gd.claim_xy(pk[i][1].index(claim)))
        chain = [nd.card for nd in s.opp_chain]
        if pa.target in chain:
            rec.click("d1debate", gd.chain_xy(chain.index(pa.target)))
        rec.marks[f"chosen{n}"] = rec.t + 4
        rec.click("d1debate", gd.LOCK_XY)
        rec.marks[f"lock{n}"] = rec.t
        if (name, n) in NO_SKIP:       # the playback at its own pace: the review screenshots see whole lines
            rec.t += 900
        for k in range(0 if (name, n) in NO_SKIP else gd.SKIPS):
            ui = "cutin" if (name, n) == CUTIN_CLICKS and k % 2 == 0 else "d1debate"
            rec.click(ui, gd.SKIP_XY, gd.SKIP_GAP)
            if ui == "cutin":
                rec.marks.setdefault("cutin_clicks", []).append(rec.t)
        rec.t += gd.ROUND_TAIL
    rec.marks["over"] = rec.t
    rec.click("d1debate", gd.BACK_XY, 30)
    end = rec.write(f"d1_lines_{name}", 60)
    return end, rec.marks


def cp_json(o: dict) -> str:
    import json
    return json.dumps(o)


def check(name: str, rt: RT.Route, end: int, marks: dict, fails: list):
    rounds = gd.forced(rt)
    switch = LANG_SWITCH[1] if LANG_SWITCH[0] == name else None

    def lang_of(n: int) -> str:
        return "en" if switch and n >= switch else "zh-TW"
    events, err = cd.run(f"d1_lines_{name}", f"tests/d1play_harness{name}", end, "zh-TW")
    tr = cp.Trace(events)
    at = cm.At(tr, events)
    bad = cd.check_lines(tr, rounds, marks, lang_of, marks["over"])
    # the outcome panel and round count equal the ref's
    grade, nrounds, outcome = cd.expected(rounds)
    L = S[lang_of(len(rounds))]
    t = marks["over"] - 5
    panel = () if outcome is None else (
        ("d1debate.grade_text", L[f"UI_V2_GRADE_{grade}"]),
        ("d1debate.rounds_text", L["UI_V2_RESULT_ROUNDS"].replace("{n}", str(nrounds))),
        ("d1debate.outcome_win", outcome == "win"), ("d1debate.mode", 3))
    for port, want in panel:
        if at.get(t, port) != want:
            bad.append(f"outcome {port}={at.get(t, port)!r} (want {want!r})")
    # R4: a new round starts with no evidence chosen; R7: 破竹 and the record's rounds are string keys, in the
    # language of the moment
    for n, (s, pa, _) in enumerate(rounds, start=1):
        lg = lang_of(n)
        tm = marks[f"shown{n}"]
        evs = at.get(tm, "d1debate.ev_list") or []
        if n > 1 and any(e["sel"] for e in evs):
            bad.append(f"R{n}: evidence still chosen when the round starts: {[e['id'] for e in evs if e['sel']]}")
        want_rt = S[lg]["UI_V2_ROUND"].replace("{n}", str(n)).replace("{max}", "20")
        if at.get(tm, "d1debate.round_text") != want_rt:
            bad.append(f"R{n}: round_text {at.get(tm, 'd1debate.round_text')!r} (want {want_rt!r})")
        if s.hachiku and at.get(tm, "d1debate.hachiku_text") != S[lg]["UI_STATE_HACHIKU"].replace("{n}", str(s.hachiku)):
            bad.append(f"R{n}: hachiku_text {at.get(tm, 'd1debate.hachiku_text')!r}")
        rows = [r["n"] for r in (at.get(tm, "d1debate.record") or [])]
        want_rows = [S[lg]["UI_DEB_ROUND"].replace("{n}", str(e.round)) for e in s.record]
        if rows != want_rows:
            bad.append(f"R{n}: record rounds {rows} (want {want_rows})")
    if name == CUTIN_CLICKS[0]:
        n = CUTIN_CLICKS[1]
        bigs = [t for t, p, v, c in tr.ticks if marks[f"lock{n}"] <= t < marks[f"lock{n + 1}"] and "cutin.big_seq" in c]
        during = [c for c in marks.get("cutin_clicks", []) if any(b <= c < b + 96 for b in bigs)]
        if not bigs or not during:
            bad.append(f"R{n}: no click during a cut-in (cut-ins at {bigs})")
    if name == "S3":
        lines, _ = cd.shown(tr, marks[f"lock{len(rounds)}"], marks["over"])
        if S["zh-TW"]["UI_V2_TIME_UP"] not in lines:
            bad.append(f"round {len(rounds)}: UI_V2_TIME_UP not shown ({lines})")
    noise = [ln for ln in err.split("\n") if ln.strip() and not ln.startswith("render: off")]
    if noise:
        bad.append("stderr: " + " | ".join(noise[:5]))
    if bad:
        fails.append(name)
        print(f"FAIL {name}: " + "\n  ".join(bad[:25]))
    else:
        print(f"PASS {name}: {len(rounds)} rounds, grade {grade}, {outcome}")
    return tr


# review screenshots (--shots DIR): a failed 拆台 on a fact (S1) and his last card recovering (S2), zh-TW and en
SHOTS = {"S1": ("topple_miss_fact", "SYS_D01_TOPPLE_MISS_FACT"), "S2": ("lastcard_hit", "SYS_D01_LASTCARD_HIT")}


def shots(out: Path, name: str, tr, end: int) -> None:
    import subprocess
    from xt_cli import EXE, XTFRAME
    shot, key = SHOTS[name]
    pt = cd.pattern("zh-TW", key)
    t0 = next(t for t, p, v, c in tr.ticks if "d1debate.sys_line" in c and pt.match(p["d1debate.sys_line"])) + 40
    out.mkdir(parents=True, exist_ok=True)
    for lang in ("zh-TW", "en"):
        tmp = Path(tempfile.mkdtemp(prefix="d1linesshots-"))
        try:
            p = subprocess.run([str(EXE), "shot", "--game", f"tests/d1play_harness{name}", "--replay",
                                str(TESTS / f"d1_lines_{name}.atrec"), "--at", str(t0), "--out", str(tmp),
                                "--lang", lang], capture_output=True, cwd=ROOT,
                               env=dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME))
            if p.returncode != 0:
                raise SystemExit(f"shot failed: {p.stderr.decode('utf-8', 'replace')}")
            shutil.copyfile(tmp / f"shot-{t0:06d}.png", out / f"{shot}_{lang}.png")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    compile_game()
    temp = Path(tempfile.gettempdir())
    before = set(os.listdir(temp))
    fails: list[str] = []
    try:
        for name, rt in SCENARIOS.items():
            gd.build_harness(name, rt)
            end, marks = record(name, rt)
            tr = check(name, rt, end, marks, fails)
            if "--shots" in sys.argv and name in SHOTS:
                shots(Path(sys.argv[sys.argv.index("--shots") + 1]), name, tr, end)
    finally:
        for name in SCENARIOS:
            shutil.rmtree(gd.harness_dir(name), ignore_errors=True)
            (TESTS / f"d1_lines_{name}.atrec").unlink(missing_ok=True)
    left = sorted(n for n in set(os.listdir(temp)) - before if n.startswith(("tmp", "d1linesshots-")))
    if left:
        fails.append("temp")
        print("FAIL temp: left in %TEMP%: " + ", ".join(left))
    print("ok" if not fails else f"FAILED: {', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
