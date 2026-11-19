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
    return cp.parse_events(out), err


# ---- the playback's system lines (E3: every line and number from the round's records; ch §12.0 names the line)

SYS_UNDER_TEST = ("SYS_D01_BOTH_REBUT", "SYS_D01_CUT_EMPTY", "SYS_D01_MISS_WRONG", "SYS_D01_TOPPLE_MISS_FACT",
                  "SYS_D01_TOPPLE_MISS_WRONG", "SYS_D01_FOOLED", "SYS_D01_FOG_REPEAT", "SYS_D01_CLASH",
                  "SYS_D01_LASTCARD_HIT", "SYS_D01_LASTCARD_NOHEAL", "SYS_D01_LASTCARD_REMOVE", "SYS_D01_ZERO_WIN",
                  "SYS_D01_KEY_BREAK", "SYS_D01_KEY_NORMAL", "SYS_D01_DENY_FACT", "SCR_D01_S07_L005",
                  "SCR_D01_S07_L006", "SYS_D01_CUT_SEALED", "SYS_D01_OPP_REBUT_MISS", "SYS_D01_LASTCARD_CORNERED",
                  "SYS_D01_HACHIKU_KEEP",
                  # E7 (design 4ac5faf): the Break / Reverse Break conditions, the chain without 破防 (once)
                  "SYS_D01_CHAIN_READY", "SYS_D01_REV_READY", "SYS_D01_CHAIN_NOBREAK",
                  # E7: the lines only the fuzz reached before (now scripted in check_d1_lines S7, S8, S10, S11)
                  "SYS_D01_LASTSTAND_OK", "SYS_D01_DESPERATE_HIT", "SYS_D01_BLOCKED")


def num(v: float) -> str:
    """A number as the debate screen shows it (v2 demo 4.4): at most two decimals, the chapter's §12 style (the flow's
    round(x * 100) / 100, half up)."""
    import math
    return "%.6g" % (math.floor(v * 100 + 0.5) / 100)


def render(lang: str, key: str, vals: dict) -> str:
    out = S[lang][key].replace("{name}", S[lang]["SPK_D01_CEDRIC"])
    for k, v in vals.items():
        if isinstance(v, list):     # E7 {issues}: string keys joined the way the screen joins them
            v = S[lang]["UI_TAG_SEP"].join(S[lang][x] for x in v)
        if not isinstance(v, str) and k.startswith("hp"):
            v = max(0.0, v)   # a credibility is never shown below 0
        out = out.replace("{" + k + "}", v if isinstance(v, str) else num(v))
    return out


def pattern(lang: str, key: str):
    parts = re.split(r"\{[a-z_]+\}", S[lang][key].replace("{name}", S[lang]["SPK_D01_CEDRIC"]))
    return re.compile("^" + ".*".join(re.escape(x) for x in parts) + "$", re.S)


def ref_lines(s, pa, ev: list, s2, memo: dict | None = None) -> tuple[list[tuple[str, dict]], bool]:
    """The ref's oracle for one round: the system lines under test that ch §12.0 calls for, with their numbers taken
    from the ref's events (state before s, player action pa, events ev, state after s2), and whether the player's
    combo resets to 0 (the 斷 stamp, ruling 7). `memo` carries the once-per-debate lines across rounds."""
    from sherefox_ref.v2 import known as K
    from sherefox_ref.v2 import lines as LN
    from sherefox_ref.v2 import model as M
    from sherefox_ref.v2.model import PA
    memo = {} if memo is None else memo

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
    # E7: the Break by chain: its conditions (n links, the issues in the order the chain reaches them); a keystone
    # Break has KEY_BREAK instead. The Reverse Break: his chain. Her chain long enough without 破防: once per debate
    rp = first("ronpa")
    if rp and rp["via"] == "chain":
        out.append(("SYS_D01_CHAIN_READY", {"n": len(rp["chain"]), "issues": LN.chain_issues(s, rp["chain"])}))
    rv = first("reverse_ronpa")
    if rv:
        out.append(("SYS_D01_REV_READY", {"n": len(rv["chain"]), "issues": LN.chain_issues(s, rv["chain"], True)}))
    if not memo.get("nobreak") and LN.nobreak_now(s, LN.records(ev, s), s2):
        memo["nobreak"] = True
        out.append(("SYS_D01_CHAIN_NOBREAK", {"n": len(s2.player_chain)}))
    ls = first("last_stand", ok=True)     # E7: {node} his card the claim refutes, {hp} her 30% (−10 on a red crack)
    if ls:
        out.append(("SYS_D01_LASTSTAND_OK", {"node": [f"CARD_D01_{ls['target']}"], "hp": ls["hp"]}))
    dy = next((e for e in pd if e["cause"] == "dying"), None)
    if dy:
        out.append(("SYS_D01_DESPERATE_HIT", {"hp": dy["hp"]}))
    if first("blocked"):
        out.append(("SYS_D01_BLOCKED", {}))
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


