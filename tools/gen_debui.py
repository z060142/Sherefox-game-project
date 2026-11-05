"""The debate UI and result flows (M4c), imported by tools/gen_flows.py: flows/debate_ui.xtflow (debate and warmup
steps: the engine's inputs, its outputs on ui#debate and ui#cutin, the player's choices, the reveal playback) and
flows/result.xtflow (result steps: ui#result, the case's consequences), their support tables under data/flow/ and
the game.json entries they add. See docs/flows.md §4.8 and §4.9; the engine interface is docs/debate-engine.md §2.

Same rules as gen_flows (edge order, no feedback, collections are read back on the next tick): the UI's own state
lives in the maps `dbui` (numbers) and `dbuiS` (strings), written by effects and read by queries; a step that must
read what a pulse wrote runs on a timer. The engine's outputs (world.deb*) are latched when a round is shown, so the
screen keeps the round's tell and state while the next round's values are already on the bus.
"""

from __future__ import annotations

import json
from collections import Counter

import gen_flows as F
from gen_flows import Graph, Mux, load, split

PA = ["solid", "sophistry", "rebut", "observe"]          # debCmdKind words (opponents.playerActions), act 1..4
OA = ["assert", "rush", "reinforce", "trap", "scorched"]  # engine action words; reveal_opp 0..4
STAGING = ["player_attack_vs_defense", "defense_vs_attack", "clash", "standoff"]   # reveal_combo 0..3
BASIS_KEY = {"tutorial": "UI_DEB_TELL_BASIS_TUTORIAL", "observe": "UI_DEB_TELL_BASIS_OBSERVE",
             "rule3": "UI_DEB_TELL_BASIS_RULE__3", "konju": "UI_DEB_TELL_BASIS_KONJU",
             "fox": "UI_DEB_TELL_BASIS_INSTINCT"}   # "script" (the tail) and "" show no badge
TYPE_KEY = {"culprit": "UI_TYPE_CRIMINAL", "protector": "UI_TYPE_PROTECTOR", "rival": "UI_TYPE_RIVAL",
            "nemesis": "UI_TYPE_NEMESIS", "mixed": "UI_TYPE_MIXED", "": ""}
# Playback timing (01-systems §4.4 揭示演出: a round 3-6 s, cards fly in and flip in 0.5 s; §4.7: a full-screen
# cut-in about 1.5 s, 論破 about 4 s, a stamp 0.5 s). Dwell after a record: 0 next tick, 1 a number / stamp / line,
# 2 the reveal (cards and the statement), 3 a full-screen cut-in, 4 論破.
DWELL = [0.001, 0.6, 1.4, 1.6, 4.0]
START_DELAY = 0.1   # debStart / debLock / debInstinct -> the engine's outputs are on the bus (pulses cross graphs a tick late)
HOLD = 1.5          # the settled numbers stay before the next round (or `next`)
FINISH = 1.2        # phase 3 (debate over) before the step ends (or `next`)
FRAGILE_MAX = 12    # F1..F12 (the engine numbers fragile nodes F<n>)
SLOTS = 15          # chain slots of debBoard (docs/debate-engine.md §2.2)
SEG = 5             # longest segment (01-systems §2.5)

COLLECTIONS = {
    "dbui": {"kind": "map", "type": "number", "capacity": 32},
    "dbuiS": {"kind": "map", "type": "string", "capacity": 16},
    "caseMod": {"kind": "map", "type": "number", "capacity": 4},     # this case only: warmup trust (A-13, §3.1)
    "progress": {"kind": "map", "type": "number", "capacity": 8},    # across chapters: trust (offset from 3)
    "uiNodeIds": {"kind": "list", "type": "string", "capacity": 16},
    "uiShat": {"kind": "list", "type": "string", "capacity": 16, "unique": True},
    "uiNodes": {"kind": "list", "type": "string", "capacity": 16},
    "uiChains": {"kind": "list", "type": "string", "capacity": SLOTS},
    "uiCands": {"kind": "list", "type": "string", "capacity": 24, "unique": True},
    "uiParryAll": {"kind": "list", "type": "string", "capacity": 24},
    "uiParry": {"kind": "list", "type": "string", "capacity": 24},
    "evF": {"kind": "list", "type": "string", "capacity": 8},
    "evN": {"kind": "list", "type": "number", "capacity": 8},
    "resStats": {"kind": "map", "type": "string", "capacity": 12},
    "resCosts": {"kind": "list", "type": "string", "capacity": 8},
}
SIGNALS = {
    "resultLines": {"type": "pulse"},                    # result -> main, dialogue: play the result scene's lines
    "resultBranch": {"type": "string", "initial": "win"},  # script.branch of those lines (win / lose)
    "debRetry": {"type": "pulse"},                       # result -> main: back to the debate step (A-14 retry)
}


# ---------------------------------------------------------------------------------------------- support tables

def speaker_chars() -> dict[str, str]:
    """speaker key -> the vn character id it is shown as most often (script: focus slot of its lines)."""
    c: Counter = Counter()
    for r in load("script"):
        f = r["focus"]
        if f:
            c[(r["speaker"], [r["slot_l"], r["slot_c"], r["slot_r"]][f - 1])] += 1
    best: dict[str, tuple[int, str]] = {}
    for (spk, char), n in c.items():
        if char and (spk not in best or n > best[spk][0]):
            best[spk] = (n, char)
    return {k: v[1] for k, v in best.items()}


def result_line(case: str, chapter: int, scene: str, speaker: str) -> str:
    """The opponent's closing line: in the last round of the debate scene, the opponent's first plain line (no
    action marker). Ch.1 SCR_CH01_S05_L028, Ch.2 SCR_CH02_S05_L046."""
    rows = [r for r in load("script") if r["chapter"] == chapter and r["scene"] == scene and r["playable"]]
    if not rows:
        return ""
    last = max(r["round"] for r in rows)
    for r in rows:
        if r["round"] == last and r["speaker"] == speaker and not r["act"]:
            return r["text"]
    return ""


# Defeat costs (10-cases): Ch.2 E02_01 leaves with the client and G-01 becomes S-01; Ch.3 E03_04 is seized and the
# trust drops (the trust row is added by the flow when the trust falls). The seized-card lines are the expanded
# UI_RES_COST_SEIZE keys (tools/build_data.py expand_templates).
LOSE_COSTS = {2: (["UI_RES_COST_SEIZE__E02_01"], "G-01"), 3: (["UI_RES_COST_SEIZE__E03_04"], "")}


