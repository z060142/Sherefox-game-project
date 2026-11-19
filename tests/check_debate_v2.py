# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Golden check of the v2 debate engine of D01 (flows/d01_debate_engine.xtflow) against the reference model
ref/src/sherefox_ref/v2 (docs/debate-engine-v2.md §6).

Usage (from the project root):
    uv run tests/check_debate_v2.py [--seeds K] [--route NAME ...] [--no-play] [--keep DIR] [--verbose]

1. regenerates the engine (tools/gen_debate_v2.py),
2. routes A-D (ref routes.py, read at run time): the forced replays through ref resolve_round give the expected
   state and events after each round,
3. seeded full-policy runs: ref play.play(loadout, seed) for debate seeds 1..K and every route loadout (ref draws
   from its own port of atrium.rng.stream, rng.DebateRng; the harness gives the engine the same seed through
   world.d1Seed, docs/debate-engine-v2.md §3.4), plus seeded fuzz runs: the same opponent, the player a seeded
   random.Random picking any action ref accepts
   (拆台, 援護, the endgame and §7.5 choices included), and three extra carry sets (EXTRA_LOADOUTS),
4. writes one headless harness project per job into a temporary directory (engine flow and tables copied in, a
   driver flow and its input table generated), runs them in parallel, and compares per round: every ref State field
   (encoded state map and the list mirrors), the event records, the claim list, the opponent's decision and tell
   for the next round, and at the end the result (grade, truth, reputation items, favour).
Prints PASS / FAIL per route and per run with the first diverging round and field. Exit 0 when all pass.
Every temporary file lives under one TemporaryDirectory and is removed at the end.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "ref" / "src"))

import gen_debate_v2 as G  # noqa: E402
from v2trace import Emitter, T  # noqa: E402
from xt_cli import EXE, XTFRAME  # noqa: E402
from sherefox_ref.v2 import known as K  # noqa: E402
from sherefox_ref.v2 import play as P  # noqa: E402
from sherefox_ref.v2 import results as RS  # noqa: E402
from sherefox_ref.v2 import epilogue as EP  # noqa: E402
from sherefox_ref.v2 import routes as RT  # noqa: E402
from sherefox_ref.v2.model import PA, IllegalAction, Loadout, PlayerAction, initial_state  # noqa: E402
from sherefox_ref.v2.policy import RngChooser, decide  # noqa: E402
from sherefox_ref.v2.resolve import resolve_round  # noqa: E402
from sherefox_ref.v2.rng import DebateRng, Stream  # noqa: E402

H_PERIOD = 4
VERBOSE = False

# --------------------------------------------------------------------------------------------- the UI's seed


class GlobalRng:
    """Python port of XTAtrium.Core.Rng, the simulation's global stream (xoshiro128** 1.1, seed expanded by
    SplitMix64; NextFloat as atrium.rng pushes it). Only used to predict the debate seed the debate UI draws."""

    def __init__(self, seed: int):
        self.s = Stream(seed)

    def next_float(self) -> float:
        return (self.s.next_u32() >> 8) * (1.0 / (1 << 24))


def ui_debate_seed(run_seed: int, draws_before: int = 0) -> int:
    """The seed flows/d01_debate_ui.xtflow gives the engine when the debate starts: floor(u * 2^24) of the next
    atrium.rng value (docs/flows.md §4.12), `draws_before` global draws into a run with seed `run_seed`."""
    g = GlobalRng(run_seed)
    for _ in range(draws_before):
        g.next_float()
    return math.floor(g.next_float() * (1 << 24))


# --------------------------------------------------------------------------------------------- expected side

def g6(v) -> str:
    if isinstance(v, bool):
        return "1" if v else "0"
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return "%.6g" % v
    return str(v)


def rec(*parts) -> str:
    return "|".join(g6(p) for p in parts)


