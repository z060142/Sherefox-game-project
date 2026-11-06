# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Statistical and rule check of the debate engine's opponent policy (docs/debate-engine.md §3.4, §6.2) against the
reference model ref/ (policy.decide_next is the oracle).

Usage (from the project root):
    uv run tests/check_policy.py [--samples N] [--seeds K] [--verbose]

1. regenerates the engine (tools/gen_debate.py);
2. builds every situation of SITUATIONS in ref/ (initial state, replayed prefix rounds, field overrides) and computes
   the exact distribution of decide_next by enumerating every choice with its probability (Fraction);
3. writes the harness project tests/policy_harness/ (a one-tick-per-step driver, the engine and the tables) and runs it
   headless K times in parallel with --seed 1..K. Per situation the engine decides once at the last debStart /
   debLock, then N/K - 1 more times with debRedecide (the same decision graph from the stored state); every decision
   (debState keys) and the tell outputs (debTell*) are recorded;
4. free play: whole debates where the engine's own decisions drive the opponent (no script rows) and the player's
   moves are fixed; each is replayed in ref/ with the engine's actions, and every decision must be one the ref
   policy can produce in that state;
5. compares, per situation, the observed frequency of every outcome (action + tell: clarity, shown pair in order, ★,
   ★ rule, basis, rule applied), of the lit node and of the tell line with the exact probabilities: |z| <= 4 per
   cell (z = (k - Np) / sqrt(Np(1-p))); an outcome with p = 0 must never occur. 4 sigma: about 300 cells in all, so
   the chance that a correct engine fails anywhere is about 2 %, while an error of the size the rulings decide
   (e.g. B11: 80 % vs 84 %) is about 7 sigma at N = 4000. The runs are seeded, so a result is reproducible.
6. asserts the hard rules on every recorded decision (situations and free play) and prints the counts.

