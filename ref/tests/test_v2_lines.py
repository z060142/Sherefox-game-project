"""v2 4.3 / E5: the debate screen's line selection (sherefox_ref.v2.lines) against the chapter's worked routes (ch §12.1-
§12.4), the S07 / §12.0 conditions and Arthur's hint rule (v2 demo E5, design 6a94528 / 93d037b).

CHAPTER is the expectation written by hand from the chapter, not from ref: per round, the lines with an id shown with
the tell (his tell line, Arthur's hint: the per-round hint table of the plan's E5 section, final version = design
93d037b's routes) and the tracked lines of the playback in order (the S07 lines, the BEAT_D01_* interludes, the state
lines, the E5 system lines), read off the route text and, for the lines E5 adds, off the route tables (the 破竹 and
破防 columns, the claims used) under the timing list of the plan's E5 section. Where the chapter's route text writes
something else, the round is in DIVERGES with what the text says and why the rule's line is expected instead.
"""

import pytest

from sherefox_ref.v2 import lines as LN
from sherefox_ref.v2.model import OA, PA, OpponentAction, PlayerAction, initial_state, tell
from sherefox_ref.v2.resolve import resolve_round
from sherefox_ref.v2.routes import ROUTES, replay

KEYS = LN.package_keys()
TRACKED = ("BEAT_D01_", "SCR_D01_S07_", "STATE_D01_", "REACT_D01_09A_2", "REACT_D01_09A_3", "SYS_D01_HACHIKU_KEEP",
           "SYS_D01_CRACK", "SYS_D01_PSYCH_NOTE", "SYS_D01_PRIVATE", "SYS_D01_COVER_WASTED")
V, C = "vague", "clear"
AT, FO, RE, PR, LAST = OA.ATTACK, OA.FORCE, OA.REBUT, OA.PARRY, OA.LAST
OA_PARRY, OA_REBUT = OpponentAction(PR), OpponentAction(RE)


def run(name):
    """[(tell line keys, [tracked keys of the playback in order], all steps)] per round of a route, with the chapter's
    stated tells."""
    rt = ROUTES[name]
    s = initial_state(rt.loadout)
    memo = LN.Memo()
    out = []
    for pa, oa, tl in rt.rounds:
        if s.outcome:
            break
        s2, ev = resolve_round(s, pa, oa)
        tells = [k for _, k in LN.tell_lines(s, tl, memo, KEYS)]
        steps = LN.round_steps(s, pa, oa, ev, s2, memo, KEYS)
        keys = [k for st in steps for k in (st.line, st.sys) if k and k.startswith(TRACKED)]
        out.append((tells, keys, steps))
        s = s2
    return out