def tables() -> dict[str, list[dict]]:
    opps = load("opponents")
    nodes = load("nodes")
    steps = load("steps")
    ev = load("evidence")
    chars = speaker_chars()
    case_rows = []
    for o in opps:
        mode = 2 if o["kind"] == "pudding" else 1 if o["kind"] == "warmup" else 0
        st = next((s for s in steps if s["arg"] == o["id"]), None)
        line = result_line(o["id"], o["chapter"], st["scene"], o["speaker"]) if st and mode != 1 else ""
        costs, ungold = LOSE_COSTS.get(o["chapter"], ([], "")) if mode == 0 else ([], "")
        after = [e["id"] for e in ev if e["chapter"] == o["chapter"] and e["obtain"] == "afterDebate"] if mode != 1 else []
        case_rows.append({"id": o["id"], "chapter": o["chapter"], "mode": mode, "char": chars.get(o["speaker"], ""),
                          "nameKey": o["speaker"], "typeKey": TYPE_KEY[o["type"]], "handPer": o["handPerMissed"],
                          "hpPer": o["hpPerMissed"], "hand": o["hand"] if mode == 1 else "",
                          "soph": int("sophistry" in split(o["playerActions"])),
                          "winLine": line, "costs": ",".join(costs), "ungold": ungold, "after": ",".join(after)})

    word = ([{"key": f"pa:{w}", "code": i, "text": ""} for i, w in enumerate(PA)]
            + [{"key": f"oa:{w}", "code": i, "text": ""} for i, w in enumerate(OA)]
            + [{"key": f"st:{w}", "code": i, "text": ""} for i, w in enumerate(STAGING)]
            + [{"key": f"basis:{k}", "code": 0, "text": v} for k, v in BASIS_KEY.items()])

    # nodes list rows: "id|state" (state 0 normal, 1 lit, 2 fragile, 3 second claim, 4 shattering)
    ids = [(n["id"], n["textKey"]) for n in nodes] + [(f"F{i}", "") for i in range(1, FRAGILE_MAX + 1)]
    node_view = [{"key": f"{i}|{s}", "id": i, "textKey": t, "state": s, "src": ""} for i, t in ids for s in range(5)]

    # chains list rows: "slot|card|link|sel" (link 0 none, 1 solid, 2 sophistry, 5 assisted, 6 cut this round)
    cards = [e for e in ev if e["onBoard"]]
    chain_view = []
    for s in range(SLOTS):
        links = (0, 1, 2, 5, 6) if s % 5 < 4 else (0,)
        for e in cards:
            for lk in links:
                for sel in (0, 1):
                    chain_view.append({"key": f"{s}|{e['id']}|{lk}|{sel}", "chain": s // 5, "pos": s % 5,
                                       "id": e["id"], "nameKey": e["nameKey"], "link": lk, "sel": bool(sel)})

    # result line per event record (01-systems §8.6, §8.7): key "case|kind|sub" (sub: reveal "player/opponent",
    # nodeRemoved the reason, nodeAdded the reason, otherwise the first field). Speaker-dependent lines use the
    # expanded keys <KEY>__<speaker>.
    ev_rows = []
    for o in opps:
        cid, spk = o["id"], o["speaker"]

        def put(kind: str, sub, line: str, dwell: int = 1) -> None:
            ev_rows.append({"key": f"{cid}|{kind}|{sub}", "line": line, "dwell": dwell if line else 0})

        for p in PA:
            for a in OA[:4]:
                if p in ("solid", "sophistry"):
                    line = ("MSG_DEB_CLASH" if a in ("assert", "rush") else
                            ("MSG_DEB_REINFORCE_HALF" if p == "solid" else "MSG_DEB_HIT") if a == "reinforce" else
                            f"MSG_DEB_TRAP_MISS__{spk}" if p == "solid" else "MSG_DEB_TRAP_HIT")
                elif p == "rebut":
                    line = "" if a in ("assert", "rush") else "MSG_DEB_PARRY_WHIFF"   # a hit: MSG_DEB_PARRY__<n>
                else:
                    line = ("MSG_DEB_OBSERVE_HALF" if a in ("assert", "rush") else
                            f"MSG_DEB_SLIP__{spk}" if a == "reinforce" else f"MSG_DEB_TRAP_EXPOSED__{spk}")
                put("reveal", f"{p}/{a}", line)
        for reason in ("chain", "parry"):
            put("nodeRemoved", reason, "MSG_DEB_SMASH")
        put("nodeRemoved", "fragile_hit", "MSG_DEB_FRAGILE_HIT")
        put("nodeAdded", "reinforce", f"MSG_DEB_REINFORCE__{spk}")
        put("nodeAdded", "observe", f"MSG_DEB_SLIP__{spk}")
        put("nodeAdded", "tail_start", f"MSG_TAIL_SECOND__{spk}")
        put("statusGained", "shaken", f"MSG_DEB_SHAKEN__{spk}")
        put("statusGained", "tail", f"MSG_TAIL_START__{spk}")
        put("break", "1", "UI_BREAK_LINE")
        put("breakVoided", "", f"MSG_TAIL_TIMEOUT__{spk}")
        put("tailResult", "0", "MSG_TAIL_WRONG__30")
        for n in range(1, 5):
            put("contradiction", n, f"MSG_CH1_CONTRA__{n}")
        put("linkSnapped", "", "MSG_DEB_LINK_CUT")
        put("infamy", "", "MSG_DEB_WEAK_HIT")
        put("msg", "MSG_DEB_PARRY_BREAK_MISS", "MSG_DEB_PARRY_BREAK_MISS")
        put("msg", "MSG_DEB_ASSIST_WASTED", "MSG_DEB_ASSIST_WASTED")
        put("msg", "ASSIST_BLOCKED", "MSG_DEB_ASSISTED")
        put("wCorrected", "CH03_W1", "MSG_DEB_SMASH")
        for n in range(1, 4):
            put("wMistake", n, "MSG_WARMUP_WRONG")
        put("wAutoCorrected", "CH03_W1", f"MSG_WARMUP_FAIL__{spk}")
        put("wEnded", "1", "MSG_WARMUP_PERFECT")
    # (linkSnapped / infamy / breakVoided go by kind only: the flow looks them up with an empty sub field)

    # cut-in records -> the cutin surface: key "id|full" (full: a full-screen cut-in that plays; a demoted one is
    # shown as a stamp when it has one: 破竹 3 -> the 破竹 stamp ×3, 01-systems §4.7 例 2)
    cut = []
    for cid in ("CUT_RONPA", "CUT_SHAKEN", "CUT_HACHIKU3", "CUT_KONJU", "CUT_SHISSHU", "CUT_BRINK", "CUT_REVERSE",
                "CUT_DOUBLE", "CUT_COUNTER"):
        cut.append({"key": f"{cid}|1", "big": cid, "stamp": "", "n": 0, "sub": cid + "_SUB",
                    "dwell": 4 if cid == "CUT_RONPA" else 3})
        cut.append({"key": f"{cid}|0", "big": "", "stamp": "STAMP_HACHIKU" if cid == "CUT_HACHIKU3" else "",
                    "n": 3 if cid == "CUT_HACHIKU3" else 0,
                    "sub": "STAMP_HACHIKU_SUB__3" if cid == "CUT_HACHIKU3" else "",
                    "dwell": 1 if cid == "CUT_HACHIKU3" else 0})
    for sid in ("STAMP_PARRY", "STAMP_TRAP", "STAMP_WHIFF", "STAMP_CLASH", "STAMP_SEEN", "STAMP_ASSIST",
                "STAMP_HACHIKU", "STAMP_HACHIKU_LOST"):
        cut.append({"key": f"{sid}|0", "big": "", "stamp": sid, "n": 0,
                    "sub": "" if sid == "STAMP_HACHIKU" else sid + "_SUB", "dwell": 1})
    for n in (1, 2, 3):   # the engine's (ref's) 破竹 stamps per layer -> the 破竹 stamp ×n
        cut.append({"key": f"STAMP_HACHIKU{n}|0", "big": "", "stamp": "STAMP_HACHIKU", "n": n,
                    "sub": f"STAMP_HACHIKU_SUB__{n}", "dwell": 1})
    return {"flowDebCase": case_rows, "flowWord": word, "flowNodeView": node_view, "flowChainView": chain_view,
            "flowEvLine": ev_rows, "flowCut": cut}


# ---------------------------------------------------------------------------------------------- helpers

def find_f(g: Graph, name: str, table: str, column: str, value: str, fcol: str, fval: str) -> str:
    """atrium.table.find with a dynamic filter: column == value and fcol == fval (inputs)."""
    g.node(name, "atrium.table.find", table=table, column=column, filterColumn=fcol)
    g.edge(value, f"{name}.value")
    g.edge(fval, f"{name}.filterValue")
    return g.put(name, f"{name}.row")


def add_all(g: Graph, name: str, coll: str, text: str, sep: str = ",") -> str:
    g.node(name, "atrium.coll.addAll", name=coll, separator=sep)
    g.edge(text, f"{name}.text")
    return f"{name}.trigger"


def truth(g: Graph):
    """T(name, expr): an atrium.expr whose truth is the condition (for when / sel)."""
    def make(name: str, expr: str) -> str:
        g.x(name, expr)
        return name + "_t"
    return make


def setter(g: Graph, coll: str):
    seq = [0]

    def put(pulse: str, key: str, value: str) -> None:
        seq[0] += 1
        g.edge(pulse, g.eff(f"{coll}_{key}_{seq[0]}", "atrium.map.set", coll, key=g.k(key), value=value))
    return put


def ssel(g: Graph, name: str, cases: list[tuple[str, str]], default: str) -> str:
    """String select chain: the value of the first (bool condition, value) that holds, else default."""
    cur = default
    for i, (cond, val) in reversed(list(enumerate(cases))):
        cur = g.sel(f"{name}_{i}", cond, val, cur)
    return g.put(name, cur)


def slim_card(g: Graph, pre: str, card: str, tags: bool = False) -> None:
    """<pre>_full (no hidden tag, appraised, or the police report reveals it; gen_flows card_values) and, with
    tags, <pre>_t0.. (flowCard tag0..) for a card id port."""
    row = g.tfind(pre + "_row", "flowCard", "id", card)
    g.tget(pre + "_hid", "flowCard", "hidden", row, "number")
    g.tget(pre + "_pol", "flowCard", "policeFull", row, "number")
    g.n(pre + "_apr", g.contains(pre + "_aprC", "appraised", card))
    g.x(pre + "_full", f"!{pre}_hid || {pre}_apr || (policeOn && {pre}_pol)")
    if tags:
        for j in range(F.max_tags()):
            g.tget(f"{pre}_t{j}", "flowCard", f"tag{j}", row)


def refutes(g: Graph, pre: str, card: str, case: str) -> None:
    """<pre>_ref: the card refutes the lit node (debCard r1..r3 by the lit node's pool index, rT for the tail node);
    <pre>_strong, <pre>_brk (Ch.1 break card)."""
    g.fmt(pre + "_ck", "{a}:{b}", case, card)
    row = g.tfind(pre + "_crow", "debCard", "key", pre + "_ck")
    for c in ("r1", "r2", "r3", "rT", "strong", "brk"):
        g.tget(f"{pre}_{c}", "debCard", c, row, "number")
    g.x(pre + "_ref", f"litIdx == 1 ? {pre}_r1 : litIdx == 2 ? {pre}_r2 : litIdx == 3 ? {pre}_r3 : "
                      f"litTail ? {pre}_rT : 0")


# ---------------------------------------------------------------------------------------------- debate UI