def ref_cutins(s, ev: list) -> list[tuple[str, str]]:
    """E7: the cut-ins of one round from the ref's records, in order, ("big", id) or ("stamp", word): ch §13 態勢大字與小印
    (the five big words 論破 / 動搖 on 破防 / 破竹 at 3 / 困獸 / 失守, and 逆論破 on a Reverse Break; guilt or anger over
    the threshold has none, design E7) and the text seals (flows §4.12: 截 on a cut that lands, the endgame cut
    included (ch §12.1 R9), 拆, 落空, 交鋒, 援護, 中計, 斷 on the combo's reset). One per record, a big word first."""
    from sherefox_ref.v2 import lines as LN
    out = []
    pat = False
    for r in LN.records(ev, s):
        k = r["k"]
        big = {"ronpa": "CUT_RONPA", "reverseRonpa": "CUT_REVERSE", "broken": "CUT_SHAKEN"}.get(k)
        if k == "hachiku" and r["after"] >= 3 > r["before"]:
            big = "CUT_HACHIKU3"
        elif k == "shisshu" and r["on"]:
            big = "CUT_SHISSHU"
        elif k == "crossed" and r["stat"] == "P":
            big = "CUT_KONJU"
        stamp = None
        if k in ("intercept", "dismantle"):
            stamp = ("CUT" if k == "intercept" else "TOPPLE") if r["ok"] else "WHIFF"
        elif k == "lastCard" and r["cut"]:
            stamp = "CUT"
        elif k == "oAttach" and pat:
            stamp = "CLASH"
        elif k == "guardSaved":
            stamp = "COVER"
        elif k == "oDmg" and r["cause"] == "whiff":
            stamp = "BAITED"
        elif k == "pDmg" and r["cause"] in ("exposed", "refuted", "last_card") and s.player_combo > 0:
            stamp = "COMBO_BREAK"
        if k == "pAttach":
            pat = True
        if big:
            out.append(("big", big))
        elif stamp:
            out.append(("stamp", stamp))
    return out


def shown_cutins(tr, lo: int, hi: int, lang: str) -> list[tuple[str, str]]:
    """The cut-ins ui#cutin played in ticks lo..hi-1, in the form of ref_cutins (a seal by its UI_V2_STAMP_* word)."""
    words = {S[lang][f"UI_V2_STAMP_{w}"]: w for w in ("CUT", "TOPPLE", "WHIFF", "CLASH", "COVER", "BAITED",
                                                       "COMBO_BREAK")}
    out = []
    for t, p, v, c in tr.ticks:
        if not lo <= t < hi:
            continue
        if "cutin.big_seq" in c and p.get("cutin.big_seq", 0) > 0:
            out.append(("big", p.get("cutin.big")))
        if "cutin.stamp_seq" in c and p.get("cutin.stamp_seq", 0) > 0:
            out.append(("stamp", words.get(p.get("cutin.stamp_text"), p.get("cutin.stamp_text"))))
    return out


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
    memo: dict = {}
    for n, (s, pa, oa) in enumerate(rounds, start=1):
        s2, ev = resolve_round(s, pa, oa)
        lang = lang_of(n)
        lo, hi = marks[f"lock{n}"], marks.get(f"lock{n + 1}", end)
        lines, stamps = shown(tr, lo, hi)
        want, reset = ref_lines(s, pa, ev, s2, memo)
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
        cuts, want_cuts = shown_cutins(tr, lo, hi, lang), ref_cutins(s, ev)     # E7: every big word and seal
        if cuts != want_cuts:
            bad.append(f"R{n}: cut-ins {cuts} (ref {want_cuts})")
    return bad


