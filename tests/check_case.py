# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Replay the investigation / clue-board recordings (tests/gen_case.py) headless and check the port trace, the list
ports (their JSON writes in the port log) and the collections at the end (--dump), including the debate engine's
board input against the reference model's board for the same route (ref/: fixtures, rules.link_kind; the layout of
docs/debate-engine.md §2.2, as tests/debate_routes.py board_layout).

Usage (from the project root):
    uv run tests/check_case.py [--frames DIR]

With --frames DIR it also writes PNG screenshots: investigate (hotspots, a card popup), the evidence book, the board
with chains and links, and the invalid link before the bounce.
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
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "ref" / "src"))
import check_playthrough as cp  # noqa: E402
import gen_case  # noqa: E402
import gen_playthrough  # noqa: E402
from sherefox_ref.fixtures import ch1_board, ch1_case, ch2_case  # noqa: E402
from sherefox_ref.model import Board  # noqa: E402
from sherefox_ref.rules import SOLID_LINK, SOPH_LINK, link_kind  # noqa: E402

SLOTS = 24


def board_layout(case, board: Board):
    """debBoard / debBoardOk / debBoardLink for a ref board (docs/debate-engine.md §2.2; tests/debate_routes.py)."""
    cards, ok, links, placed = ["-"] * SLOTS, [1] * SLOTS, [0] * SLOTS, set()
    for c, chain in enumerate(board.chains):
        for i, cid in enumerate(chain):
            s = 5 * c + i
            cards[s], ok[s] = cid, int(case.card(cid).reason_correct)
            placed.add(cid)
            if i + 1 < len(chain):
                k = link_kind(case.card(cid), case.card(chain[i + 1]))
                links[s] = 1 if k == SOLID_LINK else 2 if k == SOPH_LINK else 0
    for j, cid in enumerate(c for c in board.loose if c not in placed):
        cards[15 + j], ok[15 + j] = cid, int(case.card(cid).reason_correct)
    return cards, ok, links


def ch2_route_case():
    """ch2_case (E02_01, E02_02, E02_07 appraised) with E02_04's reason wrong, as in the recording."""
    from dataclasses import replace
    case = ch2_case()
    return replace(case, cards=tuple(replace(c, reason_correct=False) if c.id == "E02_04" else c for c in case.cards))


def run(name: str, ticks: int, frames: Path | None):
    dump = Path(tempfile.mkdtemp()) / "dump.json"
    args = [str(cp.EXE), "run", "--game", gen_playthrough.GAME, "--replay", str(ROOT / "tests" / f"{name}.atrec"),
            "--ticks", str(ticks), "--ports", "--dump", str(dump)]
    if frames:
        args += ["--ui-frames", str(frames)]
    env = dict(os.environ, XTATRIUM_XTFRAME_DIR=cp.XTFRAME)
    old_cp = None
    if os.name == "nt":
        import ctypes
        old_cp = ctypes.windll.kernel32.GetConsoleOutputCP()
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    try:
        p = subprocess.run(args, capture_output=True, env=env)
    finally:
        if old_cp:
            ctypes.windll.kernel32.SetConsoleOutputCP(old_cp)
    out = p.stdout.decode("utf-8").replace("\r\n", "\n")
    err = p.stderr.decode("utf-8").replace("\r\n", "\n")
    if p.returncode != 0:
        raise SystemExit(f"error: xtatrium run exited {p.returncode}\n{err}")
    events = []
    for raw in out.split("\n"):
        m = cp.LINE.match(raw)
        if m:
            events.append((-1 if m.group(1) == "load" else int(m.group(1)), m.group(2), m.group(3)))
        elif raw and events:
            t, kind, rest = events[-1]
            events[-1] = (t, kind, rest + "\n" + raw)
    colls = json.loads(dump.read_text(encoding="utf-8"))["collections"]
    shutil.rmtree(dump.parent, ignore_errors=True)
    return events, err, colls


def lists(events, port: str) -> list[tuple[int, list]]:
    """Every JSON write of a list port ('board document.links'), in order."""
    out = []
    for t, kind, rest in events:
        if kind == "write" and rest.startswith(port + " "):
            out.append((t, json.loads(json.loads(rest[len(port) + 1:]))))
    return out


def items(colls, name):
    c = colls.get(name, {})
    return c.get("items", [e["key"] for e in c.get("entries", [])])


def common(fail: cp.Failures, label: str, err: str, tr: cp.Trace) -> None:
    for line in err.splitlines():
        fail.check(not line.startswith(("warning:", "error:")), f"{label}: stderr: {line}")