def gen_debui() -> Graph:
    """debate and warmup steps (01-systems §4.4, A-13; ui-contracts debate, cutin; docs/flows.md §4.8)."""
    g = Graph()
    T = truth(g)
    F.chapter_values(g)
    g.put("langEn", g.cmp("langEnC", "world.language", g.k("en")))
    g.n("isDebN", g.cmp("isDebC", "world.stepKind", g.k("debate")))
    g.n("isWarmN", g.cmp("isWarmC", "world.stepKind", g.k("warmup")))
    g.n("isPaperN", g.cmp("isPaperC", "world.stepKind", g.k("paper")))
    g.x("activeN", "isDebN || isWarmN")
    begin = g.when("beginG", "world.stepBegin", "activeN_t")
    setn, sets = setter(g, "dbui"), setter(g, "dbuiS")

    # A chapter begins with its paper: the case modifiers (warmup trust) start again.
    g.edge(g.when("paperG", "world.stepBegin", "isPaperC.out"), g.eff("clrCaseMod", "atrium.map.clear", "caseMod"))

    # ---- the case (written to the engine; a graph does not read back its own world writes, so use the latch)
    case = g.latch("case", "world.stepArg", begin)
    g.edge(case, "world.debCase")
    g.edge(g.k(""), "world.debScript")        # the engine's script id = debCase (data/debScript.json, ruling G2)
    crow = g.tfind("dcRow", "flowDebCase", "id", case)
    for c in ("mode", "handPer", "hpPer", "soph"):
        g.tget("dc_" + c, "flowDebCase", c, crow, "number")
    for c in ("char", "nameKey", "typeKey", "hand"):
        g.tget("dc_" + c, "flowDebCase", c, crow)
    erow = g.tfind("ecRow", "debCase", "id", case)
    for c in ("ssOn", "brChain", "ch1", "conD", "conT", "rcap", "base", "fox", "assists", "cap"):
        g.tget("ec_" + c, "debCase", c, erow, "number")
    g.tget("ec_t", "debCase", "t", erow)
    # missed cards (01-systems §1.8, ruling D4): hand +handPerMissed and HP +hpPerMissed each, from debStart on
    g.count("missed", "oppHand")
    g.x("bonus", "isDebN ? missed * dc_hpPer : 0")
    g.edge("bonus", "world.debOppBonus")
    g.x("handN", "isDebN ? missed * dc_handPer : 0")

    # ---- UI state (map dbui; slots are stored + 1, 0 = none)
    for k in ("ph", "act", "sa", "sb", "segPh", "armed", "fast", "ev", "hold", "fin", "maxd", "maxc", "brks", "hpO", "hpM"):
        g.mget("d_" + k, "dbui", g.k(k))
    for k in ("card", "target", "msg", "rl", "fo", "fm"):
        g.mget("s_" + k, "dbuiS", g.k(k))

    # ---- engine outputs, latched when a round is shown (snap) so the screen keeps the round's tell and state
    snap = g.merge("snap")   # inputs added below (round start, after the instinct)
    num = ["debRound", "debTellStarRule", "debShaken", "debInTail", "debTailLeft", "debHachiku", "debHachikuMode",
           "debKonju", "debShisshu", "debContra", "debInstinctLeft", "debAssist", "debVoids", "debPlayerMax",
           "debOppMax", "debFragile", "dwRound", "dwMistakes"]
    txt = ["debTellClarity", "debTellShown1", "debTellShown2", "debTellStar", "debTellBasis", "debTellLit",
           "debTellGesture", "debTellLine", "dwClaim"]
    for sig in num + txt:
        g.latch("L_" + sig[3:] if sig.startswith("deb") else "L_" + sig, f"world.{sig}", snap)
    g.count("onCnt", "debOn")
    g.latch("L_on", "onCnt", snap)
    g.put("L_dwClaim", "L_dwClaim.out")
    lit = g.sel("lit", "isWarmC.out", "L_dwClaim", "L_TellLit")
    g.n("hasLitN", g.cmp("hasLitC", lit, g.k(""), "ne"))
    lrow = g.tfind("litRow", "debNode", "id", lit)
    g.tget("litIdx", "debNode", "idx", lrow, "number")
    g.n("litTail", g.cmp("litTailC", lit, "ec_t", "eq"))
    g.x("breakR", "L_Shaken == 1 && !L_InTail")                  # 論破回合 (A-8): the round after the trigger
    g.x("tailN", "L_InTail")
    g.x("shiss", "ec_ssOn && L_Shisshu > 0")

    # ---- board reads: links (debBoardLink) and links cut this round (debSnap: slot -> last round it is cut)
    for i in range(SLOTS - 1):
        g.cget(f"bl{i}", "debBoardLink", g.k(i))
        g.mget(f"snv{i}", "debSnap", g.k(str(i)))
        g.x(f"brk{i}", f"{i % 5} == 4 || bl{i} == 0 || snv{i} >= L_Round")
    g.x("sophAvail", " + ".join(f"(bl{i} == 2 && snv{i} < L_Round)" for i in range(SLOTS - 1) if i % 5 < 4))

    # ---- the segment (dbui sa/sb: the chosen slots + 1)
    g.x("segA", "d_sa - 1")
    g.x("segB", "d_sb - 1")
    g.x("segLo", "min(segA, segB)")
    g.x("segHi", "max(segA, segB)")
    g.x("segL", "d_sa > 0 ? segHi - segLo + 1 : 0")
    g.x("segSoph", " + ".join(f"(segLo <= {i} && {i} < segHi && bl{i} == 2)" for i in range(SLOTS - 1)))
    hasT = g.cmp("hasTgt", "s_target", g.k(""), "ne")
    tgt = g.sel("tgt", hasT, "s_target", lit)
    trow = g.tfind("tRow", "nodes", "id", tgt)
    g.n("tOn", g.contains("tOnC", "debOn", tgt))
    g.x("tOk", "tOn && tRow >= 0")
    share, segref, segfull, strong, brkc, names = [], [], [], [], [], []
    for k in range(SEG):
        g.x(f"q{k}s", f"segLo + {k}")
        q = g.cget(f"q{k}", "debBoard", f"q{k}s")
        g.cget(f"q{k}ok", "debBoardOk", f"q{k}s")
        g.x(f"in{k}", f"d_sa > 0 && {k} < segL")
        slim_card(g, f"q{k}", q, tags=True)
        refutes(g, f"q{k}", q, case)
        hits = []
        for j in range(F.max_tags()):
            g.n(f"q{k}h{j}", g.thas(f"q{k}hC{j}", "nodes", "tags", "tRow", f"q{k}_t{j}"))
            hits.append(f"q{k}h{j}")
        share.append(f"(in{k} && ({' || '.join(hits)}))")
        segref.append(f"(in{k} && q{k}_ref)")
        segfull.append(f"(in{k} && !q{k}_full)")
        strong.append(f"(in{k} && q{k}_strong && q{k}ok)")
        brkc.append(f"(in{k} && q{k}_brk && q{k}ok)")
    g.x("segShare", " + ".join(share))
    g.x("segRef", " + ".join(segref))
    g.x("segHidden", " + ".join(segfull))
    g.x("segStrong", " + ".join(strong))
    g.x("segBrk", " + ".join(brkc))
    # break threshold (A-8, ruling B18, ref rules.break_threshold_met): Ch.1 = E01_03 with the right reason
    g.x("thrRed", "L_HachikuMode == 2 && L_Hachiku >= 3")
    g.x("thr", "ec_ch1 ? segBrk > 0 : segSoph == 0 && (segL >= max(1, ec_brChain + L_Voids - thrRed) || "
               "(segStrong > 0 && segL >= max(1, 1 + L_Voids - thrRed)))")
    # the single card of a rebut
    hasCard = g.cmp("hasCard", "s_card", g.k(""), "ne")
    g.n("hasCardN", hasCard)
    slim_card(g, "pc", "s_card")
    refutes(g, "pc", "s_card", case)

    # ---- what can be pressed (01-systems §4.4 四個行動按鈕, A-13: the warmup only rebuts)
    g.count("parryCnt", "uiParryAll")
    g.count("chainCnt", "uiChains")
    g.x("en1", "isDebN && chainCnt > 0")
    g.x("en2", "isDebN && dc_soph && sophAvail > 0")
    g.x("en3", "hasLitN && !shiss && (parryCnt > 0 || (isDebN && (breakR || tailN)))")
    g.x("en4", "isDebN")
    why1 = g.sel("why1", "en1_t", g.k(""), g.k("MSG_DEB_NO_TARGET"))
    why2 = g.sel("why2", g.b("w2c", g.x("w2n", "dc_soph && !en2")), g.k("MSG_DEB_NOSOPH"), g.k(""))
    msg3 = g.sel("msg3", "shiss_t", g.k("MSG_DEB_NOPARRY_SHISSHU"), g.k("MSG_DEB_NOPARRY_NOCARD"))

    # ---- can it be locked
    g.x("ok1", "segL >= 1 && segSoph == 0 && tOk && segShare > 0")
    g.x("ok2", "segL >= 1 && segSoph > 0 && tOk && segShare > 0")
    g.x("ok3", "hasLitN && !shiss && (hasCardN ? pc_ref && (pc_full || isWarmN) : "
               "segL >= 1 && (breakR || tailN) && segRef > 0 && segHidden == 0 && (tailN || thr))")
    g.x("canLock", "d_ph == 0 && activeN && (d_act == 1 ? ok1 : d_act == 2 ? ok2 : d_act == 3 ? ok3 : d_act == 4)")
    g.edge("canLock.truth", "ui#debate.can_lock")

    # ---- summary (confirmation line) and preview. The templates have named placeholders (framework request:
    # atrium.textf), so the line is the localized pieces joined by spaces (as the board's tag line).
    act_btn = g.lookup("actBtn", ["", "BTN_DEB_SOLID", "BTN_DEB_SOPH", "BTN_DEB_PARRY", "BTN_DEB_OBSERVE"], "d_act")
    g.text("actBtnT", act_btn)
    g.tget("tgtKey", "nodes", "textKey", "tRow")
    lrow2 = g.tfind("litRowN", "nodes", "id", lit)
    g.tget("litKey", "nodes", "textKey", lrow2)
    g.text("tgtT", "tgtKey")
    g.text("litT", "litKey")
    for nm, card in (("a", "q0"), ("b", "segLast"), ("c", "s_card")):
        if nm == "b":
            g.x("qLs", "segHi")
            card = g.cget("segLast", "debBoard", "qLs")
        r = g.tfind(f"nm{nm}Row", "flowCard", "id", card)
        g.text(f"nm{nm}T", g.tget(f"nm{nm}Key", "flowCard", "nameKey", r))
    g.fmt("segArrow", "{a} → {b}", "nmaT", "nmbT")
    segText = g.sel("segText", g.b("segMultiC", g.x("segMulti", "segL > 1")), "segArrow", "nmaT")
    showT = g.sel("showT", hasCard, "nmcT", segText)
    g.fmt("sumAtk", "{a}　{b}　{c}", "actBtnT", "tgtT", segText)
    g.fmt("sumParry", "{a}　{b}　{c}", "actBtnT", "litT", showT)
    g.text("sumObs", g.k("UI_DEB_LOCK_SUMMARY_OBSERVE"))
    # a hint while it cannot be locked
    hint = ssel(g, "hint", [
        (g.b("h1c", g.x("h1", "(d_act == 1 || d_act == 2) && segL == 0")), g.k("MSG_DEB_SELECT_CHAIN")),
        (g.b("h2c", g.x("h2", "d_act == 1 && segSoph > 0")), g.k("MSG_DEB_NOSOLID")),
        (g.b("h3c", g.x("h3", "d_act == 2 && segSoph == 0")), g.k("MSG_DEB_NOSOPH")),
        (g.b("h4c", g.x("h4", "(d_act == 1 || d_act == 2) && segShare == 0")), g.k("MSG_DEB_NOTAG")),
        (g.b("h5c", g.x("h5", "d_act == 3")), g.k("MSG_DEB_SELECT_PARRY"))], g.k(""))
    g.text("hintT", hint)
    g.text("msgT", "s_msg")
    body = ssel(g, "sumBody", [(g.b("sb4", g.x("sb4n", "d_act == 4")), "sumObs.text"),
                               (g.b("sb3", g.x("sb3n", "d_act == 3")), "sumParry"),
                               (g.b("sb12", g.x("sb12n", "d_act == 1 || d_act == 2")), "sumAtk")], g.k(""))
    hasMsg = g.cmp("hasMsg", "s_msg", g.k(""), "ne")
    summary = ssel(g, "summary", [(hasMsg, "msgT.text"),
                                  (g.b("sumLk", g.x("sumLkN", "d_act > 0 && !canLock")), "hintT.text")], body)
    g.edge(g.sel("summaryOut", g.b("sumPh0", g.x("sumPh0N", "d_ph == 0")), summary, g.k("")), "ui#debate.summary")
    # preview (§4.4 預估列): attack damage 14 x (1 + 0.5 solid + 0.8 sophistry) x 動搖 1.5 x 破竹, as the engine
    g.x("segSolid", "segL - 1 - segSoph")
    g.x("pvDmg", "14 * (10 + 5 * segSolid + 8 * segSoph) / 10 * (breakR ? 3 / 2 : 1) * "
                 "(L_HachikuMode == 2 ? (10 + L_Hachiku) / 10 : 1)")
    pvExtra = ssel(g, "pvExtra", [(g.b("pvBr", g.x("pvBrN", "d_act == 1 && breakR && thr")), g.k("UI_DEB_PREVIEW_BREAK")),
                                  (g.b("pvSh", g.x("pvShN", "breakR")), g.k("UI_DEB_PREVIEW_SHAKEN"))], g.k(""))
    g.text("pvExtraT", pvExtra)
    g.fmt("pvAtk", "{a}　{b}", "pvDmg", "pvExtraT")
    g.text("pvParry", g.k("UI_DEB_PREVIEW_PARRY"))
    preview = ssel(g, "preview", [(g.b("pv12", g.x("pv12n", "(d_act == 1 || d_act == 2) && segL > 0")), "pvAtk"),
                                  (g.b("pv3", g.x("pv3n", "d_act == 3 && isDebN")), "pvParry.text")], g.k(""))
    g.edge(preview, "ui#debate.preview")
    g.edge(g.k(""), "ui#debate.preview_vs")

    # ---- plain ports
    g.edge("dc_mode", "ui#debate.mode")
    g.edge("dc_char", "ui#debate.opp_char")
    g.text("oppName", "dc_nameKey")
    g.edge("oppName.text", "ui#debate.opp_name")
    g.text("oppType", "dc_typeKey")
    g.edge("oppType.text", "ui#debate.opp_type")
    g.edge(g.x("hpMShow", "max(0, d_hpM)"), "ui#debate.hp_me")     # the engine's HP can go below 0
    g.edge("L_PlayerMax", "ui#debate.hp_me_max")
    g.edge(g.x("hpOShow", "max(0, d_hpO)"), "ui#debate.hp_opp")
    g.edge("L_OppMax", "ui#debate.hp_opp_max")
    g.x("roundN", "isWarmN ? L_dwRound : L_Round")
    g.fmt("roundKey", "UI_DEB_ROUND__{a}", "roundN")
    g.text("roundT", g.sel("roundKeyOn", g.b("roundOn", g.x("roundOnN", "roundN > 0")), "roundKey", g.k("")))
    g.edge("roundT.text", "ui#debate.round_text")
    g.x("rLeft", "max(0, L_Contra < ec_conT ? ec_conD - L_Round + 1 : ec_rcap - L_Round + 1)")
    # (a latch that passes 0 first pushes nothing into a format: numbers go through an expression)
    g.x("contraN", "L_Contra + 0")
    g.x("missN", "L_dwMistakes + 0")
    g.fmt("ctrCh1", "UI_CH1_CONTRA__{a}_{b}", "contraN", "rLeft")
    g.fmt("ctrWarm", "UI_WARMUP_MISS__{a}", "missN")
    ctr = ssel(g, "ctrKey", [(g.b("ctrIs2", g.x("ctrIs2N", "dc_mode == 2 && roundN > 0")), "ctrCh1"),
                             (g.b("ctrIs1", g.x("ctrIs1N", "dc_mode == 1 && roundN > 0")), "ctrWarm")], g.k(""))
    g.text("ctrT", ctr)
    g.edge("ctrT.text", "ui#debate.counter_text")
    # tell (§4.4 預兆顯示)
    for nm, sig in (("ts1", "L_TellShown1"), ("ts2", "L_TellShown2"), ("tst", "L_TellStar")):
        g.fmt(nm + "K", "oa:{a}", sig)
        r = g.tfind(nm + "R", "flowWord", "key", nm + "K")
        g.tget(nm + "C", "flowWord", "code", r, "number")
        g.x(nm, f"{nm}R >= 0 ? {nm}C : -1")
    g.x("tellA", "isWarmN ? 0 : ts1 == 4 ? 1 : max(ts1, 0)")    # the tail's 玉石俱焚 is an attack (A-9)
    g.x("tellB", "isWarmN ? -1 : ts2")
    g.x("tellStar", "isWarmN || tst < 0 ? -1 : tst == ts1 ? 0 : tst == ts2 ? 1 : -1")
    g.edge("tellA", "ui#debate.tell_a")
    g.edge("tellB", "ui#debate.tell_b")
    g.edge("tellStar", "ui#debate.tell_star")
    g.n("fuzzyN", g.cmp("fuzzyC", "L_TellClarity", g.k("fuzzy")))
    g.x("tellClar", "isWarmN ? 0 : fuzzyN")
    g.edge("tellClar", "ui#debate.tell_clarity")
    g.fmt("basisK", "basis:{a}", "L_TellBasis")
    g.text("basisT", g.tget("basisKey", "flowWord", "text", g.tfind("basisR", "flowWord", "key", "basisK")))
    g.edge(g.sel("basisOut", "isWarmC.out", g.k(""), "basisT.text"), "ui#debate.tell_basis")
    g.fmt("starK", "UI_DEB_TELL_LIKELY__{a}", "L_TellStarRule")
    g.text("starT", g.sel("starKOn", g.b("starOn", g.x("starOnN", "L_TellStarRule > 0 && !isWarmN")), "starK",
                          g.k("")))
    g.edge("starT.text", "ui#debate.tell_star_text")
    g.text("tellLineT", "L_TellLine")
    g.edge(g.sel("tellLineOut", "isWarmC.out", g.k(""), "tellLineT.text"), "ui#debate.tell_line")
    g.text("gestT", "L_TellGesture")
    g.edge(g.sel("gestOut", "isWarmC.out", g.k(""), "gestT.text"), "ui#debate.tell_gesture")
    g.x("claimN", "clamp(L_on - L_Fragile, 0, ec_cap)")
    g.n("rushN", g.cmp("rushC", "L_TellShown1", g.k("rush")))
    g.n("asrtN", g.cmp("asrtC", "L_TellShown1", g.k("assert")))
    g.n("asrt2N", g.cmp("asrt2C", "L_TellShown2", g.k("assert")))
    g.n("rush2N", g.cmp("rush2C", "L_TellShown2", g.k("rush")))
    g.fmt("cpA", "UI_DEB_COUNTER_PREVIEW__{a}_{b}", "ec_base", "claimN")
    g.fmt("cpR", "UI_DEB_COUNTER_PREVIEW_RUSH__{a}_{b}", "ec_base", "claimN")
    cp = ssel(g, "cpKey", [(g.b("cpOff", g.x("cpOffN", "dc_mode != 0 || tailN")), g.k("")),
                           (g.b("cpRush", g.x("cpRushN", "rushN && !fuzzyN")), "cpR"),
                           (g.b("cpAsrt", g.x("cpAsrtN", "asrtN || asrt2N || rush2N || rushN")), "cpA")], g.k(""))
    g.text("cpT", cp)
    g.edge("cpT.text", "ui#debate.claim_preview")
    g.edge("handN", "ui#debate.hand")
    g.edge("d_act", "ui#debate.sel_act")
    g.edge("L_InstinctLeft", "ui#debate.instinct_left")
    g.x("instOk", "d_ph == 0 && isDebN && L_InstinctLeft > 0 && fuzzyN")
    g.edge("instOk.truth", "ui#debate.instinct_ok")
    g.x("assistLeft", "max(0, L_Assist - d_armed)")
    g.edge("assistLeft", "ui#debate.assist_left")
    g.edge(g.b("armedB", "d_armed"), "ui#debate.assist_armed")
    g.x("stShaken", "L_Shaken > 0")
    g.edge("stShaken", "ui#debate.st_shaken")
    g.edge("breakR.truth", "ui#debate.st_break")
    g.x("stTail", "L_InTail ? L_TailLeft : 0")
    g.edge("stTail", "ui#debate.st_tail")
    g.edge("L_Hachiku", "ui#debate.st_hachiku")
    g.edge(g.b("hkPrev", g.x("hkPrevN", "L_HachikuMode == 1")), "ui#debate.st_hachiku_preview")
    g.edge("L_Konju", "ui#debate.st_konju")
    g.edge("L_Shisshu", "ui#debate.st_shisshu")
    g.edge(g.k(""), "ui#debate.st_flags")
    g.edge("d_ph", "ui#debate.phase")
    g.edge("s_fo", "ui#debate.float_opp")
    g.edge("s_fm", "ui#debate.float_me")
    g.text("rlT", "s_rl")
    g.edge("rlT.text", "ui#debate.result_line")

    # ---- the stages run on a beat (every tick: the clock changes) and are chosen by the map dbui: a pulse path
    # from a stage back into its own condition would be a cycle (the flow is a DAG over pulse edges too), so a
    # stage only writes the flag or the time of the next one (rsAt, r2, r3, sel, instAt, lockAt, pb / pbAt, holdAt,
    # finAt; times in clock seconds)
    g.node("clock", "clock")
    g.put("now", "clock.seconds")
    g.node("beat", "filter", op="deadband", threshold=0)
    g.edge("clock.seconds", "beat.in")
    beat = "beat.passed"
    for k in ("rsAt", "r2", "r3", "sel", "instAt", "lockAt", "pb", "pbAt", "holdAt", "finAt"):
        g.mget("d_" + k, "dbui", g.k(k))

    def stage(name: str, cond: str, clear: str | None = None) -> str:
        p = g.when(name, beat, T(name + "Go", cond))
        if clear:
            setn(p, clear, g.k(0))
        return p
    startT = stage("rsG", "d_rsAt > 0 && now >= d_rsAt", "rsAt")
    rs2T = stage("r2G", "d_r2 > 0", "r2")
    rs3T = stage("r3G", "d_r3 > 0", "r3")
    selT = stage("selG", "d_sel > 0", "sel")
    instT = stage("instG2", "d_instAt > 0 && now >= d_instAt", "instAt")
    lockT = stage("lockG2", "d_lockAt > 0 && now >= d_lockAt", "lockAt")
    g.x("soon", f"now + {START_DELAY}")

    # ---- begin: reset, the rebut candidates, start the engine
    g.edge(begin, g.eff("clrDbui", "atrium.map.clear", "dbui"))
    g.edge(begin, g.eff("clrDbuiS", "atrium.map.clear", "dbuiS"))
    setn(begin, "ph", g.k(1))
    g.edge(begin, g.eff("clrCands", "atrium.coll.clear", "uiCands"))
    g.node("candEach", "atrium.coll.forEach", name="debBoard")
    g.edge(g.when("candDeb", begin, "isDebC.out"), "candEach.trigger")
    g.edge(g.when("candG", "candEach.each", g.cmp("candOk", "candEach.item", g.k("-"), "ne")),
           g.eff("candAdd", "atrium.coll.add", "uiCands", value="candEach.item"))
    g.edge(g.when("candWarm", begin, "isWarmC.out"), add_all(g, "candHand", "uiCands", "dc_hand"))
    g.edge(begin, "world.debStart")
    setn(begin, "rsAt", "soon")

    # ---- a round is shown: reset the choice, latch the engine, rebuild the lists (rs2) and the buttons (rs3)
    rs = g.merge("rs", startT)
    for k, v in (("ph", 0), ("act", 0), ("sa", 0), ("sb", 0), ("segPh", 0), ("armed", 0), ("fast", 0), ("hold", 0)):
        setn(rs, k, g.k(v))
    for k in ("card", "target", "msg", "fo", "fm", "rl"):
        sets(rs, k, g.k(""))
    setn(rs, "hpO", "world.debOppHp")
    setn(rs, "hpM", "world.debPlayerHp")
    g.edge(rs, "snap.in")
    g.edge(instT, "snap.in")
    nodes_reset = g.merge("nodesReset", rs)
    setn(rs, "r2", g.k(1))

    # nodes: uiNodeIds = the board's nodes when the round is shown (engine debOn; the warmup's claim); during the
    # playback removed nodes shatter (uiShat) and added ones join; uiNodes = "id|state" rows of flowNodeView
    def reset_ids(pulse: str, pre: str) -> None:
        g.edge(pulse, g.eff(pre + "IdClr", "atrium.coll.clear", "uiNodeIds"))
        g.edge(pulse, g.eff(pre + "ShClr", "atrium.coll.clear", "uiShat"))
        g.node(pre + "OnEach", "atrium.coll.forEach", name="debOn")
        g.edge(pulse, pre + "OnEach.trigger")
        g.edge(pre + "OnEach.each", g.eff(pre + "IdAdd", "atrium.coll.add", "uiNodeIds", value=f"{pre}OnEach.item"))
        g.edge(g.when(pre + "WarmG", pulse, "isWarmC.out"),
               g.eff(pre + "IdW", "atrium.coll.add", "uiNodeIds", value="world.dwClaim"))
    reset_ids("nodesReset.out", "nr")
    nodes_list = g.merge("nodesList", rs2T)
    g.edge(nodes_list, g.eff("nvClr", "atrium.coll.clear", "uiNodes"))
    g.node("nvEach", "atrium.coll.forEach", name="uiNodeIds")
    g.edge(nodes_list, "nvEach.trigger")
    nv = g.put("nv", "nvEach.item")
    g.n("nvShat", g.contains("nvShatC", "uiShat", nv))
    g.n("nvTail", g.cmp("nvTailC", nv, "ec_t", "eq"))
    g.n("nvLit", g.cmp("nvLitC", nv, lit, "eq"))
    g.tfind("nvRow", "debNode", "id", nv)
    g.x("nvReal", "nvRow >= 0")
    g.x("nvSt", "nvShat ? 4 : nvTail ? 3 : nvLit ? 1 : !nvReal ? 2 : 0")
    g.fmt("nvKey", "{a}|{b}", nv, "nvSt")
    g.edge("nvEach.each", g.eff("nvAdd", "atrium.coll.add", "uiNodes", value="nvKey"))
    g.edge("nvEach.done", g.ui_list("nvList", "ui.debate.nodes", "uiNodes",
                                    {"id": "id", "text": "textKey", "state": "state", "src": "src"},
                                    join={"table": "flowNodeView", "column": "key"}, localize=["text"]))

    # chains: uiChains = "slot|card|link|sel" of the chain slots (flowChainView)
    chains_list = g.merge("chainsList", rs2T, selT)
    g.edge(chains_list, g.eff("cvClr", "atrium.coll.clear", "uiChains"))
    g.node("cvEach", "atrium.coll.forEach", name="debBoard")
    g.edge(g.when("cvDeb", chains_list, "isDebC.out"), "cvEach.trigger")
    ci, cc = g.put("ci", "cvEach.index"), g.put("cc", "cvEach.item")
    g.cget("cvBase", "debBoardLink", ci)
    g.tostr("ciS", ci)
    g.mget("cvSnap", "debSnap", "ciS")
    g.n("cvHasSnap", g.mhas("cvHasSnapC", "debSnap", "ciS"))
    g.n("cvAs", g.mhas("cvAsC", "debAssisted", "ciS"))
    g.n("cvCard", g.cmp("cvCardC", cc, g.k("-"), "ne"))
    g.x("cvLink", "cvBase == 0 ? 0 : (cvHasSnap && cvSnap >= L_Round) ? 6 : cvAs ? 5 : cvBase")
    g.x("cvSel", "d_sa > 0 && ci >= segLo && ci <= segHi")
    g.x("cvOn", f"ci < {SLOTS} && cvCard")
    g.fmt("cvKey", "{a}|{b}|{c}|{d}", ci, cc, "cvLink", "cvSel")
    g.edge(g.when("cvG", "cvEach.each", "cvOn_t"), g.eff("cvAdd", "atrium.coll.add", "uiChains", value="cvKey"))
    chains_out = g.merge("chainsOut", "cvEach.done", g.when("cvWarm", chains_list, "isWarmC.out"))
    g.edge(chains_out, g.ui_list("cvList", "ui.debate.chains", "uiChains",
                                 {"chain": "chain", "pos": "pos", "id": "id", "name": "nameKey", "link": "link",
                                  "sel": "sel"}, join={"table": "flowChainView", "column": "key"}, localize=["name"]))

    # rebut candidates that refute the lit node (A-5: appraised; the warmup takes its event cards as they are)
    g.edge(rs2T, g.eff("paClr", "atrium.coll.clear", "uiParryAll"))
    g.node("paEach", "atrium.coll.forEach", name="uiCands")
    g.edge(rs2T, "paEach.trigger")
    pa = g.put("pa", "paEach.item")
    slim_card(g, "pa", pa)
    refutes(g, "pa", pa, case)
    g.x("paOk", "hasLitN && pa_ref && (pa_full || isWarmN)")
    g.edge(g.when("paG", "paEach.each", "paOk_t"), g.eff("paAdd", "atrium.coll.add", "uiParryAll", value=pa))
    setn(rs2T, "r3", g.k(1))
    # act_enabled (list<bool>) / act_reason (list<string>) are not written: atrium.ui.list writes an array of
    # objects, which a list<bool> port rejects and a list<string> port shows as nothing (docs/flows.md §7.2).
    # The flow still refuses a disabled action and says why on the confirmation line (msg).
    picker = g.merge("picker", rs3T, selT)
    g.edge(picker, g.eff("ppClr", "atrium.coll.clear", "uiParry"))
    g.node("ppEach", "atrium.coll.forEach", name="uiParryAll")
    g.edge(g.when("ppG", picker, T("ppOn", "d_act == 3")), "ppEach.trigger")
    g.edge("ppEach.each", g.eff("ppAdd", "atrium.coll.add", "uiParry", value="ppEach.item"))
    pp_out = g.merge("ppOut", "ppEach.done", g.when("ppOff", picker, T("ppOffN", "d_act != 3")))
    g.edge(pp_out, g.ui_list("ppList", "ui.debate.parry_cards", "uiParry", {"id": "item", "name": "nameKey"},
                             join={"table": "flowCard", "column": "id"}, localize=["name"]))

    # ---- the player's choices (phase 0; docs/flows.md §3: value ports through .emitted)
    g.x("inOk", "activeN && d_ph == 0")
    # act: an enabled action is chosen; a disabled one shows why (§4.4: 失守 -> MSG_DEB_NOPARRY_SHISSHU)
    g.put("actV", "ui#debate.act")
    aP = g.when("actG", "ui#debate.act.emitted", "inOk_t")
    g.x("enV", "actV == 1 ? en1 : actV == 2 ? en2 : actV == 3 ? en3 : actV == 4 ? en4 : 0")
    okA = g.when("actOk", aP, "enV_t")
    setn(okA, "act", "actV")
    for k in ("card", "target", "msg"):
        sets(okA, k, g.k(""))
    g.edge(g.when("actObs", okA, T("actObsN", "actV == 4")), g.eff("obsClrSa", "atrium.map.set", "dbui",
                                                                     key=g.k("sa"), value=g.k(0)))
    setn(okA, "sel", g.k(1))
    badA = g.when("actBad", aP, T("enVNo", "!enV"))
    msgV = ssel(g, "msgV", [(g.b("mv1", g.x("mv1n", "actV == 1 && isDebN")), why1),
                            (g.b("mv2", g.x("mv2n", "actV == 2 && isDebN")), why2),
                            (g.b("mv3", g.x("mv3n", "actV == 3")), msg3)], g.k(""))
    sets(badA, "msg", msgV)
    # seg: first click = start, second = end when the path between is linked (one chain, no cut link)
    g.put("segV", "ui#debate.seg")
    sP = g.when("segG", "ui#debate.seg.emitted", T("segIn", "inOk && isDebN && d_act != 4"))
    g.cget("segCard", "debBoard", "segV")
    g.n("segCardN", g.cmp("segCardC", "segCard", g.k("-"), "ne"))
    path = " + ".join(f"(min(segA, segV) <= {i} && {i} < max(segA, segV) && brk{i})" for i in range(SLOTS - 1))
    g.x("segCont", f"d_segPh == 1 && floor(segA / 5) == floor(segV / 5) && ({path}) == 0")
    sOk = g.when("segOkG", sP, T("segValid", f"segV >= 0 && segV < {SLOTS} && segCardN"))
    sEnd = g.when("segEndG", sOk, "segCont_t")
    setn(sEnd, "sb", g.x("segV1", "segV + 1"))
    setn(sEnd, "segPh", g.k(0))
    sNew = g.when("segNewG", sOk, T("segNoCont", "!segCont"))
    setn(sNew, "sa", "segV1")
    setn(sNew, "sb", "segV1")
    setn(sNew, "segPh", g.k(1))
    sets(sOk, "card", g.k(""))
    sets(sOk, "msg", g.k(""))
    setn(sOk, "sel", g.k(1))
    # target: another visible, non-fragile node (A-2)
    g.put("tgtV", "ui#debate.target")
    g.n("tgtVOn", g.contains("tgtVOnC", "debOn", "tgtV"))
    g.tfind("tgtVRow", "nodes", "id", "tgtV")
    tP = g.when("tgtG", "ui#debate.target.emitted",
                T("tgtIn", "inOk && (d_act == 1 || d_act == 2) && tgtVOn && tgtVRow >= 0"))
    sets(tP, "target", "tgtV")
    # card: the picker (rebut)
    cP = g.when("cardG", "ui#debate.card.emitted", T("cardIn", "inOk && d_act == 3"))
    sets(cP, "card", "ui#debate.card")
    sets(cP, "msg", g.k(""))
    setn(cP, "sa", g.k(0))
    setn(cP, "sb", g.k(0))
    setn(cP, "segPh", g.k(0))
    setn(cP, "sel", g.k(1))
    # back: the last step back (the card or segment, else the action)
    bP = g.when("backG", "ui#debate.back", "inOk_t")
    g.x("backSub", "d_sa > 0 || hasCardN")
    bSub = g.when("backSubG", bP, "backSub_t")
    for k in ("sa", "sb", "segPh"):
        setn(bSub, k, g.k(0))
    sets(bSub, "card", g.k(""))
    bTop = g.when("backTopG", bP, T("backTopN", "!backSub"))
    setn(bTop, "act", g.k(0))
    sets(bTop, "target", g.k(""))
    sets(bP, "msg", g.k(""))
    setn(bP, "sel", g.k(1))
    # assist: armed before the lock (A-7), toggles
    asP = g.when("assistG", "ui#debate.assist", T("assistIn", "inOk && isDebN && L_Assist > 0"))
    setn(asP, "armed", g.x("armT", "1 - d_armed"))
    # instinct (A-3): the engine rewrites the tell; latch it again a moment later; the 看穿 stamp now
    inP = g.when("instG", "ui#debate.instinct", "instOk_t")
    g.edge(inP, "world.debInstinct")
    setn(inP, "instAt", "soon")

    # lock: the command (held until the next lock: the engine reads it a tick after the pulse, §7.6), the pulse
    lP = g.when("lockG", "ui#debate.lock", "canLock_t")
    # a single card that is a break by itself in the break round (Ch.1: E01_03 with the right reason; a strong card
    # when one strong card is the threshold, A-8) is shown as a one-card segment: the engine breaks on segments only
    g.index_of("pcSlot", "debBoard", "s_card")
    g.cget("pcOkV", "debBoardOk", "pcSlot")
    g.x("pcBreak", "d_act == 3 && hasCardN && breakR && pcSlot >= 0 && pcOkV && "
                   "(ec_ch1 ? pc_brk : pc_strong && 1 >= max(1, 1 + L_Voids - thrRed))")
    g.x("useSeg", "d_act == 1 || d_act == 2 || (d_act == 3 && !hasCardN)")
    kind = g.lookup("cmdKind", [""] + PA, "d_act")
    g.edge(g.latch("cmdKindL", kind, lP), "world.debCmdKind")
    g.x("cmdFrom", "pcBreak ? pcSlot : useSeg ? segA : -1")
    g.x("cmdTo", "pcBreak ? pcSlot : useSeg ? segB : -1")
    g.edge(g.latch("cmdFromL", "cmdFrom", lP), "world.debCmdFrom")
    g.edge(g.latch("cmdToL", "cmdTo", lP), "world.debCmdTo")
    g.edge(g.latch("cmdCardL", g.sel("cmdCard", g.b("useCard", g.x("useCardN", "d_act == 3 && hasCardN && !pcBreak")),
                                     "s_card", g.k("")), lP), "world.debCmdCard")
    g.edge(g.latch("cmdTgtL", g.sel("cmdTgt", g.b("atkC", g.x("atkN", "d_act == 1 || d_act == 2")), "s_target",
                                    g.k("")), lP), "world.debCmdTarget")
    g.edge(g.latch("cmdAsL", g.x("cmdAs", "isDebN && d_armed"), lP), "world.debCmdAssist")
    g.edge(lP, "world.debLock")
    setn(lP, "ph", g.k(1))
    setn(lP, "maxc", g.x("maxcN", "max(d_maxc, useSeg ? segL : 1)"))
    setn(lP, "lockAt", "soon")

    # ---- playback of the round's records (debEvents, docs/debate-engine.md §2.3)
    # pb: 1 fetch the next record (split into evF / evN), 2 play it, 3 wait until pbAt
    setn(lockT, "ev", g.k(0))
    setn(lockT, "pb", g.k(1))
    stepP = stage("fetchG", "d_pb == 1")
    g.count("evCnt", "debEvents")
    g.cget("evRec", "debEvents", "d_ev")
    more = g.when("moreG", stepP, T("more", "d_ev < evCnt"))
    g.edge(more, g.eff("evFClr", "atrium.coll.clear", "evF"))
    g.edge(more, g.eff("evNClr", "atrium.coll.clear", "evN"))
    g.edge(more, add_all(g, "evFAdd", "evF", "evRec", "|"))
    g.edge(more, add_all(g, "evNAdd", "evN", "evRec", "|"))
    setn(more, "ev", g.x("evNext", "d_ev + 1"))
    setn(more, "pb", g.k(2))
    endT = g.when("evDone", stepP, T("evOver", "!more"))
    setn(endT, "pb", g.k(0))
    parse = stage("parseG", "d_pb == 2")
    setn(parse, "pb", g.k(3))
    setn(stage("waitG", "d_pb == 3 && now >= d_pbAt"), "pb", g.k(1))
    for k in range(7):
        g.cget(f"f{k}", "evF", g.k(k))
        g.cget(f"n{k}", "evN", g.k(k))
    kinds = {}
    for nm, word in (("Rev", "reveal"), ("WRev", "wReveal"), ("Cut", "cutin"), ("DO", "dmgOpp"),
                     ("DP", "dmgPlayer"), ("Heal", "heal"), ("NR", "nodeRemoved"), ("NA", "nodeAdded")):
        kinds[nm] = g.cmp("is" + nm, "f0", g.k(word))
        g.n("is" + nm + "N", kinds[nm])
    g.n("isCtrN", g.cmp("isCtrC", "f1", g.k("counter")))
    g.fmt("subRev", "{a}/{b}", "f2", "f3")
    plain = [(g.cmp("is" + w, "f0", g.k(w)), g.k("")) for w in ("linkSnapped", "infamy", "breakVoided")]
    sub = ssel(g, "evSub", [(kinds["Rev"], "subRev"), (kinds["NR"], "f2"), (kinds["NA"], "f3")] + plain, "f1")
    g.fmt("evKey", "{a}|{b}|{c}", case, "f0", sub)
    erow2 = g.tfind("evRow", "flowEvLine", "key", "evKey")
    g.tget("evLine0", "flowEvLine", "line", erow2)
    g.fmt("ctrLine", "MSG_DEB_PARRY__{a}", "n2")
    line = g.sel("evLine", g.b("lnCtr", g.x("lnCtrN", "isDON && isCtrN")), "ctrLine", "evLine0")
    g.n("hasLineN", g.cmp("hasLineC", line, g.k(""), "ne"))
    g.x("isRevAny", "isRevN || isWRevN")
    setn(g.when("phTwo", parse, T("phTwoN", "!isRevAny")), "ph", g.k(2))
    sets(g.when("lineG", parse, "hasLineC.out"), "rl", line)
    # reveal: the cards (reveal_me 1..4, reveal_opp 0..4, reveal_combo) and the statement (tells: the opponent's
    # action line when he attacks into a defence, Sherefox's when she attacks, the clash / standoff reactions;
    # the tail's 玉石俱焚 takes the cornered lines, ruling G3)
    for nm, fmt_, f in (("rvP", "pa:{a}", "f2"), ("rvO", "oa:{a}", "f3"), ("rvS", "st:{a}", "f4")):
        g.fmt(nm + "K", fmt_, f)
        g.tget(nm, "flowWord", "code", g.tfind(nm + "R", "flowWord", "key", nm + "K"), "number")
    g.x("revMe", "isWRevN ? 3 : rvP + 1")
    g.x("revOpp", "isWRevN ? 0 : rvO")
    g.x("revCombo", "isWRevN ? 1 : rvS")
    g.fmt("rgP", "sfAction:{a}", "f2")
    g.fmt("rgO", "action:{a}", "f3")
    grp = ssel(g, "rg", [(g.cmp("rgTail", "f3", g.k("scorched")), g.k("cornered:")),
                         (g.b("rg0", g.x("rg0n", "rvS == 0")), "rgP"),
                         (g.b("rg1", g.x("rg1n", "rvS == 1")), "rgO"),
                         (g.b("rg2", g.x("rg2n", "rvS == 2")), g.k("reaction:clash"))], g.k("reaction:standoff"))
    g.fmt("rgKey", "{a}:{b}", case, grp)
    g.x("rgN", "(L_Round - 1) - 2 * floor((L_Round - 1) / 2)")
    g.tostr("rgNs", "rgN")
    find_f(g, "rgRow1", "tells", "group", "rgKey", "n", "rgNs")
    g.tfind("rgRow0", "tells", "group", "rgKey")
    g.x("rgRow", "rgRow1 >= 0 ? rgRow1 : rgRow0")
    g.tget("rgLine", "tells", "text", "rgRow")
    g.tget("wClaimKey", "nodes", "textKey", g.tfind("wClaimRow", "nodes", "id", "f2"))
    revLine = g.sel("revLine", kinds["WRev"], "wClaimKey", "rgLine")
    revP = g.when("revG", parse, "isRevAny_t")
    g.counter("revSeq", initial=0)
    for nm, src in (("revMeL", "revMe"), ("revOppL", "revOpp"), ("revComboL", "revCombo")):
        g.latch(nm, src, revP)
    g.text("revLineT", g.latch("revLineL", revLine, revP))
    g.edge(revP, "revSeq.increment")
    g.edge("revMeL.out", "ui#debate.reveal_me")
    g.edge("revOppL.out", "ui#debate.reveal_opp")
    g.edge("revComboL.out", "ui#debate.reveal_combo")
    g.edge("revSeq.value", "ui#debate.reveal_seq")
    g.edge("revLineT.text", "ui#debate.reveal_line")
    # numbers: floats and the gauges follow the record ("after" fields)
    doP = g.when("doG", parse, kinds["DO"])
    sets(doP, "fo", g.fmt("foDmg", "−{a}", "n2"))
    setn(doP, "hpO", "n4")
    setn(doP, "maxd", g.x("maxdN", "max(d_maxd, n2)"))
    dpP = g.when("dpG", parse, kinds["DP"])
    sets(dpP, "fm", g.fmt("fmDmg", "−{a}", "n2"))
    setn(dpP, "hpM", "n4")
    # breaks for the result's 論破次數 (the engine keeps only Ch.3's break label)
    g.n("isBrkN", g.cmp("isBrkC", "f0", g.k("break")))
    setn(g.when("brkG", parse, T("brkOk", "isBrkN && n1 == 1")), "brks", g.x("brksN", "d_brks + 1"))
    hlP = g.when("hlG", parse, kinds["Heal"])
    sets(hlP, "fo", g.fmt("foHeal", "+{a}", "n1"))
    setn(hlP, "hpO", "n3")
    # nodes shatter / join, then the list again
    nrP = g.when("nrG", parse, kinds["NR"])
    g.edge(nrP, g.eff("shAdd", "atrium.coll.add", "uiShat", value="f1"))
    naP = g.when("naG", parse, kinds["NA"])
    g.edge(naP, g.eff("naAdd", "atrium.coll.add", "uiNodeIds", value="f1"))
    g.edge(nrP, "nodesList.in")
    g.edge(naP, "nodesList.in")
    # cut-ins (§4.7; the engine already keeps one full-screen cut-in per round and marks the others demoted)
    g.n("cutFullN", g.cmp("cutFullC", "f2", g.k("full")))
    g.x("cutBig", "cutFullN && n5")
    g.fmt("cutKey", "{a}|{b}", "f1", "cutBig")
    crow2 = g.tfind("cutRow", "flowCut", "key", "cutKey")
    g.tget("cutB", "flowCut", "big", crow2)
    g.tget("cutS", "flowCut", "stamp", crow2)
    g.tget("cutN", "flowCut", "n", crow2, "number")
    g.tget("cutSub", "flowCut", "sub", crow2)
    g.tget("cutDw", "flowCut", "dwell", crow2, "number")
    g.n("hkStampN", g.cmp("hkStampC", "cutS", g.k("STAMP_HACHIKU")))
    g.fmt("hkSub", "STAMP_HACHIKU_SUB__{a}", "world.debHachiku")
    g.put("world_hk", "world.debHachiku")
    g.x("cutNOut", "cutN > 0 ? cutN : world_hk")
    cutSubKey = g.sel("cutSubKey", g.b("hkSubOn", g.x("hkSubOnN", "hkStampN && cutN == 0")), "hkSub", "cutSub")
    g.n("cutHasB", g.cmp("cutHasBC", "cutB", g.k(""), "ne"))
    g.n("cutHasS", g.cmp("cutHasSC", "cutS", g.k(""), "ne"))
    bigP = g.when("bigG", parse, T("bigOn", "isCutN && cutHasB && !d_fast"))
    stP = g.when("stG", parse, T("stOn", "isCutN && cutHasS && !d_fast"))
    g.edge(g.latch("bigL", "cutB", bigP), "ui#cutin.big")
    g.counter("bigSeq", initial=0)
    g.edge(bigP, "bigSeq.increment")
    g.edge("bigSeq.value", "ui#cutin.big_seq")
    stamp = Mux(g, "stamp", ["id", "n"])
    stamp.add(stP, {"id": "cutS", "n": "cutNOut"})
    stamp.add(inP, {"id": g.k("STAMP_SEEN"), "n": g.k(0)})
    g.edge(stamp.out("id", g.k("")), "ui#cutin.stamp")
    g.edge(stamp.out("n", g.k(0)), "ui#cutin.stamp_n")
    g.edge(stamp.seq, "ui#cutin.stamp_seq")
    csub = Mux(g, "csub", ["key"])
    csub.add(bigP, {"key": "cutSubKey"})
    csub.add(stP, {"key": "cutSubKey"})
    csub.add(inP, {"key": g.k("STAMP_SEEN_SUB")})
    g.text("csubT", csub.out("key", g.k("")))
    # 大字譯名 (§4.6: on by default outside zh-TW; there is no settings screen): the subtitle in English
    g.edge(g.sel("csubOut", "langEn", "csubT.text", g.k("")), "ui#cutin.subtitle")
    # the dwell before the next record (skip / next set `fast`: every record next tick, no cut-ins)
    g.x("dwell", "d_fast ? 0 : isRevAny ? 2 : isCutN ? cutDw : (isDON || isDPN || isHealN || hasLineN) ? 1 : 0")
    g.lookup("dwellS", DWELL, "dwell")
    setn(parse, "pbAt", g.x("pbAtN", "now + dwellS"))

    # ---- the round is played out: phase 2 with the engine's values, then the next round or the end
    setn(endT, "ph", g.k(2))
    setn(endT, "hold", g.k(1))
    setn(endT, "hpO", "world.debOppHp")
    setn(endT, "hpM", "world.debPlayerHp")
    g.edge(endT, "nodesReset.in")
    setn(endT, "r2", g.k(1))
    setn(endT, "holdAt", g.x("holdAtN", f"now + {HOLD}"))
    nextP = "ui#debate.next"
    g.edge(g.when("skipG", g.merge("skipM", "ui#debate.skip", nextP),
                  T("skipIn", "activeN && (d_ph == 1 || d_ph == 2) && !d_hold")),
           g.eff("fastSet", "atrium.map.set", "dbui", key=g.k("fast"), value=g.k(1)))
    setn(g.when("nextHold", nextP, T("nextHoldN", "activeN && d_ph == 2 && d_hold == 1")), "holdAt", "now")
    cont = stage("contG", "d_hold == 1 && now >= d_holdAt", "hold")
    g.put("world_dwOver", "world.dwOver")
    g.put("world_debOver", "world.debOver")
    g.x("overN", "isWarmN ? world_dwOver : world_debOver")
    over = g.when("overG", cont, "overN_t")
    setn(g.when("notOverG", cont, T("notOver", "!overN")), "rsAt", "now")
    setn(over, "ph", g.k(3))
    setn(over, "fin", g.k(1))
    setn(over, "finAt", g.x("finAtN", f"now + {FINISH}"))
    setn(g.when("nextFin", nextP, T("nextFinN", "activeN && d_ph == 3 && d_fin == 1")), "finAt", "now")
    fin = stage("finG", "d_fin == 1 && now >= d_finAt", "fin")
    # the warmup's trust for this case (A-13, §3.1: not written back to the permanent trust)
    g.edge(g.when("warmTrust", fin, "isWarmC.out"),
           g.eff("caseTrust", "atrium.map.set", "caseMod", key=g.k("trust"), value="world.dwTrustDelta"))
    g.edge(fin, "world.stepDone")
    return g


