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
from sherefox_ref.v2 import lines as LN  # noqa: E402
from sherefox_ref.v2 import model as M  # noqa: E402
from sherefox_ref.v2.data import load_chapter  # noqa: E402
from sherefox_ref.v2.routes import ROUTES  # noqa: E402

CH = load_chapter()
UI = "d1debate"
P = f"ui#{UI}"
# The dev shortcut's loadout (ref routes.py route A, ch §12.1); warm-up result pass_clean (M2 brief). The chapter's own
# run uses the loadout the carry step wrote and world.d1Warmup as the chapter left it (tools/gen_inv_v2.py).
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
KITCHEN = ("E07", ("06B", "04C"))   # ch §12.0 BEAT_D01_REFUTED_1/2: 06B / 04C refuted with the handkerchief
SH, CE, AR = "SPK_SHEREFOX", "SPK_D01_CEDRIC", "SPK_ARTHUR"
MRS, BRI, MAR, IRE, INS = "SPK_MRS_HYDE", "SPK_BRIGGS", "SPK_MARTHA", "SPK_IRENE", "SPK_INSPECTOR_BASKERVILLE"
# Arthur's hint (ref lines.hint, v2 demo E5), by index: 1-4 the action hints (tell code + 1), then the situations; 5
# and 9 every time, the others once per debate (u1 h<index>)
HINTS = ["", "TELL_D01_HINT_ASSERT", "TELL_D01_HINT_PUSH", "TELL_D01_HINT_REBUT", "TELL_D01_HINT_STALL",
         "TELL_D01_HINT_SLIP", "TELL_D01_HINT_KEY", "TELL_D01_HINT_FACT", "TELL_D01_HINT_NOCUT", "TELL_D01_HINT_LAST"]
TELL_WORDS = ["ASSERT", "PUSH", "REBUT", "STALL"]      # his tell lines TELL_D01_<word>_<n> by tell code 0-3
# the tail steps after a round's last record (ref lines.round_steps), in order: 破竹 held, the first psych card, a
# private matter said, cover set and not triggered
TAILS = ["SYS_D01_HACHIKU_KEEP", "SYS_D01_PSYCH_NOTE", "SYS_D01_PRIVATE", "SYS_D01_COVER_WASTED"]
# The playback's extra steps around a record (ref lines.round_steps): (name, before / after the record's main step,
# condition, speaker key or None for a system line, line key). Conditions read only what stays put while the record
# plays (its fields, the lock's claim, the latched round, debate flags changed between records).
EXTRAS = [
    ("xRc", "pre", "k_round && d_crk", AR, "BEAT_D01_REDCRACK_1"),
    ("x09", "pre", "k_round && isC09A", AR, "BEAT_D01_09A_1"),
    ("xL11", "pre", "k_round && modeN == 1 && !L_Dying", None, "SCR_D01_S07_L011"),
    ("xIre", "pre", "k_pAttach && isF09A", IRE, "REACT_D01_09A_3"),
    ("xCl1", "pre", "clashRec && !d_clsh", CE, "BEAT_D01_CLASH_1"),
    ("xCl2", "pre", "clashRec && !d_clsh", SH, "BEAT_D01_CLASH_2"),
    ("xLcS", "pre", "lcRec", CE, "@lcStateK"),
    # E7 (ch §7): her claim contradicts her record (red crack): his catch and her hard sell, before SYS_D01_REDCRACK
    ("xExC", "pre", "k_pDmg && c_contradiction && exHas", CE, "@exCatchK"),
    ("xExS", "pre", "k_pDmg && c_contradiction && exHas", SH, "@exSellK"),
    # E7: the Break by chain length and issues (not a keystone Break), the Reverse Break: the conditions first
    ("xCRd", "pre", "k_ronpa && viaChain", None, "SYS_D01_CHAIN_READY"),
    ("xRRd", "pre", "k_reverseRonpa", None, "SYS_D01_REV_READY"),
    ("xLc4", "pre", "lcRec && lcP05 && L_Cracks >= 1", CE, "BEAT_D01_LASTCARD_4"),
    ("xLc2", "pre", "lcRec && lcP05 && L_Cracks >= 1", INS, "BEAT_D01_LASTCARD_2"),
    ("xLc3", "pre", "lcRec && lcP05 && L_Cracks == 0", INS, "BEAT_D01_LASTCARD_3"),
    ("xL7", "pre", "k_over && rsSurr", None, "SCR_D01_S07_L007"),
    ("xL8", "pre", "k_over && rsSurr", CE, "SCR_D01_S07_L008"),
    ("x6B", "post", "k_round && isC06B && carE07", AR, "BEAT_D01_SOPH_06B_1"),
    ("x6C", "post", "k_round && isC06C", AR, "BEAT_D01_SOPH_06C_1"),
    ("x3C", "post", "k_round && apSoph && !(isC06B && carE07) && !isC06C", AR, "BEAT_D01_SOPH_03C_1"),
    ("xP1", "post", "k_round && d_p1f", "", "BEAT_D01_P1A_1"),
    ("xMrs", "post", "k_pAttach && isF09A", MRS, "REACT_D01_09A_2"),
    ("xP1b", "post", "k_pAttach && d_p1f", AR, "BEAT_D01_P1A_2"),
    ("x2C", "post", "k_pAttach && isF02C", MRS, "BEAT_D01_02C_1"),
    ("x7a", "post", "(k_pAttach && isF07A) || (k_oDmg && c_intercept && isC07A)", MAR, "BEAT_D01_07A_1"),
    ("x7b", "post", "(k_pAttach && isF07A) || (k_oDmg && c_intercept && isC07A)", BRI, "BEAT_D01_07A_2"),
    # E5: a sophistry link landed (not a psych card: no crack), after the link's other lines
    ("xCrk", "post", "k_pAttach && myClaimSoph && !scPsych", None, "SYS_D01_CRACK"),
    # E7 (design 4ac5faf): her chain long enough for a Break but he is not in 破防 at the round's end (once per debate)
    ("xNb", "post", "k_pAttach && nbNow && !d_nb", None, "SYS_D01_CHAIN_NOBREAK"),
    # E5: the first time 破竹 goes up in the debate (after SHF_HACHIKU_n); he enters 困獸
    ("xHkA", "post", "k_hachiku && n2 > n1 && !d_hkA", AR, "STATE_D01_ART_HACHIKU"),
    ("xCor", "post", "k_crossed && xP", AR, "STATE_D01_ART_CORNERED"),
    ("xRf1", "post", "k_refuted && rfKit", BRI, "BEAT_D01_REFUTED_1"),
    ("xRf2", "post", "k_refuted && rfKit", MAR, "BEAT_D01_REFUTED_2"),
    ("xRf3", "post", "k_refuted && rfHas", SH, "BEAT_D01_REFUTED_3"),
    ("xRf4", "post", "k_refuted && rfHas", AR, "BEAT_D01_REFUTED_4"),
    ("xBr1", "post", "k_shisshu && n1 == 1", SH, "STATE_D01_SHF_BREACHED"),
    ("xBr2", "post", "k_shisshu && n1 == 1", AR, "STATE_D01_ART_BREACHED"),
    ("xLc5", "post", "lcEnd", SH, "BEAT_D01_LASTCARD_5"),
    ("xLc6", "post", "lcEnd && !outOver", AR, "BEAT_D01_LASTCARD_6"),
    ("xL9", "post", "k_endgame && dyNow && !outOver", None, "SCR_D01_S07_L009"),
    ("xL16", "post", "k_over && rsLimit && !ovWin", None, "SCR_D01_S07_L016"),
]


# ---------------------------------------------------------------------------------------------- tables


def R2(expr: str) -> str:
    """An expression rounded to two decimals (the chapter's §12 tables: 103.49, 82.8, 43.31)."""
    return f"round(({expr}) * 100) / 100"

def ev_key(e: str) -> str:
    return f"C_D01_{e}_NAME" if CH.evidence[e].psych_card else f"E_D01_{e[1:]}_NAME"


def person(cid: str) -> str:
    """The speaker key of the person whose regard a private-matter claim costs (SYS_D01_PRIVATE {person}), "" for none."""
    c = CH.claims[cid]
    if not c.private:
        return ""
    if cid not in CH.private_favour:
        raise SystemExit(f"claim {cid} is a private matter with no person (d01_extra.json private_favour)")
    return f"SPK_{CH.private_favour[cid][0].upper()}"


