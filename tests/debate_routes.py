"""Debate routes for the engine harness (tests/check_debate.py): every 推薦路線 / 常見失誤 / variant of the ref tests
(ref/tests/test_ch1_route.py, test_ch2_route.py, test_ch3_route.py, the warmup tests and the A-7 / B8 / B9 rule tests
of test_warmup_and_rules.py), replayed through the reference model (ref/, the oracle) to get the expected state and
event records after every round, and turned into the harness input tables (hIn, debScript).

Only the standard library and ref/src are used (ref is read-only).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ref" / "src"))

from sherefox_ref import events as E  # noqa: E402
from sherefox_ref.fixtures import (  # noqa: E402
    ch1_board, ch1_case, ch2_board, ch2_case, ch3_board, ch3_board_no_g01, ch3_case, ch3_warmup, data_node_id,
)
from sherefox_ref.model import OA, PA, Board, Clarity, OpponentAction, PlayerAction, initial_state  # noqa: E402
from sherefox_ref.policy import Tell, use_fox_instinct  # noqa: E402
from sherefox_ref.resolve import resolve_round  # noqa: E402
from sherefox_ref.rules import SOLID_LINK, SOPH_LINK, link_kind  # noqa: E402
from sherefox_ref.warmup import resolve_warmup_round  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
import gen_debate as G  # noqa: E402

PA_NAME = {PA.SOLID: "solid", PA.SOPHISTRY: "sophistry", PA.PARRY: "rebut", PA.OBSERVE: "observe"}
OA_NAME = {OA.CLAIM: "assert", OA.RUSH: "rush", OA.REINFORCE: "reinforce", OA.TRAP: "trap", OA.ALL_IN: "scorched"}
CASE_ID = {1: "CH01_MAIN", 2: "CH02_MAIN", 3: "CH03_MAIN"}
SHAKEN = {"none": 0, "armed": 1, "held": 2}
OUTCOME = {None: "", "win": "win", "loss": "loss", "unachieved": "unachieved"}
STATUS = {"shissu": "shisshu"}
# ref DebateState field -> debState key, for the start-state overrides of some tests
OVERRIDE_KEY = {"hachiku": "hk", "shaken": "sh", "opp_hp": "ohp"}


def pa(kind, card=None, segment=(), target=None, assist=False):
    return PlayerAction(kind, segment=tuple(segment), target=target, card=card, assist=assist)


def oa(kind, lit=None, scripted=False):
    return OpponentAction(kind, lit, scripted)


def g6(v) -> str:
    return "%.6g" % v


@dataclass
class Route:
    name: str
    source: str  # the ref test it mirrors
    chapter: int
    case_fn: object = None
    board: Board | None = None
    moves: list = field(default_factory=list)
    overrides: dict = field(default_factory=dict)  # ref field -> value, applied to the initial state
    warmup: list = field(default_factory=list)  # warmup: list of card tuples (single card or a chain)
    fox: dict = field(default_factory=dict)  # round -> the fuzzy tell (shown pair) on which 狐耳直覺 is used


# ------------------------------------------------------------------------------------------------- the routes

CH1 = [
    (pa(PA.PARRY, "E01_06"), oa(OA.CLAIM, "N1")),
    (pa(PA.SOLID, segment=("E01_01", "E01_04"), target="N2"), oa(OA.REINFORCE, "N2")),
    (pa(PA.PARRY, segment=("E01_03",)), oa(OA.CLAIM, "N3")),
]
CH1_MISTAKE = [
    (pa(PA.PARRY, "E01_06"), oa(OA.CLAIM, "N1")),
    (pa(PA.PARRY, "E01_01"), oa(OA.REINFORCE, "N2")),
    (pa(PA.PARRY, "E01_06"), oa(OA.CLAIM, "N1")),
    (pa(PA.PARRY, segment=("E01_03",)), oa(OA.CLAIM, "N3")),
]
CH2 = [
    (pa(PA.PARRY, "E02_02"), oa(OA.CLAIM, "N1")),
    (pa(PA.OBSERVE), oa(OA.CLAIM, "N2")),
    (pa(PA.SOLID, segment=("E02_03", "E02_02", "E02_04", "E02_05"), target="N1"), oa(OA.REINFORCE, "N1")),
    (pa(PA.PARRY, segment=("E02_06", "E02_01")), oa(OA.RUSH, "N3")),
    (pa(PA.PARRY, segment=("E02_07", "E02_01")), oa(OA.ALL_IN, "T2", True)),
]
CH3 = [
    (pa(PA.PARRY, "E03_08"), oa(OA.CLAIM, "N1")),
    (pa(PA.OBSERVE), oa(OA.CLAIM, "N3")),
    (pa(PA.SOLID, segment=("E03_07", "E03_06"), target="N3"), oa(OA.REINFORCE, "N3")),
    (pa(PA.PARRY, segment=("E03_02", "E03_04", "G-01")), oa(OA.RUSH, "N2")),
    (pa(PA.PARRY, segment=("E03_05", "E03_03")), oa(OA.ALL_IN, "T3", True)),
]


def soph_case():
    """test_warmup_and_rules._soph_state: sophistry unlocked, E02_04 with the wrong reason."""
    case = replace(ch2_case(), sophistry_unlocked=True)
    return replace(case, cards=tuple(replace(c, reason_correct=False) if c.id == "E02_04" else c for c in case.cards))


SOPH_BOARD = Board(chains=(("E02_03", "E02_02", "E02_04"),))
SOPH_PA = dict(segment=("E02_03", "E02_02", "E02_04"), target="N1")

ROUTES = [
    Route("ch1_route", "test_ch1_route::test_route", 1, ch1_case, ch1_board(), CH1),
    Route("ch1_mistake_r2_whiff", "test_ch1_route::test_mistake_path_wins", 1, ch1_case, ch1_board(), CH1_MISTAKE),
    Route("ch1_two_misreads", "test_ch1_route::test_two_misreads_unachieved", 1, ch1_case, ch1_board(), [
        (pa(PA.PARRY, "E01_06"), oa(OA.REINFORCE, "N1")),
        (pa(PA.PARRY, "E01_06"), oa(OA.REINFORCE, "N1")),
        (pa(PA.PARRY, "E01_06"), oa(OA.CLAIM, "N1"))]),
    Route("ch1_missed_break", "test_ch1_route::test_missed_break_round_reenters_after_next_contradiction", 1,
          ch1_case, ch1_board(), CH1[:2] + [
              (pa(PA.OBSERVE), oa(OA.CLAIM, "N3")),
              (pa(PA.PARRY, "E01_06"), oa(OA.CLAIM, "N1")),
              (pa(PA.PARRY, segment=("E01_03",)), oa(OA.CLAIM, "N3"))]),
    Route("ch1_round6_cap", "test_ch1_route::test_round6_cap_unachieved", 1, ch1_case, ch1_board(),
          CH1[:2] + [(pa(PA.OBSERVE), oa(OA.CLAIM, "N3"))] * 4),
    Route("ch2_route", "test_ch2_route::test_route_*", 2, ch2_case, ch2_board(), CH2),
    Route("ch2_mistake_r4_solid_vs_rush", "test_ch2_route::test_mistake_round4_solid_break_takes_rush", 2,
          ch2_case, ch2_board(), CH2[:3] + [
              (pa(PA.SOLID, segment=("E02_06", "E02_01"), target="N3"), oa(OA.RUSH, "N3"))]),
    Route("ch2_mistake_r3_parry_whiff", "test_ch2_route::test_mistake_round3_parry_whiffs_vs_reinforce", 2,
          ch2_case, ch2_board(), CH2[:2] + [(pa(PA.PARRY, "E02_02"), oa(OA.REINFORCE, "N1"))]),
    Route("ch2_card_solid_vs_claim", "test_ch2_route::test_numbers_card_misread_costs (1)", 2, ch2_case, ch2_board(),
          [(pa(PA.SOLID, segment=("E02_03", "E02_02"), target="N1"), oa(OA.CLAIM, "N1"))]),
    Route("ch2_card_solid_vs_rush", "test_ch2_route::test_numbers_card_misread_costs (2)", 2, ch2_case, ch2_board(),
          [(pa(PA.SOLID, segment=("E02_03", "E02_02"), target="N1"), oa(OA.RUSH, "N1"))]),
    Route("ch2_card_observe_vs_claim", "test_ch2_route::test_numbers_card_misread_costs (3)", 2, ch2_case,
          ch2_board(), [(pa(PA.OBSERVE), oa(OA.CLAIM, "N1"))]),
    Route("ch2_card_parry_vs_reinforce", "test_ch2_route::test_numbers_card_misread_costs (4)", 2, ch2_case,
          ch2_board(), [(pa(PA.PARRY, "E02_02"), oa(OA.REINFORCE, "N1"))]),
    Route("ch2_card_tail_observe_void", "test_ch2_route::test_numbers_card_misread_costs (5)", 2, ch2_case,
          ch2_board(), CH2[:4] + [(pa(PA.OBSERVE), oa(OA.ALL_IN, "T2", True))]),
    Route("ch3_route", "test_ch3_route::test_route_*", 3, ch3_case, ch3_board(), CH3),
    Route("ch3_alternative_no_g01", "test_ch3_route::test_alternative_route_without_g01", 3, ch3_case,
          ch3_board_no_g01(), CH3[:3] + [
              (pa(PA.PARRY, segment=("E03_02", "E03_03")), oa(OA.RUSH, "N2")),
              (pa(PA.PARRY, segment=("E03_02", "E03_03")), oa(OA.ALL_IN, "T3", True))]),
    Route("ch3_mistake_r3_parry_vs_reinforce", "test_ch3_route::test_mistake_round3_parry_vs_reinforce", 3,
          ch3_case, ch3_board(), CH3[:2] + [
              (pa(PA.PARRY, "E03_07"), oa(OA.REINFORCE, "N3")),
              (pa(PA.SOLID, segment=("E03_07", "E03_06"), target="N3"), oa(OA.CLAIM, "N1"))]),
    Route("ch3_full_rush_shisshu", "test_ch3_route::test_full_rush_taken_causes_shissu", 3, ch3_case, ch3_board(), [
        (pa(PA.SOLID, segment=("E03_02", "E03_04"), target="N2"), oa(OA.RUSH, "N1")),
        (pa(PA.OBSERVE), oa(OA.CLAIM, "N1"))]),
    Route("ch3_konju_second_intercept", "test_ch3_route::test_konju_on_second_intercept", 3, ch3_case, ch3_board(), [
        (pa(PA.PARRY, "E03_08"), oa(OA.CLAIM, "N1")),
        (pa(PA.PARRY, "E03_07"), oa(OA.CLAIM, "N3")),
        (pa(PA.OBSERVE), oa(OA.CLAIM, "N2"))]),
    Route("ch3_cutin_shaken_over_hachiku3", "test_ch3_route::test_cutin_priority_shaken_over_hachiku3", 3, ch3_case,
          ch3_board(), [(pa(PA.PARRY, "E03_08"), oa(OA.RUSH, "N1"))], overrides={"hachiku": 2}),
    Route("ch3_warmup_e0305", "test_warmup_and_rules::test_warmup_single_card_zero_mistakes", 3,
          warmup=[("E03_05",)]),
    Route("ch3_warmup_e0302", "test_warmup_and_rules::test_warmup_e0302_also_refutes", 3, warmup=[("E03_02",)]),
    Route("ch3_warmup_three_mistakes", "test_warmup_and_rules::test_warmup_three_mistakes", 3,
          warmup=[("E03_08",)] * 3),
    Route("ch3_warmup_one_mistake", "test_warmup_and_rules::test_warmup_one_mistake_then_right", 3,
          warmup=[("E03_08",), ("E03_05",)]),
    Route("ch3_warmup_chain_is_mistake", "test_warmup_and_rules::test_warmup_parry_only_and_chain_rule", 3,
          warmup=[("E03_05", "E03_02")]),
    Route("ch2_fox_instinct", "test_warmup_and_rules::test_fox_instinct_on_fuzzy (in a route)", 2, ch2_case,
          ch2_board(), CH2[:2], fox={1: (OA.CLAIM, OA.RUSH)}),
    Route("rule_trap_crit", "test_warmup_and_rules::test_trap_crit_snaps_link_and_infamy", 2, soph_case, SOPH_BOARD,
          [(pa(PA.SOPHISTRY, **SOPH_PA), oa(OA.TRAP, "N1"))]),
    Route("rule_assist_blocks", "test_warmup_and_rules::test_assist_blocks_crit", 2, soph_case, SOPH_BOARD,
          [(pa(PA.SOPHISTRY, assist=True, **SOPH_PA), oa(OA.TRAP, "N1"))]),
    Route("rule_assist_wasted", "test_warmup_and_rules::test_assist_wasted_without_trap", 2, soph_case, SOPH_BOARD,
          [(pa(PA.SOPHISTRY, assist=True, **SOPH_PA), oa(OA.REINFORCE, "N1"))]),
    Route("rule_b8_break_locks_at_1", "test_warmup_and_rules::test_break_round_locks_at_1_attack_resolves_then_tail",
          2, ch2_case, ch2_board(), [(pa(PA.SOLID, segment=("E02_06", "E02_01"), target="N3"), oa(OA.CLAIM, "N3"))],
          overrides={"shaken": "armed", "opp_hp": 5.0}),
    Route("rule_b9_rule3_at_half", "test_warmup_and_rules::test_rule3_threshold_is_at_most_half", 2, ch2_case,
          ch2_board(), [(pa(PA.PARRY, "E02_02"), oa(OA.CLAIM, "N1"))], overrides={"opp_hp": 80.0}),
]


# ------------------------------------------------------------------------------------------------- board layout

def board_layout(case, board: Board):
    """debBoard / debBoardOk / debBoardLink (docs/debate-engine.md §2.2): chain c card i at 5c+i, loose cards from
    15; a link at slot s joins s and s+1 (1 solid, 2 sophistry, 0 none)."""
    cards = ["-"] * G.BOARD_SLOTS
    ok = [1] * G.BOARD_SLOTS
    links = [0] * G.BOARD_SLOTS
    slot_of = {}
    for c, chain in enumerate(board.chains):
        for i, cid in enumerate(chain):
            s = 5 * c + i
            cards[s], slot_of[cid] = cid, s
            ok[s] = int(case.card(cid).reason_correct)
            if i + 1 < len(chain):
                k = link_kind(case.card(cid), case.card(chain[i + 1]))
                links[s] = 1 if k == SOLID_LINK else 2 if k == SOPH_LINK else 0
    for j, cid in enumerate(c for c in board.loose if c not in slot_of):
        s = 15 + j
        cards[s], slot_of[cid] = cid, s
        ok[s] = int(case.card(cid).reason_correct)
    return cards, ok, links, slot_of


def segment_slots(segment, board: Board, slot_of) -> tuple[int, int]:
    if len(segment) == 1:
        return slot_of[segment[0]], slot_of[segment[0]]
    for c, chain in enumerate(board.chains):
        n = len(segment)
        for i in range(len(chain) - n + 1):
            if tuple(chain[i:i + n]) == tuple(segment):
                return 5 * c + i, 5 * c + i + n - 1
            if tuple(reversed(chain[i:i + n])) == tuple(segment):
                return 5 * c + i + n - 1, 5 * c + i
    raise ValueError(f"segment {segment} not on the board")


# ------------------------------------------------------------------------------------------------- expectations

def node_id(chapter: int, nid: str) -> str:
    return nid if nid.startswith("F") or nid == "LAST_STAND" else data_node_id(chapter, nid)


def record(ev, chapter: int) -> str:
    n = lambda x: node_id(chapter, x)  # noqa: E731
    b = lambda x: "1" if x else "0"  # noqa: E731
    if isinstance(ev, E.Reveal):
        pa_name = {"solid_chain": "solid", "sophistry": "sophistry", "parry": "rebut", "observe": "observe"}
        oa_name = {o.value: OA_NAME[o] for o in OA}
        return f"reveal|{ev.round}|{pa_name[ev.player_action]}|{oa_name[ev.opponent_action]}|{ev.staging}"
    if isinstance(ev, E.NodeRemoved):
        return f"nodeRemoved|{n(ev.node_id)}|{ev.cause}"
    if isinstance(ev, E.NodeAdded):
        return f"nodeAdded|{n(ev.node_id)}|{ev.node_kind}|{ev.cause}"
    if isinstance(ev, E.DamageToOpponent):
        return f"dmgOpp|{ev.source}|{g6(ev.amount)}|{g6(ev.hp_before)}|{g6(ev.hp_after)}"
    if isinstance(ev, E.DamageToPlayer):
        return f"dmgPlayer|{ev.source}|{g6(ev.amount)}|{g6(ev.hp_before)}|{g6(ev.hp_after)}"
    if isinstance(ev, E.OpponentHealed):
        return f"heal|{g6(ev.amount)}|{g6(ev.hp_before)}|{g6(ev.hp_after)}"
    if isinstance(ev, E.ContradictionCounted):
        return f"contradiction|{ev.count}|{n(ev.node_id)}"
    if isinstance(ev, E.StatusGained):
        return f"statusGained|{STATUS.get(ev.status, ev.status)}|{ev.side}|{ev.rounds}"
    if isinstance(ev, E.StatusLost):
        return f"statusLost|{STATUS.get(ev.status, ev.status)}|{ev.side}|{ev.reason}"
    if isinstance(ev, E.HachikuChanged):
        return f"hachiku|{ev.before}|{ev.after}|{b(ev.preview)}"
    if isinstance(ev, E.InfamyChanged):
        return f"infamy|{ev.before}|{ev.after}"
    if isinstance(ev, E.AssistSpent):
        return f"assistSpent|{b(ev.wasted)}"
    if isinstance(ev, E.LinkSnapped):
        return f"linkSnapped|{ev.a}|{ev.b}|{ev.until_round}"
    if isinstance(ev, E.BreakResult):
        return f"break|{b(ev.success)}|{ev.via}|{ev.label or ''}|{','.join(ev.golden_used)}"
    if isinstance(ev, E.TailStarted):
        return f"tailStarted|{ev.rounds}|{n(ev.second_claim)}"
    if isinstance(ev, E.TailResult):
        return f"tailResult|{b(ev.correct)}"
    if isinstance(ev, E.BreakVoided):
        return f"breakVoided|{g6(ev.opp_hp)}|{ev.break_voids}"
    if isinstance(ev, E.Message):
        return f"msg|{ev.id}"
    if isinstance(ev, E.CutIn):
        prio = "" if ev.priority is None else str(ev.priority)
        return f"cutin|{ev.id}|{ev.level}|{prio}|{ev.side or ''}|{b(ev.played_full)}|{b(ev.demoted)}"
    if isinstance(ev, E.DebateEnded):
        return f"ended|{ev.result}|{ev.reason}"
    raise TypeError(type(ev).__name__)


def snapshot(s, chapter: int) -> dict:
    return {
        "debRound": s.round,
        "debPlayerHp": s.player_hp or 0.0,
        "debOppHp": s.opp_hp or 0.0,
        "nodes": [node_id(chapter, x.id) for x in s.nodes],
        "debShaken": SHAKEN[s.shaken],
        "debInTail": int(s.in_tail),
        "debTailLeft": s.tail_rounds_left,
        "debVoids": s.break_voids,
        "debHachiku": s.hachiku,
        "debKonju": s.konju_left,
        "debShisshu": s.shissu_left,
        "debParries": s.parry_count,
        "debContra": s.contradictions,
        "debInfamy": s.infamy,
        "debAssist": s.assist_left,
        "debOver": int(s.over),
        "debOutcome": OUTCOME[s.outcome],
        "debBreakLabel": s.break_label or "",
        "debGoldenUsed": int(bool(s.golden_used)),
        "debFragile": sum(1 for x in s.nodes if x.kind == "fragile"),
    }


def warm_snapshot(ws, mistake_limit: int) -> dict:
    auto = ws.auto_resolved
    trust = -1 if (auto or ws.mistakes >= mistake_limit) else (1 if ws.mistakes == 0 else 0)
    return {"dwRound": ws.round, "dwIndex": ws.index, "dwMistakes": ws.mistakes, "dwOver": int(ws.over),
            "dwAuto": int(auto), "dwTrustDelta": trust, "dwReward": 0 if trust == -1 else 1}


def warm_record(e: dict) -> str:
    k = e["kind"]
    c = lambda x: data_node_id(3, x)  # noqa: E731
    if k == "WarmupReveal":
        return f"wReveal|{e['round']}|{c(e['claim'])}|{','.join(e['cards'])}"
    if k == "WarmupCorrected":
        return f"wCorrected|{c(e['claim'])}"
    if k == "WarmupMistake":
        return f"wMistake|{e['count']}"
    if k == "WarmupAutoCorrected":
        return f"wAutoCorrected|{c(e['claim'])}"
    if k == "WarmupEnded":
        return f"wEnded|{e['trust_delta']}|{1 if e['reward'] else 0}|{e['mistakes']}"
    raise TypeError(k)


# ------------------------------------------------------------------------------------------------- tables

def _row(**kw) -> dict:
    r = {c: 0 if c in ("value", "assist") else -1 if c in ("from", "to") else "" for c in G.H_IN_COLS}
    r.update(kw)
    return r


@dataclass
class Expect:
    route: Route
    start_row: int
    rows: list  # driver row of each round
    after: list  # expected snapshot after each round
    events: list  # expected records of each round
    start: dict  # expected snapshot after the start
    extra: list = field(default_factory=list)  # (driver row, expected fields, expected records) of instinct rows


def build(routes=None):
    """Returns (hIn rows, debScript rows, [Expect])."""
    h_in, script, expects = [], [], []
    for rt in routes or ROUTES:
        if rt.warmup:
            _build_warmup(rt, h_in, expects)
            continue
        case = rt.case_fn()
        s = initial_state(case, rt.board)
        if rt.overrides:
            s = replace(s, **rt.overrides)
        cards, ok, links, slot_of = board_layout(case, rt.board)
        cid = CASE_ID[rt.chapter]
        base = dict(route=rt.name, case=cid, script=rt.name)
        h_in.append(_row(op="start", board=",".join(cards), ok=",".join(map(str, ok)),
                         links=",".join(map(str, links)), **base))
        for f, v in rt.overrides.items():
            val = SHAKEN[v] if f == "shaken" else v
            h_in.append(_row(op="set", key=OVERRIDE_KEY[f], value=val, **base))
        if case.sophistry_unlocked and not G.derive_tables()["debCase"][rt.chapter - 1]["soph"]:
            h_in.append(_row(op="set", key="soph", value=1, **base))
        exp = Expect(rt, len(h_in) - 1, [], [], [], snapshot(s, rt.chapter))  # after the start and the overrides
        for i, (p, o) in enumerate(rt.moves, start=1):
            prev = s
            s, evs = resolve_round(s, p, o)
            if i in rt.fox:
                s = replace(s, fox_left=s.fox_left - 1)
            frm, to = segment_slots(p.segment, rt.board, slot_of) if p.segment else (-1, -1)
            target = data_node_id(rt.chapter, p.target) if p.target else ""
            tell = {"clarity": "", "shown1": "", "shown2": ""}
            if i in rt.fox:
                pair = rt.fox[i]
                t = Tell(Clarity.FUZZY, pair, None, None, None, o.lit, None)
                tell = {"clarity": "fuzzy", "shown1": OA_NAME[pair[0]], "shown2": OA_NAME[pair[1]]}
                s_before = prev
                s_fox, t2, fox_ev = use_fox_instinct(s_before, t, o)
                exp.extra.append((len(h_in), {
                    "debInstinctLeft": s_fox.fox_left, "debTellClarity": t2.clarity.value,
                    "debTellBasis": t2.basis, "debTellShown1": OA_NAME[t2.shown[0]]},
                    [record(e, rt.chapter) for e in fox_ev]))
                h_in.append(_row(op="instinct", **base))
            exp.rows.append(len(h_in))
            h_in.append(_row(op="round", kind=PA_NAME[p.kind], **{"from": frm}, to=to, card=p.card or "",
                             target=target, assist=int(p.assist), **base))
            script.append({"key": f"{rt.name}:{i}", "action": OA_NAME[o.kind],
                           "lit": node_id(rt.chapter, o.lit) if o.lit else "", "scripted": int(o.scripted),
                           **tell, "star": "", "basis": "", "lineKey": ""})
            exp.after.append(snapshot(s, rt.chapter))
            exp.events.append([record(e, rt.chapter) for e in evs])
        expects.append(exp)
    return h_in, script, expects


def _build_warmup(rt: Route, h_in: list, expects: list) -> None:
    ws = ch3_warmup()
    limit = next(r for r in G.derive_tables()["debCase"] if r["id"] == "CH03_WARMUP")["mis"]
    hand = sorted({c for cards in rt.warmup for c in cards})
    chain = next((cards for cards in rt.warmup if len(cards) > 1), ())
    layout = list(chain) + [c for c in hand if c not in chain]
    cards = layout + ["-"] * (G.BOARD_SLOTS - len(layout))
    base = dict(route=rt.name, case="CH03_WARMUP", script=rt.name)
    start_row = len(h_in)
    h_in.append(_row(op="start", board=",".join(cards), ok=",".join(["1"] * G.BOARD_SLOTS),
                     links=",".join(["0"] * G.BOARD_SLOTS), **base))
    exp = Expect(rt, start_row, [], [], [], warm_snapshot(ws, limit))
    for presented in rt.warmup:
        ws, evs = resolve_warmup_round(ws, "parry", tuple(presented))
        exp.rows.append(len(h_in))
        if len(presented) == 1:
            h_in.append(_row(op="round", kind="rebut", card=presented[0], **base))
        else:
            h_in.append(_row(op="round", kind="rebut", **{"from": 0}, to=len(presented) - 1, **base))
        exp.after.append(warm_snapshot(ws, limit))
        exp.events.append([warm_record(e) for e in evs])
    expects.append(exp)


def case_param_mismatches() -> list[str]:
    """debCase (tools/gen_debate.py, from data/) against the ref fixtures' CaseConfig of each chapter."""
    rows = {r["id"]: r for r in G.derive_tables()["debCase"]}
    hk = {"off": 0, "preview": 1, "on": 2}
    out = []
    for ch, fn in ((1, ch1_case), (2, ch2_case), (3, ch3_case)):
        c, r = fn(), rows[CASE_ID[ch]]
        want = {
            "hp": int(c.player_max_hp is not None), "pMax": c.player_max_hp or 0, "oMax": c.opp_max_hp or 0,
            "cap": c.node_cap, "brPct": c.break_pct, "tw": c.tail_wrong, "tr": c.tail_rounds,
            "brLine": c.breakline_pct or 0, "hk": hk[c.hachiku_mode], "kjOn": int(c.konju_enabled),
            "ssOn": int(c.shissu_enabled), "soph": int(c.sophistry_unlocked), "assists": c.assist_charges,
            "fox": c.fox_charges, "hasTail": int(c.tail is not None), "ch1": int(c.break_rule == "ch1_e0103"),
            "brCard": c.ch1_card or "", "conT": c.contradiction_target or 0, "conD": c.contradiction_deadline or 0,
            "rcap": c.round_cap or 0, "gpN": len(c.golden_primary),
            "n1": data_node_id(ch, "N1"), "n2": data_node_id(ch, "N2"), "n3": data_node_id(ch, "N3"),
            "t": data_node_id(ch, c.tail.second_claim.id) if c.tail else "",
        }
        if c.player_max_hp is not None:
            want["base"] = c.claim_base
        for k, v in want.items():
            if r[k] != v:
                out.append(f"{CASE_ID[ch]}.{k}: data {r[k]!r}, ref {v!r}")
        if set(filter(None, (r["gp1"], r["gp2"]))) != set(c.golden_primary):
            out.append(f"{CASE_ID[ch]}.gp: data {r['gp1']},{r['gp2']}, ref {sorted(c.golden_primary)}")
    return out
