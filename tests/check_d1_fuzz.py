# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""UI fuzz of the v2 demo D01 debate (v2 demo plan §2 decision 3, ticket 5.2; docs/flows.md §4.12, tests/README.md).

The engine does not reject an illegal command (docs/debate-engine-v2.md §4), so the d1debate screen must offer exactly
the legal choices. The scripted UI tests only cover their own routes; this one plays whole debates by clicking at
random among what the screen offers, and checks the screen against the reference model round by round.

How it knows what to click. A recording is replayed tick by tick, so it cannot branch on the screen while it runs.
As tests/gen_d1_play.py's seeded bot does, the reference model is stepped alongside while the recording is written:
Cedric's moves are ref policy.decide on the debate seed the screen draws from the run's rng (check_debate_v2
ui_debate_seed; no d1OppAct pinning, his real AI plays), and before each round ref legal.legal_moves says what the
player may do. The fuzz picks at random among those choices (action, evidence chip, claim row, target chip on his
chain, cover, lock; the endgame's cut / take; §7.5's last card / give up), wanders first (picks other actions,
evidence and claims, toggles cover, clicks greyed-out items and presses keys that must do nothing), and records
after every click what the screen must then show.

What it asserts, reading the port trace afterwards (each failure names the seed, round, tick and item):
- after every click: the enabled set equals ref's legal set, both ways: the action buttons (mode, can_dismantle;
  keys 1-4 and V in rounds where they do nothing), every evidence chip (ev_list = the picker's evidence), every
  claim row's `ok` for the chosen action, the target chips (a click is taken exactly when ref allows that target),
  cover (guard_ok), lock (can_lock, need_target); the selection (act, the chips' and rows' sel, guard_armed) is the
  one the clicks made, and a click on a greyed-out item changed nothing;
- when a round is shown: round, phase and mode, both credibilities, both chains (with cracks), the public record,
  the tell (clear / vague, the two actions, the star, his line, the half sentence);
- every round's playback and the tell's lines step by step (check_d1_play check_steps, check_lines);
- at the end: the result screen's grade, rounds and outcome; a debate that does not end, a round where nothing is
  enabled, a run that stops progressing (a round not shown when the next choice starts) are failures; nothing on
  stderr.

Around the debate, per seed at random: the public record opened and closed (button or R), the settings overlay
opened and closed (F1 / Esc, Esc / Backspace / the dimmed screen), the language switched in it (from round 2 on),
clicks anywhere and on ui#cutin during the playback and its cut-ins.

Usage (from the project root):
    uv run tests/check_d1_fuzz.py                 the default seeds (DEFAULT; between them every situation is reached)
    uv run tests/check_d1_fuzz.py --seeds N       seeds 1..N, loadouts A, B, C, D in turn
    uv run tests/check_d1_fuzz.py --only B:17     one debate (loadout:seed)
    uv run tests/check_d1_fuzz.py --plan N        ref only: the situations seeds 1..N reach per loadout
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS))
import check_d1_m3 as cm  # noqa: E402
import check_d1_play as cd  # noqa: E402
import check_playthrough as cp  # noqa: E402
import gen_d1_play as gd  # noqa: E402
import gen_playthrough as gp  # noqa: E402
from sherefox_ref.v2 import known as K  # noqa: E402
from sherefox_ref.v2 import lines as LN  # noqa: E402
from sherefox_ref.v2 import routes as RT  # noqa: E402
from sherefox_ref.v2.legal import is_legal, legal_moves  # noqa: E402
from sherefox_ref.v2.model import PA, Clarity, PlayerAction, initial_state  # noqa: E402
from sherefox_ref.v2.policy import RngChooser, decide  # noqa: E402
from sherefox_ref.v2.resolve import resolve_round  # noqa: E402
from sherefox_ref.v2.rng import DebateRng  # noqa: E402
from tempwatch import TempWatch  # noqa: E402
from xt_cli import EXE, XTFRAME, compile_game  # noqa: E402

S = cd.S
LOADOUTS = {k: RT.ROUTES[k].loadout for k in "ABCD"}   # B carries the talking board (P1)
# (loadout, seed): the default run, picked with --plan 150 so that between them every situation of SITUATIONS is
# reached (the summary fails a default run that misses one; a change to the planner's draws reshuffles them, so pick
# again with --plan; E8 re-picked them: the greyed-out clicks now include the refuted claims' rows): A9 a Break and his
# last card, A26 / A62 / C91 抓住他的話, A103 a successful 拆台 (a grade 3 win), A111 / B29 a Reverse Break and the §7.5
# round, B8 the dying gasp (a grade 1 win), B39 / C30 / D42 the round limit, and the wins B96 (grade 2), A90 (grade 3),
# C58 (grade 4). Random play loses most debates.
CURATED = [("A", 9), ("A", 26), ("A", 62), ("A", 90), ("A", 103), ("A", 111), ("B", 8), ("B", 29), ("B", 39),
           ("B", 96), ("C", 30), ("C", 58), ("C", 91), ("D", 42)]