def tables() -> dict[str, list[dict]]:
    claims = []
    for cid, c in CH.claims.items():
        # appr: the appraisal the claim contradicts (BEAT_D01_SOPH_03C_1, ref lines), "" for none
        appr = next((k for k in c.conflicts if k in CH.appraisals), "")
        claims.append({"id": cid, "evidence": c.evidence, "label": f"CLM_D01_{cid}", "line": f"CLM_D01_{cid}_LINE",
                       "short": f"CLM_D01_{cid}_SHORT",
                       "appr": appr,
                       "issue": f"ISSUE_D01_{ISSUE[c.issue]}_SHORT", "issueName": f"ISSUE_D01_{ISSUE[c.issue]}",
                       "catch": 0, "psych": int(c.psych_card), "private": int(c.private),
                       "person": person(cid), "react": f"REACT_D01_ISSUE_{ISSUE[c.issue]}"})
    for cid, cd in CH.cards.items():
        if cd.kind == "unfav":
            claims.append({"id": f"{M.CATCH}:{cid}", "evidence": M.CATCH, "label": "UI_V2_SEIZE", "appr": "",
                           # E7 (design ruling): chains and the public record show the caught U card's short label;
                           # UI_V2_SEIZE stays the row's name in the claim picker
                           "short": f"CARD_D01_{cid}_SHORT",
                           "line": f"CARD_D01_{cid}_CATCH", "issue": f"ISSUE_D01_{ISSUE[cd.issue]}_SHORT",
                           "issueName": f"ISSUE_D01_{ISSUE[cd.issue]}", "catch": 1, "psych": 0, "private": 0,
                           "person": "",
                           "react": f"REACT_D01_ISSUE_{ISSUE[cd.issue]}"})
    keys = F.string_keys()

    def have(k: str, alt: str) -> str:
        return k if k in keys else alt
    cards = []
    for cid, cd in CH.cards.items():
        # a line the package does not have falls back: 強辯 / 改口 -> 立論; knocked down -> his generic reaction to a
        # fact / a lie knocked down (facts have no _DOWN: only sophistry knocks them down)
        state = f"CARD_D01_{cid}_STATE"
        down = have(f"CARD_D01_{cid}_DOWN", "REACT_D01_FACT_SOPH_1" if cd.is_fact else "REACT_D01_LIE_SOPH")
        # lie / fav (E5 hints): a lie (NOCUT), a favourable fact (FACT; a slip's unfavourable fact is not one)
        cards.append({"id": cid, "kind": cd.kind, "fact": int(cd.is_fact), "key": int(cd.keystone),
                      "lie": int(cd.is_lie), "fav": int(cd.is_fact and cd.kind != "unfav"),
                      "label": f"CARD_D01_{cid}", "short": f"CARD_D01_{cid}_SHORT",
                      "issue": f"ISSUE_D01_{ISSUE[cd.issue]}_SHORT" if cd.issue else "",
                      "issueName": f"ISSUE_D01_{ISSUE[cd.issue]}" if cd.issue else "",
                      "state": state, "push": have(f"CARD_D01_{cid}_PUSH", state),
                      "retract": have(f"CARD_D01_{cid}_RETRACT", state), "down": down,
                      "tell": f"CARD_D01_{cid}_TELL" if cd.kind == "unfav" else ""})
    ev = [{"id": e, "name": ev_key(e)} for e in CH.evidence] + [{"id": M.CATCH, "name": "UI_V2_SEIZE"}]
    # spoken lines that replace the default one: CUT_D01_<claim>_<card> (his reaction to that cut, replaces _DOWN),
    # LINK_D01_<a>_<b> (承接, replaces the claim line) and REACT_D01_<claim>[_1] (his own reaction to that claim
    # landing, replaces the reaction by issue); only keys the string tables have
    lines = []
    for k in sorted(keys):
        parts = k.split("_")
        if k.startswith("CUT_D01_") and len(parts) == 4:
            lines.append({"id": f"CUT:{parts[2]}:{parts[3]}", "key": k})
        elif k.startswith("LINK_D01_") and len(parts) == 4:
            lines.append({"id": f"LINK:{parts[2]}:{parts[3]}", "key": k})
            # E7: a pair ch §8 marks ↔ has one line for both orders (ref lines.link_key)
            a, b = parts[2], parts[3]
            if (b, a) in CH.continuations and (a, b) in CH.continuations and f"LINK_D01_{b}_{a}" not in keys:
                lines.append({"id": f"LINK:{b}:{a}", "key": k})
        elif k.startswith("REACT_D01_") and parts[2] in CH.claims and (len(parts) == 3 or parts[3] == "1"):
            lines.append({"id": f"REACT:{parts[2]}", "key": k})
    # v2 demo 4.3 (ref sherefox_ref.v2.lines): the claims that break a card (`<card>:<claim>`, Arthur's NOCUT hint)
    # and the refute lines with a picked-up evidence item (BEAT_D01_REFUTED_*: its name, the hotspot where it lies,
    # the handkerchief's beat for 06B / 04C)
    brk = [{"id": f"{card}:{cl}"} for card in CH.cards for cl in sorted(CH.breakers.get(card, ()))]
    spots = json.loads((ROOT / "data" / "d01" / "d1Hotspot.json").read_text(encoding="utf-8"))
    refute = []
    for cid, c in CH.claims.items():
        for via, line in c.opp_refute:
            if via not in CH.evidence:
                continue
            hs = next(x["id"] for x in spots if via in x["ev"].split(","))
            refute.append({"id": line, "item": ev_key(via), "place": f"HS_D01_{hs[2:]}_NAME",
                           "kitchen": int(via == KITCHEN[0] and cid in KITCHEN[1])})
    # E7 (ch §7 互斥表): per claim, the claims of her record it contradicts and his catch / her hard sell for each
    # (ref lines.excl_keys); the playback takes the earliest record entry (u1Used)
    excl = []
    for cid, c in CH.claims.items():
        if not c.exclusive:
            continue
        if len(c.exclusive) > 2:
            raise SystemExit(f"claim {cid}: more than two exclusive claims (d1uiExcl has two columns)")
        row = {"id": cid}
        for i in (1, 2):
            o = c.exclusive[i - 1] if i <= len(c.exclusive) else ""
            ck, sk = LN.excl_keys(cid, o) if o else ("", "")
            if o and not {ck, sk} <= keys:
                raise SystemExit(f"claims {cid} / {o}: no {ck} / {sk} in the strings (ch §7)")
            row.update({f"x{i}": o, f"catch{i}": ck, f"sell{i}": sk})
        excl.append(row)
    return {"d1uiClaim": claims, "d1uiCard": cards, "d1uiEv": ev, "d1uiLine": lines, "d1uiBreak": brk,
            "d1uiRefute": refute, "d1uiExcl": excl}


SIGNALS = {
    "bgmD1": {"type": "string", "initial": ""},    # d01_debate_ui -> music: the debate's music moment (4.3)
    "d1Cue": {"type": "string", "initial": ""},    # d01_debate_ui -> dialogue: S07's lines after it (postWin / postLose)
}
COLLECTIONS = {
    "u1": {"kind": "map", "type": "number", "capacity": 96},
    "u1S": {"kind": "map", "type": "string", "capacity": 24},
    "u1F": {"kind": "list", "type": "string", "capacity": 16},          # the record being played, split at |
    "u1N": {"kind": "list", "type": "number", "capacity": 16},
    "u1G": {"kind": "list", "type": "string", "capacity": 16},          # the next record (lookahead), split at |
    "u1GN": {"kind": "list", "type": "number", "capacity": 16},
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
    "u1LkIss": {"kind": "map", "type": "number", "capacity": 4},     # issues of the claims that can still be linked
    "u1Rec": {"kind": "list", "type": "string", "capacity": 32},
    "u1RecId": {"kind": "map", "type": "string", "capacity": 32},
    "u1RecN": {"kind": "map", "type": "number", "capacity": 32},
    "u1RecNT": {"kind": "map", "type": "string", "capacity": 32},     # the round of a record row, as text
    "u1RecL": {"kind": "map", "type": "string", "capacity": 32},
    "u1RecU": {"kind": "map", "type": "string", "capacity": 32},
    "u1RecS": {"kind": "map", "type": "string", "capacity": 32},
    "u1RecC": {"kind": "map", "type": "string", "capacity": 32},
    "u1RecSt": {"kind": "map", "type": "string", "capacity": 32},
    "u1Used": {"kind": "map", "type": "number", "capacity": 40},       # E7: claim -> its first public record row
    "u1Pv": {"kind": "map", "type": "bool", "capacity": 8},          # E5: private-matter claims announced
    "u1None": {"kind": "list", "type": "string", "capacity": 1},     # E6: never filled (the lists before round 1)
}


# ---------------------------------------------------------------------------------------------- the flow

def issues_text(g: Graph, T, pfx: str, coll: str, table: str, kmax: int = 12) -> str:
    """E7: {issues} of SYS_D01_CHAIN_READY / REV_READY: the issue names a chain (list `coll`, ids of `table`) covers,
    in the order the chain first reaches them, joined by UI_TAG_SEP (ref lines.chain_issues)."""
    xs = list(ISSUE.values())
    for k in range(kmax):
        item = g.cget(f"{pfx}i{k}", coll, g.k(k))
        g.tget(f"{pfx}n{k}", table, "issueName", g.tfind(f"{pfx}r{k}", table, "id", item))
        for x in xs:
            g.n(f"{pfx}h{k}{x}", g.cmp(f"{pfx}c{k}{x}", f"{pfx}n{k}", g.k(f"ISSUE_D01_{x}")))
    for x in xs:
        expr = "99"
        for k in range(kmax - 1, -1, -1):
            expr = f"{pfx}h{k}{x} ? {k} : ({expr})"
        g.x(f"{pfx}f{x}", expr)          # the first chain position with issue x (99: none)
    for x in xs:
        g.x(f"{pfx}k{x}", " + ".join(f"({pfx}f{y} < {pfx}f{x} ? 1 : 0)" for y in xs if y != x))
    g.x(f"{pfx}cnt", " + ".join(f"({pfx}f{x} < 99 ? 1 : 0)" for x in xs))
    names = []
    for pos in range(3):
        key = ssel(g, f"{pfx}p{pos}", [(T(f"{pfx}p{pos}{x}", f"{pfx}f{x} < 99 && {pfx}k{x} == {pos}"),
                                        g.k(f"ISSUE_D01_{x}")) for x in xs], g.k(""))
        names.append(g.text(f"{pfx}t{pos}", key))
    sep = g.text(f"{pfx}sep", g.k("UI_TAG_SEP"))
    s1 = g.sel(f"{pfx}s1", T(f"{pfx}s1c", f"{pfx}cnt >= 2"), sep, g.k(""))
    s2 = g.sel(f"{pfx}s2", T(f"{pfx}s2c", f"{pfx}cnt >= 3"), sep, g.k(""))
    return g.fmt(f"{pfx}j2", "{a}{b}", g.fmt(f"{pfx}j1", "{a}{b}{c}{d}", names[0], s1, names[1], s2), names[2])


