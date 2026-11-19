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
from tempwatch import TempWatch  # noqa: E402
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
                  "SCR_D01_S07_L006", "SYS_D01_CUT_SEALED", "SYS_D01_OPP_REBUT_MISS", "SYS_D01_LASTCARD_CORNERED",
                  "SYS_D01_HACHIKU_KEEP")


def num(v: float) -> str:
    """A number as the debate screen shows it (v2 demo 4.4): at most two decimals, the chapter's §12 style (the flow's
    round(x * 100) / 100, half up)."""
    import math
    return "%.6g" % (math.floor(v * 100 + 0.5) / 100)


def render(lang: str, key: str, vals: dict) -> str:
    out = S[lang][key].replace("{name}", S[lang]["SPK_D01_CEDRIC"])
    for k, v in vals.items():
        if not isinstance(v, str) and k.startswith("hp"):
            v = max(0.0, v)   # a credibility is never shown below 0
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
        elif icp.get("blocked_by_parry"):
            out.append(("SYS_D01_CUT_SEALED", {}))   # E4: the cut barred by last round's sidestep
        else:
            out.append(("SYS_D01_MISS_WRONG", {"hp": whiff["hp"]}))
    if pa.kind == PA.DISMANTLE and whiff:
        d = first("dismantle")
        soph = K.view(s, pa.claim).soph
        if s.ch.cards[d["card"]].is_fact and not soph:
            out.append(("SYS_D01_TOPPLE_MISS_FACT", {"dmg": whiff["amount"], "hp": whiff["hp"]}))
        else:   # E4: a sophistry on another issue's fact is a wrong-claim miss (−5)
            out.append(("SYS_D01_TOPPLE_MISS_WRONG", {"dmg": whiff["amount"], "hp": whiff["hp"]}))
    if pa.kind == PA.DISMANTLE and first("opp_damage", cause="whiff"):   # E4: he rebutted while she dismantled
        out.append(("SYS_D01_OPP_REBUT_MISS", {"hp": first("opp_damage", cause="whiff")["hp"]}))
    dok = first("dismantle", ok=True)
    if dok and s.ch.cards[dok["card"]].is_fact:   # E4: a sophistry dismantle knocks down a fact
        out.append(("SYS_D01_DENY_FACT", {}))
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
        c0 = s.cracks
        f = num(M.LAST_ZERO_C_DMG) if c0 == 0 else f"{num(M.LAST_PER_CRACK)} × {c0}"
        if s.ch.cards[lc["card"]].kind == "pickup":
            f += f" + {num(M.LAST_PICKED_EXTRA)}"
        if s2.outcome or "heal_void" in kinds:
            out.append(("SYS_D01_LASTCARD_NOHEAL", {"formula": f, "dmg": lcd["amount"], "hp": lcd["hp"]}))
            if not s2.outcome:   # E4: 困獸 voids his recovery, the debate goes on
                out.append(("SYS_D01_LASTCARD_CORNERED", {}))
        else:
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
    # E4: 破竹 held (≥ 1 layer, no layer added, not reset) in a normal round the debate goes on after
    if s.endgame is None and not s.player_locked and not s2.outcome and s.hachiku >= 1 and s2.hachiku == s.hachiku:
        out.append(("SYS_D01_HACHIKU_KEEP", {}))
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


# ---- v2 demo 4.3: the whole playback line by line against ref sherefox_ref.v2.lines (speaker and string key, in
# order: the S07 lines, the BEAT_D01_* interludes, Arthur's hints with the tell), and a hand-written sample of the
# chapter's §12 route texts (so that ref and the game agreeing on a wrong reading is still caught)

def ui_steps(tr, lo: int, hi: int) -> list[tuple[int, tuple[str, str, str]]]:
    """(tick, (name plate, spoken line, system line)) of every playback step shown in ticks lo..hi-1."""
    out = []
    for t, p, v, c in tr.ticks:
        if lo <= t < hi and "d1debate.line_seq" in c:
            st = (p.get("d1debate.speech_who", ""), p.get("d1debate.speech", ""), p.get("d1debate.sys_line", ""))
            if st[1] or st[2]:
                out.append((t, st))
    return out


def matches(lang: str, key: str, text: str) -> bool:
    if not key:
        return text == ""
    return bool(pattern(lang, key).match(text))