def cycle(n: int) -> list[tuple[str, int]]:
    """Seeds 1..n, loadouts A, B, C, D in turn (--seeds n)."""
    return [("ABCD"[(i - 1) % 4], i) for i in range(1, n + 1)]


# the default run: the curated seeds and seeds 1-36 (about a minute with ten debates at a time)
DEFAULT = CURATED + [j for j in cycle(36) if j not in CURATED]
SITUATIONS = ("dismantle", "cover", "cover saved", "catch", "break", "last card", "dying gasp", "last stand",
              "reverse break", "round limit")

ACT = {PA.ARGUE: 1, PA.INTERCEPT: 2, PA.DISMANTLE: 3, PA.STALL: 4, PA.CUT: 5, PA.ACCEPT: 6, PA.LAST_STAND: 7}
KIND = {v: k for k, v in ACT.items()}
CLAIM_ACTS = (1, 2, 3, 5, 7)
UI_ACTS = {0: {1, 2, 4}, 1: {5, 6}, 2: {6, 7}, 3: set()}   # the buttons each mode shows (act 3: can_dismantle)
OPP_CODE = {"attack": 0, "force": 1, "rebut": 2, "parry": 3, "last": 4}   # tell_a / tell_b / tell_star
K_NUM = {1: 30, 2: 31, 3: 32, 4: 33}   # XtKey.Key1..Key4
K_V, K_R, K_ENTER = 25, 21, 40
REC_BTN = (718, 27)                    # D1Debate #btn-record (624..812 x 10..44)
REC_CLOSE = (1000, 90)                 # #rec-close (940..1060 x 74..106)
# Claim rows are clicked at their centre (gd.claim_xy). Until v2 demo E6 the faded floating number #float-me took
# the clicks meant for the fourth row (found by this fuzz in 5.2); the board now gives it pointer-events: none.
CLAIM_X = gd.claim_xy(0)[0]
GAP = (7, 10)                          # ticks between two choosing clicks
OBS = 5                                # a click's effect is read this many ticks later (lists rebuilt on the next beat)
SKIP_GAP = (4, 7)
TAIL = 70                              # after the last playback click: the hold (0.6 s) and the next round's lists
CARD = {r["id"]: r for r in json.loads((ROOT / "data" / "flow" / "d1uiCard.json").read_text(encoding="utf-8"))}
CLAIM = {r["id"]: r for r in json.loads((ROOT / "data" / "flow" / "d1uiClaim.json").read_text(encoding="utf-8"))}


def harness(lo: str) -> str:
    return "." if lo == "A" else f"tests/d1fuzz_harness{lo}"


# ------------------------------------------------------------------------------------------------ the plan (ref)

@dataclass
class Sel:
    """The screen's selection as the clicks made it (flows/d01_debate_ui: act, ev, claim, target, armed)."""
    act: int = 0
    ev: str = ""
    claim: str = ""
    target: str = ""
    armed: bool = False


@dataclass
class Obs:
    t: int
    n: int
    what: str
    s: object
    sel: Sel
    shown: bool = False      # the round was just shown: also the round-level displays
    lang: str = "zh-TW"
    tell: object = None
    record: tuple = ()


class Ref:
    """What ref allows in a state, projected onto the screen's controls."""

    def __init__(self, s) -> None:
        self.s = s
        self.legal = legal_moves(s)
        self.mode = 3 if s.outcome else 2 if s.player_locked else 1 if s.endgame else 0
        self.acts = {ACT[m.kind] for m in self.legal}
        self.picker = gd.picker(s) if not s.outcome else []
        self.evs = [e for e, _ in self.picker]
        # E8: the refuted claims are listed greyed after the others (ref known.void_rows), their evidence chip after
        # the picker's when it has no other claim
        self.void = K.void_rows(s) if not s.outcome else []
        self.chips = self.evs + (cd.e8_void_evs(s) if not s.outcome else [])
        self.chain = [n.card for n in s.opp_chain]
        self.guard = any(m.guard for m in self.legal)

    def claims(self, ev: str) -> list[str]:
        return next((cs for e, cs in self.picker if e == ev), [])

    def rows(self, ev: str) -> list[str]:
        """The claim rows the screen lists for the evidence: the picker's, then its refuted claims (E8)."""
        return self.claims(ev) + [c for c in self.void if ev != "CATCH" and self.s.ch.claims[c].evidence == ev]

    def claim_ok(self, act: int, c: str) -> bool:
        return any(ACT[m.kind] == act and m.claim == c for m in self.legal)

    def target_ok(self, act: int, t: str) -> bool:
        return any(ACT[m.kind] == act and m.target == t for m in self.legal)

    def move(self, sel: Sel) -> PlayerAction | None:
        """The command a lock would send, if ref allows it (guard as armed)."""
        if sel.act not in KIND:
            return None
        kind = KIND[sel.act]
        claim = sel.claim or None if sel.act in CLAIM_ACTS else None
        target = sel.target or None if sel.act in (3, 7) else None
        pa = PlayerAction(kind, claim, target, sel.armed and self.mode == 0)
        return pa if pa in self.legal else None

    def lock_ok(self, sel: Sel) -> bool:
        if sel.act not in KIND:
            return False
        kind = KIND[sel.act]
        claim = sel.claim or None if sel.act in CLAIM_ACTS else None
        target = sel.target or None if sel.act in (3, 7) else None
        if sel.act in CLAIM_ACTS and claim is None:
            return False
        return any(m.kind == kind and m.claim == claim and m.target == target for m in self.legal)


