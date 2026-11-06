# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Write the test recordings:

- tests/ch1_playthrough.atrec: click Ch.1 on the title, then click through every page and line of Ch.1 until the
  Ch.2 opening paper is on screen.
- tests/full_run.atrec: Ch.1 on the title, then every page and line of Ch.1, Ch.2 and Ch.3 up to the end card;
  a click on the end card (end_dismiss), Ch.3 from the title again and through it to the end card; Enter on the
  end card, then a click on the title's Ch.3 entry again (the same value as before: the chapter list reacts to
  every click, AT-040 `.emitted`), up to its opening paper.
- tests/lang_toggle.atrec: press the title's language toggle three times (zh -> en -> zh -> en), choose Ch.1, turn
  both pages of the opening paper, so the first vn line is shown in English.
- tests/settings.atrec: the title's 離開遊戲 (headless: no-op), then its 設定: English, 大字譯名 off, Esc closes it;
  Ch.1, and on its opening paper F1 opens the settings: 繁體中文, 大字譯名 on (and a click on 開 again, which sends
  nothing), Backspace closes it; Esc on the paper (no overlay open) opens it, a click on the dimmed screen closes it
  (tests/check_settings.py).
- tests/settings_display.atrec: the host's display.* as a window would write them (native 1920x1080, rendering
  1600x900, borderless; recorded like input, XTAtrium 09 §9.3), then 設定 and the 1280 x 720 option.

