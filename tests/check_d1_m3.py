# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Replay the v2 demo D01 chapter recording (tests/gen_d1_m3.py) headless and check M3: the investigation, the
evidence list with appraisal and private view, the notes page, the carry screen with Ask Arthur and the confirm list,
the loadout that reaches the debate, and route A's debate result (docs/flows.md §4.13, docs/ui-contracts.md d1inv /
d1book / d1carry, tests/README.md). Runs in zh-TW and en.

Usage (from the project root):
    uv run tests/check_d1_m3.py [--shots DIR]    --shots also writes the review screenshots (zh-TW, en) and the
                                                  hotspot overlays to DIR (needs ImageMagick `magick` for overlays)
"""

from __future__ import annotations

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
import check_d1_play as cd  # noqa: E402
import check_playthrough as cp  # noqa: E402
import gen_d1_m3 as gm  # noqa: E402
from xt_cli import EXE, XTFRAME, compile_game  # noqa: E402

S = cd.S
GAME = "tests/d1m3_harness"
LABEL = {r["id"]: r["label"] for r in json.loads((ROOT / "data" / "flow" / "d1iClaim.json").read_text(encoding="utf-8"))}


def item_name(i: str) -> str:
    import gen_inv_v2
    return gen_inv_v2.item_keys(i)[0]


class At:
    def __init__(self, tr: cp.Trace, events: list) -> None:
        self.tr = tr
        self.writes: dict[str, list[tuple[int, list]]] = {}   # list ports: their JSON writes ('d1inv.locs')
        for t, kind, rest in events:
            if kind == "write":
                head, _, val = rest.partition(" ")
                name, _, val = val.partition(" ")
                if name.startswith("document."):
                    try:
                        v = json.loads(json.loads(val))
                    except (ValueError, TypeError):
                        continue
                    self.writes.setdefault(f"{head}.{name.removeprefix('document.')}", []).append((t, v))

    def ports(self, t: int) -> dict:
        cur = {}
        for tt, p, v, c in self.tr.ticks:
            if tt > t:
                break
            cur = p
        return cur

    def vis(self, t: int) -> set:
        cur = set()
        for tt, p, v, c in self.tr.ticks:
            if tt > t:
                break
            cur = v
        return cur

    def get(self, t: int, port: str):
        if port in self.writes:
            cur = None
            for tt, v in self.writes[port]:
                if tt > t:
                    break
                cur = v
            return cur
        return self.ports(t).get(port)


def trace_signals(ticks: int) -> dict[str, str]:
    """Final values of the harness's mirror signals (t1c*, t1a*, t1n*, t1pE01) from `xtatrium trace`."""
    p = subprocess.run([str(EXE), "trace", "--game", GAME, "--replay", str(TESTS / "d1_m3.atrec"), "--ticks",
                        str(ticks)], capture_output=True, cwd=ROOT, env=dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME))
    if p.returncode != 0:
        raise SystemExit(f"trace failed: {p.stderr.decode('utf-8', 'replace')}")
    out: dict[str, str] = {}
    for ln in p.stdout.decode("utf-8", "replace").splitlines():
        m = re.match(r"^t\d+ world\.(t1\w+) .* -> (.*)$", ln)
        if m:
            out[m.group(1)] = m.group(2).strip('"')
    return out