class Rec(gd.Rec):
    def key(self, ui: str, code: int, wait: int) -> None:
        self.t += wait
        self.lines.append(json.dumps({"t": self.t, "u": gp.key(ui, code)}))


@dataclass
class Plan:
    lo: str
    seed: int
    rec: Rec
    lang0: str
    rounds: list = field(default_factory=list)     # (state before, player action, his action) per round
    obs: list = field(default_factory=list)
    langs: list = field(default_factory=list)      # (tick, language) switches
    final: object = None
    situations: set = field(default_factory=set)
    stats: dict = field(default_factory=dict)
    cutin_clicks: list = field(default_factory=list)
    rec_rows: list = field(default_factory=list)   # (round, argue, soph, red crack, claim): the public record

    def lang_at(self, t: int) -> str:
        lang = self.lang0
        for tt, lg in self.langs:
            if tt <= t:
                lang = lg
        return lang


def situations(s, pa, ev: list, s2) -> set[str]:
    out = set()
    kinds = [e["kind"] for e in ev]
    if any(e["kind"] == "dismantle" and e.get("ok") for e in ev):
        out.add("dismantle")
    if pa.guard:
        out.add("cover")
    if "guard_saved" in kinds:
        out.add("cover saved")
    if pa.kind == PA.ARGUE and K.is_catch(pa.claim):
        out.add("catch")
    if "ronpa" in kinds:
        out.add("break")
    if s.endgame and not s.endgame.get("dying"):
        out.add("last card")
    if s.endgame and s.endgame.get("dying"):
        out.add("dying gasp")
    if s.player_locked:
        out.add("last stand")
    if "reverse_ronpa" in kinds:
        out.add("reverse break")
    if s2.end_reason == "round_limit":
        out.add("round limit")
    return out


