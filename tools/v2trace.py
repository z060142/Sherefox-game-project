"""Tracing compiler used by tools/gen_debate_v2.py (docs/debate-engine-v2.md §3).

The v2 round is written in Python over symbolic values (`N` numbers, `S` strings). Branches on symbolic conditions
run both arms and merge every changed variable with a select; effects (event records, list operations, rng draws,
map writes) are recorded in program order with the path condition as their guard. `Emitter` turns the result into
an .xtflow graph: one atrium.expr per shared or large sub-expression, lookup / select / format nodes for strings,
and one pulse cascade per entry point (atrium.gate per guard, effects in edge order, XTAtrium 05 §5.4).

Constant folding uses Python floats, which are IEEE doubles like atrium.expr (08 §8.5), and every operation keeps its
operand order (fully parenthesised), so the engine computes bit-identical numbers to ref/.
"""

from __future__ import annotations

import json
import math

# --------------------------------------------------------------------------------------------- numbers


class N:
    __slots__ = ("op", "a", "v", "id", "isbool")

    def __init__(self, op, a, v, nid, isbool):
        self.op, self.a, self.v, self.id, self.isbool = op, a, v, nid, isbool

    # arithmetic only; comparisons are functions (== must stay identity for dict use)
    def __add__(self, o): return T.bin("+", self, o)
    def __radd__(self, o): return T.bin("+", o, self)
    def __sub__(self, o): return T.bin("-", self, o)
    def __rsub__(self, o): return T.bin("-", o, self)
    def __mul__(self, o): return T.bin("*", self, o)
    def __rmul__(self, o): return T.bin("*", o, self)
    def __truediv__(self, o): return T.bin("/", self, o)
    def __rtruediv__(self, o): return T.bin("/", o, self)
    def __neg__(self): return T.bin("-", 0, self)

    @property
    def const(self) -> bool:
        return self.op == "c"

    def __repr__(self) -> str:
        return f"N{self.id}:{self.op}" + (f"={self.v}" if self.op == "c" else "")


class S:
    """A string value: const ('sc'), lookup by number ('slk'), select ('ssel'), format ('sfmt'), port ('sin')."""
    __slots__ = ("op", "a", "v", "id")

    def __init__(self, op, a, v, sid):
        self.op, self.a, self.v, self.id = op, a, v, sid

    @property
    def const(self) -> bool:
        return self.op == "sc"


_CMP = {"==": lambda x, y: x == y, "!=": lambda x, y: x != y, "<": lambda x, y: x < y,
        "<=": lambda x, y: x <= y, ">": lambda x, y: x > y, ">=": lambda x, y: x >= y}
_ARITH = {"+": lambda x, y: x + y, "-": lambda x, y: x - y, "*": lambda x, y: x * y,
          "/": lambda x, y: x / y if y != 0 else math.copysign(math.inf, x) if x != 0 else math.nan}


