# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Replay the v2 demo D01 story recordings (tests/gen_d1_story.py) headless and check M4a (docs/flows.md §4.14,
docs/ui-contracts.md paper, vn, d1warm): from the title's v2 entry, the S01 paper (headline, dateline, lead, one
page), every line of S02 and S03 in the order of script_d01.csv with its name plate, the vn being the only main
screen; then the S04 warm-up three ways (clean pass, a pass with two mistakes, a failure with three), each line in
the reference model's order (ref sherefox_ref.v2.warmup) with its speaker, the point on top and the mistakes count,
the observations clickable exactly while a point waits; world.d1Warmup (pass_clean / pass / fail) and the
investigation's appraisal count (2 / 2 / 1) afterwards. Runs in zh-TW and en.

Usage (from the project root):
    uv run tests/check_d1_story.py [--shots DIR]   --shots also writes the review screenshots (zh-TW, en) to DIR
"""

from __future__ import annotations

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
import check_d1_play as cd  # noqa: E402
import check_playthrough as cp  # noqa: E402
import gen_d1_story as gs  # noqa: E402
from tempwatch import TempWatch  # noqa: E402
from xt_cli import EXE, XTFRAME, compile_game  # noqa: E402

S = cd.S
SCRIPT = {r["id"]: r for r in json.loads((ROOT / "data" / "script.json").read_text(encoding="utf-8"))}
PAPER = next(p for p in json.loads((ROOT / "data" / "papers.json").read_text(encoding="utf-8")) if p["id"] == "D01_OPEN")
MAIN = {"title", "paper", "vn", "investigate", "board", "debate", "result", "d1debate", "d1inv", "d1carry", "d1warm"}
WANT_APPR = {"pass_clean": 2, "pass": 2, "fail": 1}


def at(tr: cp.Trace, t: int) -> tuple[dict, set]:
    cur, vis = {}, set()
    for tt, p, v, c in tr.ticks:
        if tt > t:
            break
        cur, vis = p, v
    return cur, vis


def final_warmup(rec: str, ticks: int) -> str:
    """world.d1Warmup at the end of a replay (`xtatrium trace` prints its changes; initial "pass")."""
    p = subprocess.run([str(EXE), "trace", "--game", ".", "--replay", str(TESTS / f"{rec}.atrec"), "--ticks",
                        str(ticks)], capture_output=True, cwd=ROOT, env=dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME))
    if p.returncode != 0:
        raise SystemExit(f"trace failed: {p.stderr.decode('utf-8', 'replace')}")
    val = "pass"
    for ln in p.stdout.decode("utf-8", "replace").splitlines():
        m = re.match(r'^t\d+ world\.d1Warmup .* -> (".*")$', ln)
        if m:
            val = json.loads(m.group(1))   # `trace` quotes string values JSON-style
    return val


def check(name: str, run: dict, lang: str, fails: list) -> None:
    L = S[lang]
    rec = f"d1_story_{name}"
    events, err = cd.run(rec, ".", run["ticks"], lang)
    tr = cp.Trace(events)
    bad: list[str] = []

    def eq(what: str, got, want) -> None:
        if got != want:
            bad.append(f"{what}: {got!r} (want {want!r})")

    mis = 0
    for screen, lid, t in run["shown"]:
        p, vis = at(tr, t)
        eq(f"t={t} {lid} screens", sorted(vis & MAIN), [screen])
        if screen == "paper":
            eq("paper headline", p.get("paper.headline"), L[PAPER["headlineKey"]])
            eq("paper dateline", p.get("paper.dateline"), L[PAPER["datelineKey"]])
            eq("paper lead", p.get("paper.body"), L[PAPER["bodyKey"]])
            eq("paper page", p.get("paper.page"), 1.0)
            eq("paper strip, engraving", (p.get("paper.result_head"), p.get("paper.picture")), ("", "d01_wake"))   # 4.4
            continue
        row = SCRIPT[lid]
        spk = L[row["speaker"]] if row["speaker"] else ""
        if screen == "vn":
            eq(f"{lid} line", p.get("vn.line"), L[lid])
            eq(f"{lid} name plate", p.get("vn.speaker"), spk if row["focus"] else "")
            eq(f"{lid} staging", [p.get(f"vn.{k}") for k in ("bg", "slot_l", "slot_c", "slot_r")],
               [row["bg"], row["slot_l"], row["slot_c"], row["slot_r"]])
            eq(f"{lid} chapter tab", p.get("vn.chapter_title"), L["CHAP_D01_TITLE"])
            continue
        short = lid.rsplit("_", 1)[1]
        if short == "L005" or short == "L014":
            mis += 1
        eq(f"{lid} line", p.get("d1warm.line"), L[lid])
        eq(f"{lid} speaker", p.get("d1warm.speaker"), "" if row["speaker"] == "SPK_SYSTEM" else spk)
        eq(f"{lid} choosing", p.get("d1warm.choosing"), short in gs.POINTS)
        eq(f"{lid} mistakes", p.get("d1warm.miss_text"), L["UI_WARMUP_MISS"].replace("{n}", str(mis)))
        eq(f"{lid} observations", [p.get(f"d1warm.obs{i}") for i in (1, 2, 3)],
           [L[f"OBS_D01_{w}"] for w in ("W1", "W2", "W3")])
        eq(f"{lid} title", p.get("d1warm.title"), L["SCR_D01_S04_TITLE"])
        if short != "L001":
            pts = [x["line"] for x in gs.W.PLAY["points"]]
            shown_pts = [s.rsplit("_", 1)[1] for sc, s, tt in run["shown"] if sc == "d1warm" and tt <= t
                         and s.rsplit("_", 1)[1] in pts]
            eq(f"{lid} point", p.get("d1warm.point"), L[f"SCR_D01_S04_{shown_pts[-1]}"])
    # outcome
    shown = [s.rsplit("_", 1)[1] for sc, s, _ in run["shown"] if sc == "d1warm"]
    out = run["outcome"]
    eq("warm-up lines", shown, list(gs.W.play(run["picks"]).shown))
    eq("L013 shown", "L013" in shown, out == "pass_clean")
    eq("L005 shown", "L005" in shown, name != "clean")
    eq("L014 L015 shown", shown[-2:] == ["L014", "L015"], out == "fail")
    p, vis = at(tr, run["marks"]["inv"])
    eq("investigation after the warm-up", sorted(vis & MAIN), ["d1inv"])
    eq("appraisals", p.get("d1inv.appr_text"), L["UI_V2_APPRAISE_LEFT"].replace("{n}", str(WANT_APPR[out])))
    if lang == "zh-TW":
        eq("world.d1Warmup", final_warmup(rec, run["ticks"]), out)
    if "carry" in run["marks"]:
        eq("carry screen", sorted(at(tr, run["marks"]["carry"])[1] & MAIN), ["d1carry"])
    noise = [ln for ln in err.split("\n") if ln.strip() and not ln.startswith("render: off")]
    if noise:
        bad.append("stderr: " + " | ".join(noise[:5]))
    label = f"{name} [{lang}]"
    if bad:
        fails.append(label)
        print(f"FAIL {label}: " + "; ".join(bad[:20]))
    else:
        nvn = sum(1 for sc, *_ in run["shown"] if sc == "vn")
        print(f"PASS {label}: paper, {nvn} vn lines (S02, S03), warm-up {' '.join(shown)} -> {out}, "
              f"appraisals {WANT_APPR[out]}")


SHOTS = {  # name -> (run, a predicate on the marked line); taken just before the next click (fade-ins over)
    "s01_paper": ("clean", lambda sc, lid: sc == "paper"),
    "s02_landlady": ("clean", lambda sc, lid: lid == "SCR_D01_S02_L002"),
    "s03_briggs": ("clean", lambda sc, lid: lid == "SCR_D01_S03_L006"),
    "s03_cedric": ("clean", lambda sc, lid: lid == "SCR_D01_S03_L010"),
    "warm_point": ("clean", lambda sc, lid: lid == "SCR_D01_S04_L002"),
    "warm_wrong": ("pass", lambda sc, lid: lid == "SCR_D01_S04_L005"),
    "warm_success": ("clean", lambda sc, lid: lid == "SCR_D01_S04_L013"),
    "warm_fail": ("fail", lambda sc, lid: lid == "SCR_D01_S04_L014"),
    "warm_fail_arthur": ("fail", lambda sc, lid: lid == "SCR_D01_S04_L015"),
}


def shots(out: Path, ticks: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for run in sorted({r for r, _ in SHOTS.values()}):
        named = {}
        for name, (rn, pred) in SHOTS.items():
            if rn == run:
                named[name] = next(t for sc, lid, t in ticks[run]["shown"] if pred(sc, lid)) + gs.WAIT - 10
        for lang in ("zh-TW", "en"):
            tmp = Path(tempfile.mkdtemp(prefix="d1storyshots-"))
            try:
                p = subprocess.run([str(EXE), "shot", "--game", ".", "--replay", str(TESTS / f"d1_story_{run}.atrec"),
                                    "--at", ",".join(str(t) for t in sorted(set(named.values()))), "--out", str(tmp),
                                    "--lang", lang], capture_output=True, cwd=ROOT,
                                   env=dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME))
                if p.returncode != 0:
                    raise SystemExit(f"shot failed: {p.stderr.decode('utf-8', 'replace')}")
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
    if subprocess.run([sys.executable, str(TESTS / "gen_d1_story.py")], cwd=ROOT).returncode != 0:
        raise SystemExit("gen_d1_story failed")
    ticks = json.loads((TESTS / "d1_story_ticks.json").read_text(encoding="utf-8"))
    for lang in ("zh-TW", "en"):
        for name in ("clean", "pass", "fail"):
            check(name, ticks[name], lang, fails)
    if "--shots" in argv:
        shots(Path(argv[argv.index("--shots") + 1]), ticks)
    tw.__exit__(None, None, None)
    left = tw.leaks
    if left:
        fails.append("temp")
        print("FAIL temp: left behind: " + ", ".join(left))
    print("ok" if not fails else f"FAILED: {', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
