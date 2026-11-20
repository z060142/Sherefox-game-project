"""v3: the opening animation (OP), imported by tools/gen_flows.py: flows/op.xtflow. See docs/flows.md §4.16 and
docs/v3-op.md.

The OP is one more UI of the game's project (ui/project/sherefox-op, copied from the OP project; not board-owned) on
its own 1920x1080 surface, the topmost; the skip layer ui/project/opskip (a transparent surface over it) sends `skip`
on any click, Enter, Space or Esc.

world.opOn (initial true): the OP is up. While it is on, the OP surface and the skip layer are visible, main hides the
title (and every screen under it stays as it was), the music flow's moment is `op` (silence on the bgm channel).
It goes off on the skip layer's `skip`, on input.opSkip (a pulse no key is bound to: the recordings of the checks
send it at tick 0, so their runs start at the title exactly as before, docs/v3-op.md §3) or at the end of the
timeline; the title's watch_op turns it on again.

The start of a play (the first tick of the game, or watch_op) plays the timeline `op` of the OP surface and the OP's
music (audio.music.op_music on its own channel `op`, no fade, no loop) on the same pulse; going off stops both
(the music with a short fade). This flow runs first (game.json flows), so main and music read world.opOn in the same
tick: a skip at tick 0 never shows the OP.

Observation (tests/check_op.py): world.opPlays / world.opStops count the music commands of the `op` channel,
world.opMusic is that channel's cue (atrium.music.playing; "" when stopped). The timeline plays on the pulse of the
music play, so opPlays also counts the timeline's starts.
"""

from __future__ import annotations

import re
from pathlib import Path

from gen_flows import Graph

ROOT = Path(__file__).resolve().parent.parent

UI = "sherefox-op"          # the OP's UI id (kept from the OP project)
SKIP_UI = "opskip"          # the skip layer
TIMELINE = "op"             # the OP's timeline (59.3 s)
CUE = "op_music"            # audio.music cue (the OP project's own cue name)
CHANNEL = "op"              # its music channel (the bgm channel stays the music flow's)
MUSIC_FILE = "audio/op/op_music.mp3"
STOP_FADE = 0.1             # seconds: "stops at once", without a click
BOOT_SECONDS = 0.025        # the start: an autostart timer of 1.5 steps fires in tick 1 (see gen_op)
OP_DOC = ROOT / "ui" / "project" / UI / f"{UI}.xt"
UI_FLOW = f"ui/project/{UI}/{UI}.xtflow"

SIGNALS = {
    "opOn": {"type": "bool", "initial": True},          # op: the OP is up (main hides the title, music: moment op)
    "opPlays": {"type": "number", "initial": 0},        # op: music play commands on the op channel
    "opStops": {"type": "number", "initial": 0},        # op: music stop commands on the op channel
    "opMusic": {"type": "string", "initial": ""},       # op: the op channel's cue (atrium.music.playing)
}
INPUT_ACTIONS = {"opSkip": "pulse"}   # no key is bound to it (XTAtrium's SDL keymap): only recordings send it
SURFACES = [{"ui": UI, "width": 1920, "height": 1080, "visible": False},
            {"ui": SKIP_UI, "width": 1920, "height": 1080, "visible": False}]


def timeline_seconds() -> float:
    """The length of the OP's timeline: its last keyframe (the OP project's 59.3 s)."""
    text = OP_DOC.read_text(encoding="utf-8")
    body = text[text.index(f"@timeline {TIMELINE} {{"):]
    return max(float(t) for t in re.findall(r"^\s+([0-9.]+)s\b", body, re.M))


def audio_music() -> dict:
    return {CUE: {"file": MUSIC_FILE, "loop": False, "category": "bgm"}}


