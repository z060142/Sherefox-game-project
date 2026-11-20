# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Text-fit review screenshots of the D01 text boxes: not a pass/fail check.

For every kind of box that shows D01 text it renders the longest strings that can appear there, so a writer's longer
text can be checked box by box without playing every route:

1. A base run of tests/d1_m3.atrec (title, S01, S02 / S03, the warm-up, all 26 hotspots, the evidence list with two
   appraisals and E01's private views, the notes page, the carry screen with Ask Arthur, route A's debate, S07's lines,
   S08, the result screen, S09, S10, S11; tests/check_d1_m3.py regenerates it) on a copy of the game
   (tests/d1text_harness: gen_d1_play's route A harness, deleted at the end) with --ports. Each box (BOXES) names its
   ports; every string key whose text a port shows for a while, on a visible screen, is a slot (key, tick).
2. The candidates of a box are the string keys that can appear in it (BOXES, from the generators' key patterns and
   the script table), ranked by width (a CJK character 1, an ASCII one 0.5; placeholders filled with sample values).
   The top --top of them (and every candidate of a small box) are shot: a candidate the base run shows itself is shot
   at its own tick; the others are written into the harness's string table in place of a slot key of the same box
   (pass 1, 2, ...: one candidate per slot per pass), and shot at that slot's tick. Text length changes no timing, so
   the base run's ticks hold.
3. Every shot is copied to DIR/<lang>/<box>/<nn>_<key>_<len>.png; DIR/<lang>/index.tsv lists box, key, width,
   characters, slot key and tick.

The newspapers are not here: S09's column count is fixed at build time from flowTextLen (tests/check_d1_full.py --shots
shoots the three versions; S01 tests/check_d1_story.py --shots). The cut-in subtitles show English only. The claim and
card labels (claim picker, confirm row, chains) are not part of a text rewrite: tests/shots_d1_labels.py. A template's
placeholders get sample values (fill); the carry confirm's {list} names every item, the longest list there can be.

Usage (from the project root, after `xtatrium pack --game .` and a run of tests/check_d1_m3.py):
    uv run tests/shots_d1_text.py DIR [--lang zh-TW|en] [--top N] [--boxes a,b,...] [--list]
--list prints each box's ranked candidates and slots and shoots nothing.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(ROOT / "tools"))
import check_d1_play as cd  # noqa: E402
import check_playthrough as cp  # noqa: E402
import gen_d1_play as gd  # noqa: E402
from sherefox_ref.v2 import warmup as WARM  # noqa: E402
from tempwatch import TempWatch  # noqa: E402
from xt_cli import EXE, XTFRAME, compile_game  # noqa: E402

HARNESS = TESTS / "d1text_harness"
REC = "d1_m3"
SETTLE = 24          # ticks after a text appears before it is shot (fades and the standees' 420 ms are over)
QUIET = 150          # ticks a calligraphy cut-in or a stamp covers the screen
PH = re.compile(r"\{([a-z_0-9]+)\}")


def load_strings(lang: str) -> dict[str, str]:
    with open(ROOT / "strings" / f"{lang}.csv", encoding="utf-8-sig", newline="") as f:
        return {r[0]: r[1] for r in list(csv.reader(f))[1:]}


def table(name: str) -> list[dict]:
    p = ROOT / "data" / "flow" / f"{name}.json"
    if not p.exists():
        p = ROOT / "data" / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8"))


def width(text: str) -> float:
    return sum(0.5 if ord(c) < 0x2000 else 1.0 for c in text)


# ---------------------------------------------------------------------------------------------------- the boxes

def script_rows(style: int) -> list[str]:
    """The vn's D01 lines with this staging style (0 dialogue, 1 narration / notes), every scene a D01 vn plays."""
    return [r["id"] for r in table("script") if r["chapter"] == 101 and r["playable"] and r["style"] == style
            and r["scene"] != "S04" and (r["scene"] != "S07" or r["cue"])]


def keys_like(strings: dict, *pats: str) -> list[str]:
    rx = [re.compile(p + "$") for p in pats]
    return [k for k in strings if any(r.match(k) for r in rx)]


