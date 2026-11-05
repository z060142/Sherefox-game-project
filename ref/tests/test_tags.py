"""Real 類別：值 tags (ruling C4; 各章設計 Ch.1-3 「標籤值」 tables).

* the data tables (what the fixtures load) equal the design snapshot's 標籤值 tables;
* every chain of the 推薦路線 / 常見失誤 / 次級替代 tables is the link type the route expects,
  with correct reasons, after the appraisals the route implies;
* the deliberate decoys of the 標籤值 notes only ever make sophistry (dashed) links;
* every breaker listed in the node tables shares exactly the listed non-grazing values;
* every attack / parry of the routes shares a revealed tag with its target node;
* the appraisal counts (Ch.2 = 3) are what the routes need.
"""

from __future__ import annotations

import csv
import re
from dataclasses import replace
from pathlib import Path

import pytest

from helpers import OA, E, of, opp, parry, step
from sherefox_ref.fixtures import (
    CH2_APPRAISED,
    CH3_APPRAISED,
    _table,
    ch1_case,
    ch2_board,
    ch2_case,
    ch3_case,
    data_node_id,
    node_rows,
)
from sherefox_ref.model import initial_state
from sherefox_ref.rules import IllegalAction, SOLID_LINK, SOPH_LINK, link_kind, segment_tags

PROJECT = Path(__file__).resolve().parents[2]
SNAPSHOT = PROJECT / "docs" / "design" / "10-cases-ch01-04.md"
TAG_SOURCE = PROJECT / "source" / "tags" / "tags_ch01-03.csv"
CATEGORY = {"時間": "time", "地點": "place", "人物": "person", "物理": "phys", "物理特性": "phys", "醜聞": "scandal"}
HIDDEN = {"—": "no", "醫療": "medical", "機械": "mech"}


# --------------------------------------------------------------------------- snapshot parsing


def _slugs() -> dict:
    with open(TAG_SOURCE, encoding="utf-8", newline="") as fh:
        return {(CATEGORY[r["category"]], r["value"]): r["slug"] for r in csv.DictReader(fh)}


def _tag(text: str, slugs: dict) -> tuple[str, bool]:
    """「物理特性：布料※」 -> ("phys:cloth", grazing)."""
    text = text.strip()
    grazing = text.endswith("※")
    cat, value = text.rstrip("※").split("：", 1)
    return f"{CATEGORY[cat]}:{slugs[(CATEGORY[cat], value)]}", grazing


def _rows(section: str) -> list[list[str]]:
    out = []
    for line in section.splitlines():
        if line.startswith("|") and not line.startswith("| ---"):
            out.append([c.strip() for c in line.strip().strip("|").split("|")])
    return out


def snapshot_tables(chapter: int) -> tuple[list, list]:
    text = SNAPSHOT.read_text(encoding="utf-8")
    body = re.split(r"^## ", text, flags=re.M)
    ch = next(b for b in body if b.startswith(f"Ch.{chapter} "))
    sec = re.split(r"^### ", ch, flags=re.M)
    tag_sec = next(s for s in sec if s.startswith("標籤值"))
    tables = [t for t in re.split(r"\n\s*\n", tag_sec) if t.lstrip().startswith("|")]
    cards, nodes = _rows(tables[0])[1:], _rows(tables[1])[1:]
    return cards, nodes


NODE_LABEL = {"熱身說法": "W1", "尾聲第二說詞": "T1"}


def design_cards(chapter: int) -> dict:
    """id -> {"tags", "grazing", "hidden": {tag: kind}} from the snapshot."""
    slugs = _slugs()
    out = {}
    for row in snapshot_tables(chapter)[0]:
        cid = row[0]
        tags, grazing = [], set()
        for part in row[2].split("、"):
            t, g = _tag(part, slugs)
            tags.append(t)
            if g:
                grazing.add(t)
        hidden = {t: "no" for t in tags}
        for part in row[3].split("；"):
            if "＝" not in part:
                assert part.strip() == "—", (cid, part)
                continue
            vals, kind = part.split("＝", 1)
            kind = HIDDEN[re.sub(r"（.*", "", kind).strip()]
            if vals.strip() == "其餘":
                continue
            for v in vals.split("、"):
                hidden[_tag(v, slugs)[0]] = kind
        out[cid] = {"tags": tags, "grazing": grazing, "hidden": hidden, "police": "警方驗屍報告" in row[3]}
    return out