class Tracer:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._intern: dict = {}
        self._sintern: dict = {}
        self.nodes: list[N] = []
        self.snodes: list[S] = []
        self.pc: N = None  # type: ignore[assignment]
        self.effects: list = []
        self.st: dict = {}
        self.raw: list[dict] = []  # raw graph nodes created while tracing (rng, finds, forEach, ...)
        self.raw_edges: list[tuple[str, str]] = []
        self._raw_ids: set = set()
        self.pc = self.c(1)

    # ---- construction
    def _mk(self, op, a, v, isbool=False) -> N:
        key = (op, tuple(x.id for x in a), v)
        n = self._intern.get(key)
        if n is None:
            n = N(op, a, v, len(self.nodes), isbool)
            self._intern[key] = n
            self.nodes.append(n)
        return n

    def c(self, v) -> N:
        if isinstance(v, N):
            return v
        if isinstance(v, bool):
            v = 1.0 if v else 0.0
        v = float(v)
        return self._mk("c", (), v, v in (0.0, 1.0))

    def port(self, port: str, isbool=False) -> N:
        return self._mk("in", (), port, isbool)

    def lk(self, values, idx) -> N:
        """Number lookup table[idx] (a lookup node); idx must stay inside 0..len-1."""
        idx = self.c(idx)
        values = tuple(float(x) for x in values)
        if all(x == values[0] for x in values):
            return self.c(values[0])
        if idx.const:
            return self.c(values[int(idx.v)])
        return self._mk("lk", (idx,), values, all(x in (0.0, 1.0) for x in values))

    def bin(self, op, a, b) -> N:
        a, b = self.c(a), self.c(b)
        if a.const and b.const:
            if op in _CMP:
                return self.c(_CMP[op](a.v, b.v))
            return self.c(_ARITH[op](a.v, b.v))
        if op == "*" and a.const and a.v == 1.0:
            return b
        if op == "*" and b.const and b.v == 1.0:
            return a
        if op in ("==", "<=", ">=") and a is b:
            return self.c(1)
        if op in ("!=", "<", ">") and a is b:
            return self.c(0)
        return self._mk(op, (a, b), None, op in _CMP)

    def fn(self, name, *args) -> N:
        args = tuple(self.c(x) for x in args)
        if all(x.const for x in args):
            vs = [x.v for x in args]
            f = {"floor": lambda x: float(math.floor(x)), "min": min, "max": max, "abs": abs}[name]
            return self.c(f(*vs))
        if name in ("min", "max") and args[0] is args[1]:
            return args[0]
        return self._mk(name, args, None)

    # ---- logic (results 0/1)
    def truth(self, x) -> N:
        x = self.c(x)
        if x.isbool:
            return x
        return self.bin("!=", x, 0)

    def AND(self, *xs) -> N:
        out = self.c(1)
        for x in xs:
            x = self.truth(x)
            if x.const:
                if x.v == 0:
                    return self.c(0)
                continue
            if out.const:
                out = x
            elif out is x:
                continue
            else:
                out = self._mk("&&", (out, x), None, True)
        return out

    def OR(self, *xs) -> N:
        out = self.c(0)
        for x in xs:
            x = self.truth(x)
            if x.const:
                if x.v != 0:
                    return self.c(1)
                continue
            if out.const:
                out = x
            elif out is x:
                continue
            else:
                out = self._mk("||", (out, x), None, True)
        return out

    def NOT(self, x) -> N:
        x = self.truth(x)
        if x.const:
            return self.c(x.v == 0)
        if x.op == "!":
            return x.a[0]
        return self._mk("!", (x,), None, True)

    def SEL(self, cond, a, b) -> N:
        cond, a, b = self.truth(cond), self.c(a), self.c(b)
        if cond.const:
            return a if cond.v else b
        if a is b:
            return a
        if a.const and b.const and a.v == 1.0 and b.v == 0.0:
            return cond
        if a.const and b.const and a.v == 0.0 and b.v == 1.0:
            return self.NOT(cond)
        return self._mk("?:", (cond, a, b), None, a.isbool and b.isbool)

    def EQ(self, a, b): return self.bin("==", a, b)
    def NE(self, a, b): return self.bin("!=", a, b)
    def LT(self, a, b): return self.bin("<", a, b)
    def LE(self, a, b): return self.bin("<=", a, b)
    def GT(self, a, b): return self.bin(">", a, b)
    def GE(self, a, b): return self.bin(">=", a, b)
    def MIN(self, a, b): return self.fn("min", a, b)
    def MAX(self, a, b): return self.fn("max", a, b)
    def FLOOR(self, a): return self.fn("floor", a)

    def PICK(self, idx, items, default=0) -> N:
        """items: list of (index value, N); value at idx, else default."""
        idx = self.c(idx)
        out = self.c(default)
        for j, v in reversed(items):
            out = self.SEL(self.EQ(idx, j), v, out)
        return out

    # ---- strings
    def _smk(self, op, a, v) -> S:
        key = (op, tuple(x.id for x in a), v)
        s = self._sintern.get(key)
        if s is None:
            s = S(op, a, v, len(self.snodes))
            self._sintern[key] = s
            self.snodes.append(s)
        return s

    def sc(self, text: str) -> S:
        return self._smk("sc", (), text)

    def sport(self, port: str) -> S:
        return self._smk("sin", (), port)

    def slk(self, values, idx) -> S:
        idx = self.c(idx)
        values = tuple(values)
        if all(x == values[0] for x in values):
            return self.sc(values[0])
        if idx.const:
            return self.sc(values[int(idx.v)])
        return self._smk("slk", (idx,), values)

    def ssel(self, cond, a, b) -> S:
        cond = self.truth(cond)
        a, b = self.s(a), self.s(b)
        if cond.const:
            return a if cond.v else b
        if a is b:
            return a
        return self._smk("ssel", (cond, a, b), None)

    def s(self, x) -> S:
        return x if isinstance(x, S) else self.sc(str(x))

    def fmt(self, *parts) -> S:
        """'|'-joined record of parts (str, S, or N formatted %.6g by the format node)."""
        items = [p if isinstance(p, (S, N)) else self.sc(str(p)) for p in parts]
        # fold leading constant strings into the pattern; up to 4 dynamic args per format node
        return self._join(items)

    def _join(self, items) -> S:
        pattern, args = "", []
        out = None
        for i, it in enumerate(items):
            sep = "" if i == 0 else "|"
            if isinstance(it, S) and it.const:
                pattern += sep + it.v.replace("{", "{{").replace("}", "}}")
                continue
            if isinstance(it, N) and it.const:
                pattern += sep + _g6(it.v)
                continue
            if len(args) == 4:
                out = self._smk("sfmt", tuple(args), pattern)
                pattern, args = "{a}", [out]
            pattern += sep + "{" + "abcd"[len(args)] + "}"
            args.append(it)
        if not args:
            return self.sc(pattern)
        return self._smk("sfmt", tuple(args), pattern)

    # ---- raw nodes
    def raw_node(self, nid: str, ntype: str, **params) -> str:
        if nid in self._raw_ids:
            raise ValueError(f"duplicate raw node {nid}")
        self._raw_ids.add(nid)
        n = {"id": nid, "type": ntype}
        if params:
            n["params"] = params
        self.raw.append(n)
        return nid

    def raw_edge(self, src, dst) -> None:
        self.raw_edges.append((src, dst))

    # ---- control flow
    def when(self, cond, then, els=None) -> None:
        cond = self.truth(cond)
        if cond.const:
            f = then if cond.v else els
            if f:
                f()
            return
        st = self.st
        base = dict(st)
        pc0 = self.pc
        self.pc = self.AND(pc0, cond)
        then()
        st_then = dict(st)
        st.clear()
        st.update(base)
        self.pc = self.AND(pc0, self.NOT(cond))
        if els:
            els()
        st_else = dict(st)
        self.pc = pc0
        st.clear()
        for k in st_then:
            if k not in st_else:
                raise KeyError(f"state key {k} created inside a branch")
            a, b = st_then[k], st_else[k]
            if k.startswith("_l"):  # guarded lists: prefix + then items + else items
                pre = base.get(k, ())
                ta = tuple((self.AND(g, cond),) + tuple(r) for (g, *r) in a[len(pre):])
                tb = tuple((self.AND(g, self.NOT(cond)),) + tuple(r) for (g, *r) in b[len(pre):])
                st[k] = tuple(pre) + ta + tb
            elif a is b:
                st[k] = a
            else:
                st[k] = self.SEL(cond, a, b)
        for k in st_else:
            if k not in st:
                raise KeyError(f"state key {k} created inside a branch")

    def effect(self, kind: str, **data) -> None:
        g = self.pc
        if g.const and g.v == 0:
            return
        self.effects.append((g, kind, data))

    def take_effects(self) -> list:
        out, self.effects = self.effects, []
        return out


