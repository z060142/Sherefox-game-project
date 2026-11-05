"""Case fixtures for Ch.1-3.

Cards, tags and claim nodes are loaded from the game data tables (`data/evidence.json`,
`data/nodes.json`, `data/chapters.json`, built by `tools/build_data.py` from the design's
標籤值 tables), so the model and the game always judge links on the same 類別：值 tags.
Opponent profiles, boards and numbers come from 各章設計 and 數值總表.

Ids: claim nodes keep their pool index ("N1".."N3"); the tail second claim is "T<chapter>";
the Ch.3 warm-up claim is "W3_1". `DATA_NODE_IDS` maps them to the data ids.

Appraisal: each case takes the set of appraised cards. The defaults are what the 推薦路線
implies (Ch.2: E02_02 for the R1 parry, E02_01 and E02_07 for the tail chain = 3, 數值總表 五;
Ch.3: E03_02 and E03_04, with E03_01 revealed by the police report at trust >= 3).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .model import (
    EXTRINSIC,
    OA,
    SCANDAL,
    STRONG,
    SUBSTITUTE,
    Board,
    Card,
    CaseConfig,
    ClaimNodeDef,
    OpponentProfile,
    TailSpec,
)
from .warmup import WarmupClaim, WarmupState

DATA_DIR = Path(__file__).resolve().parents[3] / "data"

# B15 / 數值總表 四: 犯人型 45/15/20/20. Ch.1 Arthur: 庇護者型 without 猛攻 and 設陷 (D7 25/0/50/0;
# the policy only draws from the available actions).
ALL4 = frozenset({OA.CLAIM, OA.RUSH, OA.REINFORCE, OA.TRAP})
CULPRIT_W = ((OA.CLAIM, 45), (OA.RUSH, 15), (OA.REINFORCE, 20), (OA.TRAP, 20))
PROTECTOR_W = ((OA.CLAIM, 25), (OA.RUSH, 5), (OA.REINFORCE, 50), (OA.TRAP, 20))

GRADES = {"common": "normal", "key": "key", "story": "story", "golden": "golden", "substitute": "substitute"}

CH2_APPRAISED = frozenset({"E02_02", "E02_01", "E02_07"})
CH3_APPRAISED = frozenset({"E03_02", "E03_04"})


# --------------------------------------------------------------------------- data loading


@lru_cache(maxsize=None)
def _table(name: str) -> tuple[dict, ...]:
    with open(DATA_DIR / f"{name}.json", encoding="utf-8") as fh:
        return tuple(json.load(fh))


def _split(cell: str) -> tuple[str, ...]:
    return tuple(x for x in cell.split(",") if x)


def evidence_rows(chapter: int) -> tuple[dict, ...]:
    """Cards of a chapter's debate in data order (G-01 and S-01 join Ch.3 via `usable`)."""
    return tuple(r for r in _table("evidence") if str(chapter) in _split(r["usable"]))


def _short_node_id(row: dict) -> str:
    c = row["chapter"]
    return {"claim": f"N{row['idx']}", "tail": f"T{c}", "warmup": f"W{c}_{row['idx']}"}[row["kind"]]


def node_rows(chapter: int) -> tuple[dict, ...]:
    return tuple(r for r in _table("nodes") if r["chapter"] == chapter)


def data_node_id(chapter: int, short_id: str) -> str:
    return next(r["id"] for r in node_rows(chapter) if _short_node_id(r) == short_id)


def chapter_row(chapter: int) -> dict:
    return next(r for r in _table("chapters") if r["id"] == chapter)


def card_from_row(row: dict, appraised: bool = False, police_report: bool = True) -> Card:
    flags = set()
    if row["strong"]:
        flags.add(STRONG)
    if row["scandal"]:
        flags.add(SCANDAL)
    if row["offChain"]:
        flags.add(EXTRINSIC)
    if row["grade"] == "substitute":
        flags.add(SUBSTITUTE)
    hidden = set(_split(row["hiddenTags"]))
    if police_report:
        hidden -= set(_split(row["policeTags"]))  # 01-systems 3.1: police post-mortem report (trust >= 3)
    return Card(
        row["id"],
        _split(row["tags"]),
        grade=GRADES[row["grade"]],
        flags=frozenset(flags),
        grazing=frozenset(_split(row["grazingTags"])),
        hidden=frozenset(hidden),
        appraised=appraised,
    )


def cards(chapter: int, appraised=frozenset(), police_report: bool = True) -> tuple[Card, ...]:
    rows = evidence_rows(chapter)
    unknown = set(appraised) - {r["id"] for r in rows}
    if unknown:
        raise ValueError(f"appraised cards not in Ch.{chapter}: {sorted(unknown)}")
    return tuple(card_from_row(r, r["id"] in appraised, police_report) for r in rows)


def _node(row: dict) -> ClaimNodeDef:
    return ClaimNodeDef(
        _short_node_id(row),
        frozenset(_split(row["tags"])),
        frozenset(_split(row["refutedBy"])),
        "true" if row["truth"] else "false",
    )


def claim_pool(chapter: int) -> tuple[ClaimNodeDef, ...]:
    rows = sorted((r for r in node_rows(chapter) if r["kind"] == "claim"), key=lambda r: r["idx"])
    return tuple(_node(r) for r in rows)


def tail_node(chapter: int) -> ClaimNodeDef:
    return _node(next(r for r in node_rows(chapter) if r["kind"] == "tail"))


