# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Check the v3 opening (OP): tools/gen_op.py, flows/op.xtflow, the OP surface `sherefox-op` and its skip layer
`opskip` (docs/v3-op.md, docs/flows.md §4.16). Headless, against the packed bundle (`xtatrium pack --game .` first).

Every other recording skips the OP at tick 0 (tests/gen_playthrough.py OP_SKIP); these runs do not, except where a
case says so:

(a) start with the OP: the title is hidden from tick 0 (tick 0 draws nothing: a black frame); from tick 1 the OP
    surface and the skip layer are drawn and the OP's music starts (channel `op`, no fade) in the tick the surface
    shows (the timeline starts on that show); no bgm music before the end. At the end of the timeline (its length in
    fixed steps) the OP and its music stop, the title shows and the title's music (BGM01) starts.
(b) skip by a click, Enter and Esc (and Space once) on the skip layer in the first second, the middle and the last
    second: the next tick the title shows, the OP's music stops, the title's starts; after it nothing of the OP moves
    (no OP or skip-layer event, no world.op* change, no op-channel command, the OP surface not drawn), also when the
    timeline's end would have come.
(c) watch again: the title's 觀看片頭 (btn-op) plays the OP again from its start over the title (the title's music
    stops in that tick) and the title comes back at its end.
(d) after the OP (played out, and skipped) the v1 chapter 1 and the v2 demo play exactly as in their own recordings:
    the port trace of the recording shifted by the time the OP took equals the original's (OP lines aside).
(e) determinism: two runs give the same state hash (OP played out, and skipped in the middle); two software-rendered
    shots of the same ticks are byte-identical.

Usage (from the project root):
    uv run tests/check_op.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(ROOT / "tools"))
import gen_op as OP  # noqa: E402
import gen_playthrough as gp  # noqa: E402
from tempwatch import TempWatch  # noqa: E402
from xt_cli import EXE, XTFRAME, compile_game  # noqa: E402

END = round(OP.timeline_seconds() / gp.STEP)   # ticks from the start of a play to its end (59.3 s: 3558)
START = 1                                       # the tick the OP starts at (tools/gen_op.py BOOT_SECONDS)
BTN_OP = (804, 25)                              # the title's btn-op (x 712-896, y 10-40)
SKIP_XY = (960, 540)                            # anywhere on the skip layer (1920x1080 surface coordinates)
KEYS = {"Enter": gp.KEY_ENTER, "Esc": gp.KEY_ESC, "Space": 44}
OP_UIS = (OP.UI, OP.SKIP_UI)
SIGNALS = ["world.op*", "world.bgm", "ui.title.shown", "ui.title.hidden", "ui.title.watch_op", f"ui.{OP.UI}.*",
           f"ui.{OP.SKIP_UI}.*"]
ENV = dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME)


class Fail:
    def __init__(self) -> None:
        self.items: list[str] = []

    def check(self, cond: bool, msg: str) -> None:
        if not cond:
            self.items.append(msg)
            print(f"FAIL {msg}")


def write_rec(path: Path, lines: list[dict]) -> Path:
    head = json.dumps({"atrec": 1, "step": gp.STEP, "seed": 1, "game": gp.GAME})
    path.write_text("\n".join([head] + [json.dumps(x) for x in lines]) + "\n", encoding="utf-8", newline="\n")
    return path


def click(ui: str, xy) -> list:
    return gp.click(ui, xy)


def skip_event(method: str) -> list:
    return click(OP.SKIP_UI, SKIP_XY) if method == "click" else gp.key(OP.SKIP_UI, KEYS[method])


