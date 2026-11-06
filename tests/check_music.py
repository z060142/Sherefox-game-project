# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Check the music and the debate end jingles (docs/flows.md §4.8, §4.10; rulings H1-H3; docs/audio-requests.md)
headless.

Usage (from the project root):
    uv run tests/check_music.py

1. Static: game.json `audio` declares exactly the files under audio/ (one looping bgm-category music cue per
   audio/bgm/<id>.mp3 with tools/gen_flows.py MUSIC's loop points, one se-category cue per audio/sfx/<id>.mp3, the
   bgm channel); flowBgm.play is 1 exactly for the ids with a track; flows/music.xtflow has one atrium.music.play
   (channel bgm, fadeIn MUSIC_FADE) and debate_ui one sound node per jingle.
2. Replays (--trace; the music commands do not reach the trace, so the music flow's own values are read: the BGM
   id world.bgm, the play counter bgmPlays and the channel's target cue from atrium.music.playing, bgmNow):
   - ch1_debate (the pudding debate won): BGM01 title -> BGM02 daily -> BGM05 investigate -> BGM06 board -> BGM12
     pudding (from the debate step's first tick, its pre lines included) -> BGM11 result -> BGM02 daily (the Ch.2
     paper), and SFX_DEB_WIN once;
   - ch2_lose (Ch.2 lost, retried, lost again; observe every round, so the opponent never drops to half: no
     BGM08): BGM01 -> BGM02 -> BGM05 -> BGM06 -> BGM07 -> BGM11 -> BGM07 (the retry) -> BGM11 -> BGM02 (the Ch.3
     paper), and SFX_DEB_LOSE once per defeat.
   In each: world.bgm is flowBgm's id of world.bgmMoment on every tick; bgmPlays grows by exactly one per change of
   the played track and never otherwise; bgmNow reaches the new track within two ticks of the change.
No warning or error on stderr. The trace files go to a temporary directory that is deleted.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))
import check_playthrough as cp  # noqa: E402
import gen_flows as F  # noqa: E402
from xt_cli import EXE, XTFRAME, compile_game  # noqa: E402

TICKS = json.loads((ROOT / "tests" / "debate_ticks.json").read_text(encoding="utf-8"))
ROUTES = {
    "ch1_debate": (["BGM01", "BGM02", "BGM05", "BGM06", "BGM12", "BGM11", "BGM02"], {"SFX_DEB_WIN": 1}),
    "ch2_lose": (["BGM01", "BGM02", "BGM05", "BGM06", "BGM07", "BGM11", "BGM07", "BGM11", "BGM02"],
                 {"SFX_DEB_LOSE": 2}),
}
VALUES = ("moment", "bgmId", "bgmPlays", "bgmNow")


def check_static(fail: cp.Failures) -> None:
    game = json.loads((ROOT / "game.json").read_text(encoding="utf-8"))
    audio = game.get("audio", {})
    files = {p.relative_to(ROOT).as_posix() for p in (ROOT / "audio").rglob("*.mp3")}
    music, cues = audio.get("music", {}), audio.get("cues", {})
    fail.check(audio.get("channels") == ["bgm"], f"game.json audio.channels {audio.get('channels')}")
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
    for row in json.loads((ROOT / "data" / "flow" / "flowBgm.json").read_text(encoding="utf-8")):
        fail.check(row["play"] == int(row["bgm"] in music), f"flowBgm {row}: play must be 1 iff the id has a track")
    flow = json.loads((ROOT / "flows" / "music.xtflow").read_text(encoding="utf-8"))
    plays = [n for n in flow["nodes"] if n["type"] == "atrium.music.play"]
    fail.check(len(plays) == 1 and plays[0]["params"] == {"channel": "bgm"}, f"music.xtflow play nodes {plays}")
    consts = {n["id"]: n["params"]["value"] for n in flow["nodes"] if n["type"] == "constant"}
    fade = [e["from"] for e in flow["edges"] if e["to"] == "bgmPlay.fadeIn"]
    fail.check(len(fade) == 1 and consts.get(fade[0].split(".")[0]) == F.MUSIC_FADE, f"bgmPlay.fadeIn from {fade}")
    deb = json.loads((ROOT / "flows" / "debate_ui.xtflow").read_text(encoding="utf-8"))
    sounds = sorted(n["params"]["cue"] for n in deb["nodes"] if n["type"] == "sound")
    fail.check(sounds == sorted(F.SFX), f"debate_ui sound nodes {sounds}")


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