def step_ok(lang: str, want, got: tuple[str, str, str]) -> bool:
    who = S[lang][want.who] if want.who else ""
    return (not want.line or got[0] == who) and matches(lang, want.line, got[1]) and matches(lang, want.sys, got[2])


def show(st) -> str:
    return f"{st.who or '-'}:{st.line or '-'}|{st.sys or '-'}"


def tells_for(rounds: list, seed: int) -> list:
    """The AI's tell shown for each round of a forced replay: the engine decides every round on the debate seed
    the UI draws (the harness only overrides the move), as ref policy.decide does on the same seed."""
    from sherefox_ref.v2.policy import RngChooser, decide
    from sherefox_ref.v2.rng import DebateRng
    ch = RngChooser(DebateRng(seed))
    return [decide(s, ch).tell for s, _, _ in rounds]


def tell_shown(tr, t0: int) -> list[tuple[str, str]]:
    """The tell's lines on screen at tick t0 (E5: up to two, hint then hint2), as (name plate, text)."""
    p = [pp for t, pp, v, c in tr.ticks if t <= t0][-1]
    out = [(p.get("d1debate.hint_who", ""), p.get("d1debate.hint", "")),
           (p.get("d1debate.hint2_who", ""), p.get("d1debate.hint2", ""))]
    return [x for x in out if x[1]]


def check_steps(tr, rounds: list, marks: dict, lang, seed: int, end: int) -> list[str]:
    """Every round's playback steps and the tell's lines equal ref lines.round_steps / tell_lines; the opening (L004)
    plays once before round 1. `lang`: the language, or a function of the round (a switch mid-debate)."""
    lang_of = lang if callable(lang) else (lambda n: lang)
    lang = lang_of(1)
    from sherefox_ref.v2 import lines as LN
    from sherefox_ref.v2.resolve import resolve_round
    bad = []
    intro = ui_steps(tr, marks["start"], marks["lock1"])
    if [g for _, g in intro] != [("", "", S[lang][LN.OPENING_SYS])]:
        bad.append(f"opening: {[g for _, g in intro]}")
    memo = LN.Memo()
    tells = tells_for(rounds, seed)
    for n, ((s, pa, oa), tl) in enumerate(zip(rounds, tells), start=1):
        lang = lang_of(n)
        s2, ev = resolve_round(s, pa, oa)
        hint = LN.tell_lines(s, tl, memo)
        want = LN.round_steps(s, pa, oa, ev, s2, memo)
        lo, hi = marks[f"lock{n}"], marks.get(f"lock{n + 1}", end)
        got = ui_steps(tr, lo, hi)
        if len(got) != len(want) or not all(step_ok(lang, w, g) for w, (_, g) in zip(want, got)):
            k = next((i for i, (w, (_, g)) in enumerate(zip(want, got)) if not step_ok(lang, w, g)),
                     min(len(want), len(got)))
            bad.append(f"R{n}: step {k + 1} of {len(want)} (shown {len(got)}): want "
                       f"{[show(w) for w in want[k:k + 2]]}, shown {[g for _, g in got[k:k + 2]]}")
        got_t = tell_shown(tr, marks[f"chosen{n}"])
        if got_t != [(S[lang][w], S[lang][k]) for w, k in hint]:
            bad.append(f"R{n}: tell lines {got_t!r} (want {hint})")
    return bad


def check_vn(tr, marks: dict, lang: str, lines: tuple, prefix: str) -> list[str]:
    """S07's lines on the vn (before the debate: pre_*, after it: post_*): each line with its name plate."""
    rows = {r["id"]: r for r in json.loads((ROOT / "data" / "script.json").read_text(encoding="utf-8"))}
    bad = []
    for lid in lines:
        t0 = marks[f"{prefix}_{lid}"]
        p = [pp for t, pp, v, c in tr.ticks if t <= t0][-1]
        vis = [v for t, pp, v, c in tr.ticks if t <= t0][-1]
        spk = S[lang][rows[lid]["speaker"]] if rows[lid]["speaker"] and rows[lid]["focus"] else ""
        if (p.get("vn.line"), p.get("vn.speaker"), "vn" in vis) != (S[lang][lid], spk, True):
            bad.append(f"{lid}: vn {p.get('vn.line')!r} / {p.get('vn.speaker')!r} (vn shown: {'vn' in vis})")
    return bad