def plan(lo: str, seed: int) -> Plan:
    """Write the recording of one fuzz debate (loadout `lo`, run seed `seed`) and what the screen must show."""
    py = random.Random(seed * 1009 + ord(lo))
    rec = Rec(harness(lo), seed)
    p = Plan(lo, seed, rec, py.choice(["zh-TW", "en"]))
    p.stats = {"probes": 0, "keys": 0, "record": 0, "settings": 0, "lang": 0, "clicks": 0}
    lang = p.lang0
    chooser = RngChooser(DebateRng(gd.CV.ui_debate_seed(seed)))
    s = initial_state(replace(LOADOUTS[lo], warmup="pass_clean"))
    memo = LN.Memo()
    rec.click("title", gd.TITLE_V2, 40)
    rec.t += 40
    gd.opening(rec)
    n = 0
    while not s.outcome:
        n += 1
        if n > 20:
            raise SystemExit(f"plan {lo}:{seed}: ref did not end by round 20")
        d = decide(s, chooser)
        r = Ref(s)
        if not r.legal:
            raise SystemExit(f"plan {lo}:{seed} R{n}: ref has no legal move")
        sel = Sel()

        def observe(what: str, shown: bool = False) -> None:
            p.obs.append(Obs(rec.t + OBS, n, what, s, replace(sel), shown, p.lang_at(rec.t + OBS), d.tell,
                             tuple(p.rec_rows)))

        def wait() -> int:
            return py.randint(*GAP)

        rec.t += 2
        observe("round shown", True)
        rec.t += 6

        # -- the surroundings: the public record, the settings overlay (and the language in it)
        if py.random() < 0.3:
            p.stats["record"] += 1
            if py.random() < 0.5:
                rec.click("d1debate", REC_BTN, wait())
            else:
                rec.key("d1debate", K_R, wait())
            rec.t += 20
            how = py.randrange(3)
            if how == 0:
                rec.click("d1debate", REC_CLOSE, wait())
            elif how == 1:
                rec.click("d1debate", REC_BTN, wait())
            else:
                rec.key("d1debate", K_R, wait())
            rec.t += 10
            observe("public record closed")
        if py.random() < 0.25:
            p.stats["settings"] += 1
            rec.key("d1debate", py.choice([gp.KEY_F1, gp.KEY_ESC]), wait())
            rec.t += gp.SETTLE
            if n > 1 and py.random() < 0.6:
                p.stats["lang"] += 1
                lang = "en" if lang == "zh-TW" else "zh-TW"
                rec.click("settings", gp.SET_LANG[1 if lang == "en" else 0], 0)
                p.langs.append((rec.t, lang))
                rec.t += gp.GAP
            how = py.randrange(3)
            if how == 0:
                rec.key("settings", gp.KEY_ESC, wait())
            elif how == 1:
                rec.key("settings", gp.KEY_BACKSPACE, wait())
            else:
                rec.click("settings", gp.SET_SCRIM, wait())
            rec.t += gp.SETTLE
            observe("settings closed")

        # -- the controls
        def do_act(a: int, key: bool = False) -> None:
            ok = a in r.acts
            if key:
                p.stats["keys"] += 1
                rec.key("d1debate", K_NUM[a], wait())
            else:
                rec.click("d1debate", gd.ACT_XY[a], wait())
            if ok:
                sel.act, sel.claim, sel.target = a, "", ""
                if not sel.ev and r.evs:
                    sel.ev = r.evs[0]
            observe(f"{'key' if key else 'click'} act {a}" + ("" if ok else " (greyed out)"))

        def do_ev(e: str) -> None:
            rec.click("d1debate", gd.ev_xy(r.evs.index(e)), wait())
            sel.ev, sel.claim = e, ""
            observe(f"evidence {e}")

        def do_claim(c: str) -> None:
            rec.click("d1debate", (CLAIM_X, gd.claim_xy(r.rows(sel.ev).index(c))[1]), wait())
            ok = sel.act in CLAIM_ACTS and r.claim_ok(sel.act, c)
            if ok:
                sel.claim = c
            observe(f"claim {c}" + ("" if ok else " (greyed out)"))

        def do_target(t: str) -> None:
            rec.click("d1debate", gd.chain_xy(r.chain.index(t)), wait())
            ok = sel.act in (3, 7) and r.target_ok(sel.act, t)
            if ok:
                sel.target = t
            observe(f"target {t}" + ("" if ok else " (greyed out)"))

        def do_guard(key: bool = False) -> None:
            if key:
                p.stats["keys"] += 1
                rec.key("d1debate", K_V, wait())
            else:
                rec.click("d1debate", gd.GUARD_XY, wait())
            if r.guard:
                sel.armed = not sel.armed
            observe(f"{'key V' if key else 'cover'}" + ("" if r.guard else " (greyed out)"))

        def offered() -> list:
            """What the screen offers now (ref's legal set projected on the controls), as callables."""
            out = [lambda a=a: do_act(a) for a in sorted(r.acts)]
            if sel.act in CLAIM_ACTS:      # the picker is shown only for an action that takes a claim
                out += [lambda e=e: do_ev(e) for e in r.evs]
                out += [lambda c=c: do_claim(c) for c in r.claims(sel.ev) if r.claim_ok(sel.act, c)]
            if sel.act in (3, 7):
                out += [lambda t=t: do_target(t) for t in r.chain if r.target_ok(sel.act, t)]
            if r.guard:
                out.append(do_guard)
            return out

        def greyed() -> list:
            """Greyed-out items and keys that must do nothing now."""
            out = []
            if r.mode == 0 and 3 not in r.acts:
                out.append(lambda: do_act(3))
            if r.mode in (1, 2):
                out += [lambda a=a: do_act(a, key=True) for a in (1, 2, 3, 4)]
                out.append(lambda: do_guard(key=True))
            if sel.act in CLAIM_ACTS:
                out += [lambda c=c: do_claim(c) for c in r.rows(sel.ev) if not r.claim_ok(sel.act, c)]
            if sel.act not in (3, 7) and r.chain:
                out += [lambda t=t: do_target(t) for t in r.chain]
            if r.mode == 0 and not r.guard:
                out.append(do_guard)
            if not r.lock_ok(sel):
                out.append(lambda: lock(probe=True))
            return out

        locked = []

        def lock(probe: bool = False) -> None:
            ok = r.lock_ok(sel)
            if probe and py.random() < 0.5:
                p.stats["keys"] += 1
                rec.key("d1debate", K_ENTER, wait())
            else:
                rec.click("d1debate", gd.LOCK_XY, wait())
            if ok:
                locked.append(r.move(sel))
            else:
                observe("lock (greyed out)")

        for _ in range(py.randint(0, 5)):          # wander
            if py.random() < 0.25 and greyed():
                p.stats["probes"] += 1
                py.choice(greyed())()
            else:
                py.choice(offered())()
            if locked:
                break
        if not locked:                              # commit: a random legal move, clicked from where we are
            a = py.choice(sorted(r.acts))
            if a == 4 and py.random() < 0.5:
                do_act(a, key=True)
            elif sel.act != a or py.random() < 0.2 or (a == 7 and sel.target and py.random() < 0.5):
                do_act(a)
            if a in CLAIM_ACTS:
                evs = [e for e in r.evs if any(r.claim_ok(a, c) for c in r.claims(e))]
                e = py.choice(evs)
                if sel.ev != e:
                    do_ev(e)
                c = py.choice([c for c in r.claims(e) if r.claim_ok(a, c)])
                if sel.claim != c:
                    do_claim(c)
                if a in (3, 7):
                    ts = [m.target for m in r.legal if ACT[m.kind] == a and m.claim == c]
                    t = py.choice(ts)
                    if t is not None and sel.target != t:
                        do_target(t)
            if r.guard and sel.armed != (py.random() < 0.3):
                do_guard()
            lock()
        pa = locked[0]
        if pa is None or not is_legal(s, pa):
            raise SystemExit(f"plan {lo}:{seed} R{n}: the planned lock {pa} is not legal")
        rec.marks[f"chosen{n}"] = rec.t - 2
        rec.marks[f"lock{n}"] = rec.t
        if pa.claim is not None:
            v = K.view(s, pa.claim)
            p.rec_rows.append((n, pa.kind == PA.ARGUE, v.soph, v.red_crack, pa.claim))
        oa = d.action
        s2, ev = resolve_round(s, pa, oa)
        p.rounds.append((s, pa, oa))
        p.situations |= situations(s, pa, ev, s2)
        LN.tell_lines(s, d.tell, memo)
        steps = LN.round_steps(s, pa, oa, ev, s2, memo)
        # -- the playback: a click per step (anywhere for the first half: the whole screen skips; then where nothing
        # is while choosing), a few on ui#cutin, a margin
        nclick = len(steps) + 8
        rec.t += 5
        for k in range(nclick):
            xy = (py.randint(20, 1260), py.randint(60, 700)) if k < len(steps) // 2 else gd.SKIP_XY
            rec.click("d1debate", xy, py.randint(*SKIP_GAP))
            if py.random() < 0.25:
                rec.click("cutin", gd.SKIP_XY, 1)
                p.cutin_clicks.append(rec.t)
        rec.t += TAIL
        s = s2
    p.final = s
    rec.marks["end"] = rec.t
    gd.outro(rec, s.outcome)
    gd.epilogue(rec, s, back=False)
    rec.marks["stop"] = rec.t + 60
    return p


