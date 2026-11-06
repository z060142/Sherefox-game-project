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

    def textf(self, node_id: str, /, key: str | None = None, pattern: str | None = None, **args: str) -> str:
        """atrium.textf (08 §8.1.4): the localized template `key` (or the template text on port `pattern`) with its
        {name} placeholders filled from the keyword ports (placeholder name = keyword); returns the text port."""
        params: dict = {}
        if key:
            params["key"] = key
        params["args"] = list(args)
        self.node(node_id, "atrium.textf", **params)
        if pattern is not None:
            self.edge(pattern, f"{node_id}.pattern")
        for arg, src in args.items():
            self.edge(src, f"{node_id}.{arg}")
        return self.put(node_id, f"{node_id}.text")

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

    def ui_list(self, name: str, port: str, source: str, fields: dict, localize: list | None = None,
                bare: bool = False) -> str:
        """atrium.ui.list (08 §8.4): `fields` maps a struct field to a source column of the collection (item / index;
        key / value / index) or a reference keyed by the row key (tref(), "coll:<n>.contains", "map:<n>"). `bare`:
        one field, written as a value array for a list<bool|number|string> port (AT-047)."""
        params = {"port": port, "source": source, "fields": json.dumps(fields, ensure_ascii=False)}
        if localize:
            params["localize"] = localize
        if bare:
            params["bare"] = True
        self.node(name, "atrium.ui.list", **params)
        return f"{name}.trigger"

    def text_out(self) -> str:
        return json.dumps({"version": 1, "nodes": self.nodes + self.late, "edges": self.edges},
                          ensure_ascii=False, indent=2) + "\n"

    def stats(self) -> tuple[int, int]:
        return len(self.nodes) + len(self.late), len(self.edges)


def tref(table: str, key_col: str, col: str) -> str:
    """A ui.list field reference: column `col` of the first row of `table` whose `key_col` is the row key."""
    return f"table:{table}[{key_col}].{col}"


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

# ui-contracts: popup_grade, sel_grade (observation: the warm-up's cards, ruling G5; never on those screens)
GRADE = {"common": 0, "key": 1, "story": 2, "golden": 3, "substitute": 4, "observation": 5}
SPOT_TYPE = {"inspect": 0, "evidence": 1, "testimony": 2}                   # ui-contracts investigate: spots.type
APPRAISE = {"none": 0, "medical": 1, "mechanical": 2, "dual": 3}
# data-schema §5: hotspots.scene -> the vn background id of that scene (script.bg).
SCENE_BG = {"kitchen": "kitchen_morning", "clock_shop": "clockshop", "boiler_room": "boiler_room",
            "deck": "barge_deck", "dock": "dock_fog"}
# 10-cases 場景與登場人物 -> the scene's name key (investigate.area_name; SCENE_CH0x_*)
SCENE_NAME = {(1, "kitchen"): "SCENE_CH01_KITCHEN", (2, "clock_shop"): "SCENE_CH02_CLOCKSHOP",
              (3, "boiler_room"): "SCENE_CH03_BOILER", (3, "deck"): "SCENE_CH03_DECK", (3, "dock"): "SCENE_CH03_DOCK"}
SLOTS = 15          # board: 3 chains x 5 slots (ui-contracts board)
LOOSE = 9           # debBoard slots 15..23 (docs/debate-engine.md §2.2)


def max_tags() -> int:
    return max(len(split(e["tags"])) for e in load("evidence"))


def case_cards(chapter: int) -> list[dict]:
    """The cards of a chapter's board, in evidence-table order: usable in the chapter and on the board."""
    return [e for e in load("evidence") if str(chapter) in split(e["usable"]) and e["onBoard"]]


def string_keys() -> set[str]:
    import csv
    with (ROOT / "strings" / "zh-TW.csv").open(encoding="utf-8", newline="") as f:
        return {r["key"] for r in csv.DictReader(f)}


def spot_lines(h: dict, script: dict) -> list[tuple[str, str]]:
    """A hotspot's reaction lines (hotspots.lines): (text key, speaker key) of its playable script lines, in order.
    The evidence description rows are the popup body already; appraisal lines belong to the appraisal (they read
    the hidden tags). Narration (focus 0) has no name plate, as on the vn."""
    out = []
    for lid in split(h["lines"]):
        r = script[lid]
        if r["kind"] == "line" and r["playable"] and not r["appraisal"]:
            out.append((r["text"], r["speaker"] if r["focus"] else ""))
    return out


def max_spot_lines() -> int:
    script = {r["id"]: r for r in load("script")}
    return max(len(spot_lines(h, script)) for h in load("hotspots"))


