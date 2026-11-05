# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Replay the test recordings headless and check the UI port trace against the data tables.

Usage (from the project root):
    uv run tests/check_playthrough.py [--frames DIR] [--keep-trace]

Environment:
    XTATRIUM              XTAtrium checkout (default E:/coding4/XTArtrium); its Release build of
                          src/XTAtrium.Headless is used (dotnet build src/XTAtrium.Headless -c Release)
    XTATRIUM_XTFRAME_DIR  XTFrame runtime directory (default <XTATRIUM>/artifacts/xtframe)

Checks:
1. Data assumptions of flows/dialogue.xtflow: every vn scene of Ch.1-3 starts with its heading and every later
   row of the scene is a playable line (kind line, not inactive).
2. ch1_playthrough (zh-TW and --lang en): every playable line of Ch.1's vn steps is shown exactly once, in order
   (one vn.line_seq change per line, with the expected vn.line and vn.speaker text), the vn surface is the only
   visible main screen while lines are shown, the Ch.1 paper shows both pages while it is the only visible main
   screen, and the run ends on the Ch.2 opening paper (page 1). No warning or error on stderr.
3. full_run: every playable line of Ch.1-3 in order, every opening paper and the final paper (CH04_OPEN) with
   the previous case's strip, and the run ends on the title with its end card (title.ended).
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

XTATRIUM = Path(os.environ.get("XTATRIUM", "E:/coding4/XTArtrium"))
XTFRAME = os.environ.get("XTATRIUM_XTFRAME_DIR", str(XTATRIUM / "artifacts" / "xtframe"))
EXE = XTATRIUM / "src" / "XTAtrium.Headless" / "bin" / "Release" / "net10.0" / ("xtatrium.exe" if os.name == "nt" else "xtatrium")
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
    for step in load("steps"):
        if step["kind"] != "vn":
            continue
        rows = [r for r in script if r["chapter"] == step["chapter"] and r["scene"] == step["scene"]]
        idx = [i for i, r in enumerate(script) if r["chapter"] == step["chapter"] and r["scene"] == step["scene"]]
        fail.check(idx == list(range(idx[0], idx[0] + len(idx))), f"{step['id']}: scene rows are not contiguous")
        fail.check(rows[0]["kind"] == "heading", f"{step['id']}: first row of {step['scene']} is not its heading")
        for r in rows[1:]:
            fail.check(r["kind"] == "line" and not r["inactive"], f"{step['id']}: {r['id']} is not a playable line")


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
        p = subprocess.run(args, capture_output=True, env=env)
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
                    if parts[1] == "SHOWN":
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
    for step in load("steps"):
        if step["chapter"] != chapter or step["kind"] != "vn":
            continue
        for r in script:
            if r["chapter"] == chapter and r["scene"] == step["scene"] and r["kind"] == "line" and not r["inactive"]:
                out.append((r["id"], s[r["text"]], s[r["speaker"]] if r["focus"] != 0 else ""))
    return out


def check_playthrough(fail: Failures, lang: str, frames: Path | None) -> None:
    label = f"ch1_playthrough[{lang}]"
    ticks = gen_playthrough.ch1_playthrough()
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
    fail.check(ports_end.get("paper.result_head") == s[papers["CH02_OPEN"]["sideWinKey"]],
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
    exp = expected_lines(1, "zh-TW") + expected_lines(2, "zh-TW") + expected_lines(3, "zh-TW")
    fail.check([(x[1], x[2]) for x in shown] == [(e[1], e[2]) for e in exp],
               f"{label}: {len(shown)} lines shown, {len(exp)} expected, or out of order")
    fail.check(all(x[3] == {"vn"} for x in shown), f"{label}: a line was shown while vn was not the only main screen")
    # Every opening paper, then the final paper (CH04_OPEN) with the Ch.3 result strip, each while paper is visible.
    seen = [(ports.get("paper.headline"), ports.get("paper.result_head")) for _, ports, visible, _ in tr.ticks
            if main_visible(visible) == {"paper"}]
    for group in ("CH01_OPEN", "CH02_OPEN", "CH03_OPEN", "CH04_OPEN"):
        row = papers[group]
        strip = s[row["sideWinKey"]] if row["resultChapter"] > 0 else ""
        fail.check((s[row["headlineKey"]], strip) in seen, f"{label}: paper {group} not shown with result strip {strip!r}")
    ended = [t for t, ports, visible, ch in tr.ticks if ch.get("title.ended") is True]
    fail.check(len(ended) == 1, f"{label}: title.ended set {len(ended)} times")
    t_end, ports_end, vis_end, _ = tr.ticks[-1]
    fail.check(main_visible(vis_end) == {"title"} and ports_end.get("title.ended") is True,
               f"{label}: does not end on the title end card ({sorted(vis_end)}, ended={ports_end.get('title.ended')})")
    print(f"{label}: {len(shown)} of {len(exp)} lines (Ch.1-3) in order, 4 papers, end card at t={ended[0] if ended else '-'}")


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
    fail = Failures()
    check_data(fail)
    print("data: vn scenes are heading + playable lines" if not fail.items else "data: assumption broken")
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