def make_plan(lo: str, seed: int) -> Plan:
    pl = plan(lo, seed)
    pl.stats["clicks"] = len(pl.rec.lines) - 2   # the header and the opening's skip (gen_playthrough.OP_SKIP)
    return pl


# ------------------------------------------------------------------------------------------------ the checks


def num(v: float) -> float:
    import math
    return math.floor(max(0.0, v) * 100 + 0.5) / 100


def short_key(c: str) -> str:
    """The short label a chain node / record row shows (E6 V4); a 抓住他的話 node shows the caught U card's short label
    (E7, design ruling: CARD_D01_U1_SHORT / U2_SHORT), never UI_V2_SEIZE."""
    return f"CARD_D01_{c.split(':', 1)[1]}_SHORT" if K.is_catch(c) else f"CLM_D01_{c}_SHORT"


def label_key(c: str) -> str:
    """The full title a claim row shows; UI_V2_SEIZE stays the name of the 抓住他的話 row in the picker (E7)."""
    return "UI_V2_SEIZE" if K.is_catch(c) else f"CLM_D01_{c}"


def b(v) -> bool:
    return bool(v) and v != "false"


def check_obs(at, o: Obs, lo: str, seed: int) -> list[str]:
    r = Ref(o.s)
    sel = o.sel
    L = S[o.lang]
    head = f"seed {seed} [{lo}] R{o.n} t={o.t} after {o.what}"
    bad = []

    def get(port):
        return at.get(o.t, f"d1debate.{port}")

    def eq(port, want, got=None):
        g = get(port) if got is None else got
        if isinstance(want, bool):
            g = b(g)
        elif isinstance(want, (int, float)) and isinstance(g, (int, float)):
            if abs(g - want) <= 0.0051:
                return
        if g != want:
            bad.append(f"{head}: {port} = {g!r}, ref {want!r}")

    eq("phase", 0.0)
    if get("phase") != 0.0:
        bad.append(f"{head}: the round is not being chosen (phase {get('phase')!r}): the screen stopped progressing")
        return bad
    eq("mode", float(r.mode))
    eq("act", float(sel.act))
    # the action buttons: the mode's buttons, 拆台 as can_dismantle
    ui_acts = set(UI_ACTS.get(int(get("mode") or 0), set()))
    if int(get("mode") or 0) == 0 and b(get("can_dismantle")):
        ui_acts.add(3)
    for a in sorted(ui_acts - r.acts):
        bad.append(f"{head}: the screen offers action {a} ({KIND[a].value}), ref says it is illegal")
    for a in sorted(r.acts - ui_acts):
        bad.append(f"{head}: the screen greys out action {a} ({KIND[a].value}), ref says it is legal")
    if not ui_acts:
        bad.append(f"{head}: nothing is enabled")
    eq("guard_ok", r.guard)
    eq("guard_armed", sel.armed and r.mode == 0)
    eq("can_lock", r.lock_ok(sel))
    eq("need_target", sel.act == 3 and not sel.target)
    eq("picker_on", sel.act in CLAIM_ACTS)
    # evidence chips: the picker's evidence, in its order; the chosen one
    evs = get("ev_list") or []
    got = [(e["id"], b(e["sel"])) for e in evs]
    want = [(e, e == sel.ev) for e in r.chips]
    if got != want:
        extra = [e for e, _ in got if e not in r.chips]
        miss = [e for e in r.chips if e not in [x for x, _ in got]]
        bad.append(f"{head}: evidence chips {got} (ref {want}; offered but not in ref: {extra}, missing: {miss})")
    # claim rows of the chosen evidence: ok = the chosen action may use it
    rows = get("claims") or [] if sel.ev else []
    cs = r.rows(sel.ev) if sel.ev else []
    got_ids = [c["id"] for c in rows]
    if got_ids != cs:
        bad.append(f"{head}: claim rows of {sel.ev or '-'}: {got_ids} (ref {cs})")
    else:
        for c in rows:
            want_ok = sel.act in CLAIM_ACTS and r.claim_ok(sel.act, c["id"])
            if b(c["ok"]) != want_ok:
                what = "offers" if b(c["ok"]) else "greys out"
                bad.append(f"{head}: the screen {what} claim {c['id']} for action {sel.act}, ref says it is "
                           f"{'legal' if want_ok else 'illegal'}")
            if b(c["sel"]) != (c["id"] == sel.claim):
                bad.append(f"{head}: claim {c['id']} sel {c['sel']!r} (chosen {sel.claim or '-'})")
            if c["label"] != L[label_key(c["id"])]:    # E6 (V4): the picker shows the full title
                bad.append(f"{head}: claim {c['id']} label {c['label']!r} (want the full title)")
            view = K.view(o.s, c["id"])
            if b(c["soph"]) != view.soph:
                bad.append(f"{head}: claim {c['id']} soph {c['soph']!r}, ref {view.soph}")
            if c.get("note") != cd.e8_note(o.lang, o.s, c["id"]):     # E8: restated / void, every row
                bad.append(f"{head}: claim {c['id']} tag {c.get('note')!r}, ref {cd.e8_note(o.lang, o.s, c['id'])!r}")
    # E8: the preview, the red crack's cost and the description of the choice (no pointer moves: nothing hovered)
    claim = sel.claim if sel.act in CLAIM_ACTS else ""
    eq("preview_text", cd.e8_preview(o.lang, o.s, sel.act, claim))
    eq("crack_cost_text", cd.e8_crack(o.lang, o.s, sel.act, claim))
    eq("desc_text", cd.e8_desc(o.lang, o.s, sel.act, claim, sel.armed and r.mode == 0))
    # his chain (target chips) with the chosen target
    oc = get("ochain") or []
    got = [(x["id"], b(x["sel"]), x["label"]) for x in oc]
    # E6 (V4): chain nodes show the short label (CARD_D01_<card>_SHORT)
    want = [(t, t == sel.target, L[CARD[t]["short"]]) for t in r.chain]
    if got != want:
        bad.append(f"{head}: his chain {got} (ref {want})")
    if o.shown:
        bad += check_shown(at, o, r, head, L)
    return bad


