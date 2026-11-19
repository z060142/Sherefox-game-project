# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Every D01 string the design wrote is either shown by the game or on an explicit "not displayed" list (v2 demo E7;
docs/d01-string-coverage.md).

Default (static, no CLI needed): the keys of source/localization/d01/ (strings_d01.json, script_d01.csv,
evidence_d01.csv, ui_strings_d01.csv) are each

- referenced: the key appears in a flow (flows/*.xtflow), a board (ui/boards/project/*.dc.html), a flow or data table
  (data/**/*.json; data/script.json only through a row the vn plays, `playable`), or matches a pattern a generator
  builds keys from (PATTERNS, with the generator that builds it), or
- on NOT_DISPLAYED with the reason (a design ruling, a template, a heading, a key another one replaced).

It fails when a key is neither (a new string from the design team that nothing shows), when a NOT_DISPLAYED key is
referenced after all or no longer exists (the list went stale), and when a pattern matches no key.

--coverage DIR: which keys the test runs showed. Run the D01 checks with SHEREFOX_TEXTLOG=DIR (tests/check_playthrough
log_texts writes every string value of their port traces to DIR/<check>.txt), then this maps each key's zh-TW and en
text (placeholders as wildcards) onto those values and lists, per key, the checks that showed it, and the referenced
keys no check showed. A value that is the key itself counts (list fields the UI localizes). Board texts (data-xt-key) are not port values: they count as shown with their screen.

Usage (from the project root):
    uv run tests/check_d1_strings.py
    uv run tests/check_d1_strings.py --coverage DIR [--all]