def _check_appraisals(chapter: int, appraised) -> int:
    """Appraisal charges (data/chapters.json); raises when the chosen cards need more."""
    limit = chapter_row(chapter)["appraisals"]
    costs = {r["id"]: r["appraiseCost"] for r in evidence_rows(chapter)}
    for c in appraised:
        if costs[c] == 0:
            raise ValueError(f"{c} needs no appraisal")
    used = sum(costs[c] for c in appraised)
    if used > limit:
        raise ValueError(f"Ch.{chapter}: {used} appraisals used, only {limit} available")
    return limit


# --------------------------------------------------------------------------- Ch.1


def ch1_case() -> CaseConfig:
    arthur = OpponentProfile(
        name="Arthur",
        otype="protector",
        weights=PROTECTOR_W,
        available=frozenset({OA.CLAIM, OA.REINFORCE}),  # 不使用猛攻與設陷
        rules=frozenset({1, 4}),
        clarity_mix=(100, 0, 0),
        tutorial_clear=True,
        gestures=((OA.CLAIM, "chest_out_hands_on_hips"), (OA.REINFORCE, "pull_sleeve_down")),
    )
    return CaseConfig(
        case_id="ch1_pudding",
        chapter=1,
        stage="early",
        player_max_hp=None,
        opp_max_hp=None,
        node_cap=3,
        node_pool=claim_pool(1),
        cards=cards(1),
        opponent=arthur,
        hachiku_mode="preview",
        assist_charges=0,  # 援護 unlocks after the Ch.1 win
        break_rule="ch1_e0103",
        ch1_card="E01_03",
        contradiction_target=2,
        contradiction_deadline=3,
        round_cap=6,
        appraisals=chapter_row(1)["appraisals"],
    )


def ch1_board() -> Board:
    return Board(chains=(("E01_01", "E01_04"),), loose=("E01_02", "E01_03", "E01_05", "E01_06"))


# --------------------------------------------------------------------------- Ch.2


def ch2_case(appraised=CH2_APPRAISED) -> CaseConfig:
    fitch = OpponentProfile(
        name="Fitch",
        otype="culprit",
        weights=CULPRIT_W,
        available=ALL4,
        rules=frozenset({1, 2, 3, 4, 5}),
        clarity_mix=(60, 40, 0),
        gestures=(
            (OA.CLAIM, "tug_cuff_bow"),
            (OA.RUSH, "slam_counter_raise_voice"),
            (OA.REINFORCE, "wipe_sweat_handkerchief"),
            (OA.TRAP, "glance_corner_lip_twitch"),
        ),
    )
    return CaseConfig(
        case_id="ch2_clockshop",
        chapter=2,
        stage="early",
        player_max_hp=100.0,
        opp_max_hp=100.0,
        node_cap=3,
        node_pool=claim_pool(2),
        cards=cards(2, appraised),
        opponent=fitch,
        hachiku_mode="on",
        konju_enabled=False,
        shissu_enabled=False,
        tail=TailSpec("culprit_all_in", tail_node(2)),
        appraisals=_check_appraisals(2, appraised),
    )


def ch2_board() -> Board:
    return Board(
        chains=(("E02_03", "E02_02", "E02_04", "E02_05"), ("E02_06", "E02_01", "E02_07")),
    )


# --------------------------------------------------------------------------- Ch.3


def ch3_case(appraised=CH3_APPRAISED, police_report: bool = True) -> CaseConfig:
    pierce = OpponentProfile(
        name="Pierce",
        otype="culprit",
        weights=CULPRIT_W,
        available=ALL4,
        rules=frozenset({1, 2, 3, 4, 5}),
        clarity_mix=(60, 40, 0),
        gestures=(
            (OA.CLAIM, "touch_watch_chain"),
            (OA.RUSH, "loosen_cravat_step_forward"),
            (OA.REINFORCE, "open_ledger"),
            (OA.TRAP, "glance_arthur_tap_ledger_cover"),
        ),
    )
    return CaseConfig(
        case_id="ch3_barge",
        chapter=3,
        stage="early",
        player_max_hp=100.0,
        opp_max_hp=100.0,
        node_cap=3,
        node_pool=claim_pool(3),
        cards=cards(3, appraised, police_report),
        opponent=pierce,
        hachiku_mode="on",
        konju_enabled=True,
        shissu_enabled=True,
        tail=TailSpec("culprit_all_in", tail_node(3)),
        golden_primary=frozenset({"E03_04", "G-01"}),
        appraisals=_check_appraisals(3, appraised),
    )


def ch3_board() -> Board:
    return Board(
        chains=(("E03_07", "E03_06"), ("E03_02", "E03_04", "G-01"), ("E03_05", "E03_03")),
        loose=("E03_08", "E03_01"),
    )


def ch3_board_no_g01() -> Board:
    """Ch.2 missed G-01: secondary route E03_02 -> E03_03."""
    return Board(
        chains=(("E03_07", "E03_06"), ("E03_05", "E03_02", "E03_03")),
        loose=("E03_08", "E03_01", "E03_04"),
    )


def ch3_warmup() -> WarmupState:
    # 警督的誤判：「鑰匙在船夫身上，門又從裡面鎖著，所以就是他！」 (data node CH03_W1)
    rows = [r for r in node_rows(3) if r["kind"] == "warmup"]
    return WarmupState(claims=tuple(WarmupClaim(_short_node_id(r), frozenset(_split(r["refutedBy"]))) for r in rows))