def boxes(S: dict) -> list[dict]:
    """Each box: id, title, ports (ui.port, or ui.port[field] for a list), the candidate keys, and for the vn the
    staging style the slot must have."""
    points = [f"SCR_D01_S04_{p['line']}" for p in WARM.PLAY["points"]]
    items = [r["desc"] for r in table("d1iItem")]
    claims = [r["label"] for r in table("d1iClaim")]
    cards = keys_like(S, r"CARD_D01_[A-Z]+\d+")
    return [
        {"id": "vn_dialogue", "title": "vn dialogue box (S02, S03, S07 pre / outro, S08)", "ports": ["vn.line"],
         "style": 0, "cands": script_rows(0)},
        {"id": "vn_note", "title": "vn narration / notes box (style 1: S03 L001-L002, S10)", "ports": ["vn.line"],
         "style": 1, "cands": script_rows(1)},
        {"id": "warm_point", "title": "warm-up point box", "ports": ["d1warm.point"], "cands": points},
        {"id": "warm_obs", "title": "warm-up observation cards", "ports": ["d1warm.obs1", "d1warm.obs2", "d1warm.obs3"],
         "cands": keys_like(S, r"OBS_D01_W\d")},
        {"id": "warm_line", "title": "warm-up dialogue box", "ports": ["d1warm.line"],
         "cands": [k for k in keys_like(S, r"SCR_D01_S04_L\d{3}[A-I]?") if k not in points]},
        {"id": "inv_desc", "title": "hotspot note: description", "ports": ["d1inv.popup_body"],
         "cands": keys_like(S, r"HS_D01_\d+_DESC"), "cond": {"d1inv.popup_on": True}, "settle": 8},
        {"id": "inv_art", "title": "hotspot note: Arthur's comment", "ports": ["d1inv.popup_line"],
         "cands": keys_like(S, r"HS_D01_\d+_ART"), "cond": {"d1inv.popup_on": True}, "settle": 8},
        {"id": "book_desc", "title": "evidence list: description", "ports": ["d1book.sel_desc"],
         "cands": [i for i in items if i.startswith(("E_", "C_"))],
         "cond": {"d1book.tab": 0}},
        {"id": "book_result", "title": "evidence list: appraisal result", "ports": ["d1book.sel_result"],
         "cands": keys_like(S, r"APR_D01_\d+_RESULT"), "cond": {"d1book.tab": 0}},
        {"id": "book_remark", "title": "evidence list: Arthur's appraisal line", "ports": ["d1book.remark"],
         "cands": keys_like(S, r"APR_D01_\d+_LINE"), "cond": {"d1book.tab": 0}, "settle": 8},
        {"id": "book_opts", "title": "evidence list: private-view rows", "ports": ["d1book.opts[label]"],
         "cands": claims, "cond": {"d1book.tab": 0}},
        {"id": "book_pnotes", "title": "people notes", "ports": ["d1book.pnotes[text]"],
         "cands": [i for i in items if i.startswith(("PN_", "OBS_"))], "cond": {"d1book.tab": 1}},
        {"id": "carry_desc", "title": "carry screen: row description", "ports": ["d1carry.items[desc]"],
         "cands": [i for i in items if i.startswith(("E_", "C_"))]},
        {"id": "carry_say", "title": "carry screen: Arthur's lines", "ports": ["d1carry.say1", "d1carry.say2"],
         "cands": [k for k in keys_like(S, r"SCR_D01_S06_L\d{3}") if k not in
                   ("SCR_D01_S06_L001", "SCR_D01_S06_L002", "SCR_D01_S06_L009")]},
        {"id": "carry_first", "title": "carry screen: first-visit line", "ports": ["d1carry.first_hint"],
         "cands": ["SCR_D01_S06_L001"]},
        {"id": "carry_confirm", "title": "carry screen: confirm box", "ports": ["d1carry.confirm_text"],
         "cands": ["SCR_D01_S06_L009"], "cond": {"d1carry.phase": 1}},
        {"id": "deb_speech", "title": "debate: speech / playback band", "ports": ["d1debate.speech"], "top": 14, "cond": {"d1debate.phase": 1},
         "cands": keys_like(S, r"CLM_D01_\w+_LINE", r"CARD_D01_\w+_(STATE|PUSH|RETRACT|DOWN|CATCH)",
                            r"CUT_D01_\w+", r"LINK_D01_\w+", r"REACT_D01_\w+", r"REFUTE_D01_[0-9A-Z]+",
                            r"EXCL_D01_\w+_(CATCH|SELL)", r"BEAT_D01_\w+", r"STATE_D01_\w+", r"FOG_D01_\w+",
                            r"SHF_D01_CUT_OPEN_\d")},
        {"id": "deb_sys", "title": "debate: system line", "ports": ["d1debate.sys_line"], "top": 10, "cond": {"d1debate.phase": 1},
         "cands": keys_like(S, r"SYS_D01_\w+", r"SCR_D01_S07_L00[4-9]", r"SCR_D01_S07_L01[01]",
                            r"SCR_D01_S07_L016")},
        {"id": "deb_hint", "title": "debate: his tell line / Arthur's hint", "ports": ["d1debate.hint", "d1debate.hint2"],
         "cond": {"d1debate.phase": 0},
         "cands": keys_like(S, r"TELL_D01_(ASSERT|PUSH|REBUT|STALL)_\d", r"TELL_D01_HINT_\w+",
                            r"BEAT_D01_LASTCARD_1", r"SCR_D01_S07_L010")},
        {"id": "deb_tellcard", "title": "debate: tell box card / half sentence", "ports": ["d1debate.tell_card"],
         "cond": {"d1debate.phase": 0, "d1debate.tell_on": True},
         "cands": cards + keys_like(S, r"CARD_D01_U\d_TELL")},
        {"id": "deb_gesture", "title": "debate: tell box gesture", "ports": ["d1debate.tell_gesture"],
         "cond": {"d1debate.phase": 0, "d1debate.tell_on": True},
         "cands": keys_like(S, r"TELL_D01_GESTURE_\w+")},
    ]