def replay(name: str, idx: dict[str, int], tmp: Path) -> tuple[list[tuple[int, dict]], dict[str, list[int]], str]:
    trace = tmp / f"{name}.trace"
    p = subprocess.run([str(EXE), "run", "--game", ".", "--replay", str(ROOT / "tests" / f"{name}.atrec"),
                        "--ticks", str(TICKS[name]), "--trace", str(trace)], capture_output=True, cwd=ROOT,
                       env=dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME))
    err = p.stderr.decode("utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit(f"FAIL xtatrium run {name} (exit {p.returncode})\n{err}")
    ticks, sounds = [], {}
    head = " flows/music.xtflow:"
    with trace.open(encoding="utf-8") as f:
        for line in f:
            t = int(line[2:line.index(" ")])
            rest = line[line.index(head) + len(head):]
            for sep in (" / ", " |"):
                j = rest.find(sep)
                if j >= 0:
                    rest = rest[:j]
            tok = rest[1:].split(" ")   # the music flow's values are ids: no spaces
            if len(tok) != idx["#"]:
                raise SystemExit(f"FAIL {name}: t={t}: {len(tok)} music values, the IR has {idx['#']}")
            ticks.append((t, {"moment": tok[idx["moment"]], "bgm": tok[idx["bgmId"]],
                              "plays": int(float(tok[idx["bgmPlays"]])), "now": tok[idx["bgmNow"] + 1]}))
            for cue in re.findall(r"sound cue=(\S+)", line):
                sounds.setdefault(cue, []).append(t)
    trace.unlink()
    return ticks, sounds, err


def check_route(fail: cp.Failures, name: str, ticks: list[tuple[int, dict]], sounds: dict[str, list[int]],
                err: str) -> None:
    for line in err.splitlines():
        fail.check(not line.startswith(("warning:", "error:")), f"{name}: stderr: {line}")
    bgm_of = {r["moment"]: r["bgm"] for r in json.loads((ROOT / "data" / "flow" / "flowBgm.json").read_text("utf-8"))}
    bad = [t for t, v in ticks if bgm_of.get(v["moment"], "") != v["bgm"]]
    fail.check(not bad, f"{name}: world.bgm is not flowBgm's id of the moment at t={bad[:5]}")
    # the ids world.bgm takes (every tick: a transient id would show here) and the tracks played
    seq, played, plays, last_track = [], [], 0, None
    for i, (t, v) in enumerate(ticks):
        if v["plays"] != plays:
            fail.check(v["plays"] == plays + 1, f"{name}: t={t}: bgmPlays {plays} -> {v['plays']}")
            plays = v["plays"]
            cur = v["bgm"]
            fail.check(cur in F.MUSIC and cur != last_track, f"{name}: t={t}: a play of {cur} (last {last_track})")
            later = [w["now"] for _, w in ticks[i:i + 3]]
            fail.check(cur in later, f"{name}: t={t}: bgmNow {later} does not reach {cur}")
            played.append((t, cur))
            last_track = cur
        if not seq or seq[-1] != v["bgm"]:
            seq.append(v["bgm"])
    tracks = []
    for b in seq:   # the tracks the ids ask for: ids without a track (BGM10) keep the previous one
        if b in F.MUSIC and (not tracks or tracks[-1] != b):
            tracks.append(b)
    fail.check([b for _, b in played] == tracks, f"{name}: tracks played {[b for _, b in played]}, ids {seq}")
    want_seq, want_sounds = ROUTES[name]
    fail.check(seq == want_seq, f"{name}: world.bgm sequence {seq}, expected {want_seq}")
    got = {c: len(ts) for c, ts in sounds.items()}
    fail.check(got == want_sounds, f"{name}: sound cues {got}, expected {want_sounds}")
    print(f"{name}: world.bgm {' -> '.join(seq)}; {len(played)} plays at t={','.join(str(t) for t, _ in played)}; "
          + "; ".join(f"{c} at t={','.join(map(str, ts))}" for c, ts in sorted(sounds.items())))


def main() -> int:
    compile_game()
    fail = cp.Failures()
    check_static(fail)
    print("static: game.json audio, flowBgm.play, music and jingle nodes" + ("" if not fail.items else " (failures)"))
    idx = value_index()
    with tempfile.TemporaryDirectory(prefix="sherefox-music-") as d:
        for name in ROUTES:
            ticks, sounds, err = replay(name, idx, Path(d))
            check_route(fail, name, ticks, sounds, err)
    for f in fail.items:
        print("FAIL " + f)
    print("ok" if not fail.items else f"{len(fail.items)} failure(s)")
    return 0 if not fail.items else 1


if __name__ == "__main__":
    sys.exit(main())
