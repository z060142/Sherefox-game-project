# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build the Sherefox data tables and string tables for Ch.1-3.

Usage (from the project root):
    uv run tools/build_data.py                      build data/*.json and strings/*.csv, then validate
    uv run tools/build_data.py --check              build in memory and validate only (writes nothing)
    uv run tools/build_data.py --import-localization <dir>
                                                    copy a new localization package into source/localization/ first
    uv run tools/build_data.py --make-tag-placeholder [--force]
                                                    (re)write the category-only placeholder tag file

Inputs (all inside the project):
    source/localization/   localization package (strings.json, *.csv)
    source/tags/tags_ch01-03.csv   per-card / per-node tag values (category, value, slug, grazing, hidden)
    source/staging/staging_ch01-03.csv   per-line VN staging (bg, standees, focus, style); merged into the script table
    docs/design/*.md       design snapshots (01-systems, 02-numbers, 10-cases)
    docs/rulings.md        design rulings not yet in the snapshots (applied as constants below, cited by id)

Everything is deterministic: fixed row order, LF line endings, UTF-8 without BOM.
Standard library only. Exit code 1 when validation finds an error; count mismatches are warnings.
The table and column meanings are documented in docs/data-schema.md.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOC = ROOT / "source" / "localization"
TAG_FILE = ROOT / "source" / "tags" / "tags_ch01-03.csv"
STAGING_FILE = ROOT / "source" / "staging" / "staging_ch01-03.csv"
DESIGN = ROOT / "docs" / "design"
DATA_OUT = ROOT / "data"
STRINGS_OUT = ROOT / "strings"

CHAPTERS = (1, 2, 3)
LANGS = ("zh-TW", "en")

# ---------------------------------------------------------------- fixed vocabularies

# Tag categories: design wording -> machine id (01-systems 2.4 / 2.8, glossary "Tag").
TAG_CATEGORIES = {"時間": "time", "地點": "place", "人物": "person", "物理": "phys", "物理特性": "phys", "醜聞": "scandal"}
CATEGORY_IDS = ("time", "place", "person", "phys", "scandal")

GRADES = {"一般": "common", "關鍵": "key", "劇情": "story", "黃金": "golden", "替代": "substitute"}
APPRAISAL = {"無": "none", "醫療": "medical", "機械": "mechanical", "雙重": "dual"}
APPRAISAL_COST = {"none": 0, "medical": 1, "mechanical": 1, "dual": 2}  # 01-systems 1.5

# Opponent actions (glossary): design wording -> machine id.
ACTIONS = {"主張": "assert", "猛攻": "rush", "補強": "reinforce", "設陷": "trap"}

# English labels used in the localization notes of the debate line library (S90) -> machine id.
LIBRARY_LABELS = {
    "Assert": "assert", "Onslaught": "rush", "Reinforce": "reinforce", "Set a Trap": "trap",
    "Scorched Earth": "scorched", "Solid Chain": "solid", "Sophistry": "sophistry", "Rebut": "rebut",
    "Observe": "observe", "Clash": "clash", "Cut-In": "cutin", "Standoff": "standoff",
    "Unstoppable 1": "unstoppable1", "Unstoppable 2": "unstoppable2", "Unstoppable 3": "unstoppable3",
    "Unstoppable": "unstoppable", "Breached": "breached", "Cornered": "cornered",
    "banner line for 論破 (Break)": "bannerBreak", "banner line for 動搖 (Shaken)": "bannerShaken",
    "banner line for 破竹 (Unstoppable)": "bannerUnstoppable",
    "Unstoppable (preview)": "unstoppablePreview", "Cornered, Breached": "corneredBreached",
}

# Leading-parenthesis tokens in debate / warm-up lines of the script -> act cue.
ACT_TOKENS = {
    "預兆": "tell", "預兆・動搖": "tell", "主張": "assert", "猛攻": "rush", "補強": "reinforce", "設陷": "trap",
    "反駁": "rebut", "反駁論破": "rebutBreak", "實證連鎖": "solid", "實證連鎖論破": "solidBreak",
    "詭辯": "sophistry", "觀察": "observe", "截斷": "cutin", "動搖": "shaken", "提示": "hint",
    "誤判": "misjudge", "鑑定後": "appraised", "尾聲・玉石俱焚": "tail", "出示": "present",
}

# Scene heading text (script L001) -> step kind / sub label.
SCENE_KINDS = (
    ("報紙頭版", "paper", "open"), ("熱身小論戰", "warmup", ""), ("主論戰", "debate", ""),
    ("蒐證", "investigate", ""), ("結算", "result", ""), ("結案筆記", "vn", "notes"),
    ("日常", "vn", "daily"), ("事件", "vn", "event"),
)

# Scripted pseudo-speakers -> script kind (they get no SPK_ key).
PSEUDO_SPEAKERS = {"（場景標題）": "heading", "（證物描述）": "evidence", "（演出）": "staging",
                   "（分支）": "branch", "（備註）": "note"}

# ---------------------------------------------------------------- hand-mapped design data
# Scene slugs for the 10-cases 「場景與登場人物」 rows (identifiers only; no display text exists).
SCENE_SLUGS = {
    "事務所廚房兼客廳": "kitchen", "報時鳥鐘錶店（事務所樓下）": "clock_shop",
    "駁船鍋爐室": "boiler_room", "駁船甲板": "deck", "碼頭": "dock",
}

# Investigation point (10-cases) -> evidence it yields. [] = inspect point (no card).
# Points not listed in 10-cases but needed for an evidence card are EXTRA (see EXTRA_HOTSPOTS).
# Every entry is listed under 待確認 in docs/data-schema.md.
POINT_YIELDS = {
    1: {"冰箱": ["E01_02"], "空布丁盤": ["E01_01"], "廚房地板": ["E01_04"], "亞瑟房門": ["E01_05"],
        "外套口袋": ["E01_06"], "大門門縫": ["E01_07"]},
    2: {"報時鳥鐘": ["E02_02"], "鐘擺護蓋": ["E02_03"], "櫃台": [], "寄修收據簿": ["E02_05"],
        "零件櫃與目錄": ["E02_06"], "角落咖啡座": []},
    3: {"屍體": ["E03_01", "E03_07"], "從內側落下的門閂": ["E03_02"], "洩壓閥": ["E03_04"], "貨箱": [],
        "壓力閥門": ["E03_03"], "航行日誌": ["E03_08"], "纜繩": [],
        "煤灰腳印": [], "警方臨時拘留處": ["E03_05"], "市政公告欄": ["E03_09"]},
}
# (chapter, scene slug, label for docs, yields, type, requires)
EXTRA_HOTSPOTS = [
    (1, "kitchen", "亞瑟袖口", ["E01_03"], "evidence", ""),
    (2, "clock_shop", "替換機芯", ["E02_01"], "evidence", ""),
    (2, "clock_shop", "報童小湯米", ["E02_04"], "testimony", ""),
    (2, "clock_shop", "費奇袖口", ["E02_07"], "evidence", ""),
    (3, "boiler_room", "次級替代證物（G-01 缺少時出現，01-systems 1.9）", ["S-01"], "evidence", "missing:G-01"),
    (3, "dock", "皮爾斯大衣下擺", ["E03_06"], "evidence", ""),
]
# Evidence not obtained from a hotspot.
OBTAIN_OVERRIDE = {"E02_08": "afterDebate"}  # script Ch.2 S04: 「（論戰後取得）」

# Ruling C1 / C2 (docs/rulings.md) and explicit 強攻 marks in 10-cases.
STRONG = {"E01_03", "E02_01", "E03_04", "G-01"}
# Ruling D2: required evidence per case. Required cards are never opponent-obtainable (ruling D3).
REQUIRED = {"E01_03", "E02_02", "E02_06", "E03_02", "E03_07"}
# Golden output of key evidence (10-cases 結算・黃金線索).
GOLDEN_OUT = {"E02_01": "G-01"}
# Ruling C3: endgame second-claim refuters.
TAIL_REFUTERS = {2: ["E02_07", "E02_01"], 3: ["E03_05", "E03_03"]}
# Warm-up (10-cases Ch.3 熱身; ruling B16: a single card, either one).
WARMUP = {3: {"refuters": ["E03_05", "E03_02"], "hand": ["E03_05", "E03_02"]}}

# VN staging vocabularies (docs/ui-contracts.md, vn section). Characters without a standee yet use a slug of
# their English name so the UI can add the standee later.
STAGING_BGS = {"", "office_night", "office_day", "kitchen_morning", "clockshop", "dock_fog", "barge_deck",
               "boiler_room", "debate"}
STAGING_CHARS = {"sherefox", "arthur", "baskerville", "victor", "wolfhart", "valet", "partner"}
STAGING_PLACEHOLDER_CHARS = {"holloway", "gresham", "tommy", "old_tom"}
STAGING_COLUMNS = ["id", "bg", "slot_l", "slot_c", "slot_r", "focus", "style", "note"]
STAGING_STYLES = (0, 1, 2)

# ---------------------------------------------------------------- helpers

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO(read_text(path))))


def md_section(text: str, heading_re: str) -> str:
    """Body of the first markdown section whose heading matches, up to the next heading of the same or higher level."""
    m = re.search(heading_re, text, re.M)
    if not m:
        raise SystemExit(f"design snapshot: heading not found: {heading_re}")
    level = len(re.match(r"#+", text[m.start():]).group(0))
    rest = text[m.end():]
    nxt = re.search(r"^#{1,%d} " % level, rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def md_rows(section: str) -> list[list[str]]:
    rows = []
    for line in section.splitlines():
        line = line.strip()
        if line.startswith("|") and not re.match(r"^\|\s*:?-{3}", line):
            rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows


def leading_int(cell: str, default: int | None = None) -> int:
    m = re.match(r"\s*(-?\d+)", cell)
    if m:
        return int(m.group(1))
    if default is None:
        raise SystemExit(f"design snapshot: expected a number, got {cell!r}")
    return default


def slug_upper(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text.replace("'", "")).strip("_").upper()


def ch_key(c: int) -> str:
    return f"CH{c:02d}"


# ---------------------------------------------------------------- design snapshot parsing

def parse_systems() -> dict:
    text = read_text(DESIGN / "01-systems.md")
    scale = {}
    for row in md_rows(md_section(text, r"^### 1\.3 ")):
        m = re.match(r"Ch\.(\d+) ", row[0])
        if m and int(m.group(1)) in CHAPTERS:
            c = int(m.group(1))
            scale[c] = {
                "scenes": leading_int(row[1]), "hotspots": leading_int(row[2]),
                "common": leading_int(row[3]), "key": leading_int(row[4]), "story": leading_int(row[5]),
                "ticks": -1 if row[6].startswith("不限") else leading_int(row[6]),
                "appraisals": leading_int(row[7]),
            }
    reveal = {}
    for row in md_rows(md_section(text, r"^### 1\.5 ")):
        kind = {"醫療鑑定": "medical", "機械鑑定": "mechanical", "雙重鑑定": "dual"}.get(row[0])
        if kind and kind != "dual":
            reveal[kind] = [TAG_CATEGORIES[c] for c in re.findall(r"【(.+?)】", row[2])]
    reveal["dual"] = sorted(set(reveal["medical"]) | set(reveal["mechanical"]), key=CATEGORY_IDS.index)
    reveal["none"] = []
    for c in CHAPTERS:
        if c not in scale:
            raise SystemExit(f"01-systems 1.3: no row for Ch.{c}")
    return {"scale": scale, "reveal": reveal}


def parse_numbers() -> dict:
    text = read_text(DESIGN / "02-numbers.md")
    core = {}
    for row in md_rows(md_section(text, r"^## 一、")):
        core[row[0]] = row[1]  # 前期 column
    early = {
        "playerHp": leading_int(core["玩家主導權"]),
        "breakPct": leading_int(core["論破扣血（對手最大主導權）"]),
        "breakLine": 0 if core["破防線（4 張以上實證連鎖觸發動搖的條件）"] == "無" else leading_int(core["破防線（4 張以上實證連鎖觸發動搖的條件）"]),
        "tailPenalty": int(re.search(r"(\d+)", core["尾聲應對錯誤"]).group(1)),
        "tailRounds": leading_int(core["尾聲長度"]),
        "clarity": [int(x) for x in core["預兆清晰度（明示／模糊／偽裝）"].split("／")],
    }
    weights = {}
    for row in md_rows(md_section(text, r"^## 四、")):
        t = {"犯人型": "culprit", "庇護者型": "protector"}.get(row[0])
        if t:
            weights[t] = [int(x) for x in row[1:5]]
    cases = {}
    for row in md_rows(md_section(text, r"^## 五、")):
        m = re.match(r"Ch\.(\d+)$", row[0])
        if m and int(m.group(1)) in CHAPTERS:
            c = int(m.group(1))
            base = re.match(r"(\d+) \+ 4n", row[4])
            cases[c] = {"hp": leading_int(row[2], 0), "nodeCap": leading_int(row[3]),
                        "base": int(base.group(1)) if base else 0}
    return {"early": early, "weights": weights, "cases": cases}


def parse_cases() -> dict:
    text = read_text(DESIGN / "10-cases-ch01-04.md")
    out = {}
    for c in CHAPTERS:
        body = md_section(text, rf"^## Ch\.{c} ")
        scenes = []
        for row in md_rows(md_section(body, r"^### 場景與登場人物"))[1:]:
            if row[0] == "人物":
                break
            scenes.append((row[0], [p.strip() for p in row[1].split("、")]))
        evidence = {}
        for row in md_rows(md_section(body, r"^### 證物表"))[1:]:
            evidence[row[0]] = {"grade": row[2], "tags": row[3], "appraisal": row[4]}
        behaviour = {}
        for row in md_rows(md_section(body, r"^#### 對手行為表"))[1:]:
            behaviour[row[0]] = row[1]
        out[c] = {"scenes": scenes, "evidence": evidence, "behaviour": behaviour}
    return out


def parse_gestures(cell: str) -> dict:
    res = {}
    for part in cell.split("；"):
        if "＝" in part:
            k, v = part.split("＝", 1)
            if k.strip() in ACTIONS:
                res[ACTIONS[k.strip()]] = v.strip()
    return res


def parse_rules(cell: str) -> str:
    stripped = re.sub(r"（[^）]*）", "", cell)
    nums = re.findall(r"(?<![\d.])([1-5])(?![\d.%])", stripped)
    return ",".join(sorted(set(nums), key=int))


# ---------------------------------------------------------------- localization loading

def load_localization() -> dict:
    strings = json.loads(read_text(LOC / "strings.json"))
    evidence_rows = read_csv(LOC / "evidence_ch01-03.csv")
    script_rows = read_csv(LOC / "script_ch01-03.csv")
    ui_rows = read_csv(LOC / "ui_strings.csv")
    return {"strings": strings, "evidence": {r["ID"]: r for r in evidence_rows},
            "script": script_rows, "ui": ui_rows}


def load_tags() -> list[dict]:
    if not TAG_FILE.exists():
        raise SystemExit(f"missing {TAG_FILE.relative_to(ROOT)}; run with --make-tag-placeholder")
    rows = []
    for i, r in enumerate(read_csv(TAG_FILE), start=2):
        if not r.get("owner", "").strip() or r["owner"].lstrip().startswith("#"):
            continue
        rows.append({k: (v or "").strip() for k, v in r.items()} | {"_line": i})
    return rows


# ---------------------------------------------------------------- builders

def build_tags(tag_rows: list[dict], reveal: dict, appraisal_of: dict) -> dict:
    """owner -> {"tags": [...], "grazing": [...], "hidden": [...]} in file order."""
    out: dict[str, dict] = {}
    for r in tag_rows:
        where = f"{TAG_FILE.name}:{r['_line']}"
        cat = TAG_CATEGORIES.get(r.get("category", ""))
        if not cat:
            err(f"{where}: unknown tag category {r.get('category')!r}")
            continue
        value, slug = r.get("value", ""), r.get("slug", "")
        if value and not slug:
            err(f"{where}: tag value {value!r} needs an ASCII slug")
            continue
        if slug and not re.fullmatch(r"[a-z0-9_]+", slug):
            err(f"{where}: slug {slug!r} must match [a-z0-9_]+")
            continue
        tag = f"{cat}:{slug}" if slug else cat
        entry = out.setdefault(r["owner"], {"tags": [], "grazing": [], "hidden": []})
        if tag in entry["tags"]:
            err(f"{where}: duplicate tag {tag} on {r['owner']}")
            continue
        entry["tags"].append(tag)
        if r.get("grazing", "").lower() in ("擦邊", "1", "true", "yes", "y"):
            entry["grazing"].append(tag)
        hidden = r.get("hidden", "").lower()
        if hidden in ("yes", "1", "true"):
            entry["hidden"].append(tag)
        elif hidden in ("", "auto"):
            if cat in reveal.get(appraisal_of.get(r["owner"], "none"), []):
                entry["hidden"].append(tag)
        elif hidden not in ("no", "0", "false"):
            err(f"{where}: hidden must be auto/yes/no, got {hidden!r}")
    return out


def reason_order(eid: str) -> tuple[list[str], int]:
    """Fixed display order: correct slot = first byte of SHA-256(id) mod 3; B then C fill the other slots."""
    correct = hashlib.sha256(eid.encode("utf-8")).digest()[0] % 3
    wrong = iter([f"{eid}_REASON_B", f"{eid}_REASON_C"])
    keys = [f"{eid}_REASON_A" if i == correct else next(wrong) for i in range(3)]
    return keys, correct


def build_script(loc: dict, banners: dict) -> tuple[list[dict], dict]:
    rows = []
    info = {"scenes": {}, "speakers": {}, "evidence_lines": {}, "appraisal_line": {}}
    for r in loc["script"]:
        m = re.fullmatch(r"SCR_CH(\d\d)_S(\d\d)_L(\d{3})", r["ID"])
        if not m:
            err(f"script: bad id {r['ID']}")
            continue
        c, s, l = int(m.group(1)), int(m.group(2)), int(m.group(3))
        rows.append((c, s, l, r))
    rows.sort(key=lambda t: (t[0], t[1], t[2]))
    out = []
    state = {}
    for c, s, l, r in rows:
        scene = f"S{s:02d}"
        skey = (c, scene)
        zh, note = r["zh-TW"], r["note"]
        kind = PSEUDO_SPEAKERS.get(r["speaker_zh"], "line")
        if kind == "heading" and l != 1:
            kind = "subheading"
        if l == 1:
            if kind != "heading":
                err(f"script: {r['ID']} is L001 but not a scene heading")
            step_kind, sub = "", ""
            if s != 90:
                for word, k, sb in SCENE_KINDS:
                    if word in zh:
                        step_kind, sub = k, sb
                        break
                if not step_kind:
                    err(f"script: cannot classify scene heading {r['ID']} {zh!r}")
            info["scenes"][skey] = {"kind": step_kind or "library", "sub": sub, "heading": r["ID"]}
            state = {"branch": "", "round": 0}
        speaker = ""
        if kind == "line":
            speaker = "SPK_" + slug_upper(r["speaker_en"])
            info["speakers"].setdefault(speaker, (r["speaker_zh"], r["speaker_en"]))
        if kind == "branch":
            state["branch"] = {"勝利": "win", "敗北": "lose"}.get(zh.strip(), "")
            if not state["branch"]:
                err(f"script: unknown branch label {zh!r} in {r['ID']}")
        scene_kind = info["scenes"].get(skey, {}).get("kind", "")
        evidence, act, node, banner = [], "", "", []
        appraisal = "appraisal" in [seg.strip() for seg in note.split("|")]
        nm = re.search(r"\bevidence ((?:E\d\d_\d\d)|(?:G-\d\d))\b", note)
        if nm:
            evidence.append(nm.group(1))
            info["evidence_lines"].setdefault(nm.group(1), [])
            if appraisal:
                info["appraisal_line"][nm.group(1)] = r["ID"]
            else:
                info["evidence_lines"][nm.group(1)].append(r["ID"])
        if scene_kind in ("debate", "warmup") and kind == "line":
            rm = re.match(r"（第 (\d+) 回合", zh)
            if rm:
                state["round"] = int(rm.group(1))
            pm = re.match(r"（([^）]*)）", zh)
            if pm and not rm:
                inner = pm.group(1)
                for tok in inner.split("，"):
                    word = tok.strip().split(" ")[0]
                    if word in ACT_TOKENS:
                        act = ACT_TOKENS[word]
                        break
                if act:
                    for e in re.findall(r"E\d\d_\d\d|G-\d\d", inner):
                        if e not in evidence:
                            evidence.append(e)
                    nn = re.search(r"N(\d)", inner)
                    if nn:
                        node = f"{ch_key(c)}_N{nn.group(1)}"
            if not node:
                nn = re.search(r"亮起節點：N(\d)", zh)
                if nn:
                    node = f"{ch_key(c)}_N{nn.group(1)}"
        if kind == "staging":
            for tier, word in re.findall(r"【(大字|印)：([^】]+)】", zh):
                name = re.sub(r"×\d+$", "", word)
                key = banners.get((tier, name))
                if key:
                    banner.append(key)
                else:
                    err(f"script: {r['ID']} banner 【{tier}：{word}】 has no CUT_/STAMP_ key")
        inactive = any(seg.strip().startswith("Not triggered") or "not yet unlocked" in seg for seg in note.split("|"))
        out.append({
            "id": r["ID"], "chapter": c, "scene": scene, "seq": l, "kind": kind, "speaker": speaker,
            "text": r["ID"], "branch": state.get("branch", ""),
            "round": state.get("round", 0) if scene_kind in ("debate", "warmup") else 0,
            "act": act, "node": node, "evidence": ",".join(evidence), "appraisal": appraisal,
            "banner": ",".join(banner), "inactive": inactive,
        })
    return out, info


def merge_staging(script: list[dict]) -> None:
    """Add bg / slot_l / slot_c / slot_r / focus / style to every script row from the staging file."""
    if not STAGING_FILE.exists():
        err(f"staging: {STAGING_FILE.relative_to(ROOT)} not found")
        return
    rows = read_csv(STAGING_FILE)
    if rows and list(rows[0].keys()) != STAGING_COLUMNS:
        err(f"staging: header must be {','.join(STAGING_COLUMNS)}, got {','.join(rows[0].keys())}")
        return
    by_id: dict[str, dict] = {}
    for r in rows:
        if r["id"] in by_id:
            err(f"staging: duplicate row for {r['id']}")
        by_id[r["id"]] = r
    script_ids = {s["id"] for s in script}
    for sid in sorted(by_id.keys() - script_ids):
        err(f"staging: {sid} is not a script id")
    chars = STAGING_CHARS | STAGING_PLACEHOLDER_CHARS
    for line in script:
        r = by_id.get(line["id"])
        if r is None:
            err(f"staging: no row for script line {line['id']}")
            line.update({"bg": "", "slot_l": "", "slot_c": "", "slot_r": "", "focus": 0, "style": 0})
            continue
        slots = [r["slot_l"], r["slot_c"], r["slot_r"]]
        if r["bg"] not in STAGING_BGS:
            err(f"staging {r['id']}: unknown bg {r['bg']!r}")
        for name, cid in zip(("slot_l", "slot_c", "slot_r"), slots):
            if cid and cid not in chars:
                err(f"staging {r['id']}: unknown character id {cid!r} in {name}")
        shown = [c for c in slots if c]
        if len(shown) != len(set(shown)):
            err(f"staging {r['id']}: the same character stands in two slots")
        try:
            focus, style = int(r["focus"]), int(r["style"])
        except ValueError:
            err(f"staging {r['id']}: focus and style must be integers")
            focus, style = 0, 0
        if focus not in (0, 1, 2, 3):
            err(f"staging {r['id']}: focus {focus} not in 0..3")
        elif focus and not slots[focus - 1]:
            err(f"staging {r['id']}: focus {focus} points at an empty slot")
        if style not in STAGING_STYLES:
            err(f"staging {r['id']}: style {style} not in 0..2")
        line.update({"bg": r["bg"], "slot_l": slots[0], "slot_c": slots[1], "slot_r": slots[2],
                     "focus": focus, "style": style})


def build_tells(loc: dict, script_rows: list[dict]) -> tuple[list[dict], dict]:
    by_id = {r["ID"]: r for r in loc["script"]}
    tells, gesture_en = [], {}
    counters: dict[str, int] = {}
    last_sub: dict[tuple, str] = {}
    for row in script_rows:
        if row["scene"] != "S90" or row["kind"] in ("heading", "note"):
            continue
        src = by_id[row["id"]]
        segs = [s.strip() for s in src["note"].split("|")]
        head, rest = segs[0], segs[1:]
        category, action = "", ""
        m = re.match(r"Tell line: (.+?) \(gesture: (.+)\)$", head)
        if m:
            category, action = "tell", LIBRARY_LABELS.get(m.group(1), "")
            gesture_en.setdefault((row["chapter"], action), m.group(2))
        elif (m := re.match(r"(Action|Endgame) line: (.+)$", head)):
            category, action = m.group(1).lower(), LIBRARY_LABELS.get(m.group(2), "")
        else:
            for prefix, cat in (("Sherefox action line", "sfAction"), ("Reaction line", "reaction"),
                                ("Tutorial hint line", "tutorialHint"), ("Cornered", "cornered"),
                                ("Taunt when Breached", "taunt"), ("Sherefox state line", "sfState"),
                                ("State tutorial hint", "stateHint"), ("Arthur Tell-hint line", "arthurHint"),
                                ("Arthur state line", "arthurState")):
                if head.startswith(prefix):
                    category = cat
                    break
            for seg in rest:
                if seg.startswith("action: "):
                    action = LIBRARY_LABELS.get(seg[8:], "")
                elif seg in LIBRARY_LABELS:
                    action = LIBRARY_LABELS[seg]
            key = (row["chapter"], category)
            if action:
                last_sub[key] = action
            elif category in ("sfAction", "reaction", "sfState", "arthurState", "stateHint"):
                action = last_sub.get(key, "")
        if not category:
            err(f"tells: cannot classify library line {row['id']} note {src['note']!r}")
            continue
        case = f"{ch_key(row['chapter'])}_MAIN"
        group = f"{case}:{category}:{action}"
        n = counters.get(group, 0)
        counters[group] = n + 1
        gesture = f"GST_{ch_key(row['chapter'])}_{action.upper()}" if category == "tell" else ""
        tells.append({"id": row["id"], "chapter": row["chapter"], "case": case, "category": category,
                      "action": action, "speaker": row["speaker"], "text": row["id"], "gesture": gesture,
                      "inactive": row["inactive"], "group": group, "n": n})
    for t in tells:
        t["groupSize"] = counters[t["group"]]
    return tells, gesture_en


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate only, write nothing")
    ap.add_argument("--import-localization", metavar="DIR", help="copy a localization package into source/localization/")
    ap.add_argument("--make-tag-placeholder", action="store_true", help="write the category-only placeholder tag file")
    ap.add_argument("--force", action="store_true", help="with --make-tag-placeholder: overwrite an existing file")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if args.import_localization:
        src = Path(args.import_localization)
        LOC.mkdir(parents=True, exist_ok=True)
        for name in ("README.md", "strings.json", "ui_strings.csv", "tutorial.csv",
                     "evidence_ch01-03.csv", "script_ch01-03.csv", "glossary.csv"):
            shutil.copyfile(src / name, LOC / name)
        print(f"imported localization from {src}")

    systems = parse_systems()
    numbers = parse_numbers()
    cases = parse_cases()
    loc = load_localization()
    strings: dict[str, dict] = {k: dict(v) for k, v in loc["strings"].items()}
    ev_loc = loc["evidence"]

    # ---- evidence base data from the localization package (NAME note carries grade / appraisal)
    ev_ids = sorted({m.group(1) for k in ev_loc if (m := re.fullmatch(r"(E\d\d_\d\d)_NAME", k))})
    base = {}
    for eid in ev_ids:
        note = ev_loc[f"{eid}_NAME"]["note"]
        g = re.search(r"grade: (\S+)", note)
        a = re.search(r"appraisal: (\S+)", note)
        grade = GRADES.get(g.group(1) if g else "", "")
        appraisal = APPRAISAL.get(a.group(1) if a else "", "")
        if not grade or not appraisal:
            err(f"evidence {eid}: cannot read grade/appraisal from note {note!r}")
        cats = [TAG_CATEGORIES.get(x) for x in ev_loc[f"{eid}_TAGS"]["zh-TW"].split("・")]
        if None in cats:
            err(f"evidence {eid}: unknown tag category in {ev_loc[eid + '_TAGS']['zh-TW']!r}")
        base[eid] = {"chapter": int(eid[1:3]), "grade": grade, "appraisal": appraisal, "cats": cats}
        d = cases[int(eid[1:3])]["evidence"].get(eid)
        if not d:
            warn(f"evidence {eid}: not in the 10-cases evidence table")
        else:
            if GRADES.get(d["grade"]) != grade or APPRAISAL.get(d["appraisal"]) != appraisal \
                    or [TAG_CATEGORIES.get(x) for x in d["tags"].split("・")] != cats:
                warn(f"evidence {eid}: localization grade/appraisal/tags differ from 10-cases")
    base["G-01"] = {"chapter": 2, "grade": "golden", "appraisal": "none", "cats": ["phys", "scandal"]}  # ruling C2
    base["S-01"] = {"chapter": 3, "grade": "substitute", "appraisal": "none", "cats": ["phys", "scandal"]}

    # ---- nodes (claim nodes from the CLM_ notes; tail and warm-up nodes from rulings C3 / B16)
    node_rows_src = []
    for k, r in ev_loc.items():
        m = re.fullmatch(r"CLM_CH(\d\d)_N(\d)", k)
        if m:
            note = r["note"]
            truth_m = re.search(r"truth: (\S)", note)
            ref_m = re.search(r"refuted by: (.*)$", note)
            refs = re.findall(r"E\d\d_\d\d|G-\d\d", ref_m.group(1) if ref_m else "")
            node_rows_src.append((int(m.group(1)), "claim", int(m.group(2)), k, truth_m and truth_m.group(1) == "真", refs))
    node_rows_src.sort(key=lambda t: (t[0], t[2]))

    tag_rows = load_tags() if not args.make_tag_placeholder else []
    script_rows_tmp = []  # filled below

    # ---- banners (CUT_ = 大字, STAMP_ = 印)
    banners = {}
    for r in loc["ui"]:
        m = re.fullmatch(r"(CUT|STAMP)_[A-Z0-9_]+", r["ID"])
        if m and not r["ID"].endswith(("_LOG", "_SUB")):
            banners[("大字" if m.group(1) == "CUT" else "印", r["zh-TW"])] = r["ID"]

    script, sinfo = build_script(loc, banners)
    merge_staging(script)
    tells, gesture_en = build_tells(loc, script)

    # Tail node text: first endgame line of the chapter library; warm-up node text: the 誤判 line.
    for c in CHAPTERS:
        if c in TAIL_REFUTERS:
            line = next((t["id"] for t in tells if t["chapter"] == c and t["category"] == "endgame"), "")
            node_rows_src.append((c, "tail", 1, line, False, TAIL_REFUTERS[c]))
        if c in WARMUP:
            line = next((s["id"] for s in script if s["chapter"] == c and s["act"] == "misjudge"), "")
            node_rows_src.append((c, "warmup", 1, line, False, WARMUP[c]["refuters"]))

    def node_id(c, kind, idx):
        return f"{ch_key(c)}_{ {'claim': 'N', 'tail': 'T', 'warmup': 'W'}[kind] }{idx}"

    # ---- placeholder tag file
    if args.make_tag_placeholder:
        if TAG_FILE.exists() and not args.force:
            print(f"{TAG_FILE.relative_to(ROOT)} exists; use --force to overwrite")
            return 1
        zh_cat = {"time": "時間", "place": "地點", "person": "人物", "phys": "物理", "scandal": "醜聞"}
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["owner", "category", "value", "slug", "grazing", "hidden", "note"])
        for eid in list(ev_ids) + ["G-01", "S-01"]:
            for cat in base[eid]["cats"]:
                w.writerow([eid, zh_cat[cat], "", "", "", "auto", "PLACEHOLDER category only"])
        for c, kind, idx, _k, _t, refs in node_rows_src:
            cats = []
            for e in refs:
                for cat in base.get(e, {}).get("cats", []):
                    if cat not in cats:
                        cats.append(cat)
            for cat in cats:
                w.writerow([node_id(c, kind, idx), zh_cat[cat], "", "", "", "no",
                            "PLACEHOLDER category only; copied from refuting evidence until the 標籤值 table lands"])
        TAG_FILE.parent.mkdir(parents=True, exist_ok=True)
        TAG_FILE.write_text(buf.getvalue(), encoding="utf-8", newline="\n")
        print(f"wrote {TAG_FILE.relative_to(ROOT)}")
        return 0

    appraisal_of = {e: b["appraisal"] for e, b in base.items()}
    tags = build_tags(tag_rows, systems["reveal"], appraisal_of)
    for owner in tags:
        known = owner in base or any(owner == node_id(c, k, i) for c, k, i, *_ in node_rows_src)
        if not known:
            err(f"{TAG_FILE.name}: unknown owner {owner}")
    placeholder_tags = any("PLACEHOLDER" in r.get("note", "") for r in tag_rows)

    # ---- nodes table
    nodes = []
    refutes_of: dict[str, list[str]] = {}
    for c, kind, idx, text_key, truth, refs in node_rows_src:
        nid = node_id(c, kind, idx)
        case = f"{ch_key(c)}_{'WARMUP' if kind == 'warmup' else 'MAIN'}"
        t = tags.get(nid, {"tags": [], "grazing": []})
        if not t["tags"]:
            warn(f"node {nid}: no tags (attacks cannot target it until tags are given)")
        nodes.append({"id": nid, "chapter": c, "case": case, "kind": kind, "idx": idx, "textKey": text_key,
                      "tags": ",".join(t["tags"]), "grazingTags": ",".join(t["grazing"]),
                      "truth": bool(truth), "refutable": bool(refs), "refutedBy": ",".join(refs)})
        for e in refs:
            refutes_of.setdefault(e, []).append(nid)

    # ---- hotspots
    hotspots = []
    yielded: dict[str, str] = {}
    hotspot_doc = []  # (id, label) for the schema doc
    for c in CHAPTERS:
        design_scenes = cases[c]["scenes"]
        seen_points = set()
        per_scene: dict[str, list] = {}
        for scene_name, points in design_scenes:
            slug = SCENE_SLUGS.get(scene_name)
            if not slug:
                err(f"10-cases Ch.{c}: scene {scene_name!r} has no slug")
                continue
            for p in points:
                if p not in POINT_YIELDS[c]:
                    err(f"10-cases Ch.{c}: investigation point {p!r} has no mapping in POINT_YIELDS")
                    continue
                seen_points.add(p)
                ys = POINT_YIELDS[c][p]
                typ = "evidence" if ys else "inspect"
                per_scene.setdefault(slug, []).append((p, ys, typ, ""))
        for p in POINT_YIELDS[c]:
            if p not in seen_points:
                err(f"POINT_YIELDS Ch.{c}: point {p!r} not in the 10-cases scene table")
        for ec, slug, label, ys, typ, req in EXTRA_HOTSPOTS:
            if ec == c:
                per_scene.setdefault(slug, []).append((label + "（額外）", ys, typ, req))
        n = 0
        for scene_name, _ in design_scenes:
            slug = SCENE_SLUGS.get(scene_name)
            for i, (label, ys, typ, req) in enumerate(per_scene.get(slug, [])):
                n += 1
                hid = f"H{c:02d}_{n:02d}"
                lines = [ln for e in ys for ln in sinfo["evidence_lines"].get(e, [])]
                for e in ys:
                    if e in yielded:
                        err(f"hotspots: {e} yielded by both {yielded[e]} and {hid}")
                    yielded[e] = hid
                hotspots.append({"id": hid, "chapter": c, "scene": slug, "area": 0, "type": typ,
                                 "yields": ",".join(ys), "lines": ",".join(lines), "requires": req,
                                 "x": 100 + (i % 4) * 280, "y": 140 + (i // 4) * 200, "w": 160, "h": 120,
                                 "placeholder": True})
                hotspot_doc.append((hid, scene_name, label))

    # ---- evidence table
    evidence = []
    for eid in list(ev_ids) + ["G-01", "S-01"]:
        b = base[eid]
        t = tags.get(eid, {"tags": [], "grazing": [], "hidden": []})
        if not t["tags"]:
            err(f"evidence {eid}: no tags in {TAG_FILE.name}")
        got_cats = sorted({x.split(":")[0] for x in t["tags"]})
        if got_cats != sorted(set(b["cats"])):
            warn(f"evidence {eid}: tag categories {got_cats} differ from the design categories {sorted(set(b['cats']))}")
        is_card = b["grade"] in ("common", "key", "story")
        if is_card:
            keys, correct = reason_order(eid)
        else:
            keys, correct = ["", "", ""], -1
        grade = b["grade"]
        if eid in OBTAIN_OVERRIDE:
            obtain = OBTAIN_OVERRIDE[eid]
        elif grade == "golden":
            obtain = "golden"
        elif eid in yielded:
            obtain = "hotspot"
        else:
            obtain = ""
            err(f"evidence {eid}: no hotspot yields it and no other source is defined")
        usable = "3,12" if eid == "G-01" else str(b["chapter"])
        name_key = {"G-01": "G-01", "S-01": "G-01_SUB"}.get(eid, f"{eid}_NAME")
        evidence.append({
            "id": eid, "chapter": b["chapter"], "usable": usable, "grade": grade,
            "nameKey": name_key, "descKey": f"{eid}_DESC" if is_card else "",
            "tagsKey": f"{eid}_TAGS" if is_card else "",
            "tags": ",".join(t["tags"]), "hiddenTags": ",".join(t["hidden"]), "grazingTags": ",".join(t["grazing"]),
            "appraise": b["appraisal"], "appraiseCost": APPRAISAL_COST[b["appraisal"]],
            "appraisalKey": sinfo["appraisal_line"].get(eid, ""),
            "reason0Key": keys[0], "reason1Key": keys[1], "reason2Key": keys[2], "correct": correct,
            "onBoard": grade != "story",
            "strong": eid in STRONG, "scandal": "scandal" in b["cats"], "motive": False,
            "offChain": grade == "golden", "required": eid in REQUIRED,
            # Ruling D3: common and key cards are obtainable; story / golden / substitute are not. D2 overrides.
            "obtainable": grade in ("common", "key") and eid not in REQUIRED,
            "refutes": ",".join(refutes_of.get(eid, [])), "golden": GOLDEN_OUT.get(eid, ""),
            "obtain": obtain, "hotspot": yielded.get(eid, ""),
            "lines": ",".join(sinfo["evidence_lines"].get(eid, [])),
        })
        if b["appraisal"] != "none" and not sinfo["appraisal_line"].get(eid):
            warn(f"evidence {eid}: appraisal {b['appraisal']} but no appraisal line in the script")

    # ---- opponents
    early = numbers["early"]
    opponents = []
    for c in CHAPTERS:
        beh = cases[c]["behaviour"]
        gest = parse_gestures(beh.get("小動作預兆", ""))
        nc = numbers["cases"][c]
        if c == 1:
            # 庇護者 weights with the actions Arthur does not use (10-cases Ch.1) set to 0.
            w = list(numbers["weights"]["protector"])
            w[1] = w[3] = 0
            typ, clarity, kind = "protector", [100, 0, 0], "pudding"
        else:
            w = list(numbers["weights"]["culprit"])  # ruling B15
            typ, clarity, kind = "culprit", early["clarity"], "main"
        speaker = {1: "SPK_ARTHUR", 2: "SPK_FITCH", 3: "SPK_PIERCE"}[c]
        opponents.append({
            "id": f"{ch_key(c)}_MAIN", "chapter": c, "kind": kind, "speaker": speaker, "type": typ,
            "hp": nc["hp"], "playerHp": 0 if c == 1 else early["playerHp"], "noDamage": c == 1,
            "nodeCap": nc["nodeCap"], "damageBase": nc["base"], "damagePerNode": 4 if nc["base"] else 0,
            "rushMul": 1.25, "w_claim": w[0], "w_rush": w[1], "w_reinforce": w[2], "w_trap": w[3],
            "clear": clarity[0], "fuzzy": clarity[1], "disguise": clarity[2],
            "rules": parse_rules(beh.get("適用行為規則", "")), "ruleBias": 80, "mirror": False,
            "gestureAssert": f"GST_{ch_key(c)}_ASSERT" if "assert" in gest else "",
            "gestureRush": f"GST_{ch_key(c)}_RUSH" if "rush" in gest else "",
            "gestureReinforce": f"GST_{ch_key(c)}_REINFORCE" if "reinforce" in gest else "",
            "gestureTrap": f"GST_{ch_key(c)}_TRAP" if "trap" in gest else "",
            "playerActions": "solid,rebut,observe" if c == 1 else "solid,sophistry,rebut,observe",
            "tail": "" if c == 1 else "scorched", "tailNode": "" if c == 1 else node_id(c, "tail", 1),
            "roundLimit": 3 if c == 1 else 0, "contraTarget": 2 if c == 1 else 0, "mistakeLimit": 0,
            "hand": "", "handPerMissed": 0 if c == 1 else 1, "hpPerMissed": 0 if c == 1 else 10,
        })
        for act, zh in gest.items():
            key = f"GST_{ch_key(c)}_{act.upper()}"
            en = gesture_en.get((c, act))
            if not en:
                err(f"gesture {key}: no English gesture in the S90 tell notes")
                en = ""
            strings[key] = {"zh-TW": zh, "en": en}
        if c in WARMUP:
            opponents.append({
                "id": f"{ch_key(c)}_WARMUP", "chapter": c, "kind": "warmup", "speaker": "SPK_INSPECTOR_BASKERVILLE",
                "type": "", "hp": 0, "playerHp": 0, "noDamage": True, "nodeCap": 1, "damageBase": 0,
                "damagePerNode": 0, "rushMul": 1.25, "w_claim": 100, "w_rush": 0, "w_reinforce": 0, "w_trap": 0,
                "clear": 100, "fuzzy": 0, "disguise": 0, "rules": "", "ruleBias": 80, "mirror": False,
                "gestureAssert": "", "gestureRush": "", "gestureReinforce": "", "gestureTrap": "",
                "playerActions": "rebut", "tail": "", "tailNode": "", "roundLimit": 0, "contraTarget": 0,
                "mistakeLimit": 3, "hand": ",".join(WARMUP[c]["hand"]), "handPerMissed": 0, "hpPerMissed": 0,
            })

    # ---- papers (ruling D5): one paper per chapter boundary. Main headline and lead are the next chapter's
    # script S01; the sidebar carries the previous case's result (win / notorious / lose).
    papers = []
    side = {c: f"NEWS_SIDE_{c:02d}" for c in CHAPTERS}

    def page_sub(key):
        # A _SUB whose zh text starts with 第二版 is a page-two teaser, not a sub-headline: dropped here (the
        # teaser of the next case is that chapter's S01, now the main headline).
        if key in strings and not strings[key]["zh-TW"].startswith("第二版"):
            return key
        return ""

    def result_keys(c):
        # (headline, sub) for win / notorious / lose of the case that ended in chapter c.
        if f"NEWS_{c:02d}_WIN" in strings:
            return [(f"NEWS_{c:02d}_{x}", page_sub(f"NEWS_{c:02d}_{x}_SUB")) for x in ("WIN", "NOTO", "LOSE")]
        k = f"NEWS_{c:02d}_END"  # a single version fills all three slots
        return [(k, page_sub(f"{k}_SUB"))] * 3

    def paper(pid, c, kind, group, result_ch, head, sub, body, page2, res):
        row = {"id": pid, "chapter": c, "kind": kind, "group": group, "resultChapter": result_ch,
               "mastKey": "UI_PAPER_MAST", "headlineKey": head, "subKey": sub, "bodyKey": body,
               "page2Key": page2, "page2SubKey": "", "sideKey": side.get(result_ch, "")}
        for name, (hk, sk) in zip(("Win", "Noto", "Lose"), res):
            row[f"side{name}Key"] = hk
            row[f"side{name}SubKey"] = sk
        papers.append(row)

    for c in CHAPTERS:
        body = next((s["id"] for s in script if s["chapter"] == c and s["scene"] == "S01" and s["seq"] == 3), "")
        if c == 1:
            # No previous case: the sidebar is the opening city news NEWS_00_OPEN (01-systems 3.3); its ad is page two.
            res, page2 = [("NEWS_00_OPEN", "")] * 3, "NEWS_00_OPEN_SUB"
        else:
            res, page2 = result_keys(c - 1), ""
        paper(f"{ch_key(c)}_OPEN", c, "open", f"{ch_key(c)}_OPEN", c - 1, f"HEAD_{ch_key(c)}",
              f"HEAD_{ch_key(c)}_SUB", body, page2, res)
    # Ch.4's opening is out of scope: the paper that would open it is a final step headed by NEWS_03_NEXT.
    last = CHAPTERS[-1]
    paper(f"{ch_key(last)}_END", last, "transition", f"{ch_key(last)}_END", last, f"NEWS_{last:02d}_NEXT",
          page_sub(f"NEWS_{last:02d}_NEXT_SUB"), "", "", result_keys(last))

    # ---- steps
    steps = []
    for c in CHAPTERS:
        seq = []
        for (sc, scene), meta in sorted(sinfo["scenes"].items()):
            if sc != c or meta["kind"] == "library":
                continue
            k = meta["kind"]
            arg = {"paper": f"{ch_key(c)}_OPEN", "warmup": f"{ch_key(c)}_WARMUP", "debate": f"{ch_key(c)}_MAIN",
                   "investigate": ch_key(c)}.get(k, "")
            seq.append((k, scene, arg, meta["sub"]))
            if k == "investigate":
                seq.append(("board", "", ch_key(c), ""))
        if c == CHAPTERS[-1]:
            seq.append(("paper", "", f"{ch_key(c)}_END", "transition"))
        for i, (k, scene, arg, sub) in enumerate(seq):
            steps.append({"id": f"{ch_key(c)}_{i:02d}", "chapter": c, "idx": i, "kind": k, "sub": sub,
                          "scene": scene, "arg": arg})

    # ---- chapter titles (from the closing-notes line 「案件名稱：…。」 / "Case name: ….")
    for c in CHAPTERS:
        notes_scene = next((sc for (cc, sc), m in sinfo["scenes"].items() if cc == c and m["sub"] == "notes"), None)
        line = f"SCR_{ch_key(c)}_{notes_scene}_L002" if notes_scene else ""
        zh = re.match(r"案件名稱：(.+?)。", strings.get(line, {}).get("zh-TW", ""))
        en = re.match(r"Case name: (.+?)\. ", strings.get(line, {}).get("en", ""))
        if zh and en:
            strings[f"CHAP_{c:02d}_TITLE"] = {"zh-TW": zh.group(1), "en": en.group(1)}
        else:
            err(f"chapter {c}: cannot extract the case title from {line}")

    # ---- chapters
    chapters = []
    for c in CHAPTERS:
        sc = systems["scale"][c]
        chapters.append({
            "id": c, "key": ch_key(c), "titleKey": f"CHAP_{c:02d}_TITLE", "phase": "early",
            "scenes": sc["scenes"], "hotspotsDesign": sc["hotspots"], "commonDesign": sc["common"],
            "keyDesign": sc["key"], "storyDesign": sc["story"], "ticks": sc["ticks"], "appraisals": sc["appraisals"],
            "appraisalUnlocked": c >= 2, "assistUnlocked": c >= 2, "sophistry": c >= 2, "sophistryReads": False,
            "states": {1: "", 2: "hachiku"}.get(c, "hachiku,konju,shisshu"),
            "trustShown": c >= 3, "trustDebate": c >= 3, "trustNotoriety": True, "trustDeferred": c == 2,
            "police": c >= 3, "warmup": c in WARMUP, "missToHand": c >= 2,
            "playerHp": early["playerHp"], "breakPct": early["breakPct"], "breakLine": early["breakLine"],
            "breakStrong": 1, "breakChain": 2, "tailPenalty": early["tailPenalty"], "tailRounds": early["tailRounds"],
            "debate": f"{ch_key(c)}_MAIN", "openPaper": f"{ch_key(c)}_OPEN",
            "endPaper": f"{ch_key(c)}_END" if c == CHAPTERS[-1] else "",
            "next": c + 1,
        })

    # ---- difficulty (01-systems 6.1; transcribed, see docs/data-schema.md)
    difficulty = []
    for did, name, desc, v in (
        ("story", "UI_DIFF_STORY", "UI_DIFF_STORY_DESC",
         (1.5, 150, 180, 225, 0.8, 0.5, 12, 25, 12, 5, 15, 30, 40, 1, 2, 3, 20, "portrait", True, True, 4, 0, 0, True, "always", "exact", True, True, "normal")),
        ("standard", "UI_DIFF_NORMAL", "UI_DIFF_NORMAL_DESC",
         (1.0, 100, 120, 150, 1.0, 1.0, 25, 50, 25, 10, 30, 60, 80, 0, 1, 2, 0, "notes", False, True, 0, 0, 0, False, "near", "vague", False, True, "normal")),
        ("master", "UI_DIFF_MASTER", "UI_DIFF_MASTER_DESC",
         (1.0, 100, 120, 150, 1.1, 1.25, 30, 50, 30, 10, 30, 60, 80, 0, 1, 1, 0, "none", False, False, -2, -1, 1, False, "nearDim", "none", False, False, "restricted")),
    ):
        (hpMul, hpE, hpM, hpL, oppMul, claimMul, crit, c10pct, c10min, heal, tailE, tailM, tailL, tailBonus, assists,
         instinct, clearBonus, gestureHint, recommend, estimates, ticks, appr, apprMin, apprUnl, glow, remain,
         repute, retry, save) = v
        difficulty.append({
            "id": did, "nameKey": name, "descKey": desc, "playerHpMul": hpMul, "playerHpEarly": hpE,
            "playerHpMid": hpM, "playerHpLate": hpL, "oppHpMul": oppMul, "claimMul": claimMul, "rushMul": 1.25,
            "trapCrit": crit, "ch10PenaltyPct": c10pct, "ch10PenaltyMin": c10min, "parryCounter": 30,
            "reinforceHealPct": heal, "breakPctEarly": 70, "breakPctMid": 75, "breakPctLate": 80, "shakenRounds": 2,
            "tailWrongEarly": tailE, "tailWrongMid": tailM, "tailWrongLate": tailL, "tailRoundsBonus": tailBonus,
            "assists": assists, "instinct": instinct, "clearBonusPct": clearBonus, "starMark": True,
            "gestureHint": gestureHint, "recommendCell": recommend, "estimates": estimates, "ticksDelta": ticks,
            "appraisalsDelta": appr, "appraisalsMin": apprMin, "appraisalsUnlimited": apprUnl, "hotspotGlow": glow,
            "remainHint": remain, "reputationHint": repute, "retry": retry, "save": save, "trueEnd": True,
            "masterAchievement": did == "master",
        })

    # ---- speakers
    for key, (zh, en) in sinfo["speakers"].items():
        strings[key] = {"zh-TW": zh, "en": en}

    tables = {"chapters": chapters, "steps": steps, "script": script, "evidence": evidence, "hotspots": hotspots,
              "nodes": nodes, "opponents": opponents, "tells": tells, "papers": papers, "difficulty": difficulty}

    validate(tables, strings, systems, base, placeholder_tags)

    for w in warnings:
        print("warning:", w)
    for e in errors:
        print("error:", e)
    if errors:
        print(f"FAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1

    if not args.check:
        DATA_OUT.mkdir(exist_ok=True)
        STRINGS_OUT.mkdir(exist_ok=True)
        for name, rows in tables.items():
            write_table(DATA_OUT / f"{name}.json", rows)
        for lang in LANGS:
            write_strings(STRINGS_OUT / f"{lang}.csv", strings, lang)
    for name, rows in tables.items():
        print(f"{'checked' if args.check else 'wrote'} data/{name}.json: {len(rows)} rows")
    print(f"{'checked' if args.check else 'wrote'} strings/zh-TW.csv, strings/en.csv: {len(strings)} keys")
    print(f"OK: 0 errors, {len(warnings)} warning(s)")
    return 0


# ---------------------------------------------------------------- validation

KEY_COLUMNS = {
    "chapters": ["titleKey"], "script": ["text", "speaker"], "evidence": ["nameKey", "descKey", "tagsKey", "appraisalKey", "reason0Key", "reason1Key", "reason2Key"],
    "nodes": ["textKey"], "opponents": ["speaker", "gestureAssert", "gestureRush", "gestureReinforce", "gestureTrap"],
    "tells": ["text", "speaker", "gesture"], "papers": ["mastKey", "headlineKey", "subKey", "bodyKey", "page2Key", "page2SubKey", "sideKey",
               "sideWinKey", "sideWinSubKey", "sideNotoKey", "sideNotoSubKey", "sideLoseKey", "sideLoseSubKey"],
    "difficulty": ["nameKey", "descKey"],
}
LIST_KEY_COLUMNS = {"hotspots": ["lines"], "evidence": ["lines"]}
EVIDENCE_REF_COLUMNS = {"hotspots": ["yields"], "nodes": ["refutedBy"], "opponents": ["hand"], "script": ["evidence"]}


def validate(tables: dict, strings: dict, systems: dict, base: dict, placeholder_tags: bool) -> None:
    for name, rows in tables.items():
        if not re.fullmatch(r"[a-z][A-Za-z0-9]*", name):
            err(f"table name {name!r} is not [a-z][A-Za-z0-9]*")
        if not rows:
            continue
        cols = list(rows[0].keys())
        for i, row in enumerate(rows):
            if list(row.keys()) != cols:
                err(f"{name}[{i}]: columns differ from row 0")
            for k, v in row.items():
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
                    err(f"{name}: bad column name {k!r}")
                if v is None or not isinstance(v, (str, int, float, bool)):
                    err(f"{name}[{i}].{k}: value {v!r} is not number/bool/string")
        for k in cols:
            types = {type(r[k]) for r in rows}
            if len(types - {int, float}) > 1 or (types & {str, bool} and len(types) > 1):
                err(f"{name}.{k}: mixed value types {sorted(t.__name__ for t in types)}")
        ids = [r["id"] for r in rows if "id" in r]
        if len(ids) != len(set(ids)):
            err(f"{name}: duplicate ids")

    def need_key(table, col, key):
        if not key:
            return
        for lang in LANGS:
            if key not in strings or lang not in strings[key]:
                err(f"{table}.{col}: key {key!r} missing in {lang}")
                return

    for table, cols in KEY_COLUMNS.items():
        for row in tables[table]:
            for col in cols:
                need_key(table, col, row[col])
    for table, cols in LIST_KEY_COLUMNS.items():
        for row in tables[table]:
            for col in cols:
                for key in filter(None, row[col].split(",")):
                    need_key(table, col, key)

    ev_ids = {r["id"] for r in tables["evidence"]}
    node_ids = {r["id"] for r in tables["nodes"]}
    for table, cols in EVIDENCE_REF_COLUMNS.items():
        for row in tables[table]:
            for col in cols:
                for e in filter(None, row[col].split(",")):
                    if e not in ev_ids:
                        err(f"{table}.{col}: unknown evidence id {e!r} (row {row.get('id')})")
    for row in tables["evidence"]:
        for n in filter(None, row["refutes"].split(",")):
            if n not in node_ids:
                err(f"evidence.refutes: unknown node {n!r}")
        if row["golden"] and row["golden"] not in ev_ids:
            err(f"evidence.golden: unknown evidence {row['golden']!r}")
        if row["hotspot"] and row["hotspot"] not in {h["id"] for h in tables["hotspots"]}:
            err(f"evidence.hotspot: unknown hotspot {row['hotspot']!r}")
        for col in ("tags", "hiddenTags", "grazingTags"):
            for t in filter(None, row[col].split(",")):
                if t.split(":")[0] not in CATEGORY_IDS:
                    err(f"evidence {row['id']}.{col}: unknown tag category in {t!r}")
        all_tags = set(filter(None, row["tags"].split(",")))
        for col in ("hiddenTags", "grazingTags"):
            if not set(filter(None, row[col].split(","))) <= all_tags:
                err(f"evidence {row['id']}.{col}: not a subset of tags")
    for row in tables["nodes"]:
        for t in filter(None, row["tags"].split(",")):
            if t.split(":")[0] not in CATEGORY_IDS:
                err(f"node {row['id']}: unknown tag category in {t!r}")
    for row in tables["script"]:
        if row["node"] and row["node"] not in node_ids:
            err(f"script {row['id']}: unknown node {row['node']!r}")
    for row in tables["opponents"]:
        if row["tailNode"] and row["tailNode"] not in node_ids:
            err(f"opponents {row['id']}: unknown tail node")
    # Rulings D2 / D3: required cards exist, are common or key, come from a hotspot, and are never obtainable.
    ev_by_id = {r["id"]: r for r in tables["evidence"]}
    for e in sorted(REQUIRED):
        r = ev_by_id.get(e)
        if r is None:
            err(f"required evidence {e}: not in the evidence table")
            continue
        if not r["required"] or r["obtainable"]:
            err(f"evidence {e}: must be required=true and obtainable=false (rulings D2, D3)")
        if r["grade"] not in ("common", "key") or r["obtain"] != "hotspot":
            err(f"evidence {e}: a required card must be common/key and obtained from a hotspot")
    for r in tables["evidence"]:
        if r["required"] and r["id"] not in REQUIRED:
            err(f"evidence {r['id']}: required but not in REQUIRED (ruling D2)")
        if r["obtainable"] and r["grade"] not in ("common", "key"):
            err(f"evidence {r['id']}: only common and key cards may be obtainable (ruling D3)")
    opp_ids = {r["id"] for r in tables["opponents"]}
    paper_groups = {r["group"] for r in tables["papers"]}
    for row in tables["steps"]:
        if row["kind"] in ("warmup", "debate") and row["arg"] not in opp_ids:
            err(f"steps {row['id']}: unknown opponent {row['arg']!r}")
        if row["kind"] == "paper" and row["arg"] not in paper_groups:
            err(f"steps {row['id']}: unknown paper group {row['arg']!r}")
    # Ruling D5: each chapter starts with exactly one paper step (the S01 front page) and has no other paper
    # step, except the final transition after the last chapter.
    for c in CHAPTERS:
        cs = [r for r in tables["steps"] if r["chapter"] == c]
        n_paper = sum(r["kind"] == "paper" for r in cs)
        if n_paper != (2 if c == CHAPTERS[-1] else 1) or cs[0]["kind"] != "paper" or cs[0]["scene"] != "S01":
            err(f"steps: Ch.{c} must start with exactly one S01 paper step (ruling D5)")
        if any(r["scene"] == "S01" and r["kind"] != "paper" for r in cs):
            err(f"steps: Ch.{c} has a non-paper S01 step (ruling D5)")
    for r in tables["papers"]:
        if r["kind"] == "open" and not r["bodyKey"]:
            err(f"papers {r['id']}: an opening paper needs the S01 lead as bodyKey (ruling D5)")
    for key, v in strings.items():
        for lang in LANGS:
            if lang not in v or not isinstance(v[lang], str):
                err(f"strings: {key} has no {lang} text")

    # ---- design counts (01-systems 1.3): warnings only
    for c in CHAPTERS:
        d = systems["scale"][c]
        ev = [r for r in tables["evidence"] if r["chapter"] == c and r["grade"] in ("common", "key", "story")]
        got = {
            "scenes": len({h["scene"] for h in tables["hotspots"] if h["chapter"] == c}),
            "hotspots": len([h for h in tables["hotspots"] if h["chapter"] == c and not h["requires"]]),
            "common": sum(r["grade"] == "common" for r in ev), "key": sum(r["grade"] == "key" for r in ev),
            "story": sum(r["grade"] == "story" for r in ev),
        }
        for k, v in got.items():
            if v != d[k]:
                warn(f"Ch.{c} count mismatch vs 01-systems 1.3: {k} = {v}, design {d[k]}")
        hs = got["hotspots"]
        if d["ticks"] > 0 and hs:
            ratio = d["ticks"] / hs
            if not 0.65 <= ratio <= 0.75:
                warn(f"Ch.{c}: ticks/hotspots = {d['ticks']}/{hs} = {ratio:.2f}, design wants about 0.65-0.75 (01-systems 1.3)")
        inspect = sum(h["type"] == "inspect" for h in tables["hotspots"] if h["chapter"] == c and not h["requires"])
        if hs:
            warn(f"Ch.{c}: {inspect}/{hs} hotspots are inspect-only ({inspect * 100 // hs}%; 01-systems 1.2 expects about 40%)") if abs(inspect / hs - 0.4) > 0.1 else None
        nodes = [n for n in tables["nodes"] if n["chapter"] == c and n["kind"] == "claim"]
        cap = next(o["nodeCap"] for o in tables["opponents"] if o["id"] == f"{ch_key(c)}_MAIN")
        if len(nodes) < cap:
            warn(f"Ch.{c}: {len(nodes)} claim nodes < node cap {cap}")
    if placeholder_tags:
        warn(f"{TAG_FILE.name} is still the category-only PLACEHOLDER (ruling C4: real 類別：值 tags pending)")


# ---------------------------------------------------------------- writers

def write_table(path: Path, rows: list[dict]) -> None:
    body = ",\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows)
    path.write_text("[\n" + body + "\n]\n" if rows else "[]\n", encoding="utf-8", newline="\n")


def write_strings(path: Path, strings: dict, lang: str) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow(["key", "text"])
    for key in sorted(strings):
        w.writerow([key, strings[key][lang]])
    path.write_text(buf.getvalue(), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
