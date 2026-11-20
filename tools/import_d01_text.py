# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Import a new delivery of the D01 text (script_d01.csv, evidence_d01.csv, strings_d01.json) and rebuild everything
that depends on it.

Usage (from the project root):
    uv run tools/import_d01_text.py DIR            validate DIR's three files, copy them into source/localization/d01/,
                                                   rebuild the data and flows, check the generators, pack the bundle
    uv run tools/import_d01_text.py DIR --dry-run  validate and report the differences only (copies nothing)

DIR holds the three files of a text delivery (a design-repo localization/d01/ or a writer's hand-off). README.md and
ui_strings_d01.csv in source/localization/d01/ are never touched (`build_data.py --import-localization` copies the
whole package instead).

Validation before anything is copied (exit 1 on a problem):
  - the JSON equals the two CSVs merged (same keys, same zh-TW and en);
  - no key of the current files is missing (a removed key needs a deliberate code change, not an import);
  - every key keeps its placeholders ({n}, {a}, ...): new zh-TW = new en = current zh-TW, as sets;
  - a new script line of a scene the step table plays (SCR_D01_Sxx_Lnnn[A-I], build_data D01_SCRIPT_SCENES) has a row in
    source/staging/staging_d01.csv (a line inserted later is L<number><letter>, e.g. L002A: it plays after L<number>).
Then: build_data.py, gen_flows.py, the --check of every generator, `xtatrium pack --game .` (the tests read the packed
bundle) and the static string check (tests/check_d1_strings.py). The run tests to follow are printed at the end
(tests/README.md, "Re-importing the D01 text").
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D01 = ROOT / "source" / "localization" / "d01"
STAGING = ROOT / "source" / "staging" / "staging_d01.csv"
FILES = ("script_d01.csv", "evidence_d01.csv", "strings_d01.json")
SCENES = ("S01", "S02", "S03", "S04", "S07", "S08", "S10")   # tools/build_data.py D01_SCRIPT_SCENES
PLACEHOLDER = re.compile(r"\{[a-z_0-9]+\}")
FOLLOW_UP = ("ref: uv run --project ref pytest ref -q (one known old failure: test_tags)",
             "uv run tests/check_debate_v2.py", "uv run tests/check_d1_play.py", "uv run tests/check_d1_lines.py",
             "uv run tests/check_d1_m3.py", "uv run tests/check_d1_story.py", "uv run tests/check_d1_full.py",
             "uv run tests/check_d1_fuzz.py", "uv run tests/check_music.py",
             "v1: check_playthrough, check_case, check_debate, check_debate_play, check_nav, check_policy, check_settings",
             "text fit: uv run tests/shots_d1_text.py DIR (review screenshots of the longest strings per box)")


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate(src: Path) -> list[str]:
    errors: list[str] = []
    for name in FILES:
        if not (src / name).is_file():
            errors.append(f"{src / name}: missing")
    if errors:
        return errors
    rows: dict[str, dict] = {}
    for name in FILES[:2]:
        for r in read_csv(src / name):
            if r["ID"] in rows:
                errors.append(f"{name}: duplicate key {r['ID']}")
            rows[r["ID"]] = r
    js = read_json(src / "strings_d01.json")
    for k in sorted(rows.keys() ^ js.keys()):
        errors.append(f"{k}: in {'the CSVs' if k in rows else 'strings_d01.json'} only")
    for k in sorted(rows.keys() & js.keys()):
        for lang in ("zh-TW", "en"):
            if rows[k][lang] != js[k][lang]:
                errors.append(f"{k}: strings_d01.json {lang} differs from the CSV")
    cur: dict[str, dict] = {}
    for name in FILES[:2]:
        cur.update({r["ID"]: r for r in read_csv(D01 / name)})
    for k in sorted(cur.keys() - rows.keys()):
        errors.append(f"{k}: removed (the current files have it)")
    for k, r in rows.items():
        want = set(PLACEHOLDER.findall(cur[k]["zh-TW"] if k in cur else r["zh-TW"]))
        for lang in ("zh-TW", "en"):
            got = set(PLACEHOLDER.findall(r[lang]))
            if got != want:
                errors.append(f"{k}: {lang} placeholders {sorted(got)} != {sorted(want)}")
    staged = {r["id"] for r in read_csv(STAGING)}
    for k in rows.keys() - cur.keys():
        m = re.fullmatch(r"SCR_D01_(S\d\d)_L\d{3}[A-I]?", k)
        if m and m.group(1) in SCENES and k not in staged:
            errors.append(f"{k}: new line with no row in {STAGING.relative_to(ROOT)} (add one next to its neighbours)")
        elif k.startswith("SCR_D01_") and not m and not k.endswith("_TITLE"):
            errors.append(f"{k}: a script line id must be SCR_D01_Sxx_Lnnn or Lnnn + one letter A-I")
    return errors


def report(src: Path) -> None:
    for name in FILES[:2]:
        new, old = read_csv(src / name), {r["ID"]: r for r in read_csv(D01 / name)}
        added = [r["ID"] for r in new if r["ID"] not in old]
        diff = {lang: [r["ID"] for r in new if r["ID"] in old and r[lang] != old[r["ID"]][lang]]
                for lang in ("zh-TW", "en")}
        print(f"{name}: {len(new)} rows, added {added or 'none'}, zh-TW changed {len(diff['zh-TW'])}, "
              f"en changed {len(diff['en'])}")


def copy_normalized(src: Path, dst: Path) -> None:
    """Copy with the repo's formatting, the content unchanged: LF line ends (CSV keeps its BOM), the JSON as
    json.dumps(indent=1, ensure_ascii=False) with no final newline (the format of the design repo's file)."""
    text = src.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
    if dst.suffix == ".json":
        dst.write_bytes(json.dumps(json.loads(text), ensure_ascii=False, indent=1).encode("utf-8"))
    else:
        dst.write_bytes(("﻿" + text).encode("utf-8"))


def cli() -> list[str]:
    for var, rel in (("XTATRIUM_EXE", ""), ("XTATRIUM_SDK", "xtatrium"),
                     ("XTATRIUM", "src/XTAtrium.Headless/bin/Release/net10.0/xtatrium")):
        if os.environ.get(var):
            return [str(Path(os.environ[var]) / rel) if rel else os.environ[var]]
    found = shutil.which("xtatrium")
    if not found:
        raise SystemExit("no xtatrium CLI: set XTATRIUM_SDK (tests/README.md, Environment)")
    return [found]


def run(cmd: list[str]) -> None:
    print("$", " ".join(cmd), flush=True)
    if subprocess.run(cmd, cwd=ROOT).returncode != 0:
        raise SystemExit(f"failed: {' '.join(cmd)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", help="directory holding script_d01.csv, evidence_d01.csv and strings_d01.json")
    ap.add_argument("--dry-run", action="store_true", help="validate and report only")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    src = Path(args.dir)
    errors = validate(src)
    for e in errors:
        print("error:", e)
    if errors:
        return 1
    report(src)
    if args.dry_run:
        return 0
    for name in FILES:
        copy_normalized(src / name, D01 / name)
    print(f"copied {', '.join(FILES)} into {D01.relative_to(ROOT)}")
    uv = ["uv", "run"]
    run(uv + ["tools/build_data.py"])
    run(uv + ["tools/gen_flows.py"])
    for tool in ("build_data.py", "gen_flows.py", "gen_debate.py", "gen_debate_v2.py"):
        run(uv + [f"tools/{tool}", "--check"])
    run(cli() + ["pack", "--game", "."])
    run(uv + ["tests/check_d1_strings.py"])
    print("imported. Next (tests/README.md, \"Re-importing the D01 text\"):")
    for line in FOLLOW_UP:
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