def check(lang: str, ticks: dict, fails: list) -> None:
    L = S[lang]
    marks, asks = ticks["marks"], ticks["asks"]
    events, err = cd.run("d1_m3", GAME, ticks["ticks"], lang)
    at = At(cp.Trace(events), events)
    bad: list[str] = []

    def eq(what: str, got, want) -> None:
        if got != want:
            bad.append(f"{what}: {got!r} (want {want!r})")

    # investigation: every hotspot's note (text, Arthur, what was taken), every place done
    seen: set[str] = set()
    sep = L["UI_TAG_SEP"]
    for s in gm.SPOTS:
        t = marks[f"pop_{s['id']}"]
        n = s["id"][2:]
        eq(f"{s['id']} title", at.get(t, "d1inv.popup_title"), L[f"HS_D01_{n}_NAME"])
        eq(f"{s['id']} body", at.get(t, "d1inv.popup_body"), L[f"HS_D01_{n}_DESC"])
        eq(f"{s['id']} Arthur", at.get(t, "d1inv.popup_line"), L[f"HS_D01_{n}_ART"])
        ev = [x for x in s["ev"].split(",") if x]
        want_got = L["UI_V2_GOT"].replace("{list}", sep.join(L[item_name(x)] for x in ev)) if ev else ""
        eq(f"{s['id']} taken", at.get(t, "d1inv.popup_got"), want_got)
        note = bool(s["note"]) or (bool(s["pairNote"]) and s["pair"] in seen)
        eq(f"{s['id']} note", at.get(t, "d1inv.popup_note"), L["UI_V2_GOT_NOTE"] if note else "")
        eq(f"{s['id']} shown", at.get(t, "d1inv.popup_on"), True)
        seen.add(s["id"])
    locs = at.get(marks["scene_HALL"], "d1inv.locs") or []
    eq("places done", [x["done"] for x in locs], [True] * 6)
    eq("place tabs", [x["name"] for x in locs],
       [L.get(f"SCENE_D01_{s}_TAB", L[f"SCENE_D01_{s}"]) for s in gm.SCENES])   # the attic's short tab name
    eq("appraisals before", at.get(marks["scene_HALL"], "d1inv.appr_text"), L["UI_V2_APPRAISE_LEFT"].replace("{n}", "2"))
    # evidence list: 13 items, two appraisals, the count, the private view, the notes page
    cards = at.get(marks["book_open"], "d1book.cards") or []
    eq("evidence list", [c["id"] for c in cards], gm.ITEMS)
    eq("A01 result", at.get(marks["appr_A01"], "d1book.sel_result"), L["APR_D01_01_RESULT"])
    eq("A01 line", at.get(marks["appr_A01"], "d1book.remark"), L["APR_D01_01_LINE"])
    eq("A04 line", at.get(marks["appr_A04"], "d1book.remark"), L["APR_D01_04_LINE"])
    eq("count after 2", at.get(marks["appr_A04"], "d1book.appr_left"), L["UI_V2_APPRAISE_NONE"])
    eq("E02 appraisable", at.get(marks["book_E02"], "d1book.appraisable"), True)
    eq("E02 can appraise", at.get(marks["book_E02"], "d1book.can_appraise"), False)
    opts = at.get(marks["book_E01"], "d1book.opts") or []
    eq("E01 views", [o["label"] for o in opts], [L[LABEL[k]] for k in ("-", "01A", "01B", "01C", "01D")])
    opts = at.get(marks["note_E01"], "d1book.opts") or []
    eq("E01 view chosen", [o["id"] for o in opts if o["sel"]], ["01A"])
    marked = [c["id"] for c in (at.get(marks["note_E01"], "d1book.cards") or []) if c["mark"]]
    eq("appraised marks", marked, ["E01", "E04"])
    pn = at.get(marks["notes_page"], "d1book.pnotes") or []
    eq("notes page", [x["name"] for x in pn], [L[item_name(i)] for i in gm.NOTES])
    # carry screen
    eq("first visit hint", at.get(marks["carry1"], "d1carry.first_hint"), L["SCR_D01_S06_L001"])
    eq("back", "d1inv" in at.vis(marks["back_inv"]), True)
    # ruling 4: Back keeps the appraisals made (the count is not reset); a new visit lets Arthur repeat himself
    eq("first visit Arthur", at.get(marks["ask_v1"], "d1carry.say1"), L["SCR_D01_S06_L008"])
    eq("appraisals after back", at.get(marks["back_inv"] + 20, "d1inv.appr_text"),
       at.get(marks["before_carry"], "d1inv.appr_text"))
    eq("appraisals after back (none left)", at.get(marks["back_inv"] + 20, "d1inv.appr_text"), L["UI_V2_APPRAISE_NONE"])
    eq("second visit hint", at.get(marks["carry2"], "d1carry.first_hint"), "")
    eq("items", [x["id"] for x in at.get(marks["carry2"], "d1carry.items") or []], gm.ITEMS)
    said = []
    for mk, want in asks:
        got = at.get(marks[mk], "d1carry.say1")
        said.append(next((k for k in gm.ASK_LINES if L[f"SCR_D01_S06_{k}"] == got), got))
        if want == "L004":
            eq(f"{mk} L005", at.get(marks[mk], "d1carry.say2"), L["SCR_D01_S06_L005"])
    eq("Ask Arthur order", said, [w for _, w in asks])
    eq("nine", at.get(marks["carry_nine"], "d1carry.count_text"),
       L["SCR_D01_S06_L002"].replace("{max}", "9").replace("{n}", "9"))
    eq("no room", at.get(marks["carry_full"], "d1carry.say1"), L["UI_V2_CARRY_FULL"])
    left = [i for i in gm.ITEMS if i not in gm.ROUTE_A.carried]
    eq("confirm list", at.get(marks["confirm"], "d1carry.confirm_text"),
       L["SCR_D01_S06_L009"].replace("{list}", sep.join(L[item_name(i)] for i in left)))
    eq("confirm shown", at.get(marks["confirm"], "d1carry.phase"), 1.0)
    eq("L010", at.get(marks["l010"], "d1carry.say1"), L["SCR_D01_S06_L010"])
    eq("S07 before the debate", "vn" in at.vis(marks["go"] + 30), True)
    eq("debate shown", "d1debate" in at.vis(marks["start"] + 30), True)
    # the debate: the private view preselects 01A when E01 is chosen (round 4); no view, nothing preselected
    eq("picker default E01", at.get(marks["ev4"], "d1debate.sel_claim_text"), L["CLM_D01_01A"])
    eq("picker no view", at.get(marks["ev2"], "d1debate.sel_claim_text"), "")
    grade, nrounds, outcome = cd.expected(gm.gd.forced("A"))
    t = marks["over"]
    eq("grade", at.get(t, "d1debate.grade_text"), L[f"UI_V2_GRADE_{grade}"])
    eq("rounds", at.get(t, "d1debate.rounds_text"), L["UI_V2_RESULT_ROUNDS"].replace("{n}", str(nrounds)))
    eq("win", at.get(t, "d1debate.outcome_win"), outcome == "win")
    noise = [ln for ln in err.split("\n") if ln.strip() and not ln.startswith("render: off")]
    if noise:
        bad.append("stderr: " + " | ".join(noise[:5]))
    if bad:
        fails.append(f"chapter [{lang}]")
        print(f"FAIL chapter [{lang}]: " + "; ".join(bad[:20]))
    else:
        print(f"PASS chapter [{lang}]: 26 hotspots, 2 appraisals, private view, notes page, Ask Arthur "
              f"{' '.join(w for _, w in asks)}, confirm list, L010; route A grade {grade}, {nrounds} rounds, {outcome}")


