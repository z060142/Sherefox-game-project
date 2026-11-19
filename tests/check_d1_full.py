# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Replay the v2 demo D01 full-chapter recordings (tests/gen_d1_full.py) headless: four runs, routes A-D of ch §12,
each from the title's v2 entry through the story, the warm-up, the real investigation and carry screen, the debate
with the route's pinned moves, the ending (S07's lines after it, S08, the result screen, S09, S10, S11) and back to
the title, then the chapter started again (v2 demo 4.4; docs/flows.md §4.15, tests/README.md). Route A also in en.

Asserted against the reference model (ref sherefox_ref.v2.epilogue on the route's final state) and, separately,
against a hand-written expectation per route taken from the chapter (CHAPTER: §2 S08-S10 and §12.1-§12.4's
結算 tables), so a reading that ref and the game share is still checked against the chapter text.

Usage (from the project root):
    uv run tests/check_d1_full.py [--shots DIR]    --shots also writes review screenshots (zh-TW and en) to DIR
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(ROOT / "tools"))
import check_d1_m3 as cm  # noqa: E402
import check_d1_play as cd  # noqa: E402
import check_playthrough as cp  # noqa: E402
import gen_d1_full as gf  # noqa: E402
import gen_d1_play as gd  # noqa: E402
from sherefox_ref.v2.epilogue import epilogue  # noqa: E402
from sherefox_ref.v2.results import compute  # noqa: E402
from tempwatch import TempWatch  # noqa: E402
from xt_cli import EXE, XTFRAME, compile_game  # noqa: E402

S = cd.S


def s08(*n):
    return [f"SCR_D01_S08_L{i:03d}" for i in n]


def s09(*n):
    return [f"SCR_D01_S09_L{i:03d}" for i in n]


def s10(*n):
    return [f"SCR_D01_S10_L{i:03d}" for i in n]


# Hand-written from the chapter (§2 S08-S10 conditions, §12.x 結算 tables): grade, rounds, the S08 lines, the paper
# version and its addenda, Arthur's notes and their addenda, the reputation items (names) and the favour changes.
CHAPTER = {
    # §12.1: grade 1, 9 rounds, truth 100 -> full notes (L001-L003), decent paper; 07A said (R7) -> L004-L005
    "A": dict(grade=1, rounds=9, s08=s08(1, 4, 5, 7, 8), paper="DECENT", paper_add=[], notes=s10(1, 2, 3),
              rep=["grade_1"], fav={}),
    # §12.2: grade 1, 5 rounds, truth 85 -> full + L007 (no 07A/07B), decent; 結算台詞 L009-L010 (the board)
    "B": dict(grade=1, rounds=5, s08=s08(1, 6, 7, 8, 9, 10), paper="DECENT", paper_add=[], notes=s10(1, 2, 3, 7),
              rep=["grade_1", "psych_card"], fav={}),
    # §12.3: grade 3, 10 rounds, truth 50 -> half (L004-L005), normal + L007 (Irene) + L008; S08 L001-L003, L004-L005
    "C": dict(grade=3, rounds=10, s08=s08(1, 2, 3, 4, 5, 7, 8), paper="NORMAL", paper_add=s09(7, 8),
              notes=s10(4, 5), rep=["grade_3", "cracks", "private", "denials"], fav={"mrs_hyde": -1}),
    # §12.4: grade 5 (a loss), 8 rounds, truth 60 -> half + L007, L009; ugly paper; S08 L011-L012; inspector −1
    "D": dict(grade=5, rounds=8, s08=s08(11, 12), paper="UGLY", paper_add=[], notes=s10(4, 5, 7, 9),
              rep=["grade_5"], fav={"inspector": -1}),
}
REP_KEY = {"grade_1": "UI_V2_REP_CLEAN", "grade_2": "UI_V2_REP_HELD", "grade_3": "UI_V2_REP_COUNTERED",
           "grade_4": "UI_V2_REP_GRIND", "grade_5": "UI_V2_REP_LOSS", "cracks": "UI_V2_REP_CRACKS",
           "private": "UI_V2_REP_PRIVATE", "psych_card": "UI_V2_REP_PSYCH", "stalls": "UI_V2_REP_STALL",
           "denials": "UI_V2_REP_DENY"}