def gen_op() -> Graph:
    """The logic graph flows/op.xtflow (see the module docstring)."""
    g = Graph()
    g.node("on", "toggle", initial=True)       # world.opOn: the OP is up (from tick 0)
    g.put("on", "on.value")
    g.edge("on.value", "world.opOn")
    g.toggle("shown")                          # its surfaces are shown (from the start of a play)
    g.edge("shown.value", f"ui#{UI}.visible")
    g.edge("shown.value", f"ui#{SKIP_UI}.visible")

    # the start of a play: tick 1 of the game while still on (an autostart timer of 1.5 steps: it fires in step 4 of
    # tick 1), or the title's watch_op (the title only takes input while the OP is off: it is hidden while on).
    # Not tick 0: a graph runs its timers (step 4) before it reads the tick's input (steps 5 and 8, XTAtrium 05 §5.4),
    # so in tick 0 a run's input.opSkip is not known yet; from tick 1 it is, and a run that skips at tick 0 sends no
    # command of the OP at all. Tick 0 is a black frame (the title is already hidden: world.opOn starts true).
    # Showing the surface is what plays the timeline (the OP's UI flow, gen_op_ui): the surface is shown in the ui
    # step of the same tick as the music command below, and the timeline starts on that show.
    g.node("boot", "timer", interval=BOOT_SECONDS, autostart=True, repeat=False)
    g.edge("ui#title.watch_op", "on.setTrue")
    start = g.merge("start", g.when("bootG", "boot.tick", "on.value"), "ui#title.watch_op")
    g.edge(start, "shown.setTrue")
    # the end of the timeline: a logic graph cannot read the UI timeline's end event (ui#<ui>.timeline.<name>.end is
    # not an endpoint), so a timer of the timeline's length starts in the same tick (both count fixed steps; a second
    # start restarts it). It starts on the boot tick even after a skip at tick 0 (gating it on `on` would close a cycle
    # through on.setFalse); a tick that comes after a skip finds the OP already off.
    g.node("end", "timer", interval=timeline_seconds(), autostart=False, repeat=False)
    g.edge(g.merge("endStart", "boot.tick", "ui#title.watch_op"), "end.start")
    # off: the skip layer, the test input (also before the first play: a run that sends it at tick 0 never shows
    # the OP), the end of the timeline. Turning off (the toggle's change to false) hides the surfaces and stops the
    # music when a play had started (a skip at tick 0 sends no command; the gate reads `shown` before it is cleared).
    g.edge(g.merge("offAny", f"ui#{SKIP_UI}.skip", "input.opSkip", "end.tick"), "on.setFalse")
    g.cmp("isOn", "on.value", g.k(True))
    stop_m = g.when("mStopG", "isOn.false", "shown.value")
    g.edge("isOn.false", "shown.setFalse")

    g.node("mPlay", "atrium.music.play", channel=CHANNEL, cue=CUE, loop=False)
    g.edge(g.k(0), "mPlay.fadeIn")
    g.edge(start, "mPlay.trigger")
    g.node("mStop", "atrium.music.stop", channel=CHANNEL)
    g.edge(g.k(STOP_FADE), "mStop.fadeOut")
    g.edge(stop_m, "mStop.trigger")
    # watch again: the title's music stops in the tick the OP's starts (the music flow's own stop for the moment
    # `op` comes a tick later and finds the channel stopped)
    g.node("bgmStop", "atrium.music.stop", channel="bgm")
    g.edge(g.k(STOP_FADE), "bgmStop.fadeOut")
    g.edge("ui#title.watch_op", "bgmStop.trigger")
    g.counter("plays", initial=0)
    g.edge(start, "plays.increment")
    g.edge("plays.value", "world.opPlays")
    g.counter("stops", initial=0)
    g.edge(stop_m, "stops.increment")
    g.edge("stops.value", "world.opStops")
    g.node("now", "atrium.music.playing", channel=CHANNEL)
    g.edge("now.cue", "world.opMusic")
    return g


def gen_op_ui() -> Graph:
    """The OP's UI flow ui/project/sherefox-op/sherefox-op.xtflow (run by Atrium Script, ui.flowRuntime atrium): shown
    plays the timeline from its start, hidden stops it. (A logic graph cannot play a UI's timeline: the timeline node's
    `ui` is only valid in the global flow, XTAtrium 05 / 53 §53.6.1 rule 4.) The OP project's own flow also triggered
    its music as a sound cue; here the music is the logic graph's (a channel the skip can stop)."""
    g = Graph()
    g.node("life", "lifecycle")
    g.node("tl", "timeline", name=TIMELINE)
    g.edge("life.shown", "tl.play")
    g.edge("life.hidden", "tl.stop")
    return g