def ref_records(events: list, before) -> list[str]:
    ch = before.ch
    chain = [n.claim for n in before.player_chain]
    out = []
    for e in events:
        k = e["kind"]
        if k == "round":
            out.append(rec("round", e["round"]))
        elif k == "player_damage":
            out.append(rec("pDmg", e["amount"], e["cause"], e["hp"]))
        elif k == "opp_damage":
            out.append(rec("oDmg", e["amount"], e["cause"], e["hp"]))
        elif k == "opp_heal":
            out.append(rec("oHeal", e["before"], e["hp"]))
        elif k == "heal_void":
            out.append("healVoid")
        elif k == "reraise":
            out.append(rec("reraise", e["card"]))
        elif k == "psych_event":
            out.append(rec("psych", e["event"], *e["delta"], *e["psych"]))
        elif k == "opp_attach":
            out.append(rec("oAttach", e["card"], e["combo"]))
        elif k == "player_attach":
            f = e["factors"]
            prev = chain[-1] if "continuation" in f and chain else ""
            out.append(rec("pAttach", e["claim"], e["combo"], e["damage"], f["base"], f["combo"],
                           f.get("continuation", 1), f.get("reraise", 1), f["hachiku"], f.get("broken", 1), prev))
            chain.append(e["claim"])
        elif k == "red_crack":
            excl = set(ch.claims[e["claim"]].exclusive)
            with_ = next((r.claim for r in before.record if r.claim in excl), "")
            out.append(rec("redCrack", e["claim"], with_))
            out += [rec("redCrackRemoved", c) for c in chain if c in e["removed"]]
            chain = [c for c in chain if c not in e["removed"]]
        elif k == "exposed":
            out.append(rec("exposed", e["claim"]))
        elif k == "refuted":
            out.append(rec("refuted", e["claim"], e["line"], e["reveals"]))
        elif k == "blocked":
            out.append(rec("blocked", e["claim"]))
        elif k == "intercept":
            out.append(rec("intercept", e["claim"], e["card"], e["ok"], e.get("keystone", False),
                           e.get("blocked_by_parry", False)))
        elif k == "broken":
            out.append(rec("broken", e["cause"], e["until"]))
        elif k == "dismantle":
            out.append(rec("dismantle", e["claim"], e["card"], e["ok"]))
        elif k == "stall":
            out.append(rec("stall", e["vs"], e["repeat"]))
        elif k == "guard_saved":
            out.append(rec("guardSaved", e["hp"]))
        elif k == "hachiku":
            out.append(rec("hachiku", e["before"], e["after"]))
        elif k == "shisshu":
            out.append(rec("shisshu", e["on"]))
        elif k == "threshold_crossed":
            out.append(rec("crossed", e["stat"]))
        elif k == "debate_over":
            out.append(rec("over", e["outcome"], e["grade"], e["reason"]))
        elif k == "reverse_ronpa":
            out.append("reverseRonpa")
            out += [rec("reverseRonpaNode", c) for c in e["chain"]]
        elif k == "ronpa":
            out.append(rec("ronpa", e["via"]))
            out += [rec("ronpaNode", c) for c in e["chain"]]
        elif k == "endgame":
            out.append(rec("endgame", e["trigger"], e["cracks"]))
        elif k == "last_card":
            if e["cut"]:
                out.append(rec("lastCard", e["card"], 1, 0, 0, 0))
            elif e.get("dying"):
                out.append(rec("lastCard", e["card"], 0, 1, 0, 0))
            else:
                out.append(rec("lastCard", e["card"], 0, 0, e["damage"], e["opp_hp"]))
                out += [rec("lastCardRemoved", c) for c in chain if c in e["removed"]]
        elif k == "last_stand":
            if e["ok"]:
                out.append(rec("lastStand", e["claim"], e["target"], 1, e["hp"]))
                out += [rec("lastStandDestroyed", c) for c in e["destroyed"]]
            else:
                out.append(rec("lastStand", e["claim"], e["target"] or "", 0, 0))
        elif k == "rule3_armed":
            out.append("rule3Armed")
        else:
            raise SystemExit(f"unmapped ref event {k}")
    return out


def opt_idx(lst, x) -> int:
    return lst.index(x) + 1 if x is not None else 0


def ref_view(s) -> dict:
    """Every ref State field the engine models, in ref terms."""
    ch = s.ch
    once = {c for c in G.CLAIMS if ch.claims[c].psych is not None and ch.claims[c].psych_once}
    eg = s.endgame
    return {
        "round": s.round, "player_hp": s.player_hp, "opp_hp": s.opp_hp,
        "player_chain": [(n.claim, n.cracked) for n in s.player_chain], "opp_chain": [n.card for n in s.opp_chain],
        "player_combo": s.player_combo, "opp_combo": s.opp_combo, "hachiku": s.hachiku,
        "broken_until": s.broken_until, "shisshu": s.shisshu, "psych": list(s.psych), "psych_end": list(s.psych_end),
        "over": list(s.over), "crossed": list(s.crossed), "known": sorted(s.known),
        "record": [rec(r.round, r.claim, r.use, r.soph, r.crack, r.true) for r in s.record],
        "cracks": s.cracks, "denials": s.denials, "voided": sorted(s.voided),
        "knocked_claims": sorted(c for c in s.knocked_claims if c in ch.claims),
        "psych_used": sorted(c for c in s.psych_used if c in once),
        "hand": list(s.hand), "reraised": list(s.reraised), "knocked": list(s.knocked), "picked": sorted(s.picked),
        "reserved_last": s.reserved_last, "endgame": None if eg is None else (eg["trigger"], eg["card"], eg["dying"]),
        "ronpa_done": s.ronpa_done, "reversed": s.reversed, "player_locked": s.player_locked,
        "rule3_fired": s.rule3_fired, "rule3_pending": s.rule3_pending, "next_clear": s.next_clear,
        "no_intercept_round": s.no_intercept_round, "stall_streak": s.stall_streak, "stalls": s.stalls,
        "catch_card": s.catch_card, "catch_next": s.catch_next, "next_unfav": s.next_unfav,
        "few_fired": s.few_fired, "history": [a.value for a in s.opp_history[-2:]],
        "flag_player_soph": s.flag_player_soph, "flag_knocked_lie": s.flag_knocked_lie,
        "flag_hit_player": s.flag_hit_player, "guard_used": s.guard_used, "privates": s.privates,
        "psych_card_uses": s.psych_card_uses, "both_zero": s.both_zero, "last_card_used": s.last_card_used,
        "outcome": s.outcome, "grade": s.grade, "end_reason": s.end_reason,
    }


