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
import re
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


# ---- the playback's system lines (E3: every line and number from the round's records; ch §12.0 names the line)

SYS_UNDER_TEST = ("SYS_D01_BOTH_REBUT", "SYS_D01_CUT_EMPTY", "SYS_D01_MISS_WRONG", "SYS_D01_TOPPLE_MISS_FACT",
                  "SYS_D01_TOPPLE_MISS_WRONG", "SYS_D01_FOOLED", "SYS_D01_FOG_REPEAT", "SYS_D01_CLASH",
                  "SYS_D01_LASTCARD_HIT", "SYS_D01_LASTCARD_NOHEAL", "SYS_D01_LASTCARD_REMOVE", "SYS_D01_ZERO_WIN",
                  "SYS_D01_KEY_BREAK", "SYS_D01_KEY_NORMAL", "SYS_D01_DENY_FACT", "SCR_D01_S07_L005",
                  "SCR_D01_S07_L006")


def num(v: float) -> str:
    return "%.6g" % v


def render(lang: str, key: str, vals: dict) -> str:
    out = S[lang][key].replace("{name}", S[lang]["SPK_D01_CEDRIC"])
    for k, v in vals.items():
        out = out.replace("{" + k + "}", v if isinstance(v, str) else num(v))
    return out


def pattern(lang: str, key: str):
    parts = re.split(r"\{[a-z_]+\}", S[lang][key].replace("{name}", S[lang]["SPK_D01_CEDRIC"]))
    return re.compile("^" + ".*".join(re.escape(x) for x in parts) + "$", re.S)


def ref_lines(s, pa, ev: list, s2) -> tuple[list[tuple[str, dict]], bool]:
    """The ref's oracle for one round: the system lines under test that ch §12.0 calls for, with their numbers taken
    from the ref's events (state before s, player action pa, events ev, state after s2), and whether the player's
    combo resets to 0 (the 斷 stamp, ruling 7)."""
    from sherefox_ref.v2 import known as K
    from sherefox_ref.v2 import model as M
    from sherefox_ref.v2.model import PA

    def first(kind, **f):
        return next((e for e in ev if e["kind"] == kind and all(e.get(k) == v for k, v in f.items())), None)
    kinds = [e["kind"] for e in ev]
    out: list[tuple[str, dict]] = []
    pd = [e for e in ev if e["kind"] == "player_damage"]
    whiff = next((e for e in pd if e["cause"] == "whiff"), None)
    if pa.kind == PA.INTERCEPT and whiff:
        icp = first("intercept")
        if icp is None and first("opp_damage", cause="whiff"):
            out.append(("SYS_D01_BOTH_REBUT", {}))
        elif icp is None:
            out.append(("SYS_D01_CUT_EMPTY", {}))
        elif not icp.get("blocked_by_parry"):
            out.append(("SYS_D01_MISS_WRONG", {"hp": whiff["hp"]}))
    if pa.kind == PA.DISMANTLE and whiff:
        d = first("dismantle")
        soph = K.view(s, pa.claim).soph
        if not s.ch.cards[d["card"]].is_fact:
            out.append(("SYS_D01_TOPPLE_MISS_WRONG", {"dmg": whiff["amount"], "hp": whiff["hp"]}))
        elif not soph:
            out.append(("SYS_D01_TOPPLE_MISS_FACT", {"dmg": whiff["amount"], "hp": whiff["hp"]}))
    if any(e["cause"] == "bad_cut" for e in pd):
        out.append(("SYS_D01_MISS_WRONG", {"hp": next(e for e in pd if e["cause"] == "bad_cut")["hp"]}))
    st = first("stall")
    if st and st["vs"] == "rebut" and not st["repeat"]:
        out.append(("SYS_D01_FOOLED", {"hp": first("opp_damage", cause="whiff")["hp"]}))
    if any(e["cause"] == "stall_repeat" for e in pd):
        out.append(("SYS_D01_FOG_REPEAT", {}))
    pat, oat = first("player_attach"), first("opp_attach")
    if pat and oat and s.ch.cards[oat["card"]].kind != "unfav":
        hit = next(e for e in pd if e["cause"] == "argument")
        out.append(("SYS_D01_CLASH", {"dmg_p": pat["damage"], "hp_o": first("opp_damage", cause="argument")["hp"],
                                      "dmg_o": hit["amount"], "hp_p": hit["hp"]}))
    lc = first("last_card", cut=False)
    if lc and not lc.get("dying"):
        lcd = next(e for e in pd if e["cause"] == "last_card")
        if s2.outcome:
            out.append(("SYS_D01_LASTCARD_NOHEAL", {}))
        elif "heal_void" not in kinds:
            c0 = s.cracks
            f = num(M.LAST_ZERO_C_DMG) if c0 == 0 else f"{num(M.LAST_PER_CRACK)} × {c0}"
            if s.ch.cards[lc["card"]].kind == "pickup":
                f += f" + {num(M.LAST_PICKED_EXTRA)}"
            out.append(("SYS_D01_LASTCARD_HIT", {"formula": f, "dmg": lcd["amount"], "hp": lcd["hp"],
                                                 "pct": round(lc["opp_hp"] / s.ch.opp_max_hp * 100),
                                                 "hp_o": lc["opp_hp"]}))
        if lc["removed"]:
            out.append(("SYS_D01_LASTCARD_REMOVE", {"n": len(lc["removed"])}))
    over = first("debate_over")
    if over and over["reason"] == "second_zero":
        out.append(("SYS_D01_ZERO_WIN", {}))
    icp = first("intercept", ok=True)
    if icp:
        cd = s.ch.cards[icp["card"]]
        if icp["keystone"]:
            out.append(("SYS_D01_KEY_BREAK", {}))
        elif cd.keystone:
            out.append(("SYS_D01_KEY_NORMAL", {}))
        if cd.is_fact:
            out.append(("SYS_D01_DENY_FACT", {}))
    if first("ronpa") and not s2.outcome:
        out.append(("SCR_D01_S07_L005", {}))
    if first("endgame", trigger="zero") and not s2.outcome:
        out.append(("SCR_D01_S07_L006", {}))
    reset = s.player_combo > 0 and (any(e["cause"] in ("exposed", "refuted") for e in pd)
                                    or (lc is not None and not lc.get("dying")))
    return out, reset