def gen_d01ui() -> Graph:
    g = Graph()
    T = truth(g)
    langEn = g.put("langEn", g.cmp("langEnC", "world.language", g.k("en")))
    setn, sets = setter(g, "u1"), setter(g, "u1S")
    g.text("oppName", g.k("SPK_D01_CEDRIC"))

    # ---- UI state
    for k in ("ph", "act", "armed", "stAt", "rsAt", "lockAt", "r2", "ref", "pb", "pbAt", "ev", "hpM", "hpO", "pat",
              "endAt", "soph", "intBlk", "rmN", "patD", "tail", "sub", "intro", "crk", "p1f", "p1u", "clsh", "clsP",
              "cutOk", "m8", "m9", "m10", "hush", "hkA", "hkP", "shk", "shkP", "psn", "gsv", "nb", "nbP"):
        g.mget("d_" + k, "u1", g.k(k))
    for k in ("ev", "claim", "target", "hintK", "hintW", "hint2K", "hint2W"):
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

    # ---- start: the d1debate step begins; the carry step wrote the loadout, or (the title's dev shortcut, world.d1Dev)
    # route A's fixed set is written now. S07 L001-L003 play on the vn (dialogue, `pre`); the debate itself starts with
    # world.debGo (v2 demo 4.3): reset, then d1Start a few ticks later (it reads the loadout)
    g.cmp("isDebK", "world.stepKind", g.k("d1debate"))
    g.n("isDebKN", "isDebK")
    begin = g.when("begin", "world.stepBegin", "isDebK")
    dev = g.when("devM", begin, "world.d1Dev")
    start = g.when("start", "world.debGo", "isDebK")
    # v2 demo E6 (V2): the UI state is cleared when the step begins too (the music moment of the debate before, u1
    # m8 / m9 / m10 / hush, must not reach this step's first ticks), and again on world.debGo
    for sfx, pulse in (("", start), ("B", begin)):
        for coll in ("u1", "u1S", "u1RecId", "u1RecN", "u1RecNT", "u1RecL", "u1RecU", "u1RecS", "u1RecC", "u1RecSt",
                     "u1Pv", "u1Used"):
            g.edge(pulse, g.eff(f"clr{sfx}_{coll}", "atrium.map.clear", coll))
        for coll in ("u1F", "u1N", "u1G", "u1GN", "u1Rec"):
            g.edge(pulse, g.eff(f"sClr{sfx}_{coll}", "atrium.coll.clear", coll))
    # v2 demo E6 (V1): the screen is shown on world.debGo, but the engine's round 1 is latched only after the opening
    # step (S07 L004). Until then every port shows the new debate's initial state: `fresh` states, on when the step
    # begins and on debGo, off on the pulse that writes the real value (the round shown, a playback step, a float)
    g.merge("frOnP", begin, start)

    def fresh(name: str, off: str) -> str:
        g.node(name, "state", initial="s1", states=["s0", "s1"],
               transitions=[{"from": "*", "on": "on", "to": "s1"}, {"from": "*", "on": "off", "to": "s0"}])
        g.edge("frOnP.out", f"{name}.on")
        g.edge(off, f"{name}.off")
        return g.cmp(name + "C", f"{name}.index", g.k(1))
    for coll, items in (("d1Carry", DEV.carried), ("d1Appraised", DEV.appraisals), ("d1Notes", DEV.notes)):
        g.edge(dev, g.eff(f"clr_{coll}", "atrium.coll.clear", coll))
        g.edge(dev, add_all(g, f"add_{coll}", coll, g.k(",".join(items))))
    g.edge(dev, g.eff("clr_d1PrivNote", "atrium.map.clear", "d1PrivNote"))
    g.x("stSoon", "now + 0.1")
    setn(start, "stAt", "stSoon")
    # E6 (V1): from debGo on the screen is busy (the opening plays next), at full credibility on both sides
    setn(start, "ph", g.k(2))
    for pulse in (begin, start):
        setn(pulse, "hpM", g.k(CH.player_max_hp))
        setn(pulse, "hpO", g.k(CH.opp_max_hp))
    g.edge(g.latch("wuDev", g.k(DEV_WARMUP), dev), "world.d1Warmup")
    # the debate's seed (debate-engine-v2 §3.4): the next value of the simulation's rng when the step begins, so a
    # replay draws the same seed and two debates in one run differ; the engine reads it at d1Start
    g.node("seedRng", "atrium.rng")
    g.edge(start, "seedRng.trigger")
    g.put("seedU", "seedRng.value")
    g.edge(g.x("seedV", "floor(seedU * 16777216)"), "world.d1Seed")
    g.edge(stT, "world.d1Start")
    # the opening (S07 L004) plays as one playback step before round 1 is shown (the record lists are empty; ev past
    # the end, so the playback ends after it and shows the round)
    for k, v in (("intro", 1), ("ph", 2), ("pb", 2), ("sub", 0), ("ev", 999)):
        setn(stT, k, g.k(v))

    # ---- a round is shown: latch the engine, reset the choice, rebuild the lists on the next beat
    rs = g.merge("rs", rsT)
    num = ["d1Round", "d1RoundLimit", "d1PlayerHp", "d1PlayerMax", "d1OppHp", "d1OppMax", "d1PCombo", "d1Hachiku",
           "d1Broken", "d1Shisshu", "d1PsychP", "d1PsychG", "d1PsychA", "d1ThreshP", "d1ThreshG", "d1ThreshA",
           "d1OverP", "d1OverG", "d1OverA", "d1Cracks", "d1GuardUsed", "d1Dying", "d1TellPartial", "d1Grade"]
    txt = ["d1Phase", "d1TellClarity", "d1TellShown1", "d1TellShown2", "d1TellStar", "d1TellCard", "d1TellAction",
           "d1LastCard", "d1Outcome", "d1CatchCard"]
    # E6 (V1): L_<x> is the latched engine value once a round is shown (Lr_<x>), the debate's initial state before
    # (the chapter's constants: ref model.initial_state); the latch and `fresh` change on the same pulse, so what runs
    # on that pulse itself reads Lr_<x>
    init = {"d1Round": 1, "d1RoundLimit": CH.max_rounds, "d1PlayerHp": CH.player_max_hp,
            "d1PlayerMax": CH.player_max_hp, "d1OppHp": CH.opp_max_hp, "d1OppMax": CH.opp_max_hp,
            "d1PsychP": CH.psych_start[0], "d1PsychG": CH.psych_start[1], "d1PsychA": CH.psych_start[2],
            "d1ThreshP": CH.psych_threshold[0], "d1ThreshG": CH.psych_threshold[1],
            "d1ThreshA": CH.psych_threshold[2], "d1Phase": "choose"}
    frR = fresh("frR", rs)
    for sig in num + txt + ["d1OppAct"]:
        g.latch("Lr_" + sig[2:], f"world.{sig}", rs)
        g.sel("L_" + sig[2:], frR, g.k(init.get(sig, "" if sig in txt or sig == "d1OppAct" else 0)), "Lr_" + sig[2:])
    g.n("frRN", frR)
    # his move this round: the test hook's when it pins one (d1OppAct), else the AI's decision (debate-engine-v2 §2.1)
    g.n("oppPinN", g.cmp("oppPinC", "L_OppAct", g.k(""), "ne"))
    g.sel("effAct", "oppPinC", "L_OppAct", "L_TellAction")
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
    for k in ("ev", "claim", "target"):
        sets(rs, k, g.k(""))
    setn(rs, "r2", g.k(1))
    setn(rs, "intro", g.k(0))
    # the tell's lines (ref lines.tell_lines) are chosen on the next beat; NOCUT needs to know whether a
    # claim of this round's picker that shows as sound breaks the tell's card (d1uiBreak)
    setn(rs, "cutOk", g.k(0))
    for k in ("hintK", "hintW", "hint2K", "hint2W"):
        sets(rs, k, g.k(""))
    g.node("cutEach", "atrium.coll.forEach", name="d1ClaimList")
    g.edge(rs, "cutEach.trigger")
    cuI = g.put("cuI", "cutEach.item")
    g.tfind("cuBrk", "d1uiBreak", "id", g.fmt("cuBrkId", "{a}:{b}", "Lr_TellCard", cuI))
    g.mget("cuSoph", "d1ClaimSoph", cuI)
    g.edge(g.when("cuBrkG", "cutEach.each", T("cuBrkOk", "cuBrk >= 0 && !cuSoph")),
           g.eff("cuSet", "atrium.map.set", "u1", key=g.k("cutOk"), value=g.k(1)))

    # ---- the lists (rebuilt on the next beat after a round is shown, after a choice, on a language change)
    # E6 (V1): before round 1 is shown (fresh) the lists are written empty instead (from u1None, never filled): his
    # chain and ours, the record, the picker (hidden then)
    refAny = g.merge("refAny", r2T, refT, "langEnC.true", "langEnC.false")
    refresh = g.when("refresh", refAny, T("refOk", "!frRN"))
    emptyP = g.merge("emptyP", "frOnP.out", g.when("refEmp", refAny, T("refEmpOk", "frRN")))

    def lst(name: str, port: str, source: str, fields: dict, localize: list) -> str:
        g.edge(emptyP, g.ui_list(name + "0", port, "u1None", fields, localize=localize))
        return g.ui_list(name, port, source, fields, localize=localize)
    g.put("act", g.p("d_act"))
    # evidence chips: the evidence of the claim picker's claims, in its order (抓住他的話 first)
    for coll in ("u1Ev",):
        g.edge(refresh, g.eff("clr_" + coll, "atrium.coll.clear", coll))
    for coll in ("u1EvSel", "u1Cl"):
        typ = "atrium.coll.clear" if coll == "u1Cl" else "atrium.map.clear"
        g.edge(refresh, g.eff("clr_" + coll, typ, coll))
    for coll in ("u1ClOk", "u1ClSel", "u1ClKind", "u1ClCrk", "u1ClStd", "u1ClXtr", "u1OSel", "u1PCr", "u1Iss",
                 "u1LkIss"):
        g.edge(refresh, g.eff("clr_" + coll, "atrium.map.clear", coll))
    g.node("evEach", "atrium.coll.forEach", name="d1ClaimList")
    g.edge(refresh, "evEach.trigger")
    ei = g.put("ei", "evEach.item")
    g.tget("eiEv", "d1uiClaim", "evidence", g.tfind("eiRow", "d1uiClaim", "id", ei))
    g.edge("evEach.each", g.eff("evAdd", "atrium.coll.add", "u1Ev", value="eiEv"))
    g.edge("evEach.each", g.eff("evSelSet", "atrium.map.set", "u1EvSel", key="eiEv",
                                  value=g.cmp("eiSel", "eiEv", "s_ev")))
    g.edge("evEach.done", lst("evList", f"ui.{UI}.ev_list", "u1Ev",
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
    # the issues of the claims that can still be linked this round (the Break-ready hint, ruling d)
    g.tget("ciIss", "d1uiClaim", "issue", crow)
    g.edge(g.when("ciLkG", "clEach.each", T("ciLk", "!ciStand")),
           g.eff("clLk", "atrium.map.set", "u1LkIss", key="ciIss", value=g.k(1)))
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
    g.edge("clEach.done", lst("clList", f"ui.{UI}.claims", "u1Cl",
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
    g.edge("ocEach.done", lst("ocList", f"ui.{UI}.ochain", "d1OChain",
                                    {"id": "item", "label": tref("d1uiCard", "id", "short"),
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
    g.edge("pcEach.done", lst("pcList", f"ui.{UI}.pchain", "d1PChain",
                                    {"id": "item", "label": tref("d1uiClaim", "id", "short"),
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
    # the round as text (UI_DEB_ROUND), in the language of the moment: the list is rebuilt on a language change
    g.mget("rkN", "u1RecN", rk)
    g.edge("rcEach.each", g.eff("rcNT", "atrium.map.set", "u1RecNT", key=rk,
                                  value=g.textf("rkNT", key="UI_DEB_ROUND", n="rkN")))
    g.edge("rcEach.done", lst("rcList", f"ui.{UI}.record", "u1Rec",
                                    {"n": "map:u1RecNT", "label": "map:u1RecL", "use": "map:u1RecU",
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
    # the private view (d1PrivNote, set on the evidence list, ch §13): the claim picker starts on that claim when the
    # evidence is chosen and the action may use it (in the list, not standing for argue)
    evNow = g.sel("evNow", "hasEvC.out", g.fmt("evNowA", "{a}", "s_ev"), g.fmt("evNowB", "{a}", "ev0"))
    for nm, evk, actv in (("pnA", evNow, "aV"), ("pnE", f"{P}.pick_ev", "act")):
        g.mget(nm, "d1PrivNote", evk)
        g.n(nm + "Has", g.cmp(nm + "HasC", nm, g.k(""), "ne"))
        g.n(nm + "In", g.contains(nm + "InC", "d1ClaimList", nm))
        g.mget(nm + "Std", "d1ClaimStand", nm)
        g.x(nm + "Ok", f"{nm}Has && {nm}In && (" + " || ".join(f"{actv} == {a}" for a in CLAIM_ACTS)
            + f") && ({actv} != 1 || !{nm}Std)")
    sets(g.when("aPnG", aP, "pnAOk_t"), "claim", "pnA")
    setn(aP, "ref", g.k(1))
    # pick_ev
    evP = g.when("evG", f"{P}.pick_ev.emitted", "inOk_t")
    sets(evP, "ev", f"{P}.pick_ev")
    sets(evP, "claim", g.k(""))      # a claim of the evidence chosen before does not stay chosen (its private view may)
    sets(g.when("ePnG", evP, "pnEOk_t"), "claim", "pnE")
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
    # the claim's sophistry as it was when chosen (d1ClaimSoph already holds the next round's during playback)
    g.mget("lkSoph", "d1ClaimSoph", "s_claim")
    setn(lP, "soph", g.x("lkSophN", "needClaim && lkSoph"))
    g.mget("lkCrk", "d1ClaimCrack", "s_claim")
    setn(lP, "crk", g.x("lkCrkN", "needClaim && lkCrk"))
    g.n("isP1aN", g.cmp("isP1aC", "s_claim", g.k("P1A")))
    g.n("isP1bN", g.cmp("isP1bC", "s_claim", g.k("P1B")))
    g.x("isP1", "isP1aN || isP1bN")
    setn(lP, "p1f", g.x("p1fN", "needClaim && isP1 && !d_p1u"))
    setn(lP, "p1u", g.x("p1uN", "d_p1u || (needClaim && isP1)"))
    # the public record: one row per claim used (ref RecordEntry: soph / red crack as displayed when chosen)
    g.count("recN", "u1Rec")
    rkey = g.fmt("recKey", "r{a}", "recN")
    rP = g.when("recG", lP, "needClaim_t")
    g.edge(rP, g.eff("recAdd", "atrium.coll.add", "u1Rec", value=rkey))
    crow2 = g.tfind("scRow", "d1uiClaim", "id", "s_claim")
    g.tget("scLabel", "d1uiClaim", "label", crow2)
    g.tget("scShort", "d1uiClaim", "short", crow2)     # E6 V4: the public record and the chains use the short label
    g.tget("scLine", "d1uiClaim", "line", crow2)
    g.tget("scIssueName", "d1uiClaim", "issueName", crow2)
    g.mget("scSoph", "d1ClaimSoph", "s_claim")
    g.mget("scCrack", "d1ClaimCrack", "s_claim")
    use = g.lookup("recUse", ["", "", "UI_V2_RECORD_REBUT", "UI_V2_RECORD_REBUT", "", "UI_V2_RECORD_REBUT", "",
                              "UI_V2_RECORD_REBUT"], "act")
    for coll, val in (("u1RecId", "s_claim"), ("u1RecN", "L_Round"), ("u1RecL", "scShort"), ("u1RecU", use),
                      ("u1RecS", g.sel("recS", g.b("recSB", "scSoph"), g.k("UI_V2_CLAIM_SOPH"), g.k(""))),
                      ("u1RecC", g.sel("recC", g.b("recCB", "scCrack"), g.k("UI_V2_LINK_CRACKED"), g.k("")))):
        g.edge(rP, g.eff(f"rec_{coll}", "atrium.map.set", coll, key=rkey, value=val))
    # E7: the first record row of each claim (the earliest contradiction picks his catch line, ref lines.excl_other)
    g.n("usedHasN", g.mhas("usedHas", "u1Used", "s_claim"))
    g.edge(g.when("usedG", rP, T("usedNew", "!usedHasN")),
           g.eff("usedSet", "atrium.map.set", "u1Used", key="s_claim", value="recN"))

    # ---- playback of the round's records (d1Events, debate-engine-v2 §2.3): pb 1 fetch, 2 play, 3 wait
    setn(lockT, "ev", g.k(0))
    setn(lockT, "pb", g.k(1))
    for k in ("intBlk", "rmN", "patD", "tail", "sub", "intro", "gsv"):
        setn(lockT, k, g.k(0))
    stepP = stage("fetchG", "d_pb == 1")
    # the first clash's beat was played on the record before: from the next record on it is done
    clsF = g.when("clsFG", stepP, T("clsFOn", "d_clsP == 1"))
    setn(clsF, "clsh", g.k(1))
    setn(clsF, "clsP", g.k(0))
    # E5: the same for the once-per-debate state lines (ART_HACHIKU, SHF_SHAKEN), played on the record before
    for flag, pend in (("hkA", "hkP"), ("shk", "shkP"), ("nb", "nbP")):
        fp = g.when(f"{pend}FG", stepP, T(f"{pend}FOn", f"d_{pend} == 1"))
        setn(fp, flag, g.k(1))
        setn(fp, pend, g.k(0))
    g.count("evCnt", "d1Events")
    g.cget("evRec", "d1Events", "d_ev")
    more = g.when("moreG", stepP, T("more", "d_ev < evCnt"))
    g.edge(more, g.eff("fClr", "atrium.coll.clear", "u1F"))
    g.edge(more, g.eff("nClr", "atrium.coll.clear", "u1N"))
    g.edge(more, add_all(g, "fAdd", "u1F", "evRec", "|"))
    g.edge(more, add_all(g, "nAdd", "u1N", "evRec", "|"))
    # the record after it (one record of lookahead: what follows decides some lines, debate-engine-v2 §2.3 order)
    g.cget("evRecNx", "d1Events", g.x("evNxI", "d_ev + 1"))
    g.edge(more, g.eff("gClr", "atrium.coll.clear", "u1G"))
    g.edge(more, g.eff("gnClr", "atrium.coll.clear", "u1GN"))
    g.edge(more, add_all(g, "gAdd", "u1G", "evRecNx", "|"))
    g.edge(more, add_all(g, "gnAdd", "u1GN", "evRecNx", "|"))
    setn(more, "ev", g.x("evNext", "d_ev + 1"))
    setn(more, "pb", g.k(2))
    # After the last record, the tail steps (TAILS, ref lines.round_steps), each one when its condition holds: E4 破竹
    # held this round (≥ 1 layer, no layer added, not reset; a normal round that the debate goes on after); E5 the
    # debate's first psych card, a private matter said (once per claim), cover set and not triggered (a normal round
    # the debate goes on after). The record lists are emptied, so only the tail line matches; u1.tail = the tail step
    # shown (1-4), the next fetch looks for the next one after it.
    g.n("outOver", g.cmp("outOverC", "world.d1Outcome", g.k(""), "ne"))
    g.put("hkNowN", "world.d1Hachiku")
    g.tget("scPsych", "d1uiClaim", "psych", "scRow", "number")
    g.tget("scPriv", "d1uiClaim", "private", "scRow", "number")
    g.tget("scPerson", "d1uiClaim", "person", "scRow")
    g.n("pvDone", g.mhas("pvDoneH", "u1Pv", "s_claim"))
    g.x("usedClaim", "(" + " || ".join(f"act == {a}" for a in CLAIM_ACTS) + ") && hasClaimN")
    conds = ["modeN == 0 && !outOver && L_Hachiku >= 1 && hkNowN == L_Hachiku",
             "usedClaim && scPsych == 1 && !d_psn",
             "usedClaim && scPriv == 1 && !pvDone",
             "modeN == 0 && !outOver && d_armed && !d_gsv"]
    nxt = "0"
    for i in range(len(TAILS), 0, -1):
        nxt = f"(d_tail < {i} && ({conds[i - 1]})) ? {i} : {nxt}"
    g.x("tailNext", nxt)
    g.x("tailWant", "tailNext > 0")
    tailP = g.when("tailG", stepP, T("tailGo", "!more && tailWant"))
    for coll in ("u1F", "u1N", "u1G", "u1GN"):
        g.edge(tailP, g.eff(f"tClr_{coll}", "atrium.coll.clear", coll))
    setn(tailP, "tail", "tailNext")
    setn(tailP, "pb", g.k(2))
    endT = g.when("evDone", stepP, T("evOver", "!more && !tailWant"))
    setn(endT, "pb", g.k(0))
    setn(endT, "intro", g.k(0))
    g.x("endSoon", f"now + {HOLD}")
    setn(endT, "rsAt", "endSoon")
    # the debate is over and played out: S07's lines after it on the vn (dialogue: world.d1Cue); when they end the
    # step is done and the result step (S08, v2 demo 4.4) follows
    g.edge(g.when("endOutG", endT, T("endOut", "outOver")), "world.debEnd")
    g.edge(g.sel("d1CueV", g.cmp("d1CueWin", "world.d1Outcome", g.k("win")), g.k("postWin"), g.k("postLose")),
           "world.d1Cue")
    parse = stage("parseG", "d_pb == 2")
    setn(parse, "pb", g.k(3))
    waitP = stage("waitG", "d_pb == 3 && now >= d_pbAt")
    setn(g.when("skipG", f"{P}.skip", T("skipOn", "d_ph == 2 && d_pb == 3")), "pbAt", "now")
    for k in range(11):
        g.cget(f"f{k}", "u1F", g.k(k))
        g.cget(f"n{k}", "u1N", g.k(k))
    g.cget("g0", "u1G", g.k(0))
    g.cget("g2", "u1G", g.k(2))
    g.cget("gn5", "u1GN", g.k(5))
    kinds = ["round", "pAttach", "oAttach", "pDmg", "oDmg", "oHeal", "reraise", "refuted", "blocked", "intercept",
             "dismantle", "guardSaved", "broken", "hachiku", "shisshu", "crossed", "ronpa", "reverseRonpa",
             "endgame", "lastCard", "lastStand", "over", "stall", "healVoid", "lastCardRemoved", "exposed"]
    for kd in kinds:
        g.n("k_" + kd, g.cmp("kc_" + kd, "f0", g.k(kd)))

    def isS(name: str, port: str, val: str) -> str:
        g.n(name, g.cmp(name + "C", port, g.k(val)))
        return name
    for c in ("argument", "exposed", "refuted", "contradiction", "whiff", "fact_miss", "stalemate", "stall_repeat",
              "bad_cut", "dying", "last_card", "intercept", "dismantle"):
        isS("c_" + c, "f2", c)
    isS("hisForce", "effAct", "force")
    for kd in ("oDmg", "oAttach", "oHeal", "healVoid", "lastCard", "lastCardRemoved", "dismantle"):
        isS("nx_" + kd, "g0", kd)
    # the card of the next record (a failed 拆台: its dismantle record follows the damage)
    g.tget("nxFact", "d1uiCard", "fact", g.tfind("nxRow", "d1uiCard", "id", "g2"), "number")
    isS("stVsRebut", "f1", "rebut")
    isS("ovSecZero", "f3", "second_zero")
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
    g.tget("k_keyK", "d1uiCard", "key", krow, "number")
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
    # his reaction to a link landing: REACT_D01_<claim>, else the sophistry one, else the one of its issue
    reRow = g.tfind("reRow", "d1uiLine", "id", g.fmt("reId", "REACT:{a}", "f1"))
    g.tget("reKey", "d1uiLine", "key", reRow)
    g.tget("reIss", "d1uiClaim", "react", "f1Row")
    react = g.sel("reLine", T("reOwn", "reRow >= 0"), "reKey",
                  g.sel("reGen", g.b("f1SophB", g.p("d_soph")), g.k("REACT_D01_SOPH"), "reIss"))
    # a link of his knocked down: a fact (only sophistry does that) / a lie by sophistry / the claim's own cut line
    g.tget("k_factK", "d1uiCard", "fact", krow, "number")
    g.put("myClaimSoph", g.p("d_soph"))
    g.x("rcFactI", "L_Round - 2 * floor(L_Round / 2)")
    factLine = g.sel("factLine", T("factOdd", "rcFactI == 1"), g.k("REACT_D01_FACT_SOPH_1"),
                     g.k("REACT_D01_FACT_SOPH_2"))
    knocked = ssel(g, "knLine", [(T("knFact", "k_factK"), factLine),
                                 (T("knSoph", "myClaimSoph"), g.k("REACT_D01_LIE_SOPH")),
                                 (T("knCut", "cuOk && k_intercept"), "cuKey")], "k_downK")
    g.x("fogI", "(L_Round - 1) - 3 * floor((L_Round - 1) / 3)")
    fog = g.lookup("fogK", ["FOG_D01_1", "FOG_D01_2", "FOG_D01_3"], "fogI")
    hkLine = g.lookup("hkK", ["", "STATE_D01_SHF_HACHIKU_1", "STATE_D01_SHF_HACHIKU_2", "STATE_D01_SHF_HACHIKU_3"],
                      g.x("hkI", "clamp(n2, 0, 3)"))
    claim_act = " || ".join(f"act == {a}" for a in CLAIM_ACTS)

    # ---- the extra steps (v2 demo 4.3, EXTRAS; ref lines.round_steps)
    for cid in ("09A", "06B", "06C", "07A"):
        g.n(f"isC{cid}", g.cmp(f"isC{cid}C", "s_claim", g.k(cid)))
    for cid in ("09A", "02C", "07A"):
        g.n(f"isF{cid}", g.cmp(f"isF{cid}C", "f1", g.k(cid)))
    g.n("carE07", g.contains("carE07C", "d1Carry", g.k(KITCHEN[0])))
    g.tget("scAppr", "d1uiClaim", "appr", "scRow")
    g.n("apHas", g.cmp("apHasC", "scAppr", g.k(""), "ne"))
    g.n("apIn", g.contains("apInC", "d1Appraised", "scAppr"))
    g.x("apSoph", "myClaimSoph && apHas && apIn")
    g.x("clashRec", "k_pDmg && c_argument && d_pat")
    g.x("lcRec", "k_pDmg && c_last_card")
    g.n("lcP05", g.cmp("lcP05C", "L_LastCard", g.k("P05")))
    g.tget("lcStateK", "d1uiCard", "state", g.tfind("xLcRow", "d1uiCard", "id", "L_LastCard"))
    g.x("lcEnd", "(k_lastCard && n2 == 0 && n3 == 0 && !nx_lastCardRemoved) || (k_lastCardRemoved && !nx_lastCardRemoved)")
    rfRow = g.tfind("rfRow", "d1uiRefute", "id", "f2")
    g.tget("rfKitN", "d1uiRefute", "kitchen", rfRow, "number")
    g.tget("rfItemK", "d1uiRefute", "item", rfRow)
    g.tget("rfPlaceK", "d1uiRefute", "place", rfRow)
    g.x("rfHas", "rfRow >= 0")
    g.x("rfKit", "rfRow >= 0 && rfKitN == 1")
    g.put("dyNow", "world.d1Dying")
    # E7: the Break's way (ronpa|chain or ronpa|keystone); her chain long enough without 破防 at the round's end (the
    # engine's state after the round: 破防 lasts through round broken_until); his catch of a contradiction: the
    # earliest of her record's claims this one contradicts (d1uiExcl, u1Used = each claim's first record row)
    isS("viaChain", "f1", "chain")
    g.put("bkUntil", "world.d1BrokenUntil")
    g.x("nbNow", f"pcN >= {CH.ronpa_len} && bkUntil < L_Round")
    exRow = g.tfind("exRow", "d1uiExcl", "id", "s_claim")
    for i in (1, 2):
        g.tget(f"exX{i}", "d1uiExcl", f"x{i}", exRow)
        g.tget(f"exC{i}", "d1uiExcl", f"catch{i}", exRow)
        g.tget(f"exS{i}", "d1uiExcl", f"sell{i}", exRow)
        g.n(f"exH{i}", g.mhas(f"exHm{i}", "u1Used", f"exX{i}"))
        g.mget(f"exI{i}", "u1Used", f"exX{i}")
    g.x("exUse1", "exH1 && (!exH2 || exI1 < exI2)")
    g.x("exHas", "exRow >= 0 && (exH1 || exH2)")
    g.sel("exCatchK", g.b("exUse1B", "exUse1"), "exC1", "exC2")
    g.sel("exSellK", "exUse1B", "exS1", "exS2")
    pos = {"pre": [], "post": []}
    for nm, where, cond, _, _ in EXTRAS:
        g.x(nm + "C", f"({cond}) ? 1 : 0")
        g.x(nm + "P", " + ".join(pos[where]) or "0")
        pos[where].append(nm + "C")
    g.x("preN", " + ".join(pos["pre"]))
    g.x("postN", " + ".join(pos["post"]))
    g.x("subTotal", "preN + 1 + postN")
    g.x("isMain", "d_sub == preN")
    # the record's steps: its extra steps before the main one, the main one, its extra steps after (EXTRAS)
    subNx = g.when("subNxG", waitP, T("subMore", "d_sub + 1 < subTotal"))
    setn(subNx, "sub", g.x("subNext", "d_sub + 1"))
    setn(subNx, "pb", g.k(2))
    subEnd = g.when("subEndG", waitP, T("subDone", "d_sub + 1 >= subTotal"))
    setn(subEnd, "sub", g.k(0))
    setn(subEnd, "pb", g.k(1))
    ex_sp, ex_sy = [], []
    for nm, where, cond, who, key in EXTRAS:
        at = f"{nm}P" if where == "pre" else f"preN + 1 + {nm}P"
        c = T(nm + "S", f"{nm}C == 1 && d_sub == {at}")
        line_k = key[1:] if key.startswith("@") else g.k(key)
        if who is None:
            ex_sy.append((c, key))
        else:
            ex_sp.append((c, g.k(who), line_k))

    def MN(name: str, expr: str) -> str:
        """A condition of the record's main step."""
        return T(name, f"isMain && ({expr})")

    # spoken line: (condition, speaker key, line key)
    SH, CE, AR = g.k("SPK_SHEREFOX"), g.k("SPK_D01_CEDRIC"), g.k("SPK_ARTHUR")
    speech = ex_sp + [
        (MN("sp1", f"k_round && ({claim_act}) && hasClaimN"), SH, "scLine"),
        (MN("sp2", "k_round && act == 4"), SH, fog),
        (MN("sp3", "k_pAttach && lkOk"), SH, "lkKey"),
        (MN("sp3b", "k_pAttach && !lkOk"), CE, react),
        (MN("sp4", "k_oAttach"), CE, g.sel("oaLine", g.b("hisForceB", "hisForce"),
                                         "k_pushK", "k_stateK")),     # his move: pinned (test hook) or the AI's
        (MN("sp5", "k_reraise"), CE, "k_retractK"),
        (MN("sp6", "k_refuted"), CE, "f2"),
        (MN("sp7", "k_intercept && n3 == 1"), CE, knocked),
        (MN("sp8", "k_dismantle && n3 == 1"), CE, knocked),
        (MN("sp8b", "k_blocked"), CE, g.k("REACT_D01_BLOCK")),
        (MN("sp8c", "k_oDmg && c_whiff"), CE, g.k("REACT_D01_FOOLED")),
        (MN("sp9", "k_guardSaved"), AR, g.k("STATE_D01_ART_COVER")),
        (MN("sp10", "k_hachiku && n2 > n1"), SH, hkLine),
        (MN("sp11", "k_ronpa"), SH, g.k("STATE_D01_SHF_BREAK")),
        (MN("sp12", "k_reverseRonpa"), CE, g.k("BEAT_D01_REVERSE_1")),
        (MN("sp13", "k_lastCard && n2 == 1"), CE, "k_downK"),
        (MN("sp14", "k_lastStand && n3 == 0"), CE, g.k("BEAT_D01_LASTSTAND_FAIL_1")),
        (MN("sp15", "k_crossed && xG"), AR, g.k("BEAT_D01_GUILT_1")),
        (MN("sp16", "k_crossed && xA"), CE, g.k("BEAT_D01_ANGER_1")),
        (MN("sp17", "k_stall"), CE, g.k("REACT_D01_FOGGED")),       # §6.7 被打迷糊仗 (every 打迷糊仗)
        (MN("sp18", "k_broken && !d_shk"), SH, g.k("STATE_D01_SHF_SHAKEN")),   # E5: his first 破防 of the debate
    ]
    g.x("hasSpeech", " || ".join(c[: -len("_t")] for c, _, _ in speech))
    who = ssel(g, "spWho", [(c, w) for c, w, _ in speech], g.k(""))
    line = ssel(g, "spLine", [(c, ln) for c, _, ln in speech], g.k(""))

    # system line: (condition, template key); its values latched with it
    g.tget("lcKind", "d1uiCard", "kind", g.tfind("lcRow", "d1uiCard", "id", "L_LastCard"))
    isS("lcPicked", "lcKind", "pickup")
    lc0 = g.sel("lcF0", T("lcZero", "L_Cracks == 0"), g.fmt("lcZ", "{a}", g.k(M.LAST_ZERO_C_DMG)),
                g.fmt("lcC", "{a} × {b}", g.k(M.LAST_PER_CRACK), "L_Cracks"))
    lcF = g.sel("lcF", g.b("lcPickedB", "lcPicked"),
                g.fmt("lcP", "{a} + {b}", lc0, g.k(M.LAST_PICKED_EXTRA)), lc0)
    # the multipliers with their names (UI_V2_F_*): base × 連擊 c [× 承接 1.2] [× 重提 0.5] [× 破竹 1.x] [× 破防 1.25]
    g.text("flC", g.k("UI_V2_F_COMBO"))
    parts = [g.fmt("fmA", "{a} × {b} {c}", "n4", "flC", "n5")]
    for i, (nk, nm, lk) in enumerate((("n6", "fmL", "UI_V2_F_FOLLOW"), ("n7", "fmR", "UI_V2_F_RESTATE"),
                                      ("n8", "fmH", "UI_V2_F_HACHIKU"), ("n9", "fmB", "UI_V2_F_GUARD"))):
        g.text(nm + "K", g.k(lk))
        parts.append(g.sel(nm, T(nm + "On", f"{nk} != 1"), g.fmt(nm + "T", " × {a} {b}", nm + "K", nk), g.k("")))
    formula = g.fmt("fmAll2", "{a}{b}", g.fmt("fmAll", "{a}{b}{c}{d}", *parts[:4]), parts[4])
    # Every line and every number in it comes from the round's records (d1Events, in order; one record of lookahead in
    # u1G) and the player's own command (act, the claim's sophistry as chosen), never from his tell: the tell is the
    # AI's decision, which a scripted round (d1OppAct) overrides. ch §12.0 names the line of each case.
    sysl = [(c, k) for c, k in ex_sy] + [
        # the opening (S07 L004), a step of its own before round 1
        (MN("syIntro", "d_intro == 1"), "SCR_D01_S07_L004"),
        (MN("sy1", "k_pAttach"), "SYS_D01_ATTACH"),
        (MN("sy2", "k_oAttach && cardUnfav"), "SYS_D01_SLIP_NODMG"),
        (MN("sy3", "k_pDmg && c_argument && act == 4"), "SYS_D01_FOG_TAKE"),
        # both nodes landed: his 論證 follows his node (our link and its damage were played before)
        (MN("syClash", "k_pDmg && c_argument && d_pat"), "SYS_D01_CLASH"),
        (MN("sy4", "k_pDmg && c_exposed"), "SYS_D01_EXPOSED"),
        (MN("sy5", "k_pDmg && c_refuted"), "SYS_D01_REFUTED"),
        (MN("sy6", "k_pDmg && c_contradiction"), "SYS_D01_REDCRACK"),
        # 截斷 that whiffs: he rebutted (his own whiff follows), he sidestepped (his heal follows), or he spoke and the
        # claim does not cut it (his node follows; not when the cut was barred by last round's sidestep: no line)
        (MN("sy11", "k_pDmg && c_whiff && act == 2 && nx_oDmg"), "SYS_D01_BOTH_REBUT"),
        (MN("sy7", "k_pDmg && c_whiff && act == 2 && (nx_oHeal || nx_healVoid)"), "SYS_D01_CUT_EMPTY"),
        # E4: a cut barred by last round's sidestep (his node follows) has its own line, without numbers
        (MN("syCs", "k_pDmg && c_whiff && act == 2 && nx_oAttach && d_intBlk"), "SYS_D01_CUT_SEALED"),
        (MN("sy8", "k_pDmg && ((c_whiff && act == 2 && nx_oAttach && !d_intBlk) || c_bad_cut)"), "SYS_D01_MISS_WRONG"),
        # 拆台 that whiffs (its dismantle record follows): a fact hit by a 正論, or a link the claim does not break (E4:
        # a sophistry on a fact of another issue too, −5)
        (MN("syTpF", "k_pDmg && c_whiff && act == 3 && nx_dismantle && nxFact && !d_soph"), "SYS_D01_TOPPLE_MISS_FACT"),
        (MN("syTpW", "k_pDmg && c_whiff && act == 3 && nx_dismantle && (!nxFact || d_soph)"),
         "SYS_D01_TOPPLE_MISS_WRONG"),
        (MN("sy9", "k_pDmg && c_fact_miss"), "SYS_D01_MISS_FACT"),
        (MN("sy10", "k_pDmg && c_stalemate && act == 4"), "SYS_D01_FOG_STALL"),
        (MN("sy12", "k_pDmg && c_stall_repeat"), "SYS_D01_FOG_REPEAT"),
        (MN("sy13", "k_pDmg && c_dying"), "SYS_D01_DESPERATE_HIT"),
        # his last card hits: it ends the debate, or 困獸 voids his recovery (E4: NOHEAL, then CORNERED at the healVoid
        # record), or he recovers (his lastCard record follows, with his credibility)
        (MN("sy14", "k_pDmg && c_last_card && (outOver || nx_healVoid)"), "SYS_D01_LASTCARD_NOHEAL"),
        (MN("syCor", "k_healVoid && !outOver && modeN == 1"), "SYS_D01_LASTCARD_CORNERED"),
        (MN("syLcH", "k_pDmg && c_last_card && !outOver && nx_lastCard"), "SYS_D01_LASTCARD_HIT"),
        (MN("syLcR", "k_lastCardRemoved && !nx_lastCardRemoved"), "SYS_D01_LASTCARD_REMOVE"),
        (MN("sy15b", "k_oDmg && c_intercept && myClaimSoph"), "SYS_D01_CUT_SOPH"),
        (MN("sy15", f"k_oDmg && c_intercept && n1 > {M.INTERCEPT_DMG}"), "SYS_D01_CUT_PUSH"),
        (MN("sy16", "k_oDmg && c_intercept"), "SYS_D01_CUT_OK"),
        (MN("sy17", "k_oDmg && c_dismantle"), "SYS_D01_DISMANTLE"),
        # E4: he rebutted while she dismantled: his whiff (the dismantle's own result was told before)
        (MN("syOrm", "k_oDmg && c_whiff && act == 3"), "SYS_D01_OPP_REBUT_MISS"),
        # the cut's record: a keystone (論破 or an ordinary cut), a fact knocked down by sophistry
        (MN("syKb", "k_intercept && n3 == 1 && n4 == 1"), "SYS_D01_KEY_BREAK"),
        (MN("syKn", "k_intercept && n3 == 1 && k_keyK"), "SYS_D01_KEY_NORMAL"),
        (MN("syDf", "k_intercept && n3 == 1 && k_factK"), "SYS_D01_DENY_FACT"),
        (MN("syDfD", "k_dismantle && n3 == 1 && k_factK"), "SYS_D01_DENY_FACT"),     # E4: a sophistry 拆台 on a fact
        # his rebuttal baited by a first 打迷糊仗 (破防 and a clear tell next round): told at the stall record
        (MN("sy18", "k_stall && stVsRebut && n2 == 0"), "SYS_D01_FOOLED"),
        (MN("sy19", "k_oHeal"), "SYS_D01_STALL_HEAL"),
        (MN("sy20", "k_refuted && knownN"), "SYS_D01_NOW_KNOWN"),
        (MN("sy21", "k_blocked"), "SYS_D01_BLOCKED"),
        (MN("sy22", "k_guardSaved"), "SYS_D01_COVER"),
        (MN("sy23", "k_shisshu && n1 == 1"), "SYS_D01_BREACH_HINT"),
        (MN("sy24", "k_crossed"), "SYS_D01_PSYCH_CROSS"),
        (MN("sy25", "k_ronpa && !outOver"), "SCR_D01_S07_L005"),
        (MN("sy26", "k_reverseRonpa"), "SYS_D01_REVERSE"),
        (MN("sy27", "k_endgame && egZero && !outOver"), "SCR_D01_S07_L006"),
        (MN("sy28", "k_lastCard && n2 == 1"), "SYS_D01_CUT_WIN"),
        (MN("sy29", "k_lastStand && n3 == 1"), "SYS_D01_LASTSTAND_OK"),
        (MN("sy30", "k_lastStand && n3 == 0"), "SYS_D01_LASTSTAND_FAIL"),
        (MN("sy32", "k_over && rsLimit"), "UI_V2_TIME_UP"),
        (MN("syZw", "k_over && ovSecZero"), "SYS_D01_ZERO_WIN"),
        (MN("sy33", "k_over && ovWin"), "SYS_D01_WIN"),
        (MN("sy34", "k_over"), "SCR_D01_S07_L016"),
        # the round's tail steps (after its last record; TAILS)
        *[(MN(f"syTl{i}", f"d_tail == {i}"), key) for i, key in enumerate(TAILS, start=1)],
    ]
    g.x("hasSys", " || ".join(c[: -len("_t")] for c, _ in sysl))
    skey = ssel(g, "syKey", [(c, g.k(k)) for c, k in sysl], g.k(""))
    # one step: both lines written together (a step without a spoken line clears it)
    showP = g.when("showG", parse, T("showOn", "hasSpeech || hasSys || (isMain && k_round)"))
    spP = syP = showP
    g.text("whoT", g.latch("whoL", who, spP))
    g.text("lineK", g.latch("lineL", line, spP))
    # BEAT_D01_REFUTED_3/4: {item} the picked-up evidence, {place} the hotspot where it lies (d1uiRefute)
    g.text("rfItemT", g.latch("rfItemL", "rfItemK", spP))
    g.text("rfPlaceT", g.latch("rfPlaceL", "rfPlaceK", spP))
    g.textf("lineT", pattern="lineK.text", item="rfItemT.text", place="rfPlaceT.text")
    # E6 (V1): blank until this debate's first playback step (the debate before left its last line here)
    frPb = fresh("frPb", showP)
    g.edge(g.sel("whoOut", frPb, g.k(""), "whoT.text"), f"{P}.speech_who")
    g.edge(g.sel("lineOut", frPb, g.k(""), "lineT.text"), f"{P}.speech")
    # values: hp after (pDmg / oDmg n3, lastStand n4), damage n1 / n3, the values of oHeal, the gauge's name, ...
    # v2 demo 4.4: every credibility and damage number is shown the way the chapter's §12 tables write it: at most two
    # decimals (R2: round(x * 100) / 100; the framework prints the shortest form), never below 0
    g.x("vHp", f"{R2('max(0, k_lastStand ? n4 : k_oAttach ? d_hpM : k_stall ? d_hpO : n3)')}")
    g.x("vPct", "round(gn5 / L_OppMax * 100)")
    g.x("vRmN", "d_rmN + 1")
    # E7: {n} of CHAIN_READY / NOBREAK (her chain), REV_READY (his), LASTCARD_REMOVE (the records); {issues}
    g.x("vN", "k_reverseRonpa ? ocN : (k_ronpa || k_pAttach) ? pcN : vRmN")
    myIss = issues_text(g, T, "piss", "d1PChain", "d1uiClaim")
    opIss = issues_text(g, T, "oiss", "d1OChain", "d1uiCard")
    issues = g.sel("vIss", g.b("vIssB", "k_reverseRonpa"), opIss, myIss)
    g.x("vHpO", R2("max(0, k_pDmg && c_last_card ? gn5 : d_hpO)"))
    g.x("vDmg", R2("k_pAttach ? n3 : n1"))
    g.x("vN1", R2("max(0, n1)"))
    g.x("vN2", R2("max(0, n2)"))
    g.x("vPatD", R2("d_patD"))
    value = ssel(g, "vVal", [(g.cmp("xPC3", "f1", g.k("P")), g.k("UI_V2_GAUGE_PRESSURE")),
                             (g.cmp("xGC3", "f1", g.k("G")), g.k("UI_V2_GAUGE_GUILT"))], g.k("UI_V2_GAUGE_ANGER"))
    node = g.sel("vNode", g.b("vNodeB", "k_lastStand"), "f2Label", "tgtLabel")
    fact = g.sel("vFact", g.b("vFactB", "k_refuted"), g.fmt("vFactK", "{a}_FACT", "f2"), g.k(""))
    frm = g.sel("vFormula", g.b("vFrmB", "k_pDmg"), lcF, formula)
    lat = {nm: g.latch(nm + "L", src, syP) for nm, src in
           (("sk", skey), ("vHp", "vHp"), ("vDmg", "vDmg"), ("vHpB", "vN1"), ("vHpA", "vN2"), ("vC", "world.d1Cracks"),
            ("vDmgP", "vPatD"), ("vHpO", "vHpO"), ("vPct", "vPct"), ("vRmN", "vN"), ("vIss", issues),
            ("vValue", value), ("vNode", node), ("vClaim", "scLabel"), ("vIssue", "f1IssueName"), ("vFact", fact),
            ("vFormula", frm))}
    g.text("skT", lat["sk"])
    lat["vPerson"] = g.latch("vPersonL", "scPerson", syP)
    for nm in ("vValue", "vNode", "vClaim", "vIssue", "vFact", "vPerson"):
        g.text(nm + "T", lat[nm])
    sys_text = g.textf("sysF", pattern="skT.text", name="oppName.text", hp=lat["vHp"], dmg=lat["vDmg"],
                       hp_before=lat["vHpB"], hp_after=lat["vHpA"], hp_p=lat["vHp"], c=lat["vC"],
                       value="vValueT.text", node="vNodeT.text", claim="vClaimT.text", issue="vIssueT.text",
                       fact="vFactT.text", formula=lat["vFormula"], dmg_p=lat["vDmgP"], hp_o=lat["vHpO"],
                       dmg_o=lat["vDmg"], pct=lat["vPct"], n=lat["vRmN"], person="vPersonT.text",
                       issues=lat["vIss"])
    g.edge(g.sel("sysOut", frPb, g.k(""), sys_text), f"{P}.sys_line")
    g.counter("lineSeq", initial=0)
    g.edge(showP, "lineSeq.increment")
    g.edge("lineSeq.value", f"{P}.line_seq")

    # numbers: the gauges follow the records (after values); floats
    pdP = g.when("pdG", parse, MN("pdOn", "k_pDmg"))
    setn(pdP, "hpM", "n3")
    g.x("fN1", R2("n1"))
    fm = g.latch("fmL2", g.fmt("fmDmg", "−{a}", "fN1"), pdP)
    odP = g.when("odG", parse, MN("odOn", "k_oDmg"))
    setn(odP, "hpO", "n3")
    hlP = g.when("hlG", parse, MN("hlOn", "k_oHeal"))
    setn(hlP, "hpO", "n2")
    fo = ssel(g, "foSel", [(g.b("foHeal", "k_oHeal"), g.fmt("foH", "+{a}", g.x("healAmt", R2("n2 - n1"))))],
              g.fmt("foD", "−{a}", "fN1"))
    foL = g.latch("foL", fo, g.merge("foM", odP, hlP))
    # E6 (V1): no float of the debate before
    g.edge(g.sel("foOut", fresh("frFo", "foM.out"), g.k(""), foL), f"{P}.float_opp")
    g.edge(g.sel("fmOut", fresh("frFm", pdP), g.k(""), fm), f"{P}.float_me")
    g.counter("foSeq", initial=0)
    g.edge(g.merge("foM2", odP, hlP), "foSeq.increment")
    g.edge("foSeq.value", f"{P}.float_opp_seq")
    g.counter("fmSeq", initial=0)
    g.edge(pdP, "fmSeq.increment")
    g.edge("fmSeq.value", f"{P}.float_me_seq")
    setn(g.when("gsG", parse, MN("gsOn", "k_guardSaved")), "hpM", "n1")
    setn(g.when("lsG", parse, MN("lsOn", "k_lastStand && n3 == 1")), "hpM", "n4")
    setn(g.when("lcHG", parse, MN("lcHOn", "k_lastCard && n2 == 0 && n3 == 0")), "hpO", "n5")
    # 論破 / entering the endgame: his credibility is what the engine says after the round (1 and locked; 0 when the
    # debate is over), not the argument record's raw value before the lock (v2 demo 4.4)
    setn(g.when("lockHG", parse, MN("lockHOn", "k_ronpa || k_endgame")), "hpO", "world.d1OppHp")
    patP = g.when("patOnG", parse, MN("patOn", "k_pAttach"))
    setn(patP, "pat", g.k(1))
    setn(patP, "patD", "n3")
    setn(g.when("intBG", parse, MN("intBOn", "k_intercept")), "intBlk", "n5")
    setn(g.when("rmG", parse, MN("rmOn", "k_lastCardRemoved")), "rmN", "vRmN")
    setn(g.when("patOffG", parse, MN("patOff", "k_round")), "pat", g.k(0))
    # 論破: his chain shatters
    g.counter("shatSeq", initial=0)
    g.edge(g.when("shatG", parse, MN("shatOn", "k_ronpa")), "shatSeq.increment")
    g.edge("shatSeq.value", f"{P}.shatter_seq")

    # cut-ins (ui#cutin, same ids as v1; 動搖 now on 破防, ch §13): one big or one stamp per record
    bigs = [(MN("bg1", "k_ronpa"), "CUT_RONPA"), (MN("bg2", "k_reverseRonpa"), "CUT_REVERSE"),
            (MN("bg3", "k_hachiku && n2 >= 3 && n1 < 3"), "CUT_HACHIKU3"), (MN("bg4", "k_shisshu && n1 == 1"), "CUT_SHISSHU"),
            (MN("bg5", "k_crossed && xP"), "CUT_KONJU"), (MN("bg6", "k_broken"), "CUT_SHAKEN")]
    # stamps (ruling c): the UI_V2_STAMP_* words on a text seal; his side top right (V2_TR), ours bottom left (V2_BL)
    # E7: the endgame cut that lands is a 截 too (ch §12.1 R9 【印：截】)
    stamps = [(MN("sm1", "k_intercept && n3 == 1"), "CUT", "TR"), (MN("sm2", "k_intercept"), "WHIFF", "BL"),
              (MN("sm9", "k_lastCard && n2 == 1"), "CUT", "TR"),
              (MN("sm3", "k_dismantle && n3 == 1"), "TOPPLE", "TR"), (MN("sm4", "k_dismantle"), "WHIFF", "BL"),
              (MN("sm5", "k_oAttach && d_pat"), "CLASH", "TR"), (MN("sm6", "k_guardSaved"), "COVER", "BL"),
              (MN("sm7", "k_oDmg && c_whiff"), "BAITED", "BL"), (MN("sm8", "k_pDmg && (c_exposed || c_refuted || c_last_card) && L_PCombo > 0"), "COMBO_BREAK", "BL")]
    g.x("hasBig", " || ".join(f"bg{i}" for i in range(1, len(bigs) + 1)))
    g.x("hasStamp", "!hasBig && (" + " || ".join(f"sm{i}" for i in range(1, len(stamps) + 1)) + ")")
    bid = ssel(g, "bigId", [(c, g.k(k)) for c, k in bigs], g.k(""))
    sid = ssel(g, "stampId", [(c, g.k("V2_" + side)) for c, _, side in stamps], g.k(""))
    skey = ssel(g, "stampKey", [(c, g.k("UI_V2_STAMP_" + w)) for c, w, _ in stamps], g.k(""))
    bigP = g.when("bigG", parse, "hasBig_t")
    stP = g.when("stG2", parse, "hasStamp_t")
    g.edge(g.latch("bigL", bid, bigP), "ui#cutin.big")
    g.counter("bigSeq", initial=0)
    g.edge(bigP, "bigSeq.increment")
    g.edge(g.x("bigSeqOut", f"bigSeq == 0 ? 0 : bigSeq + {SEQ_BASE}"), "ui#cutin.big_seq")
    g.edge(g.latch("stL", sid, stP), "ui#cutin.stamp")
    g.edge(g.text("stTxt", g.latch("stKL", skey, stP)), "ui#cutin.stamp_text")
    g.counter("stSeq", initial=0)
    g.edge(stP, "stSeq.increment")
    g.edge(g.x("stSeqOut", f"stSeq == 0 ? 0 : stSeq + {SEQ_BASE}"), "ui#cutin.stamp_seq")
    # the translation line under a big word (English, when cut-in subtitles are on); the text seals need none
    subKey = g.latch("subKeyL", g.fmt("subKey", "{a}_SUB", bid), bigP)
    g.text("subT", subKey)
    g.textf("subF", pattern="subT.text", n=g.latch("subNL", "n2", bigP))
    g.n("subLangN", langEn)
    g.n("subOnN", "world.cutinSub")
    g.edge(g.sel("subOut", T("subOn", "subLangN && subOnN"), "subF.text", g.k("")), "ui#cutin.subtitle")

    # the dwell before the next record
    g.x("dwell", "!isMain ? (hasSpeech ? 3 : 2) : k_ronpa ? 5 : hasBig ? 4 : hasSpeech ? 3 : hasSys ? 2 : "
                 "(k_pDmg || k_oDmg || k_oHeal) ? 1 : 0")
    # the first clash's beat: done from the next record on (clsP, read at the next fetch)
    setn(g.when("clsPG", parse, MN("clsPOn", "clashRec && !d_clsh")), "clsP", g.k(1))
    # E5: the once-per-debate lines, done from the next record on (hkP / shkP, read at the next fetch); the tail steps'
    # own (psych note, private matter) right away: the next tail step looks only further on
    setn(g.when("hkPG", parse, MN("hkPOn", "k_hachiku && n2 > n1 && !d_hkA")), "hkP", g.k(1))
    setn(g.when("shkPG", parse, MN("shkPOn", "k_broken && !d_shk")), "shkP", g.k(1))
    setn(g.when("nbPG", parse, MN("nbPOn", "k_pAttach && nbNow && !d_nb")), "nbP", g.k(1))      # E7
    setn(g.when("psnG", parse, MN("psnOn", "d_tail == 2")), "psn", g.k(1))
    g.edge(g.when("pvG", parse, MN("pvOn", "d_tail == 3")),
           g.eff("pvSet", "atrium.map.set", "u1Pv", key="s_claim", value=g.k(True)))
    setn(g.when("gsvG", parse, MN("gsvOn", "k_guardSaved")), "gsv", g.k(1))
    # ---- music (staging bgm_cues_d01.csv README): BGM07 at the start (S07 L004's cut), BGM08 when he first drops to
    # half or is first in 破防, BGM09 on 論破 and through the endgame, BGM10 on a Reverse Break (back to BGM09 when her
    # last card succeeds); silence from S07 L007 (he gives up) and on a loss (L016), until the lines after the debate
    setn(g.when("m8G", parse, MN("m8C", "(k_oDmg && n3 <= L_OppMax / 2) || k_broken")), "m8", g.k(1))
    setn(g.when("m9G", parse, MN("m9C", "k_ronpa || k_endgame")), "m9", g.k(1))
    setn(g.when("m10G", parse, MN("m10C", "k_reverseRonpa")), "m10", g.k(1))
    setn(g.when("m10bG", parse, MN("m10bC", "k_lastStand && n3 == 1")), "m10", g.k(0))
    setn(g.when("hushG", parse, T("hushC", "xL7S || (isMain && k_over && !ovWin)")), "hush", g.k(1))
    mom = ssel(g, "bgmMomD1", [(g.b("bmOffD1", g.x("bmOffD1N", "!isDebKN")), g.k("")),
                                (g.b("bmHush", g.p("d_hush")), g.k("hush")),
                                (g.b("bmRevD1", g.x("bmRevD1N", "d_m10 == 1")), g.k("reverse")),
                                (g.b("bmBrkD1", g.p("d_m9")), g.k("break")),
                                (g.b("bm8D1", g.p("d_m8")), g.k("debate2"))], g.k("d1open"))
    g.edge(mom, "world.bgmD1")
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
    g.edge(g.x("hpMeOut", R2("max(0, d_hpM)")), f"{P}.hp_me")
    g.edge(g.x("hpOppOut", R2("max(0, d_hpO)")), f"{P}.hp_opp")
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
    g.edge(g.textf("hachikuT", key="UI_STATE_HACHIKU", n="L_Hachiku"), f"{P}.hachiku_text")
    g.x("guardDown", "L_Broken && modeN == 0")
    g.edge("guardDown_t", f"{P}.guard_down")
    g.edge(g.b("shisB", "L_Shisshu"), f"{P}.shisshu")
    # E6 (V1): the chains are the debate before's until round 1 is shown
    g.x("pcNv", "frRN ? 0 : pcN")
    g.x("issNv", "frRN ? 0 : issN")
    g.edge(g.textf("ronpaT", key="UI_V2_RONPA_PROGRESS", n="pcNv", need=g.k(CH.ronpa_len), m="issNv"),
           f"{P}.ronpa_text")
    g.x("ronpaShow", "modeN == 0")
    g.edge("ronpaShow_t", f"{P}.show_ronpa")
    # "this round can break him" (ruling d): his guard is down and one more link reaches the length; the chain covers
    # 2 issues already, or 1 and a linkable claim of another issue is in the picker
    oth = []
    for k in ISSUE.values():
        key = f"ISSUE_D01_{k}_SHORT"
        g.n(f"lk{k}", g.mhas(f"lk{k}H", "u1LkIss", g.k(key)))
        g.n(f"in{k}", g.mhas(f"in{k}H", "u1Iss", g.k(key)))
        oth.append(f"(lk{k} && !in{k})")
    g.x("ronpaBase", f"L_Broken && modeN == 0 && pcN >= {CH.ronpa_len - 1}")
    g.x("ronpaTwo", f"ronpaBase && issN >= {CH.ronpa_issues}")
    g.x("ronpaReady", f"ronpaTwo || (ronpaBase && issN == {CH.ronpa_issues - 1} && ({' || '.join(oth)}))")
    g.edge("ronpaReady_t", f"{P}.ronpa_ready")
    g.edge(g.text("ronpaRT", g.sel("ronpaRK", "ronpaTwo_t", g.k("UI_V2_RONPA_READY"), g.k("UI_V2_RONPA_READY_ISSUE"))),
           f"{P}.ronpa_ready_text")
    # the tell (laststand: none)
    g.x("tellOn", "(modeN == 0 || modeN == 1) && !frRN")     # E6: none before round 1 is shown
    g.edge("tellOn_t", f"{P}.tell_on")
    g.n("tellClearN", g.cmp("tellClearC", "L_TellClarity", g.k("clear")))
    g.edge("tellClearC.out", f"{P}.tell_clear")
    # heading: a vague tell with a card shows the card he would say if he speaks (00_core_rules §15〔M2〕)
    g.n("tcHasN", g.cmp("tcHasC", "L_TellCard", g.k(""), op="ne"))
    g.x("tellIfs", "!tellClearN && tcHasN")
    g.edge(g.text("tellHeadT", g.sel("tellHeadK", "tellIfs_t", g.k("UI_V2_TELL_IF_SPEAKS"), g.k("UI_V2_TELL_HEAD"))),
           f"{P}.tell_head")
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
    # The tell's lines (ref lines.tell_lines, v2 demo E5; ch §11 「亞瑟提示的時機」): on a clear tell (not the endgame) his
    # own tell line TELL_D01_<action>_n (that action's lines in turn: u1 tc<code> counts them); then Arthur's hint, the
    # first that holds and is not spent (a spent one falls through): 9 his last card (every time), 5 a half sentence
    # (every time), 6 the keystone, 8 a lie no claim of this round's picker that shows as 正論 can cut (d1uiBreak), 7 a
    # favourable fact, 1-4 the action on a clear tell (once per debate each: u1 h<index>); in the endgame the P05 beat
    # before it and the dying gasp's S07 L010 (his) after it. Up to two lines (hint, hint2), none in the §7.5 round.
    g.tget("tcKeyN", "d1uiCard", "key", "tcRow", "number")
    g.tget("tcLieN", "d1uiCard", "lie", "tcRow", "number")
    g.tget("tcFavN", "d1uiCard", "fav", "tcRow", "number")
    for i in (1, 2, 3, 4, 6, 7, 8):
        g.mget(f"hU{i}", "u1", g.k(f"h{i}"))
    g.x("hIdx", "modeN == 2 ? 0 : modeN == 1 ? 9 : L_TellPartial ? 5 : (tcHasN && tcKeyN && !hU6) ? 6"
                " : (tcHasN && tcLieN && !d_cutOk && !hU8) ? 8 : (tcHasN && tcFavN && !hU7) ? 7"
                " : (tellClearN && ta >= 0 && ta <= 3 && !(ta == 0 ? hU1 : ta == 1 ? hU2 : ta == 2 ? hU3 : hU4))"
                " ? ta + 1 : 0")
    hKey = g.lookup("hKey", HINTS, "hIdx")
    hFlag = g.fmt("hFlag", "h{a}", "hIdx")
    # his tell line: flat key list by tell code (each code's lines in turn)
    keys = F.string_keys()
    own, base, cnt = [], [], []
    for w in TELL_WORDS:
        ks = []
        while f"TELL_D01_{w}_{len(ks) + 1}" in keys:
            ks.append(f"TELL_D01_{w}_{len(ks) + 1}")
        base.append(len(own) + 1)
        cnt.append(len(ks))
        own += ks
    g.mget("tcN", "u1", g.fmt("tcNKey", "tc{a}", "ta"))
    g.x("ownOn", f"tellClearN && modeN == 0 && ta >= 0 && ta <= 3")
    g.x("ownCnt", " : ".join(f"ta == {i} ? {c}" for i, c in enumerate(cnt)) + " : 0")
    g.x("ownBase", " : ".join(f"ta == {i} ? {b}" for i, b in enumerate(base)) + " : 0")
    g.x("ownIdx", "ownOn && ownCnt > 0 ? ownBase + (tcN - ownCnt * floor(tcN / ownCnt)) : 0")
    ownKey = g.lookup("ownKey", [""] + own, "ownIdx")
    # the two lines: normal round: his line, Arthur's; endgame: P05 beat + hint, hint + L010 (dying), or the hint
    g.x("t1Kind", "ownIdx > 0 ? 1 : (modeN == 1 && lcP05) ? 2 : hIdx > 0 ? 3 : 0")
    g.x("t2Kind", "ownIdx > 0 ? (hIdx > 0 ? 3 : 0) : (modeN == 1 && lcP05) ? 3 : (modeN == 1 && L_Dying) ? 4 : 0")
    kinds_k = [g.k(""), ownKey, g.k("BEAT_D01_LASTCARD_1"), hKey, g.k("SCR_D01_S07_L010")]
    kinds_w = ["", "SPK_D01_CEDRIC", "SPK_ARTHUR", "SPK_ARTHUR", "SPK_D01_CEDRIC"]
    for n in (1, 2):
        kk = ssel(g, f"t{n}Key", [(T(f"t{n}K{i}", f"t{n}Kind == {i}"), kinds_k[i]) for i in range(1, 5)], g.k(""))
        sets(r2T, "hintK" if n == 1 else "hint2K", kk)
        sets(r2T, "hintW" if n == 1 else "hint2W", g.lookup(f"t{n}Who", kinds_w, f"t{n}Kind"))
    # mark the hint used (the every-time ones too: harmless) and count his line
    g.edge(g.when("hintG", r2T, T("hintOn", "hIdx > 0")), g.eff("hMark", "atrium.map.set", "u1", key=hFlag,
                                                               value=g.k(1)))
    g.edge(g.when("ownG", r2T, T("ownOnG", "ownIdx > 0")),
           g.eff("ownCount", "atrium.map.set", "u1", key="tcNKey", value=g.x("tcNext", "tcN + 1")))
    g.edge(g.text("hintT", "s_hintK"), f"{P}.hint")
    g.edge(g.text("hintWT", "s_hintW"), f"{P}.hint_who")
    g.edge(g.text("hint2T", "s_hint2K"), f"{P}.hint2")
    g.edge(g.text("hint2WT", "s_hint2W"), f"{P}.hint2_who")
    g.edge(g.textf("dyingT", key="UI_V2_DEATH_THROE", n=g.k(M.DYING_DMG)), f"{P}.dying_text")
    # the choice
    g.edge(g.b("canDisB", g.x("canDis", "ocN > 0 && !frRN")), f"{P}.can_dismantle")
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
    return g