def check_board_input(fail, label, colls, case, board) -> None:
    cards, ok, links = board_layout(case, board)
    fail.check(items(colls, "debBoard") == cards, f"{label}: debBoard {items(colls, 'debBoard')} != {cards}")
    fail.check(items(colls, "debBoardOk") == ok, f"{label}: debBoardOk {items(colls, 'debBoardOk')} != {ok}")
    fail.check(items(colls, "debBoardLink") == links,
               f"{label}: debBoardLink {items(colls, 'debBoardLink')} != {links}")


def remarks(tr: cp.Trace) -> list:
    """Board remarks in order (the first one, when the board step begins, is empty)."""
    return [ports.get("board.remark") for t, ports, vis, ch in tr.ticks if ch.get("board.remark_seq", 0) != 0]


def check_ch1(fail: cp.Failures, frames: Path | None) -> None:
    label = "ch1_case"
    ticks = gen_case.ch1()
    events, err, colls = run(label, ticks, frames)
    tr = cp.Trace(events)
    common(fail, label, err, tr)
    s = cp.strings("zh-TW")
    spots = lists(events, "investigate document.spots")
    fail.check(bool(spots) and len(spots[0][1]) == 10, f"{label}: first hotspot list {spots[:1]}")
    fail.check(bool(spots) and all(x["state"] == 1 for x in spots[-1][1]), f"{label}: not every spot visited")
    hs = {h["id"]: h for h in gen_case.load("hotspots")}
    fail.check(bool(spots) and [x["type"] for x in spots[0][1]] ==
               [{"inspect": 0, "evidence": 1, "testimony": 2}[hs[x["id"]]["type"]] for x in spots[0][1]],
               f"{label}: spot types")
    kinds = [ch["investigate.popup_kind"] for _, _, _, ch in tr.ticks if ch.get("investigate.popup_kind", 0) != 0]
    fail.check(kinds == [2] * 7 + [1] * 3, f"{label}: popup kinds {kinds}")
    fail.check(tr.last("investigate.ticks_max") == 0 and tr.last("investigate.appraise_left") == -1,
               f"{label}: Ch.1 ticks / appraisals not hidden")
    hints = [p.get("investigate.hint") for _, p, _, ch in tr.ticks if ch.get("investigate.hint_seq", 0) != 0]
    fail.check(hints == [s["ART_OPEN_CH01"], s["SHF_C1_IDLE"]], f"{label}: hints {hints}")
    fail.check(sorted(items(colls, "held")) == [f"E01_0{i}" for i in range(1, 8)], f"{label}: held")
    fail.check(items(colls, "oppHand") == [], f"{label}: opponent hand {items(colls, 'oppHand')} (Ch.1: none)")
    drawer = lists(events, "board document.drawer")
    fail.check(bool(drawer) and [d["id"] for d in drawer[-1][1]] == [f"E01_0{i}" for i in range(1, 7)],
               f"{label}: drawer {drawer[-1:] if drawer else None}")
    fail.check(bool(drawer) and all(d["reason_set"] for d in drawer[-1][1]), f"{label}: drawer reasons")
    slots = lists(events, "board document.slots")
    fail.check(bool(slots) and [(x["chain"], x["pos"], x["id"]) for x in slots[-1][1]] ==
               [(0, 0, "E01_01"), (0, 1, "E01_04")], f"{label}: slots {slots[-1:] if slots else None}")
    links = lists(events, "board document.links")
    fail.check(bool(links) and links[-1][1] == [{"chain": 0, "pos": 0, "kind": 1}], f"{label}: links")
    chains = lists(events, "board document.chain_info")
    fail.check(bool(chains) and chains[-1][1][0] == {"chain": 0, "cards": 2, "solid": 1, "soph": 0, "dmg": 21},
               f"{label}: chain plate {chains[-1:] if chains else None}")
    fail.check(remarks(tr)[-1:] == [s["ART_SOLID"]], f"{label}: remarks {remarks(tr)}")
    check_board_input(fail, label, colls, ch1_case(), ch1_board())
    fail.check(items(colls, "golden") == [], f"{label}: golden")
    fail.check(cp.main_visible(tr.ticks[-1][2]) == {"debate"}, f"{label}: after the board: {tr.ticks[-1][2]}")
    print(f"{label}: 10 spots, {len(kinds)} popups, chain E01_01-E01_04 solid, debBoard matches ref ch1_board"
          if not fail.items else f"{label}: done")