# ---------------------------------------------------------------------------------------------------- the runs

def build_harness() -> None:
    shutil.rmtree(HARNESS, ignore_errors=True)
    gd.build_harness("A", out=HARNESS)


def run_ports(lang: str, ticks: int) -> list:
    rel = str(HARNESS.relative_to(ROOT)).replace("\\", "/")
    events, _ = cd.run(REC, rel, ticks, lang)
    return events


def timelines(events: list) -> tuple[dict[str, list[tuple[int, object]]], list[tuple[int, set]]]:
    """Per port its changes (tick, value) (list ports from their JSON writes), and the visibility changes."""
    tl: dict[str, list[tuple[int, object]]] = {}
    vis: list[tuple[int, set]] = []
    cur = {"title", "cutin"}
    for t, kind, rest in events:
        if t < 0:
            continue
        if kind == "port":
            name, _, value = rest.partition("=")
            tl.setdefault(name, []).append((t, cp.unquote(value)))
        elif kind == "write":
            head, _, val = rest.partition(" ")
            name, _, val = val.partition(" ")
            if name.startswith("document."):
                try:
                    v = json.loads(json.loads(val))
                except (ValueError, TypeError):
                    continue
                tl.setdefault(f"{head}.{name.removeprefix('document.')}", []).append((t, v))
        elif kind == "event":
            parts = rest.split(" ")
            if parts[1] in ("SHOWN", "HIDDEN"):
                cur = set(cur)
                (cur.add if parts[1] == "SHOWN" else cur.discard)(parts[0])
                vis.append((t, cur))
    return tl, vis


def visible_at(vis: list[tuple[int, set]], t: int) -> set:
    cur = {"title", "cutin"}
    for tt, v in vis:
        if tt > t:
            break
        cur = v
    return cur


def value_at(tl: list[tuple[int, object]], t: int):
    cur = None
    for tt, v in tl:
        if tt > t:
            break
        cur = v
    return cur