def check_loadout(ticks: dict, fails: list) -> None:
    sig = trace_signals(ticks["ticks"])
    want = {f"t1c{i}": str(i in gm.ROUTE_A.carried).lower() for i in gm.ITEMS}
    want |= {f"t1a{a}": str(a in ("A01", "A04")).lower() for a in gm.APPRS}
    want |= {f"t1n{n}": "true" for n in gm.NOTES}
    want["t1pE01"] = "01A"
    got = {k: sig.get(k, "false" if k != "t1pE01" else "") for k in want}
    bad = [f"{k}={got[k]} (want {v})" for k, v in want.items() if got[k] != v]
    if bad:
        fails.append("loadout")
        print("FAIL loadout: " + "; ".join(bad))
    else:
        print(f"PASS loadout: d1Carry = {','.join(gm.ROUTE_A.carried)}; d1Appraised = A01,A04; d1Notes = "
              f"{','.join(gm.NOTES)}; d1PrivNote E01 = 01A")


def shots(out: Path, ticks: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    m = ticks["marks"]
    events, _ = cd.run("d1_m3", GAME, ticks["ticks"], "zh-TW")
    at = At(cp.Trace(events), events)
    # the playback frames: a SYS_D01_ATTACH line with the formula names, and a stamp
    # the playback frames (rounds without clicks, gen_d1_m3.NO_SKIP): a SYS_D01_ATTACH line with the formula names,
    # and a stamp with no big word around it
    lo, hi = m["lock2"], m["chosen4"]
    zh = S["zh-TW"]
    t_formula = next(t for t, p, v, c in at.tr.ticks if lo < t < hi and "d1debate.sys_line" in c
                     and zh["UI_V2_F_COMBO"] in str(p.get("d1debate.sys_line", "")))
    bigs = [t for t, p, v, c in at.tr.ticks if "cutin.big_seq" in c]
    t_stamp = next(t for t, p, v, c in at.tr.ticks if lo < t < hi and "cutin.stamp_seq" in c
                   and not any(abs(t - b) < 150 for b in bigs))
    named = {f"loc_{s.lower()}": m[f"scene_{s}"] for s in gm.SCENES}
    named |= {"note_hs25": m["pop_HS25"] + 8, "evlist_appraised": m["appr_A01"], "evlist_view": m["note_E01"],
              "notes_page": m["notes_page"], "carry_first": m["carry1"], "carry_arthur": m["ask1"],
              "carry_confirm": m["confirm"], "carry_l010": m["l010"], "debate_formula": t_formula + 45,
              "debate_stamp": t_stamp + 14}
    for lang in ("zh-TW", "en"):
        tmp = Path(tempfile.mkdtemp(prefix="d1m3shots-"))
        try:
            at_s = ",".join(str(t) for t in sorted(set(named.values())))
            p = subprocess.run([str(EXE), "shot", "--game", GAME, "--replay", str(TESTS / "d1_m3.atrec"), "--at", at_s,
                                "--out", str(tmp), "--lang", lang], capture_output=True, cwd=ROOT,
                               env=dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME))
            if p.returncode != 0:
                raise SystemExit(f"shot failed: {p.stderr.decode('utf-8', 'replace')}")
            for name, t in named.items():
                shutil.copyfile(tmp / f"shot-{t:06d}.png", out / f"{name}_{lang}.png")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    # hotspot overlays: every rectangle with its id over the zh-TW place shots
    ov = out / "overlays"
    ov.mkdir(exist_ok=True)
    if shutil.which("magick"):
        for scene in gm.SCENES:
            args = ["magick", str(out / f"loc_{scene.lower()}_zh-TW.png"), "-fill", "none", "-strokewidth", "3"]
            for s in [s for s in gm.SPOTS if s["scene"] == scene]:
                x, y, w, h = s["x"], s["y"], s["w"], s["h"]
                args += ["-stroke", "#ff2a2a", "-fill", "none", "-draw", f"rectangle {x},{y} {x + w - 1},{y + h - 1}",
                         "-stroke", "none", "-fill", "#ff2a2acc", "-draw", f"rectangle {x},{y} {x + 62},{y + 22}",
                         "-fill", "white", "-pointsize", "18", "-draw", f"text {x + 5},{y + 18} '{s['id']}'"]
            args.append(str(ov / f"overlay_{scene.lower()}.png"))
            subprocess.run(args, check=True)
    print(f"shots: {out}")


def main() -> int:
    argv = sys.argv[1:]
    compile_game()
    temp = Path(tempfile.gettempdir())
    before = set(os.listdir(temp))
    fails: list[str] = []
    try:
        if subprocess.run([sys.executable, str(TESTS / "gen_d1_m3.py")], cwd=ROOT).returncode != 0:
            raise SystemExit("gen_d1_m3 failed")
        ticks = json.loads((TESTS / "d1_m3_ticks.json").read_text(encoding="utf-8"))
        for lang in ("zh-TW", "en"):
            check(lang, ticks, fails)
        check_loadout(ticks, fails)
        if "--shots" in argv:
            shots(Path(argv[argv.index("--shots") + 1]), ticks)
    finally:
        shutil.rmtree(gm.HARNESS, ignore_errors=True)
    left = sorted(n for n in set(os.listdir(temp)) - before if n.startswith(("d1m3shots-", "tmp")))
    if left:
        fails.append("temp")
        print("FAIL temp: left in %TEMP%: " + ", ".join(left))
    print("ok" if not fails else f"FAILED: {', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
