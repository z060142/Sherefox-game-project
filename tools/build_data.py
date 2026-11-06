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

Inputs (all inside the project):
    source/localization/   localization package (strings.json, *.csv)
    source/tags/tags_ch01-03.csv   per-card / per-node tag values (category, value, slug, grazing, hidden, police)
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
# Tag file `hidden` column (10-cases 標籤值 需鑑定 column, ruling D8) -> the card appraisals that reveal the tag.
HIDDEN_KINDS = {"no": (), "medical": ("medical", "dual"), "mech": ("mechanical", "dual"),
                "mechanical": ("mechanical", "dual")}
TAG_COLUMNS = ["owner", "category", "value", "slug", "grazing", "hidden", "police", "note"]

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

# Hotspots come from the 「調查點」 table of each chapter in 10-cases (ids HS_CH0n_nn). The table gives the name,
# zone (區域), yielded card(s), case-note line and hint; the identifiers below are the only hand-made part.
# Zone label (區域) -> zone slug. Ch.3 zones are the three scenes themselves (rulings D9, D10).
ZONE_SLUGS = {
    "廚房": "kitchen", "客廳": "living_room",
    "櫃台": "counter", "店面": "shop_floor", "店門外": "outside", "後室門口": "back_room",
    "角落": "corner", "櫃台後": "behind_counter",
    "鍋爐室": "boiler_room", "甲板": "deck", "碼頭": "dock",
}
# Ch.3 zone label -> scene slug (Ch.1 and Ch.2 have a single scene, taken from the scene table).
CH3_ZONE_SCENES = {"鍋爐室": "boiler_room", "甲板": "deck", "碼頭": "dock"}
# Hotspot flags the design table states in words; the build cross-checks the words against these ids.
HOTSPOT_POST_DEBATE = {"HS_CH02_08"}                   # name ends with （論戰後）
# Ruling F3: granted by the flow when the main debate ends, no tick cost; excluded from the tick ratio (F1).
HOTSPOT_AUTO = {"HS_CH02_08"}
HOTSPOT_REQUIRES = {"HS_CH03_23": "missing:G-01"}      # name says 只在缺少 G-01 時出現 (01-systems 1.9, ruling D11)
HOTSPOT_REVISIT = {"HS_CH03_03", "HS_CH03_07"}         # note starts with （事件中已取得 (card picked up during the event)
HOTSPOT_PHASES = ("investigate", "postDebate")
SCREEN_W, SCREEN_H = 1280, 720
# Ruling C1 / C2 (docs/rulings.md) and explicit 強攻 marks in 10-cases.
STRONG = {"E01_03", "E02_01", "E03_04", "G-01"}
# Ruling D2: required evidence per case. Required cards are never opponent-obtainable (ruling D3).
REQUIRED = {"E01_03", "E02_02", "E02_06", "E03_02", "E03_07"}
# Golden output of key evidence (10-cases 結算・黃金線索).
GOLDEN_OUT = {"E02_01": "G-01"}
# Ruling E1: the 「待續」 card after the final paper.
END_CARD_KEY = "UI_TO_BE_CONTINUED"
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
    # 02-numbers 五 prose overrides of the 01-systems 1.3 appraisal counts, e.g. 「Ch.2 鑑定 3 次」
    # (數值總表 has precedence over 系統規格).
    appraisals = {int(c): int(n) for c, n in re.findall(r"Ch\.(\d+) 鑑定 (\d+) 次", md_section(text, r"^## 五、"))}
    return {"early": early, "weights": weights, "cases": cases, "appraisals": appraisals}


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
        spots_sec = md_section(body, r"^### 調查點")
        spots = []
        for row in md_rows(spots_sec)[1:]:
            if len(row) != 6:
                raise SystemExit(f"10-cases Ch.{c} 調查點: expected 6 columns, got {row!r}")
            spots.append({"id": row[0], "name": row[1], "zone": row[2],
                          "yields": [] if row[3] in ("", "—") else [e.strip() for e in row[3].split("、")],
                          "note": row[4], "hint": "" if row[5] in ("", "—") else row[5]})
        m = re.search(r"共 (\d+) 個調查點，(\d+) 個產出證物、(\d+) 個只寫進案件筆記", spots_sec)
        if not m:
            raise SystemExit(f"10-cases Ch.{c} 調查點: summary sentence not found")
        out[c] = {"scenes": scenes, "evidence": evidence, "behaviour": behaviour, "hotspots": spots,
                  "hotspotSummary": tuple(int(x) for x in m.groups())}
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
        raise SystemExit(f"missing {TAG_FILE.relative_to(ROOT)}")
    rows = []
    raw = read_csv(TAG_FILE)
    if raw and list(raw[0].keys()) != TAG_COLUMNS:
        err(f"{TAG_FILE.name}: header must be {','.join(TAG_COLUMNS)}, got {','.join(raw[0].keys())}")
    for i, r in enumerate(raw, start=2):
        if not r.get("owner", "").strip() or r["owner"].lstrip().startswith("#"):
            continue
        rows.append({k: (v or "").strip() for k, v in r.items()} | {"_line": i})
    return rows