The click count per step comes from the data tables (steps, script), so the recording follows the data:
paper = 2 clicks (page 1 -> page 2 -> done), vn = one click per playable line (script.playable; the first line
is shown when the step begins, the click after the last line ends the step); investigate and board steps take the
shortest route of tests/gen_case.py (MINIMAL); warmup, debate and result steps the shortest sure way of
tests/gen_debate_play.py (minimal: observe until the debate ends, continue, the result scene's lose lines).

Usage (from the project root):
    uv run tests/gen_playthrough.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
GAME = "."   # the recording header names the game exactly as the check script passes it to --game (run from the repo root)

STEP = 0.016666666666666666
GAP = 8            # ticks between two clicks
SETTLE = 24        # ticks after a step change before its first click (show transition)
HOLD = {           # extra wait (ticks) before a click, so a frame can be inspected: (step id, click index) -> ticks
    ("TITLE", 0): 40,
    ("CH01_01", 2): 60,
}
END_WAIT = 90      # ticks to keep running after the last click (the Ch.2 paper settles)

# Pointer positions (1280x720 surface coordinates).
TITLE_CH = {1: (1000, 382), 2: (1000, 490), 3: (1000, 598)}   # entries btn-ch1..3: y 328-428, 428-528, 528-628
TITLE_SETTINGS = (924, 662)   # btn-settings: x 824-1024, y 640-684
TITLE_QUIT = (1132, 662)      # btn-quit: x 1032-1232
END_CARD = (640, 360)
KEY_ENTER = 40     # XtKey.Enter
KEY_ESC = 41       # XtKey.Escape
KEY_BACKSPACE = 42
KEY_F1 = 83
TITLE_LANG = (1150, 25)
# The settings sheet (dock 760x440 centred: 260,140; its page at 280,220): option rows of 152x34 chips from x 490.
SET_LANG = {0: (566, 447), 1: (726, 447)}      # lang-zh / lang-en: x 490-642 / 650-802, y 430-464
SET_SUB = {True: (566, 513), False: (726, 513)}  # sub-on / sub-off: y 496-530
SET_SCRIM = (120, 120)                          # the dimmed screen outside the sheet
SET_RES = [(568, 255), (732, 255)]              # res_options 0 / 1: x 490-646 / 654-810, y 236-270
PAPER_CLICK = (640, 400)
VN_CLICK = (640, 620)


def load(name: str):
    return json.loads((ROOT / "data" / f"{name}.json").read_text(encoding="utf-8"))


def playable(script, chapter: int, scene: str):
    return [r for r in script if r["chapter"] == chapter and r["scene"] == scene and r["playable"]]


def plan(chapter: int):
    """(step id, surface, clicks) for every step of the chapter."""
    steps = [s for s in load("steps") if s["chapter"] == chapter]
    script = load("script")
    out = []
    for s in steps:
        if s["kind"] == "paper":
            out.append((s["id"], "paper", 2))
        elif s["kind"] == "vn":
            out.append((s["id"], "vn", len(playable(script, chapter, s["scene"]))))
        else:
            out.append((s["id"], None, 0))
    return out


def click(ui: str, xy):
    x, y = xy
    return [[ui, "pd", x, y, 0, 1], [ui, "pu", x, y, 0]]


def key(ui: str, code: int):
    return [[ui, "kd", code, 0], [ui, "ku", code, 0]]


class Recording:
    def __init__(self) -> None:
        self.lines = [json.dumps({"atrec": 1, "step": STEP, "seed": 1, "game": GAME})]
        self.t = 0

    def at(self, dt: int, events) -> None:
        self.t += dt
        self.lines.append(json.dumps({"t": self.t, "u": events}, ensure_ascii=False))

    def signals(self, dt: int, writes) -> None:
        """Host signal writes of a tick (`w`: input.* and display.*, XTAtrium 02 §2.5, 09 §9.3)."""
        self.t += dt
        self.lines.append(json.dumps({"t": self.t, "w": writes}, ensure_ascii=False))

    def write(self, name: str, tail: int) -> int:
        ticks = self.t + tail + 1
        (TESTS / f"{name}.atrec").write_bytes(("\n".join(self.lines) + "\n").encode("utf-8"))
        print(f"wrote tests/{name}.atrec ({len(self.lines) - 1} inputs, {ticks} ticks)")
        return ticks


def case_step(r: "Recording", step_id: str) -> bool:
    """Investigate / board steps: their inputs (tests/gen_case.py MINIMAL); True when the step was one."""
    step = next(s for s in load("steps") if s["id"] == step_id)
    if step["kind"] in ("warmup", "debate", "result"):
        import gen_debate_play   # imports this module
        gen_debate_play.minimal(r, step["kind"], step["chapter"])
        return True
    if step["kind"] not in ("investigate", "board"):
        return False
    import gen_case   # imports this module
    gen_case.minimal(r, step["kind"], step["chapter"])
    return True


def ch1_playthrough(lang: str = "zh-TW") -> int:
    """`lang`: the board's reason rows are found from the text of that language (tests/gen_case.reason_xy)."""
    import gen_case
    gen_case.MINIMAL_LANG = lang
    r = Recording()
    r.at(HOLD[("TITLE", 0)], click("title", TITLE_CH[1]))
    for step_id, ui, clicks in plan(1):
        if ui is None:
            if not case_step(r, step_id):
                r.t += 2   # stub: done one tick after it begins
            continue
        for k in range(clicks):
            wait = (SETTLE if k == 0 else GAP) + HOLD.get((step_id, k), 0)
            r.at(wait, click(ui, PAPER_CLICK if ui == "paper" else VN_CLICK))
    return r.write("ch1_playthrough", END_WAIT)


def play_chapters(r: Recording, chapters) -> None:
    for chapter in chapters:
        for step_id, ui, clicks in plan(chapter):
            if ui is None:
                if not case_step(r, step_id):
                    r.t += 2
                continue
            for k in range(clicks):
                r.at(SETTLE if k == 0 else GAP, click(ui, PAPER_CLICK if ui == "paper" else VN_CLICK))


def full_run() -> int:
    import gen_case
    gen_case.MINIMAL_LANG = "zh-TW"
    r = Recording()
    r.at(40, click("title", TITLE_CH[1]))
    play_chapters(r, (1, 2, 3))
    r.at(90, click("title", END_CARD))                     # end card -> end_dismiss
    r.at(SETTLE, click("title", TITLE_CH[3]))              # the chapter list works again
    play_chapters(r, (3,))
    r.at(90, [["title", "kd", KEY_ENTER, 0], ["title", "ku", KEY_ENTER, 0]])   # Enter on the end card
    r.at(SETTLE, click("title", TITLE_CH[3]))
    return r.write("full_run", 60)


def lang_toggle() -> int:
    r = Recording()
    r.at(40, click("title", TITLE_LANG))
    r.at(GAP, click("title", TITLE_LANG))
    r.at(GAP, click("title", TITLE_LANG))
    r.at(SETTLE, click("title", TITLE_CH[1]))
    r.at(SETTLE, click("paper", PAPER_CLICK))
    r.at(GAP, click("paper", PAPER_CLICK))
    return r.write("lang_toggle", 60)


def settings() -> int:
    r = Recording()
    r.at(30, click("title", TITLE_QUIT))              # 離開遊戲: atrium.app.quit, a no-op headless
    r.at(GAP, click("title", TITLE_SETTINGS))         # 設定
    r.at(SETTLE, click("settings", SET_LANG[1]))      # English
    r.at(GAP, click("settings", SET_SUB[False]))      # 大字譯名 off
    r.at(GAP, key("settings", KEY_ESC))               # Esc closes it
    r.at(SETTLE, click("title", TITLE_CH[1]))         # Ch.1: its opening paper
    r.at(SETTLE, key("paper", KEY_F1))                # F1 in the game opens it
    r.at(SETTLE, click("settings", SET_LANG[0]))      # 繁體中文
    r.at(GAP, click("settings", SET_SUB[True]))       # 大字譯名 on
    r.at(GAP, click("settings", SET_SUB[True]))       # 開 again: already on, sends nothing
    r.at(GAP, key("settings", KEY_BACKSPACE))         # Backspace closes it
    r.at(SETTLE, key("paper", KEY_ESC))               # Esc with no overlay open opens it
    r.at(SETTLE, click("settings", SET_SCRIM))        # a click on the dimmed screen closes it
    return r.write("settings", 30)


DISPLAY = {"nativeWidth": 1920, "nativeHeight": 1080, "width": 1600, "height": 900, "windowWidth": 1600,
           "windowHeight": 900, "mode": "borderless"}


def settings_display() -> int:
    r = Recording()
    r.signals(5, [[f"display.{k}", v] for k, v in DISPLAY.items()] + [["display.changed", "p"]])
    r.at(25, click("title", TITLE_SETTINGS))
    r.at(SETTLE, click("settings", SET_RES[1]))       # 1280 x 720
    return r.write("settings_display", 30)


RECORDINGS = {"ch1_playthrough": ch1_playthrough, "full_run": full_run, "lang_toggle": lang_toggle,
              "settings": settings, "settings_display": settings_display}


def main() -> int:
    for fn in RECORDINGS.values():
        fn()
    return 0


if __name__ == "__main__":
    sys.exit(main())