# hint keys
H_LAST, H_SLIP, H_KEY, H_NOCUT, H_FACT = (f"TELL_D01_HINT_{w}" for w in ("LAST", "SLIP", "KEY", "NOCUT", "FACT"))
H_ASSERT, H_PUSH = "TELL_D01_HINT_ASSERT", "TELL_D01_HINT_PUSH"
HK1, HK2, HK3 = (f"STATE_D01_SHF_HACHIKU_{n}" for n in (1, 2, 3))
ART_HK, SHAKEN, KEEP = "STATE_D01_ART_HACHIKU", "STATE_D01_SHF_SHAKEN", "SYS_D01_HACHIKU_KEEP"
CLASH = ["BEAT_D01_CLASH_1", "BEAT_D01_CLASH_2"]
# (route) -> round -> (tell lines, playback lines). Hints: A R1 −, R2 FACT, R3 ASSERT, R4 KEY, R5 −, R6 −, R7 PUSH,
# R8 −, R9 LAST; B R1 NOCUT, R2 FACT, R3 ASSERT, R4 SLIP, R5 −; C R1 −, R2 FACT, R3 ASSERT, R4 KEY, R5 LAST, R6 PUSH,
# R7-R10 −; D R1 −, R2 FACT, R3 ASSERT, R4 KEY, R5 −, R6 −, R7 NOCUT, R8 −. His tell line on every clear tell of the
# tables (明示), the lines of an action in turn (PUSH_1, PUSH_2, ...). 破竹 up: SHF_HACHIKU_<n>, the first time
# ART_HACHIKU after it; 破竹 held at ≥ 1 in a round the debate goes on after: KEEP; his first 破防: SHAKEN.
CHAPTER = {
    "A": {1: ([], [SHAKEN, HK1, ART_HK]),
          2: ([H_FACT], [HK2]),
          3: (["TELL_D01_ASSERT_1", H_ASSERT], CLASH + [KEEP]),
          4: ([H_KEY], [HK3]),
          5: ([], [KEEP]),
          6: (["TELL_D01_ASSERT_1"], [KEEP]),
          7: (["TELL_D01_PUSH_1", H_PUSH], ["BEAT_D01_07A_1", "BEAT_D01_07A_2", KEEP]),
          8: ([], ["STATE_D01_SHF_BREAK", "SCR_D01_S07_L005", "SCR_D01_S07_L009", KEEP]),
          9: ([H_LAST, "SCR_D01_S07_L010"], [])},
    "B": {1: ([H_NOCUT], ["BEAT_D01_P1A_1", "BEAT_D01_P1A_2"] + CLASH + ["SYS_D01_PSYCH_NOTE"]),
          2: ([H_FACT], [SHAKEN, HK1, ART_HK]),
          3: (["TELL_D01_ASSERT_1", H_ASSERT], ["BEAT_D01_02C_1", KEEP]),
          4: ([H_SLIP], ["BEAT_D01_GUILT_1", KEEP]),
          5: ([], ["STATE_D01_SHF_BREAK", "SCR_D01_S07_L007", "SCR_D01_S07_L008"])},
    "C": {1: ([], ["BEAT_D01_SOPH_06B_1", SHAKEN, HK1, ART_HK]),
          2: ([H_FACT], [HK2]),
          3: (["TELL_D01_ASSERT_1", H_ASSERT], ["BEAT_D01_SOPH_06C_1", HK3, "BEAT_D01_ANGER_1"]),
          4: (["TELL_D01_PUSH_1", H_KEY], ["BEAT_D01_REDCRACK_1", "STATE_D01_SHF_BREAK", "SCR_D01_S07_L005", KEEP]),
          5: (["BEAT_D01_LASTCARD_1", H_LAST], ["SCR_D01_S07_L011", "BEAT_D01_LASTCARD_4", "BEAT_D01_LASTCARD_2",
                                                "BEAT_D01_LASTCARD_5", "BEAT_D01_LASTCARD_6"]),
          6: (["TELL_D01_PUSH_2", H_PUSH], ["BEAT_D01_09A_1", "REACT_D01_09A_3", "REACT_D01_09A_2"] + CLASH
              + ["SYS_D01_PRIVATE"]),
          7: ([], ["BEAT_D01_REDCRACK_1", "BEAT_D01_07A_1", "BEAT_D01_07A_2", HK1]),
          8: ([], [HK2]),
          9: (["TELL_D01_ASSERT_1"], [HK3]),
          10: ([], [])},
    "D": {1: ([], [SHAKEN, HK1, ART_HK]),
          2: ([H_FACT], [HK2]),
          3: (["TELL_D01_ASSERT_1", H_ASSERT], []),
          4: ([H_KEY], ["BEAT_D01_REFUTED_1", "BEAT_D01_REFUTED_2", "BEAT_D01_REFUTED_3", "BEAT_D01_REFUTED_4",
                        "STATE_D01_SHF_BREACHED", "STATE_D01_ART_BREACHED"]),
          5: (["TELL_D01_ASSERT_1"], CLASH),
          6: (["TELL_D01_ASSERT_1"], []),
          7: ([H_NOCUT], ["BEAT_D01_REVERSE_1"]),
          8: ([], ["BEAT_D01_LASTSTAND_FAIL_1", "SCR_D01_S07_L016"])},
}