SH, CE, AR = "SPK_SHEREFOX", "SPK_D01_CEDRIC", "SPK_ARTHUR"
MRS, BRI, MAR, IRE, INS = "SPK_MRS_HYDE", "SPK_BRIGGS", "SPK_MARTHA", "SPK_IRENE", "SPK_INSPECTOR_BASKERVILLE"
# (route, round) -> lines the chapter's §12 text shows, in its order, as (speaker or "sys", key): each must be shown
# in this order during the round (other lines may come between). Read off the chapter by hand, not from ref.
CHAPTER_SAMPLE = {
    # E5: 破竹 0 -> 1 (the table's 破竹 column) and the debate's first time: Sherefox's minute, then Arthur's line
    ("A", 1): [(SH, "CLM_D01_11A_LINE"), ("sys", "SYS_D01_CUT_OK"), (SH, "STATE_D01_SHF_HACHIKU_1"),
               (AR, "STATE_D01_ART_HACHIKU")],
    ("A", 3): [(SH, "CLM_D01_06A_LINE"), (CE, "BEAT_D01_CLASH_1"), (SH, "BEAT_D01_CLASH_2"), ("sys", "SYS_D01_CLASH"),
               ("sys", "SYS_D01_HACHIKU_KEEP")],
    ("A", 4): [(SH, "CLM_D01_01A_LINE"), ("sys", "SYS_D01_CUT_OK"), (SH, "STATE_D01_SHF_HACHIKU_3")],
    ("A", 7): [(SH, "CLM_D01_07A_LINE"), (MAR, "BEAT_D01_07A_1"), (BRI, "BEAT_D01_07A_2"), (CE, "CARD_D01_L4_DOWN")],
    ("A", 8): [(SH, "CLM_D01_11B_LINE"), (SH, "STATE_D01_SHF_BREAK"), ("sys", "SCR_D01_S07_L005"),
               ("sys", "SCR_D01_S07_L009")],
    ("A", 9): [(SH, "CLM_D01_04B_LINE"), (CE, "CARD_D01_K1_DOWN"), ("sys", "SYS_D01_CUT_WIN")],
    ("B", 1): [(SH, "CLM_D01_P1A_LINE"), ("", "BEAT_D01_P1A_1"), (CE, "REACT_D01_P1A"), (AR, "BEAT_D01_P1A_2"),
               ("sys", "SYS_D01_CLASH"), ("sys", "SYS_D01_PSYCH_NOTE")],          # E5: the psych card's note last
    ("B", 4): [(SH, "CLM_D01_08B_LINE"), ("sys", "SYS_D01_SLIP_NODMG"), (AR, "BEAT_D01_GUILT_1")],
    ("B", 5): [("sys", "SCR_D01_S07_L007"), (CE, "SCR_D01_S07_L008"), ("sys", "SYS_D01_WIN")],
    ("C", 5): [(CE, "CARD_D01_P05_STATE"), (CE, "BEAT_D01_LASTCARD_4"), (INS, "BEAT_D01_LASTCARD_2"),
               ("sys", "SYS_D01_LASTCARD_HIT"), (SH, "BEAT_D01_LASTCARD_5"), (AR, "BEAT_D01_LASTCARD_6")],
    ("C", 6): [(AR, "BEAT_D01_09A_1"), (SH, "CLM_D01_09A_LINE"), (IRE, "REACT_D01_09A_3"), (CE, "REACT_D01_09A_1"),
               (MRS, "REACT_D01_09A_2"), ("sys", "SYS_D01_CLASH"), ("sys", "SYS_D01_PRIVATE")],   # E5: after the clash
    ("D", 4): [(SH, "CLM_D01_06B_LINE"), (CE, "REFUTE_D01_06B"), (BRI, "BEAT_D01_REFUTED_1"),
               (MAR, "BEAT_D01_REFUTED_2"), (SH, "BEAT_D01_REFUTED_3"), (AR, "BEAT_D01_REFUTED_4"),
               (SH, "STATE_D01_SHF_BREACHED"), (AR, "STATE_D01_ART_BREACHED")],
    ("D", 8): [(SH, "CLM_D01_11B_LINE"), ("sys", "SYS_D01_LASTSTAND_FAIL"), ("sys", "SCR_D01_S07_L016")],
}
# tell lines the chapter shows that do not depend on the AI's tell: the endgame's (ch §12.1 R9: Arthur's hint, then
# his line; §12.3 R5: the keys beat, then Arthur's hint)
CHAPTER_TELL = {("A", 9): [(AR, "TELL_D01_HINT_LAST"), (CE, "SCR_D01_S07_L010")],
                ("C", 5): [(AR, "BEAT_D01_LASTCARD_1"), (AR, "TELL_D01_HINT_LAST")]}