def engine_view(m: dict) -> dict:
    """The same fields decoded from the engine's state map."""
    CK, CL = G.CK, G.CL

    def card(v):
        return CK[int(v) - 1] if v else None

    def order(prefix, ids, key=lambda x: x):
        got = [(m[f"{prefix}_{key(i)}"], i) for i in ids if m.get(f"{prefix}_{key(i)}", 0) > 0]
        return [i for _, i in sorted(got)]

    eg = int(m["eg"])
    hist = [G.OA_NAMES[int(v) - 1] for v in (m["h2"], m["h1"]) if v]
    return {
        "round": m["r"], "player_hp": m["php"], "opp_hp": m["ohp"],
        "player_chain": [(c, bool(m[f"pk_{G.ck(c)}"])) for c in order("pc", CL, G.ck)],
        "opp_chain": order("oc", G.HAND_CARDS), "player_combo": m["pcb"], "opp_combo": m["ocb"],
        "hachiku": m["hk"], "broken_until": m["bu"], "shisshu": bool(m["ss"]),
        "psych": [m["p0"], m["p1"], m["p2"]], "psych_end": [m["e0"], m["e1"], m["e2"]],
        "over": [bool(m[f"o{i}"]) for i in range(3)], "crossed": [bool(m[f"cr{i}"]) for i in range(3)],
        "known": sorted(k for k in G.KNOWN if m[G.kn_key(k)]),
        "record": None,  # from the d1Record mirror
        "cracks": m["cracks"], "denials": m["den"],
        "voided": sorted(c for c in G.CLAIMS if m.get(f"vd_{c}")),
        "knocked_claims": sorted(c for c in G.CLAIMS if m[f"kc_{c}"]),
        "psych_used": sorted(c for c in G.CLAIMS if m.get(f"pu_{c}")),
        "hand": order("hd", G.HAND_CARDS), "reraised": order("rr", G.LIE_CARDS), "knocked": order("kk", G.LIE_CARDS),
        "picked": sorted(e for e in G.PICK_EV if m[f"pe_{e}"]), "reserved_last": card(m["rl"]),
        "endgame": None if eg == 0 else (G.TRIGGERS[eg], card(m["egc"]), bool(m["egd"])),
        "ronpa_done": bool(m["rdn"]), "reversed": bool(m["rev"]), "player_locked": bool(m["pl"]),
        "rule3_fired": bool(m["r3f"]), "rule3_pending": bool(m["r3p"]), "next_clear": bool(m["nclr"]),
        "no_intercept_round": m["nir"], "stall_streak": m["sstk"], "stalls": m["stalls"],
        "catch_card": card(m["cc"]), "catch_next": card(m["cn"]), "next_unfav": bool(m["nu"]),
        "few_fired": bool(m["few"]), "history": hist, "flag_player_soph": bool(m["fps"]),
        "flag_knocked_lie": card(m["fkl"]), "flag_hit_player": bool(m["fhp"]), "guard_used": bool(m["gu"]),
        "privates": m["priv"], "psych_card_uses": m["pcu"], "both_zero": bool(m["bz"]),
        "last_card_used": bool(m["lcu"]),
        "outcome": [None, "win", "loss"][int(m["out"])], "grade": int(m["grade"]) if m["out"] else None,
        "end_reason": G.REASONS[int(m["why"])] or None,
    }


def ref_decision(d) -> dict | None:
    if d is None:
        return None
    t = d.tell
    return {"action": d.action.kind.value, "card": d.action.card, "tell_card": t.card if t else None,
            "clarity": t.clarity.value if t else None, "shown": [a.value for a in t.shown] if t else [],
            "star": t.star.value if t and t.star else None, "partial": bool(t.partial) if t else False,
            "rule": d.rule or 0, "forced": d.forced if d.forced not in (None,) else ""}


def engine_decision(m: dict) -> dict:
    def act(v):
        return G.OA_NAMES[int(v) - 1] if v else None
    a = act(m["da"])
    clear_tell = a != "none"
    shown = [act(m["ds1"])] + ([act(m["ds2"])] if m["ds2"] else [])
    forced = G.FORCED[int(m["dfo"])]
    return {"action": a, "card": G.CK[int(m["dc"]) - 1] if m["dc"] else None,
            "tell_card": G.CK[int(m["dtc"]) - 1] if m["dtc"] and clear_tell else None,
            "clarity": ("vague" if m["dcl"] else "clear") if clear_tell else None,
            "shown": shown if clear_tell else [], "star": act(m["dst"]), "partial": bool(m["dp"]),
            "rule": int(m["drl"]), "forced": forced}


def ref_claims(s) -> tuple[list, dict]:
    views = K.claim_list(s)
    return [v.id for v in views], {v.id: (v.soph, v.red_crack, v.standing) for v in views}