FAV_NAME = {"inspector": "SPK_INSPECTOR_BASKERVILLE", "mrs_hyde": "SPK_MRS_HYDE"}
RUNS = (("A", "zh-TW"), ("A", "en"), ("B", "zh-TW"), ("C", "zh-TW"), ("D", "zh-TW"))


def r2(v: float) -> float:
    return math.floor(v * 100 + 0.5) / 100


def check(route: str, lang: str, info: dict, fails: list, v1: bool = False) -> None:
    L = S[lang]
    marks = info["marks"]
    events, err = cd.run(f"d1_full{route}{'_v1' if v1 else ''}", f"tests/d1full_harness{route}", info["ticks"], lang)
    tr = cp.Trace(events)
    at = cm.At(tr, events)
    at.marks = marks
    bad: list[str] = []

    def eq(what, got, want):
        if got != want:
            bad.append(f"{what}: {got!r} (want {want!r})")

    bad += check_settled(at)
    if v1:   # v1's Ch.1-3 were played to the end card, dismissed: the title is the only main screen
        eq("v1 first: on the title", sorted(at.vis(marks["v1_done"]) & set(cp.MAIN_SCREENS)), ["title"])
    rounds = gd.forced(route)
    final = gd.final_state(rounds)
    e, res = epilogue(final), compute(final)
    ch = CHAPTER[route]
    # the chapter's hand-written ending equals ref's (so both readings agree before the game is compared)
    eq("ref vs chapter: S08", list(e.s08), ch["s08"])
    eq("ref vs chapter: paper", e.paper.upper(), ch["paper"])
    eq("ref vs chapter: paper addenda", list(e.paper_addenda), ch["paper_add"])
    eq("ref vs chapter: notes", list(e.s10), ch["notes"])
    eq("ref vs chapter: grade / rounds", (e.grade, e.rounds), (ch["grade"], ch["rounds"]))
    eq("ref vs chapter: reputation items", [n for n, _, _ in e.reputation], ch["rep"])
    eq("ref vs chapter: favour", dict(e.favour), ch["fav"])

    # the investigation took what the route carried; the debate reached the route's end (the loadout was right)
    eq("investigation shown", "d1inv" in at.vis(marks["inv"] + 20), True)
    eq("carry screen shown", "d1carry" in at.vis(marks["carry"]), True)
    # E6 (V5): the evidence list button counts the new evidence and psych cards, not the notes on people
    found = {x for s in gf.spots_for(route) for x in s["ev"].split(",") if x}
    eq("list button count (evidence and psych cards only)", at.get(marks["before_book"], "d1inv.book_new"),
       float(len(found)))
    # E6 (V1): the chapter's first debate on its first visible tick
    bad += cd.check_first_tick(at, marks["go"], lang, "first debate")
    # S08 on the vn, in ref's order
    for lid in e.s08:
        t = marks[f"s08_{lid}"]
        eq(f"{lid} on the vn", ("vn" in at.vis(t), at.get(t, "vn.line")), (True, L[lid]))
    # the result screen: grade, rounds, outcome; the reputation items (label + direction, no number); the favour
    t = marks["over"]
    eq("result screen shown", "d1result" in at.vis(t), True)
    eq("result grade", at.get(t, "d1result.grade_text"), L[f"UI_V2_GRADE_{e.grade}"])
    eq("result rounds", at.get(t, "d1result.rounds_text"), L["UI_V2_RESULT_ROUNDS"].replace("{n}", str(e.rounds)))
    eq("result win", at.get(t, "d1result.win"), 1.0 if res.outcome == "win" else 0.0)
    want_rep = [{"label": L[REP_KEY[n]].replace("{n}", str(c)), "up": 1 if d > 0 else 0} for n, d, c in e.reputation]
    eq("result reputation rows", at.get(t, "d1result.rep"), want_rep)
    want_fav = [{"text": L["UI_V2_FAVOR_LINE"].replace("{name}", L[FAV_NAME[w]])
                 .replace("{delta}", ("+" if d > 0 else "−") + str(abs(d)))} for w, d in e.favour]
    if want_fav:
        eq("result favour rows", at.get(t, "d1result.fav"), want_fav)
    eq("result favour shown", at.get(t, "d1result.fav_on"), bool(want_fav))
    # hidden values: the reputation total / result and the truth score never reach the screen
    shown = json.dumps({k: v for k, v in at.ports(t).items() if k.startswith("d1result.")}, ensure_ascii=False)
    shown += json.dumps([at.get(t, "d1result.rep"), at.get(t, "d1result.fav")], ensure_ascii=False)
    for secret in {f"{res.truth}%", f"{res.truth}％", str(res.reputation_after), f"{res.reputation_delta:+d}"}:
        if secret in shown:
            bad.append(f"result screen shows a hidden value {secret!r}")
    # S09: the version's headline and lead, then the addenda; no picture
    t = marks["s09"]
    eq("S09 paper shown", "paper" in at.vis(t), True)
    eq("S09 headline", at.get(t, "paper.headline"), L[f"HEAD_D01_CLOSE_{e.paper.upper()}"])
    sep = " " if lang == "en" else ""   # the addenda run on after the lead (a space in English)
    body = "".join([L[e.paper_lines[1]]] + [sep + L[x] for x in e.paper_addenda])
    eq("S09 body", at.get(t, "paper.body"), body)
    eq("S09 no picture", at.get(t, "paper.picture"), "")
    # S10 on the vn
    for lid in e.s10:
        t = marks[f"s10_{lid}"]
        eq(f"{lid} on the vn", ("vn" in at.vis(t), at.get(t, "vn.line")), (True, L[lid]))
    # S11, back to title
    eq("S11 shown", "d1end" in at.vis(marks["s11"]), True)
    vis = at.vis(marks["back"])
    eq("back to title", ("title" in vis, sorted(vis & {"vn", "paper", "d1debate", "d1result", "d1end"})), (True, []))
    # credibility on the debate screen: two decimals at most, never below 0; 1 after a Break (ref: locked at 1)
    for tt, p, v, c in tr.ticks:
        for port in ("d1debate.hp_opp", "d1debate.hp_me"):   # (ports are float32: 103.49 reads 103.4899978)
            x = p.get(port)
            if isinstance(x, float) and (x < 0 or abs(x - r2(x)) > 1e-3):
                bad.append(f"{port} at t{tt} = {x!r} (two decimals, >= 0)")
                break
    if route in ("A", "B"):   # the Break round's playback ends with his credibility at 1
        eq("credibility after the Break", at.get(marks["end"], "d1debate.hp_opp"), 1.0)
    # the chapter again from the title: a fresh start
    t = marks["again_paper"]
    eq("again: S01 paper", ("paper" in at.vis(t), at.get(t, "paper.headline")), (True, L["HEAD_D01"]))
    t = marks["again_inv_shown"]
    eq("again: investigation shown", "d1inv" in at.vis(t), True)
    eq("again: appraisals reset", at.get(t, "d1inv.appr_text"), L["UI_V2_APPRAISE_LEFT"].replace("{n}", "2"))
    eq("again: nothing found yet", at.get(t, "d1inv.book_new"), 0.0)
    locs = at.get(t, "d1inv.locs") or []
    eq("again: no place done", [x.get("done") for x in locs], [False] * 6)
    if route == "D":   # E6: after the loss, the chapter played again up to its debate (gen_d1_full.again_debate)
        bad += check_again(at, lang)
    elif route == "B" and not v1:   # E6 (V3): again, everything found carried (HS25, HS06, HS19 never looked at)
        t = marks["again_confirm"]
        eq("again: nothing found left, confirm -> L010 (he could pick up E05 / E06)",
           (at.get(t, "d1carry.phase"), at.get(t, "d1carry.say1")), (2.0, L["SCR_D01_S06_L010"]))
    noise = [ln for ln in err.split("\n") if ln.strip() and not ln.startswith("render: off")]
    if noise:
        bad.append("stderr: " + " | ".join(noise[:5]))
    label = f"route {route}{' after v1 Ch.1-3' if v1 else ''} [{lang}]"
    if bad:
        fails.append(label)
        print(f"FAIL {label}: " + "; ".join(bad[:25]))
    else:
        print(f"PASS {label}: grade {e.grade}, {e.rounds} rounds; S08 {len(e.s08)} lines; paper {e.paper}"
              f"{' + ' + ', '.join(x[-4:] for x in e.paper_addenda) if e.paper_addenda else ''}; notes {e.notes}"
              f"{' + ' + ', '.join(x[-4:] for x in e.note_addenda) if e.note_addenda else ''}; back to title; "
              f"clean restart")