# ---------------------------------------------------------------- builders

def build_tags(tag_rows: list[dict], appraisal_of: dict) -> tuple[dict, dict]:
    """owner -> {"tags", "grazing", "hidden", "police"} (lists in file order), and
    tag id -> design value text (for the TAG_ display keys, ruling D13)."""
    out: dict[str, dict] = {}
    values: dict[str, str] = {}
    for r in tag_rows:
        where = f"{TAG_FILE.name}:{r['_line']}"
        cat = TAG_CATEGORIES.get(r.get("category", ""))
        if not cat:
            err(f"{where}: unknown tag category {r.get('category')!r}")
            continue
        value, slug = r.get("value", ""), r.get("slug", "")
        if not value or not slug:
            err(f"{where}: every tag needs a value and an ASCII slug (ruling C4)")
            continue
        if not re.fullmatch(r"[a-z0-9_]+", slug):
            err(f"{where}: slug {slug!r} must match [a-z0-9_]+")
            continue
        tag = f"{cat}:{slug}"
        if values.setdefault(tag, value) != value:
            err(f"{where}: slug {tag} is used for both {values[tag]!r} and {value!r}")
        entry = out.setdefault(r["owner"], {"tags": [], "grazing": [], "hidden": [], "police": []})
        if tag in entry["tags"]:
            err(f"{where}: duplicate tag {tag} on {r['owner']}")
            continue
        entry["tags"].append(tag)
        grazing = r.get("grazing", "").lower()
        if grazing in ("擦邊", "1", "true", "yes", "y"):
            entry["grazing"].append(tag)
        elif grazing:
            err(f"{where}: grazing must be 擦邊 or empty, got {grazing!r}")
        hidden = r.get("hidden", "").lower() or "no"
        if hidden not in HIDDEN_KINDS:
            err(f"{where}: hidden must be medical/mech/no, got {hidden!r}")
            continue
        if hidden != "no":
            if r["owner"] not in appraisal_of:
                err(f"{where}: only evidence tags can be hidden")
            elif appraisal_of[r["owner"]] not in HIDDEN_KINDS[hidden]:
                err(f"{where}: {hidden} tag on a card whose appraisal is {appraisal_of[r['owner']]}")
            entry["hidden"].append(tag)
        police = r.get("police", "").lower()
        if police in ("yes", "1", "true"):
            if hidden == "no":
                err(f"{where}: police=yes needs a hidden tag")
            entry["police"].append(tag)
        elif police not in ("", "no"):
            err(f"{where}: police must be yes or empty, got {police!r}")
    return out, values


# Display-key category names (localization README: TAG_<TIME|PLACE|PERSON|PHYSICAL|SCANDAL>_<slug>,
# the same names as UI_TAG_<category>).
TAG_KEY_CATEGORY = {"time": "TIME", "place": "PLACE", "person": "PERSON", "phys": "PHYSICAL", "scandal": "SCANDAL"}


def tag_key(tag: str) -> str:
    """Ruling D13: display key TAG_<CATEGORY>_<SLUG>, e.g. TAG_PLACE_BOILER_ROOM."""
    cat, slug = tag.split(":", 1)
    return f"TAG_{TAG_KEY_CATEGORY[cat]}_{slug.upper()}"


# Opponent gesture keys (localization README: GESTURE_<OPPONENT>_<ASSERT|ONSLAUGHT|REINFORCE|TRAP>).
GESTURE_OPPONENT = {1: "ARTHUR", 2: "FITCH", 3: "PIERCE"}
GESTURE_ACTION = {"assert": "ASSERT", "rush": "ONSLAUGHT", "reinforce": "REINFORCE", "trap": "TRAP"}