# ---- v2 demo 4.3: the whole playback line by line against ref sherefox_ref.v2.lines (speaker and string key, in
# order: the S07 lines, the BEAT_D01_* interludes, Arthur's hints with the tell), and a hand-written sample of the
# chapter's §12 route texts (so that ref and the game agreeing on a wrong reading is still caught)

# ---- v2 demo E6 (V1): the debate screen on its first visible tick

FIRST_TICK_SKIP = {"line_seq", "float_opp_seq", "float_me_seq", "shatter_seq",          # triggers: any value
                   "pick_act", "pick_ev", "pick_claim", "pick_target", "guard", "lock", "skip", "settings",
                   "hover"}  # outputs
FIRST_TICK_LISTS = ("ochain", "pchain", "ev_list", "claims", "record")


def fresh_ports(lang: str) -> dict:
    """Every d1debate port (FIRST_TICK_SKIP aside) as a new debate shows it before round 1 (S07 L004 plays next):
    round 1, full credibility both sides, empty chains / record / picker, calm gauges, composed, combo and 破竹 0, the
    screen busy (phase 1), nothing of a debate before (tell, tell lines, playback line, floats, plates)."""
    L = S[lang]
    name = L["SPK_D01_CEDRIC"]
    from sherefox_ref.v2.data import load_chapter
    ch = load_chapter()

    def f(key, **kw):
        out = L[key].replace("{name}", name)
        for k, v in kw.items():
            out = out.replace("{" + k + "}", str(v))
        return out
    want = {
        "round_text": f("UI_V2_ROUND", n=1, max=ch.max_rounds), "opp_name": name, "opp_cred": f("UI_V2_CRED_OPP"),
        "ochain_title": f("UI_V2_CHAIN_OPP"),
        "hp_me": float(ch.player_max_hp), "hp_me_max": float(ch.player_max_hp),
        "hp_opp": float(ch.opp_max_hp), "hp_opp_max": float(ch.opp_max_hp),
        "face": 0.0, "band_p": 0.0, "band_g": 0.0, "band_a": 0.0,
        "combo_text": f("UI_V2_COMBO", n=0), "hachiku": 0.0, "hachiku_text": f("UI_STATE_HACHIKU", n=0),
        "guard_down": False, "shisshu": False,
        "ronpa_text": f("UI_V2_RONPA_PROGRESS", n=0, need=ch.ronpa_len, m=0), "ronpa_ready": False,
        "ronpa_ready_text": f("UI_V2_RONPA_READY_ISSUE"), "show_ronpa": True,
        "tell_on": False, "tell_head": f("UI_V2_TELL_HEAD"), "tell_card": "", "tell_partial": False,
        "tell_clear": False, "tell_a": -1.0, "tell_b": -1.0, "tell_star": -1.0, "tell_gesture": "", "dying": False,
        "dying_text": f("UI_V2_DEATH_THROE", n=10),
        "mode": 0.0, "phase": 1.0, "act": 0.0, "can_dismantle": False, "guard_ok": False, "guard_armed": False,
        "guard_left": True, "sel_claim_text": "", "sel_target_text": "", "need_target": False, "can_lock": False,
        "picker_on": False, "hint_who": "", "hint": "", "hint2_who": "", "hint2": "",
        "speech_who": "", "speech": "", "sys_line": "", "float_opp": "", "float_me": "",
        # E8: no preview, crack cost, description or vague-tell line yet; cover 1 left; no cracks on the record
        "preview_text": "", "crack_cost_text": "", "desc_text": "", "tell_possible": "",
        "guard_left_text": f("UI_V2_SUPPORT_LEFT", n=1), "record_cracks": f("UI_V2_RECORD_CRACKS", n=0),
    }
    want.update({k: [] for k in FIRST_TICK_LISTS})
    return want


