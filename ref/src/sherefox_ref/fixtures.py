"""Case fixtures for Ch.1-3, built from 各章設計 (ch1-4_design) and 數值總表.

Inferred data (not in the design text) is marked `# INFERRED:` and listed in the report:
  * node tags = union of the refuting cards' tags (node tables give no tags);
  * tail second-claim refuters = the cards the route table uses to finish;
  * E02_01 is 強攻 (implied by 「漏 E02_06 時第 4 回合只能用 E02_01 單張論破」);
  * G-01 tags = those of its source card E02_01 (物理・醜聞); G-01 flags 強攻 + 鏈外事實.
"""

from __future__ import annotations

from .model import (
    EXTRINSIC,
    OA,
    STRONG,
    Board,
    Card,
    CaseConfig,
    ClaimNodeDef,
    OpponentProfile,
    TailSpec,
)
from .warmup import WarmupClaim, WarmupState

# SPEC-QUESTION: A-3's example gives 犯人型 45/25/15/15; 數值總表 四 gives 45/15/20/20
# (used here).
ALL4 = frozenset({OA.CLAIM, OA.RUSH, OA.REINFORCE, OA.TRAP})
CULPRIT_W = ((OA.CLAIM, 45), (OA.RUSH, 15), (OA.REINFORCE, 20), (OA.TRAP, 20))
PROTECTOR_W = ((OA.CLAIM, 25), (OA.RUSH, 5), (OA.REINFORCE, 50), (OA.TRAP, 20))


def _node(nid, refuters, cards, truth="false"):
    tags = frozenset(t for c in cards if c.id in refuters for t in c.tags)  # INFERRED
    return ClaimNodeDef(nid, tags, frozenset(refuters), truth)


# --------------------------------------------------------------------------- Ch.1

CH1_CARDS = (
    Card("E01_01", ("物理", "時間")),
    Card("E01_02", ("物理", "地點")),
    Card("E01_03", ("人物", "物理"), grade="key", flags=frozenset({STRONG})),  # 「E01_03 袖口（強攻）」
    Card("E01_04", ("地點", "時間")),
    Card("E01_05", ("地點", "人物")),
    Card("E01_06", ("時間", "人物")),
    Card("E01_07", ("人物", "地點"), grade="story"),
)


def ch1_case(deadline_rule: str = "numbers") -> CaseConfig:
    c = CH1_CARDS
    nodes = (
        _node("N1", {"E01_06", "E01_05"}, c),
        _node("N2", {"E01_01", "E01_04"}, c),
        _node("N3", {"E01_03"}, c),
    )
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
        node_pool=nodes,
        cards=c,
        opponent=arthur,
        hachiku_mode="preview",
        assist_charges=0,  # 援護 unlocks after the Ch.1 win
        break_rule="ch1_e0103",
        ch1_card="E01_03",
        contradiction_target=2,
        contradiction_deadline=3,
        ch1_deadline_rule=deadline_rule,
    )


def ch1_board() -> Board:
    return Board(chains=(("E01_01", "E01_04"),), loose=("E01_02", "E01_03", "E01_05", "E01_06"))


# --------------------------------------------------------------------------- Ch.2

CH2_CARDS = (
    Card("E02_01", ("物理", "醜聞"), grade="key", flags=frozenset({STRONG})),  # INFERRED strong
    Card("E02_02", ("時間", "地點")),
    Card("E02_03", ("物理", "地點")),
    Card("E02_04", ("時間", "人物")),
    Card("E02_05", ("時間", "人物")),
    Card("E02_06", ("物理", "地點")),
    Card("E02_07", ("人物", "物理")),
    Card("E02_08", ("人物", "地點"), grade="story"),
)


def ch2_case() -> CaseConfig:
    c = CH2_CARDS
    nodes = (
        _node("N1", {"E02_02", "E02_03", "E02_04"}, c),
        # N2 is true; no refuter -> parry always whiffs. INFERRED: no tags (none derivable).
        _node("N2", set(), c, truth="true"),
        _node("N3", {"E02_06", "E02_01"}, c),
    )
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
    tail_node = _node("T2", {"E02_07", "E02_01"}, c)  # INFERRED from route R5
    return CaseConfig(
        case_id="ch2_clockshop",
        chapter=2,
        stage="early",
        player_max_hp=100.0,
        opp_max_hp=100.0,
        node_cap=3,
        node_pool=nodes,
        cards=c,
        opponent=fitch,
        hachiku_mode="on",
        konju_enabled=False,
        shissu_enabled=False,
        tail=TailSpec("culprit_all_in", tail_node),
    )


def ch2_board() -> Board:
    return Board(
        chains=(("E02_03", "E02_02", "E02_04", "E02_05"), ("E02_06", "E02_01", "E02_07")),
    )


# --------------------------------------------------------------------------- Ch.3

CH3_CARDS = (
    Card("E03_01", ("時間", "人物")),
    Card("E03_02", ("地點", "物理")),
    Card("E03_03", ("地點", "物理")),
    Card("E03_04", ("物理", "醜聞"), grade="key", flags=frozenset({STRONG})),  # 「強攻 E03_04」
    Card("E03_05", ("人物", "地點")),
    Card("E03_06", ("人物", "物理")),
    Card("E03_07", ("醜聞", "人物")),
    Card("E03_08", ("時間", "地點")),
    Card("E03_09", ("人物", "醜聞"), grade="story"),
    # INFERRED: G-01 tags from its source card E02_01; golden clues carry 鏈外事實.
    Card("G-01", ("物理", "醜聞"), grade="golden", flags=frozenset({STRONG, EXTRINSIC})),
)


def ch3_case() -> CaseConfig:
    c = CH3_CARDS
    nodes = (
        _node("N1", {"E03_08", "E03_06"}, c),
        _node("N2", {"E03_02", "E03_03"}, c),
        _node("N3", {"E03_07"}, c),
    )
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
    tail_node = _node("T3", {"E03_05", "E03_03"}, c)  # INFERRED from route R5
    return CaseConfig(
        case_id="ch3_barge",
        chapter=3,
        stage="early",
        player_max_hp=100.0,
        opp_max_hp=100.0,
        node_cap=3,
        node_pool=nodes,
        cards=c,
        opponent=pierce,
        hachiku_mode="on",
        konju_enabled=True,
        shissu_enabled=True,
        tail=TailSpec("culprit_all_in", tail_node),
        golden_primary=frozenset({"E03_04", "G-01"}),
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
    # 警督的誤判：「鑰匙在船夫身上，門又從裡面鎖著，所以就是他！」
    return WarmupState(claims=(WarmupClaim("W3_1", frozenset({"E03_05", "E03_02"})),))
