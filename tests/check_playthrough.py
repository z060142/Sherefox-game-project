# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Replay the test recordings headless and check the UI port trace against the data tables.

Usage (from the project root):
    uv run tests/check_playthrough.py [--frames DIR] [--keep-trace]

Environment:
    XTATRIUM_EXE          the xtatrium CLI to use (overrides the rest)
    XTATRIUM_SDK          installed XTAtrium SDK directory, used when it holds the CLI and XTATRIUM is not set
    XTATRIUM              XTAtrium checkout; its Release build of src/XTAtrium.Headless is used
                          (dotnet build src/XTAtrium.Headless -c Release)
    XTATRIUM_XTFRAME_DIR  XTFrame runtime directory (default: the SDK's xtframe/, or <XTATRIUM>/artifacts/xtframe)
    With none of them set, `xtatrium` on PATH is used; when nothing is found the script stops with a message.

Checks:
1. Data assumptions of flows/dialogue.xtflow: every vn scene of Ch.1-3 has playable rows (script.playable; the
   flow skips the others, so they need not be contiguous), script.playable follows its rule (kind line, not inactive, not S90), and sceneKey is
   CH0n_Sss with n < 10 (the flow builds it with format "CH0{a}_{b}").
2. ch1_playthrough (zh-TW and --lang en): every playable line of Ch.1's vn steps is shown exactly once, in order
   (one vn.line_seq change per line, with the expected vn.line and vn.speaker text), the vn surface is the only
   visible main screen while lines are shown, the Ch.1 paper shows both pages while it is the only visible main
   screen, and the run ends on the Ch.2 opening paper (page 1). No warning or error on stderr.
3. full_run: every playable line of Ch.1-3 in order, every opening paper and the final paper (CH04_OPEN) with
   the previous case's strip, and the title's end card (title.ended). A click on the end card emits end_dismiss
   and clears title.ended with the title still the only main screen; the chapter list then starts Ch.3 (its lines
   again, up to the end card a second time); Enter on the end card dismisses it too, and the Ch.3 entry (clicked
   again, the same value) then
   opens the Ch.2 paper.
4. lang_toggle: the title's toggle flips title.lang_en (true, false, true) and the paper and the first vn line
   are then in English.

With --frames DIR the zh-TW playthrough also writes PNG screenshots to DIR: title.png (before the click),
vn_line.png (Ch.1 S02, third line) and paper_ch2.png (the Ch.2 opening paper at the end).
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import gen_playthrough  # noqa: E402

from xt_cli import EXE, XTFRAME, compile_game  # noqa: E402  (the CLI and its XTFrame runtime, tests/xt_cli.py)
MAIN_SCREENS = ("title", "paper", "vn", "investigate", "board", "debate", "result")


def load(name: str):
    return json.loads((ROOT / "data" / f"{name}.json").read_text(encoding="utf-8"))


def strings(lang: str) -> dict[str, str]:
    with open(ROOT / "strings" / f"{lang}.csv", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    return {r[0]: r[1] for r in rows[1:]}


class Failures:
    def __init__(self) -> None:
        self.items: list[str] = []

    def check(self, cond: bool, msg: str) -> None:
        if not cond:
            self.items.append(msg)


# ---------------------------------------------------------------- data assumptions

def check_data(fail: Failures) -> None:
    script = load("script")
    for r in script:
        fail.check(r["playable"] == (r["kind"] == "line" and not r["inactive"] and r["scene"] != "S90"),
                   f"{r['id']}: playable {r['playable']} does not follow the rule (data-schema §3)")
        fail.check(r["sceneKey"] == f"CH0{r['chapter']}_{r['scene']}" and r["chapter"] < 10,
                   f"{r['id']}: sceneKey {r['sceneKey']!r}")
    for step in load("steps"):
        if step["kind"] != "vn":
            continue
        key = f"CH0{step['chapter']}_{step['scene']}"
        idx = [i for i, r in enumerate(script) if r["sceneKey"] == key and r["playable"]]
        fail.check(bool(idx), f"{step['id']}: {key} has no playable row")


# ---------------------------------------------------------------- run and parse

LINE = re.compile(r"^t=(\d+|load) (port|write|event) (.*)$")


def run(recording: str, ticks: int, lang: str | None, frames: Path | None) -> tuple[list[tuple[int, str, str]], str]:
    args = [str(EXE), "run", "--game", gen_playthrough.GAME, "--replay", str(ROOT / "tests" / f"{recording}.atrec"),
            "--ticks", str(ticks), "--ports"]
    if lang:
        args += ["--lang", lang]
    if frames:
        args += ["--ui-frames", str(frames)]
    env = dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME)
    # .NET writes redirected output in the console code page; make it UTF-8 for the child, then restore it.
    old_cp = None
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        old_cp = k32.GetConsoleOutputCP()
        k32.SetConsoleOutputCP(65001)
    try:
        p = subprocess.run(args, capture_output=True, env=env, cwd=ROOT)
    finally:
        if old_cp:
            ctypes.windll.kernel32.SetConsoleOutputCP(old_cp)
    out = p.stdout.decode("utf-8").replace("\r\n", "\n")
    err = p.stderr.decode("utf-8").replace("\r\n", "\n")
    if p.returncode != 0:
        raise SystemExit(f"error: xtatrium run exited {p.returncode}\n{err}")
    events: list[tuple[int, str, str]] = []
    for raw in out.split("\n"):
        m = LINE.match(raw)
        if m:
            tick = -1 if m.group(1) == "load" else int(m.group(1))
            events.append((tick, m.group(2), m.group(3)))
        elif raw and events:
            t, kind, rest = events[-1]
            events[-1] = (t, kind, rest + "\n" + raw)   # a string value with a newline
    return events, err


def unquote(v: str):
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if v in ("true", "false"):
        return v == "true"
    try:
        return float(v)
    except ValueError:
        return v


class Trace:
    """Per tick, in order: the port values at the end of the tick and the visibility after the tick's events."""

    def __init__(self, events) -> None:
        self.ticks: list[tuple[int, dict[str, object], set[str], dict[str, object]]] = []
        ports: dict[str, object] = {}
        visible = {"title", "cutin"}   # game.json initial visibility of the main screens
        by_tick: dict[int, list] = {}
        for t, kind, rest in events:
            by_tick.setdefault(t, []).append((kind, rest))
        for t in sorted(k for k in by_tick if k >= 0):
            changed: dict[str, object] = {}
            for kind, rest in by_tick[t]:
                if kind == "port":
                    name, _, value = rest.partition("=")
                    ports[name] = changed[name] = unquote(value)
                elif kind == "event":
                    parts = rest.split(" ")
                    if parts[1] == "EMIT":
                        changed[f"emit:{parts[0]}.{parts[2]}"] = True
                    elif parts[1] == "SHOWN":
                        visible.add(parts[0])
                    elif parts[1] == "HIDDEN":
                        visible.discard(parts[0])
            self.ticks.append((t, dict(ports), set(visible), changed))

    def last(self, name: str):
        return self.ticks[-1][1].get(name) if self.ticks else None


def main_visible(visible: set[str]) -> set[str]:
    return {v for v in visible if v in MAIN_SCREENS}


# ---------------------------------------------------------------- checks

def expected_lines(chapter: int, lang: str):
    s = strings(lang)
    script = load("script")
    out = []
    import gen_debate_play   # the result steps play their scene's lines of the minimal outcome's branch
    for step in load("steps"):
        if step["chapter"] != chapter or step["kind"] not in ("vn", "result", "warmup", "debate"):
            continue
        branch = gen_debate_play.MINIMAL_BRANCH if step["kind"] == "result" else ""
        rows = [r for r in script if r["chapter"] == chapter and r["scene"] == step["scene"] and r["playable"]]
        if step["kind"] in ("warmup", "debate"):
            # script.cue: the opening lines, then (the minimal play loses every debate) the warmup's wrap-up
            cues = ["pre", "postWin"] if step["kind"] == "warmup" else ["pre", "postLose"]
            rows = [r for c in cues for r in rows if r["cue"] == c]
        else:
            rows = [r for r in rows if r["branch"] == branch]
        for r in rows:
            out.append((r["id"], s[r["text"]], s[r["speaker"]] if r["focus"] != 0 else ""))
    return out


def check_playthrough(fail: Failures, lang: str, frames: Path | None) -> None:
    label = f"ch1_playthrough[{lang}]"
    ticks = gen_playthrough.ch1_playthrough(lang)
    events, err = run("ch1_playthrough", ticks, None if lang == "zh-TW" else lang, frames / "_ppm" if frames else None)
    for line in err.splitlines():
        fail.check(not line.startswith(("warning:", "error:")), f"{label}: stderr: {line}")
    tr = Trace(events)
    s = strings(lang)
    papers = {p["group"]: p for p in load("papers")}

    shown = []
    for t, ports, visible, changed in tr.ticks:
        if "vn.line_seq" in changed and changed["vn.line_seq"] != 0:
            shown.append((t, ports.get("vn.line"), ports.get("vn.speaker")))
            fail.check(main_visible(visible) == {"vn"}, f"{label}: t={t} line shown while visible = {sorted(visible)}")
    exp = expected_lines(1, lang)
    fail.check(len(shown) == len(exp), f"{label}: {len(shown)} lines shown, {len(exp)} expected")
    for i, ((rid, text, spk), got) in enumerate(zip(exp, shown)):
        fail.check(got[1] == text, f"{label}: line {i + 1} ({rid}) t={got[0]}: text {got[1]!r} != {text!r}")
        fail.check(got[2] == spk, f"{label}: line {i + 1} ({rid}) t={got[0]}: speaker {got[2]!r} != {spk!r}")
    print(f"{label}: {len(shown)} of {len(exp)} lines shown in order" if shown[: len(exp)] and len(shown) == len(exp)
          else f"{label}: lines shown {len(shown)}, expected {len(exp)}")

    # The Ch.1 paper: page 1 then page 2, paper the only main screen; title before the click.
    ch1_head = s[papers["CH01_OPEN"]["headlineKey"]]
    ch2_head = s[papers["CH02_OPEN"]["headlineKey"]]
    pages = [(t, ports.get("paper.page")) for t, ports, visible, changed in tr.ticks
             if main_visible(visible) == {"paper"} and ports.get("paper.headline") == ch1_head]
    fail.check(any(p == 1 for _, p in pages) and any(p == 2 for _, p in pages),
               f"{label}: the Ch.1 paper did not show page 1 and page 2 ({sorted({p for _, p in pages})})")
    first = tr.ticks[0]
    fail.check(main_visible(first[2]) == {"title"}, f"{label}: first tick visible = {sorted(first[2])}")
    t_end, ports_end, vis_end, _ = tr.ticks[-1]
    fail.check(main_visible(vis_end) == {"paper"}, f"{label}: last tick visible = {sorted(vis_end)}")
    fail.check(ports_end.get("paper.headline") == ch2_head, f"{label}: last paper headline {ports_end.get('paper.headline')!r}")
    fail.check(ports_end.get("paper.page") == 1, f"{label}: last paper page {ports_end.get('paper.page')!r}")
    fail.check(ports_end.get("paper.result_head") == s[papers["CH02_OPEN"]["sideLoseKey"]],
               f"{label}: Ch.2 result strip {ports_end.get('paper.result_head')!r}")
    fail.check(ports_end.get("title.lang_en") == (lang == "en"), f"{label}: title.lang_en {ports_end.get('title.lang_en')!r}")

    if frames:
        export_frames(fail, frames, tr, ticks)


def check_full_run(fail: Failures) -> None:
    label = "full_run"
    ticks = gen_playthrough.full_run()
    events, err = run("full_run", ticks, None, None)
    for line in err.splitlines():
        fail.check(not line.startswith(("warning:", "error:")), f"{label}: stderr: {line}")
    tr = Trace(events)
    s = strings("zh-TW")
    papers = {p["group"]: p for p in load("papers")}
    shown = [(t, ports.get("vn.line"), ports.get("vn.speaker"), main_visible(visible))
             for t, ports, visible, changed in tr.ticks if "vn.line_seq" in changed and changed["vn.line_seq"] != 0]
    exp = expected_lines(1, "zh-TW") + expected_lines(2, "zh-TW") + expected_lines(3, "zh-TW") * 2
    fail.check([(x[1], x[2]) for x in shown] == [(e[1], e[2]) for e in exp],
               f"{label}: {len(shown)} lines shown, {len(exp)} expected (Ch.1-3, then Ch.3 again), or out of order")
    fail.check(all(x[3] == {"vn"} for x in shown), f"{label}: a line was shown while vn was not the only main screen")
    # Every opening paper, then the final paper (CH04_OPEN) with the Ch.3 result strip, each while paper is visible;
    # every paper port that has a papers column (data-schema §9; an empty key is an empty string).
    paper_ports = {"headline": "headlineKey", "subhead": "subKey", "body": "bodyKey", "page2_head": "page2HeadKey",
                   "page2_body": "page2BodyKey", "side": "sideKey", "ad": "adKey", "result_head": "sideLoseKey",
                   "result_sub": "sideLoseSubKey"}   # the minimal play loses every debate (gen_debate_play)
    seen = [ports for _, ports, visible, _ in tr.ticks if main_visible(visible) == {"paper"}]
    for group in ("CH01_OPEN", "CH02_OPEN", "CH03_OPEN", "CH04_OPEN"):
        row = papers[group]
        want = {f"paper.{port}": s.get(row[col], "") for port, col in paper_ports.items()}
        want["paper.picture"] = row["pictureId"]
        fail.check(any(all(p.get(k) == v for k, v in want.items()) for p in seen),
                   f"{label}: paper {group} not shown with its columns {want}")
    # The end card: shown twice (Ch.3 is played again after the first dismissal), each time on the title alone.
    # Each end_dismiss (a click, then Enter) clears title.ended by the next tick; the title then stays the only main
    # screen, without its card, until the chapter list starts a chapter (Ch.3, then Ch.3 again: the same value,
    # seen through the emit) and its paper shows.
    ended = [t for t, ports, visible, ch in tr.ticks if ch.get("title.ended") is True]
    fail.check(len(ended) == 2, f"{label}: title.ended set {len(ended)} times, expected 2")
    for t, ports, visible, ch in tr.ticks:
        if ch.get("title.ended") is True:
            fail.check(main_visible(visible) == {"title"}, f"{label}: t={t} end card while visible = {sorted(visible)}")
    dismiss = [t for t, _, _, ch in tr.ticks if ch.get("emit:title.end_dismiss")]
    fail.check(len(dismiss) == 2, f"{label}: title.end_dismiss emitted {len(dismiss)} times, expected 2")
    for i, t in enumerate(dismiss):
        want_group, want_ch = "CH03_OPEN", 3
        after = [x for x in tr.ticks if x[0] > t]
        cleared = next((x[0] for x in after if x[3].get("title.ended") is False), None)
        fail.check(cleared is not None and cleared <= t + 1, f"{label}: end_dismiss at t={t} did not clear title.ended")
        pick = next((x for x in after if "emit:title.chapter" in x[3]), None)
        fail.check(pick is not None and pick[1].get("title.chapter") == want_ch,
                   f"{label}: no title.chapter={want_ch} after end_dismiss at t={t}")
        if cleared is None or pick is None:
            continue
        idle = [x for x in after if cleared <= x[0] < pick[0]]
        fail.check(all(main_visible(v) == {"title"} and p.get("title.ended") is False for _, p, v, _ in idle),
                   f"{label}: after end_dismiss at t={t} the title is not shown alone without its card")
        head = s[papers[want_group]["headlineKey"]]
        fail.check(any(main_visible(v) == {"paper"} and p.get("paper.headline") == head
                       for tt, p, v, _ in after if tt > pick[0]),
                   f"{label}: the chapter list did not open {want_group} after end_dismiss at t={t}")
    t_end, ports_end, vis_end, _ = tr.ticks[-1]
    fail.check(main_visible(vis_end) == {"paper"} and ports_end.get("paper.page") == 1
               and ports_end.get("paper.headline") == s[papers["CH03_OPEN"]["headlineKey"]],
               f"{label}: does not end on the Ch.3 opening paper ({sorted(vis_end)}, {ports_end.get('paper.headline')!r})")
    print(f"{label}: {len(shown)} of {len(exp)} lines (Ch.1-3, Ch.3 again) in order, 4 papers, end card at "
          f"t={','.join(map(str, ended)) or '-'}, end_dismiss at t={','.join(map(str, dismiss)) or '-'} (click, Enter), "
          f"chapter list opens Ch.3, then Ch.3 again")


def check_lang_toggle(fail: Failures) -> None:
    label = "lang_toggle"
    ticks = gen_playthrough.lang_toggle()
    events, err = run("lang_toggle", ticks, None, None)
    for line in err.splitlines():
        fail.check(not line.startswith(("warning:", "error:")), f"{label}: stderr: {line}")
    tr = Trace(events)
    flips = [ch["title.lang_en"] for _, _, _, ch in tr.ticks if "title.lang_en" in ch]
    fail.check(flips[-3:] == [True, False, True], f"{label}: title.lang_en changes {flips}")
    en = strings("en")
    papers = {p["group"]: p for p in load("papers")}
    heads = {ports.get("paper.headline") for _, ports, visible, _ in tr.ticks if "paper" in visible}
    fail.check(en[papers["CH01_OPEN"]["headlineKey"]] in heads, f"{label}: no English Ch.1 headline ({heads})")
    first = expected_lines(1, "en")[0]
    fail.check(tr.last("vn.line") == first[1], f"{label}: first vn line {tr.last('vn.line')!r}")
    print(f"{label}: lang_en {flips}, paper and first line in English" if not fail.items else f"{label}: done")


# ---------------------------------------------------------------- frames

def ppm_to_png(src: Path, dst: Path) -> None:
    data = src.read_bytes()
    parts = data.split(b"\n", 3)
    w, h = (int(x) for x in parts[1].split())
    pixels = parts[3]
    raw = b"".join(b"\x00" + pixels[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    dst.write_bytes(png)


def latest_frame(dir_: Path, ui: str, before: int) -> Path | None:
    best = None
    for f in dir_.glob(f"{ui}-*.ppm"):
        t = int(f.stem.split("-")[1])
        if t < before and (best is None or t > best[0]):
            best = (t, f)
    return best[1] if best else None


def export_frames(fail: Failures, frames: Path, tr: Trace, ticks: int) -> None:
    raw = frames / "_ppm"
    rec = [json.loads(l) for l in (ROOT / "tests" / "ch1_playthrough.atrec").read_text(encoding="utf-8").splitlines()[1:]]
    clicks = [e["t"] for e in rec]
    vn_ticks = [t for t, _, _, ch in tr.ticks if ch.get("vn.line_seq") == 3]
    picks = {
        "title.png": ("title", clicks[0]),
        "vn_line.png": ("vn", next(c for c in clicks if vn_ticks and c > vn_ticks[0])),
        "paper_ch2.png": ("paper", ticks),
    }
    for name, (ui, before) in picks.items():
        f = latest_frame(raw, ui, before)
        fail.check(f is not None, f"frames: no {ui} frame before tick {before}")
        if f:
            ppm_to_png(f, frames / name)
            print(f"frames: {name} <- {f.name}")


def main() -> int:
    frames = None
    if "--frames" in sys.argv:
        frames = Path(sys.argv[sys.argv.index("--frames") + 1]).resolve()
        frames.mkdir(parents=True, exist_ok=True)
    compile_game()     # AT-036: the flows' endpoints resolve before anything runs
    fail = Failures()
    check_data(fail)
    print("data: every vn scene has playable rows; playable and sceneKey follow their rules"
          if not fail.items else "data: assumption broken")
    if frames:
        (frames / "_ppm").mkdir(exist_ok=True)
    check_playthrough(fail, "zh-TW", frames)
    check_playthrough(fail, "en", None)
    check_full_run(fail)
    check_lang_toggle(fail)
    if frames:
        shutil.rmtree(frames / "_ppm", ignore_errors=True)
    for f in fail.items:
        print("FAIL " + f)
    print("ok" if not fail.items else f"{len(fail.items)} failure(s)")
    return 0 if not fail.items else 1


if __name__ == "__main__":
    sys.exit(main())