# (route, round): what the chapter's route text shows instead of CHAPTER, and why CHAPTER expects the rule's line
# (reported to the design owner; the rule is not bent to fit one route).
DIVERGES = {
    ("A", 7): ("tell", ["TELL_D01_PUSH_2", H_PUSH],
               "the text gives him 「我受夠這場鬧劇了。」 (PUSH_2) on route A's first clear 強辯; his tell lines of an "
               "action take turns from _1, so the first one is PUSH_1 「夠了。」 (design question)"),
}
# Route text the expectation above already settles (earlier rulings; not divergences): the split-screen beat
# BEAT_D01_CLASH_* on the first clash of every debate (B1, C6, D5; written out only in A3), S07 L011 at the start of
# the endgame round (C5), 07A's Martha / Briggs beat and the red-crack beat whenever they happen (C7, plan E5), D8's
# id-less variant of LASTSTAND_FAIL_1; the E5 lines the route text does not write out (破竹, 破防, the tell lines,
# 破竹維持 in a Break round the debate goes on after: A8, C4).


@pytest.mark.parametrize("name", "ABCD")
def test_routes_against_the_chapter(name):
    got = run(name)
    assert len(got) == len(CHAPTER[name])
    bad = []
    for n, (tells, keys, _) in enumerate(got, start=1):
        want_tells, want_keys = CHAPTER[name][n]
        div = DIVERGES.get((name, n))
        if div:
            assert tells != div[1], f"{name}{n}: listed divergence is gone (tell {tells})"
        if tells != want_tells:
            bad.append(f"{name}{n} tell {tells} (chapter {want_tells})")
        if keys != want_keys:
            bad.append(f"{name}{n} play {keys} (chapter {want_keys})")
    assert not bad, bad


def test_arthur_hint_table():
    """The plan's per-round hint table (final: design 93d037b), Arthur's line only."""
    table = {"A": "- FACT ASSERT KEY - - PUSH - LAST", "B": "NOCUT FACT ASSERT SLIP -",
             "C": "- FACT ASSERT KEY LAST PUSH - - - -", "D": "- FACT ASSERT KEY - - NOCUT -"}
    for name, row in table.items():
        got = [next((k[len("TELL_D01_HINT_"):] for k in t if k.startswith("TELL_D01_HINT_")), "-") for t, _, _ in run(name)]
        assert got == row.split(), (name, got)


def test_every_key_exists_and_speakers_follow_the_package():
    import csv
    path = LN._PKG.parent / "script_d01.csv"
    with open(path, encoding="utf-8-sig", newline="") as f:
        spk = {r["ID"]: r["speaker_en"] for r in csv.DictReader(f)}
    names = {LN.SH: "Sherefox", LN.CE: "Cedric", LN.AR: "Arthur", LN.MRS: "Mrs Hyde", LN.BRI: "Briggs",
             LN.MAR: "Martha", LN.IRE: "Irene", LN.INS: "Inspector Baskerville", LN.STAGE: "(Staging)"}
    for name in "ABCD":
        rt = ROUTES[name]
        s = initial_state(rt.loadout)
        memo = LN.Memo()
        for pa, oa, tl in rt.rounds:
            if s.outcome:
                break
            s2, ev = resolve_round(s, pa, oa)
            pairs = LN.tell_lines(s, tl, memo, KEYS)
            pairs += [(st.who, st.line) for st in LN.round_steps(s, pa, oa, ev, s2, memo, KEYS) if st.line]
            for st in LN.round_steps(s, pa, oa, ev, s2, LN.Memo(), KEYS):
                assert not st.sys or st.sys in KEYS or st.sys.startswith("UI_V2_"), st.sys
            for who, k in pairs:
                assert k in KEYS, k
                if k in spk:
                    assert spk[k] == names[who], (k, who, spk[k])
            s = s2


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


# ---------------------------------------------------------------------------------------------- E5: the hint rule


def state(route: str, rnd: int):
    """The state before round `rnd` of a ref route."""
    return replay(route).states[rnd - 1]