def gesture_key(c: int, action: str) -> str:
    return f"GESTURE_{GESTURE_OPPONENT[c]}_{GESTURE_ACTION[action]}"


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
        if c not in CHAPTERS:
            # Ruling E1: the Ch.4 S01 lines are only the lead of the final paper (CH04_OPEN), not script rows.
            continue
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
            "id": r["ID"], "chapter": c, "scene": scene, "sceneKey": f"{ch_key(c)}_{scene}", "seq": l, "kind": kind,
            "speaker": speaker,
            "text": r["ID"], "branch": state.get("branch", ""),
            "round": state.get("round", 0) if scene_kind in ("debate", "warmup") else 0,
            "act": act, "node": node, "evidence": ",".join(evidence), "appraisal": appraisal,
            "banner": ",".join(banner), "inactive": inactive,
            # Shown by a dialogue runner: a spoken / narrated line (kind line, incl. system and newspaper lines),
            # not marked inactive, and not in the S90 tell library (data-schema §3).
            "playable": kind == "line" and not inactive and s != 90,
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
        gesture = gesture_key(row["chapter"], action) if category == "tell" else ""
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

    tag_rows = load_tags()
    script_rows_tmp = []  # filled below

    # ---- banners (CUT_ = 大字, STAMP_ = 印)
    banners = {}
    for r in loc["ui"]:
        m = re.fullmatch(r"(CUT|STAMP)_[A-Z0-9_]+", r["ID"])
        if m and not r["ID"].endswith(("_LOG", "_SUB")):
            banners[("大字" if m.group(1) == "CUT" else "印", r["zh-TW"])] = r["ID"]

    script, sinfo = build_script(loc, banners)
    merge_staging(script)
    tells, _gesture_en = build_tells(loc, script)

    # Tail and warm-up node text: CLM_CH0n_T1 / CLM_CH0n_W1 (localization package).
    for c in CHAPTERS:
        if c in TAIL_REFUTERS:
            node_rows_src.append((c, "tail", 1, f"CLM_{ch_key(c)}_T1", False, TAIL_REFUTERS[c]))
        if c in WARMUP:
            node_rows_src.append((c, "warmup", 1, f"CLM_{ch_key(c)}_W1", False, WARMUP[c]["refuters"]))

    def node_id(c, kind, idx):
        return f"{ch_key(c)}_{ {'claim': 'N', 'tail': 'T', 'warmup': 'W'}[kind] }{idx}"

    appraisal_of = {e: b["appraisal"] for e, b in base.items()}
    tags, tag_values = build_tags(tag_rows, appraisal_of)
    for owner in tags:
        known = owner in base or any(owner == node_id(c, k, i) for c, k, i, *_ in node_rows_src)
        if not known:
            err(f"{TAG_FILE.name}: unknown owner {owner}")

    # ---- tag display names (ruling D13): TAG_<category>_<slug>. Keys the localization package does not
    # have yet get the design value as zh-TW and, until translated, the same text as en (warning).
    tag_table = []
    untranslated = []
    for tag in sorted(tag_values):
        key = tag_key(tag)
        if key not in strings:
            strings[key] = {"zh-TW": tag_values[tag], "en": tag_values[tag]}
            untranslated.append(key)
        cat, slug = tag.split(":", 1)
        tag_table.append({"id": tag, "category": cat, "slug": slug, "nameKey": key})
    if untranslated:
        warn(f"{len(untranslated)} TAG_ display keys are not in the localization package; en = zh-TW text "
             f"until translated (ruling D13): {','.join(untranslated)}")

    # ---- nodes table
    nodes = []
    refutes_of: dict[str, list[str]] = {}
    for c, kind, idx, text_key, truth, refs in node_rows_src:
        nid = node_id(c, kind, idx)
        case = f"{ch_key(c)}_{'WARMUP' if kind == 'warmup' else 'MAIN'}"
        t = tags.get(nid, {"tags": [], "grazing": []})
        if not t["tags"]:
            err(f"node {nid}: no tags in {TAG_FILE.name}")
        nodes.append({"id": nid, "chapter": c, "case": case, "kind": kind, "idx": idx, "textKey": text_key,
                      "tags": ",".join(t["tags"]), "grazingTags": ",".join(t["grazing"]),
                      "truth": bool(truth), "refutable": bool(refs), "refutedBy": ",".join(refs)})
        for e in refs:
            refutes_of.setdefault(e, []).append(nid)

    # ---- hotspots (10-cases 「調查點」 tables are canonical; yielded cards are checked against the evidence)
    hotspots = []
    yielded: dict[str, str] = {}
    for c in CHAPTERS:
        design_scenes = cases[c]["scenes"]
        scene_slugs = [SCENE_SLUGS.get(name) for name, _ in design_scenes]
        if None in scene_slugs:
            err(f"10-cases Ch.{c}: a scene has no slug in SCENE_SLUGS")
            continue
        per_scene_count: dict[str, int] = {}
        for spot in cases[c]["hotspots"]:
            hid = spot["id"]
            if not re.fullmatch(rf"HS_CH{c:02d}_\d\d", hid):
                err(f"10-cases Ch.{c} 調查點: bad id {hid!r}")
                continue
            zone_label = spot["zone"]
            zone = ZONE_SLUGS.get(zone_label)
            if not zone:
                err(f"{hid}: zone {zone_label!r} has no slug in ZONE_SLUGS")
                continue
            if len(scene_slugs) == 1:
                scene = scene_slugs[0]
            else:
                scene = CH3_ZONE_SCENES.get(zone_label)
                if scene not in scene_slugs:
                    err(f"{hid}: zone {zone_label!r} is not one of the Ch.{c} scenes")
                    continue
            ys = spot["yields"]
            if len(ys) > 2:
                err(f"{hid}: yields more than 2 cards (01-systems 1.2)")
            typ = "inspect" if not ys else "evidence"
            if any("證詞" in ev_loc.get(f"{e}_NAME", {}).get("zh-TW", "") for e in ys):
                typ = "testimony"  # the card is a witness statement (01-systems 1.2: 證詞)
            phase = "postDebate" if hid in HOTSPOT_POST_DEBATE else "investigate"
            requires = HOTSPOT_REQUIRES.get(hid, "")
            auto = hid in HOTSPOT_AUTO
            if auto and phase != "postDebate":
                err(f"{hid}: an auto-grant hotspot must be phase=postDebate")
            revisit = hid in HOTSPOT_REVISIT
            # The design states these flags in words; the constants above must agree with the words.
            if ("論戰後" in spot["name"]) != (phase == "postDebate"):
                err(f"{hid}: design name {spot['name']!r} and HOTSPOT_POST_DEBATE disagree")
            if ("只在缺少 G-01 時出現" in spot["name"]) != bool(requires):
                err(f"{hid}: design name {spot['name']!r} and HOTSPOT_REQUIRES disagree")
            if spot["note"].startswith("（事件中已取得") != revisit:
                err(f"{hid}: design note {spot['note']!r} and HOTSPOT_REVISIT disagree")
            if revisit and not ys:
                err(f"{hid}: a revisit hotspot must yield the card it revisits")
            name_key, note_key, hint_key = f"{hid}_NAME", f"{hid}_NOTE", f"{hid}_HINT"
            if name_key not in strings:
                err(f"{hid}: string key {name_key} missing")
            if not ys and note_key not in strings:
                err(f"{hid}: inspect-only hotspot has no {note_key}")
            if ys and note_key in strings:
                err(f"{hid}: {note_key} exists but the hotspot yields a card")
            if bool(spot["hint"]) != (hint_key in strings):
                err(f"{hid}: design hint is {'present' if spot['hint'] else 'absent'} but {hint_key} "
                    f"{'exists' if hint_key in strings else 'is missing'}")
            # The design name may carry authoring notes (trailing parenthesised note, 「的新調查點」); the string
            # table holds only the on-screen name (ruling F4). Accept the raw name or the name with them stripped.
            stripped_name = re.sub(r"（[^（）]*）\s*$", "", spot["name"]).strip()
            stripped_name = re.sub(r"的新調查點$", "", stripped_name)
            for key, want in ((name_key, spot["name"]), (note_key, None if ys else spot["note"]),
                              (hint_key, spot["hint"] or None)):
                ok = {want, stripped_name} if key == name_key else {want}
                if want and key in strings and strings[key]["zh-TW"] not in ok:
                    warn(f"{key}: zh-TW text differs from the 10-cases 調查點 table")
            lines = [ln for e in ys for ln in sinfo["evidence_lines"].get(e, [])]
            for e in ys:
                if e in yielded:
                    err(f"hotspots: {e} yielded by both {yielded[e]} and {hid}")
                yielded[e] = hid
            i = per_scene_count.get(scene, 0)
            per_scene_count[scene] = i + 1
            hotspots.append({"id": hid, "chapter": c, "scene": scene, "area": 0, "zone": zone, "type": typ,
                             "phase": phase, "yields": ",".join(ys), "lines": ",".join(lines),
                             "nameKey": name_key, "noteKey": "" if ys else note_key,
                             "hintKey": hint_key if spot["hint"] else "", "requires": requires,
                             "revisit": revisit, "auto": auto,
                             "x": 100 + (i % 4) * 280, "y": 140 + (i // 4) * 200, "w": 160, "h": 120,
                             "placeholder": True})
        n_all = len(cases[c]["hotspots"])
        n_ev = sum(1 for sp in cases[c]["hotspots"] if sp["yields"])
        n_cond = sum(1 for h in hotspots if h["chapter"] == c and h["requires"])
        want_all, want_ev, want_insp = cases[c]["hotspotSummary"]
        # The summary sentence counts the conditional spot outside the total ("不計入 22 個").
        if (n_all - n_cond, n_ev - n_cond, n_all - n_ev) != (want_all, want_ev, want_insp):
            err(f"10-cases Ch.{c} 調查點: table has {n_all} rows ({n_ev} with cards, {n_cond} conditional) but the "
                f"summary says {want_all} / {want_ev} / {want_insp}")

    # ---- evidence table
    evidence = []
    for eid in list(ev_ids) + ["G-01", "S-01"]:
        b = base[eid]
        t = tags.get(eid, {"tags": [], "grazing": [], "hidden": [], "police": []})
        if not t["tags"]:
            err(f"evidence {eid}: no tags in {TAG_FILE.name}")
        # Grazing values may sit outside the card's category column (10-cases 標籤值), so compare the
        # non-grazing categories (all categories when every value is grazing, e.g. S-01) with the design.
        firm = [x for x in t["tags"] if x not in t["grazing"]] or t["tags"]
        got_cats = sorted({x.split(":")[0] for x in firm})
        d = cases.get(b["chapter"], {}).get("evidence", {}).get(eid)
        want = sorted({TAG_CATEGORIES.get(x) for x in d["tags"].split("・")} if d else set(b["cats"]))
        if got_cats != want:
            warn(f"evidence {eid}: non-grazing tag categories {got_cats} differ from the design categories {want}")
        is_card = b["grade"] in ("common", "key", "story")
        if is_card:
            keys, correct = reason_order(eid)
        else:
            keys, correct = ["", "", ""], -1
        grade = b["grade"]
        spot_row = next((h for h in hotspots if h["id"] == yielded.get(eid)), None)
        if grade == "golden":
            obtain = "golden"
        elif spot_row and spot_row["phase"] == "postDebate":
            obtain = "afterDebate"  # the spot only appears after the main debate
        elif spot_row and spot_row["revisit"]:
            obtain = "event"  # picked up during the event; the spot only replays and appraises
        elif spot_row:
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
            "policeTags": ",".join(t["police"]),
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
            "gestureAssert": gesture_key(c, "assert") if "assert" in gest else "",
            "gestureRush": gesture_key(c, "rush") if "rush" in gest else "",
            "gestureReinforce": gesture_key(c, "reinforce") if "reinforce" in gest else "",
            "gestureTrap": gesture_key(c, "trap") if "trap" in gest else "",
            "playerActions": "solid,rebut,observe" if c == 1 else "solid,sophistry,rebut,observe",
            "tail": "" if c == 1 else "scorched", "tailNode": "" if c == 1 else node_id(c, "tail", 1),
            # Ruling D15: Ch.1 needs 2 contradictions by the end of round 3 and the break by the end of round 6.
            "roundLimit": 6 if c == 1 else 0, "contraTarget": 2 if c == 1 else 0,
            "contraDeadline": 3 if c == 1 else 0, "mistakeLimit": 0,
            "hand": "", "handPerMissed": 0 if c == 1 else 1, "hpPerMissed": 0 if c == 1 else 10,
        })
        for act, zh in gest.items():
            key = gesture_key(c, act)
            if key not in strings:
                err(f"gesture {key}: not in the localization package")
            elif strings[key]["zh-TW"] != zh:
                warn(f"gesture {key}: localization zh {strings[key]['zh-TW']!r} differs from 10-cases {zh!r}")
        if c in WARMUP:
            opponents.append({
                "id": f"{ch_key(c)}_WARMUP", "chapter": c, "kind": "warmup", "speaker": "SPK_INSPECTOR_BASKERVILLE",
                "type": "", "hp": 0, "playerHp": 0, "noDamage": True, "nodeCap": 1, "damageBase": 0,
                "damagePerNode": 0, "rushMul": 1.25, "w_claim": 100, "w_rush": 0, "w_reinforce": 0, "w_trap": 0,
                "clear": 100, "fuzzy": 0, "disguise": 0, "rules": "", "ruleBias": 80, "mirror": False,
                "gestureAssert": "", "gestureRush": "", "gestureReinforce": "", "gestureTrap": "",
                "playerActions": "rebut", "tail": "", "tailNode": "", "roundLimit": 0, "contraTarget": 0,
                "contraDeadline": 0, "mistakeLimit": 3, "hand": ",".join(WARMUP[c]["hand"]), "handPerMissed": 0, "hpPerMissed": 0,
            })

    # ---- papers (ruling D5): one paper per chapter boundary. Main headline and lead are the next chapter's
    # script S01; the sidebar carries the previous case's result (win / notorious / lose).
    papers = []
    side = {c: f"NEWS_SIDE_{c:02d}" for c in CHAPTERS}

    def result_keys(c):
        # (headline, sub) for win / notorious / lose of the case that ended in chapter c. Every _SUB is the
        # result's second line (localization README: "second line / subhead"; the stray 第二版／內文 labels
        # were removed from the text on 2026-11-06).
        def sub(key):
            return key if key in strings else ""
        if f"NEWS_{c:02d}_WIN" in strings:
            return [(f"NEWS_{c:02d}_{x}", sub(f"NEWS_{c:02d}_{x}_SUB")) for x in ("WIN", "NOTO", "LOSE")]
        k = f"NEWS_{c:02d}_END"  # a single version fills all three slots
        return [(k, sub(f"{k}_SUB"))] * 3

    def paper(pid, c, kind, group, result_ch, head, sub, body, side_key, ad, res):
        row = {"id": pid, "chapter": c, "kind": kind, "group": group, "resultChapter": result_ch,
               "mastKey": "UI_PAPER_MAST", "pictureId": f"ch{c:02d}", "headlineKey": head, "subKey": sub,
               "bodyKey": body, "page2HeadKey": "", "page2BodyKey": "", "sideKey": side_key, "adKey": ad}
        for name, (hk, sk) in zip(("Win", "Noto", "Lose"), res):
            row[f"side{name}Key"] = hk
            row[f"side{name}SubKey"] = sk
        papers.append(row)

    no_result = [("", "")] * 3
    for c in CHAPTERS:
        body = next((s["id"] for s in script if s["chapter"] == c and s["scene"] == "S01" and s["seq"] == 3), "")
        if c == 1:
            # No previous case: the side column is the opening city news NEWS_00_OPEN (01-systems 3.3), the
            # result strip is empty, and NEWS_00_OPEN_SUB (the room-to-let notice) is the advert.
            side_key, ad, res = "NEWS_00_OPEN", "NEWS_00_OPEN_SUB", no_result
        else:
            side_key, ad, res = side[c - 1], "", result_keys(c - 1)
        paper(f"{ch_key(c)}_OPEN", c, "open", f"{ch_key(c)}_OPEN", c - 1, f"HEAD_{ch_key(c)}",
              f"HEAD_{ch_key(c)}_SUB", body, side_key, ad, res)
    # Ruling E1: the prototype ends with the Ch.4 opening merged paper (HEAD_CH04 / _SUB and the Ch.4 S01 lead,
    # Ch.3's result in the sidebar), then a 「待續」 card. Ch.4 itself is out of scope.
    last = CHAPTERS[-1]
    nxt = ch_key(last + 1)
    paper(f"{nxt}_OPEN", last + 1, "open", f"{nxt}_OPEN", last, f"HEAD_{nxt}", f"HEAD_{nxt}_SUB",
          f"SCR_{nxt}_S01_L003", side[last], "", result_keys(last))

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
            seq.append(("paper", "", f"{ch_key(c + 1)}_OPEN", "transition"))  # ruling E1
            seq.append(("end", "", END_CARD_KEY, ""))
        for i, (k, scene, arg, sub) in enumerate(seq):
            steps.append({"id": f"{ch_key(c)}_{i:02d}", "chapter": c, "idx": i, "kind": k, "sub": sub,
                          "scene": scene, "arg": arg})

    # ---- chapter titles: CHAP_0n_TITLE from the localization package; fallback: the closing-notes line
    # 「案件名稱：…。」 / "Case name: …."
    for c in CHAPTERS:
        if f"CHAP_{c:02d}_TITLE" in strings:
            continue
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
            "keyDesign": sc["key"], "storyDesign": sc["story"], "ticks": sc["ticks"],
            "appraisals": numbers["appraisals"].get(c, sc["appraisals"]),
            "appraisalUnlocked": c >= 2, "assistUnlocked": c >= 2, "sophistry": c >= 2, "sophistryReads": False,
            "states": {1: "", 2: "hachiku"}.get(c, "hachiku,konju,shisshu"),
            "trustShown": c >= 3, "trustDebate": c >= 3, "trustNotoriety": True, "trustDeferred": c == 2,
            "police": c >= 3, "warmup": c in WARMUP, "missToHand": c >= 2,
            "playerHp": early["playerHp"], "breakPct": early["breakPct"], "breakLine": early["breakLine"],
            "breakStrong": 1, "breakChain": 2, "tailPenalty": early["tailPenalty"], "tailRounds": early["tailRounds"],
            "debate": f"{ch_key(c)}_MAIN", "openPaper": f"{ch_key(c)}_OPEN",
            "endPaper": f"{ch_key(c + 1)}_OPEN" if c == CHAPTERS[-1] else "",
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

    # ---- debate script rows (docs/debate-engine.md §2.4, A-11): ruling G2, Ch.1 R1-R3 follow the tutorial
    # (TUT_01_12/15/17): R1 assert N1 (L003), R2 reinforce N2 (L006), R3 assert N3 (L005), all clear, basis
    # tutorial, scripted (no behaviour-rule memory); R4 on (after a missed break) is the AI. Line ids are the
    # S90 rows of the case's tells (tells.id); the tails are not script rows (the engine plays them itself).
    deb_script = []
    for case, rnd, action, node, line in (("CH01_MAIN", 1, "assert", "CH01_N1", "SCR_CH01_S90_L003"),
                                          ("CH01_MAIN", 2, "reinforce", "CH01_N2", "SCR_CH01_S90_L006"),
                                          ("CH01_MAIN", 3, "assert", "CH01_N3", "SCR_CH01_S90_L005")):
        tell = next((r for r in tells if r["id"] == line), None)
        if tell is None or tell["case"] != case or tell["category"] != "tell" or tell["action"] != action:
            err(f"debScript {case}:{rnd}: {line} is not a {action} tell line of {case}")
        if not any(n["id"] == node and n["case"] == case for n in nodes):
            err(f"debScript {case}:{rnd}: unknown node {node}")
        deb_script.append({"key": f"{case}:{rnd}", "action": action, "lit": node, "scripted": 1, "clarity": "clear",
                           "shown1": action, "shown2": "", "star": "", "starRule": 0, "basis": "tutorial",
                           "lineKey": line})

    tables = {"chapters": chapters, "steps": steps, "script": script, "evidence": evidence, "tags": tag_table,
              "hotspots": hotspots,
              "nodes": nodes, "opponents": opponents, "tells": tells, "papers": papers, "difficulty": difficulty,
              "debScript": deb_script}

    validate_templates(strings)
    validate(tables, strings, systems, base)

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
        sync_ui_strings(strings)
    for name, rows in tables.items():
        print(f"{'checked' if args.check else 'wrote'} data/{name}.json: {len(rows)} rows")
    print(f"{'checked' if args.check else 'wrote'} strings/zh-TW.csv, strings/en.csv: {len(strings)} keys")
    print(f"OK: 0 errors, {len(warnings)} warning(s)")
    return 0


