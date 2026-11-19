# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Review screenshots of every D01 claim and card label on the debate screen (v2 demo E6, V4): not a pass/fail check.

The routes show only the claims and cards they use, so this writes a scripted gallery instead: a copy of the game
(tests/d1labels_harness, gen_d1_play's route A harness plus one flow, deleted at the end) that, once round 1 of the
dev entry's debate is shown, writes pages straight into ui#d1debate's ports (the debate flow writes its lists only on
its own pulses, and nothing is clicked while the pages run):

- page k (one per claim, 30 claims and the two 抓住他的話 rows, CATCH:U1 / CATCH:U2): the claim picker shows four
  claims from k on (their full titles, two lines in English), the confirm row claim k's full title and card k's full
  title as the target, our chain seven claims from k on and his chain seven cards from k on (short labels);
- then the public record (opened with R): every claim's short label, 14 rows per page.

Each page is shot in zh-TW and en (xtatrium shot) into DIR/labels/<lang>/page_NN.png (record_N.png for the record).

Usage (from the project root):
    uv run tests/shots_d1_labels.py DIR
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(ROOT / "tools"))
import gen_d1_play as gd  # noqa: E402
from gen_debui import add_all  # noqa: E402
from gen_flows import Graph, tref  # noqa: E402
from tempwatch import TempWatch  # noqa: E402
from xt_cli import EXE, XTFRAME, compile_game  # noqa: E402

CH = gd.initial_state(gd.RT.ROUTES["A"].loadout).ch
CLAIMS = list(CH.claims) + [f"CATCH:{c}" for c, cd in CH.cards.items() if cd.kind == "unfav"]
CARDS = list(CH.cards)
HARNESS = TESTS / "d1labels_harness"
PAGE = 20           # ticks per page
REC_ROWS = 14       # public record rows per page (its scroll box shows 14)
KEY_R = 21          # XtKey.R


def cyc(seq: list[str], k: int, n: int) -> list[str]:
    return [seq[(k + i) % len(seq)] for i in range(min(n, len(seq)))]


def pages() -> tuple[list[dict], list[list[str]]]:
    main = [{"claims": cyc(CLAIMS, k, 4), "pchain": cyc(CLAIMS, k, 7), "ochain": cyc(CARDS, k, 7),
             "claim": CLAIMS[k], "card": CARDS[k % len(CARDS)]} for k in range(len(CLAIMS))]
    rec = [CLAIMS[i:i + REC_ROWS] for i in range(0, len(CLAIMS), REC_ROWS)]
    return main, rec


def flow(start: float, main: list[dict], rec: list[list[str]]) -> dict:
    """The gallery flow: one one-shot timer per page, started by the title's dev entry."""
    g = Graph()
    claim_f = {"id": "item", "label": tref("d1uiClaim", "id", "label"), "issue": tref("d1uiClaim", "id", "issue"),
               "kind": tref("lbRow", "id", "kind"), "soph": tref("lbRow", "id", "soph"), "crack": tref("lbRow", "id", "crack"),
               "stand": tref("lbRow", "id", "stand"), "extra": tref("lbRow", "id", "extra"), "ok": tref("lbRow", "id", "ok"),
               "sel": tref("lbRow", "id", "sel")}
    pc_f = {"id": "item", "label": tref("d1uiClaim", "id", "short"), "issue": tref("d1uiClaim", "id", "issue"),
            "crack": tref("lbRow", "id", "ok")}
    oc_f = {"id": "item", "label": tref("d1uiCard", "id", "short"), "issue": tref("d1uiCard", "id", "issue"),
            "sel": tref("lbRow", "id", "sel")}
    rec_f = {"n": tref("lbRow", "id", "n"), "label": tref("d1uiClaim", "id", "short"), "use": tref("lbRow", "id", "use"),
             "soph": tref("lbRow", "id", "kind"), "crack": tref("lbRow", "id", "crack"),
             "state": tref("lbRow", "id", "state")}
    loc = ["label", "issue", "kind", "crack", "stand", "extra"]
    # the confirm row: page k's claim and card (full titles); a counter of the pages picks them
    g.node("pages", "merge")
    g.counter("pageN", initial=0)
    g.edge("pages.out", "pageN.increment")
    ckeys = [""] + [f"CLM_D01_{pg['claim']}" if ":" not in pg["claim"] else "UI_V2_SEIZE" for pg in main]
    kkeys = [""] + [f"CARD_D01_{pg['card']}" for pg in main]
    g.edge(g.text("ct", g.lookup("ck", ckeys, "pageN")), "ui#d1debate.sel_claim_text")
    g.edge(g.text("kt", g.lookup("kk", kkeys, "pageN")), "ui#d1debate.sel_target_text")
    g.x("pon", "pageN > 0")
    g.edge("pon_t", "ui#d1debate.picker_on")
    for k, pg in enumerate(main):
        st, tk = g.timer(f"p{k}", start + k * PAGE / 60)
        g.edge("ui#title.v2dev", st)
        for coll, ids, port, fields, lz in (("lbC", pg["claims"], "claims", claim_f, loc),
                                             ("lbP", pg["pchain"], "pchain", pc_f, ["label", "issue"]),
                                             ("lbO", pg["ochain"], "ochain", oc_f, ["label", "issue"])):
            g.edge(tk, g.eff(f"c{k}{coll}", "atrium.coll.clear", coll))
            g.edge(tk, add_all(g, f"a{k}{coll}", coll, g.k(",".join(ids))))
        # the lists are read back on the next tick: written by a second timer one tick later
        st2, tk2 = g.timer(f"q{k}", start + (k * PAGE + 2) / 60)
        g.edge("ui#title.v2dev", st2)
        for coll, port, fields, lz in (("lbC", "claims", claim_f, loc), ("lbP", "pchain", pc_f, ["label", "issue"]),
                                       ("lbO", "ochain", oc_f, ["label", "issue"])):
            g.edge(tk2, g.ui_list(f"w{k}{coll}", f"ui.d1debate.{port}", coll, fields, localize=lz))
        g.edge(tk2, "pages.in")
    base = start + (len(main) * PAGE + 30) / 60
    for k, ids in enumerate(rec):
        st, tk = g.timer(f"r{k}", base + k * PAGE / 60)
        g.edge("ui#title.v2dev", st)
        g.edge(tk, g.eff(f"rc{k}", "atrium.coll.clear", "lbR"))
        g.edge(tk, add_all(g, f"ra{k}", "lbR", g.k(",".join(ids))))
        st2, tk2 = g.timer(f"s{k}", base + (k * PAGE + 2) / 60)
        g.edge("ui#title.v2dev", st2)
        g.edge(tk2, g.ui_list(f"rw{k}", "ui.d1debate.record", "lbR", rec_f,
                               localize=["label", "use", "soph", "crack", "state"]))
    return json.loads(g.text_out())