def hints(s, tells, memo=None):
    memo = memo or LN.Memo()
    return [[k for _, k in LN.tell_lines(s, t, memo, KEYS)] for t in tells]


def test_rule_1_last_every_time_dying_gasp_included():
    s = state("C", 5)                                    # his last card P05: the beat first, then the hint, each time
    t = tell(C, (LAST,), card="P05")
    assert hints(s, [t, t]) == [["BEAT_D01_LASTCARD_1", H_LAST]] * 2
    s = state("A", 9)                                    # the dying gasp K1: the hint, then his S07 L010
    t = tell(C, (LAST,), card="K1")
    assert hints(s, [t, t]) == [[H_LAST, "SCR_D01_S07_L010"]] * 2


def test_rule_2_slip_every_time_and_before_key_nocut_fact():
    s = state("B", 4)
    t = tell(V, (AT, FO), star=AT, card="U1", partial=True)
    assert hints(s, [t, t, t]) == [[H_SLIP]] * 3


def test_rule_3_key_once_then_falls_through():
    s = state("A", 4)                                    # L2: the keystone; route A can cut it (01A)
    vague, clear = tell(V, (AT, FO), star=AT, card="L2"), tell(C, (AT,), card="L2")
    assert hints(s, [vague, vague]) == [[H_KEY], []]     # used: a vague tell has nothing to fall to
    assert hints(s, [clear, clear]) == [["TELL_D01_ASSERT_1", H_KEY], ["TELL_D01_ASSERT_1", H_ASSERT]]


def test_rule_4_nocut_sound_claims_only_once():
    # B R1: no carried 正論 breaks L1 (no 11A / 11B / 03A); D R7: 04C (sophistry since R4) breaks L4 but does not count
    assert hints(state("B", 1), [tell(V, (AT, FO), card="L1")] * 2) == [[H_NOCUT], []]
    assert hints(state("D", 7), [tell(V, (FO, RE), card="L4")]) == [[H_NOCUT]]
    assert hints(state("A", 1), [tell(V, (AT, FO), card="L1")]) == [[]]       # 11A can cut it
    # a fact is never "a lie no one can cut"; once spent it falls through to the action on a clear tell
    s = state("B", 1)
    assert hints(s, [tell(V, (AT, FO), card="L1"), tell(C, (AT,), card="L1")]) == [
        [H_NOCUT], ["TELL_D01_ASSERT_1", H_ASSERT]]


def test_rule_5_fact_once_then_falls_through():
    s = state("A", 2)
    vague, clear = tell(V, (PR, AT), star=PR, card="F1"), tell(C, (AT,), card="F1")
    assert hints(s, [vague, vague, clear]) == [[H_FACT], [], ["TELL_D01_ASSERT_1", H_ASSERT]]


def test_rule_6_action_hints_clear_only_once_per_action():
    s = state("A", 2)
    memo = LN.Memo()
    memo.hints.add(H_FACT)
    star = tell(V, (PR, AT), star=PR, card="F1")          # ★ on a vague tell: no action hint (the hidden value)
    assert hints(s, [star], memo) == [[]]
    stall, rebut = tell(C, (PR,)), tell(C, (RE,))
    assert hints(s, [stall, stall, rebut, rebut], memo) == [
        ["TELL_D01_STALL_1", "TELL_D01_HINT_STALL"], ["TELL_D01_STALL_1"],
        ["TELL_D01_REBUT_1", "TELL_D01_HINT_REBUT"], ["TELL_D01_REBUT_2"]]


def test_his_tell_lines_clear_only_and_in_turn():
    s = state("A", 7)
    push, vague = tell(C, (FO,), card="L4"), tell(V, (FO, AT), card="L4")
    got = hints(s, [vague, push, push, vague, push])
    assert [[k for k in g if not k.startswith("TELL_D01_HINT_")] for g in got] == [
        [], ["TELL_D01_PUSH_1"], ["TELL_D01_PUSH_2"], [], ["TELL_D01_PUSH_1"]]
    assert LN.tell_keys(KEYS, AT) == ["TELL_D01_ASSERT_1"] and LN.tell_keys(KEYS, OA.LAST) == []


