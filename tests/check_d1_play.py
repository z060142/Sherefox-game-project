# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Replay the v2 demo D01 debate recordings (tests/gen_d1_play.py) headless and check what the d1debate screen shows
(docs/flows.md §4.12, docs/ui-contracts.md d1debate, tests/README.md).

Each recording plays the whole debate by clicking the screen; the check compares the outcome panel (grade, round count,
win / loss) with the ref model's result for the same moves, checks that every round was locked (the round counter
reached the ref's count), that the back to title button returns to the title, and that nothing was logged on stderr
(an unknown string key, a flow error). Route A also runs in English.

Usage (from the project root):
    uv run tests/check_d1_play.py [--shots DIR]     --shots also writes the review screenshots (zh-TW and en) to DIR
"""

from __future__ import annotations

import csv
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
import gen_d1_play as gd  # noqa: E402
from xt_cli import EXE, XTFRAME, compile_game  # noqa: E402

S = {}
for _lang in ("zh-TW", "en"):
    with open(ROOT / "strings" / f"{_lang}.csv", encoding="utf-8-sig", newline="") as _f:
        S[_lang] = {r[0]: r[1] for r in list(csv.reader(_f))[1:]}


def run(rec: str, game: str, ticks: int, lang: str) -> tuple[list, str]:
    args = [str(EXE), "run", "--game", game, "--replay", str(TESTS / f"{rec}.atrec"), "--ticks", str(ticks),
            "--ports", "--lang", lang]
    env = dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME)
    old_cp = None
    if os.name == "nt":   # .NET writes redirected output in the console code page: UTF-8 for the child
        import ctypes
        old_cp = ctypes.windll.kernel32.GetConsoleOutputCP()
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    try:
        p = subprocess.run(args, capture_output=True, env=env, cwd=ROOT)
    finally:
        if old_cp:
            ctypes.windll.kernel32.SetConsoleOutputCP(old_cp)
    out = p.stdout.decode("utf-8").replace("\r\n", "\n")
    err = p.stderr.decode("utf-8").replace("\r\n", "\n")
    if p.returncode != 0:
        raise SystemExit(f"error: xtatrium run {rec} exited {p.returncode}\n{err}")
    events = []
    for raw in out.split("\n"):
        m = cp.LINE.match(raw)
        if m:
            events.append((-1 if m.group(1) == "load" else int(m.group(1)), m.group(2), m.group(3)))
        elif raw and events:
            t, kind, rest = events[-1]
            events[-1] = (t, kind, rest + "\n" + raw)
    return events, err


def expected(rounds: list) -> tuple[int, int, str]:
    """(grade, rounds played, outcome) of the ref for the recording's moves."""
    from sherefox_ref.v2.resolve import resolve_round
    s, pa, oa = rounds[-1]
    if oa is None:   # the bot run: the last state is in the steps
        raise ValueError
    s2, _ = resolve_round(s, pa, oa)
    return s2.grade, s2.round - 1, s2.outcome


def check(label: str, rec: str, game: str, ticks: int, marks: dict, want: tuple[int, int, str], lang: str,
          fails: list) -> None:
    events, err = run(rec, game, ticks, lang)
    tr = cp.Trace(events)
    at_over = [p for t, p, v, c in tr.ticks if t <= marks["over"]][-1]
    end_vis = tr.ticks[-1][2]
    grade, nrounds, outcome = want
    exp = {"d1debate.grade_text": S[lang][f"UI_V2_GRADE_{grade}"],
           "d1debate.rounds_text": S[lang]["UI_V2_RESULT_ROUNDS"].replace("{n}", str(nrounds)),
           "d1debate.outcome_win": outcome == "win", "d1debate.mode": 3}
    bad = [f"{k}={at_over.get(k)!r} (want {v!r})" for k, v in exp.items() if at_over.get(k) != v]
    rounds_seen = {p.get("d1debate.round_text") for t, p, v, c in tr.ticks}
    last_round = S[lang]["UI_V2_ROUND"].replace("{n}", str(nrounds)).replace("{max}", "20")
    if last_round not in rounds_seen:
        bad.append(f"round {nrounds} was never shown ({last_round!r})")
    if "title" not in end_vis or "d1debate" in end_vis:
        bad.append(f"after back to title the visible screens are {sorted(end_vis)}")
    noise = [ln for ln in err.split("\n") if ln.strip() and not ln.startswith("render: off")]
    if noise:
        bad.append("stderr: " + " | ".join(noise[:5]))
    if bad:
        fails.append(label)
        print(f"FAIL {label}: " + "; ".join(bad))
    else:
        print(f"PASS {label}: grade {grade} ({exp['d1debate.grade_text']}), {nrounds} rounds, {outcome}")


