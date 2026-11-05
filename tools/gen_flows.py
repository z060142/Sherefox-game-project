# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generate the Atrium Script flows under flows/ (M2: title -> chapter steps -> paper / vn, stubs for the rest).

Usage (from the project root):
    uv run tools/gen_flows.py            write flows/*.xtflow
    uv run tools/gen_flows.py --check    exit 1 if any flows/*.xtflow differs from what this script generates

The flows talk to each other only through world.* signals (declared in game.json); see docs/flows.md for the
contract. Edge order matters where noted: a node delivers a value or pulse along its edges in file order
(XTAtrium 05 §5.4, TickProgram.OutFan), so an edge that must see a settled value comes after the edges that
change it, and a pulse that must see settled values goes through a merge (a pulse output settles the batch
before it is delivered).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLOWS = ROOT / "flows"


class Graph:
    def __init__(self) -> None:
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self._ids: set[str] = set()

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

    def const(self, node_id: str, value) -> str:
        return self.node(node_id, "constant", value=value)

    def gate(self, node_id: str) -> str:
        """A pulse gate: `<id>.go` passes to `<id>.changed` while `<id>.guard` is true (53 §53.4.15 guard)."""
        return self.node(
            node_id,
            "state",
            states=["a", "b"],
            initial="a",
            transitions=[{"from": "a", "on": "go", "to": "b"}, {"from": "b", "on": "go", "to": "a"}],
        )

    def text(self) -> str:
        return json.dumps({"version": 1, "nodes": self.nodes, "edges": self.edges}, ensure_ascii=False, indent=2) + "\n"


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

    # Step runner. cur = row of the steps table (-1 = none). Choosing a chapter jumps to that chapter's idx-0 row;
    # each world.stepDone moves to the next row (rows are in chapter, idx order, so the last step of a chapter is
    # followed by the next chapter's first step; data-schema §2).
    g.node("chText", "toString")
    g.const("zeroText", "0")
    g.node("chStart", "atrium.table.find", table="steps", column="chapter", filterColumn="idx")
    g.node("cur", "counter", initial=-1)
    g.node("kind", "atrium.table.get", table="steps", column="kind", type="string")
    g.node("arg", "atrium.table.get", table="steps", column="arg", type="string")
    g.node("scene", "atrium.table.get", table="steps", column="scene", type="string")
    g.node("chapter", "atrium.table.get", table="steps", column="chapter", type="number")
    g.node("begin", "filter", op="deadband", threshold=0)
    g.edge("ui#title.chapter", "chText.in")
    g.edge("chText.out", "chStart.value")
    g.edge("zeroText.out", "chStart.filterValue")
    g.edge("chStart.row", "cur.set")
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
    g.edge("begin.passed", "world.stepBegin")

    # Screens: exactly one of title / paper / vn is visible. Stub steps (investigate, board, debate, warmup,
    # result) leave the current screen as it is; `end` shows the title with its end card.
    g.node("screen", "state", initial="title", states=["title", "paper", "vn"],
           transitions=[{"from": "*", "on": "toTitle", "to": "title"},
                        {"from": "*", "on": "toPaper", "to": "paper"},
                        {"from": "*", "on": "toVn", "to": "vn"}])
    for name, tag in (("isEnd", "end"), ("isPaper", "paper"), ("isVn", "vn")):
        g.const(name + "Tag", tag)
        g.node(name, "compare", op="eq")
        g.edge("kind.value", name + ".a")
        g.edge(name + "Tag.out", name + ".b")
    g.edge("isEnd.true", "screen.toTitle")
    g.edge("isPaper.true", "screen.toPaper")
    g.edge("isVn.true", "screen.toVn")
    g.edge("isEnd.out", "ui#title.ended")
    for ui, flags in (("title", [True, False, False]), ("paper", [False, True, False]), ("vn", [False, False, True])):
        nid = "vis" + ui.capitalize()
        g.node(nid, "lookup", values=flags)
        g.edge("screen.index", nid + ".index")
        g.edge(nid + ".out", f"ui#{ui}.visible")
    return g


# ---------------------------------------------------------------- dialogue

def gen_dialogue() -> Graph:
    """vn steps: walk the step's scene in the script table, one line per ui#vn.advance."""
    g = Graph()
    g.const("vnTag", "vn")
    g.const("empty", "")
    g.const("no", False)
    g.const("zero", 0)
    g.const("minusOne", -1)
    g.node("isVn", "compare", op="eq")
    g.node("vnScene", "select")
    g.node("chText", "toString")
    g.edge("world.stepKind", "isVn.a")
    g.edge("vnTag.out", "isVn.b")
    g.edge("isVn.out", "vnScene.cond")
    g.edge("world.stepScene", "vnScene.a")
    g.edge("empty.out", "vnScene.b")
    g.edge("world.chapter", "chText.in")

    # Cursor: row = (first row of the scene, its L001 heading) + 1 + off. off counts advances and is reset at
    # every step begin. Assumes every row after the heading up to the next scene is a playable line (true for the
    # vn scenes of Ch.1-3; tests/check_playthrough.py verifies it); see docs/flows.md "known limits".
    g.node("first", "atrium.table.find", table="script", column="scene", filterColumn="chapter")
    g.node("off", "counter", initial=0)
    g.node("row", "atrium.expr", expr="first + 1 + off")
    g.node("rowScene", "atrium.table.get", table="script", column="scene", type="string")
    g.node("sceneEq", "compare", op="eq")
    g.node("inScene", "select")
    g.node("doneCmp", "compare", op="eq")
    g.edge("vnScene.out", "first.value")
    g.edge("chText.out", "first.filterValue")
    g.edge("first.row", "row.first")
    g.edge("off.value", "row.off")
    g.edge("row.value", "rowScene.row")
    g.edge("rowScene.value", "sceneEq.a")
    g.edge("vnScene.out", "sceneEq.b")
    g.edge("isVn.out", "inScene.cond")
    g.edge("sceneEq.out", "inScene.a")
    g.edge("no.out", "inScene.b")
    # Step done: the cursor left the scene (inScene true -> false). compare fires `true` only on that change.
    g.edge("inScene.out", "doneCmp.a")
    g.edge("no.out", "doneCmp.b")
    g.edge("doneCmp.true", "world.stepDone")

    # Show a line on step begin and on every advance, while the cursor is inside the scene. The counter edges come
    # first; the merge settles the cursor before the gate reads inScene.
    g.node("show", "merge")
    g.gate("showGate")
    g.node("disp", "filter", op="sample")
    g.node("seqBarrier", "merge")
    g.node("lineSeq", "counter", initial=0)
    g.gate("advGate")
    g.edge("world.stepBegin", "off.reset")
    g.edge("world.stepBegin", "show.in")
    g.edge("isVn.out", "advGate.guard")             # advance only counts during a vn step
    g.edge("ui#vn.advance", "advGate.go")
    g.edge("advGate.changed", "off.increment")
    g.edge("advGate.changed", "show.in")
    g.edge("show.out", "showGate.go")
    g.edge("inScene.out", "showGate.guard")
    g.edge("row.value", "disp.in")
    g.edge("showGate.changed", "disp.trigger")
    g.edge("showGate.changed", "seqBarrier.in")   # after disp: line text first, then line_seq
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

    text("headline", key("headlineKey", "headlineKey"), "headline")
    text("subhead", key("subKey", "subKey"), "subhead")
    text("body", key("bodyKey", "bodyKey"), "body")
    # page2Key is the second-page advert (only CH01_OPEN has one: NEWS_00_OPEN_SUB); data-schema §9.
    text("ad", key("page2Key", "page2Key"), "ad")

    # Side column and the "previous case" strip. resultChapter 0 (Ch.1) has no previous case: the side column
    # carries the opening city news (side*Win*Key) and the strip stays hidden. M2 has no result yet: always the
    # WIN variant (docs/flows.md).
    g.node("resultChapter", "atrium.table.get", table="papers", column="resultChapter", type="number")
    g.edge("prow.row", "resultChapter.row")
    g.node("hasResult", "compare", op="gt")
    g.edge("resultChapter.value", "hasResult.a")
    g.edge("zero.out", "hasResult.b")
    side_key = key("sideKey", "sideKey")
    win_key = key("sideWinKey", "sideWinKey")
    win_sub_key = key("sideWinSubKey", "sideWinSubKey")
    for nid, a, b, port in (("sideSel", side_key, win_key, "side"),
                            ("resHeadSel", win_key, "empty.out", "result_head"),
                            ("resSubSel", win_sub_key, "empty.out", "result_sub")):
        g.node(nid, "select")
        g.edge("hasResult.out", nid + ".cond")
        g.edge(a, nid + ".a")
        g.edge(b, nid + ".b")
        text(nid + "Text", nid + ".out", port)

    # Front-page engraving ch01..ch04 from the paper's chapter.
    g.node("chapter", "atrium.table.get", table="papers", column="chapter", type="number")
    g.node("picture", "format", format="ch0{a}")
    g.edge("prow.row", "chapter.row")
    g.edge("chapter.value", "picture.a")
    g.edge("picture.out", "ui#paper.picture")

    # No data for these yet (docs/flows.md): plain masthead, no stamp, no dateline, no second-page story.
    g.edge("zero.out", "ui#paper.mast")
    g.edge("zero.out", "ui#paper.stamp")
    g.edge("empty.out", "ui#paper.dateline")
    g.edge("empty.out", "ui#paper.page2_head")
    g.edge("empty.out", "ui#paper.page2_body")

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


# ---------------------------------------------------------------- stubs

STUB_KINDS = ["warmup", "investigate", "board", "debate", "result"]


def gen_stubs() -> Graph:
    """Step kinds without a flow yet report done at once. To implement a kind, delete its four nodes below."""
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
        g.edge(k + "Gate.changed", "done.in")
    return g


GRAPHS = {"main": gen_main, "dialogue": gen_dialogue, "paper": gen_paper, "stubs": gen_stubs}


def main() -> int:
    check = "--check" in sys.argv[1:]
    stale = []
    for name, fn in GRAPHS.items():
        path = FLOWS / f"{name}.xtflow"
        text = fn().text()
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path.name)
        else:
            path.write_bytes(text.encode("utf-8"))
            print(f"wrote {path.relative_to(ROOT).as_posix()}")
    if stale:
        print("stale: " + ", ".join(stale) + " (run uv run tools/gen_flows.py)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