Exit code 0 when everything passes.
"""

from __future__ import annotations

import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import gen_debate as G  # noqa: E402
import debate_routes as R  # noqa: E402
from sherefox_ref.fixtures import ch1_board, ch1_case, ch2_board, ch2_case, ch3_board, ch3_case, data_node_id  # noqa: E402
from sherefox_ref.model import ATTACKS, OA, PA, Clarity, OpponentAction, initial_state  # noqa: E402
from sherefox_ref.policy import decide_next  # noqa: E402
from sherefox_ref.resolve import resolve_round  # noqa: E402
from sherefox_ref.rules import IllegalAction  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
from xt_cli import EXE, XTFRAME  # noqa: E402  (tests/xt_cli.py: XTATRIUM_EXE, the SDK, or the checkout)
HARNESS = ROOT / "tests" / "policy_harness"
Z_MAX = 4.0

pa, oa = R.pa, R.oa
OA_NAME = R.OA_NAME
CODE = {OA.CLAIM: 0, OA.RUSH: 1, OA.REINFORCE: 2, OA.TRAP: 3, OA.ALL_IN: 4}
ACT = ["assert", "rush", "reinforce", "trap", "scorched"]
PA_CODE = {PA.SOLID: 0, PA.SOPHISTRY: 1, PA.PARRY: 2, PA.OBSERVE: 3}
TABLES = G.derive_tables()
CASE_ROW = {r["id"]: r for r in TABLES["debCase"]}
LINES = TABLES["debLine"]
LINE_ROW = {r["id"]: i for i, r in enumerate(LINES)}
# every string a tell output can take (the driver records rows of this table, not strings)
VOCAB = sorted({"", "clear", "fuzzy", "script", "fox", *ACT, *G.BASIS} | {r["id"] for r in TABLES["debNode"]}
               | {r[f"g{i}"] for r in TABLES["debCase"] for i in range(4)} | {r["id"] for r in LINES})


# ------------------------------------------------------------------------------------------------- the oracle

class ProbChooser:
    """Follows a fixed path of choice indices and multiplies the probability of each choice (ref RngChooser's
    semantics: weighted by weight / total, percent p / 100, uniform 1 / n)."""

    def __init__(self, path):
        self.path, self.i, self.branching, self.p = list(path), 0, [], Fraction(1)

    def _pick(self, opts):
        k = self.path[self.i] if self.i < len(self.path) else 0
        self.branching.append(len(opts))
        self.i += 1
        v, q = opts[k]
        self.p *= q
        return v

    def weighted(self, items):
        items = [(v, w) for v, w in items if w > 0]
        total = sum(w for _, w in items)
        return self._pick([(v, Fraction(w, total)) for v, w in items])

    def percent(self, p):
        return self._pick([(o, q) for o, q in ((True, Fraction(p, 100)), (False, Fraction(100 - p, 100))) if q > 0])

    def uniform(self, xs):
        xs = list(xs)
        return self._pick([(x, Fraction(1, len(xs))) for x in xs])


def outcome_key(chapter: int, act: OA, clarity: str, shown, star, star_rule, basis, lit, rule) -> tuple:
    return (OA_NAME[act], clarity, tuple(OA_NAME[a] for a in shown), OA_NAME[star] if star else "", star_rule or 0,
            basis or "", R.node_id(chapter, lit) if lit else "", rule or 0)


def distribution(state, chapter: int) -> dict[tuple, Fraction]:
    """Exact distribution of decide_next(state) over outcome keys."""
    out: dict[tuple, Fraction] = defaultdict(Fraction)
    stack = [[]]
    while stack:
        path = stack.pop()
        ch = ProbChooser(path)
        _, o, t = decide_next(state, ch)
        out[outcome_key(chapter, o.kind, t.clarity.value, t.shown, t.star, t.star_rule, t.basis, o.lit,
                        t.rule_applied)] += ch.p
        for depth in range(len(path), len(ch.branching)):
            for k in range(1, ch.branching[depth]):
                stack.append(path + [0] * (depth - len(path)) + [k])
    assert sum(out.values()) == 1
    return dict(out)


# ------------------------------------------------------------------------------------------------- situations

@dataclass
class Sit:
    name: str
    chapter: int
    case_fn: object
    board: object
    moves: list = field(default_factory=list)  # (PlayerAction, OpponentAction) prefix, played from script rows
    pre: dict = field(default_factory=dict)  # ref field -> value on the initial state
    post: dict = field(default_factory=dict)  # ref field -> value after the prefix
    line_key: str = ""  # lineKey of the last prefix round's script row (the never-same-line rule)
    script_next: dict | None = None  # a script row for the decided round: its tell must override the policy
    why: str = ""


CH2_SOLID2 = dict(segment=("E02_03", "E02_02"), target="N1")
SITUATIONS = [
    Sit("ch2_open", 2, ch2_case, ch2_board(), why="round 1: personality 45/15/20/20, clarity 60/40, decoy by personality"),
    Sit("ch2_rule1", 2, ch2_case, ch2_board(), [(pa(PA.PARRY, "E02_02"), oa(OA.CLAIM, "N1"))],
        why="rule 1 (node removed) -> reinforce 80 % + 20 % personality (B11), star 1"),
    Sit("ch2_rule4_prevline", 2, ch2_case, ch2_board(), [(pa(PA.PARRY, "E02_02"), oa(OA.REINFORCE, "N1"))],
        line_key="SCR_CH02_S90_L003", why="rule 4 (reinforce succeeded) -> assert; last line L003 is excluded"),
    Sit("ch2_rule2", 2, R.soph_case, R.SOPH_BOARD, [(pa(PA.SOPHISTRY, **R.SOPH_PA), oa(OA.CLAIM, "N1"))],
        why="rule 2 (player sophistry) -> trap"),
    Sit("ch2_rule1_beats_4", 2, ch2_case, ch2_board(), [(pa(PA.PARRY, "E02_02"), oa(OA.CLAIM, "N1"))],
        post={"last_reinforce_success": True}, why="rules 1 and 4 apply: the lowest number wins"),
    Sit("ch2_rule1_deleted_nrn", 2, ch2_case, ch2_board(), [(pa(PA.PARRY, "E02_02"), oa(OA.CLAIM, "N1"))],
        post={"last_reinforce_success": True, "no_reinforce_next": True},
        why="rule 1's reinforce deleted by 不能補強 -> rule 4 wins; reinforce never shown"),
    Sit("ch2_rule1_deleted_rule5", 2, ch2_case, ch2_board(),
        [(pa(PA.OBSERVE), oa(OA.REINFORCE, "N1")), (pa(PA.SOLID, **CH2_SOLID2), oa(OA.REINFORCE, "N1"))],
        why="reinforce twice (rule 5) and a node removed: rule 1 deleted, personality over the other three"),
    Sit("ch2_rule5_observe", 2, ch2_case, ch2_board(),
        [(pa(PA.OBSERVE), oa(OA.CLAIM, "N1")), (pa(PA.OBSERVE), oa(OA.CLAIM, "N2"))],
        why="assert twice: assert banned; observed an attack: clear, basis observe"),
    Sit("ch2_must_attack", 2, ch2_case, ch2_board(), [(pa(PA.OBSERVE), oa(OA.TRAP, "N1"))],
        why="observe exposed a trap: forced attack 45:15, clear, basis observe"),
    Sit("ch2_must_attack_rule5", 2, ch2_case, ch2_board(), [(pa(PA.OBSERVE), oa(OA.TRAP, "N1"))],
        post={"opp_history": (OA.CLAIM, OA.CLAIM)}, why="forced attack with assert banned by rule 5 -> rush"),
    Sit("ch2_no_reinforce", 2, ch2_case, ch2_board(), [(pa(PA.SOLID, **CH2_SOLID2), oa(OA.TRAP, "N1"))],
        why="missed trap: no reinforce; rule 1 (node removed) deleted with it"),
    Sit("ch2_rule3", 2, ch2_case, ch2_board(), [(pa(PA.PARRY, "E02_02"), oa(OA.CLAIM, "N1"))], pre={"opp_hp": 80.0},
        why="first time <= 50 % (B9): forced rush, clear, basis rule3 (beats rule 1)"),
    Sit("ch2_route_r4", 2, ch2_case, ch2_board(), R.CH2[:3], why="recommended route before R4"),
    Sit("ch2_tail", 2, ch2_case, ch2_board(), R.CH2[:4], why="tail: scorched, clear, basis script; endgame lines"),
    Sit("ch2_after_void_rule3", 2, ch2_case, ch2_board(), R.CH2[:4] + [(pa(PA.OBSERVE), oa(OA.ALL_IN, "T2", True))],
        why="rule 3 fired in the break round stays pending through the tail and fires after the void"),
    Sit("ch2_scripted_no_memory", 2, ch2_case, ch2_board(), [(pa(PA.PARRY, "E02_02"), oa(OA.CLAIM, "N1", True))],
        why="a scripted round (A-11) does not set rule 1"),
    Sit("ch2_script_override", 2, ch2_case, ch2_board(), [(pa(PA.PARRY, "E02_02"), oa(OA.CLAIM, "N1"))],
        script_next={"action": "assert", "lit": "CH02_N2", "scripted": 0, "clarity": "fuzzy", "shown1": "reinforce",
                     "shown2": "assert", "star": "reinforce", "starRule": 1, "basis": "",
                     "lineKey": "SCR_CH02_S90_L004"},
        why="a script row for the round overrides the policy's tell (A-11)"),
    Sit("ch3_open", 3, ch3_case, ch3_board(), why="Ch.3 round 1"),
    Sit("ch3_konju_rule3", 3, ch3_case, ch3_board(),
        [(pa(PA.PARRY, "E03_08"), oa(OA.CLAIM, "N1")), (pa(PA.PARRY, "E03_07"), oa(OA.CLAIM, "N3"))],
        why="困獸 from the 2nd intercept and HP 40 <= 50 %: rule 3 comes first"),
    Sit("ch3_konju", 3, ch3_case, ch3_board(),
        [(pa(PA.PARRY, "E03_08"), oa(OA.CLAIM, "N1")), (pa(PA.PARRY, "E03_07"), oa(OA.CLAIM, "N3"))],
        pre={"rule3_fired": True},
        why="困獸 (rule 3 already used): reinforce banned (rule 1 deleted), fuzzy -> clear basis konju"),
    Sit("ch3_route_r4", 3, ch3_case, ch3_board(), R.CH3[:3], why="recommended route before R4 (ruling A3)"),
    Sit("ch3_shisshu", 3, ch3_case, ch3_board(),
        [(pa(PA.SOLID, segment=("E03_02", "E03_04"), target="N2"), oa(OA.RUSH, "N1"))], why="after 失守"),
    Sit("ch1_open", 1, ch1_case, ch1_board(), why="Arthur round 1: 25/50 (D7), clear, basis tutorial"),
    Sit("ch1_rule1", 1, ch1_case, ch1_board(), [(pa(PA.PARRY, "E01_06"), oa(OA.CLAIM, "N1"))],
        why="Arthur rule 1: reinforce 80 % + 20 % x 2/3"),
    Sit("ch1_rule4", 1, ch1_case, ch1_board(),
        [(pa(PA.PARRY, "E01_06"), oa(OA.CLAIM, "N1")), (pa(PA.PARRY, "E01_01"), oa(OA.REINFORCE, "N2"))],
        why="Arthur rule 4: assert 80 % + 20 % x 1/3"),
]

# ref field -> (debState key, value)
def state_sets(field_name: str, value) -> list[tuple[str, float]]:
    if field_name == "opp_hp":
        return [("ohp", value)]
    if field_name == "opp_history":
        h = [CODE[a] + 1 for a in value]
        return [("h1", h[-1] if h else 0), ("h2", h[-2] if len(h) > 1 else 0)]
    key = {"last_reinforce_success": "lrs", "no_reinforce_next": "nrn", "last_node_removed": "lnr",
           "must_attack_next": "man", "rule3_pending": "r3p", "rule3_fired": "r3f", "konju_left": "kj"}[field_name]
    return [(key, float(value))]


# ------------------------------------------------------------------------------------------------- free play

@dataclass
class FreePlay:
    name: str
    chapter: int
    case_fn: object
    board: object
    options: list  # (weight, PlayerAction)
    debates: int
    rounds: int


FREE = [
    FreePlay("fp_ch2", 2, R.soph_case, R.SOPH_BOARD,
             [(4, pa(PA.OBSERVE)), (4, pa(PA.SOLID, **CH2_SOLID2)), (2, pa(PA.SOPHISTRY, **R.SOPH_PA))], 30, 12),
    FreePlay("fp_ch3", 3, ch3_case, ch3_board(),
             [(4, pa(PA.OBSERVE)), (5, pa(PA.SOLID, segment=("E03_08",), target="N1"))], 30, 12),
    FreePlay("fp_ch1", 1, ch1_case, ch1_board(),
             [(1, pa(PA.OBSERVE)), (1, pa(PA.SOLID, segment=("E01_01", "E01_04"), target="N2"))], 30, 6),
]


def free_moves(fp: FreePlay, d: int) -> list:
    rnd = random.Random(f"{fp.name}:{d}")
    out = []
    for _ in range(fp.rounds):
        opts = [(w, m) for w, m in fp.options if not (out and m.kind == PA.SOPHISTRY == out[-1].kind)]
        out.append(rnd.choices([m for _, m in opts], [w for w, _ in opts])[0])
    return out


# ------------------------------------------------------------------------------------------------- schedule

LEAD = 2
SIG_SAMPLES = 100  # per situation and run: samples whose tell outputs are recorded too (list capacity)
LAG = 1  # steps between the driver's pulse and the engine acting on it (checked: every record carries the round)
P_COLS = ["case", "script", "board", "ok", "links", "key", "value", "kind", "from", "to", "card", "target", "assist"]


class Schedule:
    def __init__(self) -> None:
        self.p_in: list[dict] = []
        # the first steps stay idle (load-time pushes)
        self.ticks: list[dict] = [{"op": "none", "r": 0, "mt": "", "st": ""} for _ in range(LEAD)]
        self.script: list[dict] = []
        self.first_free = LEAD
        self.tags: list[str] = []
        self.tag_ids: dict[str, int] = {}

    def row(self, **kw) -> int:
        r = {c: 0 if c in ("value", "assist") else -1 if c in ("from", "to") else "" for c in P_COLS}
        r.update(kw)
        self.p_in.append(r)
        return len(self.p_in) - 1

    def tag_id(self, tag: str) -> int:
        if not tag:
            return 0
        if tag not in self.tag_ids:
            self.tag_ids[tag] = len(self.tags) + 1
            self.tags.append(tag)
        return self.tag_ids[tag]

    def _slot(self, t: int) -> dict:
        while len(self.ticks) <= t:
            self.ticks.append({"op": "none", "r": self.ticks[-1]["r"], "mt": "", "st": ""})
        return self.ticks[t]

    def act(self, op: str, r: int, tag: str = "", hold: bool = False, sig: bool = True) -> None:
        """One action at the next free step. The engine acts on the driver's step-k pulse at step k + LAG
        (measured: it reads the pulse and the command values one tick late), so a start / round keeps its row
        (command values) for the next step too (`hold`). A tagged action's decision is recorded at step
        k + LAG + 1 (debState) and k + LAG + 2 (the tell outputs, written by the engine one step after the commit)."""
        t = self.first_free
        slot = self._slot(t)
        assert slot["op"] == "none"
        slot.update(op=op, r=r)
        self.first_free = t + 1
        if hold:
            self._slot(t + 1)["r"] = r
            self.first_free = t + 1 + LAG
        if tag:
            self._slot(t + LAG + 1)["mt"] = tag
            if sig:
                self._slot(t + LAG + 2)["st"] = tag

    def idle(self, n: int) -> None:
        last = self.ticks[-1]["r"]
        for _ in range(n):
            self.ticks.append({"op": "none", "r": last, "mt": "", "st": ""})
        self.first_free = len(self.ticks)


def board_cols(case, board):
    cards, ok, links, slot_of = R.board_layout(case, board)
    return dict(board=",".join(cards), ok=",".join(map(str, ok)), links=",".join(map(str, links))), slot_of


def cmd_cols(chapter, board, slot_of, p) -> dict:
    frm, to = R.segment_slots(p.segment, board, slot_of) if p.segment else (-1, -1)
    return dict(kind=R.PA_NAME[p.kind], **{"from": frm}, to=to, card=p.card or "",
                target=data_node_id(chapter, p.target) if p.target else "", assist=int(p.assist))


def build(samples_per_run: int) -> tuple[Schedule, list, list]:
    """Returns the schedule, [(Sit, ref state, case id)] and [(FreePlay, debate index, moves)]."""
    sc = Schedule()
    sits = []
    for st in SITUATIONS:
        case = st.case_fn()
        cid = R.CASE_ID[st.chapter]
        base = dict(case=cid, script=st.name)
        cols, slot_of = board_cols(case, st.board)
        s = initial_state(case, st.board)
        if st.pre:
            s = replace(s, **st.pre)
        sc.act("start", sc.row(**base, **cols), f"{st.name}:start" if not st.moves and not st.post else "", hold=True)
        for f, v in st.pre.items():
            for k, val in state_sets(f, v):
                sc.act("set", sc.row(**base, key=k, value=val))
        if case.sophistry_unlocked and not CASE_ROW[cid]["soph"]:
            sc.act("set", sc.row(**base, key="soph", value=1))
        for i, (p, o) in enumerate(st.moves, start=1):
            s, _ = resolve_round(s, p, o)
            sc.script.append({"key": f"{st.name}:{i}", "action": OA_NAME[o.kind],
                              "lit": R.node_id(st.chapter, o.lit) if o.lit else "", "scripted": int(o.scripted),
                              "clarity": "", "shown1": "", "shown2": "", "star": "", "starRule": 0, "basis": "",
                              "lineKey": st.line_key if i == len(st.moves) else ""})
            last = i == len(st.moves) and not st.post
            sc.act("round", sc.row(**base, **cmd_cols(st.chapter, st.board, slot_of, p)),
                   f"{st.name}:lock" if last else "", hold=True)
        if st.script_next:
            sc.script.append({"key": f"{st.name}:{len(st.moves) + 1}", **st.script_next})
        if st.post:
            s = replace(s, **st.post)
            for f, v in st.post.items():
                for k, val in state_sets(f, v):
                    sc.act("set", sc.row(**base, key=k, value=val))
        re_row = sc.row(**base)
        n = samples_per_run - (0 if st.post else 1)
        for k in range(n):
            sc.act("re", re_row, f"{st.name}:{k}", sig=k < SIG_SAMPLES)
        sc.idle(3)
        sits.append((st, s, cid))
    plays = []
    for fp in FREE:
        case = fp.case_fn()
        cid = R.CASE_ID[fp.chapter]
        cols, slot_of = board_cols(case, fp.board)
        for d in range(fp.debates):
            base = dict(case=cid, script=f"{fp.name}_{d}")
            moves = free_moves(fp, d)
            sc.act("start", sc.row(**base, **cols), f"{fp.name}:{d}:0", hold=True)
            if case.sophistry_unlocked and not CASE_ROW[cid]["soph"]:
                sc.act("set", sc.row(**base, key="soph", value=1))
            for r, p in enumerate(moves, start=1):
                sc.act("round", sc.row(**base, **cmd_cols(fp.chapter, fp.board, slot_of, p)), f"{fp.name}:{d}:{r}",
                       hold=True)
            sc.idle(3)
            plays.append((fp, d, moves))
    return sc, sits, plays


# ------------------------------------------------------------------------------------------------- driver

REC_KEYS = list(G.DEC_KEYS) + ["pln", "r"]
SIG_NUM = {"debTellStarRule", "debTellRule", "debRound"}
# packing of a record into decimal digits (exponent per field): one number for the decision, three for the outputs
M_PACK = [("da", 0), ("dlit", 1), ("dcl", 2), ("ds1", 3), ("ds2", 4), ("dst", 5), ("dsr", 6), ("db", 7), ("dru", 8),
          ("dln", 9), ("pln", 11), ("r", 13)]
S_PACK = [[("debTellClarity", 0), ("debTellShown1", 3), ("debTellShown2", 6), ("debTellStar", 9)],
          [("debTellBasis", 0), ("debTellLit", 3), ("debTellGesture", 6), ("debTellLine", 9)],
          [("debTellStarRule", 0), ("debTellRule", 1), ("debRound", 2)]]


def unpack(v: int, spec) -> dict:
    out = {}
    ex = [e for _, e in spec] + [16]
    for i, (k, e) in enumerate(spec):
        out[k] = (v // 10 ** e) % 10 ** (ex[i + 1] - e)
    return out


REC_SIG = ["debTellClarity", "debTellShown1", "debTellShown2", "debTellStar", "debTellStarRule", "debTellBasis",
           "debTellLit", "debTellGesture", "debTellLine", "debTellRule", "debRound"]


def gen_driver():
    """One step per tick: a deadband filter (threshold 0) on clock.seconds pulses every tick and a counter numbers
    the steps (the clock's float accumulator cannot be rounded to a tick index over 20 000 ticks). Step k (0-based)
    reads row k of table pT: first the records whose tag is set (debState decision keys; tell outputs), then the action
    (start / set / round / re). See Schedule.act for the timing."""
    g = G.Graph()
    x = g.x
    g.node("clock", "clock")
    g.node("every", "filter", op="deadband", threshold=0)
    g.edge("clock.seconds", "every.in")
    g.node("step", "counter")
    g.v["k"] = "step.value"
    for c, typ in (("op", "string"), ("r", "number"), ("mt", "number"), ("st", "number")):
        g.tget("t_" + c, "pT", c, "k", typ)
    for c in P_COLS:
        typ = "number" if c in ("value", "from", "to", "assist") else "string"
        g.tget("h_" + c, "pIn", c, "t_r", typ)
    for sig, col in (("debCase", "h_case"), ("debScript", "h_script"), ("debCmdKind", "h_kind"),
                     ("debCmdFrom", "h_from"), ("debCmdTo", "h_to"), ("debCmdCard", "h_card"),
                     ("debCmdTarget", "h_target"), ("debCmdAssist", "h_assist")):
        g.edge(g.v[col], f"world.{sig}")
    for op in ("start", "set", "round", "re"):
        g.streq("is_" + op, "t_op", g.const(op))
    x("hasM", "t_mt > 0")
    x("hasS", "t_st > 0")
    cas = G.Cascade(g, "pg")
    # records first (they read the tick-start map and the signals as written by the engine one tick ago). Numbers
    # only: every distinct string a flow builds is kept by the runtime, so unique record strings make a long run
    # quadratic; the tell strings are mapped to rows of the vocabulary table pVoc instead.
    for k in REC_KEYS:
        g.node(f"m_{k}", "atrium.map.get", name="debState")
        g.edge(g.const(k), f"m_{k}.key")
        g.v[f"m_{k}"] = f"m_{k}.value"

    def record(coll: str, cond: str, values: list[str]) -> None:
        trig = []
        for i, v in enumerate(values):
            nid = f"{coll}_{i}"
            g.node(nid, "atrium.coll.add", name=coll)
            g.edge(g.src(v), f"{nid}.value")
            trig.append(f"{nid}.trigger")
        cas.on(cond, *trig)

    # packed decimal fields (exact in a double): see unpack()
    x("pkM", " + ".join(f"{10 ** e} * {'(m_da + 1)' if k == 'da' else 'm_' + k}" for k, e in M_PACK))
    record("pRecM", "hasM", ["t_mt", "pkM"])
    vals = {}
    for sg in REC_SIG:
        if sg in SIG_NUM:
            g.v[f"n_{sg}"] = f"world.{sg}"
            vals[sg] = f"n_{sg}"
        else:
            g.tfind(f"voc_{sg}", "pVoc", "s", f"world.{sg}")
            vals[sg] = f"voc_{sg}"
    for gi, grp in enumerate(S_PACK):
        x(f"pkS{gi}", " + ".join(f"{10 ** e} * ({vals[sg]}{'' if sg in SIG_NUM else ' + 1'})" for sg, e in grp))
    record("pRecS", "hasS", ["t_st"] + [f"pkS{gi}" for gi in range(len(S_PACK))])
    for nm, coll, src in (("bCards", "debBoard", "h_board"), ("bOk", "debBoardOk", "h_ok"),
                          ("bLinks", "debBoardLink", "h_links")):
        g.node(nm + "Clr", "atrium.coll.clear", name=coll)
        g.node(nm + "Add", "atrium.coll.addAll", name=coll)
        g.edge(g.v[src], f"{nm}Add.text")
        cas.on("is_start", f"{nm}Clr.trigger", f"{nm}Add.trigger")
    for op, sig in (("start", "debStart"), ("round", "debLock"), ("re", "debRedecide")):
        g.node("p_" + op, "merge")
        g.edge(f"p_{op}.out", f"world.{sig}")
        cas.on("is_" + op, f"p_{op}.in")
    g.node("setKey", "atrium.map.set", name="debState")
    g.edge(g.v["h_key"], "setKey.key")
    g.edge(g.v["h_value"], "setKey.value")
    cas.on("is_set", "setKey.trigger")
    cas.emit("every.passed")
    # the step counter advances after the step's effects: a gate's guard that changed within the same pulse would
    # still hold its old value, so the row index must be settled before the pulse
    g.edge("every.passed", "step.increment")
    return g


def write_harness(sc: Schedule) -> int:
    for sub in ("flows", "data"):
        (HARNESS / sub).mkdir(parents=True, exist_ok=True)
    (HARNESS / "flows" / "debate_engine.xtflow").write_bytes((G.FLOWS / "debate_engine.xtflow").read_bytes())
    (HARNESS / "flows" / "driver.xtflow").write_bytes(gen_driver().text().encode("utf-8"))
    for name, rel in G.TABLES.items():
        (HARNESS / "data" / f"{name}.json").write_bytes((ROOT / rel).read_bytes())
    ticks = [{**t, "mt": sc.tag_id(t["mt"]), "st": sc.tag_id(t["st"])} for t in sc.ticks]
    for name, rows in (("pIn", sc.p_in), ("pT", ticks), (G.SCRIPT_TABLE, sc.script),
                       ("pVoc", [{"s": v} for v in VOCAB])):
        (HARNESS / "data" / f"{name}.json").write_text(
            "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows) + "\n]\n",
            encoding="utf-8", newline="\n")
    tables = {name: f"data/{name}.json" for name in list(G.TABLES) + ["pIn", "pT", "pVoc"]}
    tables[G.SCRIPT_TABLE] = G.script_table(f"data/{G.SCRIPT_TABLE}.json")
    colls = {**G.COLLECTIONS,
             "pRecM": {"kind": "list", "type": "number", "capacity": 65536},
             "pRecS": {"kind": "list", "type": "number", "capacity": 65536}}
    game = {"game": 1, "xtatrium": "0.4", "name": "sherefox-policy-harness",
            "stepSeconds": 0.016666666666666666, "gravity": [0, 0], "collisionCategories": [],
            "signals": G.SIGNALS, "input": {"actions": {}, "axes": []},
            "flows": ["flows/driver.xtflow", "flows/debate_engine.xtflow"], "tables": tables, "collections": colls}
    (HARNESS / "game.json").write_text(json.dumps(game, ensure_ascii=False, indent=1) + "\n", encoding="utf-8",
                                       newline="\n")
    (HARNESS / ".gitignore").write_text("flows/\ndata/\nout/\n", encoding="utf-8", newline="\n")
    return len(sc.ticks) + 1


def run_all(ticks: int, seeds: int) -> list[dict]:
    env = dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME)
    with tempfile.TemporaryDirectory() as tmp:
        procs = []
        for seed in range(1, seeds + 1):
            dump = Path(tmp) / f"dump{seed}.json"
            procs.append((seed, dump, subprocess.Popen(
                [str(EXE), "run", "--game", str(HARNESS), "--ticks", str(ticks), "--seed", str(seed), "--dump",
                 str(dump)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env)))
        out = []
        for seed, dump, p in procs:
            so, se = p.communicate()
            if p.returncode != 0 or not dump.exists():
                print(so + se)
                raise SystemExit(f"FAIL harness run seed {seed} (exit {p.returncode})")
            if se.strip():
                print(f"stderr (seed {seed}):\n{se.strip()}")
            colls = json.loads(dump.read_text(encoding="utf-8"))["collections"]
            out.append({"seed": seed, "m": colls["pRecM"]["items"], "s": colls["pRecS"]["items"], "stderr": se})
        return out


# ------------------------------------------------------------------------------------------------- decoding

def num(v: str) -> int:
    return int(float(v))


@dataclass
class Dec:
    tag: str
    act: int
    lit: int
    clar: int
    s1: int
    s2: int
    star: int
    star_rule: int
    basis: int
    rule: int
    line: int  # debLine row, -1 none
    prev_line: int
    rnd: int = 0
    sig: list | None = None

    def key(self, cid: str, chapter: int) -> tuple:
        c = CASE_ROW[cid]
        shown = tuple(ACT[v - 1] for v in (self.s1, self.s2) if v > 0)
        if self.act == 4:  # tail: the engine shows basis script and the second claim (read side)
            return ("scorched", "clear", ("scorched",), "", 0, "script", c["t"], 0)
        lit = c[f"n{self.lit}"] if self.lit else ""
        return (ACT[self.act] if self.act >= 0 else "?", ["clear", "fuzzy"][self.clar], shown,
                ACT[self.star - 1] if self.star else "", self.star_rule, G.BASIS[self.basis], lit, self.rule)


def decode(run: dict, tags: list[str]) -> dict[str, Dec]:
    decs: dict[str, Dec] = {}
    m, sg = [int(v) for v in run["m"]], [int(v) for v in run["s"]]
    for i in range(0, len(m), 2):
        tag = tags[m[i] - 1]
        d = unpack(m[i + 1], M_PACK)
        decs[tag] = Dec(tag, d["da"] - 1, d["dlit"], d["dcl"], d["ds1"], d["ds2"], d["dst"], d["dsr"], d["db"],
                        d["dru"], d["dln"] - 1, d["pln"] - 1, d["r"])
    n = 1 + len(S_PACK)
    for i in range(0, len(sg), n):
        tag = tags[sg[i] - 1]
        f: dict = {}
        for grp, v in zip(S_PACK, sg[i + 1:i + n]):
            f.update(unpack(v, grp))
        if tag in decs:
            decs[tag].sig = [str(f[k]) if k in SIG_NUM else (VOCAB[f[k] - 1] if f[k] > 0 else "") for k in REC_SIG]
    return decs


# ------------------------------------------------------------------------------------------------- checks

class Rules:
    def __init__(self) -> None:
        self.n = Counter()
        self.fail: list[str] = []

    def check(self, cat: str, ok: bool, msg: str) -> None:
        self.n[cat] += 1
        if not ok:
            self.n[cat + " FAIL"] += 1
            if len(self.fail) < 40:
                self.fail.append(f"{cat}: {msg}")


def visible(state) -> set[str]:
    return {n.id for n in state.nodes if n.kind in ("normal", "last_stand", "second_claim")}


def hard_rules(rules: Rules, d: Dec, state, cid: str, chapter: int, dist: dict, script_row: dict | None) -> None:
    """Rule assertions on one decision, from the rules themselves (A-3, B11-B13, 4.4) and the ref support."""
    case = state.case
    prof = case.opponent
    key = d.key(cid, chapter)
    rules.check("in ref support", key in dist, f"{d.tag}: {key} impossible in ref")
    if state.in_tail:
        rules.check("tail scorched", d.act == 4, f"{d.tag}: tail action {d.act}")
    else:
        avail = {CODE[a] for a in prof.available}
        banned = set()
        if state.no_reinforce_next or (case.konju_enabled and state.konju_left > 0):
            banned.add(2)
        h = state.opp_history
        if 5 in prof.rules and len(h) >= 2 and h[-1] == h[-2]:
            banned.add(CODE[h[-1]])
        rules.check("action available, not banned", d.act in avail and d.act not in banned,
                    f"{d.tag}: act {d.act} avail {avail} banned {banned}")
        if 3 in prof.rules and state.rule3_pending:
            rules.check("rule 3 forced rush clear", (d.act, d.clar, G.BASIS[d.basis]) ==
                        (1, 0, "tutorial" if prof.tutorial_clear else "rule3"), f"{d.tag}")
        elif state.must_attack_next:
            rules.check("must attack clear", d.act in (0, 1) and d.clar == 0 and G.BASIS[d.basis] == "observe",
                        f"{d.tag}")
        if prof.tutorial_clear:
            rules.check("tutorial clear", d.clar == 0 and G.BASIS[d.basis] == "tutorial", f"{d.tag}")
        if d.clar == 1:
            shown = [d.s1 - 1, d.s2 - 1]
            rules.check("fuzzy = action + 1 legal decoy", d.act in shown and shown[0] != shown[1]
                        and all(a in avail and a not in banned for a in shown), f"{d.tag}: {shown}")
        else:
            rules.check("clear shows the action", d.s1 - 1 == d.act and d.s2 == 0, f"{d.tag}")
        if d.star:
            rules.check("star only fuzzy, rules 1/2/4, shown", d.clar == 1 and d.star_rule in (1, 2, 4)
                        and d.star in (d.s1, d.s2), f"{d.tag}")
        if d.clar == 1 and not d.star:
            # no star -> no tendency rule applied (its action is not deleted)
            rules.check("no star -> no tendency rule", d.rule in (0, 3), f"{d.tag}: rule {d.rule}")
        lit = CASE_ROW[cid][f"n{d.lit}"] if d.lit else ""
        rules.check("lit visible, not fragile", lit in {R.node_id(chapter, v) for v in visible(state)},
                    f"{d.tag}: {lit}")
    # line: from the action's group, never the previous line
    grp = [i for i, r in enumerate(LINES) if r["case"] == cid and r["code"] == d.act]
    rules.check("line in the action's group", d.line in grp, f"{d.tag}: line {d.line} group {grp}")
    if len(grp) > 1:
        rules.check("line != previous line", d.line != d.prev_line, f"{d.tag}: {d.line}")
    # the tell outputs: the decision, or the script row when there is one (A-11)
    if d.sig is not None:
        s = dict(zip(REC_SIG, d.sig))
        c = CASE_ROW[cid]
        gest = [c["g0"], c["g1"], c["g2"], c["g3"], ""]
        if script_row:
            want = [script_row["clarity"], script_row["shown1"], script_row["shown2"], script_row["star"],
                    str(script_row["starRule"]), script_row["basis"], script_row["lit"],
                    gest[ACT.index(script_row["action"])], script_row["lineKey"], "0"]
        else:
            k = d.key(cid, chapter)
            want = [k[1], k[2][0], k[2][1] if len(k[2]) > 1 else "", k[3], str(k[4]), k[5], k[6], gest[d.act],
                    LINES[d.line]["id"] if d.line >= 0 else "", str(0 if d.act == 4 else d.rule)]
        got = [s[x] for x in REC_SIG[:-1]]
        rules.check("tell outputs" + (" = script row" if script_row else " = decision"), got == want,
                    f"{d.tag}: got {got} want {want}")


def z_cells(obs: Counter, n: int, exp: dict) -> list[tuple]:
    rows = []
    for k in sorted(set(obs) | set(exp), key=lambda k: (-float(exp.get(k, 0)), str(k))):
        p = float(exp.get(k, 0))
        o = obs.get(k, 0)
        if p in (0.0, 1.0):
            z = 0.0 if o == round(p * n) else math.inf
        else:
            z = (o - n * p) / math.sqrt(n * p * (1 - p))
        rows.append((k, p, o / n, z))
    return rows


def fmt_key(k) -> str:
    if isinstance(k, tuple) and len(k) == 8:
        act, clar, shown, star, sr, basis, _lit, rule = k
        tell = "/".join(s + ("*" + str(sr) if s == star else "") for s in shown)
        return f"{act:<9} {clar:<5} {tell:<22} {basis or '-':<8} r{rule}"
    return str(k)


def main(argv: list[str]) -> int:
    samples = int(argv[argv.index("--samples") + 1]) if "--samples" in argv else 4000
    seeds = int(argv[argv.index("--seeds") + 1]) if "--seeds" in argv else 4
    verbose = "--verbose" in argv
    per_run = samples // seeds

    t0 = time.perf_counter()
    for path, text in G.outputs().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    sc, sits, plays = build(per_run)
    ticks = write_harness(sc)
    t_gen = time.perf_counter() - t0
    t1 = time.perf_counter()
    runs = run_all(ticks, seeds)
    t_run = time.perf_counter() - t1
    decs = [decode(r, sc.tags) for r in runs]
    print(f"engine: {G.graph_stats()['debate_engine'][0]} nodes; harness {ticks} ticks x {seeds} seeds "
          f"(--seed 1..{seeds}, in parallel); generate {t_gen:.1f} s, run {t_run:.1f} s")

    rules = Rules()
    failed = 0
    summary = []
    print("\n== situations (observed vs exact ref probability, |z| <= 4; cell tables with --verbose or on failure) ==")
    for st, state, cid in sits:
        dist = distribution(state, st.chapter)
        script_row = None
        if st.script_next:
            script_row = st.script_next
        samples_d = []
        for run in decs:
            for tag, d in run.items():
                if tag.split(":")[0] == st.name:
                    samples_d.append(d)
                    rules.check("record timing (round)", d.rnd == len(st.moves) + 1, f"{tag}: round {d.rnd}")
                    hard_rules(rules, d, state, cid, st.chapter, dist, script_row)
        n = len(samples_d)
        obs_tell = Counter(tuple(d.key(cid, st.chapter)[:6]) + (d.key(cid, st.chapter)[7],) for d in samples_d)
        exp_tell: dict = defaultdict(float)
        exp_lit: dict = defaultdict(float)
        exp_act: dict = defaultdict(float)
        for k, p in dist.items():
            exp_tell[k[:6] + (k[7],)] += p
            exp_lit[k[6]] += p
            exp_act[k[0]] += p
        obs_lit = Counter(d.key(cid, st.chapter)[6] for d in samples_d)
        # lines: uniform over the action's group without the previous line
        prev = LINE_ROW.get(st.line_key, -1)
        exp_line: dict = defaultdict(float)
        for a, p in exp_act.items():
            grp = [i for i, r in enumerate(LINES) if r["case"] == cid and r["code"] == ACT.index(a)]
            cand = [i for i in grp if i != prev] if len(grp) > 1 else grp
            for i in cand:
                exp_line[LINES[i]["id"]] += p / len(cand)
        obs_line = Counter(LINES[d.line]["id"] if d.line >= 0 else "" for d in samples_d)
        worst = 0.0
        lines_out = [f"{st.name} (N={n}): {st.why}"]
        for label, obs, exp in (("tell", obs_tell, exp_tell), ("lit", obs_lit, exp_lit), ("line", obs_line, exp_line)):
            for k, p, f, z in z_cells(obs, n, exp):
                worst = max(worst, abs(z))
                mark = "" if abs(z) <= Z_MAX else "  <-- FAIL"
                lines_out.append(f"    {label:<4} {fmt_key(k) if label == 'tell' else k:<52} exp {p:7.4f}  obs {f:7.4f}"
                                 f"  z {z:+6.2f}{mark}")
        ok = worst <= Z_MAX and n == samples
        if not ok:
            failed += 1
        obs_act = Counter(ACT[d.act] for d in samples_d)
        fz_exp = sum(float(p) for k, p in dist.items() if k[1] == "fuzzy")
        fz_obs = sum(1 for d in samples_d if d.clar == 1) / max(1, n)
        acts = " ".join(f"{a} {float(exp_act.get(a, 0)):.3f}/{obs_act.get(a, 0) / max(1, n):.3f}"
                        for a in ACT if exp_act.get(a, 0) or obs_act.get(a, 0))
        summary.append((st.name, n, len(dist), worst, ok, f"{acts}; fuzzy {fz_exp:.3f}/{fz_obs:.3f}"))
        if verbose or not ok:
            print("\n".join(lines_out))

    print("\n== free play (engine decisions replayed in ref) ==")
    for fp in FREE:
        rounds = trunc = 0
        acts = Counter()
        for run in decs:
            for f2, d_i, moves in plays:
                if f2 is not fp:
                    continue
                s = initial_state(fp.case_fn(), fp.board)
                cid = R.CASE_ID[fp.chapter]
                valid = []
                for r, p in enumerate(moves, start=1):
                    d = run.get(f"{fp.name}:{d_i}:{r - 1}")
                    if d is None or s.over:
                        break
                    dist = distribution(s, fp.chapter)
                    rules.check("record timing (round)", d.rnd == r, f"{d.tag}: round {d.rnd}")
                    hard_rules(rules, d, s, cid, fp.chapter, dist, None)
                    valid.append(d)
                    acts[ACT[d.act]] += 1
                    if d.act == 4:
                        o = OpponentAction(OA.ALL_IN, s.case.tail.second_claim.id, True)
                    else:
                        lit_short = next((n.id for n in s.nodes if R.node_id(fp.chapter, n.id) ==
                                          CASE_ROW[cid][f"n{d.lit}"]), None) if d.lit else None
                        o = OpponentAction([OA.CLAIM, OA.RUSH, OA.REINFORCE, OA.TRAP][d.act], lit_short)
                    if d.rule == 3:
                        s = replace(s, rule3_pending=False)
                    try:
                        s, _ = resolve_round(s, p, o)
                        rounds += 1
                    except IllegalAction as e:
                        opp = "opponent" in str(e) or "cannot use" in str(e)
                        rules.check("opponent action legal in ref", not opp, f"{fp.name}:{d_i}:{r}: {e}")
                        trunc += 1
                        break
                # the line of consecutive rounds (signals of round r vs r-1)
                prev = None
                for d in valid:
                    line = d.sig[REC_SIG.index("debTellLine")] if d.sig else None
                    if prev is not None and d.act != 4:
                        rules.check("free play: tell line never repeats", line != prev, d.tag)
                    prev = line
        print(f"{fp.name}: {fp.debates} debates x {seeds} seeds, {rounds} rounds replayed in ref, "
              f"{trunc} stopped at a player move ref rejects; actions {dict(acts)}")

    print("\n== summary ==")
    print(f"{'situation':<26} {'N':>5} {'outcomes':>8} {'max|z|':>7}       action and fuzzy share: expected/observed")
    for name, n, k, worst, ok, marg in summary:
        print(f"{name:<26} {n:>5} {k:>8} {worst:>7.2f} {'PASS' if ok else 'FAIL'}  {marg}")
    print("\n== rule assertions ==")
    for cat in sorted(c for c in rules.n if not c.endswith(" FAIL")):
        bad = rules.n.get(cat + " FAIL", 0)
        print(f"{cat:<44} {rules.n[cat]:>7} checked, {bad} failed")
    for f in rules.fail:
        print("FAIL " + f)
    if rules.fail:
        failed += 1
    if any(r["stderr"].strip() for r in runs):
        print("FAIL stderr not empty")
        failed += 1
    print(f"{len(summary) - sum(1 for x in summary if not x[4])}/{len(summary)} situations pass; "
          f"{'ok' if not failed else 'FAIL'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