def shown_tick(ui: str, cond: dict, t0: int, t1: int, tl: dict, vis: list, settle: int = SETTLE) -> int | None:
    """The first tick in [t0, t1) from which `ui` is visible and every cond port has its value (a port never
    written: 0) for settle + 3 ticks, plus settle; None if there is none. No calligraphy cut-in or stamp may have
    started in the QUIET ticks before the shot (it covers the debate screen)."""
    quiet = sorted(t for p in ("cutin.big_seq", "cutin.stamp_seq") for t, _ in tl.get(p, []) if t > 0)
    marks = {t0} | {t for t, _ in vis if t0 < t < t1} | {t + QUIET for t in quiet if t0 < t + QUIET < t1}
    for p in cond:
        marks |= {t for t, _ in tl.get(p, []) if t0 < t < t1}
    marks = sorted(marks)
    for i, t in enumerate(marks):
        nxt = marks[i + 1] if i + 1 < len(marks) else t1
        ok = ui in visible_at(vis, t) and all((value_at(tl.get(p, []), t) or 0) == v for p, v in cond.items())
        ok = ok and not any(t + settle - QUIET < q <= t + settle for q in quiet)
        if ok and nxt - t >= settle + 3:
            return t + settle
    return None


def slots_of(box: dict, S: dict, tl: dict, vis: list, by_text: dict[str, str], end: int) -> list[tuple[str, int, str]]:
    """(key, tick, port) per key a port of the box shows long enough on its visible screen (and, for the vn, in the
    box's staging style). A text is read as the box's own candidate first (a zh-TW short label repeats the full one),
    then as any key with that text; a template candidate matches its filled text."""
    own = {S[c]: c for c in box["cands"] if c in S and not PH.search(S[c])}
    tmpl = [(re.compile("^" + ".+?".join(re.escape(x) for x in PH.split(S[c])[::2]) + "$", re.S), c)
            for c in box["cands"] if c in S and PH.search(S[c])]
    cond = dict(box.get("cond", {}))
    if "style" in box:
        cond["vn.style"] = box["style"]
    out, seen = [], set()
    for spec in box["ports"]:
        m = re.fullmatch(r"(\w+)\.(\w+)(?:\[(\w+)\])?", spec)
        ui, port, field = m.group(1), m.group(2), m.group(3)
        changes = tl.get(f"{ui}.{port}", [])
        for i, (t0, v) in enumerate(changes):
            t1 = changes[i + 1][0] if i + 1 < len(changes) else end
            t = shown_tick(ui, cond, t0, t1, tl, vis, box.get("settle", SETTLE))
            if t is None:
                continue
            texts = [r.get(field) for r in v] if field and isinstance(v, list) else [v]
            for x in texts:
                if not isinstance(x, str) or not x:
                    continue
                k = own.get(x) or by_text.get(x) or next((c for rx, c in tmpl if rx.match(x)), None)
                if k and k not in seen:
                    seen.add(k)
                    out.append((k, t, spec))
    return out


def fill(text: str, S: dict) -> str:
    """A candidate's text with sample values in its placeholders, the longest real value where one is known: the
    carry confirm's {list} names every item (all found, nothing carried)."""
    names = [S[k] for k in S if re.fullmatch(r"(E_D01_\d+|C_D01_\w+)_NAME", k)]
    sample = {"n": "10", "max": "9", "issue": S.get("ISSUE_D01_MOTIVE", "動機"),
              "issues": "、".join(S.get(f"ISSUE_D01_{i}", i) for i in ("OPP", "METHOD", "MOTIVE")),
              "list": S.get("UI_TAG_SEP", "、").join(names), "name": S.get("SPK_D01_CEDRIC", "Cedric")}
    return PH.sub(lambda m: sample.get(m.group(1), "某某某某"), text)


def shoot(lang: str, at: list[int], out: Path) -> None:
    rel = str(HARNESS.relative_to(ROOT)).replace("\\", "/")
    p = subprocess.run([str(EXE), "shot", "--game", rel, "--replay", str(TESTS / f"{REC}.atrec"),
                        "--at", ",".join(str(t) for t in sorted(set(at))), "--out", str(out), "--lang", lang],
                       capture_output=True, cwd=ROOT, env=dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME))
    if p.returncode != 0:
        raise SystemExit(f"shot failed: {p.stderr.decode('utf-8', 'replace')}")