SETTLED_UIS = ("d1warm", "d1inv", "d1book", "d1carry", "d1result", "d1end")
SETTLE = 5   # ticks: no input reaches a screen this soon after it is shown (the recordings wait 10 or more)


def list_ports(ui: str) -> list[str]:
    """The list ports of a board (ui/boards/project/<Ui>.dc.html data-xt-port)."""
    import html
    import re
    board = next(p for p in (ROOT / "ui" / "boards" / "project").glob("*.dc.html") if p.name.lower() == f"{ui}.dc.html")
    ports = html.unescape(re.search(r"data-xt-port='([^']*)'", board.read_text(encoding="utf-8")).group(1))
    return re.findall(r"(?:^|;)\s*(\w+):list<", ports)


def check_settled(at) -> list[str]:
    """v2 demo E6 (the screen audit after V1): every time a D01 screen other than the debate (which has its own check)
    becomes visible, its first visible tick already shows what it shows SETTLE ticks later (no board default, nothing
    of the chapter played before), and each of its list ports has been written."""
    bad, prev = [], set()
    for t, p, vis, _ in at.tr.ticks:
        for ui in sorted((vis - prev) & set(SETTLED_UIS)):
            for lp in list_ports(ui):
                if at.get(t, f"{ui}.{lp}") is None:
                    bad.append(f"{ui} shown at t{t}: list {lp} never written (the board's default)")
            for k in sorted(k for k in p if k.startswith(ui + ".")):
                a, b = at.get(t, k), at.get(t + SETTLE, k)
                if a != b:
                    bad.append(f"{ui} shown at t{t}: {k} = {str(a)[:50]!r}, {SETTLE} ticks later {str(b)[:50]!r}")
        prev = vis
    return bad