def first_shown(tr, after: int, ui: str = "d1debate") -> int | None:
    """The first tick at or after `after` with `ui` visible."""
    for t, _, vis, _ in tr.ticks:
        if t >= after and ui in vis:
            return t
    return None


def check_first_tick(at, after: int, lang: str, what: str) -> list[str]:
    """Every d1debate port on the first tick the screen is visible after `after` (at: check_d1_m3.At)."""
    t = first_shown(at.tr, after)
    if t is None:
        return [f"{what}: d1debate never shown after tick {after}"]
    want = fresh_ports(lang)
    bad = []
    names = sorted({k.split(".", 1)[1] for k in at.ports(t) if k.startswith("d1debate.")})
    for p in names:
        if p in FIRST_TICK_SKIP:
            continue
        if p not in want:
            bad.append(f"{what}: port {p} has no expected first-tick value (add it to fresh_ports)")
            continue
        got = at.get(t, f"d1debate.{p}")
        if got != want[p]:
            bad.append(f"{what}, first visible tick {t}: d1debate.{p} = {got!r} (want {want[p]!r})")
    for p in want:
        if p not in names:
            bad.append(f"{what}: port {p} not in the trace")
    return bad


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


# ---- v2 demo E8 (design rulings): what the choosing screen shows besides the picker, from ref and the choice. Shared
# with check_d1_lines and check_d1_fuzz.

E8_ACT_DESC = {2: "UI_V2_REBUT_CUT_DESC", 3: "UI_V2_REBUT_TOPPLE_DESC", 4: "UI_V2_ACT_STALL_DESC"}
E8_TELL = {"attack": "UI_V2_OPP_ASSERT", "force": "UI_V2_OPP_PRESS", "rebut": "UI_V2_OPP_REBUT", "parry": "UI_V2_OPP_DODGE",
           "last": "UI_V2_LAST_CARD"}


def e8_claim(s, claim: str) -> str:
    return f"CATCH:{s.catch_card}" if claim == "CATCH" else claim


def e8_preview(lang: str, s, act: int, claim: str) -> str:
    """preview_text: 議論 with a chosen claim in a normal round shows ref preview.preview (UI_V2_DMG_PREVIEW)."""
    from sherefox_ref.v2.preview import preview
    if act != 1 or not claim or s.endgame or s.player_locked or s.outcome:
        return ""
    v = preview(s, e8_claim(s, claim))
    return "" if v is None else render(lang, "UI_V2_DMG_PREVIEW", {"n": v})


def e8_crack(lang: str, s, act: int, claim: str) -> str:
    """crack_cost_text: the chosen claim (any claim action) has a red crack (UI_V2_CLAIM_CRACK_COST, {n} = 10)."""
    from sherefox_ref.v2 import known as K
    from sherefox_ref.v2.model import CONTRADICTION
    if act not in (1, 2, 3, 5, 7) or not claim or not K.view(s, e8_claim(s, claim)).red_crack:
        return ""
    return render(lang, "UI_V2_CLAIM_CRACK_COST", {"n": CONTRADICTION})