def ref_result(s) -> dict:
    r = RS.compute(s)
    e = EP.epilogue(s)
    return {"s08": list(e.s08), "s09": list(e.s09), "s10": list(e.s10), "rep_names": [n for n, _ in r.reputation],
            "truth": r.truth, "rep": [f"{n}|{d}" for n, d in r.reputation], "delta": r.reputation_delta,
            "after": r.reputation_after, "next_hp": r.next_start_hp, "favour": [f"{w}|{d}" for w, d in r.favour],
            "note": r.note_version, "paper": r.newspaper, "false": len(r.false_claims), "key_left": len(r.key_left),
            "grade": r.grade, "reason": r.reason, "rounds": r.rounds}


def engine_result(m: dict, lists: dict) -> dict:
    return {"s08": lists.get("d1EpS08", []), "s09": lists.get("d1EpS09", []), "s10": lists.get("d1EpS10", []),
            "rep_names": lists.get("d1EpRep", []),
            "truth": m["truth"], "rep": lists.get("d1Rep", []), "delta": m["rdl"], "after": m["rpa"],
            "next_hp": m["nhp"], "favour": lists.get("d1Favour", []), "note": G.NOTES[int(m["note"])],
            "paper": G.PAPERS[int(m["paper"])], "false": m["nfc"], "key_left": m["kl"], "grade": int(m["grade"]),
            "reason": G.REASONS[int(m["why"])], "rounds": m["r"] - 1}


# --------------------------------------------------------------------------------------------- jobs

class Debate:
    def __init__(self, name, loadout, steps, start_decision, start_state, seed):
        self.name, self.loadout, self.steps, self.seed = name, loadout, steps, seed
        self.start_decision, self.start_state = start_decision, start_state
        # steps: [(player action, override opponent action or None, state before, state after, events, decision)]


def route_debates(names) -> list[Debate]:
    """Each route is one debate with its own seed (the AI still decides every round; the harness overrides it)."""
    out = []
    for k, name in enumerate(names):
        seed = 1000 + k
        ch = RngChooser(DebateRng(seed))
        route = RT.ROUTES[name]
        s = initial_state(route.loadout)
        d0 = decide(s, ch)
        steps = []
        for pa, oa, _t in route.rounds:
            if s.outcome:
                break
            s2, ev = resolve_round(s, pa, oa)
            d = decide(s2, ch) if not s2.outcome else None
            steps.append((pa, oa, s, s2, ev, d))
            s = s2
        out.append(Debate(f"route {name}", route.loadout, steps, d0, initial_state(route.loadout), seed))
    return out


# extra carry sets besides the four route loadouts (model.Loadout; validated by ref initial_state)
EXTRA_LOADOUTS = {
    "min": Loadout(("E03", "E09", "E12"), (), (), warmup="fail"),
    "psych": Loadout(("P1", "E02", "E03", "E04", "E06", "E07", "E08", "E09", "E10"), ("A02", "A04"),
                     ("PN3", "PN4", "OBS01"), warmup="pass_clean"),
    "liars": Loadout(("E01", "E04", "E05", "E06", "E07", "E09", "E11", "E12", "P1"), ("A01",), ("PN1",)),
}


def loadouts() -> dict:
    out = {n: r.loadout for n, r in RT.ROUTES.items()}
    out.update(EXTRA_LOADOUTS)
    return out


def fuzz_debate(name, loadout, seed) -> Debate:
    """Opponent: ref policy on the debate's streams (debate seed `seed`). Player: random legal actions (including
    拆台, 援護, the endgame and §7.5 choices) from a seeded random.Random; legality = ref resolve_round does not
    raise."""
    py = random.Random(seed * 7919 + len(loadout.carried))
    ch = RngChooser(DebateRng(seed))
    s = s0 = initial_state(loadout)
    d = d0 = decide(s, ch)
    steps = []
    for _ in range(40):
        if s.outcome:
            break
        views = [v.id for v in K.claim_list(s)]
        cands = []
        if s.player_locked:
            for c in views:
                for t in [None] + [n.card for n in s.opp_chain]:
                    cands.append(PlayerAction(PA.LAST_STAND, c, t))
            cands.append(PlayerAction(PA.ACCEPT))
        elif s.endgame:
            cands = [PlayerAction(PA.CUT, c) for c in views] + [PlayerAction(PA.ACCEPT)]
        else:
            guard = (not s.guard_used) and py.random() < 0.25
            for c in views:
                cands.append(PlayerAction(PA.ARGUE, c, guard=guard))
                cands.append(PlayerAction(PA.INTERCEPT, c, guard=guard))
                for n in s.opp_chain:
                    cands.append(PlayerAction(PA.DISMANTLE, c, n.card, guard=guard))
            cands += [PlayerAction(PA.STALL, guard=guard)] * 3
        py.shuffle(cands)
        for pa in cands:
            try:
                s2, ev = resolve_round(s, pa, d.action)
                break
            except IllegalAction:
                continue
        else:
            raise SystemExit(f"{name}: no legal action")
        dn = decide(s2, ch) if not s2.outcome else None
        steps.append((pa, None, s, s2, ev, dn))
        s, d = s2, dn
    return Debate(name, loadout, steps, d0, s0, seed)


