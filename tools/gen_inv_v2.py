"""The v2 demo D01 investigation, evidence list, notes page and carry screen (M3), imported by tools/gen_flows.py:
flows/d01_investigate.xtflow (the UIs d1inv, d1book and d1carry), its support tables under data/flow/ (d1i*) and the
game.json entries it adds. See docs/flows.md §4.13 and docs/ui-contracts.md d1inv / d1book / d1carry.

Design: v2/11_demo_chapter.md S05 (six places, 26 hotspots), S06 (carry screen, Ask Arthur), §3.1-§3.3 (evidence,
notes on people, appraisal), §13 (攜帶選擇畫面, 問亞瑟的意見, 私下的看法, 鑑定入口與剩餘次數, 人物筆記頁). Hotspot
rectangles are authored in data/d01/d1Hotspot.json (the design has none).

D01 is chapter 101 of the step table (tools/build_data.py D01_STEPS). Choosing it resets the chapter's state (everything
below lives in collections that outlast a step, so the steps M4 inserts can read and write it: hotspots looked at,
items found, notes, appraisals, private views, the carry selection; world.d1Warmup is set to "pass" until the warm-up
step writes it, and it sets the appraisal count). The d1investigate step ends with world.stepDone; the d1carry step
writes d1Carry / d1Appraised / d1Notes and ends with world.stepDone (the d1debate step begins and tools/gen_debui_v2.py
starts the debate 0.1 s later, so the engine reads them at least one tick before d1Start); its back button sends
world.d1StepBack (main goes back one row). The private views stay in d1PrivNote (evidence -> claim) for the claim
picker.

Same rules as gen_flows / gen_debui_v2: state in the maps `i1` (numbers) and `i1S` (strings); work that must read a
collection after changing it runs on the next beat, chosen by an i1 flag.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import gen_flows as F
from gen_flows import Graph, tref
from gen_debui import add_all, setter, truth

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ref" / "src"))
from sherefox_ref.v2.data import load_chapter  # noqa: E402

CH = load_chapter()
DEBATE = json.loads((ROOT / "ref" / "data" / "d01_debate.json").read_text(encoding="utf-8"))
SPOTS = json.loads((ROOT / "data" / "d01" / "d1Hotspot.json").read_text(encoding="utf-8"))
# S05: the six places in the design's order -> background id (the d1inv board's bg values)
SCENES = [("PARLOR", "parlour"), ("STUDY", "study"), ("BASEMENT", "basement"), ("ATTIC", "attic"),
          ("BEDROOM", "bedroom"), ("HALL", "hall")]
CARRY_MAX = DEBATE["carry_limit"]          # 9 (ch §0.1)
APPR_LIMIT = DEBATE["appraisal_limit"]     # 2 (warm-up passed), 1 after a failed warm-up (ch §0.1, §3.3)
D01_CHAPTER = 101                          # tools/build_data.py D01_CHAPTER
WARMUP_DEFAULT = "pass"                    # until the warm-up step (M4) writes world.d1Warmup
ITEMS = [e for e in CH.evidence]           # E01..E12, P1 (carry items, data order)
NOTES = [k["id"] for k in DEBATE["optional_known"]]
NOTES = [n for n in ("PN1", "PN2", "PN3", "PN4", "OBS01") if n in NOTES]
APPRS = [a["id"] for a in DEBATE["appraisals"]]
SEP = ","
# S06 Ask Arthur, in priority order (ruling): (line, condition). L004 is followed by Sherefox's L005; L012 repeats.
ASK = ["L008", "L004", "L003", "L006", "L007", "L011", "L012"]
# v2 demo E6 (V3): what he could pick up if it stays behind (ref model.pickups_for, from ref's data)
PICKABLE = [e for e in CH.pickup_priority if CH.evidence[e].opponent_use]


def item_keys(i: str) -> tuple[str, str, str]:
    """(name, text, kind label) string keys of an item id (ch §3.1, §3.2)."""
    if i.startswith("E"):
        return f"E_D01_{i[1:]}_NAME", f"E_D01_{i[1:]}_DESC", "UI_V2_TYPE_EVIDENCE"
    if i.startswith("P") and not i.startswith("PN"):
        return f"C_D01_{i}_NAME", f"C_D01_{i}_DESC", "UI_V2_TYPE_PSYCH"
    if i.startswith("PN"):
        return f"PN_D01_{i[2:]}_NAME", f"PN_D01_{i[2:]}_TEXT", "UI_V2_TYPE_NOTE"
    return f"OBS_D01_{i[3:]}_NAME", f"OBS_D01_{i[3:]}_TEXT", "UI_V2_TYPE_OBS"


def _checks() -> None:
    have = {s["id"] for s in SPOTS}
    want = {f"HS{n:02d}" for n in range(1, 27)}
    if have != want:
        raise SystemExit(f"d1Hotspot.json: hotspots {sorted(want ^ have)} differ from S05's HS01..HS26")
    got = [x for s in SPOTS for x in s["ev"].split(SEP) if x] + [x for s in SPOTS for x in (s["note"], s["pairNote"]) if x]
    for i in ITEMS + NOTES:
        if i not in got:
            raise SystemExit(f"d1Hotspot.json: {i} is not obtained anywhere")
    for s in SPOTS:
        if s["scene"] not in dict(SCENES):
            raise SystemExit(f"d1Hotspot.json: {s['id']} has an unknown scene {s['scene']}")
        if len([x for x in s["ev"].split(SEP) if x]) > 2 or SEP in s["note"]:
            raise SystemExit(f"d1Hotspot.json: {s['id']}: at most 2 evidence and 1 note per hotspot (the flow's slots)")
    for c in CH.claims.values():
        if len(c.unlock) > 1:
            raise SystemExit(f"claim {c.id}: more than one unlock item (the private view's slot)")


# ---------------------------------------------------------------------------------------------- tables

def tables() -> dict[str, list[dict]]:
    _checks()
    spots = []
    for s in SPOTS:
        ev = [x for x in s["ev"].split(SEP) if x] + ["", ""]
        n = s["id"][2:]
        spots.append({"id": s["id"], "scene": s["scene"], "name": f"HS_D01_{n}_NAME", "desc": f"HS_D01_{n}_DESC",
                      "art": f"HS_D01_{n}_ART", "x": s["x"], "y": s["y"], "w": s["w"], "h": s["h"], "type": s["icon"],
                      "ev": s["ev"], "ev0": ev[0], "ev1": ev[1], "note": s["note"], "pair": s["pair"],
                      "pairNote": s["pairNote"]})
    # the place tab: the short name where the package has one (SCENE_D01_<id>_TAB), else the full name (headings)
    keys = F.string_keys()
    scenes = [{"id": sid, "bg": bg, "name": f"SCENE_D01_{sid}",
               "tab": f"SCENE_D01_{sid}_TAB" if f"SCENE_D01_{sid}_TAB" in keys else f"SCENE_D01_{sid}",
               "spots": SEP.join(s["id"] for s in SPOTS if s["scene"] == sid),
               "n": sum(1 for s in SPOTS if s["scene"] == sid)} for sid, bg in SCENES]
    items = []
    for i in ITEMS + NOTES:
        name, text, kind = item_keys(i)
        appr = CH.evidence[i].appraisal if i in CH.evidence and CH.evidence[i].appraisal else ""
        items.append({"id": i, "name": name, "desc": text, "kind": kind, "appr": appr,
                      "aprLine": f"APR_D01_{appr[1:]}_LINE" if appr else "",
                      "aprResult": f"APR_D01_{appr[1:]}_RESULT" if appr else ""})
    claims = [{"id": "-", "evidence": "", "label": "UI_V2_PRIVATE_VIEW_NONE", "unlock": ""}]
    for cid, c in CH.claims.items():
        claims.append({"id": cid, "evidence": c.evidence, "label": f"CLM_D01_{cid}",
                       "unlock": c.unlock[0] if c.unlock else ""})
    return {"d1iSpot": spots, "d1iScene": scenes, "d1iItem": items, "d1iClaim": claims}


SIGNALS = {
    "d1StepBack": {"type": "pulse"},                    # the carry screen's back: main goes back one step row
    "d1Dev": {"type": "bool", "initial": False},        # main: the title's dev shortcut entered the D01 debate row
}
COLLECTIONS = {
    "i1": {"kind": "map", "type": "number", "capacity": 32},
    "i1S": {"kind": "map", "type": "string", "capacity": 16},
    "i1Seen": {"kind": "list", "type": "string", "capacity": 32, "unique": True},   # hotspots looked at
    "i1Have": {"kind": "list", "type": "string", "capacity": 16, "unique": True},   # evidence / mind-game card found
    "i1Notes": {"kind": "list", "type": "string", "capacity": 8, "unique": True},   # notes on people / observations
    "i1Appr": {"kind": "list", "type": "string", "capacity": 4, "unique": True},    # appraisals done
    "i1New": {"kind": "list", "type": "string", "capacity": 24, "unique": True},    # found since the list was closed
    "i1Sel": {"kind": "list", "type": "string", "capacity": 16, "unique": True},    # the carry selection
    "i1Said": {"kind": "list", "type": "string", "capacity": 8, "unique": True},    # Ask Arthur lines said this visit
    "i1Here": {"kind": "list", "type": "string", "capacity": 16},                  # the current place's hotspots
    "i1SpSt": {"kind": "map", "type": "number", "capacity": 32},                   # hotspot -> 1 looked at
    "i1Left": {"kind": "map", "type": "number", "capacity": 8},                    # place -> hotspots not looked at
    "i1Locs": {"kind": "list", "type": "string", "capacity": 8},
    "i1LocSel": {"kind": "map", "type": "bool", "capacity": 8},
    "i1LocDone": {"kind": "map", "type": "bool", "capacity": 8},
    "i1All": {"kind": "list", "type": "string", "capacity": 16},                   # the carry items, data order
    "i1NAll": {"kind": "list", "type": "string", "capacity": 8},
    "i1AAll": {"kind": "list", "type": "string", "capacity": 4},
    "i1PsyAll": {"kind": "list", "type": "string", "capacity": 4},
    "i1ClAll": {"kind": "list", "type": "string", "capacity": 40},
    "i1Book": {"kind": "list", "type": "string", "capacity": 16},                  # found items, data order
    "i1CSel": {"kind": "map", "type": "bool", "capacity": 16},
    "i1CMark": {"kind": "map", "type": "string", "capacity": 16},
    "i1Opt": {"kind": "list", "type": "string", "capacity": 8},
    "i1OptSel": {"kind": "map", "type": "bool", "capacity": 8},
    "i1PN": {"kind": "list", "type": "string", "capacity": 8},
    "d1PrivNote": {"kind": "map", "type": "string", "capacity": 16},               # evidence -> claim (私下的看法)
}


# ---------------------------------------------------------------------------------------------- the flow

def gen_d01inv() -> Graph:
    g = Graph()
    T = truth(g)
    seti, sets = setter(g, "i1"), setter(g, "i1S")
    INV, BOOK, CAR = "ui#d1inv", "ui#d1book", "ui#d1carry"
    langEn = g.cmp("langEnC", "world.language", g.k("en"))
    g.put("chSel", "ui#title.chapter")
    for k in ("pop", "tab", "rb", "bk", "cr", "cv", "cph"):
        g.mget("d_" + k, "i1", g.k(k))
    for k in ("loc", "sp", "card", "rm", "w1", "s1", "w2", "s2"):
        g.mget("s_" + k, "i1S", g.k(k))

    # ---- the beat and the next-tick stages
    g.node("clock", "clock")
    g.node("beat", "filter", op="deadband", threshold=0)
    g.edge("clock.seconds", "beat.in")

    def stage(name: str, cond: str, clear: str) -> str:
        p = g.when(name, "beat.passed", T(name + "Go", cond))
        seti(p, clear, g.k(0))
        return p

    # ---- the chapter starts (the title's v2 entry chooses chapter 101): reset everything, the constant lists, the
    # hotspot counts, the warm-up result's default
    start = g.when("start", "ui#title.chapter.emitted", T("isD01", f"chSel == {D01_CHAPTER}"))
    for coll in ("i1", "i1S", "i1SpSt", "i1Left", "i1LocSel", "i1LocDone", "i1CSel", "i1CMark", "i1OptSel",
                 "d1PrivNote"):
        g.edge(start, g.eff(f"clr_{coll}", "atrium.map.clear", coll))
    for coll in ("i1Seen", "i1Have", "i1Notes", "i1Appr", "i1New", "i1Sel", "i1Said", "i1Here", "i1Book", "i1Opt",
                 "i1PN"):
        g.edge(start, g.eff(f"clr_{coll}", "atrium.coll.clear", coll))
    for coll, ids in (("i1Locs", [s for s, _ in SCENES]), ("i1All", ITEMS), ("i1NAll", NOTES), ("i1AAll", APPRS),
                      ("i1PsyAll", [i for i in ITEMS if CH.evidence[i].psych_card]), ("i1ClAll", ["-"] + list(CH.claims))):
        g.edge(start, g.eff(f"clr_{coll}", "atrium.coll.clear", coll))
        g.edge(start, add_all(g, f"add_{coll}", coll, g.k(SEP.join(ids))))
    for sid, _ in SCENES:
        n = sum(1 for s in SPOTS if s["scene"] == sid)
        g.edge(start, g.eff(f"left_{sid}", "atrium.map.set", "i1Left", key=g.k(sid), value=g.k(n)))
    sets(start, "loc", g.k(SCENES[0][0]))
    g.edge(g.latch("wuDef", g.k(WARMUP_DEFAULT), start), "world.d1Warmup")
    # the d1investigate step begins (again, after the carry screen's back)
    invB = g.when("invB", "world.stepBegin", g.cmp("isInvK", "world.stepKind", g.k("d1investigate")))
    for k, v in (("rb", 1), ("bk", 1), ("pop", 0)):
        seti(invB, k, g.k(v))

    # ---- the place: hotspots and the six tabs (rebuilt on the next beat after a change)
    rbT = stage("rbG", "d_rb > 0", "rb")
    langP = g.merge("langP", "langEnC.true", "langEnC.false")
    rb = g.merge("rbM", rbT, langP)
    srow = g.tfind("scRow", "d1iScene", "id", "s_loc")
    g.tget("scSpots", "d1iScene", "spots", srow)
    g.tget("scBg", "d1iScene", "bg", srow)
    g.edge(rb, g.eff("clr_here", "atrium.coll.clear", "i1Here"))
    g.edge(rb, add_all(g, "add_here", "i1Here", "scSpots"))
    g.edge(rb, g.ui_list("spList", "ui.d1inv.spots", "i1Here",
                         {"id": "item", "name": tref("d1iSpot", "id", "name"), "x": tref("d1iSpot", "id", "x"),
                          "y": tref("d1iSpot", "id", "y"), "w": tref("d1iSpot", "id", "w"),
                          "h": tref("d1iSpot", "id", "h"), "type": tref("d1iSpot", "id", "type"),
                          "state": "map:i1SpSt"}, localize=["name"]))
    g.node("locEach", "atrium.coll.forEach", name="i1Locs")
    g.edge(rb, "locEach.trigger")
    li = g.put("li", "locEach.item")
    g.edge("locEach.each", g.eff("locSel", "atrium.map.set", "i1LocSel", key=li, value=g.cmp("liSel", li, "s_loc")))
    g.mget("liLeft", "i1Left", li)
    g.edge("locEach.each", g.eff("locDone", "atrium.map.set", "i1LocDone", key=li,
                                   value=g.cmp("liDone", "liLeft", g.k(0))))
    g.edge("locEach.done", g.ui_list("locList", "ui.d1inv.locs", "i1Locs",
                                     {"id": "item", "name": tref("d1iScene", "id", "tab"), "sel": "map:i1LocSel",
                                      "done": "map:i1LocDone"}, localize=["name"]))
    g.edge("scBg", f"{INV}.bg")
    lP = g.when("locG", f"{INV}.pick_loc.emitted", T("locOk", "d_pop == 0"))
    sets(lP, "loc", f"{INV}.pick_loc")
    seti(lP, "rb", g.k(1))

    # ---- a hotspot: first look takes what is there; the note shows its text, Arthur's comment and what was taken
    sid = g.put("sid", f"{INV}.spot")
    prow = g.tfind("spRow", "d1iSpot", "id", sid)
    for c in ("scene", "ev", "note", "pair", "pairNote"):
        g.tget("sp_" + c, "d1iSpot", c, prow)
    g.n("seenN", g.contains("seenC", "i1Seen", sid))
    g.n("pairSeenN", g.contains("pairSeenC", "i1Seen", "sp_pair"))
    g.n("hasEvN", g.cmp("hasEvC", "sp_ev", g.k(""), "ne"))
    g.n("hasNoteN", g.cmp("hasNoteC", "sp_note", g.k(""), "ne"))
    g.n("hasPairN", g.cmp("hasPairC", "sp_pairNote", g.k(""), "ne"))
    g.mget("spLeft", "i1Left", "sp_scene")
    sP = g.when("spotG", f"{INV}.spot.emitted", T("spotOk", "d_pop == 0"))
    first = g.when("firstG", sP, T("firstOk", "!seenN"))
    g.edge(first, g.eff("seenAdd", "atrium.coll.add", "i1Seen", value=sid))
    g.edge(first, g.eff("spSt", "atrium.map.set", "i1SpSt", key=sid, value=g.k(1)))
    g.edge(first, g.eff("leftDec", "atrium.map.set", "i1Left", key="sp_scene", value=g.x("leftN", "spLeft - 1")))
    evP = g.when("evG", first, T("evOk", "hasEvN"))
    g.edge(evP, add_all(g, "haveAdd", "i1Have", "sp_ev"))
    # the evidence list's "new" marks and its button's count: evidence and psych cards only (v2 demo E6 V5: notes on
    # people are on the notes page, not in the list)
    g.edge(evP, add_all(g, "newAdd", "i1New", "sp_ev"))
    ntP = g.when("ntG", first, T("ntOk", "hasNoteN"))
    g.edge(ntP, g.eff("noteAdd", "atrium.coll.add", "i1Notes", value="sp_note"))
    # PN3: both halves (HS04 + HS05) looked at (ref optional_known: both hotspots needed)
    prP = g.when("prG", first, T("prOk", "hasPairN && pairSeenN"))
    g.edge(prP, g.eff("pairAdd", "atrium.coll.add", "i1Notes", value="sp_pairNote"))
    sets(sP, "sp", sid)
    seti(sP, "pop", g.k(1))
    seti(sP, "pnote", g.x("pnoteV", "hasNoteN || (hasPairN && pairSeenN)"))
    seti(sP, "rb", g.k(1))
    seti(sP, "bk", g.k(1))
    g.counter("popSeq", initial=0)
    g.edge(sP, "popSeq.increment")
    g.edge("popSeq.value", f"{INV}.popup_seq")
    seti(g.merge("dismissM", f"{INV}.dismiss"), "pop", g.k(0))
    # the note's ports (from i1S sp, read on the next tick)
    vrow = g.tfind("vRow", "d1iSpot", "id", "s_sp")
    for c in ("name", "desc", "art", "ev0", "ev1"):
        g.tget("v_" + c, "d1iSpot", c, vrow)
    g.edge(g.text("vName", "v_name"), f"{INV}.popup_title")
    g.edge(g.text("vDesc", "v_desc"), f"{INV}.popup_body")
    g.edge(g.text("vArt", "v_art"), f"{INV}.popup_line")
    g.edge(g.text("vSpk", g.k("SPK_ARTHUR")), f"{INV}.popup_speaker")
    names = []
    for i in (0, 1):
        g.text(f"vEvN{i}", g.tget(f"vEvK{i}", "d1iItem", "name", g.tfind(f"vEvR{i}", "d1iItem", "id", f"v_ev{i}")))
        names.append(f"vEvN{i}")
    sep = g.text("sepT", g.k("UI_TAG_SEP"))
    g.n("ev1N", g.cmp("ev1C", "v_ev1", g.k(""), "ne"))
    lst = g.sel("vList", g.b("ev1B", "ev1N"), g.fmt("vList2", "{a}{b}{c}", names[0], sep, names[1]), names[0])
    got = g.textf("vGotT", key="UI_V2_GOT", list=lst)
    g.edge(g.sel("vGot", g.cmp("ev0C", "v_ev0", g.k(""), "ne"), got, g.k("")), f"{INV}.popup_got")
    g.mget("d_pnote", "i1", g.k("pnote"))
    g.edge(g.sel("vNote", g.b("pnoteB", "d_pnote"), g.text("gotNoteT", g.k("UI_V2_GOT_NOTE")), g.k("")),
           f"{INV}.popup_note")
    g.edge(g.b("popOn", "d_pop"), f"{INV}.popup_on")
    # HUD
    g.edge(g.text("hudT", g.k("SCR_D01_S05_TITLE")), f"{INV}.hud_title")
    g.count("apprN", "i1Appr")
    g.n("wuFail", g.cmp("wuFailC", "world.d1Warmup", g.k("fail")))
    g.x("aLeft", f"max((wuFail ? {APPR_LIMIT - 1} : {APPR_LIMIT}) - apprN, 0)")
    left_t = g.sel("aLeftT", T("aLeftOk", "aLeft > 0"), g.textf("aLeftF", key="UI_V2_APPRAISE_LEFT", n="aLeft"),
                   g.text("aNoneT", g.k("UI_V2_APPRAISE_NONE")))
    g.edge(left_t, f"{INV}.appr_text")
    g.count("newN", "i1New")
    g.edge("newN", f"{INV}.book_new")

    # ---- the evidence list / notes page (d1book, modal over d1inv; main shows and hides it)
    g.cget("book0", "i1Book", g.k(0))
    bookP = g.merge("bookOpen", f"{INV}.book", f"{INV}.notes")
    seti(g.merge("bookEv", f"{INV}.book"), "tab", g.k(0))
    seti(g.merge("bookPn", f"{INV}.notes"), "tab", g.k(1))
    g.n("hasCardN", g.cmp("hasCardC", "s_card", g.k(""), "ne"))
    sets(g.when("card0G", bookP, T("card0Ok", "!hasCardN")), "card", "book0")
    sets(bookP, "rm", g.k(""))
    seti(bookP, "bk", g.k(1))
    clP = g.merge("bookClose", f"{BOOK}.close")
    g.edge(clP, g.eff("clr_new", "atrium.coll.clear", "i1New"))
    g.edge("d_tab", f"{BOOK}.tab")
    tP = g.merge("tabM", f"{BOOK}.pick_tab.emitted")
    seti(tP, "tab", f"{BOOK}.pick_tab")
    cP = g.merge("cardM", f"{BOOK}.pick_card.emitted")
    sets(cP, "card", f"{BOOK}.pick_card")
    sets(cP, "rm", g.k(""))
    seti(cP, "bk", g.k(1))
    # the selected item
    crow = g.tfind("cRow", "d1iItem", "id", "s_card")
    for c in ("name", "desc", "kind", "appr", "aprLine", "aprResult"):
        g.tget("c_" + c, "d1iItem", c, crow)
    g.n("cApprN", g.cmp("cApprC", "c_appr", g.k(""), "ne"))
    g.n("cDoneN", g.contains("cDoneC", "i1Appr", "c_appr"))
    g.x("canAppr", "hasCardN && cApprN && !cDoneN && aLeft > 0")
    aP = g.when("apprG", f"{BOOK}.appraise", "canAppr_t")
    g.edge(aP, g.eff("apprAdd", "atrium.coll.add", "i1Appr", value="c_appr"))
    sets(aP, "rm", "c_aprLine")
    seti(aP, "bk", g.k(1))
    g.counter("rmSeq", initial=0)
    g.edge(aP, "rmSeq.increment")
    g.edge("rmSeq.value", f"{BOOK}.remark_seq")
    g.edge(g.b("hasCardB", "hasCardN"), f"{BOOK}.has_sel")
    g.edge(g.text("cKindT", "c_kind"), f"{BOOK}.sel_kind")
    g.edge(g.text("cNameT", "c_name"), f"{BOOK}.sel_name")
    g.edge(g.text("cDescT", "c_desc"), f"{BOOK}.sel_desc")
    g.edge(g.b("cApprB", "cApprN"), f"{BOOK}.appraisable")
    g.edge("cDoneC.has", f"{BOOK}.appraised")
    g.edge("canAppr_t", f"{BOOK}.can_appraise")
    g.edge(left_t, f"{BOOK}.appr_left")
    g.edge(g.sel("cRes", "cDoneC.has", g.text("cResT", "c_aprResult"), g.k("")), f"{BOOK}.sel_result")
    g.edge(g.text("rmT", "s_rm"), f"{BOOK}.remark")
    g.edge("vSpk", f"{BOOK}.remark_speaker")
    # the private view: one of the evidence's claims that is unlocked now (its unlock item found or appraised)
    oP = g.when("optG", f"{BOOK}.pick_opt.emitted", "hasCardB")
    g.n("optNoneN", g.cmp("optNoneC", f"{BOOK}.pick_opt", g.k("-")))
    g.edge(oP, g.eff("noteSet", "atrium.map.set", "d1PrivNote", key="s_card",
                     value=g.sel("noteV", "optNoneC", g.k(""), f"{BOOK}.pick_opt")))
    seti(oP, "bk", g.k(1))

    # the lists, rebuilt on the next beat (and on a language change)
    bkT = stage("bkG", "d_bk > 0", "bk")
    bk = g.merge("bkM", bkT, langP)

    def rebuild_book(pre: str, pulse: str) -> str:
        """i1Book = the found items in data order; returns the forEach's done pulse."""
        g.edge(pulse, g.eff(pre + "clr", "atrium.coll.clear", "i1Book"))
        g.node(pre + "Each", "atrium.coll.forEach", name="i1All")
        g.edge(pulse, pre + "Each.trigger")
        g.n(pre + "HaveN", g.contains(pre + "HaveC", "i1Have", pre + "Each.item"))
        g.edge(g.when(pre + "HaveG", pre + "Each.each", pre + "HaveC.has"),
               g.eff(pre + "add", "atrium.coll.add", "i1Book", value=pre + "Each.item"))
        return pre + "Each.done"
    bdone = rebuild_book("bb", bk)
    g.node("bmEach", "atrium.coll.forEach", name="i1All")
    g.edge(bdone, "bmEach.trigger")
    bi = g.put("bi", "bmEach.item")
    g.edge("bmEach.each", g.eff("bmSel", "atrium.map.set", "i1CSel", key=bi, value=g.cmp("biSel", bi, "s_card")))
    g.tget("biAppr", "d1iItem", "appr", g.tfind("biRow", "d1iItem", "id", bi))
    g.n("biDoneN", g.contains("biDoneC", "i1Appr", "biAppr"))
    g.n("biHasN", g.cmp("biHasC", "biAppr", g.k(""), "ne"))
    g.edge("bmEach.each", g.eff("bmMark", "atrium.map.set", "i1CMark", key=bi,
                                  value=g.sel("biMark", T("biMarkOn", "biHasN && biDoneN"), g.k("UI_V2_APPRAISED"),
                                              g.k(""))))
    g.edge("bmEach.done", g.ui_list("cardList", "ui.d1book.cards", "i1Book",
                                    {"id": "item", "name": tref("d1iItem", "id", "name"), "psy": "coll:i1PsyAll.contains",
                                     "sel": "map:i1CSel", "mark": "map:i1CMark", "isnew": "coll:i1New.contains"},
                                    localize=["name", "mark"]))
    # options: "-" (none) then the selected evidence's unlocked claims in data order
    # (the view is read inside the forEach with a key that changes per item, so it is the current one: "-" reads the
    # selected evidence's, a claim its own evidence's)
    g.edge(bk, g.eff("clr_opt", "atrium.coll.clear", "i1Opt"))
    g.node("opEach", "atrium.coll.forEach", name="i1ClAll")
    g.edge(bk, "opEach.trigger")
    oi = g.put("oi", "opEach.item")
    orow = g.tfind("oiRow", "d1iClaim", "id", oi)
    g.tget("oiEv", "d1iClaim", "evidence", orow)
    g.tget("oiUn", "d1iClaim", "unlock", orow)
    g.n("oiMineN", g.cmp("oiMineC", "oiEv", "s_card"))
    g.n("oiNoneN", g.cmp("oiNoneC", oi, g.k("-")))
    g.mget("oiView", "d1PrivNote", g.sel("oiViewK", "oiNoneC.out", g.fmt("oiViewC", "{a}", "s_card"),
                                          g.fmt("oiViewE", "{a}", "oiEv")))
    g.n("oiPickN", g.cmp("oiPickC", "oiView", g.sel("oiPickV", "oiNoneC.out", g.k(""), g.fmt("oiPickI", "{a}", oi))))
    g.n("oiFreeN", g.cmp("oiFreeC", "oiUn", g.k("")))
    g.n("oiNoteN", g.contains("oiNoteC", "i1Notes", "oiUn"))
    g.n("oiApprN", g.contains("oiApprC", "i1Appr", "oiUn"))
    oG = g.when("oiG", "opEach.each", T("oiOk", "oiNoneN || (oiMineN && (oiFreeN || oiNoteN || oiApprN))"))
    g.edge(oG, g.eff("optAdd", "atrium.coll.add", "i1Opt", value=oi))
    g.edge(oG, g.eff("optSel", "atrium.map.set", "i1OptSel", key=oi, value="oiPickC.out"))
    g.edge("opEach.done", g.ui_list("optList", "ui.d1book.opts", "i1Opt",
                                    {"id": "item", "label": tref("d1iClaim", "id", "label"), "sel": "map:i1OptSel"},
                                    localize=["label"]))
    # notes on people and observations, data order
    g.edge(bk, g.eff("clr_pn", "atrium.coll.clear", "i1PN"))
    g.node("pnEach", "atrium.coll.forEach", name="i1NAll")
    g.edge(bk, "pnEach.trigger")
    g.edge(g.when("pnG", "pnEach.each", g.contains("pnHas", "i1Notes", "pnEach.item")),
           g.eff("pnAdd", "atrium.coll.add", "i1PN", value="pnEach.item"))
    g.edge("pnEach.done", g.ui_list("pnList", "ui.d1book.pnotes", "i1PN",
                                    {"kind": tref("d1iItem", "id", "kind"), "name": tref("d1iItem", "id", "name"),
                                     "text": tref("d1iItem", "id", "desc")}, localize=["kind", "name", "text"]))

    # ---- end of the search -> the carry screen (S06)
    g.edge(g.when("endG", f"{INV}.end", "isInvK.out"), "world.stepDone")
    eP = g.when("carB", "world.stepBegin", g.cmp("isCarK", "world.stepKind", g.k("d1carry")))
    g.edge(eP, g.eff("clr_said", "atrium.coll.clear", "i1Said"))
    for k in ("w1", "s1", "w2", "s2"):
        sets(eP, k, g.k(""))
    seti(eP, "cph", g.k(0))
    seti(eP, "cv", g.x("cvN", "d_cv + 1"))
    seti(eP, "cr", g.k(1))
    g.edge(g.when("backG", f"{CAR}.back", T("backOk", "d_cph == 0")), "world.d1StepBack")
    # the item list (found items, data order)
    crT = stage("crG", "d_cr > 0", "cr")
    cr = g.merge("crM", crT, langP)
    cdone = rebuild_book("cb", cr)
    g.edge(cdone, g.ui_list("itemList", "ui.d1carry.items", "i1Book",
                            {"id": "item", "name": tref("d1iItem", "id", "name"), "desc": tref("d1iItem", "id", "desc"),
                             "kind": tref("d1iItem", "id", "kind"), "psy": "coll:i1PsyAll.contains",
                             "sel": "coll:i1Sel.contains"}, localize=["name", "desc", "kind"]))
    g.count("selN", "i1Sel")
    g.edge(g.textf("countT", key="SCR_D01_S06_L002", max=g.k(CARRY_MAX), n="selN"), f"{CAR}.count_text")
    g.x("full", f"selN >= {CARRY_MAX}")
    g.edge("full_t", f"{CAR}.full")
    g.edge(g.sel("hint1", T("hint1On", "d_cv == 1"), g.text("l001T", g.k("SCR_D01_S06_L001")), g.k("")),
           f"{CAR}.first_hint")
    g.edge("d_cph", f"{CAR}.phase")
    # take / put down
    pv = g.put("pv", f"{CAR}.pick_item")
    g.n("pvInN", g.contains("pvInC", "i1Sel", pv))
    pP = g.when("pickG", f"{CAR}.pick_item.emitted", T("pickOk", "d_cph == 0"))
    g.edge(g.when("pvRemG", pP, T("pvRem", "pvInN")), g.eff("selRem", "atrium.coll.remove", "i1Sel", value=pv))
    g.edge(g.when("pvAddG", pP, T("pvAdd", f"!pvInN && selN < {CARRY_MAX}")),
           g.eff("selAdd", "atrium.coll.add", "i1Sel", value=pv))
    fullP = g.when("pvFullG", pP, T("pvFull", f"!pvInN && selN >= {CARRY_MAX}"))
    sets(fullP, "w1", g.k("SPK_SYSTEM"))
    sets(fullP, "s1", g.k("UI_V2_CARRY_FULL"))
    sets(fullP, "w2", g.k(""))
    sets(fullP, "s2", g.k(""))
    seti(pP, "cr", g.k(1))
    # Ask Arthur: the first line whose condition holds and that was not said this visit (L012 repeats)
    for e in ("E05", "E03", "E09", "E12", "P1"):
        g.n(f"sel{e}", g.contains(f"sel{e}C", "i1Sel", g.k(e)))
    g.n("haveE05", g.contains("haveE05C", "i1Have", g.k("E05")))
    for ln in ASK[:-1]:
        g.n(f"said{ln}", g.contains(f"said{ln}C", "i1Said", g.k(ln)))
    cond = {"L008": "haveE05 && !selE05", "L004": "selP1", "L003": "selE12", "L006": "selE09", "L007": "selE03",
            "L011": f"selN < {CARRY_MAX}"}
    expr = " : ".join(f"({cond[ln]}) && !said{ln} ? {i}" for i, ln in enumerate(ASK[:-1])) + f" : {len(ASK) - 1}"
    g.x("askI", expr)
    g.lookup("askLine", [f"SCR_D01_S06_{ln}" for ln in ASK], "askI")
    g.lookup("askId", ASK, "askI")
    askP = g.when("askG", f"{CAR}.ask", T("askOk", "d_cph == 0"))
    sets(askP, "w1", g.k("SPK_ARTHUR"))
    sets(askP, "s1", "askLine")
    g.x("askBoard", f"askI == {ASK.index('L004')}")
    sets(askP, "w2", g.sel("askW2", "askBoard_t", g.k("SPK_SHEREFOX"), g.k("")))
    sets(askP, "s2", g.sel("askS2", "askBoard_t", g.k("SCR_D01_S06_L005"), g.k("")))
    g.edge(g.when("askSaidG", askP, T("askSay", f"askI < {len(ASK) - 1}")),
           g.eff("saidAdd", "atrium.coll.add", "i1Said", value="askId"))
    g.counter("saySeq", initial=0)
    g.edge(g.merge("sayM", askP, fullP), "saySeq.increment")
    for k in ("w1", "s1", "w2", "s2"):
        g.text(f"{k}T", f"s_{k}")
    g.edge("w1T", f"{CAR}.who1")
    g.edge("s1T", f"{CAR}.say1")
    g.edge("w2T", f"{CAR}.who2")
    g.edge("s2T", f"{CAR}.say2")
    # confirm: the found items not chosen, named (never what he will pick up, ch §13)
    parts = []
    acc = g.k("")
    for i in ITEMS:
        g.n(f"lh{i}", g.contains(f"lh{i}C", "i1Have", g.k(i)))
        g.n(f"ls{i}", g.contains(f"ls{i}C", "i1Sel", g.k(i)))
        g.x(f"lf{i}", f"lh{i} && !ls{i}")
        name = g.text(f"ln{i}", g.k(item_keys(i)[0]))
        part = g.sel(f"lp{i}", f"lf{i}_t", name, g.k(""))
        empty = g.cmp(f"le{i}", acc, g.k(""))
        joined = g.sel(f"lj{i}", empty, part, g.fmt(f"lc{i}", "{a}{b}{c}", acc, sep, name))
        acc = g.sel(f"la{i}", f"lf{i}_t", joined, acc)
        parts.append(f"lf{i}")
    g.x("nLeft", " + ".join(parts))
    # v2 demo E6 (V3, ruling c): L010 plays while anything he could pick up stays in the house, found or not (ref
    # model.pickups_for: the pickup priority's evidence with an opponent use, not carried); nothing names it
    g.x("nPick", " + ".join(f"!ls{i}" for i in PICKABLE))
    g.edge(g.textf("confT", key="SCR_D01_S06_L009", list=acc), f"{CAR}.confirm_text")
    cfP = g.when("confG", f"{CAR}.confirm", T("confOk", "d_cph == 0"))
    seti(g.when("confAskG", cfP, T("confAsk", "nLeft > 0")), "cph", g.k(1))
    noList = g.when("confNoListG", cfP, T("confNoList", "nLeft == 0"))
    goNow = g.when("confGoG", noList, T("confGo", "nPick == 0"))
    seti(g.merge("noM", f"{CAR}.no"), "cph", g.k(0))
    yP = g.when("yesG", f"{CAR}.yes", T("yesOk", "d_cph == 1"))
    # L010 (S06; E6 V3: while he could pick something up); a click goes on
    l10 = g.when("l10G", g.merge("l10M", yP, noList), T("l10On", "nPick > 0"))
    seti(l10, "cph", g.k(2))
    sets(l10, "w1", g.k("SPK_ARTHUR"))
    sets(l10, "s1", g.k("SCR_D01_S06_L010"))
    sets(l10, "w2", g.k(""))
    sets(l10, "s2", g.k(""))
    g.edge(l10, "saySeq.increment")
    goYes = g.when("yesGoG", yP, T("yesGo", "nPick == 0"))
    goClick = g.when("goG", f"{CAR}.go", T("goOk", "d_cph == 2"))
    go = g.merge("goM", goNow, goYes, goClick)
    seti(go, "cph", g.k(0))
    # the loadout for the debate (data order), then the step ends (the debate starts 0.1 s after its step begins)
    for coll, src, have in (("d1Carry", "i1All", "i1Sel"), ("d1Appraised", "i1AAll", "i1Appr"),
                            ("d1Notes", "i1NAll", "i1Notes")):
        g.edge(go, g.eff(f"clr_{coll}", "atrium.coll.clear", coll))
        g.node(f"lo{coll}", "atrium.coll.forEach", name=src)
        g.edge(go, f"lo{coll}.trigger")
        g.edge(g.when(f"lo{coll}G", f"lo{coll}.each", g.contains(f"lo{coll}C", have, f"lo{coll}.item")),
               g.eff(f"lo{coll}Add", "atrium.coll.add", coll, value=f"lo{coll}.item"))
    g.edge(g.when("goDone", go, "isCarK.out"), "world.stepDone")
    return g