def check_again(at, lang: str) -> list[str]:
    """Route D's chapter again (a replay after a loss): the carry screen with HS25 (E05, E06) and HS06 (E12) never
    looked at, the nine evidence found carried and the talking board left (V3: the confirm list names only what was
    found; L010 plays because he could still pick up E05 / E06); the debate on its first visible tick (V1) and its
    round 1."""
    L = S[lang]
    marks = at.marks
    bad = []
    t = marks["again_confirm"]
    want = L["SCR_D01_S06_L009"].replace("{list}", L["C_D01_P1_NAME"])
    got = (at.get(t, "d1carry.phase"), at.get(t, "d1carry.confirm_text"))
    if got != (1.0, want):
        bad.append(f"again: confirm (phase, list) {got!r} (want {(1.0, want)!r})")
    t = marks["again_l010"]
    got = (at.get(t, "d1carry.phase"), at.get(t, "d1carry.say1"))
    if got != (2.0, L["SCR_D01_S06_L010"]):
        bad.append(f"again: after yes (phase, line) {got!r} (want L010: he could pick up what was never found)")
    bad += cd.check_first_tick(at, marks["again_go"], lang, "debate again")
    t = marks["again_r1"]
    want = cd.fresh_ports(lang)
    for p in ("round_text", "hp_me", "hp_opp", "ochain", "pchain", "record", "combo_text", "hachiku"):
        if at.get(t, f"d1debate.{p}") != want[p]:
            bad.append(f"again, round 1: d1debate.{p} = {at.get(t, f'd1debate.{p}')!r} (want {want[p]!r})")
    if at.get(t, "d1debate.phase") != 0.0:
        bad.append("again: round 1 is not offered")
    return bad