def check_shown(at, o: Obs, r: Ref, head: str, L: dict) -> list[str]:
    s = o.s
    bad = []

    def get(port):
        return at.get(o.t, f"d1debate.{port}")

    def eq(port, want):
        g = get(port)
        if isinstance(want, bool):
            g = b(g)
        if isinstance(want, float) and isinstance(g, float) and abs(g - want) <= 0.0051:
            return
        if g != want:
            bad.append(f"{head}: {port} = {g!r}, ref {want!r}")

    eq("round_text", L["UI_V2_ROUND"].replace("{n}", str(s.round)).replace("{max}", str(s.ch.max_rounds)))
    eq("hp_me", num(s.player_hp))
    eq("hp_opp", num(s.opp_hp))
    eq("hp_me_max", float(s.ch.player_max_hp))
    eq("hp_opp_max", float(s.ch.opp_max_hp))
    pc = [(x["id"], b(x["crack"]), x["label"]) for x in (get("pchain") or [])]
    want = [(nd.claim, nd.cracked, L[short_key(nd.claim)]) for nd in s.player_chain]
    if pc != want:
        bad.append(f"{head}: our chain {pc} (ref {want})")
    rec = get("record") or []
    want = [(L["UI_DEB_ROUND"].replace("{n}", str(rn)), "" if argue else L["UI_V2_RECORD_REBUT"],
             L["UI_V2_CLAIM_SOPH"] if soph else "", L["UI_V2_LINK_CRACKED"] if crk else "",
             "" if not argue or K.is_catch(c) else
             L["UI_V2_RECORD_STANDING"] if c in s.chain_claims() else L["UI_V2_RECORD_DOWN"],
             L[short_key(c)])      # E6 (V4): the short label; E7: a catch shows the U card's
            for rn, argue, soph, crk, c in o.record]
    got = [(x["n"], x["use"], x["soph"], x["crack"], x["state"], x["label"]) for x in rec]
    if got != want:
        bad.append(f"{head}: public record {got} (ref {want})")
    eq("tell_on", r.mode in (0, 1))
    t = o.tell
    if t is not None and r.mode in (0, 1):
        clear = t.clarity == Clarity.CLEAR
        eq("tell_clear", clear)
        eq("tell_a", float(OPP_CODE[t.shown[0].value]))
        eq("tell_b", -1.0 if clear else float(OPP_CODE[t.shown[1].value]))
        eq("tell_star", -1.0 if t.star is None else 0.0 if t.star == t.shown[0] else 1.0)
        eq("tell_partial", bool(t.partial))
        key = (CARD[t.card]["tell"] if t.partial else CARD[t.card]["label"]) if t.card else ""
        eq("tell_card", L[key] if key else "")
    eq("tell_possible", cd.e8_tell(o.lang, s, t) if r.mode in (0, 1) else "")    # E8
    for port, want in cd.e8_round(o.lang, s).items():                            # E8: cover count, record cracks
        eq(port, want)
    return bad


