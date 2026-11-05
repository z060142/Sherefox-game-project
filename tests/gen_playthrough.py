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
GAME = ROOT.as_posix()   # the recording header names the game exactly as the check script passes it to --game

STEP = 0.016666666666666666
GAP = 8            # ticks between two clicks
SETTLE = 24        # ticks after a step change before its first click (show transition)
HOLD = {           # extra wait (ticks) before a click, so a frame can be inspected: (step id, click index) -> ticks
    ("TITLE", 0): 40,
    ("CH01_01", 2): 60,
}
END_WAIT = 90      # ticks to keep running after the last click (the Ch.2 paper settles)

# Pointer positions (1280x720 surface coordinates).
TITLE_CH = {1: (1000, 382), 2: (1000, 490), 3: (1000, 598)}   # entries btn-ch1..3: y 328-436, 436-544, 544-652
END_CARD = (640, 360)
KEY_ENTER = 40     # XtKey.Enter
TITLE_LANG = (1150, 25)
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


class Recording:
    def __init__(self) -> None:
        self.lines = [json.dumps({"atrec": 1, "step": STEP, "seed": 1, "game": GAME})]
        self.t = 0

    def at(self, dt: int, events) -> None:
        self.t += dt
        self.lines.append(json.dumps({"t": self.t, "u": events}, ensure_ascii=False))

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


RECORDINGS = {"ch1_playthrough": ch1_playthrough, "full_run": full_run, "lang_toggle": lang_toggle}


def main() -> int:
    for fn in RECORDINGS.values():
        fn()
    return 0


if __name__ == "__main__":
    sys.exit(main())