def write_strings(lang: str, S: dict, subst: dict[str, str]) -> None:
    path = HARNESS / "strings" / f"{lang}.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["key", "text"])
        for k, v in S.items():
            w.writerow([k, subst.get(k, v)])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir")
    ap.add_argument("--lang", default="zh-TW", choices=("zh-TW", "en"))
    ap.add_argument("--top", type=int, default=6)
    ap.add_argument("--boxes", default="")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    lang = args.lang
    S = load_strings(lang)
    ticks = json.loads((TESTS / "d1_m3_ticks.json").read_text(encoding="utf-8"))["ticks"]
    want = set(filter(None, args.boxes.split(",")))
    bx = [b for b in boxes(S) if not want or b["id"] in want]
    by_text: dict[str, str] = {}
    dup = set()
    for k, v in S.items():
        if v in by_text and by_text[v] != k:
            dup.add(v)
        by_text.setdefault(v, k)
    for v in dup:
        by_text.pop(v, None)
    compile_game()
    tw = TempWatch().__enter__()
    out = Path(args.dir) / lang
    try:
        build_harness()
        tl, vis = timelines(run_ports(lang, ticks))
        used: set[str] = set()
        plan: list[tuple[int, str, list]] = []   # (pass, box id, [(cand, slot key, tick)])
        for b in bx:
            slots = slots_of(b, S, tl, vis, by_text, ticks)
            native = {k: t for k, t, _ in slots}
            cands = sorted(dict.fromkeys(c for c in b["cands"] if c in S),
                           key=lambda c: (-width(fill(S[c], S)), c))
            n_top = b.get("top", args.top)
            top = cands if len(cands) <= n_top + 2 else cands[:n_top]
            free = [s for s in slots if s[0] not in used]
            rows, p, q = [], 0, 0
            for c in top:
                if c in native and not PH.search(S[c]):
                    rows.append((0, c, c, native[c]))
                    continue
                if not free:
                    rows.append((-1, c, "", 0))
                    continue
                k, t, _ = free[q % len(free)]
                rows.append((1 + q // len(free), c, k, t))
                q += 1
            used.update(k for _, _, k, _ in rows if k)
            plan.append((b, rows, cands, slots))
            if args.list:
                print(f"== {b['id']}: {b['title']}  ({len(cands)} candidates, {len(slots)} slots)")
                for ps, c, k, t in rows:
                    print(f"  pass {ps:>2}  {c:<32} w {width(fill(S[c], S)):5.1f}  len {len(fill(S[c], S)):3}  "
                          f"slot {k or '-'} @ {t}")
        if args.list:
            return 0
        passes = sorted({ps for _, rows, _, _ in plan for ps, *_ in rows if ps >= 0})
        index = ["box\tkey\twidth\tchars\tslot\ttick\tfile"]
        for ps in passes:
            subst = {}
            at = []
            for b, rows, _, _ in plan:
                for p, c, k, t in rows:
                    if p == ps:
                        if c != k or PH.search(S[c]):
                            subst[k] = fill(S[c], S)
                        at.append(t)
            write_strings(lang, S, subst)
            tmp = Path(tempfile.mkdtemp(prefix="d1textshots-"))
            try:
                shoot(lang, at, tmp)
                for b, rows, _, _ in plan:
                    d = out / b["id"]
                    d.mkdir(parents=True, exist_ok=True)
                    for n, (p, c, k, t) in enumerate(rows):
                        if p != ps:
                            continue
                        text = fill(S[c], S)
                        name = f"{n:02d}_{c}_{len(text)}.png"
                        shutil.copyfile(tmp / f"shot-{t:06d}.png", d / name)
                        index.append(f"{b['id']}\t{c}\t{width(text)}\t{len(text)}\t{k}\t{t}\t{b['id']}/{name}")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            print(f"pass {ps}: {len(at)} shots", flush=True)
        for b, rows, _, _ in plan:
            for p, c, k, t in rows:
                if p < 0:
                    index.append(f"{b['id']}\t{c}\t{width(fill(S[c], S))}\t{len(fill(S[c], S))}\t-\t-\tno slot")
        (out / "index.tsv").write_text("\n".join(index) + "\n", encoding="utf-8")
        print(f"shots: {out}")
    finally:
        shutil.rmtree(HARNESS, ignore_errors=True)
    tw.__exit__(None, None, None)
    if tw.leaks:
        print("FAIL temp: left behind: " + ", ".join(tw.leaks))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
