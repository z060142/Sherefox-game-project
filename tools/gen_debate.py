# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generate the debate (論戰) engine: flows/debate_engine.xtflow, flows/debate_warmup.xtflow and the engine's
derived tables under data/debate/ (from data/*.json). See docs/debate-engine.md for the interface and the design.

Usage (from the project root):
    uv run tools/gen_debate.py            write the flows and tables
    uv run tools/gen_debate.py --check    exit 1 if any generated file differs

The module is also imported by tests/check_debate.py, which builds the headless harness project
(tests/debate_harness/) with build_harness().

How a round is computed (docs/debate-engine.md §3): the live state is the number map `debState` (one key per
variable). A collection query reads the map as it was at the start of the tick (an effect earlier in the tick shows
at the next evaluation, 08 §8.3.2), so the whole round, 系統規格 A-1 steps 1-5 plus the restate of the next round, is
one pure function (a DAG of atrium.expr / select / table / collection queries) of that state, the round's command
and the opponent action (tail, script row, or the policy decision stored at the previous lock). `world.debLock` then
runs the effects in edge order (05 §5.4): the event records, the board-node list operations, the 7 atrium.rng draws of
the next round's policy decision (decide(), §3.4), and finally one map.set per state variable with its next value.
Nothing in a round reads its own writes, so there is no cycle in the graph.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLOWS = ROOT / "flows"
DATA = ROOT / "data"
DEB_DATA = DATA / "debate"

# --------------------------------------------------------------------------------------------- derived tables

# Constants that are not columns of data/*.json; each names its source (docs/debate-engine.md §5).
KONJU_MUL = Fraction(5, 4)  # 01-systems A-15 困獸: opponent claim x1.25 (ruling B10 order)
SHAKEN_MUL = Fraction(3, 2)  # 01-systems A-1 動搖 x1.5
IMPATIENCE_ROUND = 15  # 02-numbers 五: 聽眾不耐 from round 15
IMPATIENCE_ADD = 5  # +5 (ruling B10 order)
VOID_PCT = 25  # 01-systems A-9: break voided -> 25% of max
KONJU_HP_PCT = 30  # 01-systems A-15: 困獸 at <= 30%
RULE3_PCT = 50  # ruling B9: rule 3 at <= 50%
KONJU_ROUNDS = 2  # 01-systems A-15
CH1_BREAK_CARD = "E01_03"  # 各章設計 Ch.1: break = E01_03 with the right reason (ref fixtures ch1_case)
GOLDEN_PRIMARY = {"CH03_MAIN": ("E03_04", "G-01")}  # 各章設計 Ch.3 / ruling B17 (ref fixtures ch3_case)


def _load(name: str) -> list[dict]:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


def _split(cell: str) -> list[str]:
    return [x for x in cell.split(",") if x]


def derive_tables() -> dict[str, list[dict]]:
    opponents = _load("opponents")
    chapters = {r["id"]: r for r in _load("chapters")}
    nodes = _load("nodes")
    evidence = _load("evidence")
    standard = next(r for r in _load("difficulty") if r["id"] == "standard")
    tells = _load("tells")

    case_rows, card_rows, node_rows, line_rows = [], [], [], []
    for o in opponents:
        cid, ch = o["id"], chapters[o["chapter"]]
        states = set(_split(ch["states"]))
        own = [n for n in nodes if n["case"] == cid]
        pool = sorted((n for n in own if n["kind"] in ("claim", "warmup")), key=lambda n: n["idx"])
        if len(pool) > 3:
            raise SystemExit(f"{cid}: the engine models at most 3 pool nodes (has {len(pool)})")
        pool_ids = [n["id"] for n in pool] + [""] * (3 - len(pool))
        rush = Fraction(str(o["rushMul"]))
        gp = GOLDEN_PRIMARY.get(cid, ())
        hp_model = not o["noDamage"]
        if o["kind"] != "warmup" and o["disguise"]:
            raise SystemExit(f"{cid}: disguise tells are not modelled (ref policy: outside Ch.1-3)")
        rules = {int(x) for x in _split(o["rules"])}
        # tell lines (系統規格 4.4 預兆顯示): per action code the group of the tells table; scorched = the tail's
        # endgame lines. Rows of one group are contiguous in debLine: [lb, lb + lc).
        lb, lc = [], []
        for code, act in enumerate(OA_NAMES):
            cat = "endgame" if act == "scorched" else "tell"
            grp = sorted((t for t in tells if t["case"] == cid and t["category"] == cat and t["action"] == act
                          and not t["inactive"]), key=lambda t: t["n"])
            lb.append(len(line_rows))
            lc.append(len(grp))
            line_rows += [{"id": t["id"], "case": cid, "code": code, "n": i} for i, t in enumerate(grp)]
        case_rows.append({
            "id": cid, "kind": o["kind"], "chapter": o["chapter"],
            "hp": int(hp_model), "pMax": o["playerHp"] if hp_model else 0, "oMax": o["hp"] if hp_model else 0,
            "cap": o["nodeCap"], "base": o["damageBase"], "per": o["damagePerNode"],
            "rushN": rush.numerator, "rushD": rush.denominator,
            "kjN": KONJU_MUL.numerator, "kjD": KONJU_MUL.denominator,
            "shN": SHAKEN_MUL.numerator, "shD": SHAKEN_MUL.denominator,
            "impR": IMPATIENCE_ROUND, "impA": IMPATIENCE_ADD,
            "counter": standard["parryCounter"], "heal": standard["reinforceHealPct"], "crit": standard["trapCrit"],
            "brPct": ch["breakPct"], "brChain": ch["breakChain"], "brStrong": ch["breakStrong"], "brLine": ch["breakLine"],
            "tw": ch["tailPenalty"], "tr": ch["tailRounds"], "voidPct": VOID_PCT,
            "kjHp": KONJU_HP_PCT, "r3": RULE3_PCT, "kjR": KONJU_ROUNDS, "shR": standard["shakenRounds"],
            # 破竹 mode: 2 on, 1 preview (Ch.1 shows the gauge only, 01-systems A-15 共通), 0 off
            "hk": 2 if "hachiku" in states else (1 if o["chapter"] == 1 else 0),
            "kjOn": int("konju" in states), "ssOn": int("shisshu" in states),
            "soph": int(ch["sophistryReads"]),
            "assists": standard["assists"] if ch["assistUnlocked"] else 0, "fox": standard["instinct"],
            "hasTail": int(bool(o["tail"])), "ch1": int(o["kind"] == "pudding"),
            "brCard": CH1_BREAK_CARD if o["kind"] == "pudding" else "",
            "conT": o["contraTarget"], "conD": o["contraDeadline"], "rcap": o["roundLimit"],
            "mis": o["mistakeLimit"],
            "gpN": len(gp), "gp1": gp[0] if gp else "", "gp2": gp[1] if len(gp) > 1 else "",
            "n1": pool_ids[0], "n2": pool_ids[1], "n3": pool_ids[2], "t": o["tailNode"],
            "g0": o["gestureAssert"], "g1": o["gestureRush"], "g2": o["gestureReinforce"], "g3": o["gestureTrap"],
            # opponent policy (A-3, 數值總表 四, ref policy.py): personality weights (an action with weight 0 is not
            # available, e.g. Ch.1 Arthur 25/0/50/0, ruling D7), clarity mix, behaviour rules 1..5, the tendency
            # follow percentage, tutorial clarity (Ch.1: every tell clear, basis tutorial), tell line groups
            "w0": o["w_claim"], "w1": o["w_rush"], "w2": o["w_reinforce"], "w3": o["w_trap"],
            "cC": o["clear"], "cF": o["fuzzy"], "tut": int(o["kind"] == "pudding"), "fol": o["ruleBias"],
            **{f"ru{i}": int(i in rules) for i in range(1, 6)},
            **{f"lb{i}": lb[i] for i in range(5)}, **{f"lc{i}": lc[i] for i in range(5)},
        })
        for n in own:
            idx = n["idx"] if n["kind"] in ("claim", "warmup") else 0
            cats = {t.split(":", 1)[0] for t in _split(n["tags"])}
            node_rows.append({
                "id": n["id"], "case": cid, "kind": n["kind"], "idx": idx,
                "key": f"{cid}:{idx}" if idx else f"{cid}:T",
                "ps": int(bool(cats & {"person", "scandal"})),
            })
        for e in evidence:
            if str(o["chapter"]) not in _split(e["usable"]):
                continue
            refutes = set(_split(e["refutes"]))
            card_rows.append({
                "key": f"{cid}:{e['id']}", "card": e["id"],
                "r1": int(pool_ids[0] in refutes), "r2": int(pool_ids[1] in refutes), "r3": int(pool_ids[2] in refutes),
                "rT": int(bool(o["tailNode"]) and o["tailNode"] in refutes),
                "strong": int(e["strong"]), "scandal": int(e["scandal"]),
                "brk": int(o["kind"] == "pudding" and e["id"] == CH1_BREAK_CARD),
                "gp": int(e["id"] in gp), "goldenId": e["id"] if e["grade"] == "golden" else "",
            })
    codes = [{"id": k, "code": i} for i, k in enumerate(PA_NAMES + OA_NAMES)]
    return {"debCase": case_rows, "debCard": card_rows, "debNode": node_rows, "debCode": codes, "debLine": line_rows}


# Command / action vocabulary = the data tables' (opponents.playerActions, tells.action).
PA_NAMES = ["solid", "sophistry", "rebut", "observe"]  # codes 0..3
OA_NAMES = ["assert", "rush", "reinforce", "trap", "scorched"]  # codes 0..4 (debCode row - 4)

# --------------------------------------------------------------------------------------------- interface

# world.* signals of the engine (docs/debate-engine.md §2). Inputs first, then outputs.
SIGNALS: dict[str, dict] = {
    # inputs
    "debCase": {"type": "string", "initial": ""},
    "debScript": {"type": "string", "initial": ""},
    "debStart": {"type": "pulse"},
    "debLock": {"type": "pulse"},
    "debInstinct": {"type": "pulse"},
    "debRedecide": {"type": "pulse"},
    "debCmdKind": {"type": "string", "initial": ""},
    "debCmdFrom": {"type": "number", "initial": -1},
    "debCmdTo": {"type": "number", "initial": -1},
    "debCmdCard": {"type": "string", "initial": ""},
    "debCmdTarget": {"type": "string", "initial": ""},
    "debCmdAssist": {"type": "number", "initial": 0},
    # 01-systems §1.8 / A-1, ruling D4: added to the opponent's start and max HP (missed cards x hpPerMissed); read at
    # debStart and every round (keep it unchanged through the debate)
    "debOppBonus": {"type": "number", "initial": 0},
    # outputs (main debate)
    "debPhase": {"type": "string", "initial": "idle"},
    "debRound": {"type": "number", "initial": 0},
    "debHpModel": {"type": "number", "initial": 0},
    "debPlayerHp": {"type": "number", "initial": 0},
    "debPlayerMax": {"type": "number", "initial": 0},
    "debOppHp": {"type": "number", "initial": 0},
    "debOppMax": {"type": "number", "initial": 0},
    "debShaken": {"type": "number", "initial": 0},
    "debInTail": {"type": "number", "initial": 0},
    "debTailLeft": {"type": "number", "initial": 0},
    "debVoids": {"type": "number", "initial": 0},
    "debHachiku": {"type": "number", "initial": 0},
    "debHachikuMode": {"type": "number", "initial": 0},
    "debKonju": {"type": "number", "initial": 0},
    "debShisshu": {"type": "number", "initial": 0},
    "debParries": {"type": "number", "initial": 0},
    "debContra": {"type": "number", "initial": 0},
    "debInfamy": {"type": "number", "initial": 0},
    "debAssist": {"type": "number", "initial": 0},
    "debInstinctLeft": {"type": "number", "initial": 0},
    "debOver": {"type": "number", "initial": 0},
    "debOutcome": {"type": "string", "initial": ""},
    "debBreakLabel": {"type": "string", "initial": ""},
    "debGoldenUsed": {"type": "number", "initial": 0},
    "debFragile": {"type": "number", "initial": 0},
    "debTellClarity": {"type": "string", "initial": ""},
    "debTellShown1": {"type": "string", "initial": ""},
    "debTellShown2": {"type": "string", "initial": ""},
    "debTellStar": {"type": "string", "initial": ""},
    "debTellBasis": {"type": "string", "initial": ""},
    "debTellLit": {"type": "string", "initial": ""},
    "debTellGesture": {"type": "string", "initial": ""},
    "debTellLine": {"type": "string", "initial": ""},
    "debTellStarRule": {"type": "number", "initial": 0},
    "debTellRule": {"type": "number", "initial": 0},
    # M5c: for the debate UI (the opponent notes, the status line, the result's 讀對預兆)
    "debReads": {"type": "number", "initial": 0},
    "debNoReinf": {"type": "number", "initial": 0},
    "debMustAtk": {"type": "number", "initial": 0},
    # outputs (warmup, A-13)
    "dwActive": {"type": "number", "initial": 0},
    "dwRound": {"type": "number", "initial": 0},
    "dwIndex": {"type": "number", "initial": 0},
    "dwClaim": {"type": "string", "initial": ""},
    "dwMistakes": {"type": "number", "initial": 0},
    "dwOver": {"type": "number", "initial": 0},
    "dwAuto": {"type": "number", "initial": 0},
    "dwTrustDelta": {"type": "number", "initial": 0},
    "dwReward": {"type": "number", "initial": 0},
}

BOARD_SLOTS = 24  # 3 chains x 5 slots (0..14) + 9 loose cards (15..23)
COLLECTIONS: dict[str, dict] = {
    "debState": {"kind": "map", "type": "number", "capacity": 64},
    "dwState": {"kind": "map", "type": "number", "capacity": 16},
    "debOn": {"kind": "list", "type": "string", "capacity": 16},
    "debEvents": {"kind": "list", "type": "string", "capacity": 64},
    "debBoard": {"kind": "list", "type": "string", "capacity": BOARD_SLOTS},
    "debBoardOk": {"kind": "list", "type": "number", "capacity": BOARD_SLOTS},
    "debBoardLink": {"kind": "list", "type": "number", "capacity": BOARD_SLOTS},
    "debSnap": {"kind": "map", "type": "number", "capacity": 32},
    "debAssisted": {"kind": "map", "type": "number", "capacity": 32},
}
TABLES = {name: f"data/debate/{name}.json" for name in ("debCase", "debCard", "debNode", "debCode", "debLine")}
SCRIPT_TABLE = "debScript"  # supplied by the game (or the harness): one row per scripted round
SCRIPT_COLUMNS = ["key", "action", "lit", "scripted", "clarity", "shown1", "shown2", "star", "starRule", "basis",
                  "lineKey"]  # docs/debate-engine.md §2.4; declared, so a script without rows still has its columns


def script_table(rel: str) -> dict:
    """The game.json declaration of the script table at `rel` (08 §8.2.1 object form)."""
    return {"file": rel, "columns": SCRIPT_COLUMNS}

# debState keys (docs/debate-engine.md §3.2): name -> meaning. All default to 0 after map.clear except the inits.
STATE_KEYS = {
    "act": "a main debate is running", "r": "round", "php": "player HP", "ohp": "opponent HP",
    "g1": "pool node 1 off the board", "g2": "pool node 2 off the board", "g3": "pool node 3 off the board",
    "flo": "fragile nodes consumed (F1..Fflo gone)", "fseq": "fragile nodes created",
    "sh": "shaken 0 none / 1 armed / 2 held", "tail": "in tail", "tl": "tail rounds left", "voids": "break voids",
    "hk": "hachiku stacks", "kj": "konju rounds left", "kjp": "konju parry condition used",
    "kjh": "konju HP condition used", "par": "intercepts", "ss": "shisshu rounds left", "as": "assists left",
    "fox": "fox instinct left", "foxr": "round the instinct was used in", "inf": "infamy", "con": "contradictions",
    "over": "debate over", "out": "outcome 0 none / 1 win / 2 loss / 3 unachieved",
    "lbl": "break label 0 / 1 primary / 2 alternative", "gold": "golden clue used in a break",
    "lnr": "rule 1: last round removed a node", "lrs": "rule 4: last reinforce succeeded",
    "nrn": "no reinforce next", "man": "must attack next", "r3f": "rule 3 fired", "r3p": "rule 3 pending",
    "nco": "next tell clear (observe)", "h1": "last opponent action + 1", "h2": "the one before + 1",
    "lpa": "last player action + 1", "soph": "sophistry counts as a 破竹 read vs reinforce",
    "pln": "tell line row (debLine) + 1 shown in the round just resolved (never-same-line rule)",
    "rd": "reads: rounds answered favourably (A-15 破竹 definition, ref resolve `right`; a tail round: correct)",
}
# the opponent's decision for the coming round (A-3, ref policy.decide_next), drawn at debStart / debLock /
# debRedecide (docs/debate-engine.md §3.4); read when the round has neither a tail nor a script row
DEC_KEYS = {
    "da": "action code 0 assert / 1 rush / 2 reinforce / 3 trap / 4 scorched", "dlit": "lit pool node 1..3 (0 none)",
    "dcl": "clarity 0 clear / 1 fuzzy", "ds1": "shown action 1 + 1", "ds2": "shown action 2 + 1 (fuzzy; 0 none)",
    "dst": "star action + 1 (0 none)", "dsr": "star rule 1/2/4 (0 none)", "db": "basis code (BASIS)",
    "dru": "rule applied 1..4 (0 none; for the opponent notes)", "dln": "tell line row (debLine) + 1 (0 none)",
}
BASIS = ["", "tutorial", "observe", "rule3", "konju"]  # db codes; the tail shows "script", the instinct "fox"
INIT_KEYS = ("act", "r", "php", "ohp", "as", "fox", "soph")


# --------------------------------------------------------------------------------------------- graph DSL

FUNCS = {"abs", "floor", "ceil", "round", "trunc", "sqrt", "min", "max", "clamp", "lerp", "sign"}
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class Graph:
    """A flow under construction. `v` maps a value name to its source port; `x()` builds an atrium.expr whose
    identifiers are value names (wired automatically)."""

    def __init__(self) -> None:
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self._ids: set[str] = set()
        self.v: dict[str, str] = {}
        self._consts: dict[str, str] = {}
        self._exprs: set[str] = set()

    def node(self, node_id: str, node_type: str, **params) -> str:
        if node_id in self._ids:
            raise ValueError(f"duplicate node id {node_id}")
        self._ids.add(node_id)
        n: dict = {"id": node_id, "type": node_type}
        if params:
            n["params"] = params
        self.nodes.append(n)
        return node_id

    def edge(self, src: str, dst: str) -> None:
        self.edges.append({"from": src, "to": dst})

    def const(self, value) -> str:
        """A shared constant node; returns its output port."""
        key = json.dumps(value)
        if key not in self._consts:
            nid = f"k{len(self._consts)}"
            self.node(nid, "constant", value=value)
            self._consts[key] = f"{nid}.out"
        return self._consts[key]

    def src(self, name_or_port: str) -> str:
        return self.v.get(name_or_port, name_or_port)

    def x(self, name: str, expr: str) -> str:
        """atrium.expr `name` = expr; every identifier must be a value name."""
        self.node(name, "atrium.expr", expr=expr)
        self._exprs.add(name)
        seen = set()
        for ident in IDENT.findall(expr):
            if ident in FUNCS or ident in seen:
                continue
            seen.add(ident)
            if ident not in self.v:
                raise KeyError(f"{name}: unknown value '{ident}' in '{expr}'")
            self.edge(self.v[ident], f"{name}.{ident}")
        self.v[name] = f"{name}.value"
        return self.v[name]

    def truth(self, name: str, num: str) -> str:
        """bool `name` = (number value != 0), for guards and select conditions: an expression's own truth output
        (08 §8.5a), else a compare node."""
        src = self.src(num)
        if src.endswith(".value") and self._is_expr(src[: -len(".value")]):
            return src[: -len(".value")] + ".truth"
        self.node(name, "compare", op="ne")
        self.edge(self.src(num), f"{name}.a")
        self.edge(self.const(0), f"{name}.b")
        return f"{name}.out"

    def _is_expr(self, node_id: str) -> bool:
        return node_id in self._exprs

    def sel(self, name: str, cond_num: str, a: str, b: str) -> str:
        """select `name` = cond_num != 0 ? a : b (a, b: ports or value names of the same type)."""
        c = self.truth(name + "_c", cond_num)
        self.node(name, "select")
        self.edge(c, f"{name}.cond")
        self.edge(self.src(a), f"{name}.a")
        self.edge(self.src(b), f"{name}.b")
        self.v[name] = f"{name}.out"
        return self.v[name]

    def streq(self, name: str, a: str, b: str, op: str = "eq") -> str:
        """number `name` = (string a op string b) as 0/1."""
        self.node(name + "_c", "compare", op=op)
        self.edge(self.src(a), f"{name}_c.a")
        self.edge(self.src(b), f"{name}_c.b")
        self.node(name, "select")
        self.edge(f"{name}_c.out", f"{name}.cond")
        self.edge(self.const(1), f"{name}.a")
        self.edge(self.const(0), f"{name}.b")
        self.v[name] = f"{name}.out"
        return self.v[name]

    def fmt(self, name: str, fmt: str, *args: str) -> str:
        self.node(name, "format", format=fmt)
        for slot, a in zip("abcd", args):
            self.edge(self.src(a), f"{name}.{slot}")
        self.v[name] = f"{name}.out"
        return self.v[name]

    def lookup(self, name: str, values: list, index: str) -> str:
        self.node(name, "lookup", values=values)
        self.edge(self.src(index), f"{name}.index")
        self.v[name] = f"{name}.out"
        return self.v[name]

    def tget(self, name: str, table: str, column: str, row: str, typ: str = "number") -> str:
        self.node(name, "atrium.table.get", table=table, column=column, type=typ)
        self.edge(self.src(row), f"{name}.row")
        self.v[name] = f"{name}.value"
        return self.v[name]

    def tfind(self, name: str, table: str, column: str, value: str) -> str:
        self.node(name, "atrium.table.find", table=table, column=column)
        self.edge(self.src(value), f"{name}.value")
        self.v[name] = f"{name}.row"
        return self.v[name]

    def cond_gate(self, node_id: str, cond_num: str) -> tuple[str, str]:
        """A pulse gate on a number (atrium.gate, 08 §8.5a: passes while it is non-zero); returns (input, output)."""
        self.node(node_id, "atrium.gate")
        self.edge(self.src(cond_num), f"{node_id}.cond")
        return f"{node_id}.trigger", f"{node_id}.pass"

    def gate(self, node_id: str, guard: str) -> tuple[str, str]:
        """A pulse gate (state a<->b on `go`, guard = bool port); returns (input, output)."""
        self.node(node_id, "state", states=["a", "b"], initial="a",
                  transitions=[{"from": "a", "on": "go", "to": "b"}, {"from": "b", "on": "go", "to": "a"}])
        self.edge(guard, f"{node_id}.guard")
        return f"{node_id}.go", f"{node_id}.changed"

    def text(self) -> str:
        return json.dumps({"version": 1, "nodes": self.nodes, "edges": self.edges}, ensure_ascii=False, indent=1) + "\n"


class Cascade:
    """An ordered list of effects run by one pulse: each step is (condition value name or None, [trigger inputs])."""

    def __init__(self, g: Graph, prefix: str) -> None:
        self.g, self.prefix, self.steps, self.n = g, prefix, [], 0

    def on(self, cond: str | None, *triggers: str) -> None:
        self.steps.append((cond, list(triggers)))

    def emit(self, source: str) -> None:
        g = self.g
        for cond, triggers in self.steps:
            if cond is None:
                for t in triggers:
                    g.edge(source, t)
                continue
            self.n += 1
            gid = f"{self.prefix}{self.n}"
            go, out = g.cond_gate(gid, cond)
            g.edge(source, go)
            for t in triggers:
                g.edge(out, t)


def ev(g: Graph, cas: Cascade, name: str, cond: str | None, record: str, *args: str, coll: str = "debEvents") -> None:
    """Append one event record to `coll` when `cond` (value name, number) is non-zero at the cascade."""
    if args:
        value = g.fmt(name, record, *args)
    else:
        value = g.const(record)
    g.node(name + "_add", "atrium.coll.add", name=coll)
    g.edge(value, f"{name}_add.value")
    cas.on(cond, f"{name}_add.trigger")


def cutin(g: Graph, cas: Cascade, name: str, cond: str, cid: str, prio: int, side: str, played: str) -> None:
    """A full-screen cut-in record: played (value name, 0/1) -> level full, else demoted to a stamp (4.7)."""
    recs = [f"cutin|{cid}|stamp|{prio}|{side}|0|1", f"cutin|{cid}|full|{prio}|{side}|1|0"]
    value = g.lookup(name, recs, played)
    g.node(name + "_add", "atrium.coll.add", name="debEvents")
    g.edge(value, f"{name}_add.value")
    cas.on(cond, f"{name}_add.trigger")


def stamp(cid: str, side: str) -> str:
    return f"cutin|{cid}|stamp||{side}|0|0"


def list_op(g: Graph, cas: Cascade, name: str, cond: str | None, op: str, coll: str, value: str | None) -> None:
    g.node(name, f"atrium.coll.{op}", name=coll)
    if value is not None:
        g.edge(g.src(value), f"{name}.value")
    cas.on(cond, f"{name}.trigger")


# --------------------------------------------------------------------------------------------- engine

CASE_NUM = ["hp", "pMax", "oMax", "cap", "base", "per", "rushN", "rushD", "kjN", "kjD", "shN", "shD", "impR", "impA",
            "counter", "heal", "crit", "brPct", "brChain", "brStrong", "brLine", "tw", "tr", "voidPct", "kjHp", "r3",
            "kjR", "shR", "hk", "kjOn", "ssOn", "soph", "assists", "fox", "hasTail", "ch1", "conT", "conD", "rcap",
            "mis", "gpN"]
POLICY_NUM = ["w0", "w1", "w2", "w3", "cC", "cF", "tut", "fol", "ru1", "ru2", "ru3", "ru4", "ru5",
              "lb0", "lb1", "lb2", "lb3", "lb4", "lc0", "lc1", "lc2", "lc3", "lc4"]  # main engine only
CASE_STR = ["kind", "brCard", "gp1", "gp2", "n1", "n2", "n3", "t", "g0", "g1", "g2", "g3"]
CARD_NUM = ["r1", "r2", "r3", "rT", "strong", "scandal", "brk", "gp"]
SEG = 5  # max segment length (系統規格 2.5: chains of 2..5 cards)


def case_inputs(g: Graph, extra=()) -> None:
    g.tfind("caseRow", "debCase", "id", "world.debCase")
    for c in CASE_NUM + list(extra):
        if c == "oMax":  # + the missed-card bonus (debOppBonus, ruling D4) in HP debates
            g.tget("c_oMax0", "debCase", c, "caseRow")
            g.v["oBonus"] = "world.debOppBonus"
            g.x("c_oMax", "c_oMax0 + (c_hp ? oBonus : 0)")
            continue
        g.tget("c_" + c, "debCase", c, "caseRow")
    for c in CASE_STR:
        g.tget("c_" + c, "debCase", c, "caseRow", "string")


def state_reads(g: Graph, coll: str, keys) -> None:
    for k in keys:
        g.node(f"s_{k}", "atrium.map.get", name=coll)
        g.edge(g.const(k), f"s_{k}.key")
        g.v[f"s_{k}"] = f"s_{k}.value"


def state_commit(g: Graph, cas: Cascade, coll: str, keys, cond: str | None = None, prefix: str = "w") -> None:
    triggers = []
    for k in keys:
        nid = f"{prefix}_{k}"
        g.node(nid, "atrium.map.set", name=coll)
        g.edge(g.const(k), f"{nid}.key")
        g.edge(g.src(f"n_{k}"), f"{nid}.value")
        triggers.append(f"{nid}.trigger")
    cas.on(cond, *triggers)


DRAWS = 7  # atrium.rng draws per decision, u1..u7 (docs/debate-engine.md §3.4)


def decide(g: Graph) -> None:
    """The opponent policy (01-systems A-3, 數值總表 四; ref policy.decide_next, the oracle), as n_<DEC_KEYS>.

    One decision graph serves three entry points through the mode state `dMode` (index 0 lock / 1 start /
    2 redecide), which selects its inputs: at debLock the next state n_* (the round just resolved, restated), at
    debStart the initial state, at debRedecide the stored state s_*. Every entry fires the 7 atrium.rng draws once,
    in a fixed order, whether used or not:
      u1 tendency follow (u * 100 < fol)   u2 action (weighted)   u3 clarity (clear / fuzzy)   u4 fuzzy decoy (weighted)
      u5 fuzzy left/right order            u6 lit node (uniform)   u7 tell line (uniform, never the last line)
    A weighted draw over a set: t = u * sum(w_i), the first i with t < w_0 + .. + w_i (canonical order assert, rush,
    reinforce, trap); this is ref RngChooser's order with u in [0, 1) instead of roll(total).
    """
    x = g.x
    g.node("dMode", "state", states=["lock", "start", "re"], initial="lock",
           transitions=[{"from": a, "on": ev_, "to": b}
                        for a in ("lock", "start", "re")
                        for ev_, b in (("toLock", "lock"), ("toStart", "start"), ("toRe", "re")) if a != b])
    g.edge(g.truth("dModeG", g.const(1)), "dMode.guard")
    g.v["dm"] = "dMode.index"
    g.node("dDraw", "merge")
    for i in range(1, DRAWS + 1):
        g.node(f"u{i}", "atrium.rng")
        g.edge("dDraw.out", f"u{i}.trigger")
        g.v[f"u{i}"] = f"u{i}.value"
    # inputs: (key, start value)
    for k, init in (("r", "1"), ("tail", "0"), ("g1", "c_cap < 1"), ("g2", "c_cap < 2"), ("g3", "c_cap < 3"),
                    ("lnr", "0"), ("lrs", "0"), ("nrn", "0"), ("man", "0"), ("r3p", "0"), ("nco", "0"), ("kj", "0"),
                    ("h1", "0"), ("h2", "0"), ("lpa", "0")):
        x(f"d_{k}", f"dm == 1 ? ({init}) : dm == 2 ? s_{k} : n_{k}")
    x("d_pl", "dm == 1 ? -1 : dm == 2 ? s_pln - 1 : curLine")  # the line shown in the round before

    def pick(name: str, u: str, masks: list[str]) -> str:
        for i, m in enumerate(masks):
            x(f"{name}_a{i}", f"c_w{i} * ({m})")
        x(f"{name}_t", f"{u} * ({name}_a0 + {name}_a1 + {name}_a2 + {name}_a3)")
        a = [f"{name}_a{i}" for i in range(4)]
        return x(name, f"{name}_t < {a[0]} ? 0 : {name}_t < {a[0]} + {a[1]} ? 1"
                       f" : {name}_t < {a[0]} + {a[1]} + {a[2]} ? 2 : {a[3]} > 0 ? 3 : -1")

    # available (weight > 0) and banned actions: rule 5 (the same action twice in a row), 不能補強 (a missed trap),
    # 困獸 (no reinforce, A-15)
    for i in range(4):
        x(f"qAv{i}", f"c_w{i} > 0")
    x("qR5", "c_ru5 && d_h1 > 0 && d_h1 == d_h2 ? d_h1 - 1 : -1")
    x("qBanR", "d_nrn || (c_kjOn && d_kj > 0)")
    for i in range(4):
        x(f"qAl{i}", f"qAv{i} && qR5 != {i}" + (" && !qBanR" if i == 2 else ""))
    # forced rules: rule 3 (first time <= 50%, B9), then the must-attack after an exposed trap
    x("qR3", "c_ru3 && d_r3p && qAv1")
    x("qMA", "!qR3 && d_man")
    x("qMa0", "qAv0 && qR5 != 0")
    x("qMa1", "qAv1 && qR5 != 1")
    x("qMb0", "qMa0 || qMa1 ? qMa0 : qAv0")
    x("qMb1", "qMa0 || qMa1 ? qMa1 : qAv1")
    # tendency rules 1 (node removed -> reinforce), 2 (player sophistry -> trap), 4 (reinforce succeeded -> assert);
    # the lowest number whose action is not deleted wins (A-3)
    x("qT1", "c_ru1 && d_lnr && qAl2")
    x("qT2", "c_ru2 && d_lpa == 2 && qAl3")
    x("qT4", "c_ru4 && d_lrs && qAl0")
    x("qTend", "!qR3 && !qMA")
    x("qTgt", "!qTend ? -1 : qT1 ? 2 : qT2 ? 3 : qT4 ? 0 : -1")
    x("qRule", "qR3 ? 3 : !qTend ? 0 : qT1 ? 1 : qT2 ? 2 : qT4 ? 4 : 0")
    x("qFol", "qTgt >= 0 && u1 * 100 < c_fol")
    # the action: the 20% personality draw includes the rule's own action (B11)
    pick("qPick", "u2", ["qMA ? qMb0 : qAl0", "qMA ? qMb1 : qAl1", "!qMA && qAl2", "!qMA && qAl3"])
    x("qAct0", "qR3 ? 1 : qFol ? qTgt : qPick")
    x("qAct", "d_tail ? 4 : qAct0")
    # clarity (A-3 table): tutorial, forced (basis rule 3 / observe), observe last round, else the case mix;
    # 困獸 turns a fuzzy tell without a basis into clear (basis konju)
    x("qForced", "qR3 || qMA")
    x("qBas0", "c_tut ? 1 : qR3 ? 3 : qMA ? 2 : d_nco ? 2 : 0")
    x("qFz0", "!c_tut && !qForced && !d_nco && u3 * (c_cC + c_cF) >= c_cC")
    x("qKjC", "c_kjOn && d_kj > 0 && qBas0 == 0 && qFz0")
    x("qFz1", "qFz0 && !qKjC")
    x("qBas1", "qKjC ? 4 : qBas0")
    # fuzzy: the true action + 1 decoy. A tendency rule's action always shows with a star (B12): it is the decoy when
    # the action differs; otherwise the decoy is drawn by personality from the other allowed actions
    x("qStar", "qFz1 && qTgt >= 0")
    x("qDS", "qStar && qAct0 != qTgt")
    pick("qDec", "u4", [f"qAl{i} && qAct0 != {i}" for i in range(4)])
    x("qFz", "qFz1 && (qDS || qDec >= 0)")  # no legal decoy -> clear (ref SPEC-QUESTION)
    x("qDecoy", "qDS ? qTgt : qDec")
    x("qSw", "u5 >= 0.5")
    x("qPlain", "d_tail || !qFz")
    x("n_da", "qAct")
    x("n_dcl", "!qPlain")
    x("n_ds1", "qPlain ? qAct + 1 : (qSw ? qDecoy : qAct0) + 1")
    x("n_ds2", "qPlain ? 0 : (qSw ? qAct0 : qDecoy) + 1")
    x("n_dst", "!qPlain && qStar ? qTgt + 1 : 0")
    x("n_dsr", "!qPlain && qStar ? qRule : 0")
    x("n_db", "qPlain && !d_tail ? qBas1 : 0")
    x("n_dru", "d_tail ? 0 : qRule")
    # lit node: uniform over the visible non-fragile nodes after the restate (B13), pool order
    for i in (1, 2, 3):
        x(f"qOn{i}", f"!d_g{i}")
    x("qK", "floor(u6 * (qOn1 + qOn2 + qOn3))")
    x("n_dlit", "d_tail ? 0 : qOn1 && qK < qOn1 ? 1 : qOn2 && qK < qOn1 + qOn2 ? 2 : qOn3 ? 3 : 0")
    # tell line (系統規格 4.4): uniform over the action's lines, never the line shown the round before
    x("qLb", "qAct == 0 ? c_lb0 : qAct == 1 ? c_lb1 : qAct == 2 ? c_lb2 : qAct == 3 ? c_lb3 : c_lb4")
    x("qLc", "qAct < 0 ? 0 : qAct == 0 ? c_lc0 : qAct == 1 ? c_lc1 : qAct == 2 ? c_lc2 : qAct == 3 ? c_lc3 : c_lc4")
    x("qLe", "d_pl >= qLb && d_pl < qLb + qLc && qLc > 1 ? d_pl - qLb : -1")
    x("qLk", "qLe >= 0 ? floor(u7 * (qLc - 1)) : floor(u7 * qLc)")
    x("n_dln", "qLc > 0 ? qLb + (qLe >= 0 && qLk >= qLe ? qLk + 1 : qLk) + 1 : 0")


def gen_engine() -> Graph:
    g = Graph()
    case_inputs(g, POLICY_NUM)
    state_reads(g, "debState", {**STATE_KEYS, **DEC_KEYS})
    for name in ("debCmdFrom", "debCmdTo", "debCmdAssist"):
        g.v["k" + name[6:]] = f"world.{name}"
    g.v["caseId"] = "world.debCase"

    # ---- command
    g.tfind("kPA", "debCode", "id", "world.debCmdKind")  # 0..3, -1 none
    g.x("hasSeg", "kFrom >= 0")
    g.x("L", "hasSeg ? abs(kTo - kFrom) + 1 : 0")
    g.x("dir", "kTo >= kFrom ? 1 : -1")
    for p in range(SEG):
        g.x(f"slot{p}", f"hasSeg && {p} < L ? kFrom + {p} * dir : -1")
        g.node(f"card{p}", "atrium.coll.get", name="debBoard")
        g.edge(g.v[f"slot{p}"], f"card{p}.index")
        g.v[f"card{p}"] = f"card{p}.value"
        g.node(f"ok{p}", "atrium.coll.get", name="debBoardOk")
        g.edge(g.v[f"slot{p}"], f"ok{p}.index")
        g.v[f"ok{p}"] = f"ok{p}.value"
        g.fmt(f"ckey{p}", "{a}:{b}", "caseId", f"card{p}")
        g.tfind(f"crow{p}", "debCard", "key", f"ckey{p}")
        for c in CARD_NUM:
            g.tget(f"{c}_{p}", "debCard", c, f"crow{p}")
        g.tget(f"gold{p}", "debCard", "goldenId", f"crow{p}", "string")
    for j in range(SEG - 1):
        g.x(f"lslot{j}", f"slot{j + 1} >= 0 ? min(slot{j}, slot{j + 1}) : -1")
        g.node(f"lk{j}", "atrium.coll.get", name="debBoardLink")
        g.edge(g.v[f"lslot{j}"], f"lk{j}.index")
        g.v[f"lk{j}"] = f"lk{j}.value"
        g.node(f"lkey{j}", "toString")
        g.edge(g.v[f"lslot{j}"], f"lkey{j}.in")
        g.node(f"asd{j}", "atrium.map.get", name="debAssisted")
        g.edge(f"lkey{j}.out", f"asd{j}.key")
        g.v[f"asd{j}"] = f"asd{j}.value"
        g.fmt(f"pair{j}", "{a}|{b}", f"card{j}", f"card{j + 1}")
    # the single parry card (pa.card)
    g.fmt("ckeyC", "{a}:{b}", "caseId", "world.debCmdCard")
    g.tfind("crowC", "debCard", "key", "ckeyC")
    for c in ("r1", "r2", "r3"):
        g.tget(f"{c}_C", "debCard", c, "crowC")

    def any_of(fmt: str) -> str:
        return " || ".join(f"({fmt.format(p=p)})" for p in range(SEG))

    def sum_of(fmt: str, n: int = SEG) -> str:
        return " + ".join(f"({fmt.format(p=p)})" for p in range(n))

    for c in ("r1", "r2", "r3", "rT", "scandal"):
        g.x(f"seg_{c}", any_of(c + "_{p}"))
    g.x("segStrongOk", any_of("strong_{p} && ok{p}"))
    g.x("segBrk", any_of("brk_{p} && ok{p}"))
    g.x("gpCount", sum_of("gp_{p}"))
    g.x("sL", sum_of("lk{p} == 1", SEG - 1))
    g.x("pL", sum_of("lk{p} == 2", SEG - 1))
    for j in range(SEG - 1):
        g.x(f"ua{j}", f"lk{j} == 2 && !asd{j}")
    g.x("anyUA", "ua0 || ua1 || ua2 || ua3")
    g.x("cj", "ua3 ? 3 : ua2 ? 2 : ua1 ? 1 : ua0 ? 0 : -1")
    g.fmt("goldA", "{a}{b}{c}{d}", "gold0", "gold1", "gold2", "gold3")
    g.fmt("golden", "{a}{b}", "goldA", "gold4")  # at most one golden clue per segment (Ch.1-3: only G-01)

    # ---- opponent action of this round (A-3 order): tail -> 玉石俱焚 (A-9, A-11); else a script row (A-11); else the
    # policy decision drawn when the round was set up (DEC_KEYS, §3.4)
    g.streq("hasScriptId", "world.debScript", g.const(""), op="ne")
    g.sel("scriptId", "hasScriptId", "world.debScript", "world.debCase")
    g.fmt("sKey", "{a}:{b}", "scriptId", "s_r")
    g.node("sFind", "atrium.table.find", table=SCRIPT_TABLE, column="key")
    g.edge(g.v["sKey"], "sFind.value")
    g.v["sRow"] = "sFind.row"
    g.x("found", "sRow >= 0")
    for col in ("action", "lit", "clarity", "shown1", "shown2", "star", "basis", "lineKey"):
        g.tget("sc_" + col, SCRIPT_TABLE, col, "sRow", "string")
    g.tget("sc_scripted", SCRIPT_TABLE, "scripted", "sRow")
    g.tget("sc_starRule", SCRIPT_TABLE, "starRule", "sRow")
    g.x("aiR", "!s_tail && !found")  # this round plays the policy decision
    act_names = [""] + OA_NAMES  # code + 1 -> action word
    g.lookup("aiAct", OA_NAMES, "s_da")
    g.x("aiLitN1", "s_dlit == 1")
    g.x("aiLitN2", "s_dlit == 2")
    g.x("aiLitN3", "s_dlit == 3")
    g.sel("aiLit3", "aiLitN3", "c_n3", g.const(""))
    g.sel("aiLit23", "aiLitN2", "c_n2", "aiLit3")
    g.sel("aiLit", "aiLitN1", "c_n1", "aiLit23")
    g.sel("actA", "found", "sc_action", "aiAct")
    g.sel("actStr", "s_tail", g.const("scorched"), "actA")
    g.sel("litA", "found", "sc_lit", "aiLit")
    g.sel("litStr", "s_tail", "c_t", "litA")
    g.tfind("actRow", "debCode", "id", "actStr")
    g.x("oA", "actRow - 4")
    g.x("oScr", "s_tail ? 1 : found ? sc_scripted : 0")
    # the tell line shown this round (debLine row, -1 none): the script row's, else the decided one
    g.tfind("lineRowS", "debLine", "id", "sc_lineKey")
    g.x("curLine", "found && !s_tail ? lineRowS : s_dln - 1")

    # ---- node indices: lit, target, pool positions
    g.tfind("litRow", "debNode", "id", "litStr")
    g.tget("litIdx", "debNode", "idx", "litRow")
    g.streq("hasTarget", "world.debCmdTarget", g.const(""), op="ne")
    g.sel("targetStr", "hasTarget", "world.debCmdTarget", "litStr")
    g.tfind("tRow", "debNode", "id", "targetStr")
    g.tget("tIdx", "debNode", "idx", "tRow")
    g.tget("tPs", "debNode", "ps", "tRow")
    for i in (1, 2, 3):
        g.node(f"pos{i}", "atrium.coll.indexOf", name="debOn")
        g.edge(g.v[f"c_n{i}"], f"pos{i}.value")
        g.v[f"pos{i}"] = f"pos{i}.index"
    g.node("onCount", "atrium.coll.count", name="debOn")
    g.v["onCount"] = "onCount.count"

    def idx_to_id(name: str, idx: str) -> str:
        g.fmt(name + "_k", "{a}:{b}", "caseId", idx)
        g.tfind(name + "_r", "debNode", "key", name + "_k")
        return g.tget(name, "debNode", "id", name + "_r", "string")

    # ---- the round (A-1). Codes: kPA solid 0 / sophistry 1 / rebut 2 / observe 3; oA assert 0 / rush 1 /
    # reinforce 2 / trap 3 / scorched 4.
    x = g.x
    x("normal", "s_act && !s_over && !s_tail")
    x("tailR", "s_act && !s_over && s_tail")
    x("isAtk", "kPA == 0 || kPA == 1")
    x("oAtk", "oA == 0 || oA == 1 || oA == 4")
    x("trapped", "kPA == 1 && oA == 3")
    x("hit", "isAtk && !trapped")
    x("icpt", "kPA == 2 && oAtk")  # intercept: Ch.1-3 attacks always target the lit node
    x("br", "s_sh == 1")
    x("stacks", "c_hk == 2 ? s_hk : 0")
    x("inSh", "c_ssOn && s_ss > 0")
    x("kjAct", "c_kjOn && s_kj > 0")
    x("nStart", "3 - s_g1 - s_g2 - s_g3")  # normal nodes at the round start (fragile excluded, B5)
    x("tRef", "(tIdx == 1 && seg_r1) || (tIdx == 2 && seg_r2) || (tIdx == 3 && seg_r3)")
    # break (A-8, B18; Ch.1 E01_03)
    x("reduce", "c_hk == 2 && s_hk >= 3")
    x("needChain", "max(1, c_brChain + s_voids - reduce)")
    x("needStrong", "max(1, c_brStrong + s_voids - reduce)")
    x("thr", "c_ch1 ? segBrk : (pL == 0 && L >= needChain) || (segStrongOk && pL == 0 && L >= needStrong)")
    x("brOk", "br && ((kPA == 0 && thr) || (kPA == 2 && hasSeg && icpt))")
    x("brVia", "kPA == 0 ? 0 : 1")
    x("missPB", "br && kPA == 2 && hasSeg && !icpt")
    # step 1: node changes
    x("nf", "s_fseq - s_flo")
    x("fragC", "hit && nf > 0")  # B6: the next hit consumes the first fragile node
    x("tAlive", "(tIdx == 1 && !s_g1) || (tIdx == 2 && !s_g2) || (tIdx == 3 && !s_g3)")
    x("remT", "kPA == 0 && !brOk && tAlive && tRef")
    for i in (1, 2, 3):
        x(f"cand{i}", f"remT && L >= 4 && !s_g{i} && tIdx != {i} && seg_r{i}")
    x("sec1", "cand1 && (!cand2 || pos1 < pos2) && (!cand3 || pos1 < pos3)")
    x("sec2", "cand2 && (!cand1 || pos2 < pos1) && (!cand3 || pos2 < pos3)")
    x("sec3", "cand3 && (!cand1 || pos3 < pos1) && (!cand2 || pos3 < pos2)")
    x("secIdx", "sec1 ? 1 : sec2 ? 2 : sec3 ? 3 : 0")
    x("remP", "icpt && !brOk")
    for i in (1, 2, 3):
        x(f"ga{i}", f"s_g{i} || (remT && tIdx == {i}) || secIdx == {i} || (remP && litIdx == {i})")
    x("obsF", "kPA == 3 && (oA == 2 || oA == 3)")
    x("recRIdx", "oA == 2 && (3 - ga1 - ga2 - ga3) < c_cap ? (ga1 ? 1 : ga2 ? 2 : ga3 ? 3 : 0) : 0")
    for i in (1, 2, 3):
        x(f"gb{i}", f"ga{i} && recRIdx != {i}")
    x("remAny", "remT || secIdx > 0 || remP")
    x("conInc", "c_conT > 0 && !brOk && (remP || (kPA == 0 && oA == 2 && remAny))")
    x("conN", "s_con + conInc")
    # step 2: damage to the opponent (A-1 order with A-15 破竹; integer ratios as in ref/rules.py)
    x("half", "oAtk || (kPA == 0 && oA == 2 && !brOk)")
    x("cd0", "14 * (10 + 5 * sL + 8 * pL) / 10")
    x("cd1", "br ? cd0 * c_shN / c_shD : cd0")
    x("cd2", "stacks ? cd1 * (10 + stacks) / 10 : cd1")
    x("cd3", "half ? cd2 / 2 : cd2")
    x("chainD", "fragC ? cd3 + 10 : cd3")
    x("ctrD", "stacks ? c_counter * (10 + stacks) / 10 : c_counter")
    x("dmgO", "hit ? chainD : icpt ? ctrD : 0")
    x("ohp1", "c_hp && dmgO != 0 ? s_ohp - dmgO : s_ohp")
    x("brAmt", "c_oMax * c_brPct / 100")
    x("oppZero", "!brOk && c_hp && ohp1 <= 0")
    x("ohp2", "brOk ? (c_hp ? max(1, ohp1 - brAmt) : ohp1) : oppZero ? 0 : ohp1")  # B8
    # step 3: damage to the player (B10 order)
    x("takeAtk", "!oppZero && oAtk && !icpt")
    x("pd0", "c_base + c_per * nStart")
    x("pd1", "oA == 1 ? pd0 * c_rushN / c_rushD : pd0")
    x("pd2", "kjAct ? pd1 * c_kjN / c_kjD : pd1")
    x("pd3", "s_r >= c_impR ? pd2 + c_impA : pd2")
    x("dmgP", "kPA == 3 ? pd3 / 2 : pd3")
    x("fullRush", "takeAtk && oA == 1 && kPA != 3")
    x("php1", "takeAtk && c_hp ? s_php - dmgP : s_php")
    x("trapOn", "!oppZero && trapped")
    x("asBlock", "trapOn && kAssist && anyUA")
    x("crit", "trapOn && !kAssist && anyUA")
    x("php2", "crit && c_hp ? php1 - c_crit : php1")
    x("asWaste", "!oppZero && kAssist && oA != 3")
    x("caughtSlot", "cj == 0 ? lslot0 : cj == 1 ? lslot1 : cj == 2 ? lslot2 : lslot3")
    # step 4: reinforce recovery
    x("reinfOk", "oA == 2 && !hit")
    x("healOk", "c_hp && reinfOk && !oppZero")
    x("ohp3", "healOk ? min(c_oMax, ohp2 + c_oMax * c_heal / 100) : ohp2")
    x("healAmt", "ohp3 - ohp2")
    # ends
    x("lossA", "!oppZero && c_hp && php2 <= 0")
    x("over1", "oppZero || lossA")
    # step 5: statuses
    x("scTrig", "c_conT == 0 && kPA == 0 && hit && tIdx > 0 && seg_scandal && tPs")
    x("fourTrig", "c_conT == 0 && kPA == 0 && hit && tIdx > 0 && L >= 4"
                  " && (c_brLine == 0 || ohp3 <= c_oMax * c_brLine / 100)")
    x("trig", "!over1 && (c_conT > 0 ? conInc && conN >= c_conT : (icpt && oA == 1) || scTrig || fourTrig)")
    x("shN", "over1 ? s_sh : brOk ? 2 : br ? (trig ? 1 : 0) : trig ? 1 : s_sh")
    x("lostBR", "!over1 && !brOk && br && !trig")
    x("gainSh", "trig && !brOk")
    x("ssLive", "c_ssOn && !over1")
    x("trigS", "ssLive && !brOk && ((fullRush && isAtk) || crit)")
    x("ssN", "!ssLive ? s_ss : brOk ? 0 : trigS ? 1 : max(0, s_ss - 1)")
    x("lostSsBr", "ssLive && brOk && s_ss > 0")
    x("lostSsExp", "ssLive && !brOk && !trigS && s_ss == 1")
    x("hkLive", "c_hk >= 1 && !over1")
    x("right", "(oAtk ? icpt || (inSh && kPA == 3) : oA == 2 ? (kPA == 1 && s_soph) || kPA == 3 : kPA == 0 || kPA == 3)"
               " || scTrig || brOk")
    x("hkNew", "trigS ? 0 : right ? min(3, s_hk + 1) : 0")
    x("hkN", "hkLive ? hkNew : s_hk")
    x("hkPrev", "c_hk == 1")
    x("hk3", "hkLive && c_hk == 2 && hkNew > s_hk && hkNew == 3")
    x("hkUp", "hkLive && c_hk == 2 && hkNew > s_hk && hkNew < 3")
    x("hkLost", "hkLive && c_hk == 2 && hkNew < s_hk")
    x("parN", "s_par + icpt")
    x("kjLive", "c_kjOn && !over1")
    x("condP", "parN >= 2 && !s_kjp")
    x("condH", "c_hp && ohp3 <= c_oMax * c_kjHp / 100 && !s_kjh")
    x("kjGain", "kjLive && !brOk && (condP || condH) && s_kj == 0")
    x("kjN", "!kjLive ? s_kj : brOk ? 0 : kjGain ? c_kjR : max(0, s_kj - 1)")
    x("kjpN", "s_kjp || (kjGain && condP)")
    x("kjhN", "s_kjh || (kjGain && condH)")
    x("lostKjBr", "kjLive && brOk && s_kj > 0")
    x("lostKjExp", "kjLive && !brOk && s_kj == 1")
    # Ch.1 ends (A4, B21, D15), tail start (A-9)
    x("ch1Live", "c_conT > 0 && !over1")
    x("winB", "ch1Live && brOk")
    x("unachD", "ch1Live && !brOk && s_r >= c_conD && conN < c_conT")
    x("capU", "ch1Live && !brOk && !unachD && c_rcap > 0 && s_r >= c_rcap")
    x("over2", "over1 || winB || unachD || capU")
    x("tailStart", "brOk && c_hasTail && !over2")
    x("winNT", "brOk && !c_hasTail && !over2")
    x("overN1", "over2 || winNT")
    x("endN", "oppZero ? 1 : lossA ? 2 : winB ? 3 : unachD ? 4 : capU ? 5 : winNT ? 6 : 0")
    # restate (A-1 step 1 of the next round): pool order among the removed (B19)
    x("recSIdx", "!overN1 && !tailStart && (3 - gb1 - gb2 - gb3) < c_cap ? (gb1 ? 1 : gb2 ? 2 : gb3 ? 3 : 0) : 0")
    # golden / label (B17)
    x("lblN1", "brOk && c_gpN > 0 ? (gpCount >= c_gpN ? 1 : 2) : 0")
    x("guOn", "brOk && (c_gpN == 0 || lblN1 == 1)")
    g.sel("gu", "guOn", "golden", g.const(""))
    g.streq("hasGold", "golden", g.const(""), op="ne")
    # cut-ins this round (4.7: one full-screen, the smallest priority; the others become stamps)
    x("fRonpa", "brOk")
    x("fShaken", "gainSh")
    x("fShisshu", "trigS")
    x("fHk3", "hk3")
    x("fKonju", "kjGain")
    x("minPrio", "min(min(fRonpa ? 3 : 99, fShaken ? 6 : 99), min(min(fKonju ? 7 : 99, fShisshu ? 8 : 99), fHk3 ? 9 : 99))")
    for nm, pr in (("Ronpa", 3), ("Shaken", 6), ("Konju", 7), ("Shisshu", 8), ("Hk3", 9)):
        x(f"p{nm}", f"minPrio == {pr}")

    # ---- the tail round (A-9 culprit 玉石俱焚)
    x("tCorrect", "kPA == 2 && hasSeg && L >= 2 && pL == 0 && seg_rT")
    x("tPhp", "tCorrect ? s_php : s_php - c_tw")
    x("tLoss", "!tCorrect && tPhp <= 0")
    x("tOver", "tCorrect || tLoss")
    x("tlN", "s_tl - 1")
    x("tVoid", "!tOver && tlN <= 0")
    x("tOhp", "tCorrect ? 0 : tVoid ? c_oMax * c_voidPct / 100 : s_ohp")

    # ---- next state (normal round | tail round)
    def nxt(key: str, normal: str, tail: str) -> None:
        x(f"n_{key}", f"tailR ? ({tail}) : ({normal})")

    nxt("act", "s_act", "s_act")
    nxt("r", "s_r + 1", "s_r + 1")
    nxt("php", "php2", "tPhp")
    nxt("ohp", "ohp3", "tOhp")
    for i in (1, 2, 3):
        nxt(f"g{i}", f"brOk ? 1 : gb{i} && recSIdx != {i}", f"tVoid ? {0 if i == 1 else 1} : s_g{i}")
    nxt("fseq", "s_fseq + obsF", "s_fseq")
    nxt("flo", "brOk ? s_fseq + obsF : s_flo + fragC", "s_flo")
    nxt("sh", "shN", "tVoid ? 0 : s_sh")
    nxt("tail", "tailStart", "tVoid ? 0 : 1")
    nxt("tl", "tailStart ? c_tr : s_tl", "max(0, tlN)")
    nxt("voids", "s_voids", "s_voids + tVoid")
    nxt("hk", "hkN", "s_hk")
    nxt("kj", "kjN", "max(0, s_kj - 1)")
    nxt("kjp", "kjpN", "s_kjp")
    nxt("kjh", "kjhN", "s_kjh")
    nxt("par", "parN", "s_par")
    nxt("ss", "tailStart ? 0 : ssN", "max(0, s_ss - 1)")
    nxt("as", "s_as - kAssist", "s_as")
    nxt("fox", "s_fox", "s_fox")
    nxt("foxr", "s_foxr", "s_foxr")
    nxt("inf", "s_inf + crit", "s_inf")
    nxt("con", "conN", "s_con")
    nxt("over", "overN1", "tOver")
    nxt("out", "endN == 1 || endN == 3 || endN == 6 ? 1 : endN == 2 ? 2 : endN == 4 || endN == 5 ? 3 : s_out",
        "tCorrect ? 1 : tLoss ? 2 : s_out")
    nxt("lbl", "brOk ? lblN1 : s_lbl", "s_lbl")
    nxt("gold", "s_gold || (guOn && hasGold)", "s_gold")
    # behaviour-rule memory (A-3); scripted rounds do not touch it (A-11)
    nxt("lnr", "oScr ? s_lnr : remAny || (brOk && onCount > 0)", "s_lnr")
    nxt("lrs", "oScr ? s_lrs : reinfOk", "s_lrs")
    nxt("nrn", "oScr ? s_nrn : kPA == 0 && oA == 3", "s_nrn")
    nxt("man", "oScr ? s_man : kPA == 3 && oA == 3", "s_man")
    x("r3fire", "!oScr && c_hp && !s_r3f && ohp3 <= c_oMax * c_r3 / 100")
    nxt("r3f", "s_r3f || r3fire", "s_r3f")
    # the forced rush of rule 3 consumes the pending flag (ref decide_next); the engine clears it at the lock of the
    # round that played it, so a debRedecide before that lock still sees it
    x("r3used", "aiR && s_dru == 3")
    nxt("r3p", "(s_r3p && !r3used) || r3fire", "s_r3p")
    nxt("nco", "kPA == 3 && oAtk", "s_nco")
    nxt("h1", "oA + 1", "oA + 1")
    nxt("h2", "s_h1", "s_h1")
    nxt("lpa", "kPA + 1", "kPA + 1")
    nxt("soph", "s_soph", "s_soph")
    nxt("pln", "curLine + 1", "curLine + 1")
    nxt("rd", "s_rd + right", "s_rd + tCorrect")
    decide(g)
    x("overNow", "tailR ? tOver : overN1")
    x("endCode", "tailR ? (tCorrect ? 7 : tLoss ? 2 : 0) : endN")

    # ---- strings for the records
    g.lookup("staging", ["player_attack_vs_defense", "defense_vs_attack", "clash", "standoff"],
             x("stg", "isAtk && oAtk ? 2 : isAtk ? 0 : oAtk ? 1 : 3"))
    g.fmt("fragId1", "F{a}", x("fLoNext", "s_flo + 1"))
    g.fmt("fragId2", "F{a}", x("fSeqNext", "s_fseq + 1"))
    idx_to_id("secId", "secIdx")
    idx_to_id("recRId", "recRIdx")
    idx_to_id("recSId", "recSIdx")
    g.sel("conNode", "remT", "targetStr", "litStr")
    g.lookup("viaStr", ["solid", "parry"], "brVia")
    g.lookup("lblStr", ["", "primary", "alternative"], "lblN1")
    g.lookup("dmgPSrc", ["claim", "rush"], x("isRush", "oA == 1"))
    g.lookup("outStr", ["", "win", "loss", "unachieved"],
             x("endOut", "endCode == 1 || endCode == 3 || endCode == 6 || endCode == 7 ? 1"
                         " : endCode == 2 ? 2 : endCode >= 4 ? 3 : 0"))
    g.lookup("reasonStr", ["", "opponent_zero", "player_zero", "break", "contradiction_deadline", "round_cap",
                           "break_no_tail", "tail_finish"], "endCode")
    for j in range(SEG - 1):
        x(f"isCj{j}", f"cj == {j}")
    g.sel("cp01", "isCj0", "pair0", "pair1")
    g.sel("cp23", "isCj2", "pair2", "pair3")
    x("cjLow", "cj <= 1")
    g.sel("caughtPair", "cjLow", "cp01", "cp23")
    g.node("caughtKey", "toString")
    g.edge(g.v["caughtSlot"], "caughtKey.in")
    g.v["caughtKey"] = "caughtKey.out"

    # ---- start (world.debStart): reset, then the round-1 board (A-1 step 1: the node cap)
    st = Cascade(g, "sg")
    g.streq("isMain", "c_kind", g.const("warmup"), op="ne")
    g.v["one"] = g.const(1)
    x("n_act0", "isMain")
    st.on(None, *[f"{n}.trigger" for n in (
        g.node("stClr", "atrium.map.clear", name="debState"),
        g.node("stClrOn", "atrium.coll.clear", name="debOn"),
        g.node("stClrEv", "atrium.coll.clear", name="debEvents"),
        g.node("stClrSnap", "atrium.map.clear", name="debSnap"),
        g.node("stClrAs", "atrium.map.clear", name="debAssisted"))])
    inits = {"act": "n_act0", "r": "one", "php": "c_pMax", "ohp": "c_oMax", "as": "c_assists", "fox": "c_fox",
             "soph": "c_soph"}
    trig = []
    for k in INIT_KEYS:
        nid = f"i_{k}"
        g.node(nid, "atrium.map.set", name="debState")
        g.edge(g.const(k), f"{nid}.key")
        g.edge(g.src(inits[k]), f"{nid}.value")
        trig.append(f"{nid}.trigger")
    st.on(None, *trig)
    for i in (1, 2, 3):
        x(f"stAdd{i}", f"isMain && c_cap >= {i}")
        list_op(g, st, f"stOn{i}", f"stAdd{i}", "add", "debOn", f"c_n{i}")
    # the decision for round 1 (A-1 step 6 of "round 0"), from the initial state
    st.on("isMain", "dMode.toStart", "dDraw.in")
    state_commit(g, st, "debState", DEC_KEYS, "isMain", prefix="sd")
    st.emit("world.debStart")

    # ---- fox instinct (world.debInstinct, before the lock): a fuzzy tell becomes clear (policy.use_fox_instinct)
    g.lookup("aiClar", ["clear", "fuzzy"], "s_dcl")
    g.sel("baseClar", "found", "sc_clarity", "aiClar")
    g.streq("tellFuzzy", "baseClar", g.const("fuzzy"))
    x("foxOk", "normal && tellFuzzy && s_fox > 0 && s_foxr != s_r")
    x("n_foxI", "s_fox - 1")
    x("n_foxrI", "s_r")
    fx = Cascade(g, "fg")
    list_op(g, fx, "fxClrEv", "foxOk", "clear", "debEvents", None)
    ev(g, fx, "eSeen", "foxOk", stamp("STAMP_SEEN", "player"))
    for k, val in (("fox", "n_foxI"), ("foxr", "n_foxrI")):
        nid = f"f_{k}"
        g.node(nid, "atrium.map.set", name="debState")
        g.edge(g.const(k), f"{nid}.key")
        g.edge(g.src(val), f"{nid}.value")
        fx.on("foxOk", f"{nid}.trigger")
    fx.emit("world.debInstinct")

    # ---- lock (world.debLock): events, board-node list, state commit
    x("live", "s_act && !s_over")
    lk = Cascade(g, "lg")
    list_op(g, lk, "lkClrEv", "live", "clear", "debEvents", None)
    ev(g, lk, "eReveal", "live", "reveal|{a}|{b}|{c}|{d}", "s_r", "world.debCmdKind", "actStr", "staging")
    # tail round
    ev(g, lk, "eTObs", x("tObs", "tailR && kPA == 3"), "msg|WARN_DEB_OBSERVE_TAIL")
    ev(g, lk, "eTRes", "tailR", "tailResult|{a}", "tCorrect")
    ev(g, lk, "eTFin", x("tFin", "tailR && tCorrect"), "dmgOpp|tail_finish|{a}|{b}|0", "s_ohp", "s_ohp")
    ev(g, lk, "eTWrong", x("tWrong", "tailR && !tCorrect"), "dmgPlayer|tail_wrong|{a}|{b}|{c}", "c_tw", "s_php", "tPhp")
    ev(g, lk, "eTHk", "tailR", "hachiku|{a}|{a}|{b}", "s_hk", "hkPrev")
    # normal round, step 1
    x("eFragC", "normal && fragC")
    list_op(g, lk, "lFragC", "eFragC", "remove", "debOn", "fragId1")
    ev(g, lk, "eFrag", "eFragC", "nodeRemoved|{a}|fragile_hit", "fragId1")
    x("eRemT", "normal && remT")
    list_op(g, lk, "lRemT", "eRemT", "remove", "debOn", "targetStr")
    ev(g, lk, "eRemTe", "eRemT", "nodeRemoved|{a}|chain", "targetStr")
    x("eSec", "normal && secIdx > 0")
    list_op(g, lk, "lSec", "eSec", "remove", "debOn", "secId")
    ev(g, lk, "eSece", "eSec", "nodeRemoved|{a}|chain", "secId")
    x("eRemP", "normal && remP")
    list_op(g, lk, "lRemP", "eRemP", "remove", "debOn", "litStr")
    ev(g, lk, "eRemPe", "eRemP", "nodeRemoved|{a}|parry", "litStr")
    x("eObsF", "normal && obsF")
    list_op(g, lk, "lObsF", "eObsF", "add", "debOn", "fragId2")
    ev(g, lk, "eObsFe", "eObsF", "nodeAdded|{a}|fragile|observe", "fragId2")
    x("eRecR", "normal && recRIdx > 0")
    list_op(g, lk, "lRecR", "eRecR", "add", "debOn", "recRId")
    ev(g, lk, "eRecRe", "eRecR", "nodeAdded|{a}|normal|reinforce", "recRId")
    ev(g, lk, "eCon", x("eConC", "normal && conInc"), "contradiction|{a}|{b}", "conN", "conNode")
    ev(g, lk, "eClash", x("eClashC", "normal && isAtk && oAtk"), stamp("STAMP_CLASH", ""))
    ev(g, lk, "eParry", x("eParryC", "normal && icpt"), stamp("STAMP_PARRY", "player"))
    ev(g, lk, "eWhiffP", x("eWhiffPC", "normal && kPA == 2 && !oAtk"), stamp("STAMP_WHIFF", "player"))
    ev(g, lk, "eWhiffO", x("eWhiffOC", "normal && kPA == 0 && oA == 3"), stamp("STAMP_WHIFF", "opponent"))
    # step 2
    ev(g, lk, "eDmgC", x("eDmgCC", "normal && c_hp && hit"), "dmgOpp|chain|{a}|{b}|{c}", "dmgO", "s_ohp", "ohp1")
    ev(g, lk, "eDmgK", x("eDmgKC", "normal && c_hp && icpt"), "dmgOpp|counter|{a}|{b}|{c}", "dmgO", "s_ohp", "ohp1")
    x("eBr", "normal && brOk")
    g.node("brEach", "atrium.coll.forEach", name="debOn")
    g.fmt("eBrNode", "nodeRemoved|{a}|break", "brEach.item")
    g.node("eBrNode_add", "atrium.coll.add", name="debEvents")
    g.edge("eBrNode.out", "eBrNode_add.value")
    g.edge("brEach.each", "eBrNode_add.trigger")
    lk.on("eBr", "brEach.trigger")
    list_op(g, lk, "lBrClr", "eBr", "clear", "debOn", None)
    ev(g, lk, "eBrRes", "eBr", "break|1|{a}|{b}|{c}", "viaStr", "lblStr", "gu")
    cutin(g, lk, "eRonpa", "eBr", "CUT_RONPA", 3, "player", "pRonpa")
    ev(g, lk, "eBrDmg", x("eBrDmgC", "eBr && c_hp"), "dmgOpp|break|{a}|{b}|{c}", "brAmt", "ohp1", "ohp2")
    x("eMissPB", "normal && missPB")
    ev(g, lk, "eMissPB1", "eMissPB", "break|0|parry||")
    ev(g, lk, "eMissPB2", "eMissPB", "msg|MSG_DEB_PARRY_BREAK_MISS")
    # step 3
    ev(g, lk, "eDmgP", x("eDmgPC", "normal && takeAtk && c_hp"), "dmgPlayer|{a}|{b}|{c}|{d}", "dmgPSrc", "dmgP",
       "s_php", "php1")
    ev(g, lk, "eTrap", x("eTrapC", "normal && trapOn"), stamp("STAMP_TRAP", "player"))
    x("eAsB", "normal && asBlock")
    ev(g, lk, "eAsB1", "eAsB", "msg|ASSIST_BLOCKED")
    ev(g, lk, "eAsB2", "eAsB", stamp("STAMP_ASSIST", "player"))
    g.node("lAsMark", "atrium.map.set", name="debAssisted")
    g.edge("caughtKey.out", "lAsMark.key")
    g.edge(g.const(1), "lAsMark.value")
    lk.on("eAsB", "lAsMark.trigger")
    x("eCrit", "normal && crit")
    ev(g, lk, "eCritD", x("eCritDC", "eCrit && c_hp"), "dmgPlayer|trap_crit|{a}|{b}|{c}", "c_crit", "php1", "php2")
    x("snapUntil", "s_r + 1")
    ev(g, lk, "eSnap", "eCrit", "linkSnapped|{a}|{b}", "caughtPair", "snapUntil")
    g.node("lSnap", "atrium.map.set", name="debSnap")
    g.edge("caughtKey.out", "lSnap.key")
    g.edge(g.v["snapUntil"], "lSnap.value")
    lk.on("eCrit", "lSnap.trigger")
    x("infN", "s_inf + 1")
    ev(g, lk, "eInf", "eCrit", "infamy|{a}|{b}", "s_inf", "infN")
    ev(g, lk, "eAsW", x("eAsWC", "normal && asWaste"), "msg|MSG_DEB_ASSIST_WASTED")
    x("asWasted", "oA != 3")
    ev(g, lk, "eAsS", x("eAsSC", "normal && kAssist"), "assistSpent|{a}", "asWasted")
    # step 4
    ev(g, lk, "eHeal", x("eHealC", "normal && healOk"), "heal|{a}|{b}|{c}", "healAmt", "ohp2", "ohp3")
    # step 5
    ev(g, lk, "eShL", x("eShLC", "normal && lostBR"), "statusLost|shaken|opponent|break_round_passed")
    x("eShG", "normal && gainSh")
    ev(g, lk, "eShGe", "eShG", "statusGained|shaken|opponent|{a}", "c_shR")
    cutin(g, lk, "eShCut", "eShG", "CUT_SHAKEN", 6, "opponent", "pShaken")
    ev(g, lk, "eSsLB", x("eSsLBC", "normal && lostSsBr"), "statusLost|shisshu|player|break")
    x("eSsG", "normal && trigS")
    ev(g, lk, "eSsGe", "eSsG", "statusGained|shisshu|player|1")
    cutin(g, lk, "eSsCut", "eSsG", "CUT_SHISSHU", 8, "player", "pShisshu")
    ev(g, lk, "eSsLE", x("eSsLEC", "normal && lostSsExp"), "statusLost|shisshu|player|expired")
    ev(g, lk, "eHk", x("eHkC", "normal && hkLive"), "hachiku|{a}|{b}|{c}", "s_hk", "hkNew", "hkPrev")
    cutin(g, lk, "eHk3", x("eHk3C", "normal && hk3"), "CUT_HACHIKU3", 9, "player", "pHk3")
    ev(g, lk, "eHkUp", x("eHkUpC", "normal && hkUp"), "cutin|STAMP_HACHIKU{a}|stamp||player|0|0", "hkNew")
    ev(g, lk, "eHkLost", x("eHkLostC", "normal && hkLost"), stamp("STAMP_HACHIKU_LOST", "player"))
    ev(g, lk, "eKjLB", x("eKjLBC", "normal && lostKjBr"), "statusLost|konju|opponent|break")
    ev(g, lk, "eKjLE", x("eKjLEC", "normal && lostKjExp"), "statusLost|konju|opponent|expired")
    x("eKjG", "normal && kjGain")
    ev(g, lk, "eKjGe", "eKjG", "statusGained|konju|opponent|{a}", "c_kjR")
    cutin(g, lk, "eKjCut", "eKjG", "CUT_KONJU", 7, "opponent", "pKonju")
    # end of the debate (both kinds of round)
    ev(g, lk, "eEnd", x("eEndC", "live && overNow"), "ended|{a}|{b}", "outStr", "reasonStr")
    # restate / tail start (normal), void (tail)
    x("eTS", "normal && tailStart")
    list_op(g, lk, "lTS", "eTS", "add", "debOn", "c_t")
    ev(g, lk, "eTS1", "eTS", "tailStarted|{a}|{b}", "c_tr", "c_t")
    ev(g, lk, "eTS2", "eTS", "nodeAdded|{a}|second_claim|tail_start", "c_t")
    ev(g, lk, "eTS3", "eTS", "statusGained|tail|opponent|{a}", "c_tr")
    x("eRecS", "normal && recSIdx > 0")
    list_op(g, lk, "lRecS", "eRecS", "add", "debOn", "recSId")
    ev(g, lk, "eRecSe", "eRecS", "nodeAdded|{a}|normal|restate", "recSId")
    x("eVoid", "tailR && tVoid")
    ev(g, lk, "eVoid1", "eVoid", "breakVoided|{a}|{b}", "tOhp", x("voidsN", "s_voids + 1"))
    ev(g, lk, "eVoid2", "eVoid", "statusLost|tail|opponent|voided")
    ev(g, lk, "eVoid3", "eVoid", "statusLost|shaken|opponent|break_voided")
    list_op(g, lk, "lVoidT", "eVoid", "remove", "debOn", "c_t")
    ev(g, lk, "eVoid4", "eVoid", "nodeRemoved|{a}|tail_void", "c_t")
    list_op(g, lk, "lVoidN", "eVoid", "add", "debOn", "c_n1")
    ev(g, lk, "eVoid5", "eVoid", "nodeAdded|{a}|normal|restate", "c_n1")
    # the decision for the next round (A-1 step 6), from the next state; then the state commit (last: nothing above
    # reads the map again this tick)
    lk.on("live", "dMode.toLock", "dDraw.in")
    state_commit(g, lk, "debState", {**STATE_KEYS, **DEC_KEYS}, "live")
    lk.emit("world.debLock")

    # ---- redecide (world.debRedecide): draw the coming round's decision again from the stored state (tests; the
    # game never fires it). Only the decision keys are written.
    rd = Cascade(g, "rg")
    rd.on("live", "dMode.toRe", "dDraw.in")
    state_commit(g, rd, "debState", DEC_KEYS, "live", prefix="rd")
    rd.emit("world.debRedecide")

    # ---- outputs
    def out(sig: str, src: str) -> None:
        g.edge(g.src(src), f"world.{sig}")

    g.lookup("phase", ["idle", "choose", "over"], x("phaseCode", "s_act ? (s_over ? 2 : 1) : 0"))
    out("debPhase", "phase")
    for sig, k in (("debRound", "s_r"), ("debPlayerHp", "s_php"), ("debOppHp", "s_ohp"), ("debShaken", "s_sh"),
                   ("debInTail", "s_tail"), ("debTailLeft", "s_tl"), ("debVoids", "s_voids"), ("debHachiku", "s_hk"),
                   ("debKonju", "s_kj"), ("debShisshu", "s_ss"), ("debParries", "s_par"), ("debContra", "s_con"),
                   ("debInfamy", "s_inf"), ("debAssist", "s_as"), ("debInstinctLeft", "s_fox"), ("debOver", "s_over"),
                   ("debGoldenUsed", "s_gold"), ("debHpModel", "c_hp"), ("debPlayerMax", "c_pMax"),
                   ("debOppMax", "c_oMax"), ("debHachikuMode", "c_hk"), ("debReads", "s_rd"),
                   ("debNoReinf", "s_nrn"), ("debMustAtk", "s_man")):
        out(sig, k)
    g.lookup("outcome", ["", "win", "loss", "unachieved"], "s_out")
    out("debOutcome", "outcome")
    g.lookup("label", ["", "primary", "alternative"], "s_lbl")
    out("debBreakLabel", "label")
    out("debFragile", x("fragCount", "s_fseq - s_flo"))
    # the tell of the coming round: tail -> clear, basis script; instinct -> clear, basis fox; a script row; else the
    # policy decision (DEC_KEYS)
    x("foxNow", "!s_tail && s_foxr == s_r && s_r > 0")
    x("plainTell", "s_tail || foxNow")
    g.lookup("aiSh1", act_names, "s_ds1")
    g.lookup("aiSh2", act_names, "s_ds2")
    g.lookup("aiStar", act_names, "s_dst")
    g.lookup("aiBasis", BASIS, "s_db")
    g.sel("bSh1", "found", "sc_shown1", "aiSh1")
    g.sel("bSh2", "found", "sc_shown2", "aiSh2")
    g.sel("bStar", "found", "sc_star", "aiStar")
    g.sel("bBasis", "found", "sc_basis", "aiBasis")
    g.sel("tClar", "plainTell", g.const("clear"), "baseClar")
    g.sel("tSh1", "plainTell", "actStr", "bSh1")
    g.sel("tSh2", "plainTell", g.const(""), "bSh2")
    g.sel("tStar", "plainTell", g.const(""), "bStar")
    g.sel("tBasisA", "foxNow", g.const("fox"), "bBasis")
    g.sel("tBasis", "s_tail", g.const("script"), "tBasisA")
    x("tStarRule", "plainTell ? 0 : found ? sc_starRule : s_dsr")
    x("tRule", "aiR ? s_dru : 0")
    x("aiLineRow", "s_dln - 1")
    g.tget("aiLine", "debLine", "id", "aiLineRow", "string")
    x("lineFromRow", "found && !s_tail")
    g.sel("tLine", "lineFromRow", "sc_lineKey", "aiLine")
    x("gIdx", "oA < 0 || oA > 3 ? 4 : oA")
    g.sel("gst01", x("gIs0", "gIdx == 0"), "c_g0", "c_g1")
    g.sel("gst23", x("gIs2", "gIdx == 2"), "c_g2", "c_g3")
    g.sel("gstA", x("gLow", "gIdx <= 1"), "gst01", "gst23")
    g.sel("gesture", x("gNone", "gIdx == 4"), g.const(""), "gstA")
    for sig, k in (("debTellClarity", "tClar"), ("debTellShown1", "tSh1"), ("debTellShown2", "tSh2"),
                   ("debTellStar", "tStar"), ("debTellBasis", "tBasis"), ("debTellLit", "litStr"),
                   ("debTellGesture", "gesture"), ("debTellLine", "tLine"), ("debTellStarRule", "tStarRule"),
                   ("debTellRule", "tRule")):
        out(sig, k)
    return g


# --------------------------------------------------------------------------------------------- warmup

WARM_KEYS = {"act": "a warmup is running", "r": "round", "idx": "claims corrected or auto-corrected",
             "mis": "mistakes", "over": "warmup over", "auto": "auto-resolved after the mistake limit"}
WARM_SEG = 3


def gen_warmup() -> Graph:
    """熱身小論戰 (01-systems A-13, ref/warmup.py): parry only, one card per claim; the mistake limit auto-corrects
    the rest. Shares the command signals, world.debStart / world.debLock and debEvents with the engine."""
    g = Graph()
    case_inputs(g)
    state_reads(g, "dwState", WARM_KEYS)
    g.v["caseId"] = "world.debCase"
    for name in ("debCmdFrom", "debCmdTo"):
        g.v["k" + name[6:]] = f"world.{name}"
    x = g.x
    g.tfind("kPA", "debCode", "id", "world.debCmdKind")
    x("hasSeg", "kFrom >= 0")
    x("L", "hasSeg ? abs(kTo - kFrom) + 1 : 0")
    x("dir", "kTo >= kFrom ? 1 : -1")
    for p in range(WARM_SEG):
        x(f"slot{p}", f"hasSeg && {p} < L ? kFrom + {p} * dir : -1")
        g.node(f"card{p}", "atrium.coll.get", name="debBoard")
        g.edge(g.v[f"slot{p}"], f"card{p}.index")
        g.v[f"card{p}"] = f"card{p}.value"
    g.fmt("seg12", ",{a},{b}", "card1", "card2")
    g.fmt("segCards", "{a}{b}", "card0", "seg12")
    x("segLen3", "L >= 3")
    x("segLen2", "L == 2")
    g.fmt("seg1", ",{a}", "card1")
    g.sel("segTail", "segLen3", "seg12", "seg1")
    g.fmt("segTwo", "{a}{b}", "card0", "segTail")
    x("multi", "L >= 2")
    g.sel("presented", "multi", "segTwo", "world.debCmdCard")
    g.fmt("ckeyC", "{a}:{b}", "caseId", "world.debCmdCard")
    g.tfind("crowC", "debCard", "key", "ckeyC")
    for c in ("r1", "r2", "r3"):
        g.tget(f"{c}_C", "debCard", c, "crowC")
    g.streq("hasCard", "world.debCmdCard", g.const(""), op="ne")
    # the current claim
    x("claimNo", "s_idx + 1")
    g.fmt("claimKey", "{a}:{b}", "caseId", "claimNo")
    g.tfind("claimRow", "debNode", "key", "claimKey")
    g.tget("claimId", "debNode", "id", "claimRow", "string")
    x("n", "c_cap")
    # a presentation is right when it is ONE card in the claim's refute list (B16); a chain is a mistake
    x("live", "s_act && !s_over && kPA == 2")
    x("ok", "!hasSeg && hasCard && ((claimNo == 1 && r1_C) || (claimNo == 2 && r2_C) || (claimNo == 3 && r3_C))")
    x("misN", "ok ? s_mis : s_mis + 1")
    x("autoNow", "!ok && misN >= c_mis")
    x("idxN", "ok ? s_idx + 1 : autoNow ? n : s_idx")
    x("overN", "idxN >= n")
    x("autoN", "s_auto || autoNow")
    x("trustD", "autoN || misN >= c_mis ? -1 : misN == 0 ? 1 : 0")
    x("reward", "autoN || misN >= c_mis ? 0 : 1")
    x("n_act", "s_act")
    x("n_r", "s_r + 1")
    x("n_idx", "idxN")
    x("n_mis", "misN")
    x("n_over", "overN")
    x("n_auto", "autoN")

    # start: only for a warmup case
    st = Cascade(g, "sg")
    g.streq("isWarm", "c_kind", g.const("warmup"))
    st.on(None, g.node("stClr", "atrium.map.clear", name="dwState") + ".trigger")
    for k, val in (("act", "isWarm"), ("r", g.const(1))):
        nid = f"i_{k}"
        g.node(nid, "atrium.map.set", name="dwState")
        g.edge(g.const(k), f"{nid}.key")
        g.edge(g.src(val), f"{nid}.value")
        st.on(None, f"{nid}.trigger")
    st.emit("world.debStart")

    lk = Cascade(g, "lg")
    list_op(g, lk, "lkClrEv", "live", "clear", "debEvents", None)
    ev(g, lk, "eReveal", "live", "wReveal|{a}|{b}|{c}", "s_r", "claimId", "presented")
    ev(g, lk, "eOk", x("eOkC", "live && ok"), "wCorrected|{a}", "claimId")
    ev(g, lk, "eMis", x("eMisC", "live && !ok"), "wMistake|{a}", "misN")
    for i in (1, 2, 3):
        x(f"autoC{i}", f"live && autoNow && s_idx < {i} && n >= {i}")
        g.fmt(f"autoK{i}", "{a}:" + str(i), "caseId")
        g.tfind(f"autoR{i}", "debNode", "key", f"autoK{i}")
        g.tget(f"autoId{i}", "debNode", "id", f"autoR{i}", "string")
        ev(g, lk, f"eAuto{i}", f"autoC{i}", "wAutoCorrected|{a}", f"autoId{i}")
    ev(g, lk, "eEnd", x("eEndC", "live && overN"), "wEnded|{a}|{b}|{c}", "trustD", "reward", "misN")
    state_commit(g, lk, "dwState", [k for k in WARM_KEYS], "live")
    lk.emit("world.debLock")

    for sig, src in (("dwActive", "s_act"), ("dwRound", "s_r"), ("dwIndex", "s_idx"), ("dwMistakes", "s_mis"),
                     ("dwOver", "s_over"), ("dwAuto", "s_auto")):
        g.edge(g.src(src), f"world.{sig}")
    g.edge("claimId.value", "world.dwClaim")
    x("trustOut", "!s_act ? 0 : s_auto || s_mis >= c_mis ? -1 : s_mis == 0 ? 1 : 0")
    x("rewardOut", "!s_act ? 0 : s_auto || s_mis >= c_mis ? 0 : 1")
    g.edge(g.v["trustOut"], "world.dwTrustDelta")
    g.edge(g.v["rewardOut"], "world.dwReward")
    return g


GRAPHS = {"debate_engine": gen_engine, "debate_warmup": gen_warmup}


def write_json(path: Path, rows) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=1) + "\n"


def outputs() -> dict[Path, str]:
    out: dict[Path, str] = {}
    for name, fn in GRAPHS.items():
        out[FLOWS / f"{name}.xtflow"] = fn().text()
    for name, rows in derive_tables().items():
        out[DEB_DATA / f"{name}.json"] = write_json(DEB_DATA / f"{name}.json", rows)
    return out


def graph_stats() -> dict[str, tuple[int, int]]:
    return {name: (len(g.nodes), len(g.edges)) for name, g in ((n, fn()) for n, fn in GRAPHS.items())}


# --------------------------------------------------------------------------------------------- harness

HARNESS_COLLECTIONS = {
    "hNum": {"kind": "map", "type": "number", "capacity": 16384},
    "hStr": {"kind": "map", "type": "string", "capacity": 8192},
    "hEv": {"kind": "list", "type": "string", "capacity": 8192},
}
H_PERIOD = 4  # ticks per driver row: 0 values, 1 action pulse, 3 snapshot
SNAP_NUM = ["debRound", "debPlayerHp", "debOppHp", "debShaken", "debInTail", "debTailLeft", "debVoids",
            "debHachiku", "debKonju", "debShisshu", "debParries", "debContra", "debInfamy", "debAssist",
            "debInstinctLeft", "debOver", "debGoldenUsed", "debFragile", "debReads", "debNoReinf", "debMustAtk",
            "dwActive", "dwRound", "dwIndex", "dwMistakes", "dwOver", "dwAuto", "dwTrustDelta", "dwReward"]
SNAP_STR = ["debPhase", "debOutcome", "debBreakLabel", "dwClaim", "debTellClarity", "debTellBasis",
            "debTellLit", "debTellShown1"]
SNAP_ON = 8  # board positions copied per snapshot
H_IN_COLS = ["op", "route", "case", "script", "board", "ok", "links", "key", "value", "kind", "from", "to", "card",
             "target", "assist"]


def gen_driver() -> Graph:
    """Harness driver: row k of table hIn acts at tick 4k+1 (start / set / instinct / round), its values are
    written at 4k, the engine outputs are copied into hNum / hStr / hEv at 4k+3."""
    g = Graph()
    x = g.x
    g.node("clock", "clock")
    g.v["sec"] = "clock.seconds"
    x("tick", "round(sec * 60)")
    x("row", "floor(tick / 4)")
    x("ph", "tick - row * 4")
    for c in H_IN_COLS:
        typ = "number" if c in ("value", "from", "to", "assist") else "string"
        g.tget("h_" + c, "hIn", c, "row", typ)
    for sig, col in (("debCase", "h_case"), ("debScript", "h_script"), ("debCmdKind", "h_kind"),
                     ("debCmdFrom", "h_from"), ("debCmdTo", "h_to"), ("debCmdCard", "h_card"),
                     ("debCmdTarget", "h_target"), ("debCmdAssist", "h_assist")):
        g.edge(g.v[col], f"world.{sig}")
    for op in ("start", "set", "instinct", "round"):
        g.streq("is_" + op, "h_op", g.const(op))
    act = Cascade(g, "ag")
    x("actStart", "is_start")
    for nm, coll, src in (("bCards", "debBoard", "h_board"), ("bOk", "debBoardOk", "h_ok"),
                          ("bLinks", "debBoardLink", "h_links")):
        g.node(nm + "Clr", "atrium.coll.clear", name=coll)
        g.node(nm + "Add", "atrium.coll.addAll", name=coll)
        g.edge(g.v[src], f"{nm}Add.text")
        act.on("actStart", f"{nm}Clr.trigger", f"{nm}Add.trigger")
    g.node("pStart", "merge")
    g.edge("pStart.out", "world.debStart")
    act.on("actStart", "pStart.in")
    g.node("setKey", "atrium.map.set", name="debState")
    g.edge(g.v["h_key"], "setKey.key")
    g.edge(g.v["h_value"], "setKey.value")
    act.on("is_set", "setKey.trigger")
    g.node("pInst", "merge")
    g.edge("pInst.out", "world.debInstinct")
    act.on("is_instinct", "pInst.in")
    g.node("pLock", "merge")
    g.edge("pLock.out", "world.debLock")
    act.on("is_round", "pLock.in")
    g.node("phAct", "compare", op="eq")
    g.edge(g.v["ph"], "phAct.a")
    g.edge(g.const(1), "phAct.b")
    act.emit("phAct.true")

    snap = Cascade(g, "sg")
    for sig in SNAP_NUM:
        g.fmt("kn_" + sig, "{a}:" + sig, "row")
        g.node("wn_" + sig, "atrium.map.set", name="hNum")
        g.edge(g.v["kn_" + sig], f"wn_{sig}.key")
        g.edge(f"world.{sig}", f"wn_{sig}.value")
        snap.on(None, f"wn_{sig}.trigger")
    for sig in SNAP_STR:
        g.fmt("ks_" + sig, "{a}:" + sig, "row")
        g.node("ws_" + sig, "atrium.map.set", name="hStr")
        g.edge(g.v["ks_" + sig], f"ws_{sig}.key")
        g.edge(f"world.{sig}", f"ws_{sig}.value")
        snap.on(None, f"ws_{sig}.trigger")
    for k in range(SNAP_ON):
        g.node(f"on{k}", "atrium.coll.get", name="debOn")
        g.edge(g.const(k), f"on{k}.index")
        g.fmt(f"ko{k}", "{a}:on" + str(k), "row")
        g.node(f"wo{k}", "atrium.map.set", name="hStr")
        g.edge(g.v[f"ko{k}"], f"wo{k}.key")
        g.edge(f"on{k}.value", f"wo{k}.value")
        snap.on(None, f"wo{k}.trigger")
    g.node("evEach", "atrium.coll.forEach", name="debEvents")
    g.fmt("evRec", "{a}#{b}", "row", "evEach.item")
    g.node("evAdd", "atrium.coll.add", name="hEv")
    g.edge(g.v["evRec"], "evAdd.value")
    g.edge("evEach.each", "evAdd.trigger")
    snap.on(x("evRow", "is_round || is_instinct"), "evEach.trigger")
    g.node("phSnap", "compare", op="eq")
    g.edge(g.v["ph"], "phSnap.a")
    g.edge(g.const(3), "phSnap.b")
    snap.emit("phSnap.true")
    return g


def build_harness(out_dir: Path, h_in: list[dict], script: list[dict]) -> int:
    """Write the harness project into out_dir (engine flows and tables copied from the project). Returns the tick
    count that runs every row."""
    if out_dir.exists():
        for sub in ("flows", "data"):
            shutil.rmtree(out_dir / sub, ignore_errors=True)
    (out_dir / "flows").mkdir(parents=True, exist_ok=True)
    (out_dir / "data").mkdir(parents=True, exist_ok=True)
    for name in GRAPHS:
        shutil.copyfile(FLOWS / f"{name}.xtflow", out_dir / "flows" / f"{name}.xtflow")
    (out_dir / "flows" / "driver.xtflow").write_bytes(gen_driver().text().encode("utf-8"))
    for name, rel in TABLES.items():
        shutil.copyfile(ROOT / rel, out_dir / "data" / f"{name}.json")
    (out_dir / "data" / "hIn.json").write_bytes(write_json(Path(), h_in).encode("utf-8"))
    (out_dir / "data" / "debScript.json").write_bytes(write_json(Path(), script).encode("utf-8"))
    tables = {name: f"data/{name}.json" for name in TABLES}
    tables["hIn"] = "data/hIn.json"
    tables[SCRIPT_TABLE] = script_table("data/debScript.json")
    game = {
        "game": 1, "xtatrium": "0.4", "name": "sherefox-debate-harness",
        "stepSeconds": 0.016666666666666666, "gravity": [0, 0], "collisionCategories": [],
        "signals": SIGNALS, "input": {"actions": {}, "axes": []},
        # the driver runs first, so the engine sees its values and pulses in the same tick (05 §5.4)
        "flows": ["flows/driver.xtflow"] + [f"flows/{n}.xtflow" for n in GRAPHS],
        "tables": tables,
        "collections": {**COLLECTIONS, **HARNESS_COLLECTIONS},
    }
    (out_dir / "game.json").write_bytes((json.dumps(game, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    return H_PERIOD * (len(h_in) + 2)


# --------------------------------------------------------------------------------------------- main

def main() -> int:
    check = "--check" in sys.argv[1:]
    stale = []
    for path, text in outputs().items():
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path.relative_to(ROOT).as_posix())
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
            print(f"wrote {path.relative_to(ROOT).as_posix()}")
    if not check:
        for name, (n, e) in graph_stats().items():
            print(f"{name}: {n} nodes, {e} edges")
    if stale:
        print("stale: " + ", ".join(stale) + " (run uv run tools/gen_debate.py)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
