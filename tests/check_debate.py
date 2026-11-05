# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Golden check of the debate engine (flows/debate_engine.xtflow, flows/debate_warmup.xtflow) against the reference
model ref/ (docs/debate-engine.md §6).

Usage (from the project root):
    uv run tests/check_debate.py [--route NAME ...] [--keep] [--verbose]

1. regenerates the engine (tools/gen_debate.py),
2. replays every route of tests/debate_routes.py through ref/ (expected state and event records after each round),
3. writes the harness project tests/debate_harness/ (engine flows and tables copied in, a driver flow and the input
   tables generated) and runs it headless once (`xtatrium run --game tests/debate_harness --ticks N --dump F`),
4. compares, per route and round: round, HP pair, the board nodes in order, shaken, tail, tail rounds, voids, 破竹,
   困獸, 失守, intercepts, contradictions, infamy, assists, over, outcome, break label, golden clue, fragile count,
   and the round's event records (exact, in order); warmup routes: round, index, mistakes, over, auto, trust, reward
   and records. Prints PASS / FAIL per route with the first diverging round and field.

Environment: XTATRIUM (default E:/coding4/XTArtrium; its Release build of src/XTAtrium.Headless is used),
XTATRIUM_XTFRAME_DIR (default <XTATRIUM>/artifacts/xtframe). Exit code 0 when every route passes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import gen_debate as G  # noqa: E402
import debate_routes as R  # noqa: E402

XTATRIUM = Path(os.environ.get("XTATRIUM", "E:/coding4/XTArtrium"))
XTFRAME = os.environ.get("XTATRIUM_XTFRAME_DIR", str(XTATRIUM / "artifacts" / "xtframe"))
EXE = XTATRIUM / "src" / "XTAtrium.Headless" / "bin" / "Release" / "net10.0" / (
    "xtatrium.exe" if os.name == "nt" else "xtatrium")
HARNESS = ROOT / "tests" / "debate_harness"
MAIN_FIELDS = ["debRound", "debPlayerHp", "debOppHp", "nodes", "debShaken", "debInTail", "debTailLeft", "debVoids",
               "debHachiku", "debKonju", "debShisshu", "debParries", "debContra", "debInfamy", "debAssist", "debOver",
               "debOutcome", "debBreakLabel", "debGoldenUsed", "debFragile"]
WARM_FIELDS = ["dwRound", "dwIndex", "dwMistakes", "dwOver", "dwAuto", "dwTrustDelta", "dwReward"]


def run_harness(ticks: int, keep: bool) -> tuple[dict, float, str]:
    env = dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME)
    with tempfile.TemporaryDirectory() as tmp:
        dump = Path(tmp) / "dump.json"
        t0 = time.perf_counter()
        p = subprocess.run([str(EXE), "run", "--game", str(HARNESS), "--ticks", str(ticks), "--dump", str(dump)],
                           capture_output=True, text=True, encoding="utf-8", env=env)
        dt = time.perf_counter() - t0
        if p.returncode != 0 or not dump.exists():
            print(p.stdout + p.stderr)
            raise SystemExit(f"FAIL harness run (exit {p.returncode})")
        data = json.loads(dump.read_text(encoding="utf-8"))
        if keep:
            (HARNESS / "out").mkdir(exist_ok=True)
            (HARNESS / "out" / "dump.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data["collections"], dt, p.stderr


def engine_snapshot(colls: dict, row: int) -> dict:
    num = {e["key"]: e["value"] for e in colls["hNum"]["entries"] if e["key"].startswith(f"{row}:")}
    txt = {e["key"]: e["value"] for e in colls["hStr"]["entries"] if e["key"].startswith(f"{row}:")}
    out = {k.split(":", 1)[1]: v for k, v in num.items()}
    out.update({k.split(":", 1)[1]: v for k, v in txt.items()})
    out["nodes"] = [out[f"on{k}"] for k in range(G.SNAP_ON) if out.get(f"on{k}")]
    return out


def engine_events(colls: dict) -> dict[int, list[str]]:
    by_row: dict[int, list[str]] = {}
    for item in colls["hEv"]["items"]:
        row, rec = item.split("#", 1)
        by_row.setdefault(int(row), []).append(rec)
    return by_row


def compare(exp, colls, events, verbose: bool) -> str | None:
    fields = WARM_FIELDS if exp.route.warmup else MAIN_FIELDS
    got0 = engine_snapshot(colls, exp.start_row)
    for f in fields:
        if f in exp.start and got0.get(f) != exp.start[f]:
            return f"start: {f} expected {exp.start[f]!r}, got {got0.get(f)!r}"
    for row, want, want_ev in exp.extra:
        got = engine_snapshot(colls, row)
        for f, v in want.items():
            if got.get(f) != v:
                return f"instinct (row {row}): {f} expected {v!r}, got {got.get(f)!r}"
        if events.get(row, []) != want_ev:
            return f"instinct (row {row}): records expected {want_ev!r}, got {events.get(row, [])!r}"
    for i, (row, want, want_ev) in enumerate(zip(exp.rows, exp.after, exp.events), start=1):
        got = engine_snapshot(colls, row + 0)
        for f in fields:
            if got.get(f) != want[f]:
                return f"round {i}: {f} expected {want[f]!r}, got {got.get(f)!r}"
        got_ev = events.get(row, [])
        if got_ev != want_ev:
            for k in range(max(len(got_ev), len(want_ev))):
                a = want_ev[k] if k < len(want_ev) else "<none>"
                b = got_ev[k] if k < len(got_ev) else "<none>"
                if a != b:
                    detail = f"round {i}: event {k + 1} expected {a!r}, got {b!r}"
                    if verbose:
                        detail += "\n      expected " + json.dumps(want_ev) + "\n      got      " + json.dumps(got_ev)
                    return detail
    return None


def main(argv: list[str]) -> int:
    keep = "--keep" in argv
    verbose = "--verbose" in argv
    names = [argv[i + 1] for i, a in enumerate(argv) if a == "--route" and i + 1 < len(argv)]
    routes = [r for r in R.ROUTES if not names or r.name in names]
    if not routes:
        print("no such route")
        return 1

    t0 = time.perf_counter()
    for path, text in G.outputs().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    h_in, script, expects = R.build(routes)
    ticks = G.build_harness(HARNESS, h_in, script)
    t_gen = time.perf_counter() - t0
    colls, t_run, stderr = run_harness(ticks, keep)
    events = engine_events(colls)

    stats = G.graph_stats()
    print(f"engine: {', '.join(f'{n} {a} nodes / {b} edges' for n, (a, b) in stats.items())}")
    print(f"harness: {len(h_in)} driver rows, {ticks} ticks; generate {t_gen:.2f} s, compile + run {t_run:.2f} s")
    if stderr.strip():
        print("stderr:\n" + stderr.strip())
    failed = 0
    bad = R.case_param_mismatches()
    if bad:
        failed += 1
        print("FAIL case parameters (data/debate/debCase.json vs ref fixtures): " + "; ".join(bad))
    else:
        print("PASS case parameters (data/debate/debCase.json == ref fixtures)")
    for exp in expects:
        err = compare(exp, colls, events, verbose)
        rounds = len(exp.rows)
        if err:
            failed += 1
            print(f"FAIL {exp.route.name} ({rounds} rounds; {exp.route.source}): {err}")
        else:
            print(f"PASS {exp.route.name} ({rounds} rounds)")
    route_fails = failed - (1 if bad else 0)
    print(f"{len(expects) - route_fails}/{len(expects)} routes pass")
    if stderr.strip():
        print("FAIL stderr not empty")
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