def play_debate(name, loadout, seed) -> Debate:
    """ref play.play(loadout, seed) (debate seed `seed`), plus the full states for the field comparison."""
    trace = P.play(loadout, seed)
    ch = RngChooser(DebateRng(seed))
    s = initial_state(loadout)
    s0 = s
    steps = []
    d = decide(s, ch)
    d0 = d
    for i in range(40):
        if s.outcome:
            break
        pa = P.bot(s, d.tell)
        s2, ev = resolve_round(s, pa, d.action)
        dn = decide(s2, ch) if not s2.outcome else None
        steps.append((pa, None, s, s2, ev, dn))
        if trace[i]["events"] != ev or trace[i]["player"]["claim"] != pa.claim:
            raise SystemExit(f"{name}: the check's replay differs from ref play.play at round {i + 1}")
        s, d = s2, dn
    if len(steps) != len(trace):
        raise SystemExit(f"{name}: replay length {len(steps)} != play.play {len(trace)}")
    return Debate(name, loadout, steps, d0, s0, seed)


# --------------------------------------------------------------------------------------------- harness

H_COLS = ["op", "kind", "claim", "target", "guard", "oppAct", "oppCard", "carry", "appr", "notes", "warmup", "seed"]
H_NUM = ("guard", "seed")
SNAP_LISTS = G.ENGINE_LISTS
SNAP_MAPS = ["d1State", "d1ClaimSoph", "d1ClaimCrack", "d1ClaimStand"]


def harness_rows(debates) -> tuple[list[dict], list[tuple]]:
    # row 0 is idle: a compare's pulse does not fire on the very first evaluation (tick 0)
    rows, index = [{c: (0 if c in H_NUM else "") for c in H_COLS}], []
    for d in debates:
        lo = d.loadout
        rows.append({"op": "start", "kind": "", "claim": "", "target": "", "guard": 0, "oppAct": "", "oppCard": "",
                     "carry": ",".join(lo.carried), "appr": ",".join(lo.appraisals), "notes": ",".join(lo.notes),
                     "warmup": lo.warmup, "seed": d.seed})
        index.append((d, -1, len(rows) - 1))
        for i, (pa, oa, *_r) in enumerate(d.steps):
            rows.append({"op": "round", "kind": pa.kind.value, "claim": pa.claim or "", "target": pa.target or "",
                         "guard": int(pa.guard), "oppAct": oa.kind.value if oa else "",
                         "oppCard": (oa.card or "") if oa else "", "carry": "", "appr": "", "notes": "",
                         "warmup": lo.warmup, "seed": d.seed})
            index.append((d, i, len(rows) - 1))
    return rows, index