# ---------------------------------------------------------------- validation

KEY_COLUMNS = {
    "chapters": ["titleKey"], "script": ["text", "speaker"], "evidence": ["nameKey", "descKey", "tagsKey", "appraisalKey", "reason0Key", "reason1Key", "reason2Key"],
    "nodes": ["textKey"], "opponents": ["speaker", "gestureAssert", "gestureRush", "gestureReinforce", "gestureTrap"],
    "tells": ["text", "speaker", "gesture"], "papers": ["mastKey", "headlineKey", "subKey", "bodyKey", "page2HeadKey", "page2BodyKey", "sideKey", "adKey",
               "sideWinKey", "sideWinSubKey", "sideNotoKey", "sideNotoSubKey", "sideLoseKey", "sideLoseSubKey"],
    "difficulty": ["nameKey", "descKey"], "tags": ["nameKey"], "hotspots": ["nameKey", "noteKey", "hintKey"],
}
# Engravings the paper board knows (ui#paper.picture; docs/ui-contracts.md paper). "" = no picture.
PAPER_PICTURES = {"", "ch01", "ch02", "ch03", "ch04"}
LIST_KEY_COLUMNS = {"hotspots": ["lines"], "evidence": ["lines"]}
EVIDENCE_REF_COLUMNS = {"hotspots": ["yields"], "nodes": ["refutedBy"], "opponents": ["hand"], "script": ["evidence"]}