def ronpa_tick(rec: str, game: str, ticks: int) -> int:
    events, _ = run(rec, game, ticks, "zh-TW")
    tr = cp.Trace(events)
    for t, p, v, c in tr.ticks:
        if c.get("cutin.big_seq", 0) > 0 and p.get("cutin.big") == "CUT_RONPA":
            return t
    raise SystemExit("shots: no 論破 cut-in in d1_shots")


def shots(out: Path, ticks: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    mA, mD = ticks["d1_shots_marks"], ticks["d1_routeD_marks"]
    rp = ronpa_tick("d1_shots", "tests/d1play_harnessA", ticks["d1_shots"])
    plan = [("d1_shots", "tests/d1play_harnessA", ticks["d1_shots"],
             {"choose_picker": mA["chosen3"], "playback": mA["lock2"] + 60, "ronpa": rp + 80,
              "endgame": mA["chosen9"], "outcome_win": mA["over"] - 5}),
            ("d1_routeD", "tests/d1play_harnessD", ticks["d1_routeD"],
             {"laststand": mD["chosen8"], "outcome_loss": mD["over"] - 5})]
    for rec, game, n, named in plan:
        for lang in ("zh-TW", "en"):
            tmp = Path(tempfile.mkdtemp(prefix="d1shots-"))
            try:
                at = ",".join(str(t) for t in named.values())
                p = subprocess.run([str(EXE), "shot", "--game", game, "--replay", str(TESTS / f"{rec}.atrec"), "--at", at,
                                    "--out", str(tmp), "--lang", lang], capture_output=True, cwd=ROOT,
                                   env=dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME))
                if p.returncode != 0:
                    raise SystemExit(f"shot {rec} failed: {p.stderr.decode('utf-8', 'replace')}")
                for name, t in named.items():
                    shutil.copyfile(tmp / f"shot-{t:06d}.png", out / f"{name}_{lang}.png")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    print(f"shots: {out}")


def main() -> int:
    argv = sys.argv[1:]
    compile_game()
    temp = Path(tempfile.gettempdir())
    before = set(os.listdir(temp))
    fails: list[str] = []
    try:
        if subprocess.run([sys.executable, str(TESTS / "gen_d1_play.py")], cwd=ROOT).returncode != 0:
            raise SystemExit("gen_d1_play failed")
        ticks = json.loads((TESTS / "d1_ticks.json").read_text(encoding="utf-8"))
        for label, rec, route, lang in (("route A", "d1_routeA", "A", "zh-TW"), ("route A [en]", "d1_routeA", "A", "en"),
                                        ("route D", "d1_routeD", "D", "zh-TW")):
            check(label, rec, f"tests/d1play_harness{route}", ticks[rec], ticks[rec + "_marks"],
                  expected(gd.forced(route)), lang, fails)
        bot = gd.CV.play_debate("bot", gd.RT.ROUTES["A"].loadout, gd.BOT_SEED)
        last = bot.steps[-1][3]
        check(f"seeded AI (seed {gd.BOT_SEED})", "d1_bot", ".", ticks["d1_bot"], ticks["d1_bot_marks"],
              (last.grade, last.round - 1, last.outcome), "zh-TW", fails)
        if "--shots" in argv:
            shots(Path(argv[argv.index("--shots") + 1]), ticks)
    finally:
        for route in ("A", "D"):
            shutil.rmtree(gd.harness_dir(route), ignore_errors=True)
    left = sorted(n for n in set(os.listdir(temp)) - before if n.startswith(("d1shots-", "tmp")))
    if left:
        fails.append("temp")
        print("FAIL temp: left in %TEMP%: " + ", ".join(left))
    print("ok" if not fails else f"FAILED: {', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
