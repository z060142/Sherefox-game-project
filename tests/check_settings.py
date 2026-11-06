# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Check the settings overlay (docs/ui-contracts.md settings, title; docs/flows.md §4.1, §4.11) headless.

Usage (from the project root):
    uv run tests/check_settings.py

It regenerates tests/settings.atrec (tests/gen_playthrough.py settings) and replays it with --ports:

1. The title's 離開遊戲 emits title.quit and the run goes on (atrium.app.quit is a no-op headless); main's flow
   feeds an atrium.app.quit node from it.
2. The title's 設定 shows the settings surface (modal, above everything but cutin in game.json); Esc closes it.
   On Ch.1's opening paper F1 opens it, Backspace closes it; Esc with no overlay open opens it, a click on the
   dimmed screen closes it. The paper stays on page 1 throughout (the keys go to the overlay or open it).
3. Text language: picking English / 繁體中文 flips title.lang_en (the title's switch, one state) and
   settings.lang_sel, and settings.current follows the language (UI_SET_RES_CURRENT, {w} x {h} = 0 x 0 headless).
4. 大字譯名: sub_on goes false, then true; a click on 開 while it is on sends nothing. debate_ui reads world.cutinSub,
   and its beat gate reads world.settingsShown (the debate pauses while settings is open, as with the notes).
5. res_options: every write is the auto option only (UI_SET_RES_AUTO in the language of the moment, selected):
   display.nativeWidth/Height are 0 headless, so no preset fits.
6. settings_display: with display.* as a window writes them (native 1920x1080, rendering 1600x900, borderless):
   res_options = auto and the presets up to 1920 x 1080, auto selected; mode_sel 1; current 1600 x 900; picking
   1280 x 720 moves `sel` to it (atrium.display.set itself is a no-op headless).
No warning or error on stderr. The checks write no files besides the regenerated recordings.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import check_playthrough as cp  # noqa: E402
import gen_playthrough  # noqa: E402
from xt_cli import compile_game  # noqa: E402


def lists(events, port: str) -> list[tuple[int, list]]:
    out = []
    for t, kind, rest in events:
        if kind == "write" and rest.startswith(port + " "):
            out.append((t, json.loads(json.loads(rest[len(port) + 1:]))))
    return out


def check_static(fail: cp.Failures) -> None:
    game = json.loads((ROOT / "game.json").read_text(encoding="utf-8"))
    fail.check(game.get("display") == {"mode": "windowed", "resolution": "auto"}, f"game.json display {game.get('display')}")
    order = [s["ui"] for s in game["ui"]["surfaces"]]
    surf = next((s for s in game["ui"]["surfaces"] if s["ui"] == "settings"), {})
    fail.check(surf.get("modal") is True and surf.get("visible") is False, f"game.json settings surface {surf}")
    fail.check("settings" in order and order.index("settings") == order.index("cutin") - 1,
               f"game.json surfaces: settings must be right below cutin ({order})")
    fail.check("flows/settings.xtflow" in game["flows"], "game.json flows: no settings")
    main = json.loads((ROOT / "flows" / "main.xtflow").read_text(encoding="utf-8"))
    quits = {n["id"] for n in main["nodes"] if n["type"] == "atrium.app.quit"}
    fail.check(any(e["from"] == "ui#title.quit" and e["to"].split(".")[0] in quits for e in main["edges"]),
               "main: ui#title.quit does not reach an atrium.app.quit node")
    deb = json.loads((ROOT / "flows" / "debate_ui.xtflow").read_text(encoding="utf-8"))
    fail.check(any(e["from"] == "world.cutinSub" for e in deb["edges"]), "debate_ui does not read world.cutinSub")
    # the debate pauses while settings is open, as with the notes: main writes world.settingsShown, and it reaches
    # the expression that gates debate_ui's beat
    fail.check(any(e["from"] == "settingsVis.out" and e["to"] == "world.settingsShown" for e in main["edges"]),
               "main does not write world.settingsShown")
    beat = next((n for n in deb["nodes"] if n["id"] == "beatOk"), {})
    fed = {e["to"].split(".")[0] for e in deb["edges"] if e["from"] == "world.settingsShown"}
    reach = {e["to"].split(".")[0] for e in deb["edges"] if e["from"].split(".")[0] in fed}
    fail.check("settingsOnN" in beat.get("params", {}).get("expr", "") and "beatOk" in reach,
               "debate_ui: the beat gate does not read world.settingsShown")


def check_display(fail: cp.Failures, zh: dict) -> None:
    label = "settings_display"
    ticks = gen_playthrough.settings_display()
    events, err = cp.run("settings_display", ticks, None, None)
    for line in err.splitlines():
        fail.check(not line.startswith(("warning:", "error:")), f"{label}: stderr: {line}")
    tr = cp.Trace(events)
    d = gen_playthrough.DISPLAY
    fail.check(tr.last("settings.mode_sel") == 1, f"{label}: mode_sel {tr.last('settings.mode_sel')}")
    want = zh["UI_SET_RES_CURRENT"].replace("{w}", str(d["width"])).replace("{h}", str(d["height"]))
    fail.check(tr.last("settings.current") == want, f"{label}: current {tr.last('settings.current')!r} != {want!r}")
    writes = [rows for _, rows in lists(events, "settings document.res_options")]
    labels = [zh["UI_SET_RES_AUTO"], "1280 × 720", "1600 × 900", "1920 × 1080"]
    fail.check(len(writes) >= 3, f"{label}: res_options written {len(writes)} time(s)")
    if len(writes) >= 3:
        fail.check([r["label"] for r in writes[-2]] == labels and [r["sel"] for r in writes[-2]] == [True, False, False, False],
                   f"{label}: res_options after display.changed {writes[-2]}")
        fail.check([r["label"] for r in writes[-1]] == labels and [r["sel"] for r in writes[-1]] == [False, True, False, False],
                   f"{label}: res_options after picking 1280 x 720 {writes[-1]}")
    if not fail.items:
        print(f"{label}: res_options {labels}, sel auto -> 1280 x 720; mode_sel 1; current {want}")


def main() -> int:
    compile_game()
    fail = cp.Failures()
    check_static(fail)
    label = "settings"
    ticks = gen_playthrough.settings()
    events, err = cp.run("settings", ticks, None, None)
    for line in err.splitlines():
        fail.check(not line.startswith(("warning:", "error:")), f"{label}: stderr: {line}")
    tr = cp.Trace(events)
    zh, en = cp.strings("zh-TW"), cp.strings("en")

    emits = [(t, k[5:]) for t, _, _, ch in tr.ticks for k in ch if k.startswith("emit:")]
    quit_t = [t for t, k in emits if k == "title.quit"]
    fail.check(len(quit_t) == 1, f"{label}: title.quit emitted at {quit_t}")
    fail.check(bool(quit_t) and tr.ticks[-1][0] > quit_t[0] + 100,
               f"{label}: the run stopped after the quit (t={tr.ticks[-1][0]}; quit is a no-op headless)")

    # visibility: open (title), close (Esc), open (F1 on the paper), close (Backspace), open (Esc), close (scrim)
    shown, flips = False, []
    for t, _, visible, _ in tr.ticks:
        if ("settings" in visible) != shown:
            shown = not shown
            flips.append(shown)
    fail.check(flips == [True, False, True, False, True, False], f"{label}: settings visibility changes {flips}")
    opens = [k for _, k in emits if k in ("title.open_settings", "paper.settings")]
    fail.check(opens == ["title.open_settings", "paper.settings", "paper.settings"], f"{label}: opened by {opens}")
    closes = [t for t, k in emits if k == "settings.close"]
    fail.check(len(closes) == 3, f"{label}: settings.close at {closes}")
    paper_pages = {ports.get("paper.page") for _, ports, visible, _ in tr.ticks if "paper" in visible}
    fail.check(paper_pages == {1}, f"{label}: paper pages while it is shown {paper_pages}")
    fail.check(cp.main_visible(tr.ticks[-1][2]) == {"paper"}, f"{label}: main screens at the end {tr.ticks[-1][2]}")

    # language: one switch (the title's) driven from the settings screen
    lang_en = [ch["title.lang_en"] for _, _, _, ch in tr.ticks if "title.lang_en" in ch]
    fail.check(lang_en[-2:] == [True, False], f"{label}: title.lang_en changes {lang_en}")
    lang_sel = [ch["settings.lang_sel"] for _, _, _, ch in tr.ticks if "settings.lang_sel" in ch]
    fail.check(lang_sel == [0, 1, 0], f"{label}: settings.lang_sel changes {lang_sel}")
    cur = [ch["settings.current"] for _, _, _, ch in tr.ticks if "settings.current" in ch]
    want = [s["UI_SET_RES_CURRENT"].replace("{w}", "0").replace("{h}", "0") for s in (zh, en, zh)]
    fail.check(cur == want, f"{label}: settings.current {cur} != {want}")

    # 大字譯名
    sub = [ch["settings.sub_on"] for _, _, _, ch in tr.ticks if "settings.sub_on" in ch]
    fail.check(sub == [True, False, True], f"{label}: settings.sub_on changes {sub}")
    toggles = [t for t, k in emits if k == "settings.toggle_sub"]
    fail.check(len(toggles) == 2, f"{label}: toggle_sub at {toggles} (the click on 開 while on must send nothing)")

    # res_options: only auto when display.native* are 0 (headless)
    writes = lists(events, "settings document.res_options")
    labels = [[r["label"] for r in rows] for _, rows in writes]
    fail.check(len(writes) >= 3, f"{label}: res_options written {len(writes)} time(s)")
    fail.check(all(len(rows) == 1 and rows[0]["sel"] is True for _, rows in writes),
               f"{label}: res_options must be the selected auto option only: {writes}")
    want_l = [[zh["UI_SET_RES_AUTO"]], [en["UI_SET_RES_AUTO"]], [zh["UI_SET_RES_AUTO"]]]
    dedup = [l for i, l in enumerate(labels) if i == 0 or l != labels[i - 1]]
    fail.check(dedup == want_l, f"{label}: res_options labels {dedup} != {want_l}")

    check_display(fail, zh)

    if not fail.items:
        print(f"{label}: quit emitted (no-op headless); opened by {', '.join(opens)}; closed by Esc, Backspace, "
              f"the dimmed screen; lang_sel {lang_sel}; sub_on {sub}; res_options {dedup}")
    for f in fail.items:
        print("FAIL " + f)
    print("ok" if not fail.items else f"{len(fail.items)} failure(s)")
    return 0 if not fail.items else 1


if __name__ == "__main__":
    sys.exit(main())