# Strings with named placeholders that the flows fill with atrium.textf (XTAtrium 08 §8.1.4) -> the placeholder names
# they fill (tools/gen_flows.py, tools/gen_debui.py). A placeholder the flow does not fill would show as nothing, so
# each language's text may use only these. The debate's result line (flowEvLine) fills {name} (the opponent) and {n}.
TEXTF_SPK = ("MSG_DEB_TRAP_MISS", "MSG_DEB_SLIP", "MSG_DEB_TRAP_EXPOSED", "MSG_DEB_SHAKEN", "MSG_DEB_REINFORCE",
             "MSG_TAIL_START", "MSG_TAIL_SECOND", "MSG_TAIL_TIMEOUT", "MSG_WARMUP_FAIL")
TEXTF_KEYS = {
    "UI_DEB_ROUND": {"n"}, "UI_CH1_CONTRA": {"n", "r"}, "UI_WARMUP_MISS": {"n"}, "UI_DEB_TELL_LIKELY": {"n"},
    "UI_DEB_TELL_BASIS_RULE": {"n"}, "STAMP_HACHIKU_SUB": {"n"}, "UI_DEB_COUNTER_PREVIEW": {"base", "n", "dmg"},
    "UI_DEB_COUNTER_PREVIEW_RUSH": {"base", "n", "dmg"}, "UI_DEB_LOCK_SUMMARY_ATK": {"action", "node", "cards"},
    "UI_DEB_LOCK_SUMMARY_PARRY": {"node", "card"}, "MSG_CH1_CONTRA": {"name", "n"}, "MSG_DEB_PARRY": {"name", "n"},
    "MSG_TAIL_WRONG": {"name", "n"}, **{k: {"name", "n"} for k in TEXTF_SPK},
    "UI_RES_COST_SEIZE": {"name"}, "WARN_BOARD_NOREASON": {"n"}, "WARN_BOARD_UNAPPR": {"n", "left"},
}
# The M4c pipeline wrote these templates filled in as `<KEY>__<values>` keys; the UI project's tables still hold them.
STALE_EXPANDED = set(TEXTF_KEYS) | {"MSG_DEB_SHAKEN_END"}
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::\d+)?\}")