def design_nodes(chapter: int) -> dict:
    """data node id -> {"tags", "breakers": {card: set(shared tags)}}."""
    slugs = _slugs()
    out = {}
    for row in snapshot_tables(chapter)[1]:
        label = NODE_LABEL.get(row[0], row[0])
        nid = f"CH{chapter:02d}_{label}"
        tags = [_tag(p, slugs)[0] for p in row[2].split("、")]
        breakers = {}
        for cid, shared in re.findall(r"(E\d\d_\d\d|G-\d\d)（([^）]*)）", row[3]):
            breakers[cid] = {_tag(p, slugs)[0] for p in shared.split("、")}
        if not breakers:
            assert row[3].startswith("無"), row
        out[nid] = {"tags": tags, "breakers": breakers}
    return out


def _evidence(cid: str) -> dict:
    return next(r for r in _table("evidence") if r["id"] == cid)


def _split(cell: str) -> list[str]:
    return [x for x in cell.split(",") if x]


# --------------------------------------------------------------------------- data == design


@pytest.mark.parametrize("chapter", [1, 2, 3])
def test_card_tags_match_design_table(chapter):
    for cid, d in design_cards(chapter).items():
        row = _evidence(cid)
        assert _split(row["tags"]) == d["tags"], cid
        assert set(_split(row["grazingTags"])) == d["grazing"], cid
        hidden = {t for t, k in d["hidden"].items() if k != "no"}
        assert set(_split(row["hiddenTags"])) == hidden, cid
        kinds = {k for k in d["hidden"].values() if k != "no"}
        assert kinds <= {"medical": {"medical"}, "mechanical": {"mech"}, "dual": {"medical", "mech"},
                         "none": set()}[row["appraise"]], cid
        assert bool(row["policeTags"]) == d["police"], cid
        if d["police"]:
            assert set(_split(row["policeTags"])) == hidden, cid


def test_every_card_has_design_tags():
    ids = set()
    for c in (1, 2, 3):
        ids |= set(design_cards(c))
    assert ids == {r["id"] for r in _table("evidence")}


def test_substitute_uses_golden_values_all_grazing():
    """Ruling D11."""
    g, s = _evidence("G-01"), _evidence("S-01")
    assert _split(s["tags"]) == _split(g["tags"])
    assert set(_split(s["grazingTags"])) == set(_split(s["tags"]))


@pytest.mark.parametrize("chapter", [1, 2, 3])
def test_node_tags_and_breakers_match_design_table(chapter):
    design = design_nodes(chapter)
    data = {r["id"]: r for r in node_rows(chapter)}
    assert set(design) == set(data)  # every claim / tail / warm-up node has design tags
    for nid, d in design.items():
        assert _split(data[nid]["tags"]) == d["tags"], nid


def _node_ids():
    out = []
    for c in (1, 2, 3):
        for nid in design_nodes(c):
            marks = ()
            if nid == "CH02_T1":
                marks = pytest.mark.xfail(
                    strict=True,
                    reason="design finding: the Ch.2 標籤值 node table lists only E02_07 as breaker of the tail "
                    "second claim, but ruling C3 (and the route R5 parry E02_07+E02_01) gives {E02_07, E02_01}; "
                    "E02_01 does share 物理特性：替換機芯黃銅 with it (after mechanical appraisal).",
                )
            out.append(pytest.param(c, nid, id=nid, marks=marks))
    return out


@pytest.mark.parametrize("chapter,nid", _node_ids())
def test_node_breakers_match_design_table(chapter, nid):
    """refutedBy (localization CLM notes / ruling C3 / B16) == the node table's 破解證物 column."""
    row = next(r for r in node_rows(chapter) if r["id"] == nid)
    assert set(_split(row["refutedBy"])) == set(design_nodes(chapter)[nid]["breakers"])


def _breaker_cases():
    out = []
    for c in (1, 2, 3):
        for nid, d in design_nodes(c).items():
            for cid, shared in d["breakers"].items():
                out.append((c, nid, cid, shared))
    return out


BREAKERS = _breaker_cases()


def test_breaker_pair_count():
    assert len(BREAKERS) == 20


