"""The v2 demo D01 debate screen (M2), imported by tools/gen_flows.py: flows/d01_debate_ui.xtflow (the d1debate UI:
the engine's loadout and commands, its outputs on ui#d1debate and ui#cutin, the player's choices, the playback of the
engine's event records), its support tables under data/flow/ (d1ui*) and the game.json entries it adds. See
docs/flows.md §4.12 and docs/ui-contracts.md d1debate; the engine interface is docs/debate-engine-v2.md §2.

Same rules as gen_flows / gen_debui (edge order, no feedback, collections are read back on the next tick): the UI's
own state lives in the maps `u1` (numbers) and `u1S` (strings); the stages run on a beat and are chosen by u1 keys.
The engine's outputs (world.d1*) are latched when a round is shown, so the screen keeps the round while the next
round's values are already on the bus. The UI greys out every choice the engine would not accept (debate-engine-v2
§4: the engine does not validate commands).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import gen_flows as F
from gen_flows import Graph, tref
from gen_debui import add_all, setter, ssel, truth

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ref" / "src"))
from sherefox_ref.v2 import model as M  # noqa: E402
from sherefox_ref.v2.data import load_chapter  # noqa: E402
from sherefox_ref.v2.routes import ROUTES  # noqa: E402

CH = load_chapter()
UI = "d1debate"
P = f"ui#{UI}"
# The dev entry's loadout (ref routes.py route A, ch §12.1); warm-up result pass_clean (M2 brief).
DEV = ROUTES["A"].loadout
DEV_WARMUP = "pass_clean"
# Player actions: the d1debate act number -> engine command word (debate-engine-v2 §2.1 d1CmdKind).
ACTS = ["", "argue", "intercept", "dismantle", "stall", "cut", "accept", "last_stand"]
CLAIM_ACTS = (1, 2, 3, 5, 7)
OPP_WORDS = ["attack", "force", "rebut", "parry", "last"]          # tell_a / tell_b 0..4
ISSUE = {"機": "OPP", "法": "METHOD", "動": "MOTIVE"}               # ISSUE_D01_<x>[_SHORT]
SEQ_BASE = 100000   # cut-in sequence numbers start here: v1's debate_ui writes the same ports from 0 up
# Playback dwell after a record (seconds): nothing, a number only, a system line, a spoken line, a cut-in, 論破.
DWELL = [0.001, 0.5, 1.8, 2.4, 1.6, 4.0]
DELAY = 0.1      # d1Start / d1Lock -> the engine's outputs are read (written after this flow; queries next tick)
HOLD = 0.6       # after the last record, before the next round is shown


# ---------------------------------------------------------------------------------------------- tables

def ev_key(e: str) -> str:
    return f"C_D01_{e}_NAME" if CH.evidence[e].psych_card else f"E_D01_{e[1:]}_NAME"


def tables() -> dict[str, list[dict]]:
    claims = []
    for cid, c in CH.claims.items():
        claims.append({"id": cid, "evidence": c.evidence, "label": f"CLM_D01_{cid}", "line": f"CLM_D01_{cid}_LINE",
                       "issue": f"ISSUE_D01_{ISSUE[c.issue]}_SHORT", "issueName": f"ISSUE_D01_{ISSUE[c.issue]}",
                       "catch": 0, "psych": int(c.psych_card), "private": int(c.private)})
    for cid, cd in CH.cards.items():
        if cd.kind == "unfav":
            claims.append({"id": f"{M.CATCH}:{cid}", "evidence": M.CATCH, "label": "UI_V2_SEIZE",
                           "line": f"CARD_D01_{cid}_CATCH", "issue": f"ISSUE_D01_{ISSUE[cd.issue]}_SHORT",
                           "issueName": f"ISSUE_D01_{ISSUE[cd.issue]}", "catch": 1, "psych": 0, "private": 0})
    cards = []
    for cid, cd in CH.cards.items():
        cards.append({"id": cid, "kind": cd.kind, "label": f"CARD_D01_{cid}",
                      "issue": f"ISSUE_D01_{ISSUE[cd.issue]}_SHORT" if cd.issue else "",
                      "state": f"CARD_D01_{cid}_STATE", "push": f"CARD_D01_{cid}_PUSH",
                      "retract": f"CARD_D01_{cid}_RETRACT", "down": f"CARD_D01_{cid}_DOWN",
                      "tell": f"CARD_D01_{cid}_TELL" if cd.kind == "unfav" else ""})
    ev = [{"id": e, "name": ev_key(e)} for e in CH.evidence] + [{"id": M.CATCH, "name": "UI_V2_SEIZE"}]
    # spoken lines that replace the default one: CUT_D01_<claim>_<card> (his reaction to that cut, replaces _DOWN)
    # and LINK_D01_<a>_<b> (承接, replaces the claim line); only keys the string tables have
    keys = F.string_keys()
    lines = []
    for k in sorted(keys):
        parts = k.split("_")
        if k.startswith("CUT_D01_") and len(parts) == 4:
            lines.append({"id": f"CUT:{parts[2]}:{parts[3]}", "key": k})
        elif k.startswith("LINK_D01_") and len(parts) == 4:
            lines.append({"id": f"LINK:{parts[2]}:{parts[3]}", "key": k})
    return {"d1uiClaim": claims, "d1uiCard": cards, "d1uiEv": ev, "d1uiLine": lines}


SIGNALS = {
    "d1Back": {"type": "pulse"},     # d01_debate_ui -> main: the outcome panel's back to title
}
COLLECTIONS = {
    "u1": {"kind": "map", "type": "number", "capacity": 48},
    "u1S": {"kind": "map", "type": "string", "capacity": 16},
    "u1F": {"kind": "list", "type": "string", "capacity": 16},          # the record being played, split at |
    "u1N": {"kind": "list", "type": "number", "capacity": 16},
    "u1Ev": {"kind": "list", "type": "string", "capacity": 24, "unique": True},   # evidence with claims
    "u1EvSel": {"kind": "map", "type": "bool", "capacity": 24},
    "u1Cl": {"kind": "list", "type": "string", "capacity": 16},         # claims of the chosen evidence
    "u1ClOk": {"kind": "map", "type": "number", "capacity": 40},
    "u1ClSel": {"kind": "map", "type": "bool", "capacity": 16},
    "u1ClKind": {"kind": "map", "type": "string", "capacity": 16},
    "u1ClCrk": {"kind": "map", "type": "string", "capacity": 16},
    "u1ClStd": {"kind": "map", "type": "string", "capacity": 16},
    "u1ClXtr": {"kind": "map", "type": "string", "capacity": 16},
    "u1OSel": {"kind": "map", "type": "bool", "capacity": 16},
    "u1PCr": {"kind": "map", "type": "number", "capacity": 16},
    "u1Iss": {"kind": "map", "type": "number", "capacity": 4},
    "u1Rec": {"kind": "list", "type": "string", "capacity": 32},
    "u1RecId": {"kind": "map", "type": "string", "capacity": 32},
    "u1RecN": {"kind": "map", "type": "number", "capacity": 32},
    "u1RecL": {"kind": "map", "type": "string", "capacity": 32},
    "u1RecU": {"kind": "map", "type": "string", "capacity": 32},
    "u1RecS": {"kind": "map", "type": "string", "capacity": 32},
    "u1RecC": {"kind": "map", "type": "string", "capacity": 32},
    "u1RecSt": {"kind": "map", "type": "string", "capacity": 32},
}


# ---------------------------------------------------------------------------------------------- the flow

def gen_d01ui() -> Graph:
    g = Graph()
    T = truth(g)
    langEn = g.put("langEn", g.cmp("langEnC", "world.language", g.k("en")))
    setn, sets = setter(g, "u1"), setter(g, "u1S")
    g.text("oppName", g.k("SPK_D01_CEDRIC"))

    # ---- UI state
    for k in ("ph", "act", "armed", "stAt", "rsAt", "lockAt", "r2", "ref", "pb", "pbAt", "ev", "hpM", "hpO", "pat",
              "endAt"):
        g.mget("d_" + k, "u1", g.k(k))
    for k in ("ev", "claim", "target"):
        g.mget("s_" + k, "u1S", g.k(k))
    g.n("hasClaimN", g.cmp("hasClaimC", "s_claim", g.k(""), "ne"))
    g.n("hasTgtN", g.cmp("hasTgtC", "s_target", g.k(""), "ne"))
    g.n("hasEvN", g.cmp("hasEvC", "s_ev", g.k(""), "ne"))

    # ---- the beat (every tick) and the stages (u1 flags / times; a stage clears its own key)
    g.node("clock", "clock")
    g.put("now", "clock.seconds")
    g.node("beat", "filter", op="deadband", threshold=0)
    g.edge("clock.seconds", "beat.in")
    g.n("settingsOnN", "world.settingsShown")
    beat = g.when("beatOn", "beat.passed", T("beatOk", "!settingsOnN"))

    def stage(name: str, cond: str, clear: str | None = None) -> str:
        p = g.when(name, beat, T(name + "Go", cond))
        if clear:
            setn(p, clear, g.k(0))
        return p

    stT = stage("stG", "d_stAt > 0 && now >= d_stAt", "stAt")
    rsT = stage("rsG", "d_rsAt > 0 && now >= d_rsAt", "rsAt")
    r2T = stage("r2G", "d_r2 > 0", "r2")
    refT = stage("refG", "d_ref > 0", "ref")
    lockT = stage("lockG2", "d_lockAt > 0 && now >= d_lockAt", "lockAt")
    g.x("soon", f"now + {DELAY}")

    # ---- start (the title's v2 entry): reset, the loadout (written now, read by d1Start a few ticks later)
    start = g.merge("start", "ui#title.v2demo")
    for coll in ("u1", "u1S", "u1RecId", "u1RecN", "u1RecL", "u1RecU", "u1RecS", "u1RecC", "u1RecSt"):
        g.edge(start, g.eff(f"clr_{coll}", "atrium.map.clear", coll))
    for coll, items in (("d1Carry", DEV.carried), ("d1Appraised", DEV.appraisals), ("d1Notes", DEV.notes)):
        g.edge(start, g.eff(f"clr_{coll}", "atrium.coll.clear", coll))
        g.edge(start, add_all(g, f"add_{coll}", coll, g.k(",".join(items))))
    g.edge(start, g.eff("clr_u1Rec", "atrium.coll.clear", "u1Rec"))
    g.x("stSoon", "now + 0.1")
    setn(start, "stAt", "stSoon")
    g.edge(g.k(DEV_WARMUP), "world.d1Warmup")
    g.edge(stT, "world.d1Start")
    setn(stT, "rsAt", "soon")

    # ---- a round is shown: latch the engine, reset the choice, rebuild the lists on the next beat
    rs = g.merge("rs", rsT)
    num = ["d1Round", "d1RoundLimit", "d1PlayerHp", "d1PlayerMax", "d1OppHp", "d1OppMax", "d1PCombo", "d1Hachiku",
           "d1Broken", "d1Shisshu", "d1PsychP", "d1PsychG", "d1PsychA", "d1ThreshP", "d1ThreshG", "d1ThreshA",
           "d1OverP", "d1OverG", "d1OverA", "d1Cracks", "d1GuardUsed", "d1Dying", "d1TellPartial", "d1Grade"]
    txt = ["d1Phase", "d1TellClarity", "d1TellShown1", "d1TellShown2", "d1TellStar", "d1TellCard", "d1TellAction",
           "d1LastCard", "d1Outcome", "d1CatchCard"]
    for sig in num + txt:
        g.latch("L_" + sig[2:], f"world.{sig}", rs)
    phase_i = ssel(g, "phW", [(g.cmp("phEg", "L_Phase", g.k("endgame")), g.k(1)),
                               (g.cmp("phLs", "L_Phase", g.k("laststand")), g.k(2)),
                               (g.cmp("phOv", "L_Phase", g.k("over")), g.k(3))], g.k(0))
    g.put("modeN", phase_i)
    g.x("phNew", "modeN == 3 ? 3 : 1")
    setn(rs, "ph", "phNew")
    setn(rs, "act", g.k(0))
    setn(rs, "armed", g.k(0))
    setn(rs, "hpM", "world.d1PlayerHp")
    setn(rs, "hpO", "world.d1OppHp")
    for k in ("claim", "target"):
        sets(rs, k, g.k(""))
    setn(rs, "r2", g.k(1))

    # ---- the lists (rebuilt on the next beat after a round is shown, after a choice, on a language change)
    refresh = g.merge("refresh", r2T, refT, "langEnC.true", "langEnC.false")
    g.put("act", g.p("d_act"))
    # evidence chips: the evidence of the claim picker's claims, in its order (抓住他的話 first)
    for coll in ("u1Ev",):
        g.edge(refresh, g.eff("clr_" + coll, "atrium.coll.clear", coll))
    for coll in ("u1EvSel", "u1Cl"):
        typ = "atrium.coll.clear" if coll == "u1Cl" else "atrium.map.clear"
        g.edge(refresh, g.eff("clr_" + coll, typ, coll))
    for coll in ("u1ClOk", "u1ClSel", "u1ClKind", "u1ClCrk", "u1ClStd", "u1ClXtr", "u1OSel", "u1PCr", "u1Iss"):
        g.edge(refresh, g.eff("clr_" + coll, "atrium.map.clear", coll))
    g.node("evEach", "atrium.coll.forEach", name="d1ClaimList")
    g.edge(refresh, "evEach.trigger")
    ei = g.put("ei", "evEach.item")
    g.tget("eiEv", "d1uiClaim", "evidence", g.tfind("eiRow", "d1uiClaim", "id", ei))
    g.edge("evEach.each", g.eff("evAdd", "atrium.coll.add", "u1Ev", value="eiEv"))
    g.edge("evEach.each", g.eff("evSelSet", "atrium.map.set", "u1EvSel", key="eiEv",
                                  value=g.cmp("eiSel", "eiEv", "s_ev")))
    g.edge("evEach.done", g.ui_list("evList", f"ui.{UI}.ev_list", "u1Ev",
                                    {"id": "item", "name": tref("d1uiEv", "id", "name"), "sel": "map:u1EvSel"},
                                    localize=["name"]))
    # claims of the chosen evidence; ok = the current action may use it (argue: not standing; the others: not
    # 抓住他的話, an argue option only)
    g.node("clEach", "atrium.coll.forEach", name="d1ClaimList")
    g.edge(refresh, "clEach.trigger")
    ci = g.put("ci", "clEach.item")
    crow = g.tfind("ciRow", "d1uiClaim", "id", ci)
    g.tget("ciEv", "d1uiClaim", "evidence", crow)
    g.tget("ciCatch", "d1uiClaim", "catch", crow, "number")
    g.tget("ciPsych", "d1uiClaim", "psych", crow, "number")
    g.tget("ciPriv", "d1uiClaim", "private", crow, "number")
    g.mget("ciStand", "d1ClaimStand", ci)
    g.mget("ciSoph", "d1ClaimSoph", ci)
    g.mget("ciCrack", "d1ClaimCrack", ci)
    g.n("ciInN", g.cmp("ciIn", "ciEv", "s_ev"))
    g.x("ciOk", "act == 1 ? !ciStand : (act == 2 || act == 3 || act == 5 || act == 7) ? !ciCatch : 0")
    clG = g.when("clG", "clEach.each", "ciIn.out")
    g.edge(clG, g.eff("clAdd", "atrium.coll.add", "u1Cl", value=ci))
    g.edge(clG, g.eff("clOk", "atrium.map.set", "u1ClOk", key=ci, value="ciOk"))
    g.edge(clG, g.eff("clSel", "atrium.map.set", "u1ClSel", key=ci, value=g.cmp("ciSel", ci, "s_claim")))
    kind = g.sel("ciKindK", g.b("ciSophB", "ciSoph"), g.k("UI_V2_CLAIM_SOPH"), g.k("UI_V2_CLAIM_SOUND"))
    g.edge(clG, g.eff("clKind", "atrium.map.set", "u1ClKind", key=ci, value=kind))
    g.edge(clG, g.eff("clCrk", "atrium.map.set", "u1ClCrk", key=ci,
                      value=g.sel("ciCrkK", g.b("ciCrkB", "ciCrack"), g.k("UI_V2_CLAIM_CRACK"), g.k(""))))
    g.edge(clG, g.eff("clStd", "atrium.map.set", "u1ClStd", key=ci,
                      value=g.sel("ciStdK", g.b("ciStdB", "ciStand"), g.k("UI_V2_CLAIM_ON_CHAIN"), g.k(""))))
    xtr = ssel(g, "ciXtr", [(g.b("ciPsB", "ciPsych"), g.k("UI_V2_CLAIM_PSYCH")),
                            (g.b("ciPrB", "ciPriv"), g.k("UI_V2_CLAIM_PRIVATE"))], g.k(""))
    g.edge(clG, g.eff("clXtr", "atrium.map.set", "u1ClXtr", key=ci, value=xtr))
    g.edge("clEach.done", g.ui_list("clList", f"ui.{UI}.claims", "u1Cl",
                                    {"id": "item", "label": tref("d1uiClaim", "id", "label"),
                                     "issue": tref("d1uiClaim", "id", "issue"), "kind": "map:u1ClKind",
                                     "soph": "map:d1ClaimSoph", "crack": "map:u1ClCrk", "stand": "map:u1ClStd",
                                     "extra": "map:u1ClXtr", "ok": "map:u1ClOk", "sel": "map:u1ClSel"},
                                    localize=["label", "issue", "kind", "crack", "stand", "extra"]))
    # his chain (sel = the chosen target)
    g.node("ocEach", "atrium.coll.forEach", name="d1OChain")
    g.edge(refresh, "ocEach.trigger")
    g.edge("ocEach.each", g.eff("ocSel", "atrium.map.set", "u1OSel", key="ocEach.item",
                                  value=g.cmp("ocSelC", "ocEach.item", "s_target")))
    g.edge("ocEach.done", g.ui_list("ocList", f"ui.{UI}.ochain", "d1OChain",
                                    {"id": "item", "label": tref("d1uiCard", "id", "label"),
                                     "issue": tref("d1uiCard", "id", "issue"), "sel": "map:u1OSel"},
                                    localize=["label", "issue"]))
    # our chain (crack = d1State pk_<claim>); u1Iss = the issues it covers (論破進度)
    g.node("pcEach", "atrium.coll.forEach", name="d1PChain")
    g.edge(refresh, "pcEach.trigger")
    pi = g.put("pi", "pcEach.item")
    g.mget("piCrack", "d1State", g.fmt("piKey", "pk_{a}", pi))
    g.edge("pcEach.each", g.eff("pcCr", "atrium.map.set", "u1PCr", key=pi, value="piCrack"))
    g.tget("piIss", "d1uiClaim", "issue", g.tfind("piRow", "d1uiClaim", "id", pi))
    g.edge("pcEach.each", g.eff("pcIss", "atrium.map.set", "u1Iss", key="piIss", value=g.k(1)))
    g.edge("pcEach.done", g.ui_list("pcList", f"ui.{UI}.pchain", "d1PChain",
                                    {"id": "item", "label": tref("d1uiClaim", "id", "label"),
                                     "issue": tref("d1uiClaim", "id", "issue"), "crack": "map:u1PCr"},
                                    localize=["label", "issue"]))
    # the public record (rows added at each lock; standing / knocked down read now)
    g.node("rcEach", "atrium.coll.forEach", name="u1Rec")
    g.edge(refresh, "rcEach.trigger")
    rk = g.put("rk", "rcEach.item")
    g.mget("rkId", "u1RecId", rk)
    g.mget("rkU", "u1RecU", rk)
    g.mget("rkStand", "d1ClaimStand", "rkId")
    g.n("rkArgN", g.cmp("rkArg", "rkU", g.k("")))
    g.tget("rkCatch", "d1uiClaim", "catch", g.tfind("rkRow", "d1uiClaim", "id", "rkId"), "number")
    st = ssel(g, "rkSt", [(g.b("rkNoSt", g.x("rkNoStN", "!rkArgN || rkCatch")), g.k("")),
                          (g.b("rkStB", "rkStand"), g.k("UI_V2_RECORD_STANDING"))], g.k("UI_V2_RECORD_DOWN"))
    g.edge("rcEach.each", g.eff("rcSt", "atrium.map.set", "u1RecSt", key=rk, value=st))
    g.edge("rcEach.done", g.ui_list("rcList", f"ui.{UI}.record", "u1Rec",
                                    {"n": "map:u1RecN", "label": "map:u1RecL", "use": "map:u1RecU",
                                     "soph": "map:u1RecS", "crack": "map:u1RecC", "state": "map:u1RecSt"},
                                    localize=["label", "use", "soph", "crack", "state"]))

    # ---- what can be chosen
    g.count("ocN", "d1OChain")
    g.count("pcN", "d1PChain")
    g.count("issN", "u1Iss")
    g.x("inOk", "d_ph == 1")
    g.x("needClaim", " || ".join(f"act == {a}" for a in CLAIM_ACTS))
    g.x("needTgt", "act == 3")
    g.x("canLock", "inOk && (act == 4 || act == 6 || (needClaim && hasClaimN && (!needTgt || hasTgtN)))")
    g.x("guardOk", "inOk && modeN == 0 && !L_GuardUsed")
    # pick_act
    g.put("aV", f"{P}.pick_act")
    g.x("aOk", "inOk && ((modeN == 0 && (aV == 1 || aV == 2 || aV == 4 || (aV == 3 && ocN > 0))) || "
               "(modeN == 1 && (aV == 5 || aV == 6)) || (modeN == 2 && (aV == 7 || aV == 6)))")
    aP = g.when("aG", f"{P}.pick_act.emitted", "aOk_t")
    setn(aP, "act", "aV")
    sets(aP, "claim", g.k(""))
    sets(aP, "target", g.k(""))
    g.cget("ev0", "u1Ev", g.k(0))
    sets(g.when("aEvG", aP, T("aEvN", "!hasEvN")), "ev", "ev0")
    setn(aP, "ref", g.k(1))
    # pick_ev
    evP = g.when("evG", f"{P}.pick_ev.emitted", "inOk_t")
    sets(evP, "ev", f"{P}.pick_ev")
    setn(evP, "ref", g.k(1))
    # pick_claim (only an enabled one)
    g.mget("cOkV", "u1ClOk", f"{P}.pick_claim")
    cP = g.when("cG", f"{P}.pick_claim.emitted", T("cOk", "inOk && needClaim && cOkV == 1"))
    sets(cP, "claim", f"{P}.pick_claim")
    setn(cP, "ref", g.k(1))
    # pick_target (dismantle; §7.5 optional)
    g.n("tOnN", g.contains("tOnC", "d1OChain", f"{P}.pick_target"))
    tP = g.when("tG", f"{P}.pick_target.emitted", T("tOk", "inOk && (act == 3 || act == 7) && tOnN"))
    sets(tP, "target", f"{P}.pick_target")
    setn(tP, "ref", g.k(1))
    # guard (援護, once per debate, armed before the lock)
    setn(g.when("gG", f"{P}.guard", "guardOk_t"), "armed", g.x("armT", "1 - d_armed"))

    # ---- lock: the command on the bus (the engine runs later in this tick), then the pulse
    g.edge(g.lookup("cmdKind", ACTS, "act"), "world.d1CmdKind")
    g.edge(g.sel("cmdClaim", "needClaim_t", "s_claim", g.k("")), "world.d1CmdClaim")
    g.edge(g.sel("cmdTgt", T("useTgt", "act == 3 || act == 7"), "s_target", g.k("")), "world.d1CmdTarget")
    g.edge(g.x("cmdGuard", "modeN == 0 && d_armed"), "world.d1CmdGuard")
    lP = g.when("lockG", f"{P}.lock", "canLock_t")
    g.edge(lP, "world.d1Lock")
    setn(lP, "ph", g.k(2))
    setn(lP, "lockAt", "soon")
    # the public record: one row per claim used (ref RecordEntry: soph / red crack as displayed when chosen)
    g.count("recN", "u1Rec")
    rkey = g.fmt("recKey", "r{a}", "recN")
    rP = g.when("recG", lP, "needClaim_t")
    g.edge(rP, g.eff("recAdd", "atrium.coll.add", "u1Rec", value=rkey))
    crow2 = g.tfind("scRow", "d1uiClaim", "id", "s_claim")
    g.tget("scLabel", "d1uiClaim", "label", crow2)
    g.tget("scLine", "d1uiClaim", "line", crow2)
    g.tget("scIssueName", "d1uiClaim", "issueName", crow2)
    g.mget("scSoph", "d1ClaimSoph", "s_claim")
    g.mget("scCrack", "d1ClaimCrack", "s_claim")
    use = g.lookup("recUse", ["", "", "UI_V2_RECORD_REBUT", "UI_V2_RECORD_REBUT", "", "UI_V2_RECORD_REBUT", "",
                              "UI_V2_RECORD_REBUT"], "act")
    for coll, val in (("u1RecId", "s_claim"), ("u1RecN", "L_Round"), ("u1RecL", "scLabel"), ("u1RecU", use),
                      ("u1RecS", g.sel("recS", g.b("recSB", "scSoph"), g.k("UI_V2_CLAIM_SOPH"), g.k(""))),
                      ("u1RecC", g.sel("recC", g.b("recCB", "scCrack"), g.k("UI_V2_LINK_CRACKED"), g.k("")))):
        g.edge(rP, g.eff(f"rec_{coll}", "atrium.map.set", coll, key=rkey, value=val))

    # ---- playback of the round's records (d1Events, debate-engine-v2 §2.3): pb 1 fetch, 2 play, 3 wait
    setn(lockT, "ev", g.k(0))
    setn(lockT, "pb", g.k(1))
    stepP = stage("fetchG", "d_pb == 1")
    g.count("evCnt", "d1Events")
    g.cget("evRec", "d1Events", "d_ev")
    more = g.when("moreG", stepP, T("more", "d_ev < evCnt"))
    g.edge(more, g.eff("fClr", "atrium.coll.clear", "u1F"))
    g.edge(more, g.eff("nClr", "atrium.coll.clear", "u1N"))
    g.edge(more, add_all(g, "fAdd", "u1F", "evRec", "|"))
    g.edge(more, add_all(g, "nAdd", "u1N", "evRec", "|"))
    setn(more, "ev", g.x("evNext", "d_ev + 1"))
    setn(more, "pb", g.k(2))
    endT = g.when("evDone", stepP, T("evOver", "!more"))
    setn(endT, "pb", g.k(0))
    g.x("endSoon", f"now + {HOLD}")
    setn(endT, "rsAt", "endSoon")
    parse = stage("parseG", "d_pb == 2")
    setn(parse, "pb", g.k(3))
    waitP = stage("waitG", "d_pb == 3 && now >= d_pbAt")
    setn(waitP, "pb", g.k(1))
    setn(g.when("skipG", f"{P}.skip", T("skipOn", "d_ph == 2 && d_pb == 3")), "pbAt", "now")
    for k in range(11):
        g.cget(f"f{k}", "u1F", g.k(k))
        g.cget(f"n{k}", "u1N", g.k(k))
    kinds = ["round", "pAttach", "oAttach", "pDmg", "oDmg", "oHeal", "reraise", "refuted", "blocked", "intercept",
             "dismantle", "guardSaved", "broken", "hachiku", "shisshu", "crossed", "ronpa", "reverseRonpa",
             "endgame", "lastCard", "lastStand", "over"]
    for kd in kinds:
        g.n("k_" + kd, g.cmp("kc_" + kd, "f0", g.k(kd)))

    def isS(name: str, port: str, val: str) -> str:
        g.n(name, g.cmp(name + "C", port, g.k(val)))
        return name
    for c in ("argument", "exposed", "refuted", "contradiction", "whiff", "fact_miss", "stalemate", "stall_repeat",
              "bad_cut", "dying", "last_card", "intercept", "dismantle"):
        isS("c_" + c, "f2", c)
    isS("hisForce", "L_TellAction", "force")
    isS("hisParry", "L_TellAction", "parry")
    for v in ("P", "G", "A"):
        isS("x" + v, "f1", v)
    isS("egZero", "f1", "zero")
    isS("ovWin", "f1", "win")
    isS("rsSurr", "f3", "surrender")
    isS("rsLimit", "f3", "round_limit")
    g.n("knownN", g.cmp("knownC", "f3", g.k(""), "ne"))
    g.n("prevN", g.cmp("prevC", "f10", g.k(""), "ne"))
    # cards and claims named by the record
    card = g.sel("recCard", T("cardF2", "k_intercept || k_dismantle"), g.fmt("f2s", "{a}", "f2"), g.fmt("f1s", "{a}", "f1"))
    krow = g.tfind("kRow", "d1uiCard", "id", card)
    for c in ("state", "push", "retract", "down", "kind", "label"):
        g.tget("k_" + c + "K", "d1uiCard", c, krow)
    isS("cardUnfav", "k_kindK", "unfav")
    g.tget("tgtLabel", "d1uiCard", "label", g.tfind("tgRow", "d1uiCard", "id", "s_target"))
    g.tget("f2Label", "d1uiCard", "label", g.tfind("f2Row", "d1uiCard", "id", "f2"))
    g.tget("f1IssueName", "d1uiClaim", "issueName", g.tfind("f1Row", "d1uiClaim", "id", "f1"))
    linkRow = g.tfind("lkRow", "d1uiLine", "id", g.fmt("lkId", "LINK:{a}:{b}", "f10", "f1"))
    g.tget("lkKey", "d1uiLine", "key", linkRow)
    g.x("lkOk", "lkRow >= 0 && prevN")
    cutRow = g.tfind("cuRow", "d1uiLine", "id", g.fmt("cuId", "CUT:{a}:{b}", "f1", "f2"))
    g.tget("cuKey", "d1uiLine", "key", cutRow)
    g.x("cuOk", "cuRow >= 0")
    g.x("fogI", "(L_Round - 1) - 3 * floor((L_Round - 1) / 3)")
    fog = g.lookup("fogK", ["FOG_D01_1", "FOG_D01_2", "FOG_D01_3"], "fogI")
    hkLine = g.lookup("hkK", ["", "STATE_D01_SHF_HACHIKU_1", "STATE_D01_SHF_HACHIKU_2", "STATE_D01_SHF_HACHIKU_3"],
                      g.x("hkI", "clamp(n2, 0, 3)"))
    claim_act = " || ".join(f"act == {a}" for a in CLAIM_ACTS)

    # spoken line: (condition, speaker key, line key)
    SH, CE, AR = g.k("SPK_SHEREFOX"), g.k("SPK_D01_CEDRIC"), g.k("SPK_ARTHUR")
    speech = [
        (T("sp1", f"k_round && ({claim_act}) && hasClaimN"), SH, "scLine"),
        (T("sp2", "k_round && act == 4"), SH, fog),
        (T("sp3", "k_pAttach && lkOk"), SH, "lkKey"),
        (T("sp4", "k_oAttach"), CE, g.sel("oaLine", g.b("hisForceB", "hisForce"),
                                         "k_pushK", "k_stateK")),
        (T("sp5", "k_reraise"), CE, "k_retractK"),
        (T("sp6", "k_refuted"), CE, "f2"),
        (T("sp7", "k_intercept && n3 == 1"), CE, g.sel("icLine", "cuOk_t", "cuKey", "k_downK")),
        (T("sp8", "k_dismantle && n3 == 1"), CE, "k_downK"),
        (T("sp9", "k_guardSaved"), AR, g.k("STATE_D01_ART_COVER")),
        (T("sp10", "k_hachiku && n2 > n1"), SH, hkLine),
        (T("sp11", "k_ronpa"), SH, g.k("STATE_D01_SHF_BREAK")),
        (T("sp12", "k_reverseRonpa"), CE, g.k("BEAT_D01_REVERSE_1")),
        (T("sp13", "k_lastCard && n2 == 1"), CE, "k_downK"),
        (T("sp14", "k_lastStand && n3 == 0"), CE, g.k("BEAT_D01_LASTSTAND_FAIL_1")),
        (T("sp15", "k_crossed && xG"), AR, g.k("BEAT_D01_GUILT_1")),
        (T("sp16", "k_crossed && xA"), CE, g.k("BEAT_D01_ANGER_1")),
    ]
    g.x("hasSpeech", " || ".join(f"sp{i}" for i in range(1, len(speech) + 1)))
    who = ssel(g, "spWho", [(c, w) for c, w, _ in speech], g.k(""))
    line = ssel(g, "spLine", [(c, ln) for c, _, ln in speech], g.k(""))
    spP = g.when("spG", parse, T("spOn", "hasSpeech || k_round"))
    g.text("whoT", g.latch("whoL", who, spP))
    g.text("lineT", g.latch("lineL", line, spP))
    g.edge("whoT.text", f"{P}.speech_who")
    g.edge("lineT.text", f"{P}.speech")

    # system line: (condition, template key); its values latched with it
    g.tget("lcKind", "d1uiCard", "kind", g.tfind("lcRow", "d1uiCard", "id", "L_LastCard"))
    isS("lcPicked", "lcKind", "pickup")
    lc0 = g.sel("lcF0", T("lcZero", "L_Cracks == 0"), g.fmt("lcZ", "{a}", g.k(M.LAST_ZERO_C_DMG)),
                g.fmt("lcC", "{a} × {b}", g.k(M.LAST_PER_CRACK), "L_Cracks"))
    lcF = g.sel("lcF", g.b("lcPickedB", "lcPicked"),
                g.fmt("lcP", "{a} + {b}", lc0, g.k(M.LAST_PICKED_EXTRA)), lc0)
    parts = [g.fmt("fmA", "{a} × {b}", "n4", "n5")]
    for i, (nk, nm) in enumerate((("n6", "fmL"), ("n7", "fmR"), ("n8", "fmH"), ("n9", "fmB"))):
        parts.append(g.sel(nm, T(nm + "On", f"{nk} != 1"), g.fmt(nm + "T", " × {a}", nk), g.k("")))
    formula = g.fmt("fmAll2", "{a}{b}", g.fmt("fmAll", "{a}{b}{c}{d}", *parts[:4]), parts[4])
    sysl = [
        (T("sy1", "k_pAttach"), "SYS_D01_ATTACH"),
        (T("sy2", "k_oAttach && cardUnfav"), "SYS_D01_SLIP_NODMG"),
        (T("sy3", "k_pDmg && c_argument && act == 4"), "SYS_D01_FOG_TAKE"),
        (T("sy4", "k_pDmg && c_exposed"), "SYS_D01_EXPOSED"),
        (T("sy5", "k_pDmg && c_refuted"), "SYS_D01_REFUTED"),
        (T("sy6", "k_pDmg && c_contradiction"), "SYS_D01_REDCRACK"),
        (T("sy7", "k_pDmg && c_whiff && hisParry && act == 2"), "SYS_D01_CUT_EMPTY"),
        (T("sy8", "k_pDmg && (c_whiff || c_bad_cut)"), "SYS_D01_MISS_WRONG"),
        (T("sy9", "k_pDmg && c_fact_miss"), "SYS_D01_MISS_FACT"),
        (T("sy10", "k_pDmg && c_stalemate && act == 4"), "SYS_D01_FOG_STALL"),
        (T("sy11", "k_pDmg && c_stalemate"), "SYS_D01_BOTH_REBUT"),
        (T("sy12", "k_pDmg && c_stall_repeat"), "SYS_D01_FOG_REPEAT"),
        (T("sy13", "k_pDmg && c_dying"), "SYS_D01_DESPERATE_HIT"),
        (T("sy14", "k_pDmg && c_last_card"), "SYS_D01_LASTCARD_NOHEAL"),
        (T("sy15", "k_oDmg && c_intercept && hisForce"), "SYS_D01_CUT_PUSH"),
        (T("sy16", "k_oDmg && c_intercept"), "SYS_D01_CUT_OK"),
        (T("sy17", "k_oDmg && c_dismantle"), "SYS_D01_DISMANTLE"),
        (T("sy18", "k_oDmg && c_whiff"), "SYS_D01_FOOLED"),
        (T("sy19", "k_oHeal"), "SYS_D01_STALL_HEAL"),
        (T("sy20", "k_refuted && knownN"), "SYS_D01_NOW_KNOWN"),
        (T("sy21", "k_blocked"), "SYS_D01_BLOCKED"),
        (T("sy22", "k_guardSaved"), "SYS_D01_COVER"),
        (T("sy23", "k_shisshu && n1 == 1"), "SYS_D01_BREACH_HINT"),
        (T("sy24", "k_crossed"), "SYS_D01_PSYCH_CROSS"),
        (T("sy25", "k_ronpa"), "SCR_D01_S07_L005"),
        (T("sy26", "k_reverseRonpa"), "SYS_D01_REVERSE"),
        (T("sy27", "k_endgame && egZero"), "SCR_D01_S07_L006"),
        (T("sy28", "k_lastCard && n2 == 1"), "SYS_D01_CUT_WIN"),
        (T("sy29", "k_lastStand && n3 == 1"), "SYS_D01_LASTSTAND_OK"),
        (T("sy30", "k_lastStand && n3 == 0"), "SYS_D01_LASTSTAND_FAIL"),
        (T("sy31", "k_over && rsSurr"), "UI_V2_GIVE_UP"),
        (T("sy32", "k_over && rsLimit"), "UI_V2_TIME_UP"),
        (T("sy33", "k_over && ovWin"), "SYS_D01_WIN"),
        (T("sy34", "k_over"), "SCR_D01_S07_L016"),
    ]
    g.x("hasSys", " || ".join(f"sy{i}" for i in range(1, len(sysl) + 1)))
    skey = ssel(g, "syKey", [(c, g.k(k)) for c, k in sysl], g.k(""))
    syP = g.when("syG", parse, T("syOn", "hasSys || k_round"))
    # values: hp after (pDmg / oDmg n3, lastStand n4), damage n1 / n3, the values of oHeal, the gauge's name, ...
    g.x("vHp", "k_lastStand ? n4 : (k_oAttach ? d_hpM : n3)")
    g.x("vDmg", "k_pAttach ? n3 : n1")
    value = ssel(g, "vVal", [(g.cmp("xPC3", "f1", g.k("P")), g.k("UI_V2_GAUGE_PRESSURE")),
                             (g.cmp("xGC3", "f1", g.k("G")), g.k("UI_V2_GAUGE_GUILT"))], g.k("UI_V2_GAUGE_ANGER"))
    node = g.sel("vNode", g.b("vNodeB", "k_lastStand"), "f2Label", "tgtLabel")
    fact = g.sel("vFact", g.b("vFactB", "k_refuted"), g.fmt("vFactK", "{a}_FACT", "f2"), g.k(""))
    frm = g.sel("vFormula", g.b("vFrmB", "k_pDmg"), lcF, formula)
    lat = {nm: g.latch(nm + "L", src, syP) for nm, src in
           (("sk", skey), ("vHp", "vHp"), ("vDmg", "vDmg"), ("vHpB", "n1"), ("vHpA", "n2"), ("vC", "world.d1Cracks"),
            ("vValue", value), ("vNode", node), ("vClaim", "scLabel"), ("vIssue", "f1IssueName"), ("vFact", fact),
            ("vFormula", frm))}
    g.text("skT", lat["sk"])
    for nm in ("vValue", "vNode", "vClaim", "vIssue", "vFact"):
        g.text(nm + "T", lat[nm])
    sys_text = g.textf("sysF", pattern="skT.text", name="oppName.text", hp=lat["vHp"], dmg=lat["vDmg"],
                       hp_before=lat["vHpB"], hp_after=lat["vHpA"], hp_p=lat["vHp"], c=lat["vC"],
                       value="vValueT.text", node="vNodeT.text", claim="vClaimT.text", issue="vIssueT.text",
                       fact="vFactT.text", formula=lat["vFormula"])
    g.edge(sys_text, f"{P}.sys_line")
    g.counter("lineSeq", initial=0)
    g.edge(g.merge("lineM", spP, syP), "lineSeq.increment")
    g.edge("lineSeq.value", f"{P}.line_seq")

    # numbers: the gauges follow the records (after values); floats
    pdP = g.when("pdG", parse, T("pdOn", "k_pDmg"))
    setn(pdP, "hpM", "n3")
    fm = g.latch("fmL2", g.fmt("fmDmg", "−{a}", "n1"), pdP)
    odP = g.when("odG", parse, T("odOn", "k_oDmg"))
    setn(odP, "hpO", "n3")
    hlP = g.when("hlG", parse, T("hlOn", "k_oHeal"))
    setn(hlP, "hpO", "n2")
    fo = ssel(g, "foSel", [(g.b("foHeal", "k_oHeal"), g.fmt("foH", "+{a}", g.x("healAmt", "n2 - n1")))],
              g.fmt("foD", "−{a}", "n1"))
    foL = g.latch("foL", fo, g.merge("foM", odP, hlP))
    g.edge(foL, f"{P}.float_opp")
    g.edge(fm, f"{P}.float_me")
    g.counter("foSeq", initial=0)
    g.edge(g.merge("foM2", odP, hlP), "foSeq.increment")
    g.edge("foSeq.value", f"{P}.float_opp_seq")
    g.counter("fmSeq", initial=0)
    g.edge(pdP, "fmSeq.increment")
    g.edge("fmSeq.value", f"{P}.float_me_seq")
    setn(g.when("gsG", parse, T("gsOn", "k_guardSaved")), "hpM", "n1")
    setn(g.when("lsG", parse, T("lsOn", "k_lastStand && n3 == 1")), "hpM", "n4")
    setn(g.when("lcHG", parse, T("lcHOn", "k_lastCard && n2 == 0 && n3 == 0")), "hpO", "n5")
    setn(g.when("patOnG", parse, T("patOn", "k_pAttach")), "pat", g.k(1))
    setn(g.when("patOffG", parse, T("patOff", "k_round")), "pat", g.k(0))
    # 論破: his chain shatters
    g.counter("shatSeq", initial=0)
    g.edge(g.when("shatG", parse, T("shatOn", "k_ronpa")), "shatSeq.increment")
    g.edge("shatSeq.value", f"{P}.shatter_seq")

    # cut-ins (ui#cutin, same ids as v1; 動搖 now on 破防, ch §13): one big or one stamp per record
    bigs = [(T("bg1", "k_ronpa"), "CUT_RONPA"), (T("bg2", "k_reverseRonpa"), "CUT_REVERSE"),
            (T("bg3", "k_hachiku && n2 >= 3 && n1 < 3"), "CUT_HACHIKU3"), (T("bg4", "k_shisshu && n1 == 1"), "CUT_SHISSHU"),
            (T("bg5", "k_crossed && xP"), "CUT_KONJU"), (T("bg6", "k_broken"), "CUT_SHAKEN")]
    stamps = [(T("sm1", "k_intercept && n3 == 1"), "STAMP_PARRY"), (T("sm2", "k_intercept"), "STAMP_WHIFF"),
              (T("sm3", "k_dismantle && n3 == 0"), "STAMP_WHIFF"), (T("sm4", "k_oAttach && d_pat"), "STAMP_CLASH"),
              (T("sm5", "k_guardSaved"), "STAMP_ASSIST"), (T("sm6", "k_oDmg && c_whiff"), "STAMP_TRAP"),
              (T("sm7", "k_hachiku && n2 > n1 && n2 < 3"), "STAMP_HACHIKU"),
              (T("sm8", "k_hachiku && n2 < n1"), "STAMP_HACHIKU_LOST")]
    g.x("hasBig", " || ".join(f"bg{i}" for i in range(1, len(bigs) + 1)))
    g.x("hasStamp", "!hasBig && (" + " || ".join(f"sm{i}" for i in range(1, len(stamps) + 1)) + ")")
    bid = ssel(g, "bigId", [(c, g.k(k)) for c, k in bigs], g.k(""))
    sid = ssel(g, "stampId", [(c, g.k(k)) for c, k in stamps], g.k(""))
    bigP = g.when("bigG", parse, "hasBig_t")
    stP = g.when("stG2", parse, "hasStamp_t")
    g.edge(g.latch("bigL", bid, bigP), "ui#cutin.big")
    g.counter("bigSeq", initial=0)
    g.edge(bigP, "bigSeq.increment")
    g.edge(g.x("bigSeqOut", f"bigSeq == 0 ? 0 : bigSeq + {SEQ_BASE}"), "ui#cutin.big_seq")
    g.edge(g.latch("stL", sid, stP), "ui#cutin.stamp")
    g.edge(g.latch("stNL", "n2", stP), "ui#cutin.stamp_n")
    g.counter("stSeq", initial=0)
    g.edge(stP, "stSeq.increment")
    g.edge(g.x("stSeqOut", f"stSeq == 0 ? 0 : stSeq + {SEQ_BASE}"), "ui#cutin.stamp_seq")
    cutM = g.merge("cutM", bigP, stP)
    subKey = g.latch("subKeyL", g.fmt("subKey", "{a}_SUB", g.sel("subId", "hasBig_t", bid, sid)), cutM)
    g.text("subT", subKey)
    g.textf("subF", pattern="subT.text", n=g.latch("subNL", "n2", cutM))
    g.n("subLangN", langEn)
    g.n("subOnN", "world.cutinSub")
    g.edge(g.sel("subOut", T("subOn", "subLangN && subOnN"), "subF.text", g.k("")), "ui#cutin.subtitle")

    # the dwell before the next record
    g.x("dwell", "k_ronpa ? 5 : hasBig ? 4 : hasSpeech ? 3 : hasSys ? 2 : (k_pDmg || k_oDmg || k_oHeal) ? 1 : 0")
    g.lookup("dwellS", DWELL, "dwell")
    setn(parse, "pbAt", g.x("pbAtN", "now + dwellS"))

    # ---- the ports
    g.x("phOut", "d_ph == 2 ? 1 : d_ph == 3 ? 2 : 0")
    g.edge("phOut", f"{P}.phase")
    g.edge("modeN", f"{P}.mode")
    g.edge("act", f"{P}.act")
    g.edge(g.textf("roundT", key="UI_V2_ROUND", n="L_Round", max="L_RoundLimit"), f"{P}.round_text")
    g.edge("oppName.text", f"{P}.opp_name")
    g.edge(g.textf("credOpp", key="UI_V2_CRED_OPP", name="oppName.text"), f"{P}.opp_cred")
    g.edge(g.textf("ocTitle", key="UI_V2_CHAIN_OPP", name="oppName.text"), f"{P}.ochain_title")
    g.edge("d_hpM", f"{P}.hp_me")
    g.edge("d_hpO", f"{P}.hp_opp")
    g.edge("L_PlayerMax", f"{P}.hp_me_max")
    g.edge("L_OppMax", f"{P}.hp_opp_max")
    # psych bands (no numbers, ch §13): 0 平常, 1 浮動 (threshold - FLOAT_BAND and up), 2 失常 (over the threshold)
    bands = []
    for v in ("P", "G", "A"):
        g.x(f"band{v}", f"L_Over{v} ? 2 : L_Psych{v} >= L_Thresh{v} - {M.FLOAT_BAND} ? 1 : 0")
        g.edge(f"band{v}", f"{P}.band_{v.lower()}")
        bands.append(f"band{v}")
    # Cedric's face: guilt > angry > cornered > uneasy > composed (G over, A over, P over, any band wavering)
    g.x("face", "L_OverG ? 4 : L_OverA ? 3 : L_OverP ? 2 : (bandP + bandG + bandA > 0 || L_Broken) ? 1 : 0")
    g.edge("face", f"{P}.face")
    g.edge(g.textf("comboT", key="UI_V2_COMBO", n="L_PCombo"), f"{P}.combo_text")
    g.edge("L_Hachiku", f"{P}.hachiku")
    g.x("guardDown", "L_Broken && modeN == 0")
    g.edge("guardDown_t", f"{P}.guard_down")
    g.edge(g.b("shisB", "L_Shisshu"), f"{P}.shisshu")
    g.edge(g.textf("ronpaT", key="UI_V2_RONPA_PROGRESS", n="pcN", need=g.k(CH.ronpa_len), m="issN"),
           f"{P}.ronpa_text")
    g.x("ronpaShow", "modeN == 0")
    g.edge("ronpaShow_t", f"{P}.show_ronpa")
    g.x("ronpaReady", f"L_Broken && modeN == 0 && pcN >= {CH.ronpa_len - 1} && issN >= {CH.ronpa_issues}")
    g.edge("ronpaReady_t", f"{P}.ronpa_ready")
    # the tell (laststand: none)
    g.x("tellOn", "modeN == 0 || modeN == 1")
    g.edge("tellOn_t", f"{P}.tell_on")
    g.n("tellClearN", g.cmp("tellClearC", "L_TellClarity", g.k("clear")))
    g.edge("tellClearC.out", f"{P}.tell_clear")
    for nm, sig in (("ta", "L_TellShown1"), ("tb", "L_TellShown2")):
        g.tget(nm + "Code", "d1Code", "code", g.tfind(nm + "Row", "d1Code", "id", sig), "number")
        g.x(nm, f"{nm}Row >= 0 ? {nm}Code : -1")
    g.edge("ta", f"{P}.tell_a")
    g.edge(g.x("tbOut", "tellClearN ? -1 : tb"), f"{P}.tell_b")
    g.n("starA", g.cmp("starAC", "L_TellStar", "L_TellShown1"))
    g.n("starB", g.cmp("starBC", "L_TellStar", "L_TellShown2"))
    g.n("starNone", g.cmp("starNoneC", "L_TellStar", g.k("")))
    g.edge(g.x("starOut", "starNone ? -1 : starA ? 0 : starB ? 1 : -1"), f"{P}.tell_star")
    trow = g.tfind("tcRow", "d1uiCard", "id", "L_TellCard")
    g.tget("tcLabel", "d1uiCard", "label", trow)
    g.tget("tcTell", "d1uiCard", "tell", trow)
    g.edge(g.b("tPartB", "L_TellPartial"), f"{P}.tell_partial")
    g.text("tcText", g.sel("tcKey", g.b("tPartB2", "L_TellPartial"), "tcTell", "tcLabel"))
    g.edge("tcText.text", f"{P}.tell_card")
    # the gesture of a clear tell (TELL_D01_GESTURE_<action>); a vague tell shows none (design question)
    gest = g.lookup("gestK", ["TELL_D01_GESTURE_ASSERT", "TELL_D01_GESTURE_PUSH", "TELL_D01_GESTURE_REBUT",
                              "TELL_D01_GESTURE_STALL", ""], g.x("gestI", "clamp(ta, 0, 4)"))
    g.text("gestT", g.sel("gestSel", T("gestOn", "tellClearN && modeN == 0 && ta >= 0"), gest, g.k("")))
    g.edge("gestT.text", f"{P}.tell_gesture")
    g.edge(g.b("dyingB", "L_Dying"), f"{P}.dying")
    g.edge(g.textf("dyingT", key="UI_V2_DEATH_THROE", n=g.k(M.DYING_DMG)), f"{P}.dying_text")
    # the choice
    g.edge(g.b("canDisB", g.x("canDis", "ocN > 0")), f"{P}.can_dismantle")
    g.edge("guardOk_t", f"{P}.guard_ok")
    g.x("guardArmed", "d_armed && modeN == 0")
    g.edge("guardArmed_t", f"{P}.guard_armed")
    g.x("guardLeft", "modeN == 0 && !L_GuardUsed")
    g.edge("guardLeft_t", f"{P}.guard_left")
    g.edge("canLock_t", f"{P}.can_lock")
    g.text("selClaimT", g.sel("selClaimK", "needClaim_t", "scLabel", g.k("")))
    g.edge("selClaimT.text", f"{P}.sel_claim_text")
    g.text("selTgtT", g.sel("selTgtK", T("selTgtOn", "act == 3 || act == 7"), "tgtLabel", g.k("")))
    g.edge("selTgtT.text", f"{P}.sel_target_text")
    g.x("needTgtOut", "act == 3 && !hasTgtN")
    g.edge("needTgtOut_t", f"{P}.need_target")
    g.x("pickOn", "needClaim && d_ph == 1")
    g.edge("pickOn_t", f"{P}.picker_on")
    # the outcome
    g.text("gradeT", g.sel("gradeSel", T("gradeOn", "L_Grade > 0"), g.fmt("gradeK", "UI_V2_GRADE_{a}", "L_Grade"), g.k("")))
    g.edge("gradeT.text", f"{P}.grade_text")
    g.edge(g.textf("roundsT", key="UI_V2_RESULT_ROUNDS", n=g.x("roundsN", "L_Round - 1")), f"{P}.rounds_text")
    g.edge(g.cmp("outWin", "L_Outcome", g.k("win")), f"{P}.outcome_win")
    # back to the title (main switches the screen)
    bP = g.when("backG", f"{P}.back_title", T("backOk", "d_ph == 3"))
    setn(bP, "ph", g.k(0))
    g.edge(bP, "world.d1Back")
    return g