def shots(out: Path, ticks: dict) -> None:
    """Review screenshots: the S01 paper with the engraving, the result screen (grade 1 win A, grade 3 win C, loss D),
    each S09 version, an S10 page, S11, the warm-up's point (zh-TW, en)."""
    out.mkdir(parents=True, exist_ok=True)
    mA, mC, mD = (ticks[r]["marks"] for r in "ACD")
    point = next(t for scr, lid, t in ticks["A"]["shown"] if lid == "SCR_D01_S04_L002")
    plan = {
        "A": {"s01_paper": mA["paper"] + 10, "warm_point": point + 10, "result_grade1_win": mA["over"],
              "s09_decent": mA["s09"], "s10_full": mA["s10_SCR_D01_S10_L001"] + 8, "s11": mA["s11"]},
        "C": {"result_grade3_win": mC["over"], "s09_normal": mC["s09"]},
        "D": {"result_loss": mD["over"], "s09_ugly": mD["s09"], "s10_half_loss": mD["s10_SCR_D01_S10_L009"] + 8},
    }
    for route, named in plan.items():
        named = {k: v for k, v in named.items() if v is not None}
        for lang in ("zh-TW", "en"):
            import tempfile
            tmp = Path(tempfile.mkdtemp(prefix="d1fullshots-"))
            try:
                at_ = ",".join(str(t) for t in sorted(set(named.values())))
                p = subprocess.run([str(EXE), "shot", "--game", f"tests/d1full_harness{route}", "--replay",
                                    str(TESTS / f"d1_full{route}.atrec"), "--at", at_, "--out", str(tmp), "--lang", lang],
                                   capture_output=True, cwd=ROOT, env=dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME))
                if p.returncode != 0:
                    raise SystemExit(f"shot {route} failed: {p.stderr.decode('utf-8', 'replace')}")
                for name, t in named.items():
                    shutil.copyfile(tmp / f"shot-{t:06d}.png", out / f"{name}_{lang}.png")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    print(f"shots: {out}")


def main() -> int:
    argv = sys.argv[1:]
    t0 = time.perf_counter()
    compile_game()
    tw = TempWatch().__enter__()   # tests/tempwatch.py: only what this run creates counts as a leak
    fails: list[str] = []
    try:
        if subprocess.run([sys.executable, str(TESTS / "gen_d1_full.py")], cwd=ROOT).returncode != 0:
            raise SystemExit("gen_d1_full failed")
        ticks = json.loads((TESTS / "d1_full_ticks.json").read_text(encoding="utf-8"))
        for route, lang in RUNS:
            check(route, lang, ticks[route], fails)
        # E6: v1's three chapters first in the same run, then the chapter (route A)
        check("A", "zh-TW", ticks["A_v1"], fails, v1=True)
        if "--shots" in argv:
            shots(Path(argv[argv.index("--shots") + 1]), ticks)
    finally:
        for route in gf.ROUTES:
            shutil.rmtree(gf.harness_dir(route), ignore_errors=True)
    tw.__exit__(None, None, None)
    if tw.leaks:
        fails.append("temp")
        print("FAIL temp: left behind: " + ", ".join(tw.leaks))
    print(f"{time.perf_counter() - t0:.0f} s")
    print("ok" if not fails else f"FAILED: {', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