def run(pl: Plan, rec_path: Path) -> tuple[list, str, float]:
    t0 = time.monotonic()
    args = [str(EXE), "run", "--game", harness(pl.lo), "--replay", str(rec_path), "--ticks", str(pl.rec.marks["stop"]),
            "--ports", "--lang", pl.lang0]
    env = dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME)
    p = subprocess.run(args, capture_output=True, env=env, cwd=ROOT)
    out = p.stdout.decode("utf-8").replace("\r\n", "\n")
    err = p.stderr.decode("utf-8").replace("\r\n", "\n")
    if p.returncode != 0:
        raise SystemExit(f"error: xtatrium run {rec_path.name} exited {p.returncode}\n{err}")
    return cp.parse_events(out), err, time.monotonic() - t0


def check(pl: Plan, events: list, err: str) -> list[str]:
    tr = cp.Trace(events)
    at = cm.At(tr, events)
    lo, seed = pl.lo, pl.seed
    bad = []
    for o in pl.obs:
        bad += check_obs(at, o, lo, seed)
        if len(bad) > 40:
            break
    marks = pl.rec.marks

    def lang_of(n: int) -> str:
        return pl.lang_at(marks[f"lock{n}"])
    dseed = gd.CV.ui_debate_seed(seed)
    bad += [f"seed {seed} [{lo}] {x}" for x in cd.check_steps(tr, pl.rounds, marks, lang_of, dseed, marks["end"])]
    bad += [f"seed {seed} [{lo}] {x}" for x in cd.check_lines(tr, pl.rounds, marks, lang_of, marks["end"])]
    s = pl.final
    L = S[pl.lang_at(marks["over"])]
    nrounds = s.round - 1
    for port, want in (("d1result.grade_text", L[f"UI_V2_GRADE_{s.grade}"]),
                       ("d1result.rounds_text", L["UI_V2_RESULT_ROUNDS"].replace("{n}", str(nrounds))),
                       ("d1result.win", 1.0 if s.outcome == "win" else 0.0)):
        if at.get(marks["over"], port) != want:
            bad.append(f"seed {seed} [{lo}] result: {port} = {at.get(marks['over'], port)!r}, ref {want!r}")
    noise = [ln for ln in err.split("\n") if ln.strip() and not ln.startswith("render: off")]
    if noise:
        bad.append(f"seed {seed} [{lo}] stderr: " + " | ".join(noise[:5]))
    # clicks on ui#cutin while a cut-in played
    bigs = [t for t, p, v, c in tr.ticks if "cutin.big_seq" in c or "cutin.stamp_seq" in c]
    pl.stats["cutin hits"] = sum(1 for c in pl.cutin_clicks if any(bt <= c < bt + 96 for bt in bigs))
    return bad


