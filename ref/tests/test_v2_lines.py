"""v2 4.3: the debate screen's line selection (sherefox_ref.v2.lines) against the chapter's worked routes (ch §12.1-
§12.4) and the S07 / §12.0 conditions.

The chapter writes each route out line by line. Only the lines that carry a string id in the localization package are
compared: the S07 lines, the BEAT_D01_* interludes, Arthur's hints (TELL_D01_HINT_*) and the speaker lines of §9 /
§11 that the playback adds as their own steps. Where the chapter's route text and the selection rule disagree, the
round is listed in DIVERGES with the reason (reported to the design owner; the rule is not bent to fit one route).
"""

import pytest

from sherefox_ref.v2 import lines as LN
from sherefox_ref.v2.model import initial_state
from sherefox_ref.v2.resolve import resolve_round
from sherefox_ref.v2.routes import ROUTES

KEYS = LN.package_keys()
TRACKED = ("BEAT_D01_", "TELL_D01_HINT_", "SCR_D01_S07_", "STATE_D01_SHF_BREACHED", "STATE_D01_ART_BREACHED",
           "REACT_D01_09A_2", "REACT_D01_09A_3")


def run(name):
    """[(tell line, [tracked keys of the playback in order], all steps)] per round of a route, with the chapter's
    stated tells."""
    rt = ROUTES[name]
    s = initial_state(rt.loadout)
    memo = LN.Memo()
    out = []
    for pa, oa, tl in rt.rounds:
        if s.outcome:
            break
        s2, ev = resolve_round(s, pa, oa)
        hint = LN.tell_line(s, tl, memo)
        steps = LN.round_steps(s, pa, oa, ev, s2, memo, KEYS)
        keys = [k for st in steps for k in (st.line, st.sys) if k and k.startswith(TRACKED)]
        out.append((hint[1] if hint else None, keys, steps))
        s = s2
    return out


# The chapter's lines with ids, per round: (tell line, playback lines in order). Hints the chapter writes without an
# id (an ad-hoc variant) count as "no keyed line" and are listed in DIVERGES when the rule plays one.
CHAPTER = {
    "A": {1: ("TELL_D01_HINT_ASSERT", []), 2: ("TELL_D01_HINT_STALL", []),
          3: ("TELL_D01_HINT_FACT", ["BEAT_D01_CLASH_1", "BEAT_D01_CLASH_2"]), 4: (None, []), 5: (None, []),
          6: (None, []), 7: ("TELL_D01_HINT_PUSH", ["BEAT_D01_07A_1", "BEAT_D01_07A_2"]),
          8: (None, ["SCR_D01_S07_L005", "SCR_D01_S07_L009"]), 9: ("SCR_D01_S07_L010", [])},
    "B": {1: (None, ["BEAT_D01_P1A_1", "BEAT_D01_P1A_2"]), 2: ("TELL_D01_HINT_REBUT", []),
          3: (None, ["BEAT_D01_02C_1"]), 4: ("TELL_D01_HINT_SLIP", ["BEAT_D01_GUILT_1"]),
          5: (None, ["SCR_D01_S07_L007", "SCR_D01_S07_L008"])},
    "C": {1: (None, ["BEAT_D01_SOPH_06B_1"]), 2: (None, []),
          3: ("TELL_D01_HINT_FACT", ["BEAT_D01_SOPH_06C_1", "BEAT_D01_ANGER_1"]),
          4: ("TELL_D01_HINT_KEY", ["BEAT_D01_REDCRACK_1", "SCR_D01_S07_L005"]),
          5: ("BEAT_D01_LASTCARD_1", ["BEAT_D01_LASTCARD_4", "BEAT_D01_LASTCARD_2", "BEAT_D01_LASTCARD_5",
                                      "BEAT_D01_LASTCARD_6"]),
          6: (None, ["BEAT_D01_09A_1", "REACT_D01_09A_3", "REACT_D01_09A_2"]), 7: (None, []), 8: (None, []),
          9: (None, []), 10: (None, [])},
    "D": {1: (None, []), 2: (None, []), 3: (None, []),
          4: (None, ["BEAT_D01_REFUTED_1", "BEAT_D01_REFUTED_2", "BEAT_D01_REFUTED_3", "BEAT_D01_REFUTED_4",
                     "STATE_D01_SHF_BREACHED", "STATE_D01_ART_BREACHED"]),
          5: (None, []), 6: (None, []), 7: ("TELL_D01_HINT_NOCUT", ["BEAT_D01_REVERSE_1"]),
          8: (None, ["SCR_D01_S07_L016"])},
}