def validate_templates(strings: dict) -> None:
    for key, names in TEXTF_KEYS.items():
        if key not in strings:
            err(f"template {key} is missing from the string tables")
            continue
        for lang, text in strings[key].items():
            extra = set(PLACEHOLDER.findall(text.replace("{{", "").replace("}}", ""))) - names
            if extra:
                err(f"template {key}: placeholder(s) {sorted(extra)} in {text!r} ({lang}) are not filled by the flows")


def validate(tables: dict, strings: dict, systems: dict, base: dict) -> None:
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
        for col in ("tags", "hiddenTags", "grazingTags", "policeTags"):
            for t in filter(None, row[col].split(",")):
                if t.split(":")[0] not in CATEGORY_IDS:
                    err(f"evidence {row['id']}.{col}: unknown tag category in {t!r}")
        all_tags = set(filter(None, row["tags"].split(",")))
        for col in ("hiddenTags", "grazingTags"):
            if not set(filter(None, row[col].split(","))) <= all_tags:
                err(f"evidence {row['id']}.{col}: not a subset of tags")
        if not set(filter(None, row["policeTags"].split(","))) <= set(filter(None, row["hiddenTags"].split(","))):
            err(f"evidence {row['id']}.policeTags: not a subset of hiddenTags")
        if row["hiddenTags"] and row["appraise"] == "none":
            err(f"evidence {row['id']}: hidden tags on a card that cannot be appraised")
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
        if r["grade"] not in ("common", "key") or r["obtain"] not in ("hotspot", "event"):
            err(f"evidence {e}: a required card must be common/key and obtained from a hotspot or the event")
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
        if row["kind"] == "end" and (row["arg"] not in strings or row is not tables["steps"][-1]):
            err(f"steps {row['id']}: the end card must be the last step and name a string key (ruling E1)")
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
        if r["pictureId"] not in PAPER_PICTURES:
            err(f"papers {r['id']}: pictureId {r['pictureId']!r} has no engraving in ui#paper (ui-contracts paper)")
        if bool(r["page2HeadKey"]) != bool(r["page2BodyKey"]):
            err(f"papers {r['id']}: page2HeadKey and page2BodyKey are set together")
    for key, v in strings.items():
        for lang in LANGS:
            if lang not in v or not isinstance(v[lang], str):
                err(f"strings: {key} has no {lang} text")

    # ---- hotspots: placeholder rectangles stay on the 1280x720 screen and do not overlap within a scene
    for h in tables["hotspots"]:
        if h["phase"] not in HOTSPOT_PHASES:
            err(f"hotspots {h['id']}: unknown phase {h['phase']!r}")
        if h["auto"] and (h["phase"] != "postDebate" or not h["yields"] or h["requires"] or h["revisit"]):
            err(f"hotspots {h['id']}: auto needs phase=postDebate, a yielded card, no requires and no revisit")
        if h["requires"] and not re.fullmatch(r"missing:[A-Z]-\d\d", h["requires"]):
            err(f"hotspots {h['id']}: bad requires {h['requires']!r}")
        if not (0 <= h["x"] and h["x"] + h["w"] <= SCREEN_W and 0 <= h["y"] and h["y"] + h["h"] <= SCREEN_H):
            err(f"hotspots {h['id']}: rectangle leaves the {SCREEN_W}x{SCREEN_H} screen")
    for i, a in enumerate(tables["hotspots"]):
        for b in tables["hotspots"][i + 1:]:
            if (a["chapter"], a["scene"]) == (b["chapter"], b["scene"]) and a["x"] < b["x"] + b["w"] \
                    and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]:
                err(f"hotspots {a['id']} and {b['id']}: placeholder rectangles overlap")

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
        # Auto-granted spots (ruling F3) cost no tick, so they are not part of the ratio (ruling F1).
        tickable = len([h for h in tables["hotspots"] if h["chapter"] == c and not h["requires"] and not h["auto"]])
        if d["ticks"] > 0 and tickable:
            ratio = d["ticks"] / tickable
            if not 0.65 <= ratio <= 0.75:
                warn(f"Ch.{c}: ticks/tickable hotspots = {d['ticks']}/{tickable} = {ratio:.2f}, design wants about 0.65-0.75 (01-systems 1.3)")
        inspect = sum(h["type"] == "inspect" for h in tables["hotspots"] if h["chapter"] == c and not h["requires"])
        if hs:
            warn(f"Ch.{c}: {inspect}/{hs} hotspots are inspect-only ({inspect * 100 // hs}%; 01-systems 1.2 expects about 40%)") if abs(inspect * 100 - 40 * hs) > 10 * hs else None
        nodes = [n for n in tables["nodes"] if n["chapter"] == c and n["kind"] == "claim"]
        cap = next(o["nodeCap"] for o in tables["opponents"] if o["id"] == f"{ch_key(c)}_MAIN")
        if len(nodes) < cap:
            warn(f"Ch.{c}: {len(nodes)} claim nodes < node cap {cap}")


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