def check_sample(tr, route: str, marks: dict, lang: str, end: int) -> list[str]:
    bad = []
    for (rt, n), want in CHAPTER_SAMPLE.items():
        if rt != route:
            continue
        got = [g for _, g in ui_steps(tr, marks[f"lock{n}"], marks.get(f"lock{n + 1}", end))]
        i = 0
        for who, key in want:
            found = False
            while i < len(got):     # a step shows a spoken line and a system line: both may match in turn
                g = got[i]
                if (who == "sys" and matches(lang, key, g[2])) or (
                        who != "sys" and g[0] == (S[lang][who] if who else "") and matches(lang, key, g[1])):
                    found = True
                    if who == "sys":
                        i += 1
                    break
                i += 1
            if not found:
                bad.append(f"sample {route}{n}: {who}:{key} not shown in the chapter's order")
                break
    for (rt, n), want in CHAPTER_TELL.items():
        if rt == route:
            got = tell_shown(tr, marks[f"chosen{n}"])
            if got != [(S[lang][w], S[lang][k]) for w, k in want]:
                bad.append(f"sample {route}{n}: tell lines {got!r} (want {want})")
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
    exp = {"d1result.grade_text": S[lang][f"UI_V2_GRADE_{grade}"],
           "d1result.rounds_text": S[lang]["UI_V2_RESULT_ROUNDS"].replace("{n}", str(nrounds)),
           "d1result.win": 1.0 if outcome == "win" else 0.0}
    bad = [f"{k}={at_over.get(k)!r} (want {v!r})" for k, v in exp.items() if at_over.get(k) != v]
    rounds_seen = {p.get("d1debate.round_text") for t, p, v, c in tr.ticks}
    last_round = S[lang]["UI_V2_ROUND"].replace("{n}", str(nrounds)).replace("{max}", "20")
    if last_round not in rounds_seen:
        bad.append(f"round {nrounds} was never shown ({last_round!r})")
    if "title" not in end_vis or end_vis & {"vn", "paper", "d1debate", "d1result", "d1end"}:
        bad.append(f"after back to title the visible screens are {sorted(end_vis)}")
    if route:
        from sherefox_ref.v2 import lines as LN
        rounds = gd.forced(route)
        bad += check_lines(tr, rounds, marks, lambda n: lang, marks["end"])
        bad += check_steps(tr, rounds, marks, lang, gd.CV.ui_debate_seed(1), marks["end"])
        bad += check_sample(tr, route, marks, lang, marks["end"])
        bad += check_vn(tr, marks, lang, LN.PRE_LINES, "pre")
        bad += check_vn(tr, marks, lang, LN.outro(outcome), "post")
    noise = [ln for ln in err.split("\n") if ln.strip() and not ln.startswith("render: off")]
    if noise:
        bad.append("stderr: " + " | ".join(noise[:5]))
    if bad:
        fails.append(label)
        print(f"FAIL {label}: " + "; ".join(bad))
    else:
        print(f"PASS {label}: grade {grade} ({exp['d1result.grade_text']}), {nrounds} rounds, {outcome}")


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
              "endgame": mA["chosen9"], "result_win": mA["over"]}),
            ("d1_routeD", "tests/d1play_harnessD", ticks["d1_routeD"],
             {"laststand": mD["chosen8"], "result_loss": mD["over"]})]
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
    tw = TempWatch().__enter__()   # tests/tempwatch.py: only what this run creates counts as a leak
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
    tw.__exit__(None, None, None)
    left = tw.leaks
    if left:
        fails.append("temp")
        print("FAIL temp: left behind: " + ", ".join(left))
    print("ok" if not fails else f"FAILED: {', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