@pytest.mark.parametrize("chapter,nid,cid,shared", BREAKERS, ids=[f"{n}-{c}" for _, n, c, _ in BREAKERS])
def test_breaker_shares_listed_non_grazing_values(chapter, nid, cid, shared):
    row = _evidence(cid)
    node = next(r for r in node_rows(chapter) if r["id"] == nid)
    card_firm = set(_split(row["tags"])) - set(_split(row["grazingTags"]))
    node_firm = set(_split(node["tags"])) - set(_split(node["grazingTags"]))
    assert card_firm & node_firm == shared


# --------------------------------------------------------------------------- route chains

CASES = {1: ch1_case, 2: ch2_case, 3: ch3_case}

# (chapter, segment, expected link type, where) — every chain of 推薦路線 / 常見失誤 / 替代路線,
# plus the board chains the routes are played from.
ROUTE_CHAINS = [
    (1, ("E01_01", "E01_04"), SOLID_LINK, "Ch.1 R2 實證連鎖"),
    (2, ("E02_03", "E02_02", "E02_04", "E02_05"), SOLID_LINK, "Ch.2 R3 實證連鎖"),
    (2, ("E02_06", "E02_01"), SOLID_LINK, "Ch.2 R4 反駁論破 / 常見失誤 R4 實證連鎖論破"),
    (2, ("E02_07", "E02_01"), SOLID_LINK, "Ch.2 R5 尾聲 2 張無弱點實證"),
    (2, ("E02_06", "E02_01", "E02_07"), SOLID_LINK, "Ch.2 board chain"),
    (3, ("E03_07", "E03_06"), SOLID_LINK, "Ch.3 R3 實證連鎖"),
    (3, ("E03_02", "E03_04", "G-01"), SOLID_LINK, "Ch.3 R4 反駁論破"),
    (3, ("E03_05", "E03_03"), SOLID_LINK, "Ch.3 R5 尾聲"),
    (3, ("E03_02", "E03_03"), SOLID_LINK, "Ch.3 次級替代論破"),
    (3, ("E03_05", "E03_02", "E03_03"), SOLID_LINK, "Ch.3 board chain without G-01"),
]


@pytest.mark.parametrize("chapter,segment,expected,where", ROUTE_CHAINS, ids=[w for *_, w in ROUTE_CHAINS])
def test_route_chain_link_type(chapter, segment, expected, where):
    case = CASES[chapter]()
    for a, b in zip(segment, segment[1:]):
        ca, cb = case.card(a), case.card(b)
        assert ca.reason_correct and cb.reason_correct
        got = link_kind(ca, cb)
        assert got == expected, (where, a, b, sorted(set(ca.revealed) & set(cb.revealed)), got)


# 標籤值 notes: 刻意的誘餌 (只共享擦邊值，接上只會是虛線), after the route's appraisals.
DECOYS = [
    (1, "E01_02", "E01_05"), (1, "E01_04", "E01_06"), (1, "E01_07", "E01_01"), (1, "E01_07", "E01_04"),
    (1, "E01_06", "E01_07"),
    (2, "E02_03", "E02_01"), (2, "E02_03", "E02_07"), (2, "E02_05", "E02_06"), (2, "E02_08", "E02_04"),
    (2, "E02_08", "E02_07"),
    (3, "E03_04", "E03_07"), (3, "E03_05", "E03_08"), (3, "G-01", "E03_07"), (3, "G-01", "E03_09"),
]


@pytest.mark.parametrize("chapter,a,b", DECOYS, ids=[f"{a}-{b}" for _, a, b in DECOYS])
def test_decoys_only_make_sophistry(chapter, a, b):
    case = CASES[chapter]()
    assert link_kind(case.card(a), case.card(b)) == SOPH_LINK


def test_e0207_e0201_dashed_before_appraisal():
    """標籤值 note: 鑑定前 E02_07↔E02_01 只共享黃銅※，鑑定後才變實線."""
    case = ch2_case(appraised=frozenset({"E02_02"}))
    assert link_kind(case.card("E02_07"), case.card("E02_01")) == SOPH_LINK
    case = ch2_case(appraised=frozenset({"E02_02", "E02_07"}))
    assert link_kind(case.card("E02_07"), case.card("E02_01")) == SOPH_LINK  # E02_01 still hidden
    assert link_kind(ch2_case().card("E02_07"), ch2_case().card("E02_01")) == SOLID_LINK


def test_e0301_e0308_cannot_link():
    """標籤值 note: 22:00～22:30 and 22:10 are different values."""
    case = ch3_case()
    assert link_kind(case.card("E03_01"), case.card("E03_08")) is None