"""

from __future__ import annotations

import csv
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOC = ROOT / "source" / "localization" / "d01"

# Keys built at run time from a pattern (the literal key is in no flow or table): regex -> where it is built.
PATTERNS = {
    r"UI_V2_GRADE_[1-5]": "tools/gen_debui_v2.py / gen_end_v2.py: fmt UI_V2_GRADE_{grade}",
    r"REFUTE_D01_[0-9A-Z]+_FACT": "tools/gen_debui_v2.py: SYS_D01_NOW_KNOWN {fact} = fmt {refute line}_FACT",
}

# Not displayed, with the reason (E7 design rulings, docs/d01-string-coverage.md class C / D).
NOT_DISPLAYED = {
    # design ruling (4ac5faf, E7)
    "SYS_D01_LASTSTAND_PROMPT": "ruling E7: the §7.5 screen already shows UI_V2_MY_LAST_CARD and his chain",
    "SYS_D01_TELL_CLEAR": "ruling E7: replaced by the tell panel",
    "SYS_D01_TELL_VAGUE": "ruling E7: replaced by the tell panel",
    "SYS_D01_TELL_VAGUE_LIKELY": "ruling E7: replaced by the tell panel",
    "SYS_D01_TELL_SLIP": "ruling E7: replaced by the tell panel",
    "EXCL_D01_TEMPLATE": "ruling E7: a template; the lines shown are the filled EXCL_D01_<a>_<b>_CATCH",
    # a key another one replaced
    "BEAT_D01_GIVEUP_1": "same text as SCR_D01_S07_L007, which plays instead (ch §12.0 note; 4.3)",
    "UI_V2_GIVE_UP": "he gives up: S07 L007 / L008 then SYS_D01_WIN play instead (4.3, flows §4.12)",
    "UI_V2_CARRY_COUNT": "the carry screen counts with SCR_D01_S06_L002 ({n} / {max}, S06)",
    "UI_V2_CRED": "the bars use UI_V2_CRED_PLAYER / UI_V2_CRED_OPP",
    # scene headings (kind heading: the vn never shows a heading; v1 the same)
    "SCR_D01_S01_TITLE": "scene heading",
    "SCR_D01_S02_TITLE": "scene heading",
    "SCR_D01_S03_TITLE": "scene heading",
    "SCR_D01_S07_TITLE": "scene heading",
    "SCR_D01_S09_TITLE": "scene heading",
    "SCR_D01_S10_TITLE": "scene heading",
    "SCR_D01_S11_TITLE": "scene heading",
    # class C: the design gives no condition or no place on the screen (listed for the design team)
    "SHF_D01_CUT_OPEN_1": "class C: cut opener, no rule for when it plays or which of the three",
    "SHF_D01_CUT_OPEN_2": "class C: cut opener, no rule for when it plays or which of the three",
    "SHF_D01_CUT_OPEN_3": "class C: cut opener, no rule for when it plays or which of the three",
    "UI_V2_ACT_STALL_DESC": "class C: tooltip; ch §13 has no tooltip or description area",
    "UI_V2_REBUT_CUT_DESC": "class C: action description; ch §13 has no description area",
    "UI_V2_REBUT_TOPPLE_DESC": "class C: action description; ch §13 has no description area",
    "UI_V2_SUPPORT_DESC": "class C: action description; ch §13 has no description area",
    "UI_V2_SEIZE_DESC": "class C: claim description; ch §13 has no description area",
    "UI_V2_CLAIM_SOPH_DESC": "class C: claim description; ch §13 has no description area",
    "UI_V2_ACT_STALL_REPEAT": "class C: warning on the 2nd stall in a row; no place on the screen given",
    "UI_V2_CLAIM_CAN_CUT": "class C: claim picker tag with no condition (every evidence claim can rebut)",
    "UI_V2_CLAIM_CRACK_COST": "class C: red-crack cost text; no place given (the row has the red-crack tag)",
    "UI_V2_CLAIM_RESTATE": "class C: restated-claim tag; ch §13's picker lists only sound / sophistry / red crack",
    "UI_V2_CLAIM_VOID": "class C: refuted-claim tag; the picker does not list a void claim (§3.4: void)",
    "UI_V2_DMG_PREVIEW": "class C: damage preview; no rule for what the estimate includes",
    "UI_V2_ENDGAME": "class C: label with no place given (the endgame screen has UI_V2_LAST_CARD)",
    "UI_V2_ISSUE": "class C: label with no place given (claims show the issue chip)",
    "UI_V2_SUPPORT_LEFT": "class C: cover count; cover is once per debate, the button greys out when spent",
    "UI_V2_TELL_POSSIBLE": "class C: the tell panel shows the two actions with UI_V2_TELL_VAGUE / _LIKELY",
    "UI_V2_RECORD_CRACKS": "class C: crack count with no place given in ch §13's public record",
    "UI_V2_BACK_TITLE": "class C: S11's button uses SCR_D01_S11_L003 (design's own line)",
    "UI_V2_NEXT_PLACEHOLDER": "class C: S11 shows SCR_D01_S11_L001-L003 instead",
    "UI_V2_CARRY_LEFT_ASK": "class C: the confirm box shows SCR_D01_S06_L009 and its buttons",
    "SCENE_D01_ATTIC": "class C: full name 'for headings', but the investigation has no place heading (tab: _TAB)",
    "SCENE_D01_BASEMENT": "class C: full name 'for headings', but the investigation has no place heading (tab: _TAB)",
}


def keys() -> dict[str, str]:
    """Every D01 key -> the file it comes from (the first one)."""
    out: dict[str, str] = {}
    for k in json.loads((LOC / "strings_d01.json").read_text(encoding="utf-8")):
        out.setdefault(k, "strings_d01.json")
    for f in ("script_d01.csv", "evidence_d01.csv", "ui_strings_d01.csv"):
        with open(LOC / f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                out.setdefault(r["ID"], f)
    return out


TOKEN = re.compile(r"[A-Z][A-Z0-9_]+")


def referenced() -> dict[str, str]:
    """Every key token the game can show -> where (the first place found)."""
    where: dict[str, str] = {}

    def add(text: str, place: str) -> None:
        for t in TOKEN.findall(text):
            where.setdefault(t, place)
    for p in sorted(glob.glob(str(ROOT / "flows" / "*.xtflow"))):
        add(Path(p).read_text(encoding="utf-8"), f"flows/{Path(p).name}")
    for p in sorted(glob.glob(str(ROOT / "ui" / "boards" / "project" / "*.dc.html"))):
        add(Path(p).read_text(encoding="utf-8"), f"board {Path(p).name}")
    for p in sorted(glob.glob(str(ROOT / "data" / "**" / "*.json"), recursive=True)):
        rel = Path(p).relative_to(ROOT).as_posix()
        if rel == "data/script.json":
            for r in json.loads(Path(p).read_text(encoding="utf-8")):
                if r.get("playable"):
                    where.setdefault(r["text"], "data/script.json (vn)")
            continue
        add(Path(p).read_text(encoding="utf-8"), rel)
    return where


def static_check() -> list[str]:
    ks, ref = keys(), referenced()
    bad = []
    pats = {p: re.compile(p + "$") for p in PATTERNS}
    for p, rx in pats.items():
        if not any(rx.match(k) for k in ks):
            bad.append(f"FAIL pattern {p} matches no D01 key")
    for k in sorted(ks):
        hit = k in ref or any(rx.match(k) for rx in pats.values())
        if k in NOT_DISPLAYED and hit:
            bad.append(f"FAIL {k} is on NOT_DISPLAYED but the game references it ({ref.get(k, 'a pattern')})")
        elif not hit and k not in NOT_DISPLAYED:
            bad.append(f"FAIL {k} ({ks[k]}) is neither shown by the game nor on NOT_DISPLAYED")
    for k in sorted(set(NOT_DISPLAYED) - set(ks)):
        bad.append(f"FAIL NOT_DISPLAYED lists {k}, which is not a D01 key")
    return bad


# ---------------------------------------------------------------- --coverage

def strings(lang: str) -> dict[str, str]:
    with open(ROOT / "strings" / f"{lang}.csv", encoding="utf-8-sig", newline="") as f:
        return {r[0]: r[1] for r in list(csv.reader(f))[1:]}


# keys whose text is filled into a template ({issue}, {formula}, {value}): found inside a value however short
FILLED = re.compile(r"^(ISSUE_D01_|UI_V2_F_|UI_V2_GAUGE_)")


def matcher(text: str, name: str, key: str = ""):
    """A regex for a string's text on screen: {name} is Cedric's name, other placeholders any text. Short texts must
    be the whole value; longer ones (and FILLED keys) may sit inside one (lists, run-on paper text, templates)."""
    text = text.replace("{name}", name)
    parts = re.split(r"\{[a-z_0-9]+\}", text)
    lit = "".join(parts)
    body = ".*?".join(re.escape(x) for x in parts)
    if len(lit.strip()) < 8 and not FILLED.match(key):
        return re.compile("^" + body + "$", re.S)
    return re.compile(body, re.S)


def coverage(d: Path, show_all: bool) -> int:
    sys.path.insert(0, str(ROOT / "tests"))
    from check_playthrough import unescape
    vals: dict[str, set[str]] = {}
    for p in sorted(d.glob("*.txt")):
        vs: set[str] = set()
        for x in p.read_text(encoding="utf-8").split("\n"):
            if x:
                _flatten(unescape(x), vs)
        vals[p.stem] = vs
    if not vals:
        print(f"error: no logs in {d} (run the checks with SHEREFOX_TEXTLOG={d})")
        return 2
    ks, ref = keys(), referenced()
    S = {lang: strings(lang) for lang in ("zh-TW", "en")}
    unshown = []
    for k in sorted(ks):
        if k in NOT_DISPLAYED:
            continue
        seen = []
        for check, vs in vals.items():
            if k in vs:          # a list field the UI localizes (ui_list localize=...) carries the key itself
                seen.append(check)
                continue
            for lang in ("zh-TW", "en"):
                t = S[lang].get(k, "")
                if not t.strip():
                    continue
                rx = matcher(t, S[lang]["SPK_D01_CEDRIC"], k)
                if any(rx.search(v) for v in vs):
                    seen.append(check)
                    break
        if not seen and "data-xt-key" in _board_attr(k):
            seen = ["(board text)"]
        if seen:
            if show_all:
                print(f"{k}: {', '.join(seen)}")
        else:
            unshown.append(k)
    print(f"{len(ks)} keys, {len(NOT_DISPLAYED)} not displayed, {len(unshown)} referenced but shown by no check:")
    for k in unshown:
        print(f"  {k} ({ref.get(k, 'pattern')})")
    return 0


def _flatten(v: str, out: set[str]) -> None:
    """A port value; a list port's value is JSON: its string leaves are what the screen shows."""
    out.add(v)
    if v[:1] in "[{":
        try:
            stack = [json.loads(v)]
        except ValueError:
            return
        while stack:
            x = stack.pop()
            if isinstance(x, str):
                out.add(x)
            elif isinstance(x, list):
                stack += x
            elif isinstance(x, dict):
                stack += list(x.values())


_BOARDS: str | None = None


def _board_attr(k: str) -> str:
    global _BOARDS
    if _BOARDS is None:
        _BOARDS = "".join(Path(p).read_text(encoding="utf-8")
                          for p in glob.glob(str(ROOT / "ui" / "boards" / "project" / "*.dc.html")))
    return "data-xt-key" if f'data-xt-key="{k}"' in _BOARDS else ""


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--coverage":
        return coverage(Path(args[1]), "--all" in args)
    bad = static_check()
    for b in bad:
        print(b)
    n = len(keys())
    if bad:
        print(f"FAILED: {len(bad)} problem(s) in {n} D01 keys")
        return 1
    print(f"ok: {n} D01 keys, {n - len(NOT_DISPLAYED)} shown, {len(NOT_DISPLAYED)} on the not-displayed list")
    return 0


if __name__ == "__main__":
    sys.exit(main())
