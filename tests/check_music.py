# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Check the music and the debate end jingles (docs/flows.md §4.8, §4.10; rulings H1-H3; the design's BGM cue table;
docs/audio-requests.md) headless.

Usage (from the project root):
    uv run tests/check_music.py

1. Static: game.json `audio` declares exactly the files under audio/ (one looping bgm-category music cue per
   audio/bgm/<id>.mp3 with tools/gen_flows.py MUSIC's loop points, one se-category cue per audio/sfx/<id>.mp3, the
   bgm channel); flowBgm.play is 1 exactly for the ids with a track or silence, its fade a FADE_SECONDS kind;
   flows/music.xtflow has the crossfade play (fadeIn = the fade's seconds), the cut's play (fadeIn 0) after a
   FADE_SECONDS["cut"] timer and one stop (fadeOut = the fade's seconds); debate_ui has one sound node per jingle.
2. Cue table (data/bgmCues.json against source/staging/bgm_cues_ch01-03.csv): every design cue reaches a shown line
   with its track after the fallback (bgm when delivered or NONE, else the fallback) and its fade; the Ch.3 cues and
   the Ch.4 teaser are listed, so the cues no replay reaches (Ch.3 after the warm-up) are covered here.
3. Replays (--trace; the music commands do not reach the trace, so the music flow's own values are read: world.bgm,
   the cue in effect, the fade of the last change, the command counters bgmPlays / bgmStops and the channel's
   target cue from atrium.music.playing): ch1_debate (the pudding debate won), ch2_lose (Ch.2 lost, retried, lost
   again), ch3_warmfail (Ch.3 from the title to the investigation, three warm-up mistakes), d1_story_clean (the v2
   demo D01 from the title through S01-S04 and the investigation to the carry screen; tests/gen_d1_story.py). The expected sequence of
   (track, fade) is derived from ROUTES (the steps and scenes each replay passes through) with bgmCues for the lines
   and flowBgm for the moments, and printed. In each: world.bgm is the cue's track while a cue is in effect and
   flowBgm's id of the moment otherwise, on every tick; its sequence of changes equals the expected one; each change
   makes exactly its commands: cross -> one play (fadeIn 1.5), cut -> one stop (fadeOut 0.2), then one play 0.2 s
   later (fadeIn 0), silence -> one stop (fadeOut of its kind), and nothing else; atrium.music.playing follows within
   two ticks; the jingles play once per main debate result.
No warning or error on stderr. The trace files go to a temporary directory that is deleted.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))
import check_playthrough as cp  # noqa: E402
import gen_flows as F  # noqa: E402
import gen_op as OP  # noqa: E402
from xt_cli import EXE, XTFRAME, compile_game  # noqa: E402