def driver() -> str:
    """Row k of hIn: values written from tick 4k (loadout lists at 4k), pulse at 4k+1, snapshot at 4k+3."""
    T.reset()
    em = Emitter("h")
    n = em.node
    n("clock", "clock")
    n("tick", "atrium.expr", expr="round(sec * 60)")
    em.edge("clock.seconds", "tick.sec")
    n("row", "atrium.expr", expr="floor(t / 4)")
    em.edge("tick.value", "row.t")
    n("ph", "atrium.expr", expr="t - floor(t / 4) * 4")
    em.edge("tick.value", "ph.t")
    for c in H_COLS:
        n(f"c_{c}", "atrium.table.get", table="hIn", column=c, type="number" if c in H_NUM else "string")
        em.edge("row.value", f"c_{c}.row")
    for sig, c in (("d1CmdKind", "kind"), ("d1CmdClaim", "claim"), ("d1CmdTarget", "target"),
                   ("d1CmdGuard", "guard"), ("d1OppAct", "oppAct"), ("d1OppCard", "oppCard"),
                   ("d1Warmup", "warmup"), ("d1Seed", "seed")):
        em.edge(f"c_{c}.value", f"world.{sig}")
    for op in ("start", "round"):
        n(f"is_{op}", "compare", op="eq")
        em.edge("c_op.value", f"is_{op}.a")
        em.edge(em.const(op), f"is_{op}.b")
        n(f"n_{op}", "select")
        em.edge(f"is_{op}.out", f"n_{op}.cond")
        em.edge(em.const(1), f"n_{op}.a")
        em.edge(em.const(0), f"n_{op}.b")

    def phase(k):
        nid = f"ph{k}"
        n(nid, "compare", op="eq")
        em.edge("ph.value", f"{nid}.a")
        em.edge(em.const(k), f"{nid}.b")
        return f"{nid}.true"

    def gate(nid, cond_port, src):
        n(nid, "atrium.gate")
        em.edge(cond_port, f"{nid}.cond")
        em.edge(src, f"{nid}.trigger")
        return f"{nid}.pass"

    p0 = gate("g0", "n_start.out", phase(0))
    for coll, c in (("d1Carry", "carry"), ("d1Appraised", "appr"), ("d1Notes", "notes")):
        n(f"clr_{coll}", "atrium.coll.clear", name=coll)
        n(f"add_{coll}", "atrium.coll.addAll", name=coll)
        em.edge(f"c_{c}.value", f"add_{coll}.text")
        em.edge(p0, f"clr_{coll}.trigger")
        em.edge(p0, f"add_{coll}.trigger")
    ph1 = phase(1)
    n("mStart", "merge")
    em.edge(gate("g1", "n_start.out", ph1), "mStart.in")
    em.edge("mStart.out", "world.d1Start")
    n("mLock", "merge")
    em.edge(gate("g2", "n_round.out", ph1), "mLock.in")
    em.edge("mLock.out", "world.d1Lock")
    ph3 = phase(3)
    for i, mp in enumerate(SNAP_MAPS):
        n(f"mf{i}", "atrium.map.forEach", name=mp)
        n(f"mk{i}", "format", format="{a}:" + mp + ":{b}")
        em.edge("row.value", f"mk{i}.a")
        em.edge(f"mf{i}.key", f"mk{i}.b")
        n(f"ms{i}", "atrium.map.set", name="hNum")
        em.edge(f"mk{i}.out", f"ms{i}.key")
        em.edge(f"mf{i}.value", f"ms{i}.value")
        em.edge(f"mf{i}.each", f"ms{i}.trigger")
        em.edge(ph3, f"mf{i}.trigger")
    for i, coll in enumerate(SNAP_LISTS):
        n(f"lf{i}", "atrium.coll.forEach", name=coll)
        n(f"lk{i}", "format", format="{a}#" + coll + "#{b}")
        em.edge("row.value", f"lk{i}.a")
        em.edge(f"lf{i}.item", f"lk{i}.b")
        n(f"la{i}", "atrium.coll.add", name="hList")
        em.edge(f"lk{i}.out", f"la{i}.value")
        em.edge(f"lf{i}.each", f"la{i}.trigger")
        em.edge(ph3, f"lf{i}.trigger")
    for i, sig in enumerate(G.OUT_STR):
        n(f"sk{i}", "format", format="{a}:" + sig)
        em.edge("row.value", f"sk{i}.a")
        n(f"ss{i}", "atrium.map.set", name="hStr")
        em.edge(f"sk{i}.out", f"ss{i}.key")
        em.edge(f"world.{sig}", f"ss{i}.value")
        em.edge(ph3, f"ss{i}.trigger")
    for i, sig in enumerate(G.OUT_NUM):
        n(f"nk{i}", "format", format="{a}:@" + sig)
        em.edge("row.value", f"nk{i}.a")
        n(f"ns{i}", "atrium.map.set", name="hNum")
        em.edge(f"nk{i}.out", f"ns{i}.key")
        em.edge(f"world.{sig}", f"ns{i}.value")
        em.edge(ph3, f"ns{i}.trigger")
    return em.text()