def test_no_tell_lines_in_the_last_stand():
    assert run("D")[7][0] == []


# ---------------------------------------------------------------------------------------------- E5: the timing list


def steps_of(s, pa, oa, memo=None):
    s2, ev = resolve_round(s, pa, oa)
    return [k for st in LN.round_steps(s, pa, oa, ev, s2, memo or LN.Memo(), KEYS) for k in (st.who, st.line, st.sys)
            if k]


def test_hachiku_lines_and_arthur_once():
    got = run("C")
    assert [k for k in got[0][1] if k.startswith("STATE_D01_")][-2:] == [HK1, ART_HK]    # R1: 0 -> 1, first time
    assert HK1 in got[6][1] and ART_HK not in got[6][1]                                 # R7: 0 -> 1 again
    assert [HK2, HK3] == [k for r in (1, 2) for k in got[r][1] if k in (HK2, HK3)]


def test_shaken_on_his_first_guard_down_only():
    got = run("A")
    assert got[0][1].count(SHAKEN) == 1
    assert all(SHAKEN not in keys for _, keys, _ in got[1:])      # R4, R7: 破防 again, no line


def test_cornered_when_he_enters_the_cornered_state():
    s = state("A", 1)
    memo = LN.Memo()
    ev = [{"kind": "round"}, {"kind": "threshold_crossed", "stat": "P"}]
    st = LN.round_steps(s, PlayerAction(PA.STALL), None, ev, s, memo, KEYS)
    assert [(x.who, x.line, x.sys) for x in st] == [
        (LN.SH, "FOG_D01_1", ""), ("", "", "SYS_D01_PSYCH_CROSS"), (LN.AR, "STATE_D01_ART_CORNERED", "")]


def test_crack_on_each_sophistry_link_not_on_a_psych_card():
    s = state("A", 1)                                     # 01B shows as 詭辯 to route A (the tube was appraised)
    from sherefox_ref.v2 import known as K
    assert K.view(s, "01B").soph
    keys = steps_of(s, PlayerAction(PA.ARGUE, "01B"), OA_PARRY)
    assert keys[keys.index("SYS_D01_ATTACH") + 1] == "SYS_D01_CRACK"
    assert "SYS_D01_CRACK" not in run("B")[0][1]           # B R1: P1A lands, a psych card (no crack)


def test_psych_note_first_psych_card_only():
    s = state("B", 1)
    memo = LN.Memo()
    first = steps_of(s, PlayerAction(PA.ARGUE, "P1A"), OA_PARRY, memo)
    again = steps_of(s, PlayerAction(PA.ARGUE, "P1B"), OA_PARRY, memo)
    assert first[-1] == "SYS_D01_PSYCH_NOTE" and "SYS_D01_PSYCH_NOTE" not in again


def test_private_once_per_claim_after_the_round():
    s = state("C", 6)
    memo = LN.Memo()
    first = steps_of(s, PlayerAction(PA.ARGUE, "09A"), OA_PARRY, memo)
    again = steps_of(s, PlayerAction(PA.ARGUE, "09A"), OA_PARRY, memo)
    assert first[-1] == "SYS_D01_PRIVATE" and "SYS_D01_PRIVATE" not in again


def test_cover_wasted_when_set_and_not_triggered():
    s = state("A", 2)                                     # he sidesteps: nothing to cover
    wasted = steps_of(s, PlayerAction(PA.ARGUE, "04A", guard=True), OA_PARRY)
    assert wasted[-1] == "SYS_D01_COVER_WASTED"
    s = state("A", 1)                                     # a cut into his rebuttal: the cover triggers
    used = steps_of(s, PlayerAction(PA.INTERCEPT, "11A", guard=True), OA_REBUT)
    assert "SYS_D01_COVER" in used and "SYS_D01_COVER_WASTED" not in used
    assert "SYS_D01_COVER_WASTED" not in steps_of(state("A", 2), PlayerAction(PA.ARGUE, "04A"), OA_PARRY)