TICKS = json.loads((ROOT / "tests" / "debate_ticks.json").read_text(encoding="utf-8"))
DT = json.loads((ROOT / "game.json").read_text(encoding="utf-8"))["stepSeconds"]
# The steps each replay passes through: ("moment", m) = a screen without script lines (flowBgm), ("paper", group),
# ("lines", sceneKey, branch) = the scene's shown lines in order (a debate / warm-up scene: its opening lines).
ROUTES = {
    "ch1_debate": ([("moment", "title"), ("paper", "CH01_OPEN"), ("lines", "CH01_S02", ""), ("lines", "CH01_S03", ""),
                    ("moment", "investigate"), ("moment", "board"), ("lines", "CH01_S05", ""), ("moment", "pudding"),
                    ("moment", "result"), ("lines", "CH01_S06", "win"), ("lines", "CH01_S07", ""),
                    ("paper", "CH02_OPEN")], {"SFX_DEB_WIN": 1}),
    # observe every round: the opponent never drops to half (no debate2); the retry has no opening lines
    "ch2_lose": ([("moment", "title"), ("paper", "CH02_OPEN"), ("lines", "CH02_S02", ""), ("lines", "CH02_S03", ""),
                  ("moment", "investigate"), ("moment", "board"), ("lines", "CH02_S05", ""), ("moment", "debate"),
                  ("moment", "result"), ("moment", "debate"), ("moment", "result"), ("lines", "CH02_S06", "lose"),
                  ("lines", "CH02_S07", ""), ("paper", "CH03_OPEN")], {"SFX_DEB_LOSE": 2}),
    # the retorts and the failure wrap-up (F001-F004) have no cue: the warm-up moment
    "ch3_warmfail": ([("moment", "title"), ("paper", "CH03_OPEN"), ("lines", "CH03_S02", ""),
                      ("lines", "CH03_S03", ""), ("lines", "CH03_S04", ""), ("moment", "warmup"),
                      ("moment", "investigate")], {}),
    # the v2 demo D01 (tests/gen_d1_story.py, M4a): the S01 paper, S02, S03 (L003's cut), then the steps without
    # script lines play a fixed cue row (docs/flows.md §4.10): the warm-up (S04 L001's), the investigation (the pseudo
    # id SCR_D01_S05_START), the carry screen (S06 L001's)
    "d1_story_clean": ([("moment", "title"), ("paper", "D01_OPEN"), ("lines", "D01_S02", ""), ("lines", "D01_S03", ""),
                        ("fixed", "SCR_D01_S04_L001"), ("fixed", "SCR_D01_S05_START"), ("fixed", "SCR_D01_S06_L001")],
                       {}),
}
TICKS.update({f"d1_story_{k}": v["ticks"] for k, v in json.loads((ROOT / "tests" / "d1_story_ticks.json").read_text(
    encoding="utf-8")).items()})
# The v2 demo D01's debate (v2 demo 4.3; staging bgm_cues_d01.csv and its README), on tests/gen_d1_play.py's route
# recordings (dev shortcut, opponent pinned by the harness): world.bgm in order and its fade; None = an id without a
# track (BGM10), which changes world.bgm but sends no command. Title BGM01; S07 L001's silence (out) over L001-L003;
# BGM07 at the start (L004's cut); BGM08 at his first 破防 (round 1 in A, D; round 2 in B); BGM09 on 論破 (A8, B5);
# B: silence from L007 (he gives up), BGM09 again with L012 (crossfade), silence at L015; A: L012 keeps BGM09, silence
# at L015; D: BGM10 on the Reverse Break (no track: BGM08 goes on), silence from the loss (L016) through L017-L019.
# v2 demo 4.4 (cues BGM_D01_14-19): then the result step's S08 lines BGM12 (L001's cue), kept under the result screen;
# the S09 paper BGM11 (its version's cue: L001 decent, L005 ugly); S10 BGM02; S11 BGM01, which the title keeps after
# back to title (no change, no restart). E5 (design 48be4a6, BGM_D01_20): on a loss S08 never plays BGM12: its lines
# (L011, L012) and the result screen stay silent after the loss's silence, and BGM11 comes back with the S09 paper.
EPILOGUE = [("BGM12", "cross"), ("BGM11", "cross"), ("BGM02", "cross"), ("BGM01", "cross")]
EPILOGUE_LOSS = [("BGM11", "cross"), ("BGM02", "cross"), ("BGM01", "cross")]
D01_ROUTES = {
    "d1_routeA": ("A", [("BGM01", "cross"), ("", "out"), ("BGM07", "cut"), ("BGM08", "cross"), ("BGM09", "cross"),
                        ("", "out")] + EPILOGUE),
    "d1_routeB": ("B", [("BGM01", "cross"), ("", "out"), ("BGM07", "cut"), ("BGM08", "cross"), ("BGM09", "cross"),
                        ("", "out"), ("BGM09", "cross"), ("", "out")] + EPILOGUE),
    "d1_routeD": ("D", [("BGM01", "cross"), ("", "out"), ("BGM07", "cut"), ("BGM08", "cross"), ("BGM10", None),
                        ("", "out")] + EPILOGUE_LOSS),
}
# v2 demo E6 (V2): two debates in one run (tests/gen_d1_play.py d1_twiceA / d1_twiceD: route A won / route D lost, back
# to the title, the dev entry again): the title keeps S11's BGM01, S07 L001's silence, then BGM07 (cut) with nothing
# of the debate before in between (its BGM09 / BGM10 / silence flags are cleared when the step begins)
AGAIN = [("", "out"), ("BGM07", "cut")]
D01_ROUTES["d1_twiceA"] = ("A", D01_ROUTES["d1_routeA"][1] + AGAIN)
D01_ROUTES["d1_twiceD"] = ("D", D01_ROUTES["d1_routeD"][1] + AGAIN)
TICKS.update({k: v for k, v in json.loads((ROOT / "tests" / "d1_ticks.json").read_text(encoding="utf-8")).items()
              if k in D01_ROUTES})