# (route, round): what the rule gives instead, and why the chapter's text differs.
DIVERGES = {
    ("A", 1): ("tell", None, "vague 立論／強辯 without ★: nothing reliable to hint (B1, C1, D1, same tell, show none)"),
    ("A", 4): ("tell", "TELL_D01_HINT_ASSERT", "★ on 立論, first time in this debate (the chapter shows no hint)"),
    ("B", 1): ("play", ["BEAT_D01_P1A_1", "BEAT_D01_P1A_2", "BEAT_D01_CLASH_1", "BEAT_D01_CLASH_2"],
               "first clash of the debate: the split-screen beat (written out only in A3)"),
    ("B", 3): ("tell", "TELL_D01_HINT_FACT", "F1 is a fact on a clear tell (A3, C3 show the hint; B3 does not)"),
    ("C", 2): ("tell", "TELL_D01_HINT_REBUT", "★ on 反駁, first time in this debate (B2 shows it, C2 does not)"),
    ("C", 5): ("play", ["SCR_D01_S07_L011", "BEAT_D01_LASTCARD_4", "BEAT_D01_LASTCARD_2", "BEAT_D01_LASTCARD_5",
                        "BEAT_D01_LASTCARD_6"],
               "S07 L011 (he plays his last card) is not written out in C5; it plays when the last card is played"),
    ("C", 6): ("play", ["BEAT_D01_09A_1", "REACT_D01_09A_3", "REACT_D01_09A_2", "BEAT_D01_CLASH_1",
                        "BEAT_D01_CLASH_2"], "first clash of the debate (see B1)"),
    ("C", 7): ("play", ["BEAT_D01_REDCRACK_1", "BEAT_D01_07A_1", "BEAT_D01_07A_2"],
               "red crack again (C7 writes a variant without an id) and 07A cuts (C7 omits Martha / Briggs)"),
    ("C", 8): ("tell", "TELL_D01_HINT_STALL", "★ on 周旋, first time in this debate"),
    ("C", 9): ("tell", "TELL_D01_HINT_ASSERT", "clear 立論 on a lie he can be cut on, first time in this debate"),
    ("D", 2): ("tell", "TELL_D01_HINT_STALL", "★ on 周旋, first time in this debate (A2 shows it, D2 does not)"),
    ("D", 3): ("tell", "TELL_D01_HINT_FACT", "F1 on a clear tell (D3 has Arthur say it after the miss, no id)"),
    ("D", 5): ("both", ("TELL_D01_HINT_KEY", ["BEAT_D01_CLASH_1", "BEAT_D01_CLASH_2"]),
               "L2 on a clear tell (D5 writes an ad-hoc hint without an id); first clash of the debate (see B1)"),
    ("D", 7): ("tell", None, "vague 強辯／反駁 without ★: no hint (the chapter's NOCUT line is on a vague tell)"),
    ("D", 8): ("play", ["BEAT_D01_LASTSTAND_FAIL_1", "SCR_D01_S07_L016"],
               "D8 writes a variant of LASTSTAND_FAIL_1 without an id"),
}


@pytest.mark.parametrize("name", "ABCD")
def test_routes_against_the_chapter(name):
    got = run(name)
    assert len(got) == len(CHAPTER[name])
    bad = []
    for n, (hint, keys, _) in enumerate(got, start=1):
        want_hint, want_keys = CHAPTER[name][n]
        div = DIVERGES.get((name, n))
        if div and div[0] in ("tell", "both"):
            dh = div[1][0] if div[0] == "both" else div[1]
            assert hint == dh, f"{name}{n}: listed divergence changed: tell {hint}"
            want_hint = dh
        if div and div[0] in ("play", "both"):
            dk = div[1][1] if div[0] == "both" else div[1]
            assert keys == dk, f"{name}{n}: listed divergence changed: {keys}"
            want_keys = dk
        if hint != want_hint:
            bad.append(f"{name}{n} tell {hint} (chapter {want_hint})")
        if keys != want_keys:
            bad.append(f"{name}{n} play {keys} (chapter {want_keys})")
    assert not bad, bad


def test_every_key_exists_and_speakers_follow_the_package():
    import csv
    path = LN._PKG.parent / "script_d01.csv"
    with open(path, encoding="utf-8-sig", newline="") as f:
        spk = {r["ID"]: r["speaker_en"] for r in csv.DictReader(f)}
    names = {LN.SH: "Sherefox", LN.CE: "Cedric", LN.AR: "Arthur", LN.MRS: "Mrs Hyde", LN.BRI: "Briggs",
             LN.MAR: "Martha", LN.IRE: "Irene", LN.INS: "Inspector Baskerville", LN.STAGE: "(Staging)"}
    for name in "ABCD":
        for hint, _, steps in run(name):
            for st in steps:
                for k in (st.line, st.sys):
                    assert not k or k in KEYS or k.startswith(("UI_V2_",)), k
                if st.line and st.line in spk:
                    assert spk[st.line] == names[st.who], (st.line, st.who, spk[st.line])


def test_tail_hachiku_keep_only_when_held():
    # A3: a clash with 破竹 2 held -> 破竹維持 last; A1 (0 -> 1) and A9 (debate over) none
    got = run("A")
    assert got[2][2][-1].sys == "SYS_D01_HACHIKU_KEEP"
    assert all(st.sys != "SYS_D01_HACHIKU_KEEP" for st in got[0][2] + got[8][2])


def test_opening_and_outro():
    assert LN.PRE_LINES == ("SCR_D01_S07_L001", "SCR_D01_S07_L002", "SCR_D01_S07_L003")
    assert LN.OPENING_SYS == "SCR_D01_S07_L004"
    assert LN.outro("win")[0] == "SCR_D01_S07_L012" and LN.outro("loss") == LN.LOSS_LINES
    assert "SCR_D01_S07_L016" not in LN.outro("loss")   # shown inside the debate (route D R8)


def test_hints_do_not_repeat_and_none_in_the_last_stand():
    for name in "ABCD":
        hints = [h for h, _, _ in run(name) if h and h.startswith("TELL_D01_HINT_")]
        assert len(hints) == len(set(hints)), (name, hints)
    assert run("D")[7][0] is None