# ---------------------------------------------------------------------------------------------- result

def gen_result() -> Graph:
    """result steps (01-systems §4.2 SCR_RESULT, §3.1-3.3, A-14 retry; ui-contracts result; docs/flows.md §4.9)."""
    g = Graph()
    T = truth(g)
    isRes = g.cmp("isRes", "world.stepKind", g.k("result"))
    g.n("isResN", isRes)
    begin = g.when("beginG", "world.stepBegin", isRes)
    case = g.put("case", "world.debCase")
    crow = g.tfind("dcRow", "flowDebCase", "id", case)
    for c in ("mode",):
        g.tget("dc_" + c, "flowDebCase", c, crow, "number")
    for c in ("winLine", "costs", "ungold", "after"):
        g.tget("dc_" + c, "flowDebCase", c, crow)
    erow = g.tfind("ecRow", "debCase", "id", case)
    for c in ("fox", "assists", "hp"):
        g.tget("ec_" + c, "debCase", c, erow, "number")
    g.tostr("chText", "world.chapter")
    chRow = g.tfind("chRow", "chapters", "id", "chText")
    for c in ("trustShown", "trustDebate", "trustNotoriety"):
        g.tget("ch_" + c, "chapters", c, chRow, "number")
    for nm, word in (("win", "win"), ("loss", "loss"), ("un", "unachieved")):
        g.n(nm + "N", g.cmp(nm + "C", "world.debOutcome", g.k(word)))
    g.put("inf", "world.debInfamy")
    g.x("winPort", "winN ? 1 : unN ? 2 : 0")
    g.edge("winPort", "ui#result.win")
    # trust (§3.1): permanent = 3 + progress.trustAdj; this case: win +1 / loss -1 where the inspector takes part,
    # infamy >= 3 -1 (applied now; the design applies it when the next case starts, which is the same number)
    g.mget("adj", "progress", g.k("trustAdj"))
    g.x("perm", "clamp(3 + adj, 0, 5)")
    g.edge("perm", "world.trust")
    g.x("delta", "(ch_trustDebate ? (winN ? 1 : lossN ? -1 : 0) : 0) + (ch_trustNotoriety && inf >= 3 ? -1 : 0)")
    g.x("trustTo", "clamp(perm + delta, 0, 5)")
    g.x("tFrom", "ch_trustShown ? perm : -1")
    g.x("tTo", "ch_trustShown ? trustTo : -1")
    g.edge("tFrom", "ui#result.trust_from")
    g.edge("tTo", "ui#result.trust_to")
    # Arthur's comment (§8.8)
    g.x("cmIdx", "winN ? (inf == 0 ? 0 : inf < 3 ? 1 : 2) : inf >= 3 ? 4 : 3")
    g.text("cmT", g.lookup("cmKey", ["ART_RES_CLEAN", "ART_RES_MID", "ART_RES_NOTORIOUS", "ART_RES_LOSE",
                                     "ART_RES_LOSE_NOTO"], "cmIdx"))
    g.edge("cmT.text", "ui#result.comment")
    # the opponent's closing line (a win or Ch.1's unachieved: he confesses anyway, A-13)
    g.text("oppT", g.sel("oppKey", g.b("oppOn", g.x("oppOnN", "winN || unN")), "dc_winLine", g.k("")))
    g.edge("oppT.text", "ui#result.opp_line")
    g.edge(g.b("retryB", "lossN"), "ui#result.can_retry")
    # stats (§4.2): the engine's counters and the UI's (dbui maxd / maxc)
    g.mget("maxd", "dbui", g.k("maxd"))
    g.mget("maxc", "dbui", g.k("maxc"))
    g.mget("brkN", "dbui", g.k("brks"))
    stats = [("UI_RES_ROUNDS", "max(0, world_round - 1)", None), ("UI_RES_PARRIES", "world_par", None),
             ("UI_RES_MAXDMG", "maxd", "ec_hp"), ("UI_RES_MAXCHAIN", "maxc", None), ("UI_RES_BREAKS", "brkN", None),
             ("UI_RES_ASSIST", "max(0, ec_assists - world_as)", "ec_hp"),
             ("UI_RES_INSTINCT", "max(0, ec_fox - world_fox)", None), ("UI_RES_HP", "max(0, world_php)", "ec_hp")]
    for nm, sig in (("world_round", "debRound"), ("world_par", "debParries"), ("world_as", "debAssist"),
                    ("world_fox", "debInstinctLeft"), ("world_php", "debPlayerHp")):
        g.put(nm, f"world.{sig}")
    g.edge(begin, g.eff("clrStats", "atrium.map.clear", "resStats"))
    for i, (key, expr, cond) in enumerate(stats):
        g.x(f"stV{i}", expr)
        g.fmt(f"stS{i}", "{a}", f"stV{i}")
        p = begin if cond is None else g.when(f"stG{i}", begin, T(f"stC{i}", cond))
        g.edge(p, g.eff(f"stSet{i}", "atrium.map.set", "resStats", key=g.k(key), value=f"stS{i}"))
    g.edge(begin, g.ui_list("statsList", "ui.result.stats", "resStats", {"label": "key", "value": "value"},
                            localize=["label"]))
    # costs on a defeat (§4.2, 10-cases)
    g.edge(begin, g.eff("clrCosts", "atrium.coll.clear", "resCosts"))
    g.edge(g.when("costTrust", begin, T("costTrustN", "lossN && delta < 0")),
           g.eff("costTrustAdd", "atrium.coll.add", "resCosts", value=g.k("UI_RES_COST_TRUST")))
    g.edge(g.when("costG", begin, "lossC.out"), add_all(g, "costAdd", "resCosts", "dc_costs"))
    g.edge(begin, g.ui_list("costList", "ui.result.costs", "resCosts", {"text": "item"}, localize=["text"]))
    g.edge(begin, g.eff("resOpen", "atrium.map.set", "dbui", key=g.k("res"), value=g.k(1)))
    g.mget("resOn", "dbui", g.k("res"))

    # continue: the consequences, then the result scene's lines (dialogue)
    cP = g.when("contG", "ui#result.continue", T("contIn", "isResN && resOn == 1"))
    g.edge(cP, g.eff("resClose", "atrium.map.set", "dbui", key=g.k("res"), value=g.k(0)))
    g.edge(cP, g.eff("trustSet", "atrium.map.set", "progress", key=g.k("trustAdj"), value=g.x("adjN", "trustTo - 3")))
    # the paper's sidebar variant (§3.3 判定順序): loss -> lose; win and infamy >= 3 -> notorious; else win
    g.x("ocIdx", "winN ? (inf >= 3 ? 1 : 0) : 2")
    oc = g.lookup("ocWord", ["win", "notorious", "lose"], "ocIdx")
    g.edge(g.latch("ocL", oc, cP), "world.caseOutcome")
    br = g.lookup("brWord", ["win", "win", "lose"], "ocIdx")
    g.edge(g.latch("brL", br, cP), "world.resultBranch")
    # a win: the cards the result scene gives (ruling F3: E02_08 into the private collection); a Ch.2 loss: the
    # golden clue goes (10-cases: G-01 becomes S-01)
    g.edge(g.when("afterG", cP, "winC.out"), add_all(g, "afterAdd", "held", "dc_after"))
    g.edge(g.when("ungoldG", cP, "lossC.out"), g.eff("ungold", "atrium.coll.remove", "golden", value="dc_ungold"))
    g.edge(cP, "world.resultLines")
    # retry (A-14): back to the debate step; nothing of this result has been applied, the board stays
    rP = g.when("retryG", "ui#result.retry", T("retryIn", "isResN && resOn == 1 && lossN"))
    g.edge(rP, g.eff("resCloseR", "atrium.map.set", "dbui", key=g.k("res"), value=g.k(0)))
    g.edge(rP, "world.debRetry")
    return g
