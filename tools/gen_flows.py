# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generate the Atrium Script flows under flows/, their support tables under data/flow/ and the game.json entries
they need (M3: title -> chapter steps -> paper / vn / investigate / board; stubs for warmup, debate, result).

Usage (from the project root):
    uv run tools/gen_flows.py            write flows/*.xtflow, data/flow/*.json and the flow entries of game.json
    uv run tools/gen_flows.py --check    exit 1 if any of them differs from what this script generates
    uv run tools/gen_flows.py --stats    also print node / edge counts

The flows talk to each other only through world.* signals and collections (declared in game.json); see
docs/flows.md for the contract. Edge order matters where noted: a node delivers a value or pulse along its edges
in file order (XTAtrium 05 §5.4, TickProgram.OutFan), so an edge that must see a settled value comes after the
edges that change it, and a pulse that must see settled values goes through a merge or a gate (a pulse output
settles the batch before it is delivered).

Collections: an effect (add, set, ...) changes a collection at once, but a query whose inputs did not change is
re-evaluated only in step 4 of the next tick (08 §8.0, §8.3.2). So a step that has to read what an earlier step of
the same tick wrote runs one tick later, on a `next` timer (interval 1 ms, no repeat: it fires in step 4 of the next
tick). Timers are declared after every other node, so in that step 4 every query has been re-evaluated before the
timer's pulse is delivered (05 §5.4: the timed nodes run in declaration order).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLOWS = ROOT / "flows"
DATA = ROOT / "data"
FLOW_DATA = DATA / "flow"
GAME_JSON = ROOT / "game.json"

IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
FUNCS = {"abs", "floor", "ceil", "round", "trunc", "sqrt", "min", "max", "clamp", "lerp", "sign"}


def load(name: str) -> list[dict]:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


def split(cell: str) -> list[str]:
    return [x for x in cell.split(",") if x]


class Graph:
    """A flow under construction.

    `v` maps a value name to its source port; `x()` builds an atrium.expr whose identifiers are value names. Helpers
    that create a value register it under their node id, so a node id doubles as a value name in expressions.
    """

    def __init__(self) -> None:
        self.nodes: list[dict] = []
        self.late: list[dict] = []   # timers: declared last (see the module docstring)
        self.edges: list[dict] = []
        self._ids: set[str] = set()
        self._consts: dict[str, str] = {}
        self.v: dict[str, str] = {}

    # ---- raw
    def node(self, node_id: str, node_type: str, **params) -> str:
        if node_id in self._ids:
            raise ValueError(f"duplicate node id {node_id}")
        self._ids.add(node_id)
        n: dict = {"id": node_id, "type": node_type}
        if params:
            n["params"] = params
        (self.late if node_type == "timer" else self.nodes).append(n)
        return node_id

    def edge(self, src: str, dst: str) -> None:
        self.edges.append({"from": self.p(src), "to": dst})

    def p(self, name_or_port: str) -> str:
        return self.v.get(name_or_port, name_or_port)

    def const(self, node_id: str, value) -> str:
        """A named constant node (M2 style); returns the node id."""
        return self.node(node_id, "constant", value=value)

    def k(self, value) -> str:
        """A shared constant; returns its output port."""
        key = json.dumps(value)
        if key not in self._consts:
            nid = f"K{len(self._consts)}"
            self.node(nid, "constant", value=value)
            self._consts[key] = f"{nid}.out"
        return self._consts[key]

    def gate(self, node_id: str) -> str:
        """A pulse gate: `<id>.go` passes to `<id>.changed` while `<id>.guard` is true (53 §53.4.15 guard)."""
        return self.node(
            node_id,
            "state",
            states=["a", "b"],
            initial="a",
            transitions=[{"from": "a", "on": "go", "to": "b"}, {"from": "b", "on": "go", "to": "a"}],
        )

    # ---- values
    def put(self, name: str, port: str) -> str:
        self.v[name] = port
        return port

    def x(self, name: str, expr: str) -> str:
        """number `name` = atrium.expr; every identifier must be a value name. `<name>_t` is its truth (bool)."""
        self.node(name, "atrium.expr", expr=expr)
        seen = set()
        for ident in IDENT.findall(expr):
            if ident in FUNCS or ident in seen:
                continue
            seen.add(ident)
            if ident not in self.v:
                raise KeyError(f"{name}: unknown value '{ident}' in '{expr}'")
            self.edge(self.v[ident], f"{name}.{ident}")
        self.put(name + "_t", f"{name}.truth")
        return self.put(name, f"{name}.value")

    def b(self, name: str, num: str) -> str:
        """bool `name` = number != 0 (an expression's own truth output when `num` is one)."""
        src = self.p(num)
        if src.endswith(".value") and self._is_expr(src[: -len(".value")]):
            return self.put(name, src[: -len(".value")] + ".truth")
        self.node(name, "compare", op="ne")
        self.edge(num, f"{name}.a")
        self.edge(self.k(0), f"{name}.b")
        return self.put(name, f"{name}.out")

    def _is_expr(self, node_id: str) -> bool:
        return any(n["id"] == node_id and n["type"] == "atrium.expr" for n in self.nodes)

    def n(self, name: str, flag: str) -> str:
        """number `name` = bool ? 1 : 0."""
        self.node(name, "select")
        self.edge(flag, f"{name}.cond")
        self.edge(self.k(1), f"{name}.a")
        self.edge(self.k(0), f"{name}.b")
        return self.put(name, f"{name}.out")

    def cmp(self, name: str, a: str, b: str, op: str = "eq") -> str:
        """bool `name` = a op b (compare; strings or numbers)."""
        self.node(name, "compare", op=op)
        self.edge(a, f"{name}.a")
        self.edge(b, f"{name}.b")
        return self.put(name, f"{name}.out")

    def sel(self, name: str, cond: str, a: str, b: str) -> str:
        self.node(name, "select")
        self.edge(cond, f"{name}.cond")
        self.edge(a, f"{name}.a")
        self.edge(b, f"{name}.b")
        return self.put(name, f"{name}.out")

    def fmt(self, name: str, pattern: str, *args: str) -> str:
        self.node(name, "format", format=pattern)
        for slot, a in zip("abcd", args):
            self.edge(a, f"{name}.{slot}")
        return self.put(name, f"{name}.out")

    def tostr(self, name: str, src: str) -> str:
        self.node(name, "toString")
        self.edge(src, f"{name}.in")
        return self.put(name, f"{name}.out")

    def lookup(self, name: str, values: list, index: str) -> str:
        self.node(name, "lookup", values=values)
        self.edge(index, f"{name}.index")
        return self.put(name, f"{name}.out")

    def text(self, name: str, key: str) -> str:
        self.node(name, "atrium.text")
        self.edge(key, f"{name}.key")
        return self.put(name, f"{name}.text")

    def latch(self, name: str, value: str, trigger: str) -> str:
        """filter(sample): the value of `value` when `trigger` fires (passed values are always sent on)."""
        self.node(name, "filter", op="sample")
        self.edge(value, f"{name}.in")
        self.edge(trigger, f"{name}.trigger")
        return self.put(name, f"{name}.out")

    def merge(self, name: str, *sources: str) -> str:
        self.node(name, "merge")
        for s in sources:
            self.edge(s, f"{name}.in")
        return f"{name}.out"

    def when(self, name: str, pulse: str, cond: str) -> str:
        """The pulse, passed on only while `cond` holds; returns the output pulse. An expression condition (its
        truth) uses atrium.gate on the expression's number (08 §8.5a); any other bool uses a guarded state gate."""
        src = self.p(cond)
        if src.endswith(".truth"):
            self.node(name, "atrium.gate")
            self.edge(src[: -len(".truth")] + ".value", f"{name}.cond")
            self.edge(pulse, f"{name}.trigger")
            return f"{name}.pass"
        self.gate(name)
        self.edge(cond, f"{name}.guard")
        self.edge(pulse, f"{name}.go")
        return f"{name}.changed"

    def timer(self, name: str, interval: float = 0.001) -> tuple[str, str]:
        """A one-shot timer: `start` now, `tick` in step 4 of a later tick (1 ms: the next one; declared last)."""
        self.node(name, "timer", interval=interval, autostart=False, repeat=False)
        return f"{name}.start", f"{name}.tick"

    def toggle(self, name: str) -> str:
        self.node(name, "toggle", initial=False)
        return self.put(name, f"{name}.value")

    def counter(self, name: str, **params) -> str:
        self.node(name, "counter", **params)
        return self.put(name, f"{name}.value")

    # ---- data
    def tget(self, name: str, table: str, column: str, row: str, typ: str = "string") -> str:
        self.node(name, "atrium.table.get", table=table, column=column, type=typ)
        self.edge(row, f"{name}.row")
        return self.put(name, f"{name}.value")

    def tfind(self, name: str, table: str, column: str, value: str, filters: dict | None = None,
              frm: str | None = None) -> str:
        params = {"table": table, "column": column}
        if filters:
            params["filters"] = json.dumps(filters, ensure_ascii=False)
        self.node(name, "atrium.table.find", **params)
        self.edge(value, f"{name}.value")
        if frm is not None:
            self.edge(frm, f"{name}.from")
        return self.put(name, f"{name}.row")

    def thas(self, name: str, table: str, column: str, row: str, value: str) -> str:
        self.node(name, "atrium.table.has", table=table, column=column)
        self.edge(row, f"{name}.row")
        self.edge(value, f"{name}.value")
        return self.put(name, f"{name}.has")

    def cget(self, name: str, coll: str, index: str) -> str:
        self.node(name, "atrium.coll.get", name=coll)
        self.edge(index, f"{name}.index")
        self.put(name + "_ok", f"{name}.valid")
        return self.put(name, f"{name}.value")

    def contains(self, name: str, coll: str, value: str) -> str:
        self.node(name, "atrium.coll.contains", name=coll)
        self.edge(value, f"{name}.value")
        return self.put(name, f"{name}.has")

    def index_of(self, name: str, coll: str, value: str) -> str:
        self.node(name, "atrium.coll.indexOf", name=coll)
        self.edge(value, f"{name}.value")
        return self.put(name, f"{name}.index")

    def count(self, name: str, coll: str) -> str:
        self.node(name, "atrium.coll.count", name=coll)
        return self.put(name, f"{name}.count")

    def mget(self, name: str, coll: str, key: str) -> str:
        self.node(name, "atrium.map.get", name=coll)
        self.edge(key, f"{name}.key")
        return self.put(name, f"{name}.value")

    def mhas(self, name: str, coll: str, key: str) -> str:
        self.node(name, "atrium.map.has", name=coll)
        self.edge(key, f"{name}.key")
        return self.put(name, f"{name}.has")

    # ---- effects (return the trigger input)
    def eff(self, name: str, typ: str, coll: str, **inputs) -> str:
        self.node(name, typ, name=coll)
        for port, src in inputs.items():
            self.edge(src, f"{name}.{port}")
        return f"{name}.trigger"

    def ui_list(self, name: str, port: str, source: str, fields: dict, join: dict | None = None,
                localize: list | None = None) -> str:
        params = {"port": port, "source": source, "fields": json.dumps(fields, ensure_ascii=False)}
        if join:
            params["join"] = json.dumps(join, ensure_ascii=False)
        if localize:
            params["localize"] = localize
        self.node(name, "atrium.ui.list", **params)
        return f"{name}.trigger"

    def text_out(self) -> str:
        return json.dumps({"version": 1, "nodes": self.nodes + self.late, "edges": self.edges},
                          ensure_ascii=False, indent=2) + "\n"

    def stats(self) -> tuple[int, int]:
        return len(self.nodes) + len(self.late), len(self.edges)


class Mux:
    """A value shown on a port that several events set: each source latches its own values and makes itself the
    current source; the outputs follow the current source (select chains). `seq` counts the events."""

    def __init__(self, g: Graph, name: str, fields: list[str]) -> None:
        self.g, self.name, self.fields = g, name, fields
        self.sources: list[dict[str, str]] = []
        self.src = name + "Src.index"   # a state node, made when the outputs are first asked for
        self.seq = g.counter(name + "Seq", initial=0)

    def add(self, pulse: str, values: dict[str, str]) -> None:
        g, i = self.g, len(self.sources) + 1
        latched = {f: g.latch(f"{self.name}{i}_{f}", values[f], pulse) for f in self.fields}
        g.edge(pulse, f"{self.name}Src.e{i}")
        g.edge(pulse, f"{self.name}Seq.increment")
        self.sources.append(latched)

    def out(self, field: str, default: str) -> str:
        g, cur = self.g, default
        if self.name + "Src" not in g._ids:
            n = len(self.sources)
            g.node(self.name + "Src", "state", initial="s0", states=[f"s{i}" for i in range(n + 1)],
                   transitions=[{"from": "*", "on": f"e{i}", "to": f"s{i}"} for i in range(1, n + 1)])
        for i, latched in enumerate(self.sources, start=1):
            c = g.cmp(f"{self.name}_{field}_is{i}", self.src, g.k(i))
            cur = g.sel(f"{self.name}_{field}_{i}", c, latched[field], cur)
        return cur


# ---------------------------------------------------------------- support tables (data/flow)

GRADE = {"common": 0, "key": 1, "story": 2, "golden": 3, "substitute": 4}   # ui-contracts: popup_grade, sel_grade
SPOT_TYPE = {"inspect": 0, "evidence": 1, "testimony": 2}                   # ui-contracts investigate: spots.type
APPRAISE = {"none": 0, "medical": 1, "mechanical": 2, "dual": 3}
# data-schema §5: hotspots.scene -> the vn background id of that scene (script.bg).
SCENE_BG = {"kitchen": "kitchen_morning", "clock_shop": "clockshop", "boiler_room": "boiler_room",
            "deck": "barge_deck", "dock": "dock_fog"}
SLOTS = 15          # board: 3 chains x 5 slots (ui-contracts board)
LOOSE = 9           # debBoard slots 15..23 (docs/debate-engine.md §2.2)


def max_tags() -> int:
    return max(len(split(e["tags"])) for e in load("evidence"))


def case_cards(chapter: int) -> list[dict]:
    """The cards of a chapter's board, in evidence-table order: usable in the chapter and on the board."""
    return [e for e in load("evidence") if str(chapter) in split(e["usable"]) and e["onBoard"]]


def flow_tables() -> dict[str, list[dict]]:
    ev = load("evidence")
    hs = load("hotspots")
    chapters = [c["id"] for c in load("chapters")]
    mt = max_tags()

    card = []
    for e in ev:
        hidden, police = set(split(e["hiddenTags"])), set(split(e["policeTags"]))
        if police and police != hidden:
            raise ValueError(f"{e['id']}: policeTags must be empty or equal hiddenTags (flows reveal all at once)")
        tags = split(e["tags"])
        row = {"id": e["id"], "nameKey": e["nameKey"], "descKey": e["descKey"], "grade": GRADE[e["grade"]],
               "story": int(e["grade"] == "story"), "onBoard": int(e["onBoard"]), "appraise": APPRAISE[e["appraise"]],
               "cost": e["appraiseCost"], "hidden": int(bool(hidden)), "policeFull": int(bool(police)),
               "fixed": int(e["correct"] == -1), "correct": e["correct"],
               "reason1": e["reason0Key"], "reason2": e["reason1Key"], "reason3": e["reason2Key"],
               "golden": e["golden"], "goldenCard": int(e["grade"] == "golden"), "sub": int(e["grade"] == "substitute"),
               "obtainable": int(e["obtainable"]), "required": int(e["required"]),
               "tags": e["tags"], "hiddenTags": e["hiddenTags"], "grazingTags": e["grazingTags"]}
        for i in range(mt):
            row[f"tag{i}"] = tags[i] if i < len(tags) else ""
        card.append(row)

    spot, scene, case = [], [], []
    for c in chapters:
        rows = [h for h in hs if h["chapter"] == c and h["phase"] == "investigate" and not h["auto"]]
        scenes: list[str] = []
        for h in rows:
            ys = split(h["yields"])
            if len(ys) > 1:
                raise ValueError(f"{h['id']}: flows handle one card per hotspot")
            req = h["requires"]
            if req and not req.startswith("missing:"):
                raise ValueError(f"{h['id']}: unknown requires {req!r}")
            spot.append({"id": h["id"], "nameKey": h["nameKey"], "noteKey": h["noteKey"], "x": h["x"], "y": h["y"],
                         "w": h["w"], "h": h["h"], "type": SPOT_TYPE[h["type"]], "yield": ys[0] if ys else "",
                         "reqMissing": req[len("missing:"):] if req else ""})
            if h["scene"] not in scenes:
                scenes.append(h["scene"])
        for i, s in enumerate(scenes):
            scene.append({"key": f"{c}:{i}", "chapter": c, "idx": i, "bg": SCENE_BG[s],
                          "spots": ",".join(h["id"] for h in rows if h["scene"] == s)})
        cards = case_cards(c)
        # A substitute only appears when its golden clue is missing (01-systems §1.9), so they never both count.
        if len(cards) - min(sum(e["grade"] == "golden" for e in cards), sum(e["grade"] == "substitute" for e in cards)) > LOOSE:
            raise ValueError(f"Ch.{c}: {len(cards)} board cards, debBoard has {LOOSE} loose slots")
        case.append({"id": c, "scenes": len(scenes), "spots": ",".join(h["id"] for h in rows),
                     "eventCards": ",".join(e["id"] for e in ev if e["chapter"] == c and e["obtain"] == "event"),
                     "policeCards": ",".join(e["id"] for e in ev if e["chapter"] == c and e["policeTags"]),
                     "cards": ",".join(e["id"] for e in cards)})

    # Composite-key rows for list ports with more than one changing field per row (atrium.ui.list takes one join
    # and one collection value per row; docs/flows.md §7). Key = card id and the changing fields, "|"-separated.
    by_id = {r["id"]: r for r in card}
    order = [r["id"] for r in card]
    board_ids = sorted({e["id"] for c in chapters for e in case_cards(c)}, key=order.index)
    drawer = [{"key": f"{i}|{a}|{r}|{p}", "id": i, "nameKey": by_id[i]["nameKey"], "grade": by_id[i]["grade"],
               "appraised": bool(a), "reason_set": bool(r), "placed": bool(p)}
              for i in board_ids for a in (0, 1) for r in (0, 1) for p in (0, 1)]
    book = [{"key": f"{r['id']}|{a}|{n}", "id": r["id"], "nameKey": r["nameKey"], "grade": r["grade"],
             "appraised": bool(a), "isnew": bool(n)} for r in card for a in (0, 1) for n in (0, 1)]
    slot = [{"key": f"{s}|{i}", "chain": s // 5, "pos": s % 5, "id": i, "nameKey": by_id[i]["nameKey"],
             "grade": by_id[i]["grade"]} for s in range(SLOTS) for i in board_ids]
    link = [{"key": str(s), "chain": s // 5, "pos": s % 5} for s in range(SLOTS) if s % 5 < 4]
    chain = [{"key": f"{c}|{n}|{s}|{p}", "chain": c, "cards": n, "solid": s, "soph": p}
             for c in range(3) for n in range(6) for s in range(6) for p in range(6) if s + p <= max(n - 1, 0)]
    return {"flowCard": card, "flowSpot": spot, "flowScene": scene, "flowCase": case, "flowDrawer": drawer,
            "flowBook": book, "flowSlot": slot, "flowLink": link, "flowChain": chain}


def table_text(rows: list[dict]) -> str:
    return "[\n" + ",\n".join("  " + json.dumps(r, ensure_ascii=False) for r in rows) + "\n]\n"


# ---------------------------------------------------------------- game.json entries owned by the flows

SIGNALS = {
    "trust": {"type": "number", "initial": 3},          # 01-systems §3.1: permanent trust, starts at 3
    "bookOpen": {"type": "bool", "initial": False},     # main: the evidence book overlay is open
    "caseOutcome": {"type": "string", "initial": ""},   # debate result of the current case (stub: "win")
}
COLLECTIONS = {
    # case state (investigation -> board -> debate)
    "held": {"kind": "list", "type": "string", "capacity": 32, "unique": True},
    "appraised": {"kind": "list", "type": "string", "capacity": 32, "unique": True},
    "golden": {"kind": "list", "type": "string", "capacity": 8, "unique": True},
    "oppHand": {"kind": "list", "type": "string", "capacity": 16, "unique": True},
    "caseNum": {"kind": "map", "type": "number", "capacity": 8},
    "invState": {"kind": "map", "type": "number", "capacity": 8},
    "boardState": {"kind": "map", "type": "number", "capacity": 16},
    # investigation
    "spotSeen": {"kind": "map", "type": "number", "capacity": 64},
    "spotsHere": {"kind": "map", "type": "number", "capacity": 16},
    "toFind": {"kind": "list", "type": "string", "capacity": 32, "unique": True},
    "needed": {"kind": "list", "type": "string", "capacity": 8, "unique": True},
    "notes": {"kind": "list", "type": "string", "capacity": 32, "unique": True},
    "newCards": {"kind": "list", "type": "string", "capacity": 32, "unique": True},
    "caseSpots": {"kind": "list", "type": "string", "capacity": 64},
    "sceneSpots": {"kind": "list", "type": "string", "capacity": 16},
    "bookList": {"kind": "list", "type": "string", "capacity": 32},
    # board
    "row0": {"kind": "list", "type": "string", "capacity": 5, "unique": True},
    "row1": {"kind": "list", "type": "string", "capacity": 5, "unique": True},
    "row2": {"kind": "list", "type": "string", "capacity": 5, "unique": True},
    "reason": {"kind": "map", "type": "number", "capacity": 32},
    "caseCards": {"kind": "list", "type": "string", "capacity": 16, "unique": True},
    "boardCards": {"kind": "list", "type": "string", "capacity": 16, "unique": True},
    "slotList": {"kind": "list", "type": "string", "capacity": SLOTS},
    "linkMap": {"kind": "map", "type": "number", "capacity": 16},
    "chainMap": {"kind": "map", "type": "number", "capacity": 3},
    "drawerList": {"kind": "list", "type": "string", "capacity": 16},
    # the debate engine's board input (docs/debate-engine.md §2.2; same declaration as tools/gen_debate.py)
    "debBoard": {"kind": "list", "type": "string", "capacity": SLOTS + LOOSE},
    "debBoardOk": {"kind": "list", "type": "number", "capacity": SLOTS + LOOSE},
    "debBoardLink": {"kind": "list", "type": "number", "capacity": SLOTS + LOOSE},
    # dialogue cursor
    "dlgState": {"kind": "map", "type": "number", "capacity": 2},
}
FLOW_ORDER = ["main", "dialogue", "paper", "investigate", "board", "stubs"]


def game_json_text(tables: dict) -> str:
    game = json.loads(GAME_JSON.read_text(encoding="utf-8"))
    for name, decl in SIGNALS.items():
        game["signals"][name] = decl
    colls = game.get("collections", {})
    colls.update(COLLECTIONS)
    game["collections"] = colls
    for name in tables:
        game["tables"][name] = f"data/flow/{name}.json"
    game["flows"] = [f"flows/{f}.xtflow" for f in FLOW_ORDER]
    return json.dumps(game, ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------- shared pieces

def lang_changed(g: Graph) -> str:
    """A pulse when world.language changes (a state that follows it)."""
    g.cmp("langEn", "world.language", g.k("en"))
    return g.merge("langChanged", "langEn.true", "langEn.false")


def chapter_values(g: Graph) -> None:
    """Values of the current chapter: chapters row, flowCase row, police report (01-systems §3.1: trust >= 3)."""
    g.put("ch", "world.chapter")
    g.put("trust", "world.trust")
    g.tostr("chText", "world.chapter")
    g.tfind("chRow", "chapters", "id", "chText")
    g.tget("ticksInit", "chapters", "ticks", "chRow", "number")
    g.tget("apprInit", "chapters", "appraisals", "chRow", "number")
    g.tget("unlockedN", "chapters", "appraisalUnlocked", "chRow", "number")
    g.tget("policeCh", "chapters", "police", "chRow", "number")
    g.tget("trustShownN", "chapters", "trustShown", "chRow", "number")
    g.tget("missToHand", "chapters", "missToHand", "chRow", "number")
    g.tget("oppId", "chapters", "debate", "chRow")
    g.tget("phase", "chapters", "phase", "chRow")
    g.x("policeOn", "policeCh && trust >= 3")
    g.tfind("caseRow", "flowCase", "id", "chText")
    g.tget("caseScenes", "flowCase", "scenes", "caseRow", "number")
    g.tget("caseSpotsText", "flowCase", "spots", "caseRow")
    g.tget("caseEvent", "flowCase", "eventCards", "caseRow")
    g.tget("casePolice", "flowCase", "policeCards", "caseRow")
    g.tget("caseCardsText", "flowCase", "cards", "caseRow")
    g.mget("apprLeft", "caseNum", g.k("appr"))


def card_values(g: Graph, pre: str, card: str) -> str:
    """Per-card values for `card` (a string port) under value names <pre>_<field>; returns the flowCard row."""
    row = g.tfind(pre + "_row", "flowCard", "id", card)
    for col in ("grade", "story", "appraise", "cost", "hidden", "policeFull", "fixed", "correct", "goldenCard", "sub",
                "obtainable", "required", "onBoard"):
        g.tget(f"{pre}_{col}", "flowCard", col, row, "number")
    for col in ("nameKey", "descKey", "golden", "reason1", "reason2", "reason3"):
        g.tget(f"{pre}_{col}", "flowCard", col, row)
    g.n(pre + "_apprHas", g.contains(pre + "_apprC", "appraised", card))
    # Revealed: nothing hidden, appraised, or a police report that reveals all of it (01-systems §1.5, §3.1).
    g.x(pre + "_full", f"!{pre}_hidden || {pre}_apprHas || (policeOn && {pre}_policeFull)")
    return row


def reason_values(g: Graph, pre: str, card: str) -> None:
    """<pre>_rsn (chosen reason 1..3, 0 none), <pre>_ok (reason correct or fixed) for a card with card_values."""
    g.mget(pre + "_rsn", "reason", card)
    g.x(pre + "_ok", f"{pre}_fixed || {pre}_rsn == {pre}_correct + 1")
    g.x(pre + "_rset", f"{pre}_fixed || {pre}_rsn > 0")


def appraisal(g: Graph, pre: str, card: str, trigger: str) -> tuple[str, str]:
    """「交給亞瑟」(01-systems §1.5) on `card`: returns (line key port, pulse when a line is said).

    Not unlocked or no card: nothing. Nothing to appraise (cost 0 or already revealed): ART_APPR_NONE. Not enough
    charges left: ART_APPR_EMPTY. Otherwise the card joins `appraised`, the charges drop by its cost and Arthur says
    the done line of its kind. The decision is read before the effects (queries keep their value within the tick).
    """
    card_values(g, pre, card)
    g.n(pre + "_has", g.cmp(pre + "_hasC", card, g.k(""), "ne"))
    g.x(pre + "_idx", f"!({pre}_has && unlockedN) ? 0 : ({pre}_cost == 0 || {pre}_full) ? 1 : "
                      f"apprLeft < {pre}_cost ? 2 : 2 + {pre}_appraise")
    line = g.lookup(pre + "_line", ["", "ART_APPR_NONE", "ART_APPR_EMPTY", "ART_APPR_MED_DONE", "ART_APPR_MECH_DONE",
                                    "ART_APPR_DUAL"], pre + "_idx")
    g.x(pre + "_newLeft", f"apprLeft - {pre}_cost")
    do = g.when(pre + "_do", trigger, g.b(pre + "_doC", g.x(pre + "_doN", f"{pre}_idx >= 3")))
    g.edge(do, g.eff(pre + "_add", "atrium.coll.add", "appraised", value=card))
    g.edge(do, g.eff(pre + "_set", "atrium.map.set", "caseNum", key=g.k("appr"), value=pre + "_newLeft"))
    said = g.when(pre + "_said", trigger, g.b(pre + "_saidC", pre + "_idx"))
    return line, said


def tag_line(g: Graph, pre: str) -> str:
    """The detail panel's tag text for a card with card_values: each tag's display name, or UI_TAG_HIDDEN while it
    is not revealed, joined by a space (no separator key in the string table yet; docs/flows.md §7)."""
    pieces = []
    for i in range(max_tags()):
        t = g.tget(f"{pre}_t{i}", "flowCard", f"tag{i}", pre + "_row")
        g.n(f"{pre}_h{i}", g.thas(f"{pre}_hC{i}", "flowCard", "hiddenTags", pre + "_row", t))
        g.tget(f"{pre}_tk{i}", "tags", "nameKey", g.tfind(f"{pre}_tr{i}", "tags", "id", t))
        rev = g.b(f"{pre}_rv{i}", g.x(f"{pre}_rvN{i}", f"!{pre}_h{i} || {pre}_full"))
        key = g.sel(f"{pre}_key{i}", rev, f"{pre}_tk{i}", g.k("UI_TAG_HIDDEN"))
        has = g.cmp(f"{pre}_e{i}", t, g.k(""), "ne")
        key = g.sel(f"{pre}_kk{i}", has, key, g.k(""))
        txt = g.text(f"{pre}_tx{i}", key)
        if i == 0:
            pieces.append(txt)
        else:
            pieces.append(g.sel(f"{pre}_p{i}", has, g.fmt(f"{pre}_sp{i}", " {a}", txt), g.k("")))
    out = g.fmt(pre + "_tags", "{a}{b}{c}{d}", *pieces[:4])
    if len(pieces) > 4:
        out = g.fmt(pre + "_tags2", "{a}{b}{c}{d}", out, *pieces[4:7])
    return out


# ---------------------------------------------------------------- main

def gen_main() -> Graph:
    """App state machine: title, the step runner over the steps table, surface visibility, language."""
    g = Graph()

    # Language toggle (M0 behaviour). The state follows world.language when something else writes it (--lang,
    # a later settings screen); the title's toggle flips the state, which writes world.language.
    g.node("lang", "state", initial="zh", states=["zh", "en"],
           transitions=[{"from": "zh", "on": "toggle", "to": "en"}, {"from": "en", "on": "toggle", "to": "zh"}])
    g.node("langTag", "lookup", values=["zh-TW", "en"])
    g.const("enTag", "en")
    g.node("langIsEn", "compare", op="eq")
    g.node("langName", "select")
    g.const("zhName", "zh")
    g.const("enName", "en")
    g.const("one", 1)
    g.node("isEnUi", "compare", op="eq")
    g.edge("ui#title.lang_toggle", "lang.toggle")
    g.edge("lang.index", "langTag.index")
    g.edge("langTag.out", "world.language")
    g.edge("world.language", "langIsEn.a")
    g.edge("enTag.out", "langIsEn.b")
    g.edge("langIsEn.out", "langName.cond")
    g.edge("enName.out", "langName.a")
    g.edge("zhName.out", "langName.b")
    g.edge("langName.out", "lang.set")
    g.edge("lang.index", "isEnUi.a")
    g.edge("one.out", "isEnUi.b")
    g.edge("isEnUi.out", "ui#title.lang_en")

    # Step runner. cur = row of the steps table (-1 = none). Choosing a chapter jumps to that chapter's idx-0 row:
    # the row is latched on every emit of title.chapter (AT-040 `.emitted`), so choosing the same chapter again
    # restarts it. Each world.stepDone moves to the next row (rows are in chapter, idx order; data-schema §2).
    g.node("chText", "toString")
    g.const("zeroText", "0")
    g.node("chStart", "atrium.table.find", table="steps", column="chapter", filterColumn="idx")
    g.node("chPick", "filter", op="sample")
    g.node("cur", "counter", initial=-1)
    g.node("kind", "atrium.table.get", table="steps", column="kind", type="string")
    g.node("arg", "atrium.table.get", table="steps", column="arg", type="string")
    g.node("scene", "atrium.table.get", table="steps", column="scene", type="string")
    g.node("chapter", "atrium.table.get", table="steps", column="chapter", type="number")
    g.node("begin", "filter", op="deadband", threshold=0)
    g.node("rebegin", "merge")
    g.edge("ui#title.chapter", "chText.in")
    g.edge("chText.out", "chStart.value")
    g.edge("zeroText.out", "chStart.filterValue")
    g.edge("chStart.row", "chPick.in")
    # The comparison first: whether the chosen row is already the current one (then cur does not change and the
    # step is begun again below).
    g.node("same", "compare", op="eq")
    g.edge("chStart.row", "same.a")
    g.edge("cur.value", "same.b")
    g.gate("sameGate")
    g.edge("same.out", "sameGate.guard")
    g.edge("ui#title.chapter.emitted", "sameGate.go")
    g.edge("ui#title.chapter.emitted", "chPick.trigger")
    g.edge("chPick.out", "cur.set")
    g.edge("world.stepDone", "cur.increment")
    g.edge("cur.value", "kind.row")
    g.edge("cur.value", "arg.row")
    g.edge("cur.value", "scene.row")
    g.edge("cur.value", "chapter.row")
    g.edge("cur.value", "world.stepRow")
    g.edge("kind.value", "world.stepKind")
    g.edge("arg.value", "world.stepArg")
    g.edge("scene.value", "world.stepScene")
    g.edge("chapter.value", "world.chapter")
    # Last edge of cur.value: the pulse goes out after the step's kind/arg/scene/chapter are settled and written.
    g.edge("cur.value", "begin.in")
    g.edge("begin.passed", "rebegin.in")
    g.edge("sameGate.changed", "rebegin.in")
    g.edge("rebegin.out", "world.stepBegin")

    # Screens: exactly one of title / paper / vn / investigate / board is visible. Stub steps (warmup, debate,
    # result) leave the current screen as it is; `end` shows the title with its end card.
    screens = ["title", "paper", "vn", "investigate", "board"]
    g.node("screen", "state", initial="title", states=screens,
           transitions=[{"from": "*", "on": "to_" + s, "to": s} for s in screens])
    for name, tag, scr in (("isEnd", "end", "title"), ("isPaper", "paper", "paper"), ("isVn", "vn", "vn"),
                           ("isInv", "investigate", "investigate"), ("isBoard", "board", "board")):
        g.const(name + "Tag", tag)
        g.node(name, "compare", op="eq")
        g.edge("kind.value", name + ".a")
        g.edge(name + "Tag.out", name + ".b")
        g.edge(name + ".true", f"screen.to_{scr}")

    # End card: shown while the step is `end` until the title's end_dismiss. The step stays `end`, so the chapter
    # list (no longer covered) starts a new run; entering an end step shows the card again.
    g.node("card", "state", initial="open", states=["open", "closed"],
           transitions=[{"from": "open", "on": "dismiss", "to": "closed"},
                        {"from": "*", "on": "rearm", "to": "open"}])
    g.const("zeroIdx", 0)
    g.const("no", False)
    g.node("cardOpen", "compare", op="eq")
    g.node("ended", "select")
    g.edge("isEnd.true", "card.rearm")
    g.edge("ui#title.end_dismiss", "card.dismiss")
    g.edge("card.index", "cardOpen.a")
    g.edge("zeroIdx.out", "cardOpen.b")
    g.edge("isEnd.out", "ended.cond")
    g.edge("cardOpen.out", "ended.a")
    g.edge("no.out", "ended.b")
    g.edge("ended.out", "ui#title.ended")
    for i, ui in enumerate(screens):
        nid = "vis" + ui.capitalize()
        g.node(nid, "lookup", values=[j == i for j in range(len(screens))])
        g.edge("screen.index", nid + ".index")
        g.edge(nid + ".out", f"ui#{ui}.visible")

    # Evidence book overlay (modal): investigate.book opens it during an investigate step, its close button closes
    # it, every step begin closes it. world.bookOpen tells the investigate flow.
    g.node("book", "state", initial="closed", states=["closed", "open"],
           transitions=[{"from": "closed", "on": "open", "to": "open"}, {"from": "*", "on": "close", "to": "closed"}])
    g.gate("bookGate")
    g.edge("isInv.out", "bookGate.guard")
    g.edge("ui#investigate.book", "bookGate.go")
    g.edge("bookGate.changed", "book.open")
    g.edge("ui#evbook.close", "book.close")
    g.edge("rebegin.out", "book.close")
    g.node("bookVis", "lookup", values=[False, True])
    g.edge("book.index", "bookVis.index")
    g.edge("bookVis.out", "ui#evbook.visible")
    g.edge("bookVis.out", "world.bookOpen")
    return g


# ---------------------------------------------------------------- dialogue

def gen_dialogue() -> Graph:
    """vn steps: walk the playable rows of the step's scene in the script table, one row per ui#vn.advance.

    The cursor (the shown row) lives in the map `dlgState` (key "row"): the flow is acyclic, so it cannot feed the
    row it found back into the find that looks for the next one; the map is read back on the next tick (an advance
    never comes in the tick its row was written). next = find(script, sceneKey, filters playable, from = row + 1)
    skips the rows that are not played (AT-040); -1 = the scene is over (step done)."""
    g = Graph()
    g.const("vnTag", "vn")
    g.const("empty", "")
    g.const("no", False)
    g.const("zero", 0)
    g.const("minusOne", -1)
    g.node("isVn", "compare", op="eq")
    g.node("vnScene", "select")
    g.node("chText", "toString")
    g.node("sceneKey", "format", format="CH0{a}_{b}")   # script.sceneKey, e.g. CH01_S02 (chapters 1-9)
    g.edge("world.stepKind", "isVn.a")
    g.edge("vnTag.out", "isVn.b")
    g.edge("isVn.out", "vnScene.cond")
    g.edge("world.stepScene", "vnScene.a")
    g.edge("empty.out", "vnScene.b")
    g.edge("world.chapter", "chText.in")
    g.edge("world.chapter", "sceneKey.a")
    g.edge("vnScene.out", "sceneKey.b")

    playable = {"playable": "true"}
    g.tfind("first", "script", "sceneKey", "sceneKey.out", filters=playable)
    g.mget("cur", "dlgState", g.k("row"))
    g.x("from", "cur + 1")
    g.tfind("next", "script", "sceneKey", "sceneKey.out", filters=playable, frm="from")
    g.toggle("atBegin")
    g.sel("pick", "atBegin.value", "first", "next")
    g.x("pickOk", "pick >= 0")
    g.x("pickNo", "pick < 0")

    # Step begin (vn) shows the first playable row; each advance (only during a vn step) shows the next one, or
    # ends the step when there is none. The toggle selects first/next; the merge settles it before the gates read it.
    g.gate("beginGate")
    g.edge("isVn.out", "beginGate.guard")
    g.edge("world.stepBegin", "beginGate.go")
    g.gate("advGate")
    g.edge("isVn.out", "advGate.guard")
    g.edge("ui#vn.advance", "advGate.go")
    g.edge("beginGate.changed", "atBegin.setTrue")
    g.edge("advGate.changed", "atBegin.setFalse")
    g.node("show", "merge")
    g.edge("beginGate.changed", "show.in")
    g.edge("advGate.changed", "show.in")
    shown = g.when("showGate", "show.out", "pickOk_t")
    over = g.when("overGate", "show.out", "pickNo_t")
    g.edge(over, "world.stepDone")
    g.node("disp", "filter", op="sample")
    g.edge("pick", "disp.in")
    g.edge(shown, "disp.trigger")
    g.edge(shown, g.eff("setRow", "atrium.map.set", "dlgState", key=g.k("row"), value="pick"))
    g.node("seqBarrier", "merge")
    g.node("lineSeq", "counter", initial=0)
    g.edge(shown, "seqBarrier.in")   # after disp: line text first, then line_seq
    g.edge("seqBarrier.out", "lineSeq.increment")
    g.edge("lineSeq.value", "ui#vn.line_seq")

    # The shown row -> vn ports. Text is resolved by atrium.text, so a language switch re-resolves it live.
    cols = [("spk", "speaker", "string"), ("txt", "text", "string"), ("bg", "bg", "string"),
            ("slotL", "slot_l", "string"), ("slotC", "slot_c", "string"), ("slotR", "slot_r", "string"),
            ("focus", "focus", "number"), ("style", "style", "number")]
    for nid, col, typ in cols:
        g.node(nid, "atrium.table.get", table="script", column=col, type=typ)
        g.edge("disp.out", nid + ".row")
    g.node("hasSpeaker", "compare", op="ne")
    g.node("spkKey", "select")
    g.node("spkText", "atrium.text")
    g.node("lineText", "atrium.text")
    g.edge("focus.value", "hasSpeaker.a")
    g.edge("zero.out", "hasSpeaker.b")
    g.edge("hasSpeaker.out", "spkKey.cond")   # narration, system and newspaper lines (focus 0) have no name plate
    g.edge("spk.value", "spkKey.a")
    g.edge("empty.out", "spkKey.b")
    g.edge("spkKey.out", "spkText.key")
    g.edge("spkText.text", "ui#vn.speaker")
    g.edge("txt.value", "lineText.key")
    g.edge("lineText.text", "ui#vn.line")
    g.edge("bg.value", "ui#vn.bg")
    g.edge("slotL.value", "ui#vn.slot_l")
    g.edge("slotC.value", "ui#vn.slot_c")
    g.edge("slotR.value", "ui#vn.slot_r")
    g.edge("focus.value", "ui#vn.focus")
    g.edge("style.value", "ui#vn.style")

    # Chapter tab, no choices in Ch.1-3, trust row hidden until the trust system exists.
    g.node("chRow", "atrium.table.find", table="chapters", column="id")
    g.node("chTitleKey", "atrium.table.get", table="chapters", column="titleKey", type="string")
    g.node("chTitle", "atrium.text")
    g.edge("chText.out", "chRow.value")
    g.edge("chRow.row", "chTitleKey.row")
    g.edge("chTitleKey.value", "chTitle.key")
    g.edge("chTitle.text", "ui#vn.chapter_title")
    g.edge("zero.out", "ui#vn.choice_count")
    for i in range(1, 5):
        g.edge("empty.out", f"ui#vn.choice{i}")
        g.edge("no.out", f"ui#vn.choice_locked{i}")
    g.edge("minusOne.out", "ui#vn.trust")
    return g


# ---------------------------------------------------------------- paper

def gen_paper() -> Graph:
    """paper steps: fill ui#paper from the papers row (group = step arg); next/prev turn pages, next on page 2 ends."""
    g = Graph()
    g.const("paperTag", "paper")
    g.const("empty", "")
    g.const("zero", 0)
    g.const("three", 3)
    g.node("isPaper", "compare", op="eq")
    g.gate("paperBegin")
    g.node("paperId", "filter", op="sample")
    g.node("prow", "atrium.table.find", table="papers", column="group")
    g.edge("world.stepKind", "isPaper.a")
    g.edge("paperTag.out", "isPaper.b")
    # The paper id is latched when a paper step begins, so the pages keep their text while the surface hides.
    g.edge("isPaper.out", "paperBegin.guard")
    g.edge("world.stepBegin", "paperBegin.go")
    g.edge("world.stepArg", "paperId.in")
    g.edge("paperBegin.changed", "paperId.trigger")
    g.edge("paperId.out", "prow.value")

    def key(nid: str, col: str) -> str:
        g.node(nid, "atrium.table.get", table="papers", column=col, type="string")
        g.edge("prow.row", nid + ".row")
        return nid + ".value"

    def text(nid: str, key_src: str, port: str | None) -> str:
        g.node(nid, "atrium.text")
        g.edge(key_src, nid + ".key")
        if port:
            g.edge(nid + ".text", f"ui#paper.{port}")
        return nid + ".text"

    # One papers column per port (data-schema §9). An empty key gives an empty string, which hides that part:
    # no second-page story, no advert, no "previous case" strip on the Ch.1 paper.
    text("headline", key("headlineKey", "headlineKey"), "headline")
    text("subhead", key("subKey", "subKey"), "subhead")
    text("body", key("bodyKey", "bodyKey"), "body")
    text("page2Head", key("page2HeadKey", "page2HeadKey"), "page2_head")
    text("page2Body", key("page2BodyKey", "page2BodyKey"), "page2_body")
    text("side", key("sideKey", "sideKey"), "side")
    text("ad", key("adKey", "adKey"), "ad")
    # The "previous case" strip. The debate is still a stub (world.caseOutcome = win): always the WIN variant.
    text("resultHead", key("sideWinKey", "sideWinKey"), "result_head")
    text("resultSub", key("sideWinSubKey", "sideWinSubKey"), "result_sub")
    g.edge(key("pictureId", "pictureId"), "ui#paper.picture")

    # No data for these yet (docs/flows.md): plain masthead, no stamp, no dateline.
    g.edge("zero.out", "ui#paper.mast")
    g.edge("zero.out", "ui#paper.stamp")
    g.edge("empty.out", "ui#paper.dateline")

    # Pages: pg 1 = front page, 2 = second page, 3 = read (step done). Reset when a paper step begins; next/prev
    # only count during a paper step.
    g.node("pg", "counter", initial=1, min=1, max=3)
    g.node("page", "atrium.expr", expr="min(pg, 2)")
    g.node("pgDone", "compare", op="ge")
    g.gate("nextGate")
    g.gate("prevGate")
    g.edge("paperBegin.changed", "pg.reset")
    g.edge("isPaper.out", "nextGate.guard")
    g.edge("isPaper.out", "prevGate.guard")
    g.edge("ui#paper.next", "nextGate.go")
    g.edge("ui#paper.prev", "prevGate.go")
    g.edge("nextGate.changed", "pg.increment")
    g.edge("prevGate.changed", "pg.decrement")
    g.edge("pg.value", "page.pg")
    g.edge("page.value", "ui#paper.page")
    g.edge("pg.value", "pgDone.a")
    g.edge("three.out", "pgDone.b")
    g.edge("pgDone.true", "world.stepDone")
    return g


# ---------------------------------------------------------------- investigate (+ evidence book)

def gen_investigate() -> Graph:
    """investigate steps (01-systems §1) and the evidence book overlay (ui-contracts investigate, evbook)."""
    g = Graph()
    chapter_values(g)
    lang = lang_changed(g)
    isInv = g.cmp("isInv", "world.stepKind", g.k("investigate"))
    begin = g.when("beginGate", "world.stepBegin", isInv)
    g.x("lim", "ticksInit > 0")                      # Ch.1: unlimited (-1)
    # State that gates the pulses that change it lives in the map invState (a node feeding back into the gate of
    # its own setter would be a cycle): ticks left, scene index, popup open. Written now, read from the next tick.
    g.mget("ticks", "invState", g.k("ticks"))
    g.mget("sc", "invState", g.k("sc"))                # scene index (Ch.3 has three scenes)
    g.mget("popOpenN", "invState", g.k("pop"))
    popOpen = g.b("popOpen", "popOpenN")
    bookNew = g.counter("bookNew", initial=0)

    def put_state(name: str, pulse: str, key: str, value: str) -> None:
        g.edge(pulse, g.eff(name, "atrium.map.set", "invState", key=g.k(key), value=value))
    g.n("bookOpenN", "world.bookOpen")
    g.count("neededN", "needed")
    g.count("toFindN", "toFind")
    g.x("outOfTime", "lim && ticks <= 0")
    g.x("canEndN", "neededN == 0")
    g.x("inputOk", "!popOpenN && !bookOpenN")

    hint = Mux(g, "hint", ["key"])
    popup = Mux(g, "pop", ["kind", "title", "body", "grade"])
    initStart, initTick = g.timer("initTimer")
    bookStart, bookTick = g.timer("bookTimer")

    # ---- step begin: clear the case, cards obtained in the event scenes (evidence.obtain = event), the police
    # report (01-systems §3.1: trust >= 3 gives the autopsy card revealed), ticks, charges; the rest next tick.
    for coll in ("held", "appraised", "spotSeen", "toFind", "needed", "oppHand", "notes", "newCards", "spotsHere",
                 "caseSpots"):
        typ = "atrium.map.clear" if COLLECTIONS[coll]["kind"] == "map" else "atrium.coll.clear"
        g.node(f"clr_{coll}", typ, name=coll)
        g.edge(begin, f"clr_{coll}.trigger")
    g.edge(begin, g.eff("addEvent", "atrium.coll.addAll", "held", text="caseEvent"))
    g.edge(g.when("policeGate", begin, "policeOn_t"), g.eff("addPolice", "atrium.coll.addAll", "held",
                                                            text="casePolice"))
    g.edge(begin, g.eff("addSpots", "atrium.coll.addAll", "caseSpots", text="caseSpotsText"))
    g.edge(begin, g.eff("clr_invState", "atrium.map.clear", "invState"))
    put_state("ticksSet", begin, "ticks", "ticksInit")
    g.edge(begin, g.eff("apprSet", "atrium.map.set", "caseNum", key=g.k("appr"), value="apprInit"))
    g.edge(begin, "bookNew.reset")
    # Opening line (01-systems §1.4, ART_OPEN_CH0n); a police case without the report: ART_NO_REPORT (§1.11).
    g.fmt("openKey", "ART_OPEN_CH0{a}", "ch")
    g.x("noReport", "policeCh && !policeOn")
    g.sel("openLine", "noReport_t", g.k("ART_NO_REPORT"), "openKey")
    hint.add(begin, {"key": "openLine"})
    g.edge(begin, initStart)

    # ---- next tick: what the spots can still give (toFind; required ones in `needed`), then the first scene.
    g.node("spotEach", "atrium.coll.forEach", name="caseSpots")
    g.edge(initTick, "spotEach.trigger")
    g.put("si", "spotEach.item")
    srow = g.tfind("si_row", "flowSpot", "id", "si")
    g.tget("si_type", "flowSpot", "type", srow, "number")
    g.tget("si_yield", "flowSpot", "yield", srow)
    g.tget("si_req", "flowSpot", "reqMissing", srow)
    g.n("si_held", g.contains("si_heldC", "held", "si_yield"))
    g.n("si_gold", g.contains("si_goldC", "golden", "si_req"))
    g.tget("si_required", "flowCard", "required", g.tfind("si_crow", "flowCard", "id", "si_yield"), "number")
    g.n("si_noReq", g.cmp("si_noReqC", "si_req", g.k(""), "eq"))
    g.x("si_find", "si_type > 0 && (si_noReq || !si_gold) && !si_held")
    g.x("si_need", "si_find && si_required")
    g.edge(g.when("si_findG", "spotEach.each", "si_find_t"), g.eff("si_add", "atrium.coll.add", "toFind",
                                                                   value="si_yield"))
    g.edge(g.when("si_needG", "spotEach.each", "si_need_t"), g.eff("si_needA", "atrium.coll.add", "needed",
                                                                   value="si_yield"))

    # ---- scene: background, arrows, and its spots (spotsHere: id -> 0 not visited / 1 visited) -> spots list.
    g.fmt("sceneKey", "{a}:{b}", "ch", "sc")
    scrow = g.tfind("sceneRow", "flowScene", "key", "sceneKey")
    g.edge(g.tget("sceneBg", "flowScene", "bg", scrow), "ui#investigate.bg")
    g.tget("sceneSpotsText", "flowScene", "spots", scrow)
    g.edge(g.cmp("navPrev", "sc", g.k(0), "gt"), "ui#investigate.nav_prev")
    g.x("lastScene", "caseScenes - 1")
    g.edge(g.cmp("navNext", "sc", "lastScene", "lt"), "ui#investigate.nav_next")
    g.edge(g.k(""), "ui#investigate.area_name")   # no scene-name keys yet (docs/flows.md §7)
    spots_list = g.ui_list("spotsList", "ui.investigate.spots", "spotsHere",
                           {"id": "key", "name": "nameKey", "x": "x", "y": "y", "w": "w", "h": "h", "type": "type",
                            "state": "value"}, join={"table": "flowSpot", "column": "id"}, localize=["name"])
    rebuild = g.merge("rebuild")
    g.edge(rebuild, g.eff("clrHere", "atrium.map.clear", "spotsHere"))
    g.edge(rebuild, g.eff("clrScene", "atrium.coll.clear", "sceneSpots"))
    g.edge(rebuild, g.eff("addScene", "atrium.coll.addAll", "sceneSpots", text="sceneSpotsText"))
    g.node("sceneEach", "atrium.coll.forEach", name="sceneSpots")
    g.edge(rebuild, "sceneEach.trigger")
    g.edge(rebuild, spots_list)
    g.put("ss", "sceneEach.item")
    g.tget("ss_req", "flowSpot", "reqMissing", g.tfind("ss_row", "flowSpot", "id", "ss"))
    g.n("ss_noReq", g.cmp("ss_noReqC", "ss_req", g.k(""), "eq"))
    g.n("ss_gold", g.contains("ss_goldC", "golden", "ss_req"))
    g.n("ss_seen", g.mhas("ss_seenC", "spotSeen", "ss"))
    g.x("ss_show", "ss_noReq || !ss_gold")
    g.edge(g.when("ss_showG", "sceneEach.each", "ss_show_t"),
           g.eff("ss_set", "atrium.map.set", "spotsHere", key="ss", value="ss_seen"))
    g.edge(initTick, "rebuild.in")
    g.edge(lang, spots_list)

    # Area arrows (Ch.3): nav -1 / +1, switching costs nothing (§1.4).
    g.put("navV", "ui#investigate.nav")
    nav = g.when("navGate", g.when("navInv", "ui#investigate.nav.emitted", isInv), "inputOk_t")
    g.x("navIncN", "navV > 0 && sc < caseScenes - 1")
    g.x("navDecN", "navV < 0 && sc > 0")
    g.x("scUp", "sc + 1")
    g.x("scDown", "sc - 1")
    put_state("navIncS", g.when("navInc", nav, "navIncN_t"), "sc", "scUp")
    put_state("navDecS", g.when("navDec", nav, "navDecN_t"), "sc", "scDown")
    navStart, navTick = g.timer("navTimer")
    g.edge(nav, navStart)
    g.edge(navTick, "rebuild.in")

    # ---- a spot click (01-systems §1.2, §1.4; rulings F5, F6). The values below are read before the effects:
    # a query keeps its value for the rest of the tick unless its input changes.
    g.put("spot", "ui#investigate.spot")
    crow = g.tfind("c_row", "flowSpot", "id", "spot")
    g.tget("c_type", "flowSpot", "type", crow, "number")
    g.tget("c_yield", "flowSpot", "yield", crow)
    g.tget("c_name", "flowSpot", "nameKey", crow)
    g.tget("c_note", "flowSpot", "noteKey", crow)
    card_values(g, "cy", "c_yield")
    g.n("c_seen", g.mhas("c_seenC", "spotSeen", "spot"))
    g.n("c_held", g.contains("c_heldC", "held", "c_yield"))
    g.x("c_costs", "!c_seen")
    # A card already held (event cards, the police report) is not obtained again: its spot shows the card as
    # information. Visited spots replay for free; the first visit of any spot costs one tick (F5, F6).
    g.x("c_obtain", "c_type > 0 && !c_held")
    g.x("c_kind", "c_type == 0 ? 1 : c_obtain ? (c_type == 2 ? 3 : 2) : 1")
    g.x("c_inspect", "c_type == 0")
    g.sel("c_title", "c_inspect_t", "c_name", "cy_nameKey")
    g.sel("c_body", "c_inspect_t", "c_note", "cy_descKey")
    g.x("clickOkN", "inputOk && !outOfTime")
    click = g.when("clickGate", g.when("clickInv", "ui#investigate.spot.emitted", isInv), "clickOkN_t")
    costs = g.when("c_costG", click, "c_costs_t")
    g.edge(costs, g.eff("c_seenSet", "atrium.map.set", "spotSeen", key="spot", value=g.k(1)))
    g.edge(costs, g.eff("c_hereSet", "atrium.map.set", "spotsHere", key="spot", value=g.k(1)))
    g.x("ticksLess", "ticks - 1")
    put_state("c_tickS", g.when("c_tickG", costs, "lim_t"), "ticks", "ticksLess")
    obtain = g.when("c_obtG", click, "c_obtain_t")
    for coll, typ in (("held", "add"), ("toFind", "remove"), ("needed", "remove"), ("newCards", "add")):
        g.edge(obtain, g.eff(f"c_do_{coll}", f"atrium.coll.{typ}", coll, value="c_yield"))
    g.edge(obtain, "bookNew.increment")
    g.edge(g.when("c_noteG", click, "c_inspect_t"), g.eff("c_noteAdd", "atrium.coll.add", "notes", value="c_note"))
    popup.add(click, {"kind": "c_kind", "title": "c_title", "body": "c_body", "grade": "cy_grade"})
    put_state("c_popS", click, "pop", g.k(1))
    # Arthur's line after the click (ticks read before it: 1 = time out, 4 = 3 left) (§1.3 ART_TIME_LOW), a key /
    # story / substitute card obtained; none in Ch.1, where Arthur is not the assistant yet (§1.11).
    g.x("c_hint", "ch == 1 ? 0 : (lim && c_costs && ticks == 1) ? 1 : (lim && c_costs && ticks == 4) ? 2 : "
                  "c_obtain ? (cy_grade == 1 ? 3 : cy_grade == 2 ? 4 : cy_grade == 4 ? 5 : 0) : 0")
    g.lookup("c_hintKey", ["", "ART_TIME_OUT", "ART_TIME_LOW", "ART_FOUND_KEY", "ART_FOUND_PLOT", "ART_SUB_FOUND"],
             "c_hint")
    hint.add(g.when("c_hintG", g.merge("c_hintM", click), "c_hint_t"), {"key": "c_hintKey"})
    g.edge(click, spots_list)

    # ---- popup closed. Out of ticks: first the required-card rescue (§1.7 ART_RESCUE, shown as an obtained card),
    # then the end of the investigation.
    dismiss = g.when("dismissGate", g.when("dismissInv", "ui#investigate.dismiss", isInv), popOpen)
    put_state("d_popS", dismiss, "pop", g.k(0))
    g.x("rescueN", "outOfTime && neededN > 0")
    rescue = g.when("rescueGate", dismiss, "rescueN_t")
    g.cget("rc", "needed", g.k(0))
    card_values(g, "rcv", "rc")
    popup.add(rescue, {"kind": g.k(2), "title": "rcv_nameKey", "body": "rcv_descKey", "grade": "rcv_grade"})
    hint.add(rescue, {"key": g.k("ART_RESCUE")})
    put_state("r_popS", rescue, "pop", g.k(1))
    g.node("rescueEach", "atrium.coll.forEach", name="needed")
    g.edge(rescue, "rescueEach.trigger")
    for coll, typ in (("held", "add"), ("toFind", "remove"), ("newCards", "add")):
        g.edge("rescueEach.each", g.eff(f"r_{coll}", f"atrium.coll.{typ}", coll, value="rescueEach.item"))
    g.edge("rescueEach.each", "bookNew.increment")
    g.edge(rescue, g.eff("r_clear", "atrium.coll.clear", "needed"))
    finish = g.merge("finish")
    g.x("timeoutN", "outOfTime && neededN == 0")
    g.edge(g.when("timeoutEnd", dismiss, "timeoutN_t"), "finish.in")
    g.x("endOkN", "inputOk && canEndN")
    g.edge(g.when("endGate", g.when("endInv", "ui#investigate.end", isInv), "endOkN_t"), "finish.in")
    # End (§1.8): every card the spots could still give that the opponent can obtain goes to his hand (D4: hand +1,
    # HP +10 each; applied by the debate); not in Ch.1 (chapters.missToHand). Then the step is done.
    g.node("missEach", "atrium.coll.forEach", name="toFind")
    g.edge(finish, "missEach.trigger")
    g.put("mi", "missEach.item")
    g.tget("mi_obt", "flowCard", "obtainable", g.tfind("mi_row", "flowCard", "id", "mi"), "number")
    g.x("mi_n", "mi_obt && missToHand")
    g.edge(g.when("mi_g", "missEach.each", "mi_n_t"), g.eff("mi_add", "atrium.coll.add", "oppHand", value="mi"))
    g.edge(g.merge("finishDone", finish), "world.stepDone")

    # ---- Arthur's hint (ask_hint): cards still to find (§1.11); Ch.1 is Sherefox's own line.
    ask = g.when("askGate", g.when("askInv", "ui#investigate.ask_hint", isInv), "inputOk_t")
    g.x("askIdx", "ch == 1 ? (toFindN > 0 ? 1 : 2) : toFindN >= 4 ? 3 : toFindN >= 1 ? 4 : 5")
    g.lookup("askKey", ["", "SHF_C1_REMAIN", "SHF_C1_IDLE", "ART_REMAIN_MANY", "ART_REMAIN_FEW", "ART_REMAIN_NONE"],
             "askIdx")
    hint.add(ask, {"key": "askKey"})

    # ---- evidence book (ui-contracts evbook): tabs, cards, notes, details, appraisal.
    g.node("bookState", "compare", op="eq")
    g.edge("world.bookOpen", "bookState.a")
    g.edge(g.k(True), "bookState.b")
    g.edge("bookState.true", "bookNew.reset")
    g.edge("bookState.true", bookStart)
    g.edge("bookState.false", g.eff("clrNew", "atrium.coll.clear", "newCards"))
    g.counter("tab", initial=0, min=0, max=2)
    g.latch("tabPick", "ui#evbook.select_tab", "ui#evbook.select_tab.emitted")
    g.edge("tabPick", "tab.set")
    g.edge("ui#evbook.select_tab.emitted", bookStart)
    g.edge(lang, bookStart)
    g.latch("bsel", "ui#evbook.select", "ui#evbook.select.emitted")
    card_values(g, "bs", "bsel")
    g.edge("bsel", "ui#evbook.sel_id")
    g.edge(g.text("bs_name", "bs_nameKey"), "ui#evbook.sel_name")
    g.edge(g.text("bs_desc", "bs_descKey"), "ui#evbook.sel_desc")
    g.edge(tag_line(g, "bs"), "ui#evbook.sel_tags")
    g.edge("bs_grade", "ui#evbook.sel_grade")
    g.x("bs_can", "unlockedN && bs_cost > 0 && !bs_full && apprLeft >= bs_cost")
    g.edge("bs_can_t", "ui#evbook.sel_can_appraise")
    g.edge("tab", "ui#evbook.tab")
    g.edge("apprLeft", "ui#evbook.appraise_left")
    line, said = appraisal(g, "ba", "bsel", g.when("bookAppr", "ui#evbook.appraise", isInv))
    hint.add(said, {"key": line})
    g.edge(said, bookStart)
    # Cards of the current tab as "id|appraised|new" keys (flowBook): 0 case evidence (held, not story),
    # 1 golden clues, 2 private collection (held story cards).
    g.edge(bookTick, g.eff("clrBook", "atrium.coll.clear", "bookList"))
    for t, (coll, want) in enumerate((("held", "!bi0_story"), ("golden", "1"), ("held", "bi2_story"))):
        pre = f"bi{t}"
        g.node(pre + "Each", "atrium.coll.forEach", name=coll)
        g.x(pre + "TabN", f"tab == {t}")
        g.edge(g.when(pre + "Tab", bookTick, pre + "TabN_t"), pre + "Each.trigger")
        item = g.put(pre, pre + "Each.item")
        card_values(g, pre, item)
        g.n(pre + "_new", g.contains(pre + "_newC", "newCards", item))
        key = g.fmt(pre + "_key", "{a}|{b}|{c}", item, pre + "_full", pre + "_new")
        g.x(pre + "_n", want)
        g.edge(g.when(pre + "_g", pre + "Each.each", pre + "_n_t"),
               g.eff(pre + "_add", "atrium.coll.add", "bookList", value=key))
    g.edge(bookTick, g.ui_list("cardsList", "ui.evbook.cards", "bookList",
                               {"id": "id", "name": "nameKey", "grade": "grade", "appraised": "appraised",
                                "isnew": "isnew"}, join={"table": "flowBook", "column": "key"}, localize=["name"]))
    g.edge(bookTick, g.ui_list("notesList", "ui.evbook.notes", "notes", {"text": "item"}, localize=["text"]))

    # ---- ports
    g.sel("ticksPort", "lim_t", "ticks", g.k(0))
    g.edge("ticksPort", "ui#investigate.ticks")
    g.sel("ticksMax", "lim_t", "ticksInit", g.k(0))
    g.edge("ticksMax", "ui#investigate.ticks_max")
    g.sel("apprPort", g.b("unlockedB", "unlockedN"), "apprLeft", g.k(-1))
    g.edge("apprPort", "ui#investigate.appraise_left")
    g.sel("trustPort", g.b("trustShownB", "trustShownN"), "trust", g.k(-1))
    g.edge("trustPort", "ui#investigate.trust")
    g.edge(bookNew, "ui#investigate.book_new")
    g.edge("canEndN_t", "ui#investigate.can_end")
    g.edge(g.text("hintText", hint.out("key", g.k(""))), "ui#investigate.hint")
    g.edge(hint.seq, "ui#investigate.hint_seq")
    g.sel("popKind", popOpen, popup.out("kind", g.k(0)), g.k(0))
    g.edge("popKind", "ui#investigate.popup_kind")
    g.edge(g.text("popTitle", popup.out("title", g.k(""))), "ui#investigate.popup_title")
    g.edge(g.text("popBody", popup.out("body", g.k(""))), "ui#investigate.popup_body")
    g.edge(popup.out("grade", g.k(0)), "ui#investigate.popup_grade")
    g.edge(popup.seq, "ui#investigate.popup_seq")
    return g


# ---------------------------------------------------------------- board

def gen_board() -> Graph:
    """board steps (01-systems §2; ui-contracts board): drawer, 3 chains x 5 slots, reasons, link judgement,
    chain plates, appraisal, the checks before the debate and the debate engine's board input."""
    g = Graph()
    chapter_values(g)
    lang = lang_changed(g)
    mt = max_tags()
    isBoard = g.cmp("isBoard", "world.stepKind", g.k("board"))
    begin = g.when("beginGate", "world.stepBegin", isBoard)
    # Flags that gate the pulses that set them live in the map boardState (a node feeding back into the gate of
    # its own setter would be a cycle); written now, read from the next tick. 0 after the step begins.
    flags = ("locked", "armed", "bouncing", "placeMode", "solidSaid", "invalidSaid")
    for t in flags:
        g.mget(t + "N", "boardState", g.k(t))
    g.toggle("selOn")
    g.counter("sophN", initial=0)
    g.counter("unappr", initial=0)
    g.counter("looseN", initial=0)
    remark = Mux(g, "remark", ["key"])
    initStart, initTick = g.timer("initTimer")
    refStart, refTick = g.timer("refreshTimer")
    # The invalid link stays on the board for a moment before the card goes back (§2.6: spark, then bounce).
    bounceStart, bounceTick = g.timer("bounceTimer", 0.35)
    list2Start, list2Tick = g.timer("list2Timer")   # lists again after a bounce or a closed gap
    g.put("X", "X.out")           # the last placed card (latched by `place`, below)

    # ---- begin: empty board; the drawer (boardCards) next tick: the chapter's board cards that are held or golden.
    for coll in ("row0", "row1", "row2", "reason", "boardCards", "caseCards", "slotList", "linkMap", "chainMap",
                 "drawerList"):
        typ = "atrium.map.clear" if COLLECTIONS[coll]["kind"] == "map" else "atrium.coll.clear"
        g.node(f"clr_{coll}", typ, name=coll)
        g.edge(begin, f"clr_{coll}.trigger")
    g.edge(begin, g.eff("addCase", "atrium.coll.addAll", "caseCards", text="caseCardsText"))
    g.edge(begin, g.eff("clr_boardState", "atrium.map.clear", "boardState"))
    g.edge(begin, "selOn.setFalse")
    g.edge(begin, "sophN.reset")
    remark.add(begin, {"key": g.k("")})
    g.edge(begin, initStart)
    g.node("cardEach", "atrium.coll.forEach", name="caseCards")
    g.edge(initTick, "cardEach.trigger")
    g.n("ce_held", g.contains("ce_heldC", "held", "cardEach.item"))
    g.n("ce_gold", g.contains("ce_goldC", "golden", "cardEach.item"))
    g.x("ce_n", "ce_held || ce_gold")
    g.edge(g.when("ce_g", "cardEach.each", "ce_n_t"),
           g.eff("ce_add", "atrium.coll.add", "boardCards", value="cardEach.item"))
    refresh = g.merge("refresh", initTick, refTick)

    # ---- the 15 slots: row r = list row<r> (cards are always packed from pos 0), slot s = 5r + i.
    for s in range(SLOTS):
        r, i = divmod(s, 5)
        g.cget(f"id{s}", f"row{r}", g.k(i))
        g.n(f"v{s}", f"id{s}_ok")
        card_values(g, f"s{s}", f"id{s}")
        reason_values(g, f"s{s}", f"id{s}")
        g.x(f"noR{s}", f"v{s} && !s{s}_rset")
    # Links between slot s and s+1 (ruling C4, ref rules.link_kind): a revealed tag of the left card that the right
    # card has and reveals is shared; solid = a shared tag neither card marks grazing and both reasons correct and no
    # substitute; sophistry = shared otherwise; invalid (3) = nothing shared; 4 = solid with a golden clue.
    links = [s for s in range(SLOTS) if s % 5 < 4]
    for s in links:
        a, bb = f"s{s}", f"s{s + 1}"
        terms_sh, terms_fm = [], []
        for t in range(mt):
            tag = g.tget(f"L{s}_t{t}", "flowCard", f"tag{t}", a + "_row")
            g.n(f"L{s}_in{t}", g.thas(f"L{s}_inC{t}", "flowCard", "tags", bb + "_row", tag))
            g.n(f"L{s}_hb{t}", g.thas(f"L{s}_hbC{t}", "flowCard", "hiddenTags", bb + "_row", tag))
            g.n(f"L{s}_ha{t}", g.thas(f"L{s}_haC{t}", "flowCard", "hiddenTags", a + "_row", tag))
            g.n(f"L{s}_ga{t}", g.thas(f"L{s}_gaC{t}", "flowCard", "grazingTags", a + "_row", tag))
            g.n(f"L{s}_gb{t}", g.thas(f"L{s}_gbC{t}", "flowCard", "grazingTags", bb + "_row", tag))
            g.x(f"L{s}_sh{t}", f"L{s}_in{t} && (!L{s}_ha{t} || {a}_full) && (!L{s}_hb{t} || {bb}_full)")
            g.x(f"L{s}_fm{t}", f"L{s}_sh{t} && !L{s}_ga{t} && !L{s}_gb{t}")
            terms_sh.append(f"L{s}_sh{t}")
            terms_fm.append(f"L{s}_fm{t}")
        g.x(f"L{s}_shared", " + ".join(terms_sh))
        g.x(f"L{s}_firm", " + ".join(terms_fm))
        g.x(f"k{s}", f"!(v{s} && v{s + 1}) ? 0 : L{s}_shared == 0 ? 3 : "
                     f"(L{s}_firm > 0 && {a}_ok && {bb}_ok && !{a}_sub && !{bb}_sub) ? "
                     f"(({a}_goldenCard || {bb}_goldenCard) ? 4 : 1) : 2")
        g.x(f"dl{s}", f"(k{s} == 1 || k{s} == 4) ? 1 : k{s} == 2 ? 2 : 0")   # debBoardLink value
    for r in range(3):
        sl = [s for s in links if s // 5 == r]
        g.x(f"cnt{r}", " + ".join(f"v{s}" for s in range(5 * r, 5 * r + 5)))
        g.x(f"solid{r}", " + ".join(f"(k{s} == 1 || k{s} == 4)" for s in sl))
        g.x(f"soph{r}", " + ".join(f"(k{s} == 2)" for s in sl))
        # 01-systems §2.5: 14 x (1 + 0.5 solid + 0.8 sophistry), written like ref rules.chain_damage_breakdown.
        g.x(f"dmg{r}", f"cnt{r} >= 2 ? 14 * (10 + 5 * solid{r} + 8 * soph{r}) / 10 : 0")
    g.x("chains", "(cnt0 >= 2) + (cnt1 >= 2) + (cnt2 >= 2)")
    g.x("noReason", " + ".join(f"noR{s}" for s in range(SLOTS)))
    first_inv = "99"
    for s in reversed(links):
        first_inv = f"(k{s} == 3 ? {s} : {first_inv})"
    g.x("firstInv", first_inv)
    g.x("anyInv", "firstInv < 99")

    # The last placed card X: its slot and the links next to it (for the remark and the bounce).
    for r in range(3):
        g.index_of(f"xi{r}", f"row{r}", "X")
    g.x("xs", "xi0 >= 0 ? xi0 : xi1 >= 0 ? 5 + xi1 : xi2 >= 0 ? 10 + xi2 : -1")
    for s in links:
        g.x(f"adj{s}", f"xs >= 0 && (xs == {s} || xs == {s} + 1)")
    g.x("xInv", " + ".join(f"adj{s} * (k{s} == 3)" for s in links))
    g.x("xSoph", " + ".join(f"adj{s} * (k{s} == 2)" for s in links))
    g.x("xSolid", " + ".join(f"adj{s} * (k{s} == 1 || k{s} == 4)" for s in links))
    g.x("xSub", " + ".join(f"adj{s} * (k{s} == 1 || k{s} == 2 || k{s} == 4) * (s{s}_sub || s{s + 1}_sub)"
                           for s in links))

    # ---- refresh (one tick after a change, so every query above has been re-evaluated): bounce an invalid
    # placement, close an invalid gap left by an unplace, the remark, then the four lists.
    g.x("refIdx", "placeModeN && xInv ? 1 : anyInv ? 2 : placeModeN ? 3 : 0")
    g.latch("refDec", "refIdx", refresh)
    ref = g.merge("refM", refresh)
    g.x("bounceN", "refDec == 1")
    bounce = g.when("bounceG", ref, "bounceN_t")
    g.latch("bounceX", "X", bounce)
    g.edge(bounce, g.eff("bs1_bouncing", "atrium.map.set", "boardState", key=g.k("bouncing"), value=g.k(1)))
    g.edge(bounce, bounceStart)
    g.x("invSayN", "!invalidSaidN")
    remark.add(g.when("invRemark", bounce, "invSayN_t"), {"key": g.k("ART_INVALID")})
    g.edge(bounce, g.eff("bs2_invalidSaid", "atrium.map.set", "boardState", key=g.k("invalidSaid"), value=g.k(1)))
    # An unplace joined two cards that share nothing: the cards right of the gap go back to the drawer.
    g.x("tailN", "refDec == 2")
    tail = g.when("tailG", ref, "tailN_t")
    g.x("tailRow", "floor(firstInv / 5)")
    g.x("tailFrom", "firstInv - 5 * tailRow + 1")
    for r in range(3):
        for j in range(4):
            g.x(f"tl{r}_{j}", f"tailRow == {r} && {j} < cnt{r} - tailFrom")
            g.edge(g.when(f"tl{r}_{j}G", tail, f"tl{r}_{j}_t"),
                   g.eff(f"tl{r}_{j}R", "atrium.coll.removeAt", f"row{r}", index="tailFrom"))
    g.edge(tail, list2Start)
    # 01-systems §2.4: a new sophistry link -> ART_SOPH_1..4 in turn; the first solid link of the chapter ->
    # ART_SOLID; a substitute card in a new link -> ART_SUB_LINK.
    g.x("plIdx", "xSub > 0 ? 1 : xSoph > 0 ? 2 : (xSolid > 0 && !solidSaidN) ? 3 : 0")
    g.x("sophI", "sophN - 4 * floor(sophN / 4)")
    g.lookup("sophKey", ["ART_SOPH_1", "ART_SOPH_2", "ART_SOPH_3", "ART_SOPH_4"], "sophI")
    g.lookup("plKey0", ["", "ART_SUB_LINK", "", "ART_SOLID"], "plIdx")
    g.x("plSoph", "plIdx == 2")
    g.x("plSolid", "plIdx == 3")
    g.sel("plKey", "plSoph_t", "sophKey", "plKey0")
    g.x("placedN", "refDec == 3")
    placed = g.when("placedG", ref, "placedN_t")
    said = g.when("plSaid", placed, "plIdx_t")
    remark.add(said, {"key": "plKey"})
    g.edge(g.when("plSophG", said, "plSoph_t"), "sophN.increment")
    g.edge(g.when("plSolidG", said, "plSolid_t"), g.eff("bs3_solidSaid", "atrium.map.set", "boardState", key=g.k("solidSaid"), value=g.k(1)))
    g.edge(ref, g.eff("bs4_placeMode", "atrium.map.set", "boardState", key=g.k("placeMode"), value=g.k(0)))
    lists = g.merge("lists", ref, list2Tick)
    # Lists. slots: "slot|id" keys (flowSlot); links: slot -> kind (flowLink); chain plates: "chain|cards|solid|soph"
    # -> damage (flowChain, in chain order); drawer: "id|appraised|reason set|placed" keys (flowDrawer).
    g.edge(lists, g.eff("clrSlots", "atrium.coll.clear", "slotList"))
    for s in range(SLOTS):
        g.fmt(f"sk{s}", "{a}|{b}", g.k(s), f"id{s}")
        g.edge(g.when(f"sk{s}G", lists, f"id{s}_ok"), g.eff(f"sk{s}A", "atrium.coll.add", "slotList", value=f"sk{s}"))
    g.edge(lists, g.ui_list("slotsList", "ui.board.slots", "slotList",
                          {"chain": "chain", "pos": "pos", "id": "id", "name": "nameKey", "grade": "grade"},
                          join={"table": "flowSlot", "column": "key"}, localize=["name"]))
    g.edge(lists, g.eff("clrLinks", "atrium.map.clear", "linkMap"))
    for s in links:
        g.edge(g.when(f"lk{s}G", lists, f"k{s}_t"),
               g.eff(f"lk{s}S", "atrium.map.set", "linkMap", key=g.k(str(s)), value=f"k{s}"))
    g.edge(lists, g.ui_list("linksList", "ui.board.links", "linkMap", {"chain": "chain", "pos": "pos", "kind": "value"},
                          join={"table": "flowLink", "column": "key"}))
    g.edge(lists, g.eff("clrChains", "atrium.map.clear", "chainMap"))
    for r in range(3):
        g.fmt(f"ck{r}", "{a}|{b}|{c}|{d}", g.k(r), f"cnt{r}", f"solid{r}", f"soph{r}")
        g.edge(lists, g.eff(f"ck{r}S", "atrium.map.set", "chainMap", key=f"ck{r}", value=f"dmg{r}"))
    g.edge(lists, g.ui_list("chainList", "ui.board.chain_info", "chainMap",
                          {"chain": "chain", "cards": "cards", "solid": "solid", "soph": "soph", "dmg": "value"},
                          join={"table": "flowChain", "column": "key"}))
    g.edge(lists, g.eff("clrDrawer", "atrium.coll.clear", "drawerList"))
    g.edge(lists, "unappr.reset")
    g.node("drawEach", "atrium.coll.forEach", name="boardCards")
    g.edge(lists, "drawEach.trigger")
    di = g.put("di", "drawEach.item")
    card_values(g, "di", di)
    reason_values(g, "di", di)
    for r in range(3):
        g.n(f"di_in{r}", g.contains(f"di_inC{r}", f"row{r}", di))
    g.x("di_placed", "di_in0 || di_in1 || di_in2")
    g.fmt("di_key", "{a}|{b}|{c}|{d}", di, "di_full", "di_rset", "di_placed")
    g.edge("drawEach.each", g.eff("di_add", "atrium.coll.add", "drawerList", value="di_key"))
    g.x("di_unN", "unlockedN && di_cost > 0 && !di_full")
    g.edge(g.when("di_unG", "drawEach.each", "di_unN_t"), "unappr.increment")
    g.edge(lists, g.ui_list("drawerUi", "ui.board.drawer", "drawerList",
                          {"id": "id", "name": "nameKey", "grade": "grade", "appraised": "appraised",
                           "reason_set": "reason_set", "placed": "placed"},
                          join={"table": "flowDrawer", "column": "key"}, localize=["name"]))
    g.edge(lang, refStart)
    # The invalid card leaves the board after the spark, then the board refreshes.
    for r in range(3):
        g.edge(g.when(f"bx{r}G", bounceTick, g.contains(f"bx{r}C", f"row{r}", "bounceX")),
               g.eff(f"bx{r}R", "atrium.coll.remove", f"row{r}", value="bounceX"))
    g.edge(bounceTick, g.eff("bs5_bouncing", "atrium.map.set", "boardState", key=g.k("bouncing"), value=g.k(0)))
    g.edge(bounceTick, list2Start)

    # ---- input (only during the board step, before the lock, not while a card bounces)
    g.x("activeN", "!lockedN && !bouncingN")
    g.latch("selL", "ui#board.select", "ui#board.select.emitted")
    g.edge(g.when("selG", g.when("selInv", "ui#board.select.emitted", isBoard), "activeN_t"), "selOn.setTrue")
    g.sel("sel", "selOn.value", "selL", g.k(""))
    card_values(g, "sc", "sel")
    reason_values(g, "sc", "sel")
    g.n("sc_has", g.cmp("sc_hasC", "sel", g.k(""), "ne"))

    # place (value = chain x 5 + pos): the card goes to that chain at pos or, when the chain is shorter, at its end
    # (chains stay packed from pos 0; coll.insert clamps the index), out of its old chain; a card already in that
    # chain or a full chain (MSG_CHAIN_MAX) does not move. The links are judged on the refresh.
    g.put("pv", "ui#board.place")
    g.x("pr", "floor(pv / 5)")
    g.x("pp", "pv - 5 * pr")
    for r in range(3):
        g.n(f"in{r}", g.contains(f"inC{r}", f"row{r}", "sel"))
    g.x("selRow", "in0 ? 0 : in1 ? 1 : in2 ? 2 : -1")
    g.x("prCnt", "pr == 0 ? cnt0 : pr == 1 ? cnt1 : cnt2")
    g.x("plDec", "!sc_has ? 0 : selRow == pr ? 0 : prCnt >= 5 ? 1 : 2")
    pin = g.when("placeAct", g.when("placeInv", "ui#board.place.emitted", isBoard), "activeN_t")
    g.latch("plD", "plDec", pin)
    pl = g.merge("plM", pin)
    g.x("fullN", "plD == 1")
    remark.add(g.when("fullG", pl, "fullN_t"), {"key": g.k("MSG_CHAIN_MAX")})
    g.x("placeGoN", "plD == 2")
    go = g.when("placeGoG", pl, "placeGoN_t")
    g.latch("X", "sel", go)
    for r in range(3):
        g.x(f"mv{r}N", f"selRow == {r}")
        g.edge(g.when(f"mv{r}G", go, f"mv{r}N_t"), g.eff(f"mv{r}R", "atrium.coll.remove", f"row{r}", value="sel"))
    for r in range(3):
        g.x(f"ins{r}N", f"pr == {r}")
        g.edge(g.when(f"ins{r}G", go, f"ins{r}N_t"),
               g.eff(f"ins{r}I", "atrium.coll.insert", f"row{r}", value="sel", index="pp"))
    g.edge(go, g.eff("bs6_placeMode", "atrium.map.set", "boardState", key=g.k("placeMode"), value=g.k(1)))
    g.edge(go, g.eff("bs7_armed", "atrium.map.set", "boardState", key=g.k("armed"), value=g.k(0)))
    g.edge(go, refStart)

    # unplace (id): back to the drawer; the chain closes up (an invalid join is handled by the refresh).
    up = g.when("unAct", g.when("unInv", "ui#board.unplace.emitted", isBoard), "activeN_t")
    g.latch("U", "ui#board.unplace", up)
    um = g.merge("unM", up)
    for r in range(3):
        g.edge(g.when(f"un{r}G", um, g.contains(f"unC{r}", f"row{r}", "U")),
               g.eff(f"un{r}R", "atrium.coll.remove", f"row{r}", value="U"))
    g.edge(um, g.eff("bs8_placeMode", "atrium.map.set", "boardState", key=g.k("placeMode"), value=g.k(0)))
    g.edge(um, g.eff("bs9_armed", "atrium.map.set", "boardState", key=g.k("armed"), value=g.k(0)))
    g.edge(um, refStart)

    # reason 1..3 for the selected card (not for golden / substitute cards: fixed, §2.3).
    g.put("rv", "ui#board.reason")
    g.x("rsOkN", "activeN && sc_has && !sc_fixed")
    rs = g.when("rsAct", g.when("rsInv", "ui#board.reason.emitted", isBoard), "rsOkN_t")
    g.edge(rs, g.eff("rsSet", "atrium.map.set", "reason", key="sel", value="rv"))
    g.edge(rs, g.eff("bs10_armed", "atrium.map.set", "boardState", key=g.k("armed"), value=g.k(0)))
    g.edge(rs, refStart)

    # appraisal from the detail panel (same rule as the evidence book).
    line, said_a = appraisal(g, "ap", "sel", g.when("apAct", g.when("apInv", "ui#board.appraise", isBoard),
                                                    "activeN_t"))
    remark.add(said_a, {"key": line})
    g.edge(said_a, refStart)

    # ---- to the debate (§2.7): no chain -> MSG_BOARD_NOCHAIN; unchosen reasons (placed cards) or cards still to
    # appraise with charges left -> the warning as a remark, a second press goes on; then lock.
    g.x("tdIdx", "chains == 0 ? 1 : (!armedN && (noReason > 0 || (unappr > 0 && apprLeft > 0))) ? 2 : 3")
    td = g.when("tdAct", g.when("tdInv", "ui#board.to_debate", isBoard), "activeN_t")
    g.latch("tdD", "tdIdx", td)
    tdm = g.merge("tdM", td)
    g.x("noChainN", "tdD == 1")
    remark.add(g.when("noChainG", tdm, "noChainN_t"), {"key": g.k("MSG_BOARD_NOCHAIN")})
    g.x("warnN", "tdD == 2")
    warn = g.when("warnG", tdm, "warnN_t")
    g.sel("warnKey", "noReason_t", g.k("WARN_BOARD_NOREASON"), g.k("WARN_BOARD_UNAPPR"))
    remark.add(warn, {"key": "warnKey"})
    g.edge(warn, g.eff("bs11_armed", "atrium.map.set", "boardState", key=g.k("armed"), value=g.k(1)))
    g.x("commitN", "tdD == 3")
    commit = g.when("commitG", tdm, "commitN_t")
    # debBoard / debBoardOk / debBoardLink (docs/debate-engine.md §2.2): chain c card i at 5c + i ("-" empty, ok 1,
    # link 0), then the drawer cards that are not on the board from 15 in drawer order, "-" up to 24.
    for coll in ("debBoard", "debBoardOk", "debBoardLink"):
        g.edge(commit, g.eff(f"cm_clr_{coll}", "atrium.coll.clear", coll))
    for s in range(SLOTS):
        g.sel(f"cmId{s}", f"id{s}_ok", f"id{s}", g.k("-"))
        g.x(f"cmOk{s}", f"v{s} ? s{s}_ok : 1")
        g.edge(commit, g.eff(f"cmB{s}", "atrium.coll.add", "debBoard", value=f"cmId{s}"))
        g.edge(commit, g.eff(f"cmO{s}", "atrium.coll.add", "debBoardOk", value=f"cmOk{s}"))
        g.edge(commit, g.eff(f"cmL{s}", "atrium.coll.add", "debBoardLink",
                             value=f"dl{s}" if s % 5 < 4 else g.k(0)))
    g.edge(commit, "looseN.reset")
    g.node("looseEach", "atrium.coll.forEach", name="boardCards")
    g.edge(commit, "looseEach.trigger")
    li = g.put("li", "looseEach.item")
    card_values(g, "li", li)
    reason_values(g, "li", li)
    for r in range(3):
        g.n(f"li_in{r}", g.contains(f"li_inC{r}", f"row{r}", li))
    g.x("li_n", "!(li_in0 || li_in1 || li_in2)")
    loose = g.when("li_g", "looseEach.each", "li_n_t")
    g.edge(loose, g.eff("li_B", "atrium.coll.add", "debBoard", value=li))
    g.edge(loose, g.eff("li_O", "atrium.coll.add", "debBoardOk", value="li_ok"))
    g.edge(loose, g.eff("li_L", "atrium.coll.add", "debBoardLink", value=g.k(0)))
    g.edge(loose, "looseN.increment")
    pads = g.merge("padM", commit)
    for j in range(LOOSE):
        g.x(f"pad{j}N", f"looseN <= {j}")
        pad = g.when(f"pad{j}G", pads, f"pad{j}N_t")
        g.edge(pad, g.eff(f"pad{j}B", "atrium.coll.add", "debBoard", value=g.k("-")))
        g.edge(pad, g.eff(f"pad{j}O", "atrium.coll.add", "debBoardOk", value=g.k(1)))
        g.edge(pad, g.eff(f"pad{j}L", "atrium.coll.add", "debBoardLink", value=g.k(0)))
    # Golden clues (§2.3): a card with evidence.golden and the correct reason at the lock gives its clue silently;
    # otherwise the clue is taken away (the latest playthrough of the chapter counts).
    g.node("goldEach", "atrium.coll.forEach", name="caseCards")
    g.edge(pads, "goldEach.trigger")
    gi = g.put("gi", "goldEach.item")
    card_values(g, "gi", gi)
    reason_values(g, "gi", gi)
    g.n("gi_on", g.contains("gi_onC", "boardCards", gi))
    g.n("gi_hasG", g.cmp("gi_hasGC", "gi_golden", g.k(""), "ne"))
    g.x("gi_addN", "gi_hasG && gi_on && gi_ok")
    g.x("gi_remN", "gi_hasG && !(gi_on && gi_ok)")
    g.edge(g.when("gi_addG", "goldEach.each", "gi_addN_t"), g.eff("gi_add", "atrium.coll.add", "golden",
                                                                  value="gi_golden"))
    g.edge(g.when("gi_remG", "goldEach.each", "gi_remN_t"), g.eff("gi_rem", "atrium.coll.remove", "golden",
                                                                  value="gi_golden"))
    g.edge(pads, g.eff("bs12_locked", "atrium.map.set", "boardState", key=g.k("locked"), value=g.k(1)))
    g.edge(g.merge("commitDone", pads), "world.stepDone")

    # ---- ports
    g.edge("sel", "ui#board.sel_id")
    g.edge(g.text("sc_name", "sc_nameKey"), "ui#board.sel_name")
    g.edge(g.text("sc_desc", "sc_descKey"), "ui#board.sel_desc")
    g.edge(tag_line(g, "sc"), "ui#board.sel_tags")
    g.edge("sc_grade", "ui#board.sel_grade")
    for i in (1, 2, 3):
        g.edge(g.text(f"sc_r{i}", f"sc_reason{i}"), f"ui#board.sel_reason{i}")
    g.edge("sc_rsn", "ui#board.sel_reason")
    g.edge(g.b("sc_fixedB", "sc_fixed"), "ui#board.sel_fixed")
    g.x("sc_can", "activeN && unlockedN && sc_cost > 0 && !sc_full && apprLeft >= sc_cost")
    g.edge("sc_can_t", "ui#board.sel_can_appraise")
    g.edge("apprLeft", "ui#board.appraise_left")
    g.tget("oppSpk", "opponents", "speaker", g.tfind("oppRow", "opponents", "id", "oppId"))
    g.edge(g.text("oppName", "oppSpk"), "ui#board.opponent_name")
    g.sel("condKey0", g.cmp("phaseMid", "phase", g.k("mid")), g.k("UI_BOARD_COND_MID"), g.k("UI_BOARD_COND_EARLY"))
    g.sel("condKey", g.cmp("phaseLate", "phase", g.k("late")), g.k("UI_BOARD_COND_LATE"), "condKey0")
    g.edge(g.text("condText", "condKey"), "ui#board.threshold_text")
    g.edge(g.text("remarkText", remark.out("key", g.k(""))), "ui#board.remark")
    g.edge(remark.seq, "ui#board.remark_seq")
    return g


# ---------------------------------------------------------------- stubs

STUB_KINDS = ["warmup", "debate", "result"]


def gen_stubs() -> Graph:
    """Step kinds without a flow yet report done at once. The debate stub records a win (world.caseOutcome), so the
    papers and results downstream have an outcome. E02_08 (ruling F3, auto-granted when the Ch.2 debate ends) is
    for the debate pass (M4c)."""
    g = Graph()
    g.node("done", "merge")
    g.edge("done.out", "world.stepDone")
    for k in STUB_KINDS:
        g.const(k + "Tag", k)
        g.node(k + "Is", "compare", op="eq")
        g.gate(k + "Gate")
        g.edge("world.stepKind", k + "Is.a")
        g.edge(k + "Tag.out", k + "Is.b")
        g.edge(k + "Is.out", k + "Gate.guard")
        g.edge("world.stepBegin", k + "Gate.go")
        if k == "debate":
            g.const("win", "win")
            g.node("outcome", "filter", op="sample")
            g.edge("win.out", "outcome.in")
            g.edge(k + "Gate.changed", "outcome.trigger")
            g.edge("outcome.out", "world.caseOutcome")
        g.edge(k + "Gate.changed", "done.in")
    return g


GRAPHS = {"main": gen_main, "dialogue": gen_dialogue, "paper": gen_paper, "investigate": gen_investigate,
          "board": gen_board, "stubs": gen_stubs}


def outputs() -> dict[Path, str]:
    out = {FLOWS / f"{name}.xtflow": fn().text_out() for name, fn in GRAPHS.items()}
    tables = flow_tables()
    for name, rows in tables.items():
        out[FLOW_DATA / f"{name}.json"] = table_text(rows)
    out[GAME_JSON] = game_json_text(tables)
    return out


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
    if "--stats" in sys.argv[1:]:
        for name, fn in GRAPHS.items():
            n, e = fn().stats()
            print(f"{name}: {n} nodes, {e} edges")
    if stale:
        print("stale: " + ", ".join(stale) + " (run uv run tools/gen_flows.py)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