def e8_desc_key(s, act: int, claim: str, armed: bool, hover: str = "") -> str:
    """desc_text's key: the hovered action / cover / claim, else the chosen claim (sophistry, 抓住他的話), else the chosen
    action (2-4; 打迷糊仗 after a 打迷糊仗 last round: UI_V2_ACT_STALL_REPEAT), else cover when armed; "" for none."""
    from sherefox_ref.v2 import known as K
    normal = not (s.endgame or s.player_locked or s.outcome)

    def of_claim(c):
        if not c:
            return ""
        c = e8_claim(s, c)
        if K.is_catch(c):
            return "UI_V2_SEIZE_DESC"
        return "UI_V2_CLAIM_SOPH_DESC" if K.view(s, c).soph else ""
    key = ""
    if normal and hover in ("act2", "act3", "act4"):
        key = E8_ACT_DESC[int(hover[3])]
    elif normal and hover == "guard":
        key = "UI_V2_SUPPORT_DESC"
    elif hover and of_claim(hover):
        key = of_claim(hover)
    elif act in (1, 2, 3, 5, 7) and of_claim(claim):
        key = of_claim(claim)
    elif normal and act in E8_ACT_DESC:
        key = E8_ACT_DESC[act]
    elif normal and armed:
        key = "UI_V2_SUPPORT_DESC"
    if key == "UI_V2_ACT_STALL_DESC" and s.stall_streak > 0:
        key = "UI_V2_ACT_STALL_REPEAT"
    return key


def e8_desc(lang: str, s, act: int, claim: str, armed: bool, hover: str = "") -> str:
    k = e8_desc_key(s, act, claim, armed, hover)
    return S[lang][k] if k else ""


def e8_note(lang: str, s, cid: str) -> str:
    """A claim row's tag: UI_V2_CLAIM_VOID (refuted, greyed), UI_V2_CLAIM_RESTATE (knocked off, may be raised again)."""
    from sherefox_ref.v2 import known as K
    if cid in K.void_rows(s):
        return S[lang]["UI_V2_CLAIM_VOID"]
    return S[lang]["UI_V2_CLAIM_RESTATE"] if K.restate(s, cid) else ""


def e8_tell(lang: str, s, tell) -> str:
    """tell_possible: a vague tell's two actions, the starred one followed by ★ and UI_V2_TELL_LIKELY."""
    from sherefox_ref.v2.model import Clarity
    if tell is None or s.player_locked or s.outcome or tell.clarity == Clarity.CLEAR or len(tell.shown) < 2:
        return ""
    L = S[lang]
    names = [L[E8_TELL[a.value]] + (f" \u2605{L['UI_V2_TELL_LIKELY']}" if tell.star == a else "") for a in tell.shown]
    return L["UI_V2_TELL_POSSIBLE"].replace("{a}", names[0]).replace("{b}", names[1])


def e8_round(lang: str, s) -> dict:
    """The E8 ports that follow the round shown: the cover count and the record's crack count."""
    return {"guard_left_text": render(lang, "UI_V2_SUPPORT_LEFT", {"n": 0 if s.guard_used else 1}),
            "record_cracks": render(lang, "UI_V2_RECORD_CRACKS", {"n": s.cracks})}


def e8_void_evs(s) -> list[str]:
    """The evidence chips the void rows add after the picker's (ref known.void_rows, first appearance)."""
    from sherefox_ref.v2 import known as K
    out: list[str] = []
    have = {e for e, _ in gd.picker(s)}
    for c in K.void_rows(s):
        e = s.ch.claims[c].evidence
        if e not in have and e not in out:
            out.append(e)
    return out