def write_harness(out: Path, rows: list[dict], driver_text: str) -> int:
    (out / "flows").mkdir(parents=True)
    (out / "data").mkdir()
    shutil.copyfile(G.FLOW, out / "flows" / "d01_debate_engine.xtflow")
    (out / "flows" / "driver.xtflow").write_text(driver_text, encoding="utf-8", newline="\n")
    tables = {}
    for name, rel in G.TABLES.items():
        shutil.copyfile(ROOT / rel, out / "data" / f"{name}.json")
        tables[name] = f"data/{name}.json"
    (out / "data" / "hIn.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    tables["hIn"] = "data/hIn.json"
    game = {
        "game": 1, "xtatrium": "0.4", "name": "sherefox-d01-debate-harness",
        "stepSeconds": 0.016666666666666666, "gravity": [0, 0], "collisionCategories": [],
        "signals": G.SIGNALS, "input": {"actions": {}, "axes": []},
        "flows": ["flows/driver.xtflow", "flows/d01_debate_engine.xtflow"],
        "tables": tables,
        "collections": {**G.COLLECTIONS,
                        "hNum": {"kind": "map", "type": "number", "capacity": 65536},
                        "hStr": {"kind": "map", "type": "string", "capacity": 8192},
                        "hList": {"kind": "list", "type": "string", "capacity": 65536}},
    }
    (out / "game.json").write_text(json.dumps(game, ensure_ascii=False, indent=1), encoding="utf-8")
    return H_PERIOD * (len(rows) + 1)


# --------------------------------------------------------------------------------------------- compare

def parse_dump(colls: dict) -> tuple[dict, dict]:
    """-> (maps[row][map] = {key: value}, lists[row][coll] = [items]) plus strings in maps[row]['@str']."""
    maps: dict = {}
    for e in colls["hNum"]["entries"]:
        row, rest = e["key"].split(":", 1)
        if rest.startswith("@"):
            maps.setdefault(int(row), {}).setdefault("@num", {})[rest[1:]] = e["value"]
            continue
        mp, key = rest.split(":", 1)
        maps.setdefault(int(row), {}).setdefault(mp, {})[key] = e["value"]
    for e in colls["hStr"]["entries"]:
        row, sig = e["key"].split(":", 1)
        maps.setdefault(int(row), {}).setdefault("@str", {})[sig] = e["value"]
    lists: dict = {}
    for item in colls["hList"]["items"]:
        row, coll, val = item.split("#", 2)
        lists.setdefault(int(row), {}).setdefault(coll, []).append(val)
    return maps, lists


def first_diff(want: dict, got: dict) -> str | None:
    for k, v in want.items():
        if got.get(k) != v:
            return f"{k}: expected {v!r}, got {got.get(k)!r}"
    return None


def check_row(s, ev_before, events, dec, m: dict, lists: dict, strs: dict, nums: dict) -> str | None:
    st = m.get("d1State")
    if not st:
        return "no state snapshot"
    want, got = ref_view(s), engine_view(st)
    got["record"] = lists.get("d1Record", [])
    err = first_diff(want, got)
    if err:
        return "state " + err
    mirrors = {"d1PChain": [n.claim for n in s.player_chain], "d1OChain": [n.card for n in s.opp_chain],
               "d1Hand": list(s.hand), "d1Knocked": list(s.knocked)}
    for coll, v in mirrors.items():
        if lists.get(coll, []) != v:
            return f"list {coll}: expected {v!r}, got {lists.get(coll, [])!r}"
    if sorted(lists.get("d1Known", [])) != sorted(s.known):
        return f"list d1Known: expected {sorted(s.known)!r}, got {sorted(lists.get('d1Known', []))!r}"
    if events is not None:
        want_ev = ref_records(events, ev_before)
        got_ev = lists.get("d1Events", [])
        if got_ev != want_ev:
            for k in range(max(len(got_ev), len(want_ev))):
                a = want_ev[k] if k < len(want_ev) else "<none>"
                b = got_ev[k] if k < len(got_ev) else "<none>"
                if a != b:
                    return f"event {k + 1}: expected {a!r}, got {b!r}"
    if not s.outcome:
        ids, flags = ref_claims(s)
        if lists.get("d1ClaimList", []) != ids:
            return f"claim list: expected {ids!r}, got {lists.get('d1ClaimList', [])!r}"
        vd = K.void_rows(s)     # E8: refuted claims the picker greys out
        if lists.get("d1ClaimVoid", []) != vd:
            return f"void claims: expected {vd!r}, got {lists.get('d1ClaimVoid', [])!r}"
        for cid, (soph, red, stand) in flags.items():
            g_ = (bool(m["d1ClaimSoph"].get(cid)), bool(m["d1ClaimCrack"].get(cid)),
                  bool(m["d1ClaimStand"].get(cid)))
            if g_ != (soph, red, stand):
                return f"claim view {cid}: expected soph/crack/standing {(soph, red, stand)}, got {g_}"
        wd, gd = ref_decision(dec), engine_decision(st)
        err = first_diff(wd, gd)
        if err:
            return "decision " + err
        if strs.get("d1TellAction") != wd["action"]:
            return f"output d1TellAction: expected {wd['action']!r}, got {strs.get('d1TellAction')!r}"
        if strs.get("d1TellCard") != (wd["tell_card"] or ""):
            return f"output d1TellCard: expected {wd['tell_card']!r}, got {strs.get('d1TellCard')!r}"
    else:
        err = first_diff(ref_result(s), engine_result(st, lists))
        if err:
            return "result " + err
        if strs.get("d1Outcome") != s.outcome or nums.get("d1Grade") != s.grade:
            return "outputs d1Outcome / d1Grade"
        if nums.get("d1Privates") != s.privates:
            return "output d1Privates"
        fav = dict(RS.compute(s).favour)
        for w in G.FAV_WHO:
            if nums.get(G.fav_signal(w)) != fav.get(w, 0):
                return f"output {G.fav_signal(w)}: expected {fav.get(w, 0)}, got {nums.get(G.fav_signal(w))}"
    if nums.get("d1PlayerHp") != s.player_hp or nums.get("d1Round") != s.round:
        return "outputs d1PlayerHp / d1Round"
    return None


def compare(debate: Debate, index, maps, lists) -> tuple[int, str | None]:
    rows = [(i, r) for d, i, r in index if d is debate]
    for i, row in rows:
        m, li = maps.get(row, {}), lists.get(row, {})
        strs, nums = m.get("@str", {}), m.get("@num", {})
        if i < 0:
            err = check_row(debate.start_state, None, None, debate.start_decision, m, li, strs, nums)
            if err:
                return 0, err
            continue
        pa, oa, before, after, ev, dec = debate.steps[i]
        err = check_row(after, before, ev, dec, m, li, strs, nums)
        if err:
            if VERBOSE:
                nl = chr(10)
                err += (nl + "      expected events " + json.dumps(ref_records(ev, before), ensure_ascii=False)
                        + nl + "      engine events   " + json.dumps(li.get("d1Events", []), ensure_ascii=False))
            return i + 1, err
    return len(debate.steps), None


# --------------------------------------------------------------------------------------------- main

def main(argv: list[str]) -> int:
    seeds = int(argv[argv.index("--seeds") + 1]) if "--seeds" in argv else 4
    global VERBOSE
    verbose = VERBOSE = "--verbose" in argv
    keep = Path(argv[argv.index("--keep") + 1]) if "--keep" in argv else None
    names = [argv[i + 1] for i, a in enumerate(argv) if a == "--route"] or list(RT.ROUTES)
    t0 = time.perf_counter()
    for path, text in G.generated().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    n_nodes, n_edges = G.graph_stats()
    drv = driver()
    jobs = []  # (label, seed, debates)
    jobs.append(("routes", 1, route_debates(names)))
    if "--no-play" not in argv:
        for seed in range(1, seeds + 1):
            for lname, lo in loadouts().items():
                label = f"play seed {seed} loadout {lname}"
                jobs.append((label, seed, [play_debate(label, lo, seed)]))
                label = f"fuzz seed {seed} loadout {lname}"
                jobs.append((label, seed, [fuzz_debate(label, lo, seed)]))
    t_ref = time.perf_counter() - t0
    env = dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME)
    failed = 0
    with tempfile.TemporaryDirectory(prefix="sherefox-d01-") as tmp:
        t1 = time.perf_counter()

        def run_job(k):
            label, seed, debates = jobs[k]
            hdir = Path(tmp) / f"h{k}"
            rows, index = harness_rows(debates)
            ticks = write_harness(hdir, rows, drv)
            dump = Path(tmp) / f"dump{k}.json"
            p = subprocess.run([str(EXE), "run", "--game", str(hdir), "--ticks", str(ticks), "--seed", str(seed),
                                "--dump", str(dump)], capture_output=True, text=True, encoding="utf-8", env=env)
            out = []
            if p.returncode != 0 or not dump.exists():
                return label, f"harness run exit {p.returncode}: {p.stdout}{p.stderr}", out
            colls = json.loads(dump.read_text(encoding="utf-8"))["collections"]
            dump.unlink()
            if k != 0 or not keep:
                shutil.rmtree(hdir)
            maps, lists = parse_dump(colls)
            for d in debates:
                n, err = compare(d, index, maps, lists)
                out.append((d, n, err))
            return label, (f"stderr not empty: {p.stderr.strip()[:2000]}" if p.stderr.strip() else None), out

        results = []
        with ThreadPoolExecutor(max_workers=max(1, min(16, os.cpu_count() or 4))) as pool:
            for label, problem, out in pool.map(run_job, range(len(jobs))):
                if problem:
                    print(f"FAIL {label}: {problem}")
                    failed += 1
                results += out
        t_run = time.perf_counter() - t1
        if keep:
            if keep.exists():
                shutil.rmtree(keep)
            shutil.copytree(Path(tmp) / "h0", keep)
    print(f"engine: {n_nodes} nodes / {n_edges} edges; {len(jobs)} harness runs; ref + generate {t_ref:.1f} s, "
          f"compile + run {t_run:.1f} s")
    for d, n, err in results:
        tag = ""
        if d.name.startswith("route "):
            name = d.name.split()[1]
            rp = RT.replay(name)
            bad = [i for i, p_ in enumerate(rp.producible) if p_ is False]
            tag = f"; ref policy cannot produce rounds {bad}" if bad else ""
        if err:
            failed += 1
            where = "start" if n == 0 else f"round {n}"
            print(f"FAIL {d.name} ({len(d.steps)} rounds{tag}): {where}: {err}")
            if verbose:
                pa, oa, before, after, ev, dec = d.steps[max(0, n - 1)] if d.steps else (None,) * 6
                print("      ref events: " + json.dumps(ev, ensure_ascii=False, default=str)[:3000])
        else:
            res = d.steps[-1][3].outcome if d.steps else None
            print(f"PASS {d.name} ({len(d.steps)} rounds, {res or 'unfinished'}{tag})")
    total = len(results)
    print(f"{total - sum(1 for _, _, e in results if e)}/{total} debates pass")
    # v2 demo 4.4: every ending line (ch §2 S08-S10) must be reached by at least one engine-checked debate (the
    # default four seeds and the routes do; a narrower run only reports it)
    seen = set()
    for d, n, err in results:
        s = d.steps[-1][3] if d.steps else None
        if s is not None and s.outcome and not err:
            e = EP.epilogue(s)
            seen.update(e.s08 + e.s09 + e.s10)
    every = [f"SCR_D01_S08_L{i:03d}" for i in range(1, 13)] + [f"SCR_D01_S09_L{i:03d}" for i in range(1, 9)]         + [f"SCR_D01_S10_L{i:03d}" for i in range(1, 10)]
    missing = [x for x in every if x not in seen]
    full_run = "--route" not in argv and "--no-play" not in argv and seeds >= 4
    print(f"ending lines reached: {len(every) - len(missing)}/{len(every)}"
          + (f" (missing {', '.join(missing)})" if missing else ""))
    if missing and full_run:
        print("FAIL ending coverage")
        failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