def run_all(plans: list, paths: list, workers: int) -> list:
    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(run, plans, paths))


def plan_report(n: int) -> int:
    for lo in "ABCD":
        for seed in range(1, n + 1):
            pl = plan(lo, seed)
            s = pl.final
            print(f"{lo}:{seed:<4} {s.round - 1:>2} rounds grade {s.grade} {s.outcome:<4} "
                  f"{', '.join(x for x in SITUATIONS if x in pl.situations)}")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if "--plan" in argv:
        return plan_report(int(argv[argv.index("--plan") + 1]))
    if "--only" in argv:
        lo, sd = argv[argv.index("--only") + 1].split(":")
        jobs = [(lo, int(sd))]
    elif "--seeds" in argv:
        jobs = cycle(int(argv[argv.index("--seeds") + 1]))
    else:
        jobs = list(DEFAULT)
    t_start = time.monotonic()
    compile_game()
    tw = TempWatch().__enter__()
    fails: list[str] = []
    reached: dict[str, int] = {x: 0 for x in SITUATIONS}
    total_rounds = 0
    stats: dict[str, int] = {}
    try:
        for lo in sorted({lo for lo, _ in jobs} - {"A"}):
            gd.build_harness(lo, RT.Route(lo, LOADOUTS[lo], ()), out=ROOT / harness(lo), pin=False)
        plans = [make_plan(lo, sd) for lo, sd in jobs]
        paths = []
        for pl in plans:
            path = tw.dir / f"fuzz_{pl.lo}{pl.seed}.atrec"
            path.write_text("\n".join(pl.rec.lines) + "\n", encoding="utf-8", newline="\n")
            paths.append(path)
        workers = max(1, min(len(plans), (os.cpu_count() or 2) // 2, 10))
        old_cp = None
        if os.name == "nt":   # .NET writes redirected output in the console code page: UTF-8 for the children
            import ctypes
            old_cp = ctypes.windll.kernel32.GetConsoleOutputCP()
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        try:
            results = run_all(plans, paths, workers)
        finally:
            if old_cp:
                ctypes.windll.kernel32.SetConsoleOutputCP(old_cp)
        for pl, (events, err, secs) in zip(plans, results):
            bad = check(pl, events, err)
            s = pl.final
            total_rounds += s.round - 1
            for x in pl.situations:
                reached[x] += 1
            for k, v in pl.stats.items():
                stats[k] = stats.get(k, 0) + v
            line = (f"seed {pl.seed} [{pl.lo}] {pl.lang0}: {s.round - 1} rounds, grade {s.grade} {s.outcome}; "
                    f"{', '.join(x for x in SITUATIONS if x in pl.situations) or '-'} ({secs:.1f} s)")
            if bad:
                fails.append(f"{pl.lo}:{pl.seed}")
                print(f"FAIL {line}\n  " + "\n  ".join(bad[:30]))
            else:
                print(f"PASS {line}")
        for path in paths:
            path.unlink(missing_ok=True)
    finally:
        for lo in "BCD":
            shutil.rmtree(ROOT / harness(lo), ignore_errors=True)
    print(f"{len(plans)} debates, {total_rounds} rounds; situations: "
          + ", ".join(f"{x} {reached[x]}" for x in SITUATIONS))
    print("around them: " + ", ".join(f"{k} {v}" for k, v in stats.items()))
    missing = [x for x in SITUATIONS if not reached[x]]
    if missing and jobs == DEFAULT:
        fails.append("coverage")
        print(f"FAIL coverage: never reached: {', '.join(missing)}")
    tw.__exit__(None, None, None)
    if tw.leaks:
        fails.append("temp")
        print("FAIL temp: left behind: " + ", ".join(tw.leaks))
    print(f"time {time.monotonic() - t_start:.0f} s")
    print("ok" if not fails else f"FAILED: {', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