def flow_tables() -> dict[str, list[dict]]:
    ev = load("evidence")
    hs = load("hotspots")
    script = {r["id"]: r for r in load("script")}
    keys = string_keys()
    ml = max_spot_lines()
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
               "tags": e["tags"], "hiddenTags": e["hiddenTags"], "grazingTags": e["grazingTags"],
               "apprLine": e["appraisalKey"]}
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
            # the note when the police report has been handed over (trust >= 3, ruling F6): <noteKey>_REPORT
            report = h["noteKey"] + "_REPORT" if h["noteKey"] and h["noteKey"] + "_REPORT" in keys else ""
            lines = spot_lines(h, script)
            row = {"id": h["id"], "nameKey": h["nameKey"], "noteKey": h["noteKey"], "reportNote": report,
                   "x": h["x"], "y": h["y"], "w": h["w"], "h": h["h"], "type": SPOT_TYPE[h["type"]],
                   "yield": ys[0] if ys else "", "reqMissing": req[len("missing:"):] if req else "",
                   "nLines": len(lines)}
            for i in range(ml):
                row[f"line{i}"], row[f"spk{i}"] = lines[i] if i < len(lines) else ("", "")
            spot.append(row)
            if h["scene"] not in scenes:
                scenes.append(h["scene"])
        for i, s in enumerate(scenes):
            name = SCENE_NAME.get((c, s), "")
            if name not in keys:
                raise ValueError(f"Ch.{c} scene {s}: no name key ({name or 'SCENE_NAME'})")
            scene.append({"key": f"{c}:{i}", "chapter": c, "idx": i, "bg": SCENE_BG[s], "nameKey": name,
                          "spots": ",".join(h["id"] for h in rows if h["scene"] == s)})
        cards = case_cards(c)
        # A substitute only appears when its golden clue is missing (01-systems §1.9), so they never both count.
        if len(cards) - min(sum(e["grade"] == "golden" for e in cards), sum(e["grade"] == "substitute" for e in cards)) > LOOSE:
            raise ValueError(f"Ch.{c}: {len(cards)} board cards, debBoard has {LOOSE} loose slots")
        case.append({"id": c, "scenes": len(scenes), "spots": ",".join(h["id"] for h in rows),
                     "eventCards": ",".join(e["id"] for e in ev if e["chapter"] == c and e["obtain"] == "event"),
                     "policeCards": ",".join(e["id"] for e in ev if e["chapter"] == c and e["policeTags"]),
                     "cards": ",".join(e["id"] for e in cards)})

    # board.links: a link slot -> its chain and position (the list's row key is the slot)
    link = [{"key": str(s), "chain": s // 5, "pos": s % 5} for s in range(SLOTS) if s % 5 < 4]
    return {"flowCard": card, "flowSpot": spot, "flowScene": scene, "flowCase": case, "flowLink": link}


def table_text(rows: list[dict]) -> str:
    return "[\n" + ",\n".join("  " + json.dumps(r, ensure_ascii=False) for r in rows) + "\n]\n"


# ---------------------------------------------------------------- game.json entries owned by the flows

SIGNALS = {
    "trust": {"type": "number", "initial": 3},          # 01-systems §3.1: permanent trust, starts at 3
    "bookOpen": {"type": "bool", "initial": False},     # main: the evidence book overlay is open
    "caseOutcome": {"type": "string", "initial": ""},   # result: win / notorious / lose (the paper's sidebar)
    # debate / warmup steps (docs/flows.md §4.2): the lines around the debate screen (script.cue)
    "debGo": {"type": "pulse"},                         # dialogue -> main, debate_ui: the pre lines are over
    "debEnd": {"type": "pulse"},                        # debate_ui -> dialogue: the debate is over
    "debCue": {"type": "string", "initial": "post"},    # debate_ui: the cue of the lines after it (post / postWin / postLose)
    "vnShow": {"type": "pulse"},                        # dialogue -> main: lines after the debate, show the vn
    # ruling G5: a warm-up retort on the vn in the middle of the warm-up (script.cue wrong:<card>)
    "debAside": {"type": "pulse"},                      # debate_ui -> dialogue: play the lines of debAsideCue now
    "debAsideCue": {"type": "string", "initial": ""},   # debate_ui: their cue
    "debBack": {"type": "pulse"},                       # dialogue -> main, debate_ui: they are over, back to the debate
    "debRetrying": {"type": "bool", "initial": False},  # main: the debate step was entered by a retry (no pre lines)
    "notesOpen": {"type": "pulse"},                     # debate_ui -> main: show the opponent notes overlay
    "notesShown": {"type": "bool", "initial": False},   # main: the opponent notes overlay is open
    "settingsShown": {"type": "bool", "initial": False},  # main: the settings overlay is open (the debate pauses)
    # music hooks (rulings H1-H3; no playback yet): the moment and its BGM id (docs/flows.md §4.10)
    "bgmMoment": {"type": "string", "initial": "title"},
    "bgm": {"type": "string", "initial": "BGM01"},
    # settings (ui-contracts settings; 01-systems §4.6, §4.7 在地化): 大字譯名, on by default (shown only outside zh-TW)
    "cutinSub": {"type": "bool", "initial": True},
}
COLLECTIONS = {
    # case state (investigation -> board -> debate)
    "held": {"kind": "list", "type": "string", "capacity": 32, "unique": True},
    "appraised": {"kind": "list", "type": "string", "capacity": 32, "unique": True},
    "golden": {"kind": "list", "type": "string", "capacity": 8, "unique": True},
    "oppHand": {"kind": "list", "type": "string", "capacity": 16, "unique": True},
    "caseNum": {"kind": "map", "type": "number", "capacity": 8},
    "invState": {"kind": "map", "type": "number", "capacity": 8},
    "invStr": {"kind": "map", "type": "string", "capacity": 2},     # investigate: the popup's spot
    "boardState": {"kind": "map", "type": "number", "capacity": 16},
    # investigation
    "spotSeen": {"kind": "map", "type": "number", "capacity": 64},
    "spotsHere": {"kind": "map", "type": "number", "capacity": 16},
    "toFind": {"kind": "list", "type": "string", "capacity": 32, "unique": True},
    "needed": {"kind": "list", "type": "string", "capacity": 8, "unique": True},
    "notes": {"kind": "list", "type": "string", "capacity": 32, "unique": True},
    "newCards": {"kind": "list", "type": "string", "capacity": 32, "unique": True},
    "caseSpots": {"kind": "list", "type": "string", "capacity": 64},
    "visSpots": {"kind": "list", "type": "string", "capacity": 64},  # the case's spots shown (conditions met)
    "sceneSpots": {"kind": "list", "type": "string", "capacity": 16},
    "bookList": {"kind": "map", "type": "bool", "capacity": 32},      # evbook.cards: id -> revealed
    # board
    "row0": {"kind": "list", "type": "string", "capacity": 5, "unique": True},
    "row1": {"kind": "list", "type": "string", "capacity": 5, "unique": True},
    "row2": {"kind": "list", "type": "string", "capacity": 5, "unique": True},
    "reason": {"kind": "map", "type": "number", "capacity": 32},
    "caseCards": {"kind": "list", "type": "string", "capacity": 16, "unique": True},
    "boardCards": {"kind": "list", "type": "string", "capacity": 16, "unique": True},
    # the list ports' sources (§5.2): board.slots, board.links, board.chain_info, board.drawer
    "slotList": {"kind": "map", "type": "number", "capacity": SLOTS},    # card -> chain
    "slotPos": {"kind": "map", "type": "number", "capacity": SLOTS},     # card -> pos
    "linkMap": {"kind": "map", "type": "number", "capacity": 16},        # slot -> link kind
    "chainMap": {"kind": "map", "type": "number", "capacity": 3},        # chain -> damage
    "chainCards": {"kind": "map", "type": "number", "capacity": 3},
    "chainSolid": {"kind": "map", "type": "number", "capacity": 3},
    "chainSoph": {"kind": "map", "type": "number", "capacity": 3},
    "drawerList": {"kind": "map", "type": "bool", "capacity": 16},       # card -> revealed
    "drawRset": {"kind": "map", "type": "bool", "capacity": 16},         # card -> reason chosen (or fixed)
    "drawPlaced": {"kind": "map", "type": "bool", "capacity": 16},       # card -> on the board
    # the debate engine's board input (docs/debate-engine.md §2.2; same declaration as tools/gen_debate.py)
    "debBoard": {"kind": "list", "type": "string", "capacity": SLOTS + LOOSE},
    "debBoardOk": {"kind": "list", "type": "number", "capacity": SLOTS + LOOSE},
    "debBoardLink": {"kind": "list", "type": "number", "capacity": SLOTS + LOOSE},
    # dialogue cursor
    "dlgState": {"kind": "map", "type": "number", "capacity": 2},
    # settings: settings.res_options (the option labels) and the selected one's label (its `sel`)
    "setRes": {"kind": "list", "type": "string", "capacity": 1 + 5, "unique": True},
    "setResOn": {"kind": "list", "type": "string", "capacity": 1},
}
# debate_ui runs before the engine (its values reach the engine in the same tick, its pulses the next one,
# docs/debate-engine.md §7.6), result after it.
FLOW_ORDER = ["main", "settings", "dialogue", "paper", "investigate", "board", "debate_ui", "debate_engine", "debate_warmup",
              "result", "music"]


def game_json_text(tables: dict) -> str:
    import gen_debui
    game = json.loads(GAME_JSON.read_text(encoding="utf-8"))
    # the debate engine's interface (tools/gen_debate.py) and the debate UI / result flows' (tools/gen_debui.py)
    for name, decl in {**SIGNALS, **gen_debate.SIGNALS, **gen_debui.SIGNALS}.items():
        game["signals"][name] = decl
    colls = game.get("collections", {})
    colls.update(gen_debate.COLLECTIONS)
    colls.update(COLLECTIONS)
    colls.update(gen_debui.COLLECTIONS)
    game["collections"] = colls
    for name in [n for n in game["tables"] if n.startswith("flow")]:   # the flow tables are all regenerated
        del game["tables"][name]
    for name in tables:
        game["tables"][name] = f"data/flow/{name}.json"
    for name, rel in gen_debate.TABLES.items():
        game["tables"][name] = rel
    game["tables"][gen_debate.SCRIPT_TABLE] = gen_debate.script_table("data/debScript.json")   # tools/build_data.py
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
    # effective trust of this case (01-systems §3.1): the permanent trust + the warmup's modifier (caseMod)
    g.put("trustP", "world.trust")
    g.mget("trustD", "caseMod", g.k("trust"))
    g.x("trust", "clamp(trustP + trustD, 0, 5)")
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
    the card's appraisal line (evidence.appraisalKey, §1.5 step 3 「鑑定台詞」), or the done line of its kind when the
    card has none. The decision is read before the effects (queries keep their value within the tick).
    """
    card_values(g, pre, card)
    g.n(pre + "_has", g.cmp(pre + "_hasC", card, g.k(""), "ne"))
    g.x(pre + "_idx", f"!({pre}_has && unlockedN) ? 0 : ({pre}_cost == 0 || {pre}_full) ? 1 : "
                      f"apprLeft < {pre}_cost ? 2 : 2 + {pre}_appraise")
    g.lookup(pre + "_line0", ["", "ART_APPR_NONE", "ART_APPR_EMPTY", "ART_APPR_MED_DONE", "ART_APPR_MECH_DONE",
                              "ART_APPR_DUAL"], pre + "_idx")
    g.tget(pre + "_apprLine", "flowCard", "apprLine", pre + "_row")
    g.n(pre + "_hasAL", g.cmp(pre + "_hasALC", pre + "_apprLine", g.k(""), "ne"))
    g.x(pre + "_useAL", f"{pre}_idx >= 3 && {pre}_hasAL")
    line = g.sel(pre + "_line", pre + "_useAL_t", pre + "_apprLine", pre + "_line0")
    g.x(pre + "_newLeft", f"apprLeft - {pre}_cost")
    do = g.when(pre + "_do", trigger, g.b(pre + "_doC", g.x(pre + "_doN", f"{pre}_idx >= 3")))
    g.edge(do, g.eff(pre + "_add", "atrium.coll.add", "appraised", value=card))
    g.edge(do, g.eff(pre + "_set", "atrium.map.set", "caseNum", key=g.k("appr"), value=pre + "_newLeft"))
    said = g.when(pre + "_said", trigger, g.b(pre + "_saidC", pre + "_idx"))
    return line, said


def tag_line(g: Graph, pre: str) -> str:
    """The detail panel's tag text for a card with card_values: each tag's display name, or UI_TAG_HIDDEN while it
    is not revealed, joined by UI_TAG_SEP."""
    pieces = []
    sep = g.text(pre + "_sep", g.k("UI_TAG_SEP"))
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
            pieces.append(g.sel(f"{pre}_p{i}", has, g.fmt(f"{pre}_sp{i}", "{a}{b}", sep, txt), g.k("")))
    out = g.fmt(pre + "_tags", "{a}{b}{c}{d}", *pieces[:4])
    if len(pieces) > 4:
        out = g.fmt(pre + "_tags2", "{a}{b}{c}{d}", out, *pieces[4:7])
    return out


# ---------------------------------------------------------------- main

def gen_main() -> Graph:
    """App state machine: title, the step runner over the steps table, surface visibility, language."""
    g = Graph()

    # Language toggle (M0 behaviour). The state follows world.language when something else writes it (--lang);
    # the title's toggle flips the state and the settings screen's text language sets it (to_zh / to_en), which
    # writes world.language: one switch for both screens.
    g.node("lang", "state", initial="zh", states=["zh", "en"],
           transitions=[{"from": "zh", "on": "toggle", "to": "en"}, {"from": "en", "on": "toggle", "to": "zh"},
                        {"from": "*", "on": "to_zh", "to": "zh"}, {"from": "*", "on": "to_en", "to": "en"}])
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
    # settings: pick_lang 0 / 1 (ui-contracts settings); lang_sel = the state's index (0 zh, 1 en)
    g.put("pickLang", "ui#settings.pick_lang")
    g.x("pickZhN", "pickLang == 0")
    g.x("pickEnN", "pickLang == 1")
    g.edge(g.when("pickZh", "ui#settings.pick_lang.emitted", "pickZhN_t"), "lang.to_zh")
    g.edge(g.when("pickEn", "ui#settings.pick_lang.emitted", "pickEnN_t"), "lang.to_en")
    g.edge("lang.index", "ui#settings.lang_sel")

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
    # A retried debate (A-14) starts without its opening lines (docs/flows.md §4.2): world.debRetrying is true from
    # the retry until the step after it begins (written before the step begins: the toggle's edges come first)
    g.toggle("retrying")
    g.edge("world.debRetry", "retrying.setTrue")
    g.edge("world.stepDone", "retrying.setFalse")
    g.edge("ui#title.chapter.emitted", "retrying.setFalse")
    g.edge("retrying.value", "world.debRetrying")
    g.edge("world.stepDone", "cur.increment")
    g.edge("world.debRetry", "cur.decrement")    # result -> the debate step again (A-14 retry)
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

    # Screens: exactly one of title / paper / vn / investigate / board / debate / result is visible; `end` shows
    # the title with its end card; warmup and debate steps show the debate; a result step shows the result, then
    # the vn for its scene's lines (world.resultLines).
    screens = ["title", "paper", "vn", "investigate", "board", "debate", "result"]
    g.node("screen", "state", initial="title", states=screens,
           transitions=[{"from": "*", "on": "to_" + s, "to": s} for s in screens])
    # A debate / warmup step whose scene has `pre` lines (script.cue) starts on the vn; the debate screen comes with
    # world.debGo (dialogue, after those lines). The lines after the debate show the vn again (world.vnShow).
    g.fmt("sceneKey", "CH0{a}_{b}", "chapter.value", "scene.value")
    g.tfind("preRow", "script", "sceneKey", "sceneKey", filters={"playable": "true", "cue": "pre"})
    g.x("hasPre", "preRow >= 0")
    g.x("noPre", "preRow < 0")
    for name, tag, scr in (("isEnd", "end", "title"), ("isPaper", "paper", "paper"), ("isVn", "vn", "vn"),
                           ("isInv", "investigate", "investigate"), ("isBoard", "board", "board"),
                           ("isDeb", "debate", None), ("isWarm", "warmup", None), ("isRes", "result", "result")):
        g.const(name + "Tag", tag)
        g.node(name, "compare", op="eq")
        g.edge("kind.value", name + ".a")
        g.edge(name + "Tag.out", name + ".b")
        if scr:
            g.edge(name + ".true", f"screen.to_{scr}")
    # decided on the step's begin pulse (cur.value's last edge: the step's scene and chapter are settled by then)
    g.n("isDebN", "isDeb.out")
    g.n("isWarmN", "isWarm.out")
    g.n("retryN", "retrying.value")
    g.x("debPre", "(isDebN || isWarmN) && hasPre && !retryN")
    g.x("debNoPre", "(isDebN || isWarmN) && (noPre || retryN)")
    g.edge("world.debGo", "screen.to_debate")
    g.edge("world.vnShow", "screen.to_vn")
    g.edge("world.debBack", "screen.to_debate")
    g.edge("world.resultLines", "screen.to_vn")
    g.edge(g.when("debPreG", "rebegin.out", "debPre_t"), "screen.to_vn")
    g.edge(g.when("debNoPreG", "rebegin.out", "debNoPre_t"), "screen.to_debate")

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

    # Opponent notes overlay (modal, 01-systems §4.4 亞瑟的對手筆記): debate_ui asks for it (world.notesOpen: the
    # 對手筆記 button / N, or the defeat review), its close button closes it, every step begin closes it.
    # world.notesShown tells debate_ui (the debate is paused while it is open).
    g.node("notes", "state", initial="closed", states=["closed", "open"],
           transitions=[{"from": "closed", "on": "open", "to": "open"}, {"from": "*", "on": "close", "to": "closed"}])
    g.edge("world.notesOpen", "notes.open")
    g.edge("ui#notes.close", "notes.close")
    g.edge("rebegin.out", "notes.close")
    g.node("notesVis", "lookup", values=[False, True])
    g.edge("notes.index", "notesVis.index")
    g.edge("notesVis.out", "ui#notes.visible")
    g.edge("notesVis.out", "world.notesShown")

    # Settings overlay (modal, ui-contracts settings): the title's 設定 entry; in the game Esc (when no overlay is
    # open: a visible modal overlay takes the keys) or F1 on the main screens, F1 on the evidence book and the
    # opponent notes. Its close (Esc, Backspace, the button, the dimmed screen) closes it; a step begin does not.
    # world.settingsShown tells debate_ui (the debate is paused while it is open, as with the notes).
    g.node("settings", "state", initial="closed", states=["closed", "open"],
           transitions=[{"from": "closed", "on": "open", "to": "open"}, {"from": "*", "on": "close", "to": "closed"}])
    g.edge("ui#title.open_settings", "settings.open")
    for ui in ("vn", "paper", "investigate", "board", "debate", "result", "evbook", "notes"):
        g.edge(f"ui#{ui}.settings", "settings.open")
    g.edge("ui#settings.close", "settings.close")
    g.node("settingsVis", "lookup", values=[False, True])
    g.edge("settings.index", "settingsVis.index")
    g.edge("settingsVis.out", "ui#settings.visible")
    g.edge("settingsVis.out", "world.settingsShown")

    # The title's 離開遊戲 (ui-contracts title, XTAtrium 09 §9.6): the host closes after this tick (headless: no-op).
    g.node("quit", "atrium.app.quit")
    g.edge("ui#title.quit", "quit.trigger")
    return g


# ---------------------------------------------------------------- settings

# ui-contracts settings: the resolution presets, listed up to the display's native size. Both sides grow, so the
# presets that fit are always a prefix: option i (0 = auto) is RES_PRESETS[i - 1].
RES_PRESETS = [(1280, 720), (1600, 900), (1920, 1080), (2560, 1440), (3840, 2160)]
WINDOW_MODES = ["windowed", "borderless", "fullscreen"]   # settings.mode_sel / pick_mode 0..2 (XTAtrium 09 §9.2)


def gen_settings() -> Graph:
    """The settings overlay's content (ui-contracts settings; XTAtrium 09): resolution and window mode through
    atrium.display.set (read back from display.*), 大字譯名 (world.cutinSub). Its visibility and text language are
    main's (the language state there is the title's too)."""
    g = Graph()
    # the actual render size (display.* change -> the text follows; headless 0 x 0)
    g.edge(g.textf("current", key="UI_SET_RES_CURRENT", w="display.width", h="display.height"),
           "ui#settings.current")

    # window mode: display.mode -> 0 / 1 / 2; a pick applies it at once, with the resolution chosen last
    g.n("modeB", g.cmp("modeBC", "display.mode", g.k("borderless")))
    g.n("modeF", g.cmp("modeFC", "display.mode", g.k("fullscreen")))
    g.edge(g.x("modeSel", "modeB + 2 * modeF"), "ui#settings.mode_sel")

    # resolution: the chosen option (0 = auto: the game.json default), applied at once (auto = 0 x 0)
    ws = [0] + [w for w, _ in RES_PRESETS]
    hs = [0] + [h for _, h in RES_PRESETS]
    labels = [f"{w} × {h}" for w, h in RES_PRESETS]   # bare numbers: the same in every language
    g.put("pickRes", "ui#settings.pick_res")
    res_idx = g.latch("resIdx", "pickRes", "ui#settings.pick_res.emitted")
    g.node("resSet", "atrium.display.set")
    g.edge(g.lookup("pickW", ws, "pickRes"), "resSet.width")
    g.edge(g.lookup("pickH", hs, "pickRes"), "resSet.height")
    g.edge("ui#settings.pick_res.emitted", "resSet.trigger")
    g.node("modeSet", "atrium.display.set")
    g.edge(g.lookup("selW", ws, res_idx), "modeSet.width")
    g.edge(g.lookup("selH", hs, res_idx), "modeSet.height")
    g.edge(g.lookup("pickMode", WINDOW_MODES, "ui#settings.pick_mode"), "modeSet.mode")
    g.edge("ui#settings.pick_mode.emitted", "modeSet.trigger")

    # res_options: auto (UI_SET_RES_AUTO, this language) and the presets up to display.nativeWidth/Height (none
    # when they are 0: headless); `sel` = the chosen option. Rewritten at start, on a pick, on display.changed and
    # on a language change, one tick later (a timer), when the label texts and the chosen option are settled.
    auto = g.text("autoT", g.k("UI_SET_RES_AUTO"))
    g.put("nW", "display.nativeWidth")
    g.put("nH", "display.nativeHeight")
    g.put("resIdxV", res_idx)
    g.x("resAuto", "resIdxV == 0")
    sel = g.sel("selLabel", "resAuto_t", auto, g.lookup("selPreset", [""] + labels, res_idx))
    lang = lang_changed(g)
    start, tick = g.timer("resT")
    g.node("resInit", "timer", interval=0.001, autostart=True, repeat=False)
    for src in ("resInit.tick", "ui#settings.pick_res.emitted", "display.changed", lang):
        g.edge(src, start)
    g.edge(tick, g.eff("resClr", "atrium.coll.clear", "setRes"))
    g.edge(tick, g.eff("resAddA", "atrium.coll.add", "setRes", value=auto))
    for i, (w, h) in enumerate(RES_PRESETS, start=1):
        g.x(f"fit{i}", f"nW >= {w} && nH >= {h}")
        g.edge(g.when(f"fitG{i}", tick, f"fit{i}_t"),
               g.eff(f"resAdd{i}", "atrium.coll.add", "setRes", value=g.k(labels[i - 1])))
    g.edge(tick, g.eff("selClr", "atrium.coll.clear", "setResOn"))
    g.edge(tick, g.eff("selAdd", "atrium.coll.add", "setResOn", value=sel))
    g.edge(tick, g.ui_list("resList", "ui.settings.res_options", "setRes",
                           {"label": "item", "sel": "coll:setResOn.contains"}))

    # 大字譯名 (01-systems §4.6, §4.7 在地化): on by default; debate_ui shows the cut-in subtitle when it is on and
    # the language is not zh-TW
    g.node("subOn", "toggle", initial=True)
    g.edge("ui#settings.toggle_sub", "subOn.toggle")
    g.edge("subOn.value", "ui#settings.sub_on")
    g.edge("subOn.value", "world.cutinSub")
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
    g.cmp("isRes", "world.stepKind", g.k("result"))
    g.n("isVnN", "isVn.out")
    g.n("isResN", "isRes.out")
    g.n("isDebN", g.cmp("isDebC", "world.stepKind", g.k("debate")))
    g.n("isWarmN", g.cmp("isWarmC", "world.stepKind", g.k("warmup")))
    g.x("isDebK", "isDebN || isWarmN")
    g.x("vnOrRes", "isVnN || isResN || isDebK")
    g.node("vnScene", "select")
    g.node("chText", "toString")
    g.node("sceneKey", "format", format="CH0{a}_{b}")   # script.sceneKey, e.g. CH01_S02 (chapters 1-9)
    g.edge("world.stepKind", "isVn.a")
    g.edge("vnTag.out", "isVn.b")
    g.edge("vnOrRes.truth", "vnScene.cond")
    g.edge("world.stepScene", "vnScene.a")
    g.edge("empty.out", "vnScene.b")
    g.edge("world.chapter", "chText.in")
    g.edge("world.chapter", "sceneKey.a")
    g.edge("vnScene.out", "sceneKey.b")

    # A result step's lines (world.resultLines, after the result screen) are the rows of its branch (script.branch
    # win / lose, world.resultBranch); vn scenes have no branch rows.
    playable = {"playable": "true"}
    g.sel("branch", "isRes.out", "world.resultBranch", g.k(""))
    for nm in ("first", "next"):
        g.node(nm, "atrium.table.find", table="script", column="sceneKey", filterColumn="branch",
               filters=json.dumps(playable))
        g.edge("sceneKey.out", f"{nm}.value")
        g.edge("branch", f"{nm}.filterValue")
        g.put(nm, f"{nm}.row")
        if nm == "first":
            g.mget("cur", "dlgState", g.k("row"))
            g.x("from", "cur + 1")
    g.edge("from", "next.from")
    # A debate / warmup step (script.cue): the `pre` lines before the debate screen, the lines of world.debCue
    # (post / postWin / postLose, written by debate_ui) after it.
    g.toggle("postMode")
    # a warm-up retort (ruling G5, world.debAside): the lines of world.debAsideCue in the middle of the warm-up, then
    # back to the debate (world.debBack) instead of ending the step
    g.toggle("asideMode")
    # a retried debate (world.debRetrying, A-14) skips its opening lines: no row has the cue "-"
    g.sel("preCue", "world.debRetrying", g.k("-"), g.k("pre"))
    g.sel("postCue", "postMode.value", "world.debCue", "preCue")
    g.sel("cueVal", "asideMode.value", "world.debAsideCue", "postCue")
    for nm in ("dfirst", "dnext"):
        g.node(nm, "atrium.table.find", table="script", column="sceneKey", filterColumn="cue",
               filters=json.dumps(playable))
        g.edge("sceneKey.out", f"{nm}.value")
        g.edge("cueVal", f"{nm}.filterValue")
        g.put(nm, f"{nm}.row")
    g.edge("from", "dnext.from")
    g.toggle("atBegin")
    g.sel("pickV", "atBegin.value", "first", "next")
    g.sel("pickD", "atBegin.value", "dfirst", "dnext")
    g.sel("pick", "isDebK_t", "pickD", "pickV")
    g.x("pickOk", "pick >= 0")
    g.x("pickNo", "pick < 0")

    # Step begin (vn) shows the first playable row; each advance (only during a vn step) shows the next one, or
    # ends the step when there is none. The toggle selects first/next; the merge settles it before the gates read it.
    g.gate("beginGate")
    g.edge("isVn.out", "beginGate.guard")
    g.edge("world.stepBegin", "beginGate.go")
    resBegin = g.when("resBeginG", "world.resultLines", "isRes.out")
    debBegin = g.when("debBeginG", "world.stepBegin", "isDebK_t")
    postEnd = g.when("postBeginG", "world.debEnd", "isDebK_t")
    asideBegin = g.when("asideBeginG", "world.debAside", "isDebK_t")
    postBegin = g.merge("postAnyM", postEnd, asideBegin)
    g.gate("advGate")
    g.edge("vnOrRes.truth", "advGate.guard")
    g.edge("ui#vn.advance", "advGate.go")
    g.edge(debBegin, "postMode.setFalse")
    g.edge(postBegin, "postMode.setTrue")
    g.edge(debBegin, "asideMode.setFalse")
    g.edge(postEnd, "asideMode.setFalse")
    g.edge(asideBegin, "asideMode.setTrue")
    g.edge("beginGate.changed", "atBegin.setTrue")
    g.edge(resBegin, "atBegin.setTrue")
    g.edge(debBegin, "atBegin.setTrue")
    # the lines after a debate: the vn comes back first (world.vnShow reaches main next tick), the first line is
    # shown on a timer in that next tick, so it is never written while the debate screen is still up
    g.x("dfirstOk", "dfirst >= 0")
    g.edge(g.when("postShowG", g.merge("postShowM", postEnd), "dfirstOk_t"), "world.vnShow")
    # a retort always has its line (debate_ui asks only when the script has a row with that cue)
    g.edge(asideBegin, "world.vnShow")
    postStart, postTick = g.timer("postTimer")
    g.edge(postBegin, postStart)
    g.edge(postTick, "atBegin.setTrue")
    g.edge("advGate.changed", "atBegin.setFalse")
    g.node("show", "merge")
    g.edge("beginGate.changed", "show.in")
    g.edge(resBegin, "show.in")
    g.edge(debBegin, "show.in")
    g.edge(postTick, "show.in")
    g.edge("advGate.changed", "show.in")
    shown = g.when("showGate", "show.out", "pickOk_t")
    over = g.when("overGate", "show.out", "pickNo_t")
    # no lines after the debate: the step ends (on the timer's tick)
    g.n("postModeN", "postMode.value")
    g.n("asideN", "asideMode.value")
    g.x("overDone", "!isDebK || (postModeN && !asideN)")
    g.x("overBack", "isDebK && postModeN && asideN")
    g.x("overGo", "isDebK && !postModeN")
    g.edge(g.when("overDoneG", over, "overDone_t"), "world.stepDone")
    g.edge(g.when("overBackG", over, "overBack_t"), "world.debBack")
    g.edge(g.when("overGoG", over, "overGo_t"), "world.debGo")
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
    # The "previous case" strip (01-systems §3.3 判定順序): world.caseOutcome lose / notorious / win (anything
    # else, e.g. a chapter chosen from the title: win).
    g.cmp("ocLose", "world.caseOutcome", g.k("lose"))
    g.cmp("ocNoto", "world.caseOutcome", g.k("notorious"))
    for port, col in (("result_head", "Key"), ("result_sub", "SubKey")):
        w, n, l = key(f"sw{col}", f"sideWin{col}"), key(f"sn{col}", f"sideNoto{col}"), key(f"sl{col}", f"sideLose{col}")
        g.sel(f"sv{col}", "ocNoto.out", n, w)
        g.sel(f"sx{col}", "ocLose.out", l, f"sv{col}")
        text(f"result{col}", f"sx{col}", port)
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
    g.mget("pl", "invState", g.k("pl"))                # the popup's reaction line shown (0-based)
    g.mget("msgSt", "invState", g.k("msg"))            # end messages: 1 the rescue shown, 2 the missed cards shown
    g.mget("endArm", "invState", g.k("arm"))           # 結束蒐證 pressed once (the warning is up)
    g.mget("autoDone", "invState", g.k("auto"))        # the 全部調查完畢 confirmation has been shown (§1.7)
    bookNew = g.counter("bookNew", initial=0)

    def put_state(name: str, pulse: str, key: str, value: str) -> None:
        g.edge(pulse, g.eff(name, "atrium.map.set", "invState", key=g.k(key), value=value))
    g.n("bookOpenN", "world.bookOpen")
    g.count("neededN", "needed")
    g.count("toFindN", "toFind")
    g.x("outOfTime", "lim && ticks <= 0")
    g.x("canEndN", "neededN == 0")
    g.x("inputOk", "!popOpenN && !bookOpenN")

    hint = Mux(g, "hint", ["key", "left"])
    # spot: the clicked spot (its reaction lines); msg: 0 a spot, 1 the rescue, 2 the missed cards, 3 none missed;
    # n: the missed cards; r0..: the rescued cards (names in MSG_INV_RESCUE)
    popup = Mux(g, "pop", ["kind", "title", "body", "grade", "spot", "msg", "n", "r0", "r1", "r2"])
    NO_MSG = {"spot": g.k(""), "msg": g.k(0), "n": g.k(0), "r0": g.k(""), "r1": g.k(""), "r2": g.k("")}
    initStart, initTick = g.timer("initTimer")
    bookStart, bookTick = g.timer("bookTimer")

    # ---- step begin: clear the case, cards obtained in the event scenes (evidence.obtain = event), the police
    # report (01-systems §3.1: trust >= 3 gives the autopsy card revealed), ticks, charges; the rest next tick.
    for coll in ("held", "appraised", "spotSeen", "toFind", "needed", "oppHand", "notes", "newCards", "spotsHere",
                 "caseSpots", "visSpots"):
        typ = "atrium.map.clear" if COLLECTIONS[coll]["kind"] == "map" else "atrium.coll.clear"
        g.node(f"clr_{coll}", typ, name=coll)
        g.edge(begin, f"clr_{coll}.trigger")
    g.edge(begin, g.eff("addEvent", "atrium.coll.addAll", "held", text="caseEvent"))
    g.edge(g.when("policeGate", begin, "policeOn_t"), g.eff("addPolice", "atrium.coll.addAll", "held",
                                                            text="casePolice"))
    g.edge(begin, g.eff("addSpots", "atrium.coll.addAll", "caseSpots", text="caseSpotsText"))
    g.edge(begin, g.eff("clr_invState", "atrium.map.clear", "invState"))
    g.edge(begin, g.eff("clr_invStr", "atrium.map.clear", "invStr"))
    put_state("ticksSet", begin, "ticks", "ticksInit")
    g.edge(begin, g.eff("apprSet", "atrium.map.set", "caseNum", key=g.k("appr"), value="apprInit"))
    g.edge(begin, "bookNew.reset")
    # Opening line (01-systems §1.4, ART_OPEN_CH0n); a police case without the report: ART_NO_REPORT (§1.11).
    g.fmt("openKey", "ART_OPEN_CH0{a}", "ch")
    g.x("noReport", "policeCh && !policeOn")
    g.sel("openLine", "noReport_t", g.k("ART_NO_REPORT"), "openKey")
    hint.add(begin, {"key": "openLine", "left": g.k(0)})
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
    g.x("si_vis", "si_noReq || !si_gold")
    g.edge(g.when("si_visG", "spotEach.each", "si_vis_t"), g.eff("si_visA", "atrium.coll.add", "visSpots",
                                                                 value="si"))
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
    g.edge(g.text("areaName", g.tget("sceneName", "flowScene", "nameKey", scrow)), "ui#investigate.area_name")
    spots_list = g.ui_list("spotsList", "ui.investigate.spots", "spotsHere",
                           {"id": "key", "name": tref("flowSpot", "id", "nameKey"),
                            **{c: tref("flowSpot", "id", c) for c in ("x", "y", "w", "h", "type")},
                            "state": "value"}, localize=["name"])
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
    put_state("navArmS", nav, "arm", g.k(0))
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
    g.tget("c_note0", "flowSpot", "noteKey", crow)
    g.tget("c_report", "flowSpot", "reportNote", crow)
    card_values(g, "cy", "c_yield")
    g.n("c_seen", g.mhas("c_seenC", "spotSeen", "spot"))
    g.n("c_held", g.contains("c_heldC", "held", "c_yield"))
    g.x("c_costs", "!c_seen")
    # A card already held (event cards, the police report) is not obtained again: its spot shows the card as
    # information. Visited spots replay for free; the first visit of any spot costs one tick (F5, F6).
    # With the police report (ruling F6, trust >= 3) a spot with a report note (HS_CH03_01) only shows that note.
    g.n("c_hasRep", g.cmp("c_hasRepC", "c_report", g.k(""), "ne"))
    g.x("c_rep", "policeOn && c_hasRep")
    g.sel("c_note", "c_rep_t", "c_report", "c_note0")
    g.x("c_obtain", "c_type > 0 && !c_held && !c_rep")
    g.x("c_inspect", "c_type == 0 || c_rep")
    g.x("c_kind", "c_inspect ? 1 : c_obtain ? (c_type == 2 ? 3 : 2) : 1")
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
    popup.add(click, {"kind": "c_kind", "title": "c_title", "body": "c_body", "grade": "cy_grade",
                      **NO_MSG, "spot": "spot"})
    put_state("c_popS", click, "pop", g.k(1))
    put_state("c_plS", click, "pl", g.k(0))
    g.edge(click, g.eff("c_spotS", "atrium.map.set", "invStr", key=g.k("spot"), value="spot"))
    put_state("c_armS", click, "arm", g.k(0))
    # Arthur's line after the click (ticks read before it: 1 = time out, 4 = 3 left) (§1.3 ART_TIME_LOW), a key /
    # story / substitute card obtained; none in Ch.1, where Arthur is not the assistant yet (§1.11).
    g.x("c_hint", "ch == 1 ? 0 : (lim && c_costs && ticks == 1) ? 1 : (lim && c_costs && ticks == 4) ? 2 : "
                  "c_obtain ? (cy_grade == 1 ? 3 : cy_grade == 2 ? 4 : cy_grade == 4 ? 5 : 0) : 0")
    g.lookup("c_hintKey", ["", "ART_TIME_OUT", "ART_TIME_LOW", "ART_FOUND_KEY", "ART_FOUND_PLOT", "ART_SUB_FOUND"],
             "c_hint")
    hint.add(g.when("c_hintG", g.merge("c_hintM", click), "c_hint_t"), {"key": "c_hintKey", "left": g.k(0)})
    g.edge(click, spots_list)

    # ---- popup clicked: the spot's next reaction line (hotspots.lines, in order), or closed after the last one.
    # (the popup's spot is kept in invStr too: the gates may not read the popup's own outputs, rule 2)
    g.mget("s_spot", "invStr", g.k("spot"))
    g.tget("s_nLines", "flowSpot", "nLines", g.tfind("s_row", "flowSpot", "id", "s_spot"), "number")
    g.n("s_hasSpot", g.cmp("s_hasSpotC", "s_spot", g.k(""), "ne"))
    g.x("moreN", "s_hasSpot && msgSt == 0 && pl + 1 < s_nLines")
    g.x("lastN", "!moreN")
    dismiss = g.when("dismissGate", g.when("dismissInv", "ui#investigate.dismiss", isInv), popOpen)
    adv = g.when("advGate", dismiss, "moreN_t")
    close = g.when("closeGate", dismiss, "lastN_t")
    g.x("plNext", "pl + 1")
    put_state("a_plS", adv, "pl", "plNext")
    advStart, advTick = g.timer("advTimer")       # the next line is read back next tick, then line_seq moves
    g.edge(adv, advStart)
    put_state("d_popS", close, "pop", g.k(0))
    put_state("d_plS", close, "pl", g.k(0))
    g.edge(close, g.eff("d_spotS", "atrium.map.set", "invStr", key=g.k("spot"), value=g.k("")))
    # Out of ticks: first the required-card rescue (§1.7: ART_RESCUE, MSG_INV_RESCUE with the cards), then the end
    # of the investigation.
    g.x("rescueN", "outOfTime && neededN > 0 && msgSt == 0")
    rescue = g.when("rescueGate", close, "rescueN_t")
    rc = [g.cget(f"rc{i}", "needed", g.k(i)) for i in range(3)]
    popup.add(rescue, {"kind": g.k(4), "title": g.k(""), "body": g.k(""), "grade": g.k(0),
                       **NO_MSG, "msg": g.k(1), "r0": rc[0], "r1": rc[1], "r2": rc[2]})
    put_state("r_popS", rescue, "pop", g.k(1))
    put_state("r_msgS", rescue, "msg", g.k(1))
    g.node("rescueEach", "atrium.coll.forEach", name="needed")
    g.edge(rescue, "rescueEach.trigger")
    for coll, typ in (("held", "add"), ("toFind", "remove"), ("newCards", "add")):
        g.edge("rescueEach.each", g.eff(f"r_{coll}", f"atrium.coll.{typ}", coll, value="rescueEach.item"))
    g.edge("rescueEach.each", "bookNew.increment")
    g.edge(rescue, g.eff("r_clear", "atrium.coll.clear", "needed"))
    finish = g.merge("finish")
    g.x("timeoutN", "outOfTime && neededN == 0 && msgSt < 2")
    g.edge(g.when("timeoutEnd", close, "timeoutN_t"), "finish.in")
    # 結束蒐證 (§1.7): the first press warns in the hint bubble (Ch.2-3 WARN_INV_END with the ticks left, or
    # WARN_INV_END_ZERO when every spot has been looked at; Ch.1, §1.11: SHF_C1_REMAIN while cards remain, none
    # left: no warning), a second press ends; a spot click or an area change asks again.
    g.x("endOkN", "inputOk && canEndN")
    endP = g.when("endGate", g.when("endInv", "ui#investigate.end", isInv), "endOkN_t")
    g.count("seenN", "spotSeen")
    g.count("visN", "visSpots")
    g.x("needWarn", "ch == 1 ? toFindN > 0 : 1")
    g.x("warnIdx", "ch == 1 ? 0 : seenN >= visN ? 1 : 2")
    warnKey = g.lookup("warnKey", ["SHF_C1_REMAIN", "WARN_INV_END_ZERO", "WARN_INV_END"], "warnIdx")
    g.x("warnN", "needWarn && !endArm")
    g.x("goN", "!needWarn || endArm")
    warnP = g.when("warnGate", endP, "warnN_t")
    put_state("w_armS", warnP, "arm", g.k(1))
    hint.add(warnP, {"key": warnKey, "left": "ticks"})
    g.edge(g.when("goGate", endP, "goN_t"), "finish.in")
    # 全部調查完畢 (§1.7): when the popup of the last spot not yet looked at closes, the end confirmation comes up by
    # itself (WARN_INV_END_ZERO in the hint bubble, armed: one press of 結束蒐證 ends), once per investigation; it is
    # not forced: a spot click or an area change disarms it as usual.
    g.x("autoN", "!outOfTime && canEndN && visN > 0 && seenN >= visN && msgSt == 0 && !autoDone")
    autoP = g.when("autoGate", close, "autoN_t")
    put_state("au_armS", autoP, "arm", g.k(1))
    put_state("au_doneS", autoP, "auto", g.k(1))
    hint.add(autoP, {"key": g.k("WARN_INV_END_ZERO"), "left": "ticks"})
    # End (§1.8): every card the spots could still give that the opponent can obtain goes to his hand (D4: hand +1,
    # HP +10 each; applied by the debate); not in Ch.1 (chapters.missToHand). Then MSG_INV_MISSED with their
    # count (MSG_INV_MISSED_NONE for none) in the popup, and the step is done when it is closed; Ch.1: done now.
    g.node("missEach", "atrium.coll.forEach", name="toFind")
    g.edge(finish, "missEach.trigger")
    g.put("mi", "missEach.item")
    g.tget("mi_obt", "flowCard", "obtainable", g.tfind("mi_row", "flowCard", "id", "mi"), "number")
    g.x("mi_n", "mi_obt && missToHand")
    g.edge(g.when("mi_g", "missEach.each", "mi_n_t"), g.eff("mi_add", "atrium.coll.add", "oppHand", value="mi"))
    fin = g.merge("finishDone", finish)
    g.x("withMsg", "missToHand != 0")
    g.x("noMissMsg", "missToHand == 0")
    g.edge(g.when("finNow", fin, "noMissMsg_t"), "world.stepDone")
    missStart, missTick = g.timer("missTimer")
    g.edge(g.when("finMsg", fin, "withMsg_t"), missStart)
    g.count("handN", "oppHand")
    g.x("missMsg", "handN > 0 ? 2 : 3")
    popup.add(missTick, {"kind": g.k(4), "title": g.k(""), "body": g.k(""), "grade": g.k(0),
                         **NO_MSG, "msg": "missMsg", "n": "handN"})
    put_state("m_popS", missTick, "pop", g.k(1))
    put_state("m_msgS", missTick, "msg", g.k(2))
    g.x("msgDoneN", "msgSt == 2")
    g.edge(g.when("msgDone", close, "msgDoneN_t"), "world.stepDone")

    # ---- Arthur's hint (ask_hint): cards still to find (§1.11); Ch.1 is Sherefox's own line.
    ask = g.when("askGate", g.when("askInv", "ui#investigate.ask_hint", isInv), "inputOk_t")
    g.x("askIdx", "ch == 1 ? (toFindN > 0 ? 1 : 2) : toFindN >= 4 ? 3 : toFindN >= 1 ? 4 : 5")
    g.lookup("askKey", ["", "SHF_C1_REMAIN", "SHF_C1_IDLE", "ART_REMAIN_MANY", "ART_REMAIN_FEW", "ART_REMAIN_NONE"],
             "askIdx")
    hint.add(ask, {"key": "askKey", "left": g.k(0)})

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
    # Arthur's line in the book itself (evbook.remark; the hint bubble is under the modal book)
    # (cleared when the book opens)
    brm = Mux(g, "bookRm", ["key"])
    brm.add("bookState.true", {"key": g.k("")})
    brm.add(said, {"key": line})
    g.edge(g.text("bookRemark", brm.out("key", g.k(""))), "ui#evbook.remark")
    g.edge(brm.seq, "ui#evbook.remark_seq")
    g.edge(said, bookStart)
    # Cards of the current tab (bookList: id -> revealed): 0 case evidence (held, not story), 1 golden clues,
    # 2 private collection (held story cards).
    g.edge(bookTick, g.eff("clrBook", "atrium.map.clear", "bookList"))
    for t, (coll, want) in enumerate((("held", "!bi0_story"), ("golden", "1"), ("held", "bi2_story"))):
        pre = f"bi{t}"
        g.node(pre + "Each", "atrium.coll.forEach", name=coll)
        g.x(pre + "TabN", f"tab == {t}")
        g.edge(g.when(pre + "Tab", bookTick, pre + "TabN_t"), pre + "Each.trigger")
        item = g.put(pre, pre + "Each.item")
        card_values(g, pre, item)
        g.x(pre + "_n", want)
        g.edge(g.when(pre + "_g", pre + "Each.each", pre + "_n_t"),
               g.eff(pre + "_add", "atrium.map.set", "bookList", key=item, value=pre + "_full_t"))
    g.edge(bookTick, g.ui_list("cardsList", "ui.evbook.cards", "bookList",
                               {"id": "key", "name": tref("flowCard", "id", "nameKey"),
                                "grade": tref("flowCard", "id", "grade"), "appraised": "value",
                                "isnew": "coll:newCards.contains"}, localize=["name"]))
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
    g.text("hintText", hint.out("key", g.k("")))
    g.edge(g.textf("hintF", pattern="hintText.text", left=hint.out("left", g.k(0))), "ui#investigate.hint")
    g.edge(hint.seq, "ui#investigate.hint_seq")
    g.sel("popKind", popOpen, popup.out("kind", g.k(0)), g.k(0))
    g.edge("popKind", "ui#investigate.popup_kind")
    g.edge(g.text("popTitle", popup.out("title", g.k(""))), "ui#investigate.popup_title")
    g.put("p_spot", popup.out("spot", g.k("")))
    g.put("p_msg", popup.out("msg", g.k(0)))
    prow = g.tfind("p_row", "flowSpot", "id", "p_spot")
    g.tget("p_nLines", "flowSpot", "nLines", prow, "number")
    g.n("p_hasSpot", g.cmp("p_hasSpotC", "p_spot", g.k(""), "ne"))
    g.x("moreD", "p_hasSpot && p_msg == 0 && pl + 1 < p_nLines")
    # the body: the spot's text, or the end message (MSG_INV_RESCUE names the rescued cards, joined by UI_TAG_SEP)
    g.text("popBodyK", popup.out("body", g.k("")))
    sep = g.text("rsSep", g.k("UI_TAG_SEP"))
    names = []
    for i in range(3):
        rid = popup.out(f"r{i}", g.k(""))
        g.text(f"rsName{i}", g.tget(f"rsKey{i}", "flowCard", "nameKey", g.tfind(f"rsRow{i}", "flowCard", "id", rid)))
        if i == 0:
            names.append(f"rsName{i}")
        else:
            has = g.cmp(f"rsHas{i}", rid, g.k(""), "ne")
            names.append(g.sel(f"rsPart{i}", has, g.fmt(f"rsSp{i}", "{a}{b}", sep, f"rsName{i}"), g.k("")))
    g.fmt("rsNames", "{a}{b}{c}", *names)
    g.textf("rescueT", key="MSG_INV_RESCUE", name="rsNames")
    g.textf("missedT", key="MSG_INV_MISSED", n=popup.out("n", g.k(0)))
    g.text("noneT", g.k("MSG_INV_MISSED_NONE"))
    g.x("pmIs1", "p_msg == 1")
    g.x("pmIs2", "p_msg == 2")
    g.x("pmIs3", "p_msg == 3")
    body = g.sel("popBody3", "pmIs3_t", "noneT", "popBodyK")
    body = g.sel("popBody2", "pmIs2_t", "missedT", body)
    body = g.sel("popBody", "pmIs1_t", "rescueT", body)
    g.edge(body, "ui#investigate.popup_body")
    # the reaction line under the body (the rescue: Arthur's ART_RESCUE)
    lk, sk = g.k(""), g.k("")
    for i in range(max_spot_lines()):
        g.tget(f"p_line{i}", "flowSpot", f"line{i}", prow)
        g.tget(f"p_spk{i}", "flowSpot", f"spk{i}", prow)
        at = g.cmp(f"p_at{i}", "pl", g.k(i))
        lk = g.sel(f"p_lk{i}", at, f"p_line{i}", lk)
        sk = g.sel(f"p_sk{i}", at, f"p_spk{i}", sk)
    lk = g.sel("p_lineKey", "pmIs1_t", g.k("ART_RESCUE"), g.sel("p_lk", "p_hasSpotC", lk, g.k("")))
    sk = g.sel("p_spkKey", "pmIs1_t", g.k("SPK_ARTHUR"), g.sel("p_sk", "p_hasSpotC", sk, g.k("")))
    g.edge(g.text("popLine", lk), "ui#investigate.popup_line")
    g.edge(g.text("popSpk", sk), "ui#investigate.popup_speaker")
    g.edge("moreD_t", "ui#investigate.popup_more")
    g.counter("advN", initial=0)                # each popup (its first line) and each next line
    g.edge(advTick, "advN.increment")
    g.edge(g.x("plSeqV", "popSeq + advN"), "ui#investigate.popup_line_seq")
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
        # A card without a chosen reason links to nothing (01-systems §2.3): 0, the row is split there; invalid
        # (nothing shared) still bounces a card when it is placed, reason or not.
        g.x(f"k{s}", f"!(v{s} && v{s + 1}) ? 0 : L{s}_shared == 0 ? 3 : !({a}_rset && {bb}_rset) ? 0 : "
                     f"(L{s}_firm > 0 && {a}_ok && {bb}_ok && !{a}_sub && !{bb}_sub) ? "
                     f"(({a}_goldenCard || {bb}_goldenCard) ? 4 : 1) : 2")
        g.x(f"dl{s}", f"(k{s} == 1 || k{s} == 4) ? 1 : k{s} == 2 ? 2 : 0")   # debBoardLink value
    for r in range(3):
        sl = [s for s in links if s // 5 == r]
        # cards of the row that are linked to a neighbour (an unreasoned card is in no chain, §2.3)
        g.x(f"cnt{r}", " + ".join(
            f"(v{s} && ({' || '.join(f'(k{j} == 1 || k{j} == 2 || k{j} == 4)' for j in (s - 1, s) if j in links and j // 5 == r)}))"
            for s in range(5 * r, 5 * r + 5)))
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
    # Lists (08 §8.4 field references, keyed by the row key). slots: card -> chain (slotList) and pos (slotPos), in
    # slot order; links: slot -> kind (linkMap; chain and pos from flowLink); chain plates: chain -> damage
    # (chainMap, inserted in chain order, so index = chain) with chainCards / chainSolid / chainSoph; drawer: card ->
    # revealed (drawerList) with drawRset / drawPlaced.
    g.edge(lists, g.eff("clrSlots", "atrium.map.clear", "slotList"))
    g.edge(lists, g.eff("clrSlotPos", "atrium.map.clear", "slotPos"))
    for s in range(SLOTS):
        sk = g.when(f"sk{s}G", lists, f"id{s}_ok")
        g.edge(sk, g.eff(f"sk{s}A", "atrium.map.set", "slotList", key=f"id{s}", value=g.k(s // 5)))
        g.edge(sk, g.eff(f"sk{s}P", "atrium.map.set", "slotPos", key=f"id{s}", value=g.k(s % 5)))
    g.edge(lists, g.ui_list("slotsList", "ui.board.slots", "slotList",
                          {"chain": "value", "pos": "map:slotPos", "id": "key",
                           "name": tref("flowCard", "id", "nameKey"), "grade": tref("flowCard", "id", "grade")},
                          localize=["name"]))
    g.edge(lists, g.eff("clrLinks", "atrium.map.clear", "linkMap"))
    for s in links:
        g.edge(g.when(f"lk{s}G", lists, f"k{s}_t"),
               g.eff(f"lk{s}S", "atrium.map.set", "linkMap", key=g.k(str(s)), value=f"k{s}"))
    g.edge(lists, g.ui_list("linksList", "ui.board.links", "linkMap",
                          {"chain": tref("flowLink", "key", "chain"), "pos": tref("flowLink", "key", "pos"),
                           "kind": "value"}))
    for coll in ("chainMap", "chainCards", "chainSolid", "chainSoph"):
        g.edge(lists, g.eff(f"lc_{coll}", "atrium.map.clear", coll))
    for r in range(3):
        for coll, val in (("chainMap", f"dmg{r}"), ("chainCards", f"cnt{r}"), ("chainSolid", f"solid{r}"),
                          ("chainSoph", f"soph{r}")):
            g.edge(lists, g.eff(f"ck{r}_{coll}", "atrium.map.set", coll, key=g.k(str(r)), value=val))
    g.edge(lists, g.ui_list("chainList", "ui.board.chain_info", "chainMap",
                          {"chain": "index", "cards": "map:chainCards", "solid": "map:chainSolid",
                           "soph": "map:chainSoph", "dmg": "value"}))
    for coll in ("drawerList", "drawRset", "drawPlaced"):
        g.edge(lists, g.eff(f"lc_{coll}", "atrium.map.clear", coll))
    g.edge(lists, "unappr.reset")
    g.node("drawEach", "atrium.coll.forEach", name="boardCards")
    g.edge(lists, "drawEach.trigger")
    di = g.put("di", "drawEach.item")
    card_values(g, "di", di)
    reason_values(g, "di", di)
    for r in range(3):
        g.n(f"di_in{r}", g.contains(f"di_inC{r}", f"row{r}", di))
    g.x("di_placed", "di_in0 || di_in1 || di_in2")
    for coll, val in (("drawerList", "di_full_t"), ("drawRset", "di_rset_t"), ("drawPlaced", "di_placed_t")):
        g.edge("drawEach.each", g.eff(f"di_{coll}", "atrium.map.set", coll, key=di, value=val))
    g.x("di_unN", "unlockedN && di_cost > 0 && !di_full")
    g.edge(g.when("di_unG", "drawEach.each", "di_unN_t"), "unappr.increment")
    g.edge(lists, g.ui_list("drawerUi", "ui.board.drawer", "drawerList",
                          {"id": "key", "name": tref("flowCard", "id", "nameKey"),
                           "grade": tref("flowCard", "id", "grade"), "appraised": "value",
                           "reason_set": "map:drawRset", "placed": "map:drawPlaced"}, localize=["name"]))
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
    # appraise with charges left -> the warning as a remark (WARN_BOARD_*, atrium.textf), a second press goes on;
    # then lock.
    g.x("tdIdx", "chains == 0 ? 1 : (!armedN && (noReason > 0 || (unappr > 0 && apprLeft > 0))) ? 2 : 3")
    td = g.when("tdAct", g.when("tdInv", "ui#board.to_debate", isBoard), "activeN_t")
    g.latch("tdD", "tdIdx", td)
    tdm = g.merge("tdM", td)
    g.x("noChainN", "tdD == 1")
    remark.add(g.when("noChainG", tdm, "noChainN_t"), {"key": g.k("MSG_BOARD_NOCHAIN")})
    g.x("warnN", "tdD == 2")
    warn = g.when("warnG", tdm, "warnN_t")
    g.sel("warnKey", "noReason_t", g.k("WARN_BOARD_NOREASON"), g.k("WARN_BOARD_UNAPPR"))
    # the warning's {n} (cards without a reason, or cards still to appraise) and {left} (charges), latched before
    # the remark's key changes
    g.x("warnCount", "noReason > 0 ? noReason : unappr")
    g.latch("warnNL", "warnCount", warn)
    g.latch("warnLeftL", "apprLeft", warn)
    remark.add(warn, {"key": "warnKey"})
    g.edge(warn, g.eff("bs11_armed", "atrium.map.set", "boardState", key=g.k("armed"), value=g.k(1)))
    g.x("commitN", "tdD == 3")
    commit = g.when("commitG", tdm, "commitN_t")
    # debBoard / debBoardOk / debBoardLink (docs/debate-engine.md §2.2): chain c card i at 5c + i ("-" empty, ok 1,
    # link 0), then the drawer cards that are not on the board from 15 in drawer order, "-" up to 24.
    for coll in ("debBoard", "debBoardOk", "debBoardLink"):
        g.edge(commit, g.eff(f"cm_clr_{coll}", "atrium.coll.clear", coll))
    for s in range(SLOTS):
        # a placed card without a reason does not fight (§2.7): an empty slot for the engine
        g.x(f"cmOn{s}", f"v{s} && s{s}_rset")
        g.sel(f"cmId{s}", f"cmOn{s}_t", f"id{s}", g.k("-"))
        g.x(f"cmOk{s}", f"cmOn{s} ? s{s}_ok : 1")
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
    # UI_BOARD_THRESHOLD「{stage}論破：{condition}」: the stage name (UI_STAGE_*) and its condition
    g.sel("stageKey0", "phaseMid", g.k("UI_STAGE_MID"), g.k("UI_STAGE_EARLY"))
    g.sel("stageKey", "phaseLate", g.k("UI_STAGE_LATE"), "stageKey0")
    g.textf("condText", key="UI_BOARD_THRESHOLD", stage=g.text("stageText", "stageKey"),
            condition=g.text("condPart", "condKey"))
    g.edge("condText", "ui#board.threshold_text")
    g.text("remarkText", remark.out("key", g.k("")))
    g.edge(g.textf("remarkF", pattern="remarkText.text", n="warnNL", left="warnLeftL"), "ui#board.remark")
    g.edge(remark.seq, "ui#board.remark_seq")
    return g


# ---------------------------------------------------------------- stubs

import gen_debate  # noqa: E402  (the engine's interface: signals, collections, tables)


# ---------------------------------------------------------------- music

def gen_music() -> Graph:
    """Music hooks (rulings H1-H3, docs/audio-requests.md): world.bgmMoment = the moment the game is in (the step
    kind; a debate / warmup step: debate_ui's world.bgmDeb), world.bgm = its BGM id (flowBgm). The framework has no
    music playback yet: playing it later is one node on world.bgm (docs/flows.md §4.10)."""
    g = Graph()
    cur = g.k("title")   # no step, the end card
    for kind, mom in (("result", "result"), ("board", "board"), ("investigate", "investigate"), ("vn", "daily"),
                      ("paper", "daily")):
        cur = g.sel(f"m_{kind}", g.cmp(f"is_{kind}", "world.stepKind", g.k(kind)), g.k(mom), cur)
    g.n("isDebN", g.cmp("isDebC", "world.stepKind", g.k("debate")))
    g.n("isWarmN", g.cmp("isWarmC", "world.stepKind", g.k("warmup")))
    g.x("isDebK", "isDebN || isWarmN")
    mom = g.sel("moment", "isDebK_t", "world.bgmDeb", cur)
    g.edge(mom, "world.bgmMoment")
    g.edge(g.tget("bgmId", "flowBgm", "bgm", g.tfind("bgmRow", "flowBgm", "moment", mom)), "world.bgm")
    return g


def graphs() -> dict:
    import gen_debui  # the debate UI and result flows (it imports this module, so not at the top)
    return {"main": gen_main, "settings": gen_settings, "dialogue": gen_dialogue, "paper": gen_paper, "investigate": gen_investigate,
            "board": gen_board, "debate_ui": gen_debui.gen_debui, "result": gen_debui.gen_result, "music": gen_music}


def outputs() -> dict[Path, str]:
    import gen_debui
    out = {FLOWS / f"{name}.xtflow": fn().text_out() for name, fn in graphs().items()}
    tables = flow_tables()
    tables.update(gen_debui.tables())
    for name, rows in tables.items():
        out[FLOW_DATA / f"{name}.json"] = table_text(rows)
    out[GAME_JSON] = game_json_text(tables)
    return out


def main() -> int:
    check = "--check" in sys.argv[1:]
    stale = []
    out = outputs()
    for path, text in out.items():
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path.relative_to(ROOT).as_posix())
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
            print(f"wrote {path.relative_to(ROOT).as_posix()}")
    # data/flow/ holds only generated tables: one that is no longer generated is stale (deleted when writing)
    for path in sorted(FLOW_DATA.glob("*.json")):
        if path not in out:
            if check:
                stale.append(path.relative_to(ROOT).as_posix())
            else:
                path.unlink()
                print(f"deleted {path.relative_to(ROOT).as_posix()}")
    if "--stats" in sys.argv[1:]:
        for name, fn in graphs().items():
            n, e = fn().stats()
            print(f"{name}: {n} nodes, {e} edges")
    if stale:
        print("stale: " + ", ".join(stale) + " (run uv run tools/gen_flows.py)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