VALUES = ("moment", "momBgm", "cueOk", "cueBgm", "bgmId", "bgmFadeA", "bgmSecsA", "bgmPlays", "bgmStops", "bgmNow")


def load(rel: str) -> list[dict]:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def expected(name: str) -> list[tuple[str, str]]:
    """The (track, fade) changes ROUTES[name] asks for: "" = silence; ids without a track (BGM10) are skipped."""
    cues, bgm = load("data/bgmCues.json"), {r["moment"]: r for r in load("data/flow/flowBgm.json")}
    branch = {r["id"]: r["branch"] for r in load("data/script.json")}
    body = {p["group"]: p["bodyKey"] for p in load("data/papers.json")}
    want: list[tuple[str, str]] = []
    for seg in ROUTES[name][0]:
        if seg[0] == "moment":
            r = bgm[seg[1]]
            asks = [(r["bgm"], r["fade"])] if r["play"] else []
        elif seg[0] == "fixed":
            asks = [(r["bgm"], r["fade"]) for r in cues if r["line"] == seg[1]]
        elif seg[0] == "paper":
            asks = [(r["bgm"], r["fade"]) for r in cues if r["line"] == body[seg[1]]]
        else:
            asks = [(r["bgm"], r["fade"]) for r in cues
                    if r["scene"] == seg[1] and branch.get(r["line"], "") in ("", seg[2])]
        for a in asks:
            if not want or want[-1][0] != a[0]:
                want.append(a)
    return want