def build(start: float, main: list[dict], rec: list[list[str]]) -> None:
    gd.build_harness("A")
    shutil.rmtree(HARNESS, ignore_errors=True)
    shutil.move(str(gd.harness_dir("A")), str(HARNESS))
    rows = [{"id": c, "kind": "UI_V2_CLAIM_SOPH", "soph": 1, "crack": "UI_V2_CLAIM_CRACK", "stand": "UI_V2_CLAIM_ON_CHAIN",
             "extra": "UI_V2_CLAIM_PRIVATE", "ok": 1, "sel": False, "n": "Round 20", "use": "UI_V2_RECORD_REBUT",
             "state": "UI_V2_RECORD_STANDING"} for c in CLAIMS + CARDS]
    (HARNESS / "data" / "flow" / "lbRow.json").write_text(json.dumps(rows, ensure_ascii=False, indent=0) + "\n",
                                                          encoding="utf-8", newline="\n")
    (HARNESS / "flows" / "d1labels.xtflow").write_text(json.dumps(flow(start, main, rec), ensure_ascii=False, indent=1)
                                                       + "\n", encoding="utf-8", newline="\n")
    game = json.loads((HARNESS / "game.json").read_text(encoding="utf-8"))
    game["tables"]["lbRow"] = "data/flow/lbRow.json"
    for c in ("lbC", "lbP", "lbO", "lbR"):
        game["collections"][c] = {"kind": "list", "type": "string", "capacity": 32}
    game["flows"].append("flows/d1labels.xtflow")
    (HARNESS / "game.json").write_text(json.dumps(game, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
                                       newline="\n")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    out = Path(sys.argv[1]) / "labels"
    compile_game()
    tw = TempWatch().__enter__()
    try:
        main_p, rec_p = pages()
        # the recording: the dev entry, S07 L001-L003, the opening skipped, round 1 shown; the pages run on timers
        r = gd.Rec(str(HARNESS.relative_to(ROOT)).replace("\\", "/"))
        r.click("title", gd.TITLE_V2, 40)
        dev = r.t
        r.t += 40
        gd.opening(r)
        start = (r.t + 40 - dev) / 60
        t0 = r.t + 40
        shots = {f"page_{k:02d}": t0 + k * PAGE + 10 for k in range(len(main_p))}
        rbase = t0 + len(main_p) * PAGE + 30
        r.t = rbase - 10
        r.lines.append(json.dumps({"t": r.t, "u": [["d1debate", "kd", KEY_R, 0], ["d1debate", "ku", KEY_R, 0]]}))
        shots.update({f"record_{k}": rbase + k * PAGE + 10 for k in range(len(rec_p))})
        r.write("d1_labels", 0)
        build(start, main_p, rec_p)
        for lang in ("zh-TW", "en"):
            (out / lang).mkdir(parents=True, exist_ok=True)
            tmp = Path(tempfile.mkdtemp(prefix="d1shots-"))
            try:
                p = subprocess.run([str(EXE), "shot", "--game", "tests/d1labels_harness", "--replay",
                                    str(TESTS / "d1_labels.atrec"), "--at", ",".join(str(t) for t in shots.values()),
                                    "--out", str(tmp), "--lang", lang], capture_output=True,
                                   cwd=ROOT, env=dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME))
                if p.returncode != 0:
                    raise SystemExit(f"shot failed: {p.stderr.decode('utf-8', 'replace')}")
                for name, t in shots.items():
                    shutil.copyfile(tmp / f"shot-{t:06d}.png", out / lang / f"{name}.png")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        print(f"labels: {len(main_p)} pages and {len(rec_p)} record pages per language in {out}")
    finally:
        shutil.rmtree(HARNESS, ignore_errors=True)
        (TESTS / "d1_labels.atrec").unlink(missing_ok=True)
    tw.__exit__(None, None, None)
    if tw.leaks:
        print("FAIL temp: left behind: " + ", ".join(tw.leaks))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