def check_ch2(fail: cp.Failures, frames: Path | None) -> None:
    label = "ch2_case"
    ticks = gen_case.ch2()
    events, err, colls = run(label, ticks, frames)
    tr = cp.Trace(events)
    common(fail, label, err, tr)
    s = cp.strings("zh-TW")
    tk = [ch["investigate.ticks"] for _, _, _, ch in tr.ticks if "investigate.ticks" in ch]
    fail.check(tk[-8:] == [8, 7, 6, 5, 4, 3, 2, 1], f"{label}: ticks {tk}")
    kinds = [ch["investigate.popup_kind"] for _, _, _, ch in tr.ticks if ch.get("investigate.popup_kind", 0) != 0]
    fail.check(kinds == [2, 2, 2, 3, 2, 2, 1], f"{label}: popup kinds {kinds}")
    hints = [p.get("investigate.hint") for _, p, _, ch in tr.ticks if ch.get("investigate.hint_seq", 0) != 0]
    want = [s["ART_OPEN_CH02"], s["ART_FOUND_KEY"], s["ART_TIME_LOW"], s["ART_APPR_MECH_DONE"], s["ART_REMAIN_FEW"]]
    fail.check(hints == want, f"{label}: hints {hints}")
    fail.check(any("evbook" in v for _, _, v, _ in tr.ticks), f"{label}: the evidence book was never shown")
    book = lists(events, "evbook document.cards")
    e01 = [c for _, rows in book for c in rows if c["id"] == "E02_01"]
    fail.check([c["appraised"] for c in e01][:1] == [False] and e01[-1:] and e01[-1]["appraised"],
               f"{label}: E02_01 in the book {e01}")
    appr = [ch["investigate.appraise_left"] for _, _, _, ch in tr.ticks if "investigate.appraise_left" in ch]
    fail.check(appr[-4:] == [3, 2, 1, 0], f"{label}: appraisals {appr}")
    fail.check(items(colls, "oppHand") == ["E02_05"], f"{label}: opponent hand {items(colls, 'oppHand')}")
    fail.check(sorted(items(colls, "appraised")) == ["E02_01", "E02_02", "E02_07"], f"{label}: appraised")
    want_r = [s["ART_APPR_MECH_DONE"], s["ART_APPR_MECH_DONE"], s["ART_SOLID"], s["ART_SOPH_1"], s["ART_INVALID"]]
    fail.check(remarks(tr)[1:] == want_r, f"{label}: remarks {remarks(tr)}")
    links = lists(events, "board document.links")
    fail.check(any(any(x["kind"] == 3 for x in rows) for _, rows in links), f"{label}: no invalid link shown")
    fail.check(bool(links) and links[-1][1] == [{"chain": 0, "pos": 0, "kind": 1}, {"chain": 0, "pos": 1, "kind": 2},
                                                {"chain": 1, "pos": 0, "kind": 1}, {"chain": 1, "pos": 1, "kind": 1}],
               f"{label}: links {links[-1:] if links else None}")
    chains = lists(events, "board document.chain_info")
    fail.check(bool(chains) and chains[-1][1][:2] == [{"chain": 0, "cards": 3, "solid": 1, "soph": 1, "dmg": 32.2},
                                                      {"chain": 1, "cards": 3, "solid": 2, "soph": 0, "dmg": 28}],
               f"{label}: chain plates {chains[-1:] if chains else None}")
    board = Board(chains=(("E02_03", "E02_02", "E02_04"), ("E02_06", "E02_01", "E02_07")))
    check_board_input(fail, label, colls, ch2_route_case(), board)
    fail.check(items(colls, "golden") == ["G-01"], f"{label}: golden {items(colls, 'golden')}")
    print(f"{label}: ticks 8->1, E02_01 appraised in the book, E02_05 to the opponent's hand, sophistry and invalid "
          f"links, debBoard matches the ref board, G-01 earned" if not fail.items else f"{label}: done")


SHOTS = {
    "ch1_case": [("inv_ch1", "investigate", 770), ("board_ch1", "board", 960)],
    "ch2_case": [("inv_ch2", "investigate", 440), ("popup_card", "investigate", 266), ("evbook", "evbook", 630),
                 ("board_invalid", "board", 885), ("board_ch2", "board", 972)],
}


def main() -> int:
    frames = None
    if "--frames" in sys.argv:
        frames = Path(sys.argv[sys.argv.index("--frames") + 1]).resolve()
        frames.mkdir(parents=True, exist_ok=True)
    fail = cp.Failures()
    for name, fn in (("ch1_case", check_ch1), ("ch2_case", check_ch2)):
        raw = frames / "_ppm" if frames else None
        if raw:
            shutil.rmtree(raw, ignore_errors=True)
            raw.mkdir()
        fn(fail, raw)
        if raw:
            for png, ui, t in SHOTS[name]:
                f = cp.latest_frame(raw, ui, t + 1)
                fail.check(f is not None, f"frames: no {ui} frame before tick {t}")
                if f:
                    cp.ppm_to_png(f, frames / f"{png}.png")
                    print(f"frames: {png}.png <- {f.name}")
            shutil.rmtree(raw, ignore_errors=True)
    for f in fail.items:
        print("FAIL " + f)
    print("ok" if not fail.items else f"{len(fail.items)} failure(s)")
    return 0 if not fail.items else 1


if __name__ == "__main__":
    sys.exit(main())