def check_e8(tr, rounds: list, marks: dict, lang_of, seed: int) -> list[str]:
    """Per round of a recording (no pointer moves: nothing hovered), at its `chosen` mark: the preview, the crack cost
    and the description for the choice; the vague tell's line; the cover count and the record's crack count; the
    restated / void tags of the rows the picker shows."""
    bad = []
    tells = tells_for(rounds, seed)
    for n, ((s, pa, oa), tl) in enumerate(zip(rounds, tells), start=1):
        lang = lang_of(n)
        t0 = marks[f"chosen{n}"]
        p = [pp for t, pp, v, c in tr.ticks if t <= t0][-1]
        act = {"argue": 1, "intercept": 2, "dismantle": 3, "stall": 4, "cut": 5, "accept": 6,
               "last_stand": 7}[pa.kind.value]
        claim = pa.claim or ""
        want = {"preview_text": e8_preview(lang, s, act, claim), "crack_cost_text": e8_crack(lang, s, act, claim),
                "desc_text": e8_desc(lang, s, act, claim, bool(pa.guard)), "tell_possible": e8_tell(lang, s, tl)}
        want.update(e8_round(lang, s))
        for k, v in want.items():
            if p.get(f"d1debate.{k}") != v:
                bad.append(f"R{n}: {k} = {p.get(f'd1debate.{k}')!r} (want {v!r})")
        rows = p.get("d1debate.claims") or []
        for row in (json.loads(rows) if isinstance(rows, str) else rows):
            w = e8_note(lang, s, row["id"])
            if row.get("note") != w:
                bad.append(f"R{n}: claim {row['id']} tag {row.get('note')!r} (want {w!r})")
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
    ("A", 8): [(SH, "CLM_D01_11B_LINE"), ("sys", "SYS_D01_CHAIN_READY"), (SH, "STATE_D01_SHF_BREAK"),
               ("sys", "SCR_D01_S07_L005"),
               ("sys", "SCR_D01_S07_L009")],
    ("A", 9): [(SH, "CLM_D01_04B_LINE"), (CE, "CARD_D01_K1_DOWN"), ("sys", "SYS_D01_CUT_WIN")],
    ("B", 1): [(SH, "CLM_D01_P1A_LINE"), ("", "BEAT_D01_P1A_1"), (CE, "REACT_D01_P1A"), (AR, "BEAT_D01_P1A_2"),
               ("sys", "SYS_D01_CLASH"), ("sys", "SYS_D01_PSYCH_NOTE")],          # E5: the psych card's note last
    ("B", 4): [(SH, "CLM_D01_08B_LINE"), ("sys", "SYS_D01_SLIP_NODMG"), (AR, "BEAT_D01_GUILT_1")],
    ("B", 5): [("sys", "SYS_D01_CHAIN_READY"), ("sys", "SCR_D01_S07_L007"), (CE, "SCR_D01_S07_L008"),
               ("sys", "SYS_D01_WIN")],
    # E7 (ch §7, §12.3 R4 / R7): his catch of the contradiction and her hard sell, then the red crack's cost
    ("C", 4): [(AR, "BEAT_D01_REDCRACK_1"), (SH, "CLM_D01_06A_LINE"), (CE, "EXCL_D01_06A_06C_CATCH"),
               (SH, "EXCL_D01_06A_06C_SELL"), ("sys", "SYS_D01_REDCRACK")],
    ("C", 7): [(AR, "BEAT_D01_REDCRACK_1"), (SH, "CLM_D01_07A_LINE"), (CE, "EXCL_D01_06B_07A_CATCH"),
               (SH, "EXCL_D01_06B_07A_SELL"), ("sys", "SYS_D01_REDCRACK")],
    ("C", 5): [(CE, "CARD_D01_P05_STATE"), (CE, "BEAT_D01_LASTCARD_4"), (INS, "BEAT_D01_LASTCARD_2"),
               ("sys", "SYS_D01_LASTCARD_HIT"), (SH, "BEAT_D01_LASTCARD_5"), (AR, "BEAT_D01_LASTCARD_6")],
    ("C", 6): [(AR, "BEAT_D01_09A_1"), (SH, "CLM_D01_09A_LINE"), (IRE, "REACT_D01_09A_3"), (CE, "REACT_D01_09A_1"),
               (MRS, "REACT_D01_09A_2"), ("sys", "SYS_D01_CLASH"), ("sys", "SYS_D01_PRIVATE")],   # E5: after the clash
    ("D", 4): [(SH, "CLM_D01_06B_LINE"), (CE, "REFUTE_D01_06B"), (BRI, "BEAT_D01_REFUTED_1"),
               (MAR, "BEAT_D01_REFUTED_2"), (SH, "BEAT_D01_REFUTED_3"), (AR, "BEAT_D01_REFUTED_4"),
               (SH, "STATE_D01_SHF_BREACHED"), (AR, "STATE_D01_ART_BREACHED")],
    ("D", 7): [("sys", "SYS_D01_REV_READY"), (CE, "BEAT_D01_REVERSE_1"), ("sys", "SYS_D01_REVERSE")],   # E7
    ("D", 8): [(SH, "CLM_D01_11B_LINE"), ("sys", "SYS_D01_LASTSTAND_FAIL"), ("sys", "SCR_D01_S07_L016")],
}
# tell lines the chapter shows that do not depend on the AI's tell: the endgame's (ch §12.1 R9: Arthur's hint, then
# his line; §12.3 R5: the keys beat, then Arthur's hint)
CHAPTER_TELL = {("A", 7): [(CE, "TELL_D01_PUSH_1"), (AR, "TELL_D01_HINT_PUSH")],   # E6: design 1d56459
                ("A", 9): [(AR, "TELL_D01_HINT_LAST"), (CE, "SCR_D01_S07_L010")],
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
    import check_d1_m3 as cm
    # E6 (V1): the first debate of the run on its first visible tick (the dev entry)
    bad += check_first_tick(cm.At(tr, events), 0, lang, "first debate")
    if route:
        from sherefox_ref.v2 import lines as LN
        rounds = gd.forced(route)
        bad += check_lines(tr, rounds, marks, lambda n: lang, marks["end"])
        bad += check_steps(tr, rounds, marks, lang, gd.CV.ui_debate_seed(1), marks["end"])
        bad += check_e8(tr, rounds, marks, lambda n: lang, gd.CV.ui_debate_seed(1))
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


def check_twice(label: str, rec: str, game: str, ticks: int, marks: dict, lang: str, fails: list) -> None:
    """v2 demo E6 (V1): a debate played to its end (a win / a loss), back to the title, the dev entry again: the second
    debate's first visible tick shows a new debate (not the one before), and its round 1 then the engine's round 1."""
    import check_d1_m3 as cm
    events, err = run(rec, game, ticks, lang)
    tr = cp.Trace(events)
    at = cm.At(tr, events)
    bad = check_first_tick(at, 0, lang, "first debate")
    bad += check_first_tick(at, marks["back"], lang, "debate again")
    t = marks["again_r1"]
    want = fresh_ports(lang)
    for p in ("round_text", "hp_me", "hp_opp", "ochain", "pchain", "record", "combo_text", "hachiku"):
        if at.get(t, f"d1debate.{p}") != want[p]:
            bad.append(f"debate again, round 1 shown: d1debate.{p} = {at.get(t, f'd1debate.{p}')!r} (want {want[p]!r})")
    if at.get(t, "d1debate.phase") != 0.0 or not at.get(t, "d1debate.tell_on"):
        bad.append("debate again: round 1 is not offered (phase / tell)")
    noise = [ln for ln in err.split("\n") if ln.strip() and not ln.startswith("render: off")]
    if noise:
        bad.append("stderr: " + " | ".join(noise[:5]))
    if bad:
        fails.append(label)
        print(f"FAIL {label}: " + "; ".join(bad))
    else:
        print(f"PASS {label}: the second debate starts fresh")


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
        for label, rec, route, lang in (("replay after a win", "d1_twiceA", "A", "zh-TW"),
                                        ("replay after a loss [en]", "d1_twiceD", "D", "en")):
            check_twice(label, rec, f"tests/d1play_harness{route}", ticks[rec], ticks[rec + "_marks"], lang, fails)
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
