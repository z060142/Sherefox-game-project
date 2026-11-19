# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generate the v2 debate engine of chapter D01 (《守靈夜消失的遺囑》): flows/d01_debate_engine.xtflow and its
derived tables under data/d01/. See docs/debate-engine-v2.md for the interface and the design.

Usage (from the project root):
    uv run tools/gen_debate_v2.py            write the flow and the tables
    uv run tools/gen_debate_v2.py --check    exit 1 if any generated file differs

Source data: ref/data/d01_debate.json and ref/data/d01_extra.json, read through the reference model's own loader
(ref/src/sherefox_ref/v2/data.py: exclusive lists and breakers merged in both directions), so the engine and the
oracle never disagree on the data. There is no second copy under data/d01/: data/d01/*.json are derived tables.

How a round is computed (docs/debate-engine-v2.md §3): the live state is the number map `d1State` (one key per
variable). A collection query reads it as it was at the start of the tick (XTAtrium 08 §8.3.2), so one round
(ref resolve_round) plus the opponent's decision for the next round (ref policy.decide) is a pure function of that
state and the round's command. The round is written below in Python over symbolic values (tools/v2trace.py):
every branch on game state runs both arms and merges with selects; every effect (event record, list mirror
operation, rng draw, map write) is recorded in program order with its path condition. `world.d1Lock` runs the
effects in that order (05 §5.4), ending with one map.set per state key.

Randomness (docs/debate-engine-v2.md §3.4): one atrium.rng.stream per draw of the policy's trace contract (ref
rng.DebateRng), reset at d1Start from `world.d1Seed` (stream k: seed * 8 + k); each is rolled at most once per
decision, at the point where ref draws.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "ref" / "src"))

from v2trace import T, N, S, Emitter  # noqa: E402
from sherefox_ref.v2 import model as M  # noqa: E402
from sherefox_ref.v2.data import load_chapter  # noqa: E402

FLOW = ROOT / "flows" / "d01_debate_engine.xtflow"
DATA_OUT = ROOT / "data" / "d01"
RAW = json.loads((ROOT / "ref" / "data" / "d01_debate.json").read_text(encoding="utf-8"))

# --------------------------------------------------------------------------------------------- data

CH = load_chapter()
CLAIMS = list(CH.claims)
UNFAV = [c for c in CH.cards if CH.cards[c].kind == "unfav"]
CL = CLAIMS + [f"{M.CATCH}:{u}" for u in UNFAV]  # claim index space: claims, then 抓住他的話 per unfavourable fact
NCLAIM, NCL = len(CLAIMS), len(CL)
CK = list(CH.cards)  # card index space
NCK = len(CK)
ISS = list(CH.issues)
OA_NAMES = ["attack", "force", "rebut", "parry", "last", "none"]  # opponent codes 0..5 (ref model.OA values)
PA_NAMES = ["argue", "intercept", "dismantle", "stall", "cut", "accept", "last_stand"]  # player codes 0..6
AT, FO, RE, PR, LAST, NONE = range(6)
ARGUE, INTERCEPT, DISMANTLE, STALL, CUT, ACCEPT, LAST_STAND = range(7)
STAT = ["P", "G", "A"]
WARMUPS = list(CH.warmup)  # pass_clean / pass / fail
REASONS = ["", "confession", "zero", "second_zero", "second_ronpa", "surrender", "clean", "no_last_card",
           "dying_cut", "last_card_cut", "dying_hit", "dying", "last_card", "no_last_stand", "last_stand_failed",
           "round_limit"]
TRIGGERS = ["", "ronpa", "zero"]
FORCED = ["", "rule3", "rage", "endgame", "none"]
NOTES = ["", "full", "half", "wrong"]
PAPERS = ["", "decent", "normal", "ugly"]
BIG = 1e9


def ck(cid: str) -> str:
    """State-key suffix of a claim index entry."""
    return "C" + cid.split(":", 1)[1] if cid.startswith(M.CATCH) else cid


def card_of(cid: str):
    return CH.cards[cid]


def claim_attr(fn, catch_value):
    """Per claim index (CL) attribute list."""
    out = [fn(CH.claims[c]) for c in CLAIMS]
    out += [catch_value(u) for u in UNFAV]
    return out


C_ISSUE = claim_attr(lambda c: ISS.index(c.issue), lambda u: ISS.index(CH.cards[u].issue))
C_TRUE = claim_attr(lambda c: int(c.true), lambda u: 1)
C_PSYCARD = claim_attr(lambda c: int(c.psych_card), lambda u: 0)
C_PRIVATE = claim_attr(lambda c: int(c.private), lambda u: 0)
C_HASPSY = claim_attr(lambda c: int(c.psych is not None), lambda u: 0)
C_ONCE = claim_attr(lambda c: int(c.psych_once), lambda u: 0)
C_PSY = [claim_attr(lambda c, i=i: (c.psych[i] if c.psych else 0.0), lambda u: 0.0) for i in range(3)]
C_PSYKIND = claim_attr(lambda c: (c.psych_kind or "psych_card") if c.psych else "", lambda u: "")
K_KIND = [CH.cards[c].kind for c in CK]
K_ISSUE = [ISS.index(CH.cards[c].issue) if CH.cards[c].issue else -1 for c in CK]
K_LIE = [int(CH.cards[c].is_lie) for c in CK]
K_FACT = [int(CH.cards[c].is_fact) for c in CK]
K_UNFAV = [int(k == "unfav") for k in K_KIND]
K_PICKUP = [int(k == "pickup") for k in K_KIND]
K_KEY = [int(CH.cards[c].keystone) for c in CK]
K_FRAMES = [int(CH.cards[c].frames) for c in CK]
HAND_CARDS = [c for c in CK if K_KIND[CK.index(c)] != "last"]  # cards that can be in hand / on his chain
LIE_CARDS = [c for c in HAND_CARDS if CH.cards[c].is_lie]  # knockable, re-raisable
PICK_EV = [e for e in CH.pickup_priority if CH.evidence[e].opponent_use]
SCRIPTED_LAST = next((c for c in CH.last_card_order if not c.startswith("@")), None)
SAID = []
for _c in CH.claims.values():
    for _x in list(_c.conflicts) + list(_c.unlock):
        if _x.startswith("said:") and _x not in SAID:
            SAID.append(_x)
for _x in CH.refute_lines.values():
    if _x and _x not in SAID:
        SAID.append(_x)
KNOWN = list(CH.evidence) + list(CH.appraisals) + list(CH.optional_known) + SAID + UNFAV
REFUTE_LINES = list(CH.refute_lines)
EXCL = [[int(j in CH.claims[c].exclusive) if c in CH.claims else 0 for j in CLAIMS] for c in CL]
PRIV_WHO = sorted({w for w, _ in CH.private_favour.values()})


def kn_key(item: str) -> str:
    if item.startswith("said:"):
        return f"kn_said{SAID.index(item)}"
    return f"kn_{item}"


def _static_checks() -> None:
    named = set()
    for slot in CH.play_order:
        if slot == "@pickups":
            named |= {CH.evidence[e].opponent_use for e in CH.pickup_priority}
        elif not slot.startswith("@"):
            named.add(slot)
    for c in HAND_CARDS:
        if K_KIND[CK.index(c)] in ("lie", "fav") and c not in named:
            raise SystemExit(f"card {c} is not named by play_order (hand-order fallback not modelled)")
    if CH.last_card_order[0] != "@pickup" or SCRIPTED_LAST is None:
        raise SystemExit("last card order other than [@pickup, <card>] is not modelled")
    for c in CH.claims.values():
        for via, _ in c.opp_refute:
            if via not in CH.evidence and via not in CH.cards:
                raise SystemExit(f"refute via {via}: unknown")


_static_checks()

# --------------------------------------------------------------------------------------------- interface

SIGNALS: dict[str, dict] = {
    # inputs (written by the debate UI before the pulse; the loadout collections a tick before d1Start)
    "d1Start": {"type": "pulse"},
    "d1Lock": {"type": "pulse"},
    "d1Warmup": {"type": "string", "initial": "pass"},
    "d1CmdKind": {"type": "string", "initial": ""},
    "d1CmdClaim": {"type": "string", "initial": ""},
    "d1CmdTarget": {"type": "string", "initial": ""},
    "d1CmdGuard": {"type": "number", "initial": 0},
    "d1OppAct": {"type": "string", "initial": ""},
    "d1OppCard": {"type": "string", "initial": ""},
    "d1Seed": {"type": "number", "initial": 0},
}
OUT_NUM = ["d1Round", "d1PlayerHp", "d1PlayerMax", "d1OppHp", "d1OppMax", "d1PCombo", "d1OCombo", "d1Hachiku",
           "d1Broken", "d1BrokenUntil", "d1Shisshu", "d1PsychP", "d1PsychG", "d1PsychA", "d1PsychEndP",
           "d1PsychEndG", "d1PsychEndA", "d1OverP", "d1OverG", "d1OverA", "d1ThreshP", "d1ThreshG", "d1ThreshA",
           "d1Cracks", "d1Denials", "d1GuardUsed", "d1Dying", "d1LastCardUsed", "d1PlayerLocked", "d1RoundLimit",
           "d1Grade", "d1Truth", "d1RepDelta", "d1RepAfter", "d1NextStartHp", "d1TellPartial", "d1TellRule",
           "d1HandCount"]
OUT_STR = ["d1Phase", "d1CatchCard", "d1Endgame", "d1LastCard", "d1Outcome", "d1EndReason", "d1Note", "d1Paper",
           "d1TellClarity", "d1TellShown1", "d1TellShown2", "d1TellStar", "d1TellCard", "d1TellForced",
           "d1TellAction"]
for _n in OUT_NUM:
    SIGNALS[_n] = {"type": "number", "initial": 0}
for _n in OUT_STR:
    SIGNALS[_n] = {"type": "string", "initial": ""}

COLLECTIONS = {
    "d1State": {"kind": "map", "type": "number", "capacity": 1024},
    "d1Events": {"kind": "list", "type": "string", "capacity": 512},
    "d1PChain": {"kind": "list", "type": "string", "capacity": 64},
    "d1OChain": {"kind": "list", "type": "string", "capacity": 64},
    "d1Hand": {"kind": "list", "type": "string", "capacity": 64},
    "d1Knocked": {"kind": "list", "type": "string", "capacity": 64},
    "d1Known": {"kind": "list", "type": "string", "capacity": 128, "unique": True},
    "d1Record": {"kind": "list", "type": "string", "capacity": 128},
    "d1ClaimList": {"kind": "list", "type": "string", "capacity": 64},
    "d1ClaimSoph": {"kind": "map", "type": "number", "capacity": 64},
    "d1ClaimCrack": {"kind": "map", "type": "number", "capacity": 64},
    "d1ClaimStand": {"kind": "map", "type": "number", "capacity": 64},
    "d1Rep": {"kind": "list", "type": "string", "capacity": 16},
    "d1Favour": {"kind": "list", "type": "string", "capacity": 16},
    # loadout inputs (written by the UI / harness)
    "d1Carry": {"kind": "list", "type": "string", "capacity": 32, "unique": True},
    "d1Appraised": {"kind": "list", "type": "string", "capacity": 32, "unique": True},
    "d1Notes": {"kind": "list", "type": "string", "capacity": 32, "unique": True},
}
ENGINE_LISTS = ["d1Events", "d1PChain", "d1OChain", "d1Hand", "d1Knocked", "d1Known", "d1Record", "d1ClaimList",
                "d1Rep", "d1Favour"]

# --------------------------------------------------------------------------------------------- tables


def derive_tables() -> dict[str, list[dict]]:
    raw_claims = {c["id"]: c for c in RAW["claims"]}
    raw_cards = {c["id"]: c for c in RAW["opponent"]["cards"]}
    claims = []
    for i, cid in enumerate(CL):
        if cid in CH.claims:
            c = CH.claims[cid]
            loc = raw_claims[cid].get("loc", {})
            claims.append({"id": cid, "idx": i, "evidence": c.evidence, "issue": c.issue, "true": int(c.true),
                           "psychCard": int(c.psych_card), "private": int(c.private), "catch": 0,
                           "card": "", "label": loc.get("label", ""), "line": loc.get("line", "")})
        else:
            u = cid.split(":", 1)[1]
            loc = raw_cards[u].get("loc", {})
            claims.append({"id": cid, "idx": i, "evidence": "", "issue": CH.cards[u].issue, "true": 1,
                           "psychCard": 0, "private": 0, "catch": 1, "card": u, "label": loc.get("catch", ""),
                           "line": loc.get("catch", "")})
    cards = []
    for i, cid in enumerate(CK):
        cd = CH.cards[cid]
        loc = raw_cards[cid].get("loc", {})
        cards.append({"id": cid, "idx": i, "kind": cd.kind, "issue": cd.issue or "", "lie": int(cd.is_lie),
                      "fact": int(cd.is_fact), "keystone": int(cd.keystone), "frames": int(cd.frames),
                      "source": cd.source or "",
                      **{k: loc.get(k, "") for k in ("label", "state", "push", "retract", "down", "tell", "catch")}})
    evidence = [{"id": e.id, "appraisal": e.appraisal or "", "opponentUse": e.opponent_use or "", "key": int(e.key),
                 "psychCard": int(e.psych_card)} for e in CH.evidence.values()]
    codes = [{"id": n, "side": "opponent", "code": i} for i, n in enumerate(OA_NAMES)]
    codes += [{"id": n, "side": "player", "code": i} for i, n in enumerate(PA_NAMES)]
    warm = [{"id": k, "inspector": v["inspector"], "appraisalLimit": v["appraisal_limit"]} for k, v in CH.warmup.items()]
    known = [{"id": k, "key": kn_key(k)} for k in KNOWN]
    refute = [{"id": k, "reveals": v or ""} for k, v in CH.refute_lines.items()]
    return {"d1Claim": claims, "d1Card": cards, "d1Evidence": evidence, "d1Code": codes, "d1Warmup": warm,
            "d1KnownItem": known, "d1Refute": refute}


TABLES = {n: f"data/d01/{n}.json" for n in ("d1Claim", "d1Card", "d1Evidence", "d1Code", "d1Warmup", "d1KnownItem",
                                            "d1Refute")}

# --------------------------------------------------------------------------------------------- state keys

SCALARS = {
    "act": "a debate is running", "r": "round about to be played (ref State.round)",
    "php": "player credibility", "ohp": "opponent credibility", "pcb": "player combo", "ocb": "opponent combo",
    "hk": "破竹 stacks", "bu": "破防 lasts through this round (broken_until)", "ss": "失守",
    "p0": "psych P (current, after decay)", "p1": "psych G", "p2": "psych A",
    "e0": "psych P after the last round's events (psych_end)", "e1": "psych_end G", "e2": "psych_end A",
    "o0": "P over threshold (困獸)", "o1": "G over (認罪傾向)", "o2": "A over (怒氣)",
    "cr0": "P ever crossed", "cr1": "G ever crossed", "cr2": "A ever crossed",
    "cracks": "cracks c", "den": "denials", "cc": "catch card this round (card idx + 1)",
    "cn": "catch card next round", "nu": "next 立論 plays an unfavourable fact", "few": "選項所剩無幾 fired",
    "r3f": "rule ③ fired", "r3p": "rule ③ pending", "nclr": "next tell clear (打迷糊仗 baited)",
    "nir": "no-intercept round", "sstk": "stall streak", "stalls": "stalls",
    "fps": "rule ② flag: player 詭辯 last round", "fkl": "rule ① flag: lie knocked last round (card idx + 1)",
    "fhp": "rule ④ flag: hit the player last round", "gu": "援護 used", "priv": "private claims said",
    "pcu": "psych card uses", "bz": "both reached zero", "out": "outcome 0 / 1 win / 2 loss", "grade": "grade",
    "why": "end reason (REASONS)", "eg": "pending endgame round: 0 / 1 ronpa / 2 zero",
    "egc": "endgame card idx + 1", "egd": "endgame card is the dying gasp", "rdn": "ronpa done",
    "rev": "reversed (his last card hit)", "pl": "player locked (§7.5 round pending)", "lcu": "last card used",
    "rl": "reserved last card idx + 1", "h1": "his last action code + 1", "h2": "the one before + 1",
    "pcs": "player chain sequence", "ocs": "opponent chain sequence", "hs": "hand sequence",
    "rrs": "re-raise sequence", "kks": "knocked sequence", "rs": "public record length",
    "wu": "warmup result (d1Warmup row)",
    # results (meaningful once out != 0)
    "truth": "truth score %", "nfc": "distinct false claims said", "kl": "key evidence left behind",
    "rdl": "reputation delta", "rpa": "reputation after", "nhp": "next debate start credibility bonus",
    "note": "note version (NOTES)", "paper": "newspaper (PAPERS)",
}
DEC_KEYS = {
    "da": "his action code + 1 for the coming round (OA_NAMES)", "dc": "his card idx + 1 (立論/強辯/last)",
    "dcl": "tell clarity 0 clear / 1 vague", "ds1": "shown action 1 + 1 (canonical order)",
    "ds2": "shown action 2 + 1 (vague)", "dst": "★ action + 1", "dp": "partial (slip: unfavourable fact)",
    "drl": "tendency rule that applied", "dfo": "forced (FORCED)",
    "dtc": "card shown in the tell idx + 1 (vague: the card he would say if he speaks, 00_core_rules §15〔M2〕)",
}


def state_keys() -> list[str]:
    keys = list(SCALARS) + list(DEC_KEYS)
    for c in CL:
        keys += [f"pc_{ck(c)}", f"pk_{ck(c)}"]
    for c in CLAIMS:
        keys += [f"kc_{c}", f"sd_{c}"]
        cl = CH.claims[c]
        if cl.opp_refute:
            keys.append(f"vd_{c}")
        if cl.psych is not None and cl.psych_once:
            keys.append(f"pu_{c}")
        if c in CH.private_favour:
            keys.append(f"sn_{c}")
    for c in HAND_CARDS:
        keys += [f"hd_{c}", f"oc_{c}"]
    for c in LIE_CARDS:
        keys += [f"rr_{c}", f"kk_{c}"]
    keys += [kn_key(k) for k in KNOWN]
    keys += [f"car_{e}" for e in CH.evidence]
    keys += [f"pe_{e}" for e in PICK_EV]
    return keys


KEYS = state_keys()
SCRATCH = ["rd_patt", "rd_oatt", "rd_rok", "rd_rb", "rd_hurt", "rd_gt", "rd_key", "rd_pdmg", "rd_odmg", "rd_oev",
           "rd_shn", "rd_kl", "rd_ps", "rd_nclr", "rd_done"] + [f"d_{k}" for k in DEC_KEYS]

# --------------------------------------------------------------------------------------------- tracing helpers

st: dict = {}


def g(k):
    return st[k]


def put(k, v):
    st[k] = T.c(v) if not isinstance(v, N) else v


def inc(k, by=1):
    put(k, g(k) + by)


def ev(*parts):
    T.effect("add", coll="d1Events", value=T.fmt(*parts))


def eff_if(cond, kind, **d):
    pc0 = T.pc
    T.pc = T.AND(pc0, cond)
    T.effect(kind, **d)
    T.pc = pc0


def cls(i) -> S:
    return T.slk(CL, T.MAX(0, T.MIN(NCL - 1, i)))


def cks(i) -> S:
    return T.slk(CK, T.MAX(0, T.MIN(NCK - 1, i)))


def lk(values, i):
    return T.lk(values, T.MAX(0, T.MIN(len(values) - 1, i)))


_uid = [0]


def uid(p: str) -> str:
    _uid[0] += 1
    return f"{p}{_uid[0]}"


def find(table: str, column: str, value_port: str) -> N:
    nid = T.raw_node(uid("f"), "atrium.table.find", table=table, column=column)
    T.raw_edge(value_port, f"{nid}.value")
    return T.port(f"{nid}.row")


def str_is(port: str, text: str) -> N:
    """number 0/1 = (string at port == text)."""
    cid = T.raw_node(uid("q"), "compare", op="eq")
    T.raw_edge(port, f"{cid}.a")
    T.raw_edge(T.sc(text), f"{cid}.b")
    sid = T.raw_node(uid("qs"), "select")
    T.raw_edge(f"{cid}.out", f"{sid}.cond")
    T.raw_edge(T.c(1), f"{sid}.a")
    T.raw_edge(T.c(0), f"{sid}.b")
    return T.port(f"{sid}.out", isbool=True)


def contains(coll: str, item: str) -> N:
    nid = T.raw_node(uid("lc"), "atrium.coll.contains", name=coll)
    T.raw_edge(T.sc(item), f"{nid}.value")
    sid = T.raw_node(uid("lcs"), "select")
    T.raw_edge(f"{nid}.has", f"{sid}.cond")
    T.raw_edge(T.c(1), f"{sid}.a")
    T.raw_edge(T.c(0), f"{sid}.b")
    return T.port(f"{sid}.out", isbool=True)


def foreach_sub(coll: str, kind: str, table: str | None = None, cond_fn=None) -> None:
    """One `kind|item` record per element of list `coll` as it is at this point (atrium.coll.forEach), filtered by
    cond_fn(row of the item in `table`)."""
    nid = T.raw_node(uid("fe"), "atrium.coll.forEach", name=coll)
    rec = T.fmt(kind, T.sport(f"{nid}.item"))
    add = T.raw_node(uid("fa"), "atrium.coll.add", name="d1Events")
    T.raw_edge(rec, f"{add}.value")
    if cond_fn is None:
        T.raw_edge(f"{nid}.each", f"{add}.trigger")
    else:
        fid = T.raw_node(uid("ff"), "atrium.table.find", table=table, column="id")
        T.raw_edge(f"{nid}.item", f"{fid}.value")
        row = T.port(f"{fid}.row")
        gid = T.raw_node(uid("fg"), "atrium.gate")
        T.raw_edge(cond_fn(T.MAX(0, row)), f"{gid}.cond")
        T.raw_edge(f"{nid}.each", f"{gid}.trigger")
        T.raw_edge(f"{gid}.pass", f"{add}.trigger")
    T.effect("pulse", inputs=[f"{nid}.trigger"])


DRAWS = ("tendency", "clarity", "base", "slip", "decoy")  # ref rng.DRAWS (the policy's trace contract)
SEED_STRIDE = 8  # ref rng.SEED_STRIDE: stream k is seeded with seed * 8 + k
STREAM_FROM = "rsFrom"  # toggle: true while d1Start's cascade runs (picks the entry's n for each stream)
_draw_n: dict = {}  # draw name -> {entry prefix: n}


def stream_id(name: str) -> str:
    return f"rs_{name}"


def make_streams() -> None:
    """The debate's random streams (ref rng.DebateRng): one atrium.rng.stream per draw, seeded from world.d1Seed."""
    _draw_n.clear()
    seed = T.port("world.d1Seed")
    for k, name in enumerate(DRAWS, start=1):
        nid = T.raw_node(stream_id(name), "atrium.rng.stream")
        T.raw_edge(seed * SEED_STRIDE + k, f"{nid}.seed")
    T.raw_node(STREAM_FROM, "toggle")
    sid = T.raw_node(STREAM_FROM + "N", "select")
    T.raw_edge(f"{STREAM_FROM}.value", f"{sid}.cond")
    T.raw_edge(T.c(1), f"{sid}.a")
    T.raw_edge(T.c(0), f"{sid}.b")


def reset_streams() -> None:
    """d1Start: reseed every stream from world.d1Seed (the node reads its seed input on reset)."""
    T.effect("pulse", inputs=[f"{stream_id(name)}.reset" for name in DRAWS])


def wire_stream_n() -> None:
    """Each stream's n: a constant when both entries roll it with the same constant (the param), else the input
    wired to (d1Start running ? n of the start entry : n of the lock entry)."""
    from_start = T.port(f"{STREAM_FROM}N.out", isbool=True)
    for name in DRAWS:
        ns = _draw_n.get(name, {})
        if not ns:
            continue
        vals = list(ns.values())
        if all(v.const for v in vals) and len({v.v for v in vals}) == 1:
            T.raw[[r["id"] for r in T.raw].index(stream_id(name))]["params"] = {"n": vals[0].v}
            continue
        n_start = ns.get("dS", ns.get("dL"))
        n_lock = ns.get("dL", n_start)
        T.raw_edge(T.SEL(from_start, n_start, n_lock), f"{stream_id(name)}.n")


def draw(prefix: str, name: str, n) -> N:
    """ref roll(n) of draw `name` at this point (guarded by the path condition): the stream's `roll`; its value is
    the unbiased integer in [0, n). Each stream rolls at most once per entry."""
    n = T.c(n)
    if prefix in _draw_n.setdefault(name, {}):
        raise ValueError(f"draw {name} twice in entry {prefix}")
    _draw_n[name][prefix] = n
    T.effect("pulse", inputs=[f"{stream_id(name)}.roll"])
    return T.port(f"{stream_id(name)}.value")


def fold_or(xs):
    return T.OR(*xs) if xs else T.c(0)


def fold_sum(xs):
    out = T.c(0)
    first = True
    for x in xs:
        out = x if first else out + x
        first = False
    return out


def fold_min(xs):
    out = T.c(BIG)
    for x in xs:
        out = T.MIN(out, x)
    return out


def argfirst(conds_idx):
    """conds_idx: list of (cond, idx); idx of the first true cond, else -1."""
    out = T.c(-1)
    for c, i in reversed(conds_idx):
        out = T.SEL(c, i, out)
    return out


def cm(c):
    """combo_mult (ref resolve.combo_mult)."""
    return T.c(1.0) + T.c(M.COMBO_STEP) * (T.MIN(c, M.COMBO_CAP) - 1)


# ---- claim views (ref known.py)

def soph_of(i: int) -> N:
    cid = CL[i]
    if cid not in CH.claims:
        return T.c(0)
    c = CH.claims[cid]
    if c.psych_card:
        return T.c(1)
    return fold_or([g(kn_key(k)) for k in c.conflicts if k in KNOWN])


def red_of(i: int) -> N:
    cid = CL[i]
    if cid not in CH.claims:
        return T.c(0)
    return fold_or([T.GT(g(f"sd_{j}"), 0) for j in CH.claims[cid].exclusive])


def avail_of(i: int) -> N:
    c = CH.claims[CL[i]]
    parts = [g(f"car_{c.evidence}")] + [g(kn_key(u)) for u in c.unlock if u in KNOWN]
    if any(u not in KNOWN for u in c.unlock):
        return T.c(0)
    if c.opp_refute:
        parts.append(T.NOT(g(f"vd_{c.id}")))
    return T.AND(*parts)


def vec(prefix: str, ids, idx_of) -> list:
    return [(idx_of(x), g(f"{prefix}_{x}")) for x in ids]


def card_vec(prefix: str, cards) -> list:
    return [(CK.index(c), g(f"{prefix}_{c}")) for c in cards]


def claim_vec(prefix: str, claims) -> list:
    return [(CL.index(c), g(f"{prefix}_{ck(c)}")) for c in claims]


def breaks_lk(ci: N, card: int) -> N:
    """claim index ci is in breakers[card] (ref Chapter.breakers)."""
    cid = CK[card]
    return lk([int(c in CH.breakers.get(cid, ())) for c in CL], ci)


def breaks_dyn(ci: N, card: N) -> N:
    return T.PICK(card, [(k, breaks_lk(ci, k)) for k in range(NCK)])


def set_card(prefix: str, cards, idx: N, value) -> None:
    for c in cards:
        k = f"{prefix}_{c}"
        put(k, T.SEL(T.EQ(idx, CK.index(c)), value, g(k)))


def set_claim(prefix: str, claims, idx: N, value) -> None:
    for c in claims:
        k = f"{prefix}_{ck(c)}"
        put(k, T.SEL(T.EQ(idx, CL.index(c)), value, g(k)))


# --------------------------------------------------------------------------------------------- the round

class Cmd:
    def __init__(self, pk, ci, ti, guard, ok, ocard):
        self.pk, self.ci, self.ti, self.guard, self.ok, self.oc = pk, ci, ti, guard, ok, ocard


def hurt_player(amount, cause: str) -> N:
    amount = T.c(amount)
    if cause in ("argument", "exposed", "refuted", "last_card", "dying"):  # resolve.OPP_DEALT
        amount = T.SEL(R.ss0, amount * M.SHISSHU_MULT, amount)
    put("php", g("php") - amount)
    ev("pDmg", amount, cause, g("php"))
    return amount


def hurt_opp(amount, cause: str) -> None:
    put("ohp", g("ohp") - amount)
    ev("oDmg", T.c(amount), cause, g("ohp"))


def heal_opp() -> None:
    def void():
        ev("healVoid")

    def heal():
        before = g("ohp")
        put("ohp", T.MIN(CH.opp_max_hp, g("ohp") + M.HEAL))
        ev("oHeal", before, g("ohp"))
    T.when(g("o0"), void, heal)


def reraise() -> None:
    kks = [(c, g(f"kk_{c}")) for c in LIE_CARDS]

    def go():
        fkl = g("fkl")
        in_kn = fold_or([T.AND(T.EQ(fkl, CK.index(c) + 1), T.GT(v, 0)) for c, v in kks])
        mn = fold_min([T.SEL(T.GT(v, 0), v, BIG) for c, v in kks])
        oldest = argfirst([(T.AND(T.GT(v, 0), T.EQ(v, mn)), CK.index(c)) for c, v in kks])
        cid = T.SEL(in_kn, fkl - 1, oldest)
        set_card("kk", LIE_CARDS, cid, 0)
        set_card("hd", LIE_CARDS, cid, g("hs") + 1)
        set_card("rr", LIE_CARDS, cid, g("rrs") + 1)
        inc("hs")
        inc("rrs")
        T.effect("remove", coll="d1Knocked", value=cks(cid))
        T.effect("add", coll="d1Hand", value=cks(cid))
        ev("reraise", cks(cid))
    T.when(fold_or([T.GT(v, 0) for _, v in kks]), go)


def remove_from_hand(card: N) -> None:
    set_card("hd", HAND_CARDS, card, 0)
    set_card("rr", LIE_CARDS, card, 0)
    T.effect("remove", coll="d1Hand", value=cks(card))


def pev(name, deltas) -> None:
    """append to rd.p_events (guarded list, merged by Tracer.when)."""
    name = T.s(name)
    st["_lpev"] = st["_lpev"] + ((T.c(1), name, *[T.c(d) for d in deltas]),)


def psych_add(name, deltas) -> None:
    for i in range(3):
        put(f"p{i}", T.MAX(0.0, T.MIN(100.0, g(f"p{i}") + deltas[i])))
    ev("psych", name, *[T.c(d) for d in deltas], g("p0"), g("p1"), g("p2"))


def set_broken(cause: str) -> None:
    put("bu", T.MAX(g("bu"), R.r0 + 1))
    ev("broken", cause, g("bu"))


def opp_attach(cmd: Cmd, factor=1.0, damage=True) -> None:
    card = cmd.oc
    remove_from_hand(card)
    inc("ocs")
    set_card("oc", HAND_CARDS, card, g("ocs"))
    T.effect("add", coll="d1OChain", value=cks(card))
    inc("ocb")
    put("rd_oatt", 1)
    put("rd_oev", 1)
    ev("oAttach", cks(card), g("ocb"))

    def unfav():
        put("cn", card + 1)

    def normal():
        if not damage:
            return
        d = T.c(CH.opp_base_damage) * cm(g("ocb"))
        d1 = d * M.FORCE_MULT
        d2 = T.SEL(g("o2"), d1 * M.RAGE_FORCE_MULT, d1)
        d = T.SEL(T.EQ(cmd.ok, FO), d2, d)
        d = d * factor
        od = hurt_player(d, "argument")
        put("rd_odmg", od)
        put("rd_hurt", T.OR(g("rd_hurt"), T.GT(od, 0)))
    T.when(lk(K_UNFAV, card), unfav, normal)


def player_attach(cmd: Cmd, soph: N, crack: N) -> None:
    ci = cmd.ci
    catch = T.GE(ci, NCLAIM)
    issue = lk(C_ISSUE, ci)
    base = T.SEL(catch, M.BASE_CATCH, T.SEL(soph, M.BASE_SOPH, M.BASE_PROPER))
    pcs = [(i, g(f"pc_{ck(c)}")) for i, c in enumerate(CL)]
    mx = T.c(0)
    for _, v in pcs:
        mx = T.MAX(mx, v)
    prev = argfirst([(T.AND(T.GT(v, 0), T.EQ(v, mx)), i) for i, v in pcs])
    prev_issue = lk(C_ISSUE, prev)
    pair = fold_or([T.AND(T.EQ(prev, CL.index(a)), T.EQ(ci, CL.index(b))) for a, b in sorted(CH.continuations)])
    inc("pcs")
    set_claim("pc", CL, ci, g("pcs"))
    set_claim("pk", CL, ci, crack)
    T.effect("add", coll="d1PChain", value=cls(ci))
    inc("pcb")
    put("rd_patt", 1)
    cmv = cm(g("pcb"))
    d = base * cmv
    cont = T.AND(T.GT(mx, 0), T.OR(T.EQ(prev_issue, issue), pair))
    d = T.SEL(cont, d * M.CONTINUATION, d)
    kcv = T.PICK(ci, [(CL.index(c), g(f"kc_{c}")) for c in CLAIMS])
    rer = T.AND(T.NOT(catch), kcv)
    d = T.SEL(rer, d * M.RERAISE_MULT, d)
    h = T.c(1.0) + T.c(M.HACHIKU_STEP) * R.hk0
    d = d * h
    d = T.SEL(R.broken0, d * M.BROKEN_BONUS, d)
    put("rd_pdmg", d)
    ev("pAttach", cls(ci), g("pcb"), d, base, cmv, T.SEL(cont, M.CONTINUATION, 1), T.SEL(rer, M.RERAISE_MULT, 1), h,
       T.SEL(R.broken0, M.BROKEN_BONUS, 1), T.ssel(cont, cls(prev), ""))
    hurt_opp(d, "argument")


def claim_effect(cmd: Cmd) -> None:
    ci = cmd.ci
    used = T.PICK(ci, [(CL.index(c), g(f"pu_{c}")) for c in CLAIMS if f"pu_{c}" in st])
    fire = T.AND(lk(C_HASPSY, ci), T.NOT(T.AND(lk(C_ONCE, ci), used)))

    def go():
        for c in CLAIMS:
            if f"pu_{c}" in st:
                put(f"pu_{c}", T.SEL(T.EQ(ci, CL.index(c)), 1, g(f"pu_{c}")))
        pev(T.slk(C_PSYKIND, T.MAX(0, T.MIN(NCL - 1, ci))), [lk(C_PSY[i], ci) for i in range(3)])
    T.when(fire, go)


def record(cmd: Cmd, use: str, soph, crack, true) -> None:
    ci = cmd.ci
    for c in CLAIMS:
        k = f"sd_{c}"
        put(k, T.SEL(T.AND(T.EQ(ci, CL.index(c)), T.EQ(g(k), 0)), g("rs") + 1, g(k)))
        if f"sn_{c}" in st:
            put(f"sn_{c}", T.SEL(T.EQ(ci, CL.index(c)), g(f"sn_{c}") + 1, g(f"sn_{c}")))
    inc("rs")
    T.effect("add", coll="d1Record", value=T.fmt(R.r0, cls(ci), use, soph, crack, true))


def use_claim(cmd: Cmd, use: str):
    """ref resolve._use_claim (validation left to the UI). Returns (soph, crack)."""
    ci = cmd.ci
    soph = T.PICK(ci, [(i, soph_of(i)) for i in range(NCLAIM)])
    red = T.PICK(ci, [(i, red_of(i)) for i in range(NCLAIM)])
    psyc = lk(C_PSYCARD, ci)
    true = lk(C_TRUE, ci)
    crack = T.OR(T.AND(soph, T.NOT(psyc)), red)

    def red_branch():
        hurt_player(M.CONTRADICTION, "contradiction")
        cand = [(T.AND(lk([EXCL[i][j] for i in range(NCL)], ci), T.GT(g(f"sd_{c}"), 0)), g(f"sd_{c}"), j)
                for j, c in enumerate(CLAIMS)]
        mn = fold_min([T.SEL(cnd, v, BIG) for cnd, v, _ in cand])
        with_ = argfirst([(T.AND(cnd, T.EQ(v, mn)), j) for cnd, v, j in cand])
        rems = []
        for j, c in enumerate(CLAIMS):
            rem = T.AND(lk([EXCL[i][j] for i in range(NCL)], ci), T.GT(g(f"pc_{c}"), 0))
            rems.append((rem, c))
            put(f"pc_{c}", T.SEL(rem, 0, g(f"pc_{c}")))
            put(f"kc_{c}", T.SEL(rem, 1, g(f"kc_{c}")))
        ev("redCrack", cls(ci), T.ssel(T.GE(with_, 0), cls(with_), ""))
        foreach_sub("d1PChain", "redCrackRemoved", "d1Claim",
                    lambda row: T.PICK(ci, [(i, lk(EXCL[i] + [0] * (NCL - NCLAIM), row)) for i in range(NCLAIM)]))
        for rem, c in rems:
            eff_if(rem, "remove", coll="d1PChain", value=T.sc(c))
    T.when(red, red_branch)
    put("cracks", g("cracks") + crack)
    record(cmd, use, soph, crack, true)
    notc = T.LT(ci, NCLAIM)
    put("pcu", g("pcu") + T.AND(notc, psyc))
    put("priv", g("priv") + T.AND(notc, lk(C_PRIVATE, ci)))
    put("rd_ps", soph)
    return soph, crack


def knock(card: N, soph) -> None:
    """A lie goes to the knocked list (intercept / dismantle)."""
    inc("kks")
    set_card("kk", LIE_CARDS, card, g("kks"))
    T.effect("add", coll="d1Knocked", value=cks(card))
    put("rd_kl", card + 1)
    tab = CH.psych_events
    pev(T.ssel(soph, "lie_down_soph", "lie_down_proper"),
        [T.SEL(soph, tab["lie_down_soph"][i], tab["lie_down_proper"][i]) for i in range(3)])


def deny() -> None:
    inc("den")
    pev("fact_down_soph", CH.psych_events["fact_down_soph"])


def refuting_line(ci: N) -> N:
    """ref resolve._refuting_line: refute line index + 1, 0 none."""
    items = []
    for i, cid in enumerate(CLAIMS):
        out = T.c(0)
        for via, line in reversed(CH.claims[cid].opp_refute):
            conds = []
            if via in PICK_EV:
                conds.append(g(f"pe_{via}"))
            if via in CH.cards and via in HAND_CARDS:
                conds.append(T.GT(g(f"oc_{via}"), 0))
            out = T.SEL(fold_or(conds), REFUTE_LINES.index(line) + 1, out)
        items.append((i, out))
    return T.PICK(ci, items)


def normal_round(cmd: Cmd) -> None:
    ok, pk = cmd.ok, cmd.pk
    put("h2", g("h1"))
    put("h1", ok + 1)
    attacks = T.OR(T.EQ(ok, AT), T.EQ(ok, FO))
    T.when(attacks, lambda: put("nu", 0))
    T.when(cmd.guard, lambda: put("gu", 1))

    def stall_count():
        inc("sstk")
        inc("stalls")
    T.when(T.EQ(pk, STALL), stall_count, lambda: put("sstk", 0))

    def argue():
        soph, crack = use_claim(cmd, "argue")

        def vs_rebut():
            put("rd_rb", 1)
            line = T.SEL(soph, 0, refuting_line(cmd.ci))

            def exposed():
                hurt_player(M.EXPOSED, "exposed")
                put("pcb", 0)
                put("rd_shn", 1); put("rd_hurt", 1); put("rd_gt", 1)
                put("rd_oev", 1)
                ev("exposed", cls(cmd.ci))

            def refuted():
                hurt_player(M.REFUTED, "refuted")
                put("pcb", 0)
                set_claim("vd", [c for c in CLAIMS if CH.claims[c].opp_refute], cmd.ci, 1)
                reveals = [CH.refute_lines.get(ln) for ln in REFUTE_LINES]
                for ln, rv in zip(REFUTE_LINES, reveals):
                    if rv:
                        hit = T.EQ(line, REFUTE_LINES.index(ln) + 1)
                        put(kn_key(rv), T.OR(g(kn_key(rv)), hit))
                        eff_if(hit, "add", coll="d1Known", value=T.sc(rv))
                put("rd_shn", 1); put("rd_hurt", 1); put("rd_gt", 1)
                put("rd_oev", 1)
                ev("refuted", cls(cmd.ci), T.slk([""] + REFUTE_LINES, line),
                   T.slk([""] + [rv or "" for rv in reveals], line))

            T.when(soph, exposed, lambda: T.when(T.GT(line, 0), refuted, lambda: ev("blocked", cls(cmd.ci))))

        def vs_other():
            T.when(T.EQ(ok, PR), heal_opp)
            player_attach(cmd, soph, crack)

            def caught():
                for u in UNFAV:
                    hit = T.EQ(g("cc"), CK.index(u) + 1)
                    put(kn_key(u), T.OR(g(kn_key(u)), hit))
                    eff_if(hit, "add", coll="d1Known", value=T.sc(u))
            T.when(T.GE(cmd.ci, NCLAIM), caught)
            claim_effect(cmd)

            def no_attack():
                put("rd_rok", 1)
                reraise()
            T.when(attacks, lambda: opp_attach(cmd), no_attack)

        T.when(T.EQ(ok, RE), vs_rebut, vs_other)

    def intercept():
        soph, crack = use_claim(cmd, "intercept")
        card = cmd.oc
        c_issue = lk(C_ISSUE, cmd.ci)

        def vs_attack():
            blocked = T.EQ(g("nir"), R.r0)
            okk = T.SEL(soph, T.EQ(lk(K_ISSUE, card), c_issue), T.AND(lk(K_LIE, card), breaks_dyn(cmd.ci, card)))

            def success():
                hurt_opp(T.SEL(T.EQ(ok, FO), M.INTERCEPT_DMG + M.INTERCEPT_FORCE_EXTRA, M.INTERCEPT_DMG + 0.0),
                         "intercept")
                put("ocb", 0)
                remove_from_hand(card)
                T.when(lk(K_LIE, card), lambda: knock(card, soph), deny)
                set_broken("intercepted")
                put("rd_rok", 1)
                key = T.AND(lk(K_KEY, card), T.OR(R.broken0, T.LE(R.ohp0, M.KEY_HP_RATIO * CH.opp_max_hp)))
                put("rd_key", key)
                ev("intercept", cls(cmd.ci), cks(card), 1, key, 0)
                claim_effect(cmd)

            def fail():
                put("rd_rb", 1)
                put("rd_gt", 1)
                ev("intercept", cls(cmd.ci), cks(card), 0, 0, blocked)

                def whiff():
                    hurt_player(M.WHIFF, "whiff")
                    opp_attach(cmd)

                def fact():
                    hurt_player(M.FACT_MISS, "fact_miss")
                    opp_attach(cmd, damage=False)
                    T.when(lk(K_UNFAV, card), lambda: put("cn", 0))
                T.when(T.OR(lk(K_LIE, card), blocked, soph), whiff, fact)

            T.when(T.AND(okk, T.NOT(blocked)), success, fail)

        def vs_rebut():
            put("rd_rb", 1)
            put("rd_gt", 1)
            hurt_player(M.WHIFF, "whiff")
            hurt_opp(M.WHIFF, "whiff")
            put("rd_oev", 2)
            set_broken("rebut_whiff")

        def vs_parry():
            put("rd_rb", 1)
            put("rd_gt", 1)
            hurt_player(M.WHIFF, "whiff")
            put("nir", R.r0 + 1)
            heal_opp()
            reraise()

        T.when(attacks, vs_attack, lambda: T.when(T.EQ(ok, RE), vs_rebut, vs_parry))

    def dismantle():
        soph, crack = use_claim(cmd, "dismantle")
        ti = T.MAX(0, cmd.ti)
        c_issue = lk(C_ISSUE, cmd.ci)
        okd = T.SEL(soph, T.EQ(lk(K_ISSUE, ti), c_issue), T.AND(lk(K_LIE, ti), breaks_dyn(cmd.ci, ti)))

        def success():
            set_card("oc", HAND_CARDS, ti, 0)
            T.effect("remove", coll="d1OChain", value=cks(ti))
            hurt_opp(M.DISMANTLE_DMG, "dismantle")
            put("ocb", 0)
            T.when(lk(K_LIE, ti), lambda: knock(ti, soph), deny)
            put("rd_rok", 1)
            claim_effect(cmd)

        def fail():
            put("rd_rb", 1)
            put("rd_gt", 1)
            hurt_player(T.SEL(lk(K_FACT, ti), M.FACT_MISS, M.WHIFF), "whiff")

        T.when(okd, success, fail)
        ev("dismantle", cls(cmd.ci), cks(ti), okd)

        def vs_rebut():
            hurt_opp(M.WHIFF, "whiff")
            put("rd_oev", 2)
            set_broken("rebut_whiff")

        def vs_parry():
            heal_opp()
            reraise()
        T.when(attacks, lambda: opp_attach(cmd), lambda: T.when(T.EQ(ok, RE), vs_rebut, vs_parry))

    def stall():
        repeat = T.GE(g("sstk"), 2)
        pev("stalled", CH.psych_events["stalled"])

        def vs_attack():
            opp_attach(cmd, factor=T.SEL(repeat, 1.0, 0.5))
            put("rd_rb", 1)

        def vs_rebut():
            hurt_opp(M.WHIFF, "whiff")
            put("rd_oev", 2)

            def first():
                set_broken("rebut_whiff")
                put("rd_nclr", 1)
                put("rd_rok", 1)
            T.when(T.NOT(repeat), first)

        def vs_parry():
            heal_opp()
            reraise()
            hurt_player(M.STALEMATE, "stalemate")
            hurt_opp(M.STALEMATE, "stalemate")
        T.when(attacks, vs_attack, lambda: T.when(T.EQ(ok, RE), vs_rebut, vs_parry))
        T.when(repeat, lambda: hurt_player(M.STALL_REPEAT_EXTRA, "stall_repeat"))
        ev("stall", T.slk(OA_NAMES, T.MAX(0, T.MIN(5, ok))), repeat)

    T.when(T.EQ(pk, ARGUE), argue,
           lambda: T.when(T.EQ(pk, INTERCEPT), intercept,
                          lambda: T.when(T.EQ(pk, DISMANTLE), dismantle, stall)))

    # 援護
    def guard_saved():
        put("php", T.MAX(g("php"), R.hp0))
        put("rd_shn", 0)
        ev("guardSaved", g("php"))
    T.when(T.AND(cmd.guard, g("rd_gt")), guard_saved)

    # 破竹 / 失守
    good = T.AND(g("rd_rok"), T.NOT(g("rd_hurt")))
    before = g("hk")
    put("hk", T.SEL(good, T.MIN(M.HACHIKU_MAX, g("hk") + 1), T.SEL(g("rd_rb"), 0, g("hk"))))
    T.when(T.NE(g("hk"), before), lambda: ev("hachiku", before, g("hk")))

    def ss_off():
        put("ss", 0)
        ev("shisshu", 0)
    T.when(T.AND(g("ss"), good), ss_off)

    def ss_on():
        put("ss", 1)
        ev("shisshu", 1)
    T.when(g("rd_shn"), ss_on)

    put("nclr", g("rd_nclr"))
    put("fps", g("rd_ps"))
    put("fkl", g("rd_kl"))
    put("fhp", T.EQ(g("rd_oev"), 1))
    put("r3p", 0)
    psych_step()
    T.when(T.EQ(g("out"), 0), stance)


def psych_step() -> None:
    tab = CH.psych_events
    for item in st["_lpev"]:
        guard, name, *ds = item
        T.when(guard, lambda name=name, ds=ds: psych_add(name, ds))
    T.when(T.EQ(g("rd_oev"), 1), lambda: psych_add("hit_player", tab["hit_player"]))
    T.when(T.EQ(g("rd_oev"), 2), lambda: psych_add("own_rebut_whiff", tab["own_rebut_whiff"]))
    cnt = fold_sum([T.GT(g(f"hd_{c}"), 0) for c in HAND_CARDS if K_KIND[CK.index(c)] in ("lie", "fav", "pickup")])

    def few():
        put("few", 1)
        psych_add("few_options", tab["few_options"])
    T.when(T.AND(T.NOT(g("few")), T.LE(cnt, M.FEW_OPTIONS_AT)), few)
    thr = CH.psych_threshold
    for i in range(3):
        now = T.GE(g(f"p{i}"), thr[i])

        def crossed(i=i):
            put(f"cr{i}", 1)
            ev("crossed", STAT[i])
            T.when(T.EQ(g("eg"), 0), lambda: set_broken(f"crossed_{STAT[i]}"))
            if i == 0:
                put("nu", 1)
        T.when(T.AND(now, T.NOT(g(f"o{i}"))), crossed)
        put(f"o{i}", now)
    for i in range(3):
        put(f"e{i}", g(f"p{i}"))
    T.when(T.GE(g("p1"), 100.0), lambda: win(T.SEL(T.EQ(g("cracks"), 0), 1, 2), "confession"))


def win(grade, reason: str) -> None:
    grade = T.c(grade)
    g2 = T.SEL(g("bz"), T.MIN(4, grade + 1), grade)
    put("out", 1)
    put("grade", g2)
    put("why", REASONS.index(reason))
    put("eg", 0)
    ev("over", "win", g2, reason)


def lose(reason: str) -> None:
    put("php", T.MAX(0.0, g("php")))
    put("out", 2)
    put("grade", 5)
    put("why", REASONS.index(reason))
    put("eg", 0)
    ev("over", "loss", 5, reason)


def stance() -> None:
    need, issues = CH.ronpa_len, CH.ronpa_issues
    pchain = [(c, T.GT(g(f"pc_{ck(c)}"), 0)) for c in CL]
    plen = fold_sum([on for _, on in pchain])
    pdist = fold_sum([fold_or([on for c, on in pchain if C_ISSUE[CL.index(c)] == x]) for x in range(len(ISS))])
    ronpa = T.OR(g("rd_key"), T.AND(g("rd_patt"), T.GE(g("bu"), R.r0), T.GE(plen, need), T.GE(pdist, issues)))
    ochain = [(c, T.GT(g(f"oc_{c}"), 0)) for c in HAND_CARDS]
    olen = fold_sum([on for _, on in ochain])
    oiss = sorted({K_ISSUE[CK.index(c)] for c in HAND_CARDS})
    odist = fold_sum([fold_or([on for c, on in ochain if K_ISSUE[CK.index(c)] == x]) for x in oiss])
    rev = T.AND(R.ss0, g("rd_oatt"), T.GE(olen, need), T.GE(odist, issues))
    both = T.AND(ronpa, rev)
    pw = T.GE(g("rd_pdmg"), g("rd_odmg"))
    rev2 = T.AND(rev, T.NOT(T.AND(both, pw)))
    ron2 = T.AND(ronpa, T.NOT(T.AND(both, T.NOT(pw))))

    def reverse():
        put("php", 1.0)
        put("pcb", 0)
        put("pl", 1)
        ev("reverseRonpa")
        foreach_sub("d1OChain", "reverseRonpaNode")

    def both_zero():
        put("bz", 1)
        put("php", 1.0)
        enter_endgame("zero")

    def ronpa_():
        ev("ronpa", T.ssel(g("rd_key"), "keystone", "chain"))
        foreach_sub("d1PChain", "ronpaNode")
        enter_endgame("ronpa")

    T.when(rev2, reverse, lambda: T.when(
        T.AND(T.LE(g("php"), 0), T.LE(g("ohp"), 0)), both_zero, lambda: T.when(
            T.LE(g("php"), 0), lambda: lose("zero"), lambda: T.when(
                ron2, ronpa_, lambda: T.when(T.LE(g("ohp"), 0), lambda: enter_endgame("zero"))))))


def enter_endgame(trigger: str) -> None:
    ronpa = trigger == "ronpa"
    if ronpa:
        for c in HAND_CARDS:
            put(f"oc_{c}", 0)
        T.effect("clear", coll="d1OChain")
        put("rdn", 1)
    put("ocb", 0)
    hp_end = 1.0 if ronpa else 0.0
    c = g("cracks")
    ev("endgame", trigger, c)
    tcode = TRIGGERS.index(trigger)
    any_picked = fold_or([g(f"pe_{e}") for e in PICK_EV])

    def second():
        put("ohp", hp_end)
        win(T.SEL(g("rdn"), 3, 4), f"second_{trigger}")

    def surrender():
        put("ohp", hp_end)
        win(T.SEL(T.EQ(c, 0), 1, 2) if ronpa else 4, "surrender")

    def dying():
        put("ohp", 1.0)
        put("eg", tcode)
        put("egc", CK.index(SCRIPTED_LAST) + 1)
        put("egd", 1)

    def last():
        put("ohp", 1.0)
        put("eg", tcode)
        put("egc", T.SEL(T.GT(g("rl"), 0), g("rl"), CK.index(SCRIPTED_LAST) + 1))
        put("egd", 0)

    T.when(g("lcu"), second, lambda: T.when(g("o1"), surrender, lambda: T.when(
        T.AND(T.EQ(c, 0), T.NOT(any_picked)), dying, last)))


def endgame_round(cmd: Cmd) -> None:
    card = g("egc") - 1
    put("h2", g("h1"))
    put("h1", LAST + 1)
    c0 = g("cracks")
    ronpa = T.EQ(g("eg"), 1)
    dyingv = g("egd")
    cutting = T.EQ(cmd.pk, CUT)
    brk = T.AND(cutting, breaks_dyn(cmd.ci, card))

    def cut():
        use_claim(cmd, "cut")

        def ok():
            ev("lastCard", cks(card), 1, 0, 0, 0)
            T.when(dyingv, lambda: win(T.SEL(ronpa, 1, 4), "dying_cut"),
                   lambda: win(T.SEL(ronpa, T.SEL(T.EQ(c0, 0), 1, 2), 4), "last_card_cut"))
            for i in range(3):
                put(f"e{i}", g(f"p{i}"))
        T.when(brk, ok)
    T.when(cutting, cut)

    def rest():
        T.when(cutting, lambda: hurt_player(M.LAST_BAD_CUT, "bad_cut"))
        put("rd_oev", 1)

        def dying():
            hurt_player(M.DYING_DMG, "dying")
            ev("lastCard", cks(card), 0, 1, 0, 0)
            psych_step()
            T.when(T.LE(g("php"), 0), lambda: lose("dying"),
                   lambda: T.when(T.EQ(g("out"), 0), lambda: win(T.SEL(ronpa, 1, 4), "dying_hit")))

        def hit():
            put("lcu", 1)
            put("rev", 1)
            rems = []
            for c in CL:
                rem = T.AND(T.GT(g(f"pc_{ck(c)}"), 0), g(f"pk_{ck(c)}"))
                rems.append((rem, c))
                put(f"pc_{ck(c)}", T.SEL(rem, 0, g(f"pc_{ck(c)}")))
                if c in CH.claims:
                    put(f"kc_{c}", T.SEL(rem, 1, g(f"kc_{c}")))
            pkv = [(i, g(f"pk_{ck(c)}")) for i, c in enumerate(CL)]
            put("pcb", 0)
            put("hk", 0)
            put("bu", 0)
            extra = T.SEL(lk(K_PICKUP, card), M.LAST_PICKED_EXTRA, 0.0)
            zero = T.EQ(c0, 0)
            dmg = T.SEL(zero, M.LAST_ZERO_C_DMG + extra, T.c(M.LAST_PER_CRACK) * c0 + extra)
            heal = T.SEL(zero, M.LAST_ZERO_C_HEAL, T.MIN(M.LAST_HEAL_CAP, T.c(M.LAST_HEAL_PER_CRACK) * c0))
            hurt_player(dmg, "last_card")
            T.when(g("o0"), lambda: ev("healVoid"), lambda: put("ohp", T.c(CH.opp_max_hp) * heal))
            put("eg", 0)
            ev("lastCard", cks(card), 0, 0, dmg, g("ohp"))
            foreach_sub("d1PChain", "lastCardRemoved", "d1Claim", lambda row: T.PICK(row, pkv))
            for rem, c in rems:
                eff_if(rem, "remove", coll="d1PChain", value=T.sc(c))
            put("fhp", 1)
            put("fps", g("rd_ps"))
            put("fkl", 0)
            psych_step()
            T.when(T.AND(T.LE(g("php"), 0), T.EQ(g("out"), 0)), lambda: lose("last_card"))

        T.when(dyingv, dying, hit)
    T.when(T.NOT(brk), rest)


def last_stand_round(cmd: Cmd) -> None:
    put("h2", g("h1"))
    put("h1", NONE + 1)
    ci = cmd.ci

    def stand():
        soph = T.PICK(ci, [(i, soph_of(i)) for i in range(NCLAIM)])
        red = T.PICK(ci, [(i, red_of(i)) for i in range(NCLAIM)])
        record(cmd, "last_stand", soph, red, lk(C_TRUE, ci))
        put("cracks", g("cracks") + red)
        has_t = T.GE(cmd.ti, 0)
        cand = []
        for c in HAND_CARDS:
            k = CK.index(c)
            brk = T.AND(T.c(K_LIE[k]), breaks_lk(ci, k))
            cand.append((T.AND(T.GT(g(f"oc_{c}"), 0), brk, T.OR(T.NOT(has_t), T.EQ(cmd.ti, k))), g(f"oc_{c}"), k))
        mn = fold_min([T.SEL(cnd, v, BIG) for cnd, v, _ in cand])
        hit = argfirst([(T.AND(cnd, T.EQ(v, mn)), k) for cnd, v, k in cand])
        any_hit = fold_or([cnd for cnd, _, _ in cand])

        def failed():
            ev("lastStand", cls(ci), T.sport("world.d1CmdTarget"), 0, 0)
            put("php", 0.0)
            lose("last_stand_failed")

        def ok():
            ocv = [(k, g(f"oc_{CK[k]}")) for k in (CK.index(c) for c in HAND_CARDS)]
            rems = []
            for c in HAND_CARDS:
                rem = T.AND(T.GT(g(f"oc_{c}"), 0), T.GE(g(f"oc_{c}"), mn))
                rems.append((rem, c))
                put(f"oc_{c}", T.SEL(rem, 0, g(f"oc_{c}")))
            put("ocb", 0)
            put("php", T.c(CH.player_max_hp) * M.COMEBACK_RATIO)
            T.when(red, lambda: put("php", g("php") - M.CONTRADICTION))
            put("pl", 0)
            ev("lastStand", cls(ci), cks(hit), 1, g("php"))
            foreach_sub("d1OChain", "lastStandDestroyed", "d1Card", lambda row: T.GE(T.PICK(row, ocv), mn))
            for rem, c in rems:
                eff_if(rem, "remove", coll="d1OChain", value=T.sc(c))
            pev("lie_down_proper", CH.psych_events["lie_down_proper"])
            put("fps", 0)
            put("fkl", 0)
            put("fhp", 0)
            psych_step()
        T.when(T.OR(soph, T.NOT(any_hit)), failed, ok)

    T.when(T.EQ(cmd.pk, ACCEPT), lambda: lose("no_last_stand"), stand)


class _R:
    pass


R = _R()


def resolve(cmd: Cmd) -> None:
    """ref resolve.resolve_round on the traced state `st`."""
    R.r0 = g("r")
    R.broken0 = T.GE(g("bu"), g("r"))
    R.hk0 = g("hk")
    R.ss0 = g("ss")
    R.ohp0 = g("ohp")
    R.hp0 = g("php")
    for k in SCRATCH:
        put(k, 0)
    st["_lpev"] = ()
    ev("round", R.r0)
    T.when(g("pl"), lambda: last_stand_round(cmd),
           lambda: T.when(g("eg"), lambda: endgame_round(cmd), lambda: normal_round(cmd)))

    def rule3():
        put("r3f", 1)
        put("r3p", 1)
        ev("rule3Armed")
    T.when(T.AND(T.EQ(g("out"), 0), T.EQ(g("eg"), 0), T.NOT(g("r3f")),
                 T.LE(g("ohp"), CH.rule3_hp_ratio * CH.opp_max_hp)), rule3)

    def limit():
        mine = g("php") / CH.player_max_hp
        his = g("ohp") / CH.opp_max_hp
        T.when(T.GT(mine, his), lambda: win(4, "round_limit"), lambda: lose("round_limit"))
    T.when(T.AND(T.EQ(g("out"), 0), T.GE(g("r"), CH.max_rounds)), limit)
    inc("r")

    def begin():
        for i in range(3):
            put(f"p{i}", T.MAX(0.0, g(f"p{i}") - CH.psych_decay[i]))
            put(f"o{i}", T.GE(g(f"p{i}"), CH.psych_threshold[i]))
        put("cc", g("cn"))
        put("cn", 0)
    T.when(T.EQ(g("out"), 0), begin)


# --------------------------------------------------------------------------------------------- the policy

def decide(prefix: str) -> None:
    """ref policy.decide on the traced state `st`; writes d_<DEC_KEYS>. Draws (one atrium.rng.stream per draw name)
    only when the ref draws, in the ref order (policy.py trace contract)."""
    for k in DEC_KEYS:
        put(f"d_{k}", 0)

    def none_round():
        put("d_da", NONE + 1)
        put("d_dfo", FORCED.index("none"))

    def last_round():
        put("d_da", LAST + 1)
        put("d_dc", g("egc"))
        put("d_dtc", g("egc"))
        put("d_ds1", LAST + 1)
        put("d_dfo", FORCED.index("endgame"))

    def normal():
        o1, o2 = g("o1"), g("o2")
        hand = {c: T.GT(g(f"hd_{c}"), 0) for c in HAND_CARDS}
        rr = {c: g(f"rr_{c}") for c in LIE_CARDS}

        def nre(c):
            return T.EQ(rr[c], 0) if c in rr else T.c(1)

        def okf(c, cond):
            return T.AND(cond, T.NOT(T.AND(o1, T.c(K_FRAMES[CK.index(c)]))))

        slots = []  # (eligible, card idx + 1) in play order
        for slot in CH.play_order:
            if slot == "@pickups":
                for e in CH.pickup_priority:
                    c = CH.evidence[e].opponent_use
                    if c in hand:
                        slots.append((okf(c, T.AND(hand[c], nre(c))), T.c(CK.index(c) + 1)))
            elif slot == "@reraised":
                el = [(c, okf(c, T.AND(T.GT(rr[c], 0), hand[c]))) for c in LIE_CARDS]
                mn = fold_min([T.SEL(e, rr[c], BIG) for c, e in el])
                first = argfirst([(T.AND(e, T.EQ(rr[c], mn)), CK.index(c)) for c, e in el])
                slots.append((fold_or([e for _, e in el]), first + 1))
            elif slot in hand:
                slots.append((okf(slot, T.AND(hand[slot], nre(slot))), T.c(CK.index(slot) + 1)))
        normal0 = T.c(0)
        for e, v in reversed(slots):
            normal0 = T.SEL(e, v, normal0)
        has_normal = fold_or([e for e, _ in slots])
        unf = [c for c in CH.unfav_order if c in hand]
        u0 = T.c(0)
        for c in reversed(unf):
            u0 = T.SEL(hand[c], CK.index(c) + 1, u0)
        has_unfav = fold_or([hand[c] for c in unf])
        # available_actions
        atk_ok = T.OR(has_normal, has_unfav)
        acts = [atk_ok, atk_ok, T.c(1), T.c(1)]
        rage_av = [T.c(0), acts[1], acts[2], T.c(0)]
        h1, h2 = g("h1"), g("h2")
        nacts = fold_sum(acts)
        r5 = [T.AND(T.GT(h2, 0), T.EQ(h1, h2), T.EQ(h1, k + 1), acts[k], T.GT(nacts, 1)) for k in range(4)]
        norm_av = [T.AND(acts[k], T.NOT(r5[k])) for k in range(4)]
        av = [T.SEL(o2, rage_av[k], norm_av[k]) for k in range(4)]
        # tendency
        flags = {"player_soph_last_round": g("fps"), "own_lie_knocked_last_round": T.GT(g("fkl"), 0),
                 "hit_player_last_round": g("fhp")}
        trule, tact = T.c(0), T.c(-1)
        for rule, when, action in reversed(CH.tendencies):
            a = OA_NAMES.index(M.ACTION_BY_NAME[action].value)
            cond = T.AND(flags[when], av[a])
            trule = T.SEL(cond, rule, trule)
            tact = T.SEL(cond, a, tact)
        can_attack = atk_ok
        rule3 = T.AND(g("r3p"), can_attack)
        forced = T.SEL(rule3, FORCED.index("rule3"), T.SEL(o2, FORCED.index("rage"), 0))
        actv = T.SEL(rule3, FO, -1)
        # 1. tendency
        cond_t = T.AND(T.NOT(rule3), T.NOT(o2), T.GT(trule, 0))
        st["_d_act"] = actv

        def tend():
            fol = T.LT(draw(prefix, "tendency", 100), CH.follow_pct)
            st["_d_act"] = T.SEL(fol, tact, st["_d_act"])
        _branch_draw(cond_t, tend)
        actv = st["_d_act"]
        rule = T.SEL(cond_t, trule, 0)
        # 2. clarity
        clear_forced = T.OR(T.GT(forced, 0), g("o0"), g("nclr"))
        cw, vw = CH.tell_clarity
        st["_d_vague"] = T.c(0)

        def clar():
            st["_d_vague"] = T.GE(draw(prefix, "clarity", cw + vw), cw)
        _branch_draw(T.NOT(clear_forced), clar)
        vague = st["_d_vague"]
        # 3. base action
        thr = CH.psych_threshold
        floating = fold_or([T.GE(g(f"p{i}"), thr[i] - M.FLOAT_BAND) for i in range(3)])
        act_none = T.LT(actv, 0)
        wn = {OA_NAMES.index(M.ACTION_BY_NAME[k].value): v for k, v in CH.weights.items()}
        fr, rb = CH.rage_split
        wr = {FO: fr, RE: rb}
        w = [T.SEL(av[k], T.SEL(o2, wr.get(k, 0), wn.get(k, 0)), 0) for k in range(4)]
        st["_d_act"] = actv

        def base():
            total = fold_sum(w)
            rr_ = draw(prefix, "base", total)
            cum = []
            acc = None
            for k in range(4):
                acc = w[k] if acc is None else acc + w[k]
                cum.append(acc)
            pick = T.c(3)
            for k in (2, 1, 0):
                pick = T.SEL(T.LT(rr_, cum[k]), k, pick)
            st["_d_act"] = pick
        _branch_draw(act_none, base)
        actv = st["_d_act"]
        atk = T.OR(T.EQ(actv, AT), T.EQ(actv, FO))
        # 4. slip: only when he really speaks (00_core_rules §15〔M2〕)
        slip_cond = T.AND(atk, floating, has_unfav, has_normal, T.NOT(g("nu")))
        st["_d_slip"] = T.c(0)

        def slip():
            st["_d_slip"] = T.LT(draw(prefix, "slip", 100), M.SLIP_PCT)
        _branch_draw(slip_cond, slip)
        slipv = st["_d_slip"]
        cardv = T.SEL(T.AND(g("nu"), has_unfav), u0,
                      T.SEL(T.AND(slipv, has_unfav), u0, T.SEL(has_normal, normal0, u0)))
        # the card he would say if he speaks (§15〔M2〕): the 立論 card rule without a slip (0 = none)
        would = T.SEL(T.AND(g("nu"), has_unfav), u0, T.SEL(has_normal, normal0, u0))
        dc = T.SEL(atk, cardv, 0)
        # 5. decoy
        pool = [T.AND(av[k], T.NE(actv, k)) for k in range(4)]
        npool = fold_sum(pool)
        st["_d_decoy"] = T.c(-1)

        def decoy():
            kk = draw(prefix, "decoy", npool)
            out = T.c(-1)
            before = T.c(0)
            sel = []
            for k in range(4):
                sel.append((T.AND(pool[k], T.EQ(before, kk)), k))
                before = before + pool[k]
            st["_d_decoy"] = argfirst(sel)
        _branch_draw(T.AND(vague, T.GT(npool, 0)), decoy)
        dec = st["_d_decoy"]
        vague_t = T.AND(vague, T.GT(npool, 0))
        rule_act = T.PICK(rule, [(r_, OA_NAMES.index(M.ACTION_BY_NAME[a_].value)) for r_, _, a_ in CH.tendencies],
                          -9)
        star = T.AND(vague_t, T.GT(rule, 0), T.EQ(rule_act, actv))
        put("d_da", actv + 1)
        put("d_dc", dc)
        put("d_dcl", vague_t)
        put("d_ds1", T.SEL(vague_t, T.MIN(actv, dec) + 1, actv + 1))
        put("d_ds2", T.SEL(vague_t, T.MAX(actv, dec) + 1, 0))
        put("d_dst", T.SEL(star, actv + 1, 0))
        # the tell's card: a vague tell shows the would-say card when he stays silent (§15〔M2〕)
        dtc = T.SEL(T.AND(vague_t, T.NOT(atk)), would, dc)
        put("d_dtc", dtc)
        put("d_dp", T.AND(T.GT(dtc, 0), lk(K_UNFAV, dtc - 1)))
        put("d_drl", rule)
        put("d_dfo", forced)

    for k in ("_d_act", "_d_vague", "_d_slip", "_d_decoy"):
        st[k] = T.c(0)
    T.when(T.EQ(g("out"), 0), lambda: T.when(g("pl"), none_round, lambda: T.when(g("eg"), last_round, normal)))
    for k in ("_d_act", "_d_vague", "_d_slip", "_d_decoy"):
        del st[k]


def _branch_draw(cond, fn) -> None:
    """Run fn (which draws and writes st['_d_*']) under cond; the st values merge as selects."""
    T.when(cond, fn)


# --------------------------------------------------------------------------------------------- results (ref results.py)

def results() -> None:
    nfc = fold_sum([T.GT(g(f"sd_{c}"), 0) for c in CLAIMS if not CH.claims[c].true])
    kl = fold_sum([T.NOT(g(f"car_{e.id}")) for e in CH.evidence.values() if e.key])
    put("nfc", nfc)
    put("kl", kl)
    truth = T.MAX(0, T.c(100) - T.c(M.TRUTH_FALSE_CLAIM) * nfc - T.c(M.TRUTH_DENIAL) * g("den")
                  - T.c(M.TRUTH_KEY_LEFT) * kl)
    put("truth", truth)
    grade = g("grade")
    gi = T.MAX(0, T.MIN(4, grade - 1))
    items = [(T.c(1), T.slk([f"grade_{k}" for k in range(1, 6)], gi), T.lk([M.REP_GRADE[k] for k in range(1, 6)], gi)),
             (T.GT(g("cracks"), 0), T.sc("cracks"), T.MAX(M.REP_CRACK_CAP, T.c(M.REP_PER_CRACK) * g("cracks"))),
             (T.GT(g("priv"), 0), T.sc("private"), T.c(M.REP_PRIVATE) * g("priv")),
             (T.GT(g("pcu"), 0), T.sc("psych_card"), T.c(M.REP_PSYCH_CARD)),
             (T.GE(g("stalls"), M.REP_STALLS_AT), T.sc("stalls"), T.c(M.REP_STALLS)),
             (T.GT(g("den"), 0), T.sc("denials"), T.c(M.REP_DENIAL) * g("den"))]
    delta = fold_sum([T.SEL(c, v, 0) for c, _, v in items])
    put("rdl", delta)
    after = T.MAX(0, T.MIN(100, T.c(CH.reputation_start) + delta))
    put("rpa", after)
    put("nhp", T.MAX(-10.0, T.MIN(10.0, (after - 50) / 5)))
    put("note", T.SEL(T.GE(truth, 70), 1, T.SEL(T.GE(truth, 40), 2, 3)))
    put("paper", T.SEL(T.LE(grade, 2), 1, T.SEL(T.LE(grade, 4), 2, 3)))
    over = T.NE(g("out"), 0)
    eff_if(over, "clear", coll="d1Rep")
    for c, name, v in items:
        eff_if(T.AND(over, c), "add", coll="d1Rep", value=T.fmt(name, v))
    eff_if(over, "clear", coll="d1Favour")
    insp = T.lk([CH.warmup[w]["inspector"] for w in WARMUPS], T.MAX(0, T.MIN(len(WARMUPS) - 1, g("wu"))))
    eff_if(T.AND(over, T.NE(insp, 0)), "add", coll="d1Favour", value=T.fmt("inspector", insp))
    for who in PRIV_WHO:
        cl = [c for c, (w, _) in CH.private_favour.items() if w == who]
        tot = fold_sum([T.c(CH.private_favour[c][1]) * g(f"sn_{c}") for c in cl])
        anyc = fold_or([T.GT(g(f"sn_{c}"), 0) for c in cl])
        eff_if(T.AND(over, anyc), "add", coll="d1Favour", value=T.fmt(who, tot))


def claim_list() -> None:
    """The 說法選擇器 for the coming round (ref known.claim_list) as d1ClaimList + flag maps."""
    T.effect("clear", coll="d1ClaimList")
    for u in UNFAV:
        eff_if(T.EQ(g("cc"), CK.index(u) + 1), "add", coll="d1ClaimList", value=T.sc(f"{M.CATCH}:{u}"))
    for i, c in enumerate(CLAIMS):
        eff_if(avail_of(i), "add", coll="d1ClaimList", value=T.sc(c))
    for i, c in enumerate(CL):
        T.effect("mset", coll="d1ClaimSoph", key=T.sc(c), value=soph_of(i))
        T.effect("mset", coll="d1ClaimCrack", key=T.sc(c), value=red_of(i))
        T.effect("mset", coll="d1ClaimStand", key=T.sc(c), value=T.GT(g(f"pc_{ck(c)}"), 0))


def commit() -> None:
    for k in KEYS:
        v = st[f"d_{k}"] if k in DEC_KEYS else st[k]
        T.effect("mset", coll="d1State", key=T.sc(k), value=v)


# --------------------------------------------------------------------------------------------- entry points

def init_state() -> dict:
    s: dict = {k: T.c(0) for k in KEYS}
    s.update({k: T.c(0) for k in SCRATCH})
    s["act"] = T.c(1)
    s["r"] = T.c(1)
    s["php"] = T.c(CH.player_max_hp)
    s["ohp"] = T.c(CH.opp_max_hp)
    for i in range(3):
        s[f"p{i}"] = T.c(CH.psych_start[i])
        s[f"e{i}"] = T.c(CH.psych_start[i])
    for e in CH.evidence:
        s[f"car_{e}"] = contains("d1Carry", e)
        s[kn_key(e)] = s[f"car_{e}"]
    for a in CH.appraisals:
        s[kn_key(a)] = contains("d1Appraised", a)
    for n in CH.optional_known:
        s[kn_key(n)] = contains("d1Notes", n)
    # pickups (model.pickups_for): first max_pickup left-behind evidence in priority order
    left_before = T.c(0)
    picked = []
    for e in PICK_EV:
        left = T.NOT(s[f"car_{e}"])
        p = T.AND(left, T.LT(left_before, CH.max_pickup))
        s[f"pe_{e}"] = p
        picked.append((e, p))
        left_before = left_before + left
    base = [c for c in CK if K_KIND[CK.index(c)] in ("lie", "fav", "unfav")]
    for i, c in enumerate(base):
        s[f"hd_{c}"] = T.c(i + 1)
    # the first picked card is the reserved last card; the rest are held in hand (priority order)
    rl = T.c(0)
    for e, p in reversed(picked):
        rl = T.SEL(p, CK.index(CH.evidence[e].opponent_use) + 1, rl)
    s["rl"] = rl
    seq = T.c(len(base))
    seen = T.c(0)
    held = []
    for e, p in picked:
        c = CH.evidence[e].opponent_use
        h = T.AND(p, seen)
        held.append((c, h))
        s[f"hd_{c}"] = T.SEL(h, seq + 1, 0)
        seq = seq + h
        seen = T.OR(seen, p)
    s["hs"] = seq
    wrow = find("d1Warmup", "id", "world.d1Warmup")
    s["wu"] = T.MAX(0, wrow)
    s["_held"] = held
    return s


def trace_start() -> list:
    global st
    st = init_state()
    T.st = st
    held = st.pop("_held")
    T.pc = T.c(1)
    T.effect("pulse", inputs=[f"{STREAM_FROM}.setTrue"])
    reset_streams()
    for coll in ENGINE_LISTS:
        T.effect("clear", coll=coll)
    for c in CK:
        if K_KIND[CK.index(c)] in ("lie", "fav", "unfav"):
            T.effect("add", coll="d1Hand", value=T.sc(c))
    for c, h in held:
        eff_if(h, "add", coll="d1Hand", value=T.sc(c))
    for k in KNOWN:
        if kn_key(k) in st:
            eff_if(st[kn_key(k)], "add", coll="d1Known", value=T.sc(k))
    decide("dS")
    claim_list()
    T.effect("mclear", coll="d1State")
    commit()
    return T.take_effects()


def state_reads() -> dict:
    s = {}
    for k in KEYS:
        nid = T.raw_node(f"s_{k}", "atrium.map.get", name="d1State")
        T.raw_edge(T.sc(k), f"{nid}.key")
        s[k] = T.port(f"{nid}.value")
    return s


def command(s) -> Cmd:
    krow = find("d1Code", "id", "world.d1CmdKind")
    pk = krow - len(OA_NAMES)
    crow = find("d1Claim", "id", "world.d1CmdClaim")
    is_catch = str_is("world.d1CmdClaim", M.CATCH)
    cmap = [0] * (NCK + 1)
    for j, u in enumerate(UNFAV):
        cmap[CK.index(u) + 1] = NCLAIM + j
    catch_idx = T.lk(cmap, T.MAX(0, T.MIN(NCK, s["cc"])))
    ci = T.SEL(is_catch, catch_idx, T.MAX(0, crow))
    ti = find("d1Card", "id", "world.d1CmdTarget")
    guard = T.NE(T.port("world.d1CmdGuard"), 0)
    orow = find("d1Code", "id", "world.d1OppAct")
    has_o = T.GE(orow, 0)
    ok = T.SEL(has_o, orow, s["da"] - 1)
    ocrow = find("d1Card", "id", "world.d1OppCard")
    oc = T.SEL(has_o, T.MAX(0, ocrow), T.MAX(0, s["dc"] - 1))
    return Cmd(pk, ci, ti, guard, ok, oc)


def trace_lock(reads: dict) -> list:
    global st
    st = dict(reads)
    T.st = st
    for k in SCRATCH:
        st[k] = T.c(0)
    cmd = command(reads)
    T.pc = T.c(1)
    T.effect("pulse", inputs=[f"{STREAM_FROM}.setFalse"])
    T.pc = T.AND(reads["act"], T.EQ(reads["out"], 0))
    T.effect("clear", coll="d1Events")
    resolve(cmd)
    decide("dL")
    claim_list()
    results()
    commit()
    return T.take_effects()


# --------------------------------------------------------------------------------------------- outputs

def outputs(s: dict) -> list[tuple[str, object]]:
    """(signal, value) pairs from the stored state (readable from the tick after a pulse)."""
    def cardname(v):
        return T.slk([""] + CK, T.MAX(0, T.MIN(NCK, v)))

    def actname(v):
        return T.slk([""] + OA_NAMES, T.MAX(0, T.MIN(len(OA_NAMES), v)))
    phase = T.SEL(T.NOT(s["act"]), 0, T.SEL(T.NE(s["out"], 0), 4, T.SEL(s["pl"], 3, T.SEL(s["eg"], 2, 1))))
    hand = fold_sum([T.GT(s[f"hd_{c}"], 0) for c in HAND_CARDS])
    out = [
        ("d1Phase", T.slk(["idle", "choose", "endgame", "laststand", "over"], phase)),
        ("d1Round", s["r"]), ("d1PlayerHp", s["php"]), ("d1PlayerMax", T.c(CH.player_max_hp)),
        ("d1OppHp", s["ohp"]), ("d1OppMax", T.c(CH.opp_max_hp)), ("d1PCombo", s["pcb"]), ("d1OCombo", s["ocb"]),
        ("d1Hachiku", s["hk"]), ("d1Broken", T.GE(s["bu"], s["r"])), ("d1BrokenUntil", s["bu"]),
        ("d1Shisshu", s["ss"]),
        ("d1PsychP", s["p0"]), ("d1PsychG", s["p1"]), ("d1PsychA", s["p2"]),
        ("d1PsychEndP", s["e0"]), ("d1PsychEndG", s["e1"]), ("d1PsychEndA", s["e2"]),
        ("d1OverP", s["o0"]), ("d1OverG", s["o1"]), ("d1OverA", s["o2"]),
        ("d1ThreshP", T.c(CH.psych_threshold[0])), ("d1ThreshG", T.c(CH.psych_threshold[1])),
        ("d1ThreshA", T.c(CH.psych_threshold[2])),
        ("d1Cracks", s["cracks"]), ("d1Denials", s["den"]), ("d1GuardUsed", s["gu"]), ("d1Dying", s["egd"]),
        ("d1LastCardUsed", s["lcu"]), ("d1PlayerLocked", s["pl"]), ("d1RoundLimit", T.c(CH.max_rounds)),
        ("d1Grade", s["grade"]), ("d1Truth", s["truth"]), ("d1RepDelta", s["rdl"]), ("d1RepAfter", s["rpa"]),
        ("d1NextStartHp", s["nhp"]), ("d1TellPartial", s["dp"]), ("d1TellRule", s["drl"]), ("d1HandCount", hand),
        ("d1CatchCard", cardname(s["cc"])),
        ("d1Endgame", T.slk(TRIGGERS, T.MAX(0, T.MIN(2, s["eg"])))),
        ("d1LastCard", T.ssel(s["eg"], cardname(s["egc"]), "")),
        ("d1Outcome", T.slk(["", "win", "loss"], T.MAX(0, T.MIN(2, s["out"])))),
        ("d1EndReason", T.slk(REASONS, T.MAX(0, T.MIN(len(REASONS) - 1, s["why"])))),
        ("d1Note", T.ssel(s["out"], T.slk(NOTES, T.MAX(0, T.MIN(3, s["note"]))), "")),
        ("d1Paper", T.ssel(s["out"], T.slk(PAPERS, T.MAX(0, T.MIN(3, s["paper"]))), "")),
        ("d1TellClarity", T.ssel(T.AND(s["act"], T.EQ(s["out"], 0), T.NOT(s["pl"])),
                                 T.ssel(s["dcl"], "vague", "clear"), "")),
        ("d1TellShown1", actname(s["ds1"])), ("d1TellShown2", actname(s["ds2"])),
        ("d1TellStar", actname(s["dst"])), ("d1TellCard", cardname(s["dtc"])),
        ("d1TellForced", T.slk(FORCED, T.MAX(0, T.MIN(len(FORCED) - 1, s["dfo"])))),
        ("d1TellAction", actname(s["da"])),
    ]
    return out


# --------------------------------------------------------------------------------------------- build

def build() -> Emitter:
    T.reset()
    _uid[0] = 0
    Emitter._eff_n = 0
    make_streams()
    start_eff = trace_start()
    reads = state_reads()
    lock_eff = trace_lock(reads)
    wire_stream_n()
    outs = outputs(reads)
    em = Emitter()
    em.add_raw(T)
    roots = []
    for eff in (start_eff, lock_eff):
        for gd, kind, d in eff:
            roots.append(gd)
            roots += [v for v in d.values() if isinstance(v, (N, S))]
    roots += [s for s, _ in T.raw_edges if isinstance(s, (N, S))]
    roots += [v for _, v in outs]
    em.count(roots)
    em.cascade("world.d1Start", start_eff, "st")
    em.cascade("world.d1Lock", lock_eff, "lo")
    em.flush_raw_edges()
    for sig, v in outs:
        em.edge(em.any_(v), f"world.{sig}")
    return em


_built: list = []


def engine() -> Emitter:
    if not _built:
        _built.append(build())
    return _built[0]


def write_json(rows) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=1) + "\n"


def generated() -> dict[Path, str]:
    out = {FLOW: engine().text()}
    for name, rows in derive_tables().items():
        out[DATA_OUT / f"{name}.json"] = write_json(rows)
    return out


def graph_stats() -> tuple[int, int]:
    em = engine()
    return len(em.nodes), len(em.edges)


def main() -> int:
    check = "--check" in sys.argv[1:]
    stale = []
    for path, text in generated().items():
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path.relative_to(ROOT).as_posix())
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
            print(f"wrote {path.relative_to(ROOT).as_posix()}")
    if not check:
        n, e = graph_stats()
        print(f"d01_debate_engine: {n} nodes, {e} edges")
    if stale:
        print("stale: " + ", ".join(stale) + " (run uv run tools/gen_debate_v2.py)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