def shown(tr, lo: int, hi: int) -> tuple[list[str], list[str]]:
    """(system lines, stamp texts) the screen showed in ticks lo..hi-1."""
    lines = [p["d1debate.sys_line"] for t, p, v, c in tr.ticks if lo <= t < hi and "d1debate.sys_line" in c]
    stamps = [p.get("cutin.stamp_text") for t, p, v, c in tr.ticks if lo <= t < hi and "cutin.stamp_seq" in c]
    return lines, stamps


def check_lines(tr, rounds: list, marks: dict, lang_of, end: int) -> list[str]:
    """Per round: every line the ref calls for is shown with its numbers, no other line under test is shown, and the
    斷 stamp shows exactly when the combo resets. `rounds` = forced() of the recording; lang_of(n) its language."""
    from sherefox_ref.v2.resolve import resolve_round
    bad = []
    for n, (s, pa, oa) in enumerate(rounds, start=1):
        s2, ev = resolve_round(s, pa, oa)
        lang = lang_of(n)
        lo, hi = marks[f"lock{n}"], marks.get(f"lock{n + 1}", end)
        lines, stamps = shown(tr, lo, hi)
        want, reset = ref_lines(s, pa, ev, s2)
        wanted = {render(lang, key, vals) for key, vals in want}
        for key, vals in want:
            txt = render(lang, key, vals)
            if txt not in lines:
                bad.append(f"R{n}: {key} {txt!r} not shown (shown: {lines})")
        for key in sorted(set(SYS_UNDER_TEST) - {k for k, _ in want}):
            pt = pattern(lang, key)
            hit = [x for x in lines if pt.match(x) and x not in wanted]
            if hit:
                bad.append(f"R{n}: {key} shown but not called for: {hit[0]!r}")
        brk = S[lang]["UI_V2_STAMP_COMBO_BREAK"]
        if (brk in stamps) != reset or stamps.count(brk) > 1:
            bad.append(f"R{n}: stamp {brk!r} x{stamps.count(brk)} (combo reset: {reset}; stamps {stamps})")
    return bad


def expected(rounds: list) -> tuple[int, int, str]:
    """(grade, rounds played, outcome) of the ref for the recording's moves."""
    from sherefox_ref.v2.resolve import resolve_round
    s, pa, oa = rounds[-1]
    if oa is None:   # the bot run: the last state is in the steps
        raise ValueError
    s2, _ = resolve_round(s, pa, oa)
    return s2.grade, s2.round - 1, s2.outcome


def check(label: str, rec: str, game: str, ticks: int, marks: dict, want: tuple[int, int, str], lang: str,
          fails: list, route: str | None = None) -> None:
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
    if route:
        bad += check_lines(tr, gd.forced(route), marks, lambda n: lang, marks["over"])
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
                                        ("route B", "d1_routeB", "B", "zh-TW"), ("route C", "d1_routeC", "C", "en"),
                                        ("route D", "d1_routeD", "D", "zh-TW")):
            check(label, rec, f"tests/d1play_harness{route}", ticks[rec], ticks[rec + "_marks"],
                  expected(gd.forced(route)), lang, fails, route)
        bot = gd.CV.play_debate("bot", gd.RT.ROUTES["A"].loadout, gd.BOT_DEBATE_SEED)
        last = bot.steps[-1][3]
        check(f"seeded AI (seed {gd.BOT_SEED})", "d1_bot", ".", ticks["d1_bot"], ticks["d1_bot_marks"],
              (last.grade, last.round - 1, last.outcome), "zh-TW", fails)
        if "--shots" in argv:
            shots(Path(argv[argv.index("--shots") + 1]), ticks)
    finally:
        for route in gd.ROUTES:
            shutil.rmtree(gd.harness_dir(route), ignore_errors=True)
    left = sorted(n for n in set(os.listdir(temp)) - before if n.startswith(("d1shots-", "tmp")))
    if left:
        fails.append("temp")
        print("FAIL temp: left in %TEMP%: " + ", ".join(left))
    print("ok" if not fails else f"FAILED: {', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