def check_static(fail: cp.Failures) -> None:
    game = json.loads((ROOT / "game.json").read_text(encoding="utf-8"))
    audio = game.get("audio", {})
    files = {p.relative_to(ROOT).as_posix() for p in (ROOT / "audio").rglob("*.mp3")}
    music, cues = audio.get("music", {}), audio.get("cues", {})
    # v3: the opening's music on its own channel (tools/gen_op.py; tests/check_op.py plays it)
    fail.check(audio.get("channels") == ["bgm", OP.CHANNEL], f"game.json audio.channels {audio.get('channels')}")
    fail.check(music.get(OP.CUE) == {"file": OP.MUSIC_FILE, "loop": False, "category": "bgm"},
               f"game.json audio.music.{OP.CUE} {music.get(OP.CUE)}")
    fail.check({d["file"] for d in [*music.values(), *cues.values()]} == files,
               f"game.json audio does not declare exactly the files under audio/ ({sorted(files)})")
    for bid, (start, end) in F.MUSIC.items():
        d = music.get(bid, {})
        want = {"file": f"audio/bgm/{bid}.mp3", "loop": True, "loopEnd": round(end * F.AUDIO_RATE), "category": "bgm"}
        if start:
            want["loopStart"] = round(start * F.AUDIO_RATE)
        fail.check(d == want, f"game.json audio.music.{bid} {d}, expected {want}")
    for cid in F.SFX:
        fail.check(cues.get(cid) == {"file": f"audio/sfx/{cid}.mp3", "category": "se"}, f"game.json audio.cues.{cid}")
    fail.check(game["tables"].get("bgmCues") == "data/bgmCues.json", "game.json tables.bgmCues")
    for row in load("data/flow/flowBgm.json"):
        fail.check(row["play"] == int(row["bgm"] in music or row["bgm"] == ""),
                   f"flowBgm {row}: play must be 1 iff the id has a track or is silence")
        fail.check(F.FADE_SECONDS.get(row["fade"]) == row["secs"], f"flowBgm {row}: fade / secs")
    flow = json.loads((ROOT / "flows" / "music.xtflow").read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in flow["nodes"]}
    consts = {n["id"]: n["params"]["value"] for n in flow["nodes"] if n["type"] == "constant"}
    src = {e["to"]: e["from"] for e in flow["edges"]}
    plays = sorted(n["id"] for n in flow["nodes"] if n["type"] == "atrium.music.play")
    stops = sorted(n["id"] for n in flow["nodes"] if n["type"] == "atrium.music.stop")
    fail.check(plays == ["bgmCutPlay", "bgmPlay"] and stops == ["bgmStop"], f"music.xtflow plays {plays} stops {stops}")
    fail.check(all(nodes[i].get("params") == {"channel": "bgm"} for i in plays + stops), "music commands: channel bgm")
    fail.check(src.get("bgmPlay.fadeIn") == "bgmSecsA.out" and src.get("bgmStop.fadeOut") == "bgmSecsA.out",
               f"bgmPlay.fadeIn / bgmStop.fadeOut from {src.get('bgmPlay.fadeIn')} / {src.get('bgmStop.fadeOut')}")
    fail.check(consts.get(src.get("bgmCutPlay.fadeIn", ".").split(".")[0]) == 0, "bgmCutPlay.fadeIn must be 0")
    fail.check(nodes.get("bgmCut", {}).get("params", {}).get("interval") == F.FADE_SECONDS["cut"],
               f"bgmCut timer {nodes.get('bgmCut')}")
    deb = json.loads((ROOT / "flows" / "debate_ui.xtflow").read_text(encoding="utf-8"))
    sounds = sorted(n["params"]["cue"] for n in deb["nodes"] if n["type"] == "sound")
    fail.check(sounds == sorted(F.SFX), f"debate_ui sound nodes {sounds}")


