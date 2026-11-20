# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Replay the v2 demo D01 click-probe recording (tests/gen_d1_views.py) headless and check that every clickable row
of the D01 lists selects what it shows wherever on the row it is clicked, and that the private views (私下的看法) are
kept per evidence and reach the debate (docs/ui-contracts.md d1inv / d1book / d1carry / d1debate / d1warm,
tests/README.md). Runs in zh-TW and en.

- every expectation of d1_views_ticks.json "checks", read from the list ports' JSON writes (d1inv.locs, d1book.cards,
  d1book.opts, d1carry.items, d1debate.ev_list / claims / ochain): the selected ids, and for the private view also the
  rows shown for the selected evidence;
- the private views at the end (`--dump`: d1PrivNote) equal what the recording chose (one cleared);
- the warm-up's observation cards clicked at five points: each run's d1warm port trace equals the centre run's.

Regression for the private-view rows that could not be chosen (v2 demo, commit 60ed969): the rows' selected state
lived in a map of 8 entries keyed by claim that was never cleared, so after the first 8 claims shown every other row
stayed unlit when clicked (and the lit "(no view yet)" row went off), and "(no view yet)" of the last evidence (P1)
read the view from before the click.

Usage (from the project root):
    uv run tests/check_d1_views.py
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
import check_d1_play as cd  # noqa: E402
import check_playthrough as cp  # noqa: E402
import gen_d1_views as gv  # noqa: E402
from check_d1_m3 import At  # noqa: E402
from tempwatch import TempWatch  # noqa: E402
from xt_cli import EXE, XTFRAME, compile_game  # noqa: E402

PORT = {"locs": "d1inv.locs", "cards": "d1book.cards", "opts": "d1book.opts", "carry": "d1carry.items",
        "evs": "d1debate.ev_list", "claims": "d1debate.claims", "chain": "d1debate.ochain"}


def run_dump(rec: Path, game: str, ticks: int, lang: str) -> tuple[list, str, dict]:
    """`xtatrium run --ports --dump` (the dump into a temporary directory, removed)."""
    tmp = Path(tempfile.mkdtemp(prefix="sherefox-views-"))
    try:
        args = [str(EXE), "run", "--game", game, "--replay", str(rec), "--ticks", str(ticks), "--ports", "--lang",
                lang, "--dump", str(tmp / "dump.json")]
        old_cp = None
        if os.name == "nt":   # .NET writes redirected output in the console code page: UTF-8 for the child
            import ctypes
            old_cp = ctypes.windll.kernel32.GetConsoleOutputCP()
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        try:
            p = subprocess.run(args, capture_output=True, cwd=ROOT, env=dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME))
        finally:
            if old_cp:
                ctypes.windll.kernel32.SetConsoleOutputCP(old_cp)
        out = p.stdout.decode("utf-8").replace("\r\n", "\n")
        err = p.stderr.decode("utf-8").replace("\r\n", "\n")
        if p.returncode != 0:
            raise SystemExit(f"error: xtatrium run {rec.name} exited {p.returncode}\n{err}")
        dump = json.loads((tmp / "dump.json").read_text(encoding="utf-8"))
        return cp.parse_events(out), err, dump
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check(lang: str, ticks: dict, fails: list) -> None:
    events, err, dump = run_dump(TESTS / "d1_views.atrec", gv.GAME, ticks["ticks"], lang)
    at = At(cp.Trace(events), events)
    bad: list[str] = []
    kinds: dict[str, int] = {}
    for c in ticks["checks"]:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
        lst = at.get(c["t"], PORT[c["kind"]]) or []
        sel = [x["id"] for x in lst if x.get("sel")]
        if c["kind"] == "carry":
            sel = sorted(sel, key=gv.gm.ITEMS.index)
        got = {"sel": sel}
        want = {"sel": c["sel"]}
        if c["kind"] == "opts":
            got["rows"] = [x["id"] for x in lst]
            want["rows"] = c["rows"]
        if got != want:
            bad.append(f"{c['what']} (t{c['t']}): got {got}, want {want}")
    views = {e["key"]: e["value"] for e in dump["collections"].get("d1PrivNote", {}).get("entries", [])}
    want_views = {e: v for e, v in ticks["views"].items()}
    got_views = {e: views.get(e, "") for e in want_views}
    if got_views != want_views:
        bad.append(f"d1PrivNote at the end: {got_views} (want {want_views})")
    noise = [ln for ln in err.split("\n") if ln.strip() and not ln.startswith("render: off")]
    if noise:
        bad.append("stderr: " + " | ".join(noise[:5]))
    if bad:
        fails.append(f"views [{lang}]")
        print(f"FAIL views [{lang}]: {len(bad)} of {len(ticks['checks']) + 1} checks")
        for b in bad[:40]:
            print("  " + b)
    else:
        print(f"PASS views [{lang}]: " + ", ".join(f"{n} {k}" for k, n in kinds.items())
              + f"; d1PrivNote = {','.join(f'{e}:{v or chr(45)}' for e, v in got_views.items())}")


def check_warm(lang: str, fails: list) -> None:
    """The warm-up's observation cards at five points: the d1warm port trace equals the centre run's."""
    tmp = Path(tempfile.mkdtemp(prefix="sherefox-views-"))
    try:
        traces = {}
        for point, (r, end) in gv.warm_variants().items():
            path = tmp / f"warm_{point}.atrec"
            path.write_text("\n".join(r.lines) + "\n", encoding="utf-8", newline="\n")
            events, err, _ = run_dump(path, ".", end, lang)
            traces[point] = [(t, rest) for t, kind, rest in events
                             if kind == "port" and rest.startswith("d1warm.")]
        bad = [p for p, tr in traces.items() if tr != traces["centre"]]
        if not traces["centre"]:
            bad.append("no d1warm trace")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if bad:
        fails.append(f"warm-up cards [{lang}]")
        print(f"FAIL warm-up cards [{lang}]: the run clicked at {', '.join(bad)} differs from the centre's")
    else:
        print(f"PASS warm-up cards [{lang}]: the observation cards at five points ({len(traces['centre'])} d1warm "
              f"port changes, the same in each run)")


def main() -> int:
    compile_game()
    tw = TempWatch().__enter__()   # tests/tempwatch.py: only what this run creates counts as a leak
    fails: list[str] = []
    try:
        if subprocess.run([sys.executable, str(TESTS / "gen_d1_views.py")], cwd=ROOT).returncode != 0:
            raise SystemExit("gen_d1_views failed")
        ticks = json.loads((TESTS / "d1_views_ticks.json").read_text(encoding="utf-8"))
        for lang in ("zh-TW", "en"):
            check(lang, ticks, fails)
            check_warm(lang, fails)
    finally:
        shutil.rmtree(gv.HARNESS, ignore_errors=True)
    tw.__exit__(None, None, None)
    if tw.leaks:
        fails.append("temp")
        print("FAIL temp: left behind: " + ", ".join(tw.leaks))
    print("ok" if not fails else f"FAILED: {', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