def test_wrong_reason_or_substitute_is_sophistry():
    case = ch3_case()
    a, b = case.card("E03_07"), case.card("E03_06")
    assert link_kind(replace(a, reason_correct=False), b) == SOPH_LINK
    assert link_kind(case.card("S-01"), case.card("E03_04")) == SOPH_LINK  # D11: all grazing
    sub = replace(case.card("G-01"), id="X", grade="substitute")
    assert link_kind(sub, case.card("E03_04")) == SOPH_LINK  # substitute card, non-grazing share


# --------------------------------------------------------------------------- route targets

# (chapter, cards shown, target node) for every attack / parry of the routes and mistake rounds.
ROUTE_TARGETS = [
    (1, ("E01_06",), "N1"), (1, ("E01_01", "E01_04"), "N2"), (1, ("E01_03",), "N3"), (1, ("E01_01",), "N2"),
    (2, ("E02_02",), "N1"), (2, ("E02_03", "E02_02", "E02_04", "E02_05"), "N1"), (2, ("E02_06", "E02_01"), "N3"),
    (2, ("E02_07", "E02_01"), "T2"),
    (3, ("E03_08",), "N1"), (3, ("E03_07", "E03_06"), "N3"), (3, ("E03_02", "E03_04", "G-01"), "N2"),
    (3, ("E03_05", "E03_03"), "T3"), (3, ("E03_02", "E03_03"), "N2"), (3, ("E03_07",), "N3"),
]


@pytest.mark.parametrize("chapter,cards,target", ROUTE_TARGETS, ids=[f"ch{c}-{t}-{'+'.join(s)}" for c, s, t in ROUTE_TARGETS])
def test_route_target_shares_revealed_tag(chapter, cards, target):
    case = CASES[chapter]()
    node = case.node_def(target)
    assert segment_tags(case, cards) & set(node.tags), (cards, target)
    # the refuting cards of a parry each share a revealed non-grazing value with the node
    for cid in cards:
        if cid in node.refuters:
            card = case.card(cid)
            assert (set(card.revealed) - card.grazing) & set(node.tags), (cid, target)


def test_warmup_refuters_share_tags():
    w = next(r for r in node_rows(3) if r["kind"] == "warmup")
    case = ch3_case()
    for cid in _split(w["refutedBy"]):
        assert set(case.card(cid).revealed) & set(_split(w["tags"])), cid
    assert data_node_id(3, "W3_1") == "CH03_W1"


# --------------------------------------------------------------------------- appraisals


def test_fixture_tags_equal_data_tags():
    for case in (ch1_case(), ch2_case(), ch3_case()):
        for card in case.cards:
            row = _evidence(card.id)
            assert card.tags == tuple(_split(row["tags"]))
            assert card.grazing == frozenset(_split(row["grazingTags"]))


def test_appraisal_counts():
    assert [ch1_case().appraisals, ch2_case().appraisals, ch3_case().appraisals] == [0, 3, 3]
    assert len(CH2_APPRAISED) == 3 and len(CH3_APPRAISED) == 2
    with pytest.raises(ValueError):
        ch2_case(appraised=frozenset({"E02_01", "E02_02", "E02_07", "E02_03"}))  # E02_03 needs none
    # without the police report (trust <= 2) E03_01 must be appraised too: 3 of 3
    ch3_case(appraised=frozenset({"E03_01", "E03_02", "E03_04"}), police_report=False)


def test_ch2_r1_parry_needs_appraised_e0202():
    """數值總表 五: 「R1 反駁需要已鑑定的 E02_02」."""
    case = ch2_case(appraised=frozenset({"E02_01", "E02_07"}))
    s0 = initial_state(case, ch2_board())
    with pytest.raises(IllegalAction):
        step(s0, parry("E02_02"), opp(OA.CLAIM, "N1"))
    s0 = initial_state(ch2_case(), ch2_board())
    s1, ev = step(s0, parry("E02_02"), opp(OA.CLAIM, "N1"))
    assert [d.amount for d in of(ev, E.DamageToOpponent)] == [30.0]


def test_police_report_reveals_e0301():
    with_report = ch3_case().card("E03_01")
    without = ch3_case(police_report=False).card("E03_01")
    assert with_report.fully_revealed and set(with_report.revealed) == set(with_report.tags)
    assert not without.fully_revealed and without.revealed == ("person:moss",)