def check_cues(fail: cp.Failures) -> None:
    """Every design cue reaches a shown line of bgmCues with its resolved track and fade (past the warm-up, Ch.3 and
    the Ch.4 teaser are covered only here)."""
    text = (ROOT / "source" / "staging" / "bgm_cues_ch01-03.csv").read_text(encoding="utf-8-sig")
    design = list(csv.DictReader(io.StringIO(text)))
    rows = load("data/bgmCues.json")
    for r in rows:
        fail.check(r["bgm"] in F.MUSIC or r["bgm"] == "", f"bgmCues {r['line']}: undelivered track {r['bgm']}")
        fail.check(F.FADE_SECONDS.get(r["fade"]) == r["secs"], f"bgmCues {r['line']}: fade / secs")
    for d in design:
        bgm = d["bgm"] if d["bgm"] == "NONE" or d["bgm"] in F.MUSIC else d["fallback"]
        want = ("" if bgm == "NONE" else bgm, d["fade"])
        got = [r for r in rows if r["cue"] == d["cue_id"]]
        fail.check(bool(got) and all((r["bgm"], r["fade"]) == want for r in got),
                   f"{d['cue_id']}: bgmCues rows {[(r['line'], r['bgm'], r['fade']) for r in got]}, expected {want}")
        if d["chapter"] not in ("1", "2") and got:
            print(f"  {d['cue_id']} {d['start_id']} -> {got[0]['line']}..{got[-1]['line']}: "
                  f"{want[0] or 'silence'} ({want[1]}; design {d['bgm']}{' / ' + d['fallback'] if d['fallback'] else ''})")
    # the v2 demo D01 (source/staging/bgm_cues_d01.csv): all 20 cues are in the table (E5: BGM_D01_20, the loss's
    # silent S08 from L011), S07 onward too; the pseudo id SCR_D01_S05_START has its row
    text = (ROOT / "source" / "staging" / "bgm_cues_d01.csv").read_text(encoding="utf-8-sig")
    d01 = list(csv.DictReader(io.StringIO(text)))
    fail.check(len(d01) == 20, f"bgm_cues_d01.csv: {len(d01)} cues (20 expected)")
    loss = [r for r in load("data/bgmCues.json") if r["line"] in ("SCR_D01_S08_L011", "SCR_D01_S08_L012")]
    fail.check([(r["cue"], r["bgm"]) for r in loss] == [("BGM_D01_20", "")] * 2,
               f"the loss's S08 lines are not silent (BGM_D01_20): {loss}")
    for d in d01:
        bgm = d["bgm"] if d["bgm"] == "NONE" or d["bgm"] in F.MUSIC else d["fallback"]
        want = ("" if bgm == "NONE" else bgm, d["fade"])
        got = [r for r in rows if r["cue"] == d["cue_id"]]
        fail.check(bool(got) and all((r["bgm"], r["fade"]) == want for r in got) and got[0]["line"] == d["start_id"],
                   f"{d['cue_id']}: bgmCues rows {[(r['line'], r['bgm'], r['fade']) for r in got]}, expected {want} "
                   f"from {d['start_id']}")
    r = next((r for r in rows if r["line"] == "SCR_D01_S05_START"), None)
    fail.check(r is not None and (r["cue"], r["scene"], r["bgm"]) == ("BGM_D01_06", "D01_S05", "BGM05"),
               f"bgmCues SCR_D01_S05_START: {r}")
    for line, cue, bgm, fade in (("SCR_CH03_S03_L002", "BGM_CH03_03", "BGM03", "cross"),
                                 ("SCR_CH03_S03_L003", "BGM_CH03_04", "BGM04", "cut"),
                                 ("SCR_CH03_S07_L010", "BGM_CH03_09", "BGM03", "cross"),
                                 # the line inserted with the text rewrite keeps S03's carriage music; the cut to
                                 # BGM04 still starts on L003 (the inspector)
                                 ("SCR_D01_S03_L002", "BGM_D01_03", "BGM03", "cross"),
                                 ("SCR_D01_S03_L002A", "BGM_D01_03", "BGM03", "cross"),
                                 ("SCR_D01_S03_L003", "BGM_D01_04", "BGM04", "cut")):
        r = next((r for r in rows if r["line"] == line), None)
        fail.check(r is not None and (r["cue"], r["bgm"], r["fade"]) == (cue, bgm, fade), f"bgmCues {line}: {r}")


def value_index() -> dict[str, int]:
    """The music flow's node id -> index of its first output in the trace (node order x output order, 53 §53.7.1),
    from `xtatrium compile --game . --emit ir`."""
    p = subprocess.run([str(EXE), "compile", "--game", ".", "--emit", "ir"], capture_output=True, cwd=ROOT,
                       env=dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME))
    if p.returncode != 0:
        raise SystemExit(f"FAIL compile --emit ir (exit {p.returncode})")
    out, idx, n, on = p.stdout.decode("utf-8", errors="replace"), {}, 0, False   # the music flow is ASCII
    for line in out.splitlines():
        if line.startswith("== "):
            on = line.endswith("/music.xtflow (logic)")
            continue
        if not on:
            continue
        m = re.match(r"  node \d+ (\S+) ", line)
        if m:
            idx[m.group(1)] = n
        elif re.match(r"    out \d+ ", line):
            n += 1
    idx["#"] = n
    return idx


def trace_lines(text: str) -> list[str]:
    """The --trace lines, one per tick (t=N) or host effect (tN ...). A string value never breaks a line (XTAtrium
    AT-092: control characters are escaped, check_playthrough.unescape), so any other line is an error."""
    out = [ln for ln in text.split(chr(10)) if ln]
    bad = [ln for ln in out if not re.match(r"t=?\d+ ", ln)]
    if bad:
        raise SystemExit(f"FAIL trace: not a tick or effect line: {bad[0][:200]!r}")
    return out