def run(args: list[str]) -> str:
    p = subprocess.run([str(EXE), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
                       env=ENV)
    if p.returncode != 0:
        raise SystemExit(f"FAIL xtatrium {' '.join(args)} (exit {p.returncode})\n{p.stdout[-2000:]}{p.stderr[-2000:]}")
    return p.stdout


class Trace:
    """`xtatrium trace` lines (signal changes, pulses, host effects) as (tick, text), the UI documents' clocks left out."""

    def __init__(self, rec: Path | None, ticks: int) -> None:
        args = ["trace", "--game", ".", "--ticks", str(ticks)]
        if rec is not None:
            args += ["--replay", str(rec)]
        for s in SIGNALS:
            args += ["--signals", s]
        self.lines: list[tuple[int, str]] = []
        for line in run(args).splitlines():
            m = re.match(r"t(\d+) (.*)$", line)
            if m and ".document." not in m.group(2):
                self.lines.append((int(m.group(1)), m.group(2)))

    def at(self, t: int) -> list[str]:
        return [x for tt, x in self.lines if tt == t]

    def has(self, t: int, pattern: str) -> bool:
        return any(re.search(pattern, x) for x in self.at(t))

    def ticks(self, pattern: str) -> list[int]:
        return [t for t, x in self.lines if re.search(pattern, x)]


def surfaces(rec: Path | None, ticks: list[int], tmp: Path, renderer: str = "sw") -> dict[int, set[str]]:
    """The surfaces drawn at each tick (`xtatrium shot` lists them)."""
    out = tmp / f"shot-{len(list(tmp.iterdir()))}"
    args = ["shot", "--game", ".", "--at", ",".join(map(str, ticks)), "--out", str(out), "--renderer", renderer]
    if rec is not None:
        args += ["--replay", str(rec)]
    res = {}
    for line in run(args).splitlines():
        m = re.search(r"shot-(\d+)\.png .* surfaces=(\S*)", line)
        if m:
            res[int(m.group(1))] = set(m.group(2).split(","))
    return res


# ---------------------------------------------------------------- (a) start with the OP

def check_start(fail: Fail, tmp: Path) -> None:
    tr = Trace(None, START + END + 90)
    e = START + END
    fail.check(tr.has(0, r"ui\.title\.hidden pulse"), "start: the title is not hidden at tick 0")
    fail.check(tr.has(START, rf"ui\.{OP.UI}\.shown pulse"), f"start: the OP surface does not show at tick {START}")
    fail.check(tr.has(START, rf"effect music\.play {OP.CHANNEL} {OP.CUE} loop=false fade=0"),
               f"start: no OP music command at tick {START} ({tr.at(START)})")
    plays = tr.ticks(rf"effect music\.play {OP.CHANNEL} ")
    fail.check(plays == [START], f"start: OP music plays at {plays}, expected [{START}]")
    bgm = tr.ticks(r"effect music\.(play|stop) bgm ")
    fail.check(bgm and min(bgm) >= e, f"start: title music during the OP (bgm commands at {bgm})")
    fail.check(tr.has(e, r"world\.opOn true -> false"), f"start: the OP is not over at tick {e}")
    fail.check(tr.has(e, rf"ui\.{OP.UI}\.hidden pulse") and tr.has(e, r"ui\.title\.shown pulse"),
               f"start: at the end ({e}) the OP does not hide or the title does not show: {tr.at(e)}")
    fail.check(tr.ticks(rf"effect music\.stop {OP.CHANNEL} ") == [e], "start: the OP music does not stop at the end")
    fail.check(tr.ticks(r"effect music\.play bgm BGM01") in ([e], [e + 1]),
               f"start: the title music starts at {tr.ticks(r'effect music.play bgm BGM01')}")
    fail.check(tr.ticks(r"ui\.title\.shown") == [e], f"start: the title shows at {tr.ticks(r'ui.title.shown')}")
    vis = surfaces(None, [0, START, END // 2, e - 1, e + 1, e + 60], tmp)
    fail.check(not ({"title"} | set(OP_UIS)) & vis.get(0, set()), f"start: tick 0 draws {sorted(vis.get(0, set()))}")
    for t in (START, END // 2, e - 1):
        fail.check(set(OP_UIS) <= vis.get(t, set()) and "title" not in vis.get(t, set()),
                   f"start: tick {t} draws {sorted(vis.get(t, set()))}")
    for t in (e + 1, e + 60):
        fail.check("title" in vis.get(t, set()) and not set(OP_UIS) & vis.get(t, set()),
                   f"start: tick {t} draws {sorted(vis.get(t, set()))}")
    print(f"start: title hidden at tick 0; OP shown and its music at tick {START}; end at {e}: title shown, BGM01 at "
          f"{tr.ticks(r'effect music.play bgm BGM01')}")


# ---------------------------------------------------------------- (b) skip

def after_quiet(fail: Fail, tr: Trace, s: int, name: str) -> None:
    """Nothing of the OP after the tick that turned it off (s)."""
    later = [(t, x) for t, x in tr.lines if t > s and (
        x.startswith(f"ui.{OP.UI}.") or x.startswith(f"ui.{OP.SKIP_UI}.") or x.startswith("world.op")
        and not x.startswith("world.opMusic") or f"music.play {OP.CHANNEL} " in x or f"music.stop {OP.CHANNEL} " in x)]
    # the op channel's cue goes empty on the next tick (atrium.music.playing follows the stop command)
    later = [(t, x) for t, x in later if not (t == s + 1 and x.startswith("world.opMusic"))]
    fail.check(not later, f"{name}: the OP moves after the skip: {later[:6]}")


def check_skip(fail: Fail, tmp: Path) -> None:
    moments = {"first second": 30, "middle": END // 2, "last second": END - 30}
    cases = [(m, at) for m in ("click", "Enter", "Esc") for at in moments.items()] + [("Space", ("middle", END // 2))]
    for method, (when, at) in cases:
        name = f"skip {method} {when} (t{at})"
        rec = write_rec(tmp / f"skip-{method}-{at}.atrec", [{"t": at, "u": skip_event(method)}])
        tr = Trace(rec, START + END + 120)
        s = at + 1   # a UI event reaches the logic graph the next tick
        fail.check(tr.has(at, rf"ui\.{OP.SKIP_UI}\.skip pulse"), f"{name}: no skip event")
        fail.check(tr.has(s, r"world\.opOn true -> false") and tr.has(s, r"ui\.title\.shown pulse")
                   and tr.has(s, rf"ui\.{OP.UI}\.hidden pulse"), f"{name}: tick {s}: {tr.at(s)}")
        fail.check(tr.ticks(rf"effect music\.stop {OP.CHANNEL} ") == [s], f"{name}: the OP music does not stop at {s}")
        fail.check(tr.ticks(r"effect music\.play bgm BGM01") in ([s], [s + 1]),
                   f"{name}: the title music starts at {tr.ticks(r'effect music.play bgm BGM01')}")
        after_quiet(fail, tr, s, name)
        vis = surfaces(rec, [at, s + 1, START + END + 5], tmp)
        fail.check(set(OP_UIS) <= vis.get(at, set()) and "title" not in vis.get(at, set()),
                   f"{name}: tick {at} draws {sorted(vis.get(at, set()))}")
        for t in (s + 1, START + END + 5):
            fail.check("title" in vis.get(t, set()) and not set(OP_UIS) & vis.get(t, set()),
                       f"{name}: tick {t} draws {sorted(vis.get(t, set()))}")
    print(f"skip: {len(cases)} cases (click, Enter, Esc at t30 / t{END // 2} / t{END - 30}, Space): title the next "
          "tick, OP music stopped, BGM01, nothing of the OP afterwards")


# ---------------------------------------------------------------- (c) watch again

def check_again(fail: Fail, tmp: Path) -> None:
    w = 120
    rec = write_rec(tmp / "again.atrec", [{"t": 30, "u": skip_event("click")}, {"t": w, "u": click("title", BTN_OP)}])
    tr = Trace(rec, w + 1 + END + 90)
    a = w + 1
    fail.check(tr.has(w, r"ui\.title\.watch_op pulse"), "again: btn-op sends no watch_op")
    fail.check(tr.has(a, r"world\.opOn false -> true") and tr.has(a, rf"ui\.{OP.UI}\.shown pulse")
               and tr.has(a, r"ui\.title\.hidden pulse"), f"again: tick {a}: {tr.at(a)}")
    fail.check(tr.has(a, rf"effect music\.play {OP.CHANNEL} {OP.CUE} loop=false fade=0")
               and tr.has(a, r"effect music\.stop bgm "), f"again: tick {a} music: {tr.at(a)}")
    bgm = [t for t in tr.ticks(r"effect music\.play bgm ") if t > a]
    fail.check(bgm and min(bgm) >= a + END, f"again: title music during the OP ({bgm})")
    # the end: the timer of the timeline's length starts from the watch_op event here (in the tick's pulse step 8, so
    # it first counts the next tick) and from the boot timer at the start (in step 4, counted at once): a tick later
    ends = tr.ticks(rf"ui\.{OP.UI}\.hidden pulse")
    e = ends[-1] if ends else -1
    fail.check(e in (a + END, a + END + 1) and tr.has(e, r"ui\.title\.shown pulse"),
               f"again: the end at {e}, expected {a + END} or {a + END + 1}: {tr.at(e)}")
    vis = surfaces(rec, [a, a + 600, e - 1, e + 1], tmp)
    for t in (a, a + 600, e - 1):
        fail.check(set(OP_UIS) <= vis.get(t, set()) and "title" not in vis.get(t, set()),
                   f"again: tick {t} draws {sorted(vis.get(t, set()))}")
    fail.check("title" in vis.get(e + 1, set()) and not set(OP_UIS) & vis.get(e + 1, set()),
               f"again: tick {e + 1} draws {sorted(vis.get(e + 1, set()))}")
    print(f"again: btn-op at t{w} plays the OP from t{a} (title music stopped), title back at t{e}")


# ---------------------------------------------------------------- (d) the game after the OP

def ports(rec: Path, ticks: int) -> list[tuple[int, str]]:
    out = []
    for line in run(["run", "--game", ".", "--replay", str(rec), "--ticks", str(ticks), "--ports"]).splitlines():
        m = re.match(r"t=(\d+) (.*)$", line)
        if m and not any(f" {u}." in f" {m.group(2)}" or f" {u} " in f" {m.group(2)} " for u in OP_UIS):
            out.append((int(m.group(1)), m.group(2)))
    return out


def check_after(fail: Fail, tmp: Path) -> None:
    # (recording, ticks to compare): v1 chapter 1 through its paper, the vn and into the investigation; the v2 demo
    # from the title's v2 entry through S01-S03 and its warm-up
    for name, until in (("ch1_playthrough", 2400), ("d1_story_clean", 3600)):
        src = [json.loads(x) for x in (TESTS / f"{name}.atrec").read_text(encoding="utf-8").splitlines()[1:]]
        events = [x for x in src if "u" in x and x["t"] <= until]
        first = events[0]["t"]
        base = ports(write_rec(tmp / f"{name}-0.atrec", [{"t": 0, "w": [["input.opSkip", "p"]]}] + events), until + 60)
        want = [(t, x) for t, x in base if t >= first]
        for how, d, lead in (("played out", START + END, []), ("skipped", 31, [{"t": 30, "u": skip_event("click")}])):
            moved = [{"t": x["t"] + d, "u": x["u"]} for x in events]
            got = ports(write_rec(tmp / f"{name}-{d}.atrec", lead + moved), until + 60 + d)
            got = [(t - d, x) for t, x in got if t >= first + d]
            same = got == want
            if not same:
                diff = next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), min(len(got), len(want)))
                print(f"  {name} {how}: first difference at line {diff}: got {got[diff:diff + 2]} want {want[diff:diff + 2]}")
            fail.check(same, f"after: {name} after the OP {how} does not play as its recording "
                             f"({len(got)} / {len(want)} port lines)")
        print(f"after: {name} (to t{until}, {len(want)} port lines) the same after the OP played out and skipped")


# ---------------------------------------------------------------- (e) determinism

def check_determinism(fail: Fail, tmp: Path) -> None:
    mid = write_rec(tmp / "det-mid.atrec", [{"t": END // 2, "u": skip_event("Enter")}])
    for name, rec, ticks in (("played out", None, START + END + 60), ("skipped in the middle", mid, START + END + 60)):
        args = ["run", "--game", ".", "--ticks", str(ticks), "--hash"] + (["--replay", str(rec)] if rec else [])
        h = [re.search(r"hash: (\S+)", run(args)) for _ in range(2)]
        fail.check(all(h) and h[0].group(1) == h[1].group(1), f"determinism: {name}: hashes differ")
        print(f"determinism: {name}: hash {h[0].group(1) if h[0] else '?'} twice")
    at = [60, 600, 1500, 2400, 3300, END - 2]
    shots = []
    for i in range(2):
        out = tmp / f"det-{i}"
        run(["shot", "--game", ".", "--at", ",".join(map(str, at)), "--out", str(out), "--renderer", "sw"])
        shots.append({p.name: p.read_bytes() for p in sorted(out.glob("*.png"))})
    fail.check(len(shots[0]) == len(at) and shots[0] == shots[1], "determinism: sw frames differ between two runs")
    print(f"determinism: sw frames at {at} byte-identical in two runs")


def main() -> int:
    t0 = time.perf_counter()
    compile_game()
    fail = Fail()
    tw = TempWatch().__enter__()   # tests/tempwatch.py: only what this run creates counts as a leak
    try:
        with tempfile.TemporaryDirectory(prefix="sherefox-op-") as d:
            tmp = Path(d)
            for step in (check_start, check_skip, check_again, check_after, check_determinism):
                step(fail, tmp)
    finally:
        tw.__exit__(None, None, None)
    if tw.leaks:
        fail.check(False, "temp: left behind: " + ", ".join(tw.leaks))
    print(f"{time.perf_counter() - t0:.0f} s")
    print("ok" if not fail.items else f"FAILED: {len(fail.items)}")
    return 1 if fail.items else 0


if __name__ == "__main__":
    sys.exit(main())