UI_STRINGS_OUT = ROOT / "ui" / "project" / "shared" / "strings"


def sync_ui_strings(strings: dict) -> None:
    """The UI project's string tables = the game's string tables (one source).

    Keys that exist only in the UI project (added by a UI pass before the
    localization package had them) are kept and reported, so nothing is lost.
    """
    if not UI_STRINGS_OUT.is_dir():
        return
    merged = {k: dict(v) for k, v in strings.items()}
    ui_only: set[str] = set()
    for lang in LANGS:
        f = UI_STRINGS_OUT / f"{lang}.csv"
        if not f.exists():
            continue
        rows = list(csv.reader(io.StringIO(f.read_text(encoding="utf-8-sig"))))
        for row in rows[1:] if rows and rows[0][:2] == ["key", "text"] else rows:
            if len(row) >= 2 and row[0] and row[0] not in strings:
                if row[0].split("__")[0] in STALE_EXPANDED and "__" in row[0]:
                    continue   # an expanded template key of M4c (atrium.textf fills the canonical key now)
                merged.setdefault(row[0], {l: "" for l in LANGS})[lang] = row[1]
                ui_only.add(row[0])
    for lang in LANGS:
        write_strings(UI_STRINGS_OUT / f"{lang}.csv", merged, lang)
    if ui_only:
        print("warning: UI-only string keys (add them to the localization):", ", ".join(sorted(ui_only)))
    print(f"wrote ui/project/shared/strings: {len(merged)} keys")


if __name__ == "__main__":
    sys.exit(main())