def music_values(line: str, idx: dict[str, int]) -> dict | None:
    """The music flow's values on one trace line (None when the line has none)."""
    head = " flows/music.xtflow:"
    if head not in line:
        return None
    rest = line[line.index(head) + len(head):].rstrip("\n")
    for sep in (" / ", " |"):
        j = rest.find(sep)
        if j >= 0:
            rest = rest[:j]
    # the music flow's values are ids: no spaces ("" is an empty token); bare, with the CLI's escapes undone
    tok = [cp.unescape(x) for x in rest[1:].split(" ")]
    if len(tok) != idx["#"]:
        raise SystemExit(f"FAIL music trace: {len(tok)} values, the IR has {idx['#']}")
    v = {k: tok[idx[k]] for k in VALUES}
    v["now"] = tok[idx["bgmNow"] + 1]   # atrium.music.playing: playing, cue
    for k in ("bgmPlays", "bgmStops", "bgmSecsA", "cueOk"):
        v[k] = float(v[k] if v[k] not in ("", "-") else 0)
    return v


def replay(name: str, idx: dict[str, int], tmp: Path, game: str = ".") -> tuple[list[tuple[int, dict]], dict[str, list[int]], str]:
    trace = tmp / f"{name}.trace"
    p = subprocess.run([str(EXE), "run", "--game", game, "--replay", str(ROOT / "tests" / f"{name}.atrec"),
                        "--ticks", str(TICKS[name]), "--trace", str(trace)], capture_output=True, cwd=ROOT,
                       env=dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME))
    err = p.stderr.decode("utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit(f"FAIL xtatrium run {name} (exit {p.returncode})\n{err}")
    ticks, sounds = [], {}
    with trace.open(encoding="utf-8") as f:
        for line in trace_lines(f.read()):
            if not line.startswith("t="):   # host effect lines (XTAtrium AT-056) repeat the sound cues
                continue
            t = int(line[2:line.index(" ")])
            v = music_values(line, idx)
            if v is not None:
                ticks.append((t, v))
            for cue in re.findall(r"sound cue=(\S+)", line):
                sounds.setdefault(cue, []).append(t)
    trace.unlink()
    return ticks, sounds, err


def bgm_sequence(ticks: list[tuple[int, dict]]) -> list[str]:
    """The ids world.bgm takes, in order ("" = silence)."""
    out: list[str] = []
    for _, v in ticks:
        if not out or out[-1] != v["bgmId"]:
            out.append(v["bgmId"])
    return out


def fmt(seq: list[tuple[str, str]]) -> str:
    return " -> ".join(f"{b or 'silence'} ({f})" for b, f in seq)


def check_route(fail: cp.Failures, name: str, ticks: list[tuple[int, dict]], sounds: dict[str, list[int]],
                err: str, want: list | None = None, jingles: dict | None = None) -> None:
    for line in err.splitlines():
        fail.check(not line.startswith(("warning:", "error:")), f"{name}: stderr: {line}")
    bad = [t for t, v in ticks if v["bgmId"] != (v["cueBgm"] if v["cueOk"] else v["momBgm"])]
    fail.check(not bad, f"{name}: world.bgm is neither the cue's track nor the moment's at t={bad[:5]}")
    # the ids world.bgm takes (every tick: a transient id would show here) and the commands of each change
    cmds, plays, stops = [], 0, 0
    for i, (t, v) in enumerate(ticks):
        if v["bgmPlays"] == plays and v["bgmStops"] == stops:
            continue
        fail.check(v["bgmPlays"] + v["bgmStops"] == plays + stops + 1,
                   f"{name}: t={t}: two commands in a tick ({plays}/{stops} -> {v['bgmPlays']}/{v['bgmStops']})")
        kind = "play" if v["bgmPlays"] != plays else "stop"
        plays, stops = v["bgmPlays"], v["bgmStops"]
        cmds.append((t, kind, v["bgmFadeA"], 0.0 if kind == "play" and v["bgmFadeA"] == "cut" else v["bgmSecsA"]))
        target = "" if kind == "stop" else v["bgmId"]
        later = [w["now"] for _, w in ticks[i:i + 3]]
        fail.check(target in later, f"{name}: t={t}: atrium.music.playing {later} does not reach {target or 'silence'}")
    ids = bgm_sequence(ticks)
    want = expected(name) if want is None else want
    fail.check(ids == [b for b, _ in want], f"{name}: world.bgm {ids}, expected {[b for b, _ in want]}")
    # the commands each expected change makes, in order
    exp_cmds = []
    for b, f in want:
        if f is None:       # an id without a track: the current music goes on
            continue
        if b == "":
            exp_cmds.append(("stop", f, F.FADE_SECONDS[f]))
        elif f == "cut":
            exp_cmds += [("stop", f, F.FADE_SECONDS[f]), ("play", f, 0.0)]
        else:
            exp_cmds.append(("play", f, F.FADE_SECONDS[f]))
    got_cmds = [(k, f, round(s, 3)) for _, k, f, s in cmds]
    fail.check(got_cmds == exp_cmds, f"{name}: commands {got_cmds}, expected {exp_cmds}")
    for j, (t, k, f, _) in enumerate(cmds):
        if k == "play" and f == "cut":
            gap = (t - cmds[j - 1][0]) * DT if j else -1
            fail.check(j > 0 and cmds[j - 1][1] == "stop"
                       and F.FADE_SECONDS["cut"] - DT <= gap <= F.FADE_SECONDS["cut"] + 2 * DT,
                       f"{name}: t={t}: the cut's play {gap:.3f} s after the stop")
    got = {c: len(ts) for c, ts in sounds.items()}
    jingles = ROUTES[name][1] if jingles is None else jingles
    fail.check(got == jingles, f"{name}: sound cues {got}, expected {jingles}")
    print(f"{name}: expected {fmt([(b, f or '-') for b, f in want])}")
    print(f"{name}: world.bgm {' -> '.join(b or 'silence' for b in ids)}")
    print(f"{name}: commands " + ", ".join(f"t={t} {k} {f} {s:g}s" for t, k, f, s in cmds)
          + "".join(f"; {c} at t={','.join(map(str, ts))}" for c, ts in sorted(sounds.items())))


def main() -> int:
    compile_game()
    fail = cp.Failures()
    check_static(fail)
    print("static: game.json audio, flowBgm, music commands and jingle nodes" + ("" if not fail.items else " (failures)"))
    n = len(fail.items)
    print("cue table (Ch.3 and the Ch.4 teaser):")
    check_cues(fail)
    print("cue table: every design cue reaches its lines" + ("" if len(fail.items) == n else " (failures)"))
    idx = value_index()
    with tempfile.TemporaryDirectory(prefix="sherefox-music-") as d:
        for name in ROUTES:
            ticks, sounds, err = replay(name, idx, Path(d))
            check_route(fail, name, ticks, sounds, err)
        # the v2 demo D01's debate: the route recordings and their harnesses (tests/gen_d1_play.py), deleted after
        import gen_d1_play as gd
        try:
            if subprocess.run([sys.executable, str(ROOT / "tests" / "gen_d1_play.py")], cwd=ROOT).returncode != 0:
                raise SystemExit("gen_d1_play failed")
            TICKS.update(json.loads((ROOT / "tests" / "d1_ticks.json").read_text(encoding="utf-8")))
            for name, (route, want) in D01_ROUTES.items():
                ticks, sounds, err = replay(name, idx, Path(d), f"tests/d1play_harness{route}")
                check_route(fail, name, ticks, sounds, err, want, {})
        finally:
            for route in gd.ROUTES:
                shutil.rmtree(gd.harness_dir(route), ignore_errors=True)
    for f in fail.items:
        print("FAIL " + f)
    print("ok" if not fail.items else f"{len(fail.items)} failure(s)")
    return 0 if not fail.items else 1


if __name__ == "__main__":
    sys.exit(main())