T = Tracer()


def _g6(v: float) -> str:
    return "%.6g" % v


# --------------------------------------------------------------------------------------------- emission

FUNCS = ("floor", "min", "max", "abs")


def _lit(v: float) -> str:
    if v == int(v) and abs(v) < 1e15:
        s = str(int(v))
    else:
        s = repr(v)
    return f"(0 - {s[1:]})" if s.startswith("-") else s


class Emitter:
    """Builds the .xtflow node and edge lists from traced values."""

    INLINE_MAX = 600
    DEPTH_MAX = 40

    def __init__(self, prefix: str = "") -> None:
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.ids: set = set()
        self.p = prefix
        self.done: dict[int, str] = {}  # N id -> port
        self.sdone: dict[int, str] = {}
        self.bdone: dict[int, str] = {}
        self.consts: dict = {}
        self.refs: dict[int, int] = {}
        self.gates = 0

    # ---- plumbing
    def node(self, nid, ntype, **params) -> str:
        if nid in self.ids:
            raise ValueError(f"duplicate node id {nid}")
        self.ids.add(nid)
        n = {"id": nid, "type": ntype}
        if params:
            n["params"] = params
        self.nodes.append(n)
        return nid

    def edge(self, src, dst) -> None:
        self.edges.append({"from": src, "to": dst})

    def const(self, value) -> str:
        key = json.dumps(value)
        if key not in self.consts:
            nid = f"{self.p}k{len(self.consts)}"
            self.node(nid, "constant", value=value)
            self.consts[key] = f"{nid}.out"
        return self.consts[key]

    def add_raw(self, tracer: Tracer) -> None:
        for n in tracer.raw:
            self.node(n["id"], n["type"], **n.get("params", {}))
        self._raw_edges = list(tracer.raw_edges)

    def flush_raw_edges(self) -> None:
        for s, d in self._raw_edges:
            src = self.num(s) if isinstance(s, N) else self.str_(s) if isinstance(s, S) else s
            self.edge(src, d)

    # ---- reference counts (call once with every root before emitting)
    def count(self, roots) -> None:
        seen = set()
        stack = [r for r in roots if isinstance(r, (N, S))]
        while stack:
            x = stack.pop()
            for ch in x.a:
                if isinstance(ch, N):
                    self.refs[ch.id] = self.refs.get(ch.id, 0) + 1
                if (type(ch), ch.id) not in seen:
                    seen.add((type(ch), ch.id))
                    stack.append(ch)

    # ---- numbers
    def num(self, n: N) -> str:
        """Port carrying number n."""
        if n.op == "c":
            return self.const(n.v)
        if n.op == "in":
            return n.v
        if n.id in self.done:
            return self.done[n.id]
        if n.op == "lk":
            nid = f"{self.p}l{n.id}"
            self.node(nid, "lookup", values=list(n.v))
            self.edge(self.num(n.a[0]), f"{nid}.index")
            self.done[n.id] = f"{nid}.out"
            return self.done[n.id]
        # iterative materialisation of children first (avoids deep recursion)
        order = []
        stack = [(n, False)]
        visited = set()
        while stack:
            x, post = stack.pop()
            if post:
                order.append(x)
                continue
            if x.id in visited:
                continue
            visited.add(x.id)
            stack.append((x, True))
            for ch in x.a:
                if isinstance(ch, N) and ch.op not in ("c", "in") and ch.id not in self.done:
                    stack.append((ch, False))
        texts: dict[int, tuple[str, int, list]] = {}
        for x in order:
            if x.id in self.done:
                continue
            if x.op == "lk":
                self.num(x)
                continue
            t, d, ids = self._text(x, texts)
            shared = self.refs.get(x.id, 0) > 1
            if x is n or shared or len(t) > self.INLINE_MAX or d > self.DEPTH_MAX:
                self._emit_expr(x, t, ids)
            else:
                texts[x.id] = (t, d, ids)
        return self.done[n.id]

    def _emit_expr(self, x: N, text: str, ids: list) -> None:
        nid = f"{self.p}e{x.id}"
        self.node(nid, "atrium.expr", expr=text)
        for ident, port in ids:
            self.edge(port, f"{nid}.{ident}")
        self.done[x.id] = f"{nid}.value"

    def _ref(self, ch: N, texts) -> tuple[str, int, list]:
        if ch.op == "c":
            return _lit(ch.v), 0, []
        if ch.op == "in":
            return f"i{ch.id}", 0, [(f"i{ch.id}", ch.v)]
        if ch.id in self.done:
            return f"v{ch.id}", 0, [(f"v{ch.id}", self.done[ch.id])]
        return texts[ch.id]

    def _text(self, x: N, texts) -> tuple[str, int, list]:
        parts = [self._ref(ch, texts) for ch in x.a]
        ids = []
        for _, _, i in parts:
            for p in i:
                if p not in ids:
                    ids.append(p)
        d = 1 + max((p[1] for p in parts), default=0)
        t = [p[0] for p in parts]
        op = x.op
        if op in FUNCS:
            s = f"{op}({', '.join(t)})"
        elif op == "!":
            s = f"(!{t[0]})"
        elif op == "?:":
            s = f"({t[0]} ? {t[1]} : {t[2]})"
        else:
            s = f"({t[0]} {op} {t[1]})"
        return s, d, ids

    def boolp(self, n: N) -> str:
        """Bool port for n != 0."""
        n = T.truth(n)
        if n.op == "c":
            return self.const(bool(n.v))
        if n.id in self.bdone:
            return self.bdone[n.id]
        p = self.num(n)
        if p.endswith(".value") and p[: -len(".value")] in self.ids and self._is_expr(p[: -len(".value")]):
            out = p[: -len(".value")] + ".truth"
        else:
            nid = f"{self.p}b{n.id}"
            self.node(nid, "compare", op="ne")
            self.edge(p, f"{nid}.a")
            self.edge(self.const(0), f"{nid}.b")
            out = f"{nid}.out"
        self.bdone[n.id] = out
        return out

    def _is_expr(self, nid: str) -> bool:
        return nid.startswith(f"{self.p}e")

    # ---- strings
    def str_(self, s: S) -> str:
        if s.op == "sc":
            return self.const(s.v)
        if s.op == "sin":
            return s.v
        if s.id in self.sdone:
            return self.sdone[s.id]
        nid = f"{self.p}s{s.id}"
        if s.op == "slk":
            self.node(nid, "lookup", values=list(s.v))
            self.edge(self.num(s.a[0]), f"{nid}.index")
            port = f"{nid}.out"
        elif s.op == "ssel":
            c, a, b = s.a
            self.node(nid, "select")
            self.edge(self.boolp(c), f"{nid}.cond")
            self.edge(self.str_(a), f"{nid}.a")
            self.edge(self.str_(b), f"{nid}.b")
            port = f"{nid}.out"
        elif s.op == "sfmt":
            self.node(nid, "format", format=s.v)
            for slot, a in zip("abcd", s.a):
                self.edge(self.num(a) if isinstance(a, N) else self.str_(a), f"{nid}.{slot}")
            port = f"{nid}.out"
        else:
            raise ValueError(s.op)
        self.sdone[s.id] = port
        return port

    def any_(self, x) -> str:
        return self.num(x) if isinstance(x, N) else self.str_(x)

    # ---- cascades
    def cascade(self, source: str, effects: list, name: str) -> None:
        """Run effects in order on pulse `source`; consecutive effects with one guard share a gate."""
        groups: list[tuple[N, list[str]]] = []
        for guard, kind, data in effects:
            trig = self._effect(kind, data, name)
            if groups and groups[-1][0] is guard:
                groups[-1][1].extend(trig)
            else:
                groups.append((guard, list(trig)))
        for guard, trig in groups:
            if guard.const:
                if guard.v == 0:
                    continue
                for t in trig:
                    self.edge(source, t)
                continue
            self.gates += 1
            gid = f"{self.p}{name}g{self.gates}"
            self.node(gid, "atrium.gate")
            self.edge(self.num(guard), f"{gid}.cond")
            self.edge(source, f"{gid}.trigger")
            for t in trig:
                self.edge(f"{gid}.pass", t)

    _eff_n = 0

    def _eid(self, name: str) -> str:
        Emitter._eff_n += 1
        return f"{self.p}{name}x{Emitter._eff_n}"

    def _effect(self, kind: str, d: dict, name: str) -> list[str]:
        if kind == "pulse":  # trigger existing inputs
            return list(d["inputs"])
        nid = self._eid(name)
        if kind == "add":
            self.node(nid, "atrium.coll.add", name=d["coll"])
            self.edge(self.any_(d["value"]), f"{nid}.value")
        elif kind == "remove":
            self.node(nid, "atrium.coll.remove", name=d["coll"])
            self.edge(self.any_(d["value"]), f"{nid}.value")
        elif kind == "clear":
            self.node(nid, "atrium.coll.clear", name=d["coll"])
        elif kind == "mclear":
            self.node(nid, "atrium.map.clear", name=d["coll"])
        elif kind == "mset":
            self.node(nid, "atrium.map.set", name=d["coll"])
            self.edge(self.any_(d["key"]), f"{nid}.key")
            self.edge(self.any_(d["value"]), f"{nid}.value")
        else:
            raise ValueError(kind)
        return [f"{nid}.trigger"]

    def text(self) -> str:
        return json.dumps({"version": 1, "nodes": self.nodes, "edges": self.edges}, ensure_ascii=False,
                          indent=1) + "\n"
