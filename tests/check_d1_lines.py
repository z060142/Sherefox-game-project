# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Scripted D01 debates that reach the playback lines the four ref routes do not (v2 demo E3: review findings R2-R7,
ruling 7), replayed headless; what the d1debate screen shows is checked against the ref model (docs/flows.md §4.12,
tests/README.md).

Each scenario is a forced-opponent replay like tests/gen_d1_play.py's routes: a harness copy of the game pins his
move of every round through the engine's test hook (d1OppAct / d1OppCard) and loads the scenario's loadout on the dev
shortcut. The recording clicks the screen the M2 way. Per round, tests/check_d1_play.py check_lines compares the
system lines with the ref's events (every line ch §12.0 calls for, with its numbers; no other line under test) and the
斷 stamp with the ref's combo.

- S1 (route A's loadout): 截斷 vs his 反駁 (BOTH_REBUT, no FOOLED), a clash (CLASH), a 正論 拆台 on his fact F1
  (TOPPLE_MISS_FACT, −10), 打迷糊仗 vs 立論, a 拆台 whose claim does not break L1 (TOPPLE_MISS_WRONG, −5), 打迷糊仗 vs
  反駁 twice (FOOLED, then FOG_REPEAT and no FOOLED), a sophistry 截斷 on his fact F2 (DENY_FACT), a failed 截斷 that
  drops 破竹 with the combo kept (no 斷), a sophistry exposed with combo 1 (斷). The text language is switched to
  English in round 4 through the settings overlay (F1) before choosing: lines, the round counter, 破竹 and the public
  record's rounds follow. Every round after the first starts with no evidence chosen (R4).
- S2 (route A's loadout): a sophistry on the chain, a Break with one crack, his last card K1 taken: it hits, removes
  the cracked link and the debate goes on (LASTCARD_HIT with his recovery, LASTCARD_REMOVE), then a second zero
  (ZERO_WIN). The Break round's playback is clicked on the cut-in surface as well as the screen while the cut-in plays.
- S3 (route A's loadout): both sides stall to the round limit: round 20 ends as the ref says (a loss on credibility,
  UI_V2_TIME_UP).
- S4 (E4; route A's evidence with the talking board for E05): 破竹 held at 3 (SYS_D01_HACHIKU_KEEP after the round's
  last system line), 困獸 from round 5, his last card P05 hits in round 9 with the recovery voided (LASTCARD_NOHEAL then
  LASTCARD_CORNERED, the cracked link removed), then a second zero.
- S5 (E4; route A's loadout): a cut sealed by last round's sidestep (CUT_SEALED), a sophistry 拆台 on another issue's
  fact (−5, TOPPLE_MISS_WRONG), a sophistry 拆台 that knocks down a fact while he rebuts (DENY_FACT, OPP_REBUT_MISS).
- S6 (E5; route C's loadout): a private matter said with cover set that does not trigger (SYS_D01_PRIVATE {person},
  then SYS_D01_COVER_WASTED), the private matter's claim not announced twice.

E7 (v2 demo plan E7, docs/d01-string-coverage.md): the strings no test showed before.
- S7 (E05 and E06 left behind: he holds P06; A02, A04): 承接 03A -> 02A (a ↔ pair in the other order) and 02A -> 04B,
  his rebuttal blocking a sound claim (BLOCKED), 03A cutting L1 (CUT_D01_03A_L1), 03B (REACT_D01_03B) against his
  P06, 05B refuted with the work order (REFUTE_D01_05B, NOW_KNOWN with REFUTE_D01_05B_FACT), a 拆台 on P06 (its full
  title on the confirm row), 09A cutting L3 (CUT_D01_09A_L3), his slip U2 and 抓住他的話 on it (CARD_D01_U2_CATCH: the
  chain and the public record show CARD_D01_U2_SHORT, the record opened with R), the chain long enough without 破防
  (CHAIN_NOBREAK), a cut into his rebuttal under cover (COVER).
- S8 (route D, appraisal A04): the Reverse Break (REV_READY), then the last stand with 04B on L4: LASTSTAND_OK, her
  credibility back to 30% (42), the debate goes on.
- S9 (route A's loadout): 承接 05A -> 01C and 11A -> 11B, the chain without 破防, two contradictions (his catch and her
  hard sell, EXCL_D01_01D_05A / 05A_05B), his credibility to 0 without a Break (S07 L006, a zero endgame), his last
  card K1 cut: grade 4; the ending's S10 L008 (a win, 06B said, 07A / 07B not, truth < 70).
- S10 (route A's loadout): a keystone Break with no crack, the dying gasp, her endgame cut fails (DESPERATE_HIT).
- S11 (route A to its round 8): the dying gasp taken (DESPERATE_HIT).
- S12 (E05, E07 left: P05 kept as his last card, P07 held): his 強辯 with P07 (CARD_D01_P07_PUSH), 承接 08A -> 10A,
  a 拆台 that knocks L3 down (CARD_D01_L3_DOWN), the endgame cut on P05 (CARD_D01_P05_DOWN, the 截 seal).
- S13 (E05, E06 left: P05 kept, P06 held): his 強辯 with P06 (CARD_D01_P06_PUSH), P05 taken with no crack
  (BEAT_D01_LASTCARD_3).
- S14 (route D): the last stand with the red-crack 06A on L2: back to 30%, then −10 (32; rules §7.5, V-12).
Every round of these is checked like the others (check_lines, check_steps, the cut-ins); E7_REACHED lists the lines
each must keep reaching, HP_AT her credibility after the last stand, and a scenario that ends also has its S08 / S10
lines checked against ref epilogue.

E8 (v2 demo plan E8, design rulings): every round of every scenario is also checked at its choice
(tests/check_d1_play.py check_e8): the damage preview (ref preview.py), the red crack's cost, the one-line description of
the choice, the vague tell's line (with ★ UI_V2_TELL_LIKELY on the likelier action), the cover count, the public
record's crack count and the restated / void tags of the claim rows. E8_REACHED lists what the scenarios must keep
showing there (a preview, a cost, each description, a restated and a void row, a starred and an unstarred vague line, a
record with cracks), HOVER_PROBE the round where the pointer is moved over 截斷, 拆台, 打迷糊仗 and 援護 (each one's
description) and off again; the cut opener SHF_D01_CUT_OPEN_n plays in the playback (check_steps), and S14's red-crack
last stand shows LASTSTAND_OK at 42 before the contradiction lines and REDCRACK at 32 (RED_LAST).

E5 (v2 demo plan E5): every scenario's whole playback and the tell's lines are also compared step by step with ref
lines.round_steps / tell_lines on the AI's tells of the debate seed (tests/check_d1_play.py check_steps). The lines
E5 adds that routes A-D do not reach show here: his tell lines in turn (S3: PUSH_1 / PUSH_2, REBUT_1 / REBUT_2), a
spent hint falling through (S2 R7, S4 R10: FACT spent, his action's hint instead), a half sentence on a clear tell
(S4 R7: his line and SLIP), the P05 beat with HINT_LAST (S4 R9), SYS_D01_CRACK (S2 R1, S4 R4), SYS_D01_PSYCH_NOTE
(S4 R2), STATE_D01_ART_CORNERED (S4 R5), SYS_D01_PRIVATE and SYS_D01_COVER_WASTED (S6). E5_REACHED lists them and
the check fails when the scenario's ref playback stops reaching one (the AI's tells follow the seed).

Usage (from the project root):
    uv run tests/check_d1_lines.py [--shots DIR]    --shots also writes a failed-拆台 line, a LASTCARD_HIT line,
                                                    Arthur's first 破竹 line and a private matter (zh-TW, en) to DIR
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS))
import check_d1_m3 as cm  # noqa: E402
import check_d1_play as cd  # noqa: E402
import check_playthrough as cp  # noqa: E402
import gen_d1_play as gd  # noqa: E402
import gen_playthrough as gp  # noqa: E402
from sherefox_ref.v2 import routes as RT  # noqa: E402
from sherefox_ref.v2.model import PA, PlayerAction  # noqa: E402
from tempwatch import TempWatch  # noqa: E402
from xt_cli import compile_game  # noqa: E402

S = cd.S
A, R, P = RT.AT, RT.RE, RT.PR


def dis(claim: str, target: str) -> PlayerAction:
    return PlayerAction(PA.DISMANTLE, claim, target)


KEY_R = 21                     # XtKey.R (the public record)


def route(name: str, rounds: list) -> RT.Route:
    return RT.Route(name, RT.ROUTES["A"].loadout, tuple((pa, oa, None) for pa, oa in rounds))


op = RT.opp
SCENARIOS = {
    "S1": route("S1", [(RT.cut("11A"), op(R)), (RT.argue("04A"), op(A, "F1")), (dis("06A", "F1"), op(P)),
                       (RT.stall(), op(A, "L1")), (dis("04B", "L1"), op(P)), (RT.stall(), op(R)), (RT.stall(), op(R)),
                       (RT.cut("06B"), op(A, "F2")), (RT.cut("11B"), op(A, "L3")), (RT.argue("01B"), op(R))]),
    "S2": route("S2", [(RT.argue("01B"), op(P)), (RT.argue("04A"), op(P)), (RT.argue("08A"), op(P)),
                       (RT.cut("11A"), op(A, "L1")), (RT.argue("10A"), op(P)), (RT.accept(), op(RT.LAST, "K1")),
                       (RT.argue("01A"), op(P)), (RT.argue("06A"), op(P)), (RT.argue("11B"), op(P))]),
    "S3": route("S3", [(RT.stall(), op(P))] * 20),
    # E4 (design 3689f6d): 破竹 held (HACHIKU_KEEP, rounds 4-8); 困獸 (P over from round 5) voids his last card's
    # recovery and the debate goes on (LASTCARD_NOHEAL then LASTCARD_CORNERED, round 9); a sidestep's voided heal
    # says nothing (rounds 6, 8)
    "S4": RT.Route("S4", RT.Loadout(("E01", "E02", "E04", "E06", "E07", "E08", "E10", "E11", "P1"), ("A01", "A04"),
                                    ("PN1", "PN2", "PN3", "PN4"), warmup="pass_clean"),
                   tuple((pa, oa, None) for pa, oa in [
                       (RT.cut("11A"), op(A, "L1")), (RT.argue("P1B"), op(P)), (RT.cut("01A"), op(A, "L2")),
                       (RT.argue("01B"), op(P)), (RT.cut("07A"), op(A, "L4")), (RT.argue("04A"), op(P)),
                       (RT.cut("08A"), op(A, "L3")), (RT.argue("10A"), op(P)), (RT.accept(), op(RT.LAST, "P05")),
                       (RT.argue("06A"), op(P))])),
    # E4: a cut sealed by last round's sidestep (CUT_SEALED), a sophistry dismantle on another issue's fact (−5,
    # TOPPLE_MISS_WRONG), a sophistry dismantle that knocks down a fact while he rebuts (DENY_FACT, OPP_REBUT_MISS)
    "S5": route("S5", [(RT.cut("11A"), op(P)), (RT.cut("01A"), op(A, "L2")), (RT.argue("04A"), op(A, "F1")),
                       (dis("06B", "F1"), op(P)), (dis("06C", "F1"), op(R))]),
    # E5: a private matter said (09A) under a cover that does not trigger (he sidesteps), then a quiet round
    "S6": RT.Route("S6", RT.ROUTES["C"].loadout, tuple((pa, oa, None) for pa, oa in [
        (RT.argue("09A", guard=True), op(P)), (RT.argue("10A"), op(P)), (RT.stall(), op(A, "L1"))])),
    # E7: the strings no scenario reached before (see the module doc)
    "S7": RT.Route("S7", RT.Loadout(("E01", "E02", "E03", "E04", "E05", "E09", "E10", "E11", "E12"), ("A02", "A04"),
                                    ("PN1", "PN2", "PN3", "PN4"), warmup="pass"),
                   tuple((pa, oa, None) for pa, oa in [
                       (RT.argue("03A"), op(P)), (RT.argue("02A"), op(P)), (RT.argue("04B"), op(P)),
                       (RT.argue("12A"), op(R)), (RT.cut("03A"), op(A, "L1")), (RT.argue("03B"), op(A, "P06")),
                       (RT.argue("05B"), op(R)), (dis("12A", "P06"), op(P)), (RT.cut("09A"), op(A, "L3")),
                       (RT.argue("11A"), op(A, "U2")), (RT.argue("CATCH"), op(RT.FO, "L4")),
                       (RT.cut("11B", guard=True), op(R))])),
    "S8": RT.Route("S8", RT.Loadout(RT.ROUTES["D"].loadout.carried, ("A02", "A04"), (), warmup="pass"),
                   tuple((pa, oa, None) for pa, oa, _ in RT.ROUTES["D"].rounds[:7]) + tuple(
                       (pa, oa, None) for pa, oa in [(RT.last_stand("04B", "L4"), op(RT.NONE)),
                                                     (RT.argue("12A"), op(P)), (RT.argue("03A"), op(A, "L3"))])),
    "S9": route("S9", [(RT.cut("11A"), op(A, "L1")), (RT.argue("05A"), op(P)), (RT.argue("01C"), op(P)),
                       (RT.argue("11A"), op(P)), (RT.argue("11B"), op(P)), (RT.argue("06B"), op(P)),
                       (RT.argue("01D"), op(P)), (RT.argue("05B"), op(P)), (RT.argue("04A"), op(P)),
                       (RT.end_cut("04B"), op(RT.LAST, "K1"))]),
    "S10": route("S10", [(RT.cut("11A"), op(A, "L1")), (RT.argue("05A"), op(P)), (RT.argue("01C"), op(P)),
                         (RT.argue("11A"), op(P)), (RT.argue("11B"), op(P)), (RT.stall(), op(R)),
                         (RT.cut("01A"), op(A, "L2")), (RT.end_cut("05A"), op(RT.LAST, "K1"))]),
    "S11": route("S11", [(pa, oa) for pa, oa, _ in RT.ROUTES["A"].rounds[:8]] + [(RT.accept(), op(RT.LAST, "K1"))]),
    "S12": RT.Route("S12", RT.Loadout(("E01", "E02", "E03", "E04", "E06", "E08", "E09", "E10", "E11"), ("A01", "A04"),
                                      ("PN1", "PN2", "PN3", "PN4"), warmup="pass"),
                    tuple((pa, oa, None) for pa, oa in [
                        (RT.cut("11A"), op(A, "L1")), (RT.argue("08A"), op(RT.FO, "P07")), (RT.argue("10A"), op(A, "L3")),
                        (dis("09A", "L3"), op(P)), (RT.stall(), op(R)), (RT.cut("01A"), op(A, "L2")),
                        (RT.end_cut("01C"), op(RT.LAST, "P05"))])),
    "S13": RT.Route("S13", RT.Loadout(("E01", "E02", "E03", "E04", "E07", "E08", "E09", "E10", "E11"), ("A01", "A04"),
                                      ("PN1", "PN2", "PN3", "PN4"), warmup="pass"),
                    tuple((pa, oa, None) for pa, oa in [
                        (RT.cut("11A"), op(A, "L1")), (RT.argue("08A"), op(RT.FO, "P06")), (RT.stall(), op(R)),
                        (RT.cut("01A"), op(A, "L2")), (RT.accept(), op(RT.LAST, "P05")), (RT.argue("10A"), op(P))])),
    "S14": RT.Route("S14", RT.ROUTES["D"].loadout, tuple((pa, oa, None) for pa, oa, _ in RT.ROUTES["D"].rounds[:7]) + tuple(
        (pa, oa, None) for pa, oa in [(RT.last_stand("06A", "L2"), op(RT.NONE)), (RT.argue("12A"), op(P))])),
}
# E7: (scenario, round) -> lines its ref playback must reach (the strings this scenario is here to show)
E7_REACHED = {
    ("S7", 2): ["LINK_D01_02A_03A"], ("S7", 3): ["LINK_D01_02A_04B"], ("S7", 4): ["SYS_D01_BLOCKED", "REACT_D01_BLOCK"],
    ("S7", 5): ["CUT_D01_03A_L1"], ("S7", 6): ["CLM_D01_03B_LINE", "REACT_D01_03B", "CARD_D01_P06_STATE"],
    ("S7", 7): ["REFUTE_D01_05B", "SYS_D01_NOW_KNOWN"], ("S7", 9): ["CUT_D01_09A_L3"],
    ("S7", 11): ["CARD_D01_U2_CATCH", "SYS_D01_CHAIN_NOBREAK"], ("S7", 12): ["SYS_D01_COVER"],
    ("S8", 7): ["SYS_D01_REV_READY"], ("S8", 8): ["SYS_D01_LASTSTAND_OK"],
    ("S9", 3): ["LINK_D01_05A_01C"], ("S9", 5): ["LINK_D01_11A_11B", "SYS_D01_CHAIN_NOBREAK"],
    ("S9", 7): ["EXCL_D01_01D_05A_CATCH", "EXCL_D01_01D_05A_SELL"], ("S9", 8): ["EXCL_D01_05A_05B_CATCH"],
    ("S9", 9): ["SCR_D01_S07_L006"],
    ("S10", 8): ["SYS_D01_DESPERATE_HIT"], ("S11", 9): ["SYS_D01_DESPERATE_HIT"],
    ("S12", 2): ["CARD_D01_P07_PUSH"], ("S12", 3): ["LINK_D01_10A_08A"], ("S12", 4): ["CARD_D01_L3_DOWN"],
    ("S12", 7): ["CARD_D01_P05_DOWN"], ("S13", 2): ["CARD_D01_P06_PUSH"], ("S13", 5): ["BEAT_D01_LASTCARD_3"],
    ("S14", 8): ["SYS_D01_LASTSTAND_OK"],
}
# E7: her credibility on the screen when that round is shown (rules §7.5: the last stand puts her back to 30% of 140;
# a red-crack claim then costs 10, V-12)
HP_AT = {("S8", 9): 42.0, ("S14", 9): 32.0}
# (scenario, round): the public record opened with R and closed again before choosing (E7: S7's catch node; E8: S9's
# record header with two cracks)
RECORD_PEEKS = {("S7", 12), ("S9", 9)}
# E8: (scenario, round) -> what the choice must show there (check_e8 checks every round; these say the scenarios still
# reach each case): "desc:<key>", "preview", "crack", "restate:<claim>", "void:<claim>", "star", "nostar", "cracks"
E8_REACHED = {("S3", 2): ["desc:UI_V2_ACT_STALL_REPEAT"], ("S9", 2): ["preview", "star"], ("S9", 7): ["crack"],
              ("S9", 6): ["desc:UI_V2_CLAIM_SOPH_DESC"], ("S9", 8): ["restate:05A", "crack", "star", "preview"],
              ("S9", 9): ["cracks"], ("S7", 11): ["desc:UI_V2_SEIZE_DESC"], ("S7", 8): ["desc:UI_V2_REBUT_TOPPLE_DESC"],
              ("S7", 5): ["desc:UI_V2_REBUT_CUT_DESC", "nostar"], ("S6", 1): ["desc:UI_V2_SUPPORT_DESC"],
              ("S6", 3): ["desc:UI_V2_ACT_STALL_DESC"], ("S14", 8): ["void:06B", "crack"]}
# E8: the round where the pointer is moved over the actions and cover before choosing, then off them (onto his chain's
# empty box): (x, y, hover value) in order
HOVER_PROBE = ("S1", 2)
HOVER_AT = [(gd.ACT_XY[2], "act2"), (gd.ACT_XY[3], "act3"), (gd.ACT_XY[4], "act4"), (gd.GUARD_XY, "guard"),
            ((700, 120), "")]
RED_LAST = ("S14", 8)          # E8: the red-crack last stand, two steps (42, then the red crack's −10 to 32)
# E5: (scenario, round) -> lines the ref playback must reach there (tell lines and steps; see the module doc)
E5_REACHED = {("S3", 6): ["TELL_D01_REBUT_1"], ("S3", 7): ["TELL_D01_REBUT_2"], ("S3", 9): ["TELL_D01_PUSH_1"],
              ("S3", 11): ["TELL_D01_PUSH_2"], ("S2", 7): ["TELL_D01_HINT_PUSH"], ("S4", 10): ["TELL_D01_HINT_ASSERT"],
              ("S4", 7): ["TELL_D01_PUSH_1", "TELL_D01_HINT_SLIP"], ("S4", 9): ["BEAT_D01_LASTCARD_1", "TELL_D01_HINT_LAST"],
              ("S2", 1): ["SYS_D01_CRACK"], ("S4", 4): ["SYS_D01_CRACK"], ("S4", 2): ["SYS_D01_PSYCH_NOTE"],
              ("S4", 5): ["STATE_D01_ART_CORNERED"], ("S6", 1): ["SYS_D01_PRIVATE", "SYS_D01_COVER_WASTED"]}
LANG_SWITCH = ("S1", 4)        # (scenario, round): English chosen in the settings overlay before that round's choice
CUTIN_CLICKS = ("S2", 5)       # (scenario, round): the playback is clicked on ui#cutin and ui#d1debate
NO_SKIP = {("S1", 3), ("S2", 6), ("S6", 1),   # rounds played back without clicks (the failed 拆台, his last card, E5:
                                              # Arthur's first 破竹 line and the private matter)
           # E7: the rounds of the review screenshots (--shots: each new line at its own pace)
           ("S7", 2), ("S7", 4), ("S7", 5), ("S7", 7), ("S7", 11), ("S7", 12), ("S8", 7), ("S8", 8), ("S9", 7),
           ("S9", 9), ("S10", 8), ("S12", 2), ("S12", 7), ("S13", 5), ("S14", 8)}


def record(name: str, rt: RT.Route) -> tuple[int, dict]:
    rec = gd.Rec(f"tests/d1play_harness{name}")
    rec.click("title", gd.TITLE_V2, 40)
    rec.t += 40
    gd.opening(rec)
    for n, (s, pa, _) in enumerate(gd.forced(rt), start=1):
        if (name, n) == LANG_SWITCH:
            rec.lines.append(cp_json({"t": rec.t + 10, "u": gp.key("d1debate", gp.KEY_F1)}))
            rec.t += 10 + gp.SETTLE
            rec.click("settings", gp.SET_LANG[1], 0)
            rec.t += gp.GAP
            rec.lines.append(cp_json({"t": rec.t, "u": gp.key("settings", gp.KEY_ESC)}))
            rec.t += gp.SETTLE
        rec.marks[f"shown{n}"] = rec.t + 6
        if (name, n) == HOVER_PROBE:   # E8: the pointer over each action and cover, then off them
            for k, (xy, _) in enumerate(HOVER_AT):
                rec.hover("d1debate", xy, 20 if k == 0 else 12)
                rec.marks[f"hover{k}"] = rec.t + 4
        if (name, n) in RECORD_PEEKS:  # E7: the public record with the catch node (R opens it, R closes it)
            rec.lines.append(cp_json({"t": rec.t + 40, "u": gp.key("d1debate", KEY_R)}))
            rec.marks["record_open"] = rec.t + 70
            rec.t += 90
            rec.lines.append(cp_json({"t": rec.t, "u": gp.key("d1debate", KEY_R)}))
            rec.t += gp.SETTLE
        act = gd.PA_ACT[pa.kind]
        rec.click("d1debate", gd.ACT_XY[act], 12)
        if pa.claim is not None:
            pk = gd.picker(s)
            claim = f"CATCH:{s.catch_card}" if pa.claim == "CATCH" else pa.claim
            ev = "CATCH" if claim.startswith("CATCH") else s.ch.claims[claim].evidence
            i = [e for e, _ in pk].index(ev)
            rec.click("d1debate", gd.ev_xy(i))
            rec.click("d1debate", gd.claim_xy(pk[i][1].index(claim)))
        chain = [nd.card for nd in s.opp_chain]
        if pa.target in chain:
            rec.click("d1debate", gd.chain_xy(chain.index(pa.target)))
        if pa.guard:                   # E5 (S6): cover set before the lock
            rec.click("d1debate", gd.GUARD_XY)
        rec.marks[f"chosen{n}"] = rec.t + 4
        rec.click("d1debate", gd.LOCK_XY)
        rec.marks[f"lock{n}"] = rec.t
        if (name, n) in NO_SKIP:       # the playback at its own pace: the review screenshots see whole lines
            rec.t += gd.NO_SKIP_WAIT
        for k in range(0 if (name, n) in NO_SKIP else gd.SKIPS):
            ui = "cutin" if (name, n) == CUTIN_CLICKS and k % 2 == 0 else "d1debate"
            rec.click(ui, gd.SKIP_XY, gd.SKIP_GAP)
            if ui == "cutin":
                rec.marks.setdefault("cutin_clicks", []).append(rec.t)
        rec.t += gd.ROUND_TAIL
    rec.marks["end"] = rec.t
    gd.outro(rec, gd.outcome_of(gd.forced(rt)))
    if gd.outcome_of(gd.forced(rt)) is not None:
        gd.epilogue(rec, gd.final_state(gd.forced(rt)))   # 4.4: S08, the result screen (`over`), ..., back to title
    else:
        rec.marks["over"] = rec.t
    end = rec.write(f"d1_lines_{name}", 60)
    return end, rec.marks


def cp_json(o: dict) -> str:
    import json
    return json.dumps(o)


def check(name: str, rt: RT.Route, end: int, marks: dict, fails: list):
    rounds = gd.forced(rt)
    switch = LANG_SWITCH[1] if LANG_SWITCH[0] == name else None

    def lang_of(n: int) -> str:
        return "en" if switch and n >= switch else "zh-TW"
    events, err = cd.run(f"d1_lines_{name}", f"tests/d1play_harness{name}", end, "zh-TW")
    tr = cp.Trace(events)
    at = cm.At(tr, events)
    bad = cd.check_lines(tr, rounds, marks, lang_of, marks["end"])
    # E5: the whole playback and the tell's lines against ref, and the E5 lines this scenario is here to reach
    seed = gd.CV.ui_debate_seed(1)
    bad += cd.check_steps(tr, rounds, marks, lang_of, seed, marks["end"])
    bad += reached(name, rounds, seed)
    bad += cd.check_e8(tr, rounds, marks, lang_of, seed)        # E8: preview, cost, description, tags, counts
    bad += e8_reached(name, rounds, seed)
    if name == HOVER_PROBE[0]:
        n = HOVER_PROBE[1]
        s0 = rounds[n - 1][0]
        for k, (_, hv) in enumerate(HOVER_AT):
            want = cd.e8_desc(lang_of(n), s0, 0, "", False, hv)
            got = at.get(marks[f"hover{k}"], "d1debate.desc_text")
            if got != want or (hv and not want):
                bad.append(f"R{n}: pointer on {hv or 'nothing'}: desc_text {got!r} (want {want!r})")
    if name == RED_LAST[0]:            # E8: 42 first, then the contradiction's lines and the red crack at 32
        n = RED_LAST[1]
        steps = [g for _, g in cd.ui_steps(tr, marks[f"lock{n}"], marks.get(f"lock{n + 1}", marks["end"]))]
        sysl = [x[2] for x in steps if x[2]]
        ok = cd.pattern("zh-TW", "SYS_D01_LASTSTAND_OK")
        rc = cd.pattern("zh-TW", "SYS_D01_REDCRACK")
        i = next((k for k, x in enumerate(sysl) if ok.match(x)), None)
        j = next((k for k, x in enumerate(sysl) if rc.match(x)), None)
        if i is None or j is None or j < i or "42" not in sysl[i] or "32" not in sysl[j]:
            bad.append(f"R{n}: the red-crack last stand: {sysl}")
    # the outcome panel and round count equal the ref's
    grade, nrounds, outcome = cd.expected(rounds)
    L = S[lang_of(len(rounds))]
    t = marks["over"]
    panel = () if outcome is None else (
        ("d1result.grade_text", L[f"UI_V2_GRADE_{grade}"]),
        ("d1result.rounds_text", L["UI_V2_RESULT_ROUNDS"].replace("{n}", str(nrounds))),
        ("d1result.win", 1.0 if outcome == "win" else 0.0))
    for port, want in panel:
        if at.get(t, port) != want:
            bad.append(f"outcome {port}={at.get(t, port)!r} (want {want!r})")
    # R4: a new round starts with no evidence chosen; R7: 破竹 and the record's rounds are string keys, in the
    # language of the moment
    for n, (s, pa, _) in enumerate(rounds, start=1):
        lg = lang_of(n)
        tm = marks[f"shown{n}"]
        evs = at.get(tm, "d1debate.ev_list") or []
        if n > 1 and any(e["sel"] for e in evs):
            bad.append(f"R{n}: evidence still chosen when the round starts: {[e['id'] for e in evs if e['sel']]}")
        want_rt = S[lg]["UI_V2_ROUND"].replace("{n}", str(n)).replace("{max}", "20")
        if at.get(tm, "d1debate.round_text") != want_rt:
            bad.append(f"R{n}: round_text {at.get(tm, 'd1debate.round_text')!r} (want {want_rt!r})")
        if s.hachiku and at.get(tm, "d1debate.hachiku_text") != S[lg]["UI_STATE_HACHIKU"].replace("{n}", str(s.hachiku)):
            bad.append(f"R{n}: hachiku_text {at.get(tm, 'd1debate.hachiku_text')!r}")
        rows = [r["n"] for r in (at.get(tm, "d1debate.record") or [])]
        want_rows = [S[lg]["UI_DEB_ROUND"].replace("{n}", str(e.round)) for e in s.record]
        if rows != want_rows:
            bad.append(f"R{n}: record rounds {rows} (want {want_rows})")
    if name == CUTIN_CLICKS[0]:
        n = CUTIN_CLICKS[1]
        bigs = [t for t, p, v, c in tr.ticks if marks[f"lock{n}"] <= t < marks[f"lock{n + 1}"] and "cutin.big_seq" in c]
        during = [c for c in marks.get("cutin_clicks", []) if any(b <= c < b + 96 for b in bigs)]
        if not bigs or not during:
            bad.append(f"R{n}: no click during a cut-in (cut-ins at {bigs})")
    if name == "S6":                   # E5: SYS_D01_PRIVATE names the person whose regard it costs
        lines, _ = cd.shown(tr, marks["lock1"], marks["lock2"])
        want = cd.render("zh-TW", "SYS_D01_PRIVATE", {"person": S["zh-TW"]["SPK_MRS_HYDE"]})
        if want not in lines:
            bad.append(f"R1: {want!r} not shown ({lines})")
    for (sc, n), hp in HP_AT.items():  # E7: the last stand's 30%
        if sc == name and abs((at.get(marks[f"shown{n}"], "d1debate.hp_me") or 0) - hp) > 0.01:
            bad.append(f"R{n}: hp_me {at.get(marks[f'shown{n}'], 'd1debate.hp_me')!r} (want {hp})")
    if name == "S7":                   # E7: 抓住他的話 shows the caught U card's short label (design ruling)
        n = 12
        u2 = S["zh-TW"]["CARD_D01_U2_SHORT"]
        chain = [x["label"] for x in at.get(marks[f"shown{n}"], "d1debate.pchain") or []]
        recl = [x["label"] for x in at.get(marks["record_open"], "d1debate.record") or []]
        if u2 not in chain or u2 not in recl or S["zh-TW"]["UI_V2_SEIZE"] in chain + recl:
            bad.append(f"R{n}: the catch node: chain {chain}, record {recl} (want {u2!r})")
    if outcome is not None:            # E7: the ending's S08 and S10 lines (ref epilogue)
        from sherefox_ref.v2.epilogue import epilogue
        e = epilogue(gd.final_state(rounds))
        for lid in e.s08 + e.s10:
            mk = marks.get(f"s08_{lid}") or marks.get(f"s10_{lid}")
            if mk is None or at.get(mk, "vn.line") != S["zh-TW"][lid]:
                bad.append(f"ending: {lid} not on the vn ({at.get(mk, 'vn.line') if mk else 'no mark'!r})")
    if name == "S3":
        lines, _ = cd.shown(tr, marks[f"lock{len(rounds)}"], marks["end"])
        if S["zh-TW"]["UI_V2_TIME_UP"] not in lines:
            bad.append(f"round {len(rounds)}: UI_V2_TIME_UP not shown ({lines})")
    noise = [ln for ln in err.split("\n") if ln.strip() and not ln.startswith("render: off")]
    if noise:
        bad.append("stderr: " + " | ".join(noise[:5]))
    if bad:
        fails.append(name)
        print(f"FAIL {name}: " + "\n  ".join(bad[:25]))
    else:
        print(f"PASS {name}: {len(rounds)} rounds, grade {grade}, {outcome}")
    return tr


def e8_reached(name: str, rounds: list, seed: int) -> list[str]:
    """E8_REACHED: the scenario's ref states and choices still reach each listed case."""
    from sherefox_ref.v2 import known as K
    bad = []
    tells = cd.tells_for(rounds, seed)
    for n, ((s, pa, _), tl) in enumerate(zip(rounds, tells), start=1):
        act = gd.PA_ACT[pa.kind]
        c = pa.claim or ""
        for want in E8_REACHED.get((name, n), []):
            kind, _, arg = want.partition(":")
            ok = {"desc": lambda: cd.e8_desc_key(s, act, c, bool(pa.guard)) == arg,
                  "preview": lambda: cd.e8_preview("zh-TW", s, act, c) != "",
                  "crack": lambda: cd.e8_crack("zh-TW", s, act, c) != "",
                  "restate": lambda: K.restate(s, arg) and s.ch.claims[arg].evidence == s.ch.claims[c].evidence,
                  "void": lambda: arg in K.void_rows(s) and s.ch.claims[arg].evidence == s.ch.claims[c].evidence,
                  "star": lambda: S["zh-TW"]["UI_V2_TELL_LIKELY"] in cd.e8_tell("zh-TW", s, tl),
                  "nostar": lambda: cd.e8_tell("zh-TW", s, tl) != "" and
                  S["zh-TW"]["UI_V2_TELL_LIKELY"] not in cd.e8_tell("zh-TW", s, tl),
                  "cracks": lambda: s.cracks >= 2}[kind]()
            if not ok:
                bad.append(f"R{n}: the scenario no longer reaches E8 case {want}")
    return bad


def reached(name: str, rounds: list, seed: int) -> list[str]:
    """E5_REACHED: the ref playback (tell lines and steps) of the listed rounds holds the listed lines."""
    from sherefox_ref.v2 import lines as LN
    from sherefox_ref.v2.resolve import resolve_round
    memo, bad = LN.Memo(), []
    for n, ((s, pa, oa), tl) in enumerate(zip(rounds, cd.tells_for(rounds, seed)), start=1):
        s2, ev = resolve_round(s, pa, oa)
        keys = [k for _, k in LN.tell_lines(s, tl, memo)]
        keys += [k for st in LN.round_steps(s, pa, oa, ev, s2, memo) for k in (st.line, st.sys) if k]
        missing = [k for k in E5_REACHED.get((name, n), []) + E7_REACHED.get((name, n), []) if k not in keys]
        if missing:
            bad.append(f"R{n}: the scenario no longer reaches {missing}")
    return bad


# review screenshots (--shots DIR): a failed 拆台 on a fact (S1), his last card recovering (S2), E5: Arthur's first 破竹
# line and the private matter (S6), zh-TW and en; (shot name, line key: a system line, or a spoken one)
SHOTS = {"S2": [("lastcard_hit", "SYS_D01_LASTCARD_HIT")],
         "S6": [("hachiku_state_line", "STATE_D01_ART_HACHIKU"), ("private_matter", "SYS_D01_PRIVATE")],
         # E7: the lines shown for the first time, the catch node on the chain (round shown) and in the record
         "S1": [("topple_miss_fact", "SYS_D01_TOPPLE_MISS_FACT"),
                # E8: the one-line description with the pointer on each action and on cover
                ("desc_cut", "@hover0"), ("desc_topple", "@hover1"), ("desc_stall", "@hover2"),
                ("desc_cover", "@hover3")],
         "S3": [("desc_stall_repeat", "@chosen2")],
         "S7": [("cut_open", "SHF_D01_CUT_OPEN_1"), ("desc_seize", "@chosen11"), ("blocked", "SYS_D01_BLOCKED"), ("link_03a_02a", "LINK_D01_02A_03A"), ("cut_03a_l1", "CUT_D01_03A_L1"),
                ("refute_05b", "SYS_D01_NOW_KNOWN"), ("u2_catch_line", "CARD_D01_U2_CATCH"),
                ("chain_nobreak", "SYS_D01_CHAIN_NOBREAK"), ("catch_on_chain", "@shown12"),
                ("catch_in_record", "@record_open"), ("cover", "SYS_D01_COVER")],
         "S8": [("rev_ready", "SYS_D01_REV_READY"), ("laststand_ok", "SYS_D01_LASTSTAND_OK"), ("after_laststand", "@shown9")],
         "S9": [("preview_star", "@chosen2"), ("desc_soph", "@chosen6"), ("crack_cost", "@chosen7"),
                ("restate_row", "@chosen8"), ("record_cracks", "@record_open"), ("endgame_head", "@chosen10"),
                ("excl_catch", "EXCL_D01_01D_05A_CATCH"), ("excl_sell", "EXCL_D01_01D_05A_SELL"),
                ("zero_endgame", "SCR_D01_S07_L006"), ("s10_l008", "@s10_SCR_D01_S10_L008")],
         "S10": [("desperate_hit", "SYS_D01_DESPERATE_HIT")],
         "S12": [("p07_push", "CARD_D01_P07_PUSH"), ("endgame_cut_stamp", "CARD_D01_P05_DOWN")],
         "S13": [("lastcard_3", "BEAT_D01_LASTCARD_3")],
         "S14": [("void_row", "@chosen8"), ("laststand_redcrack", "SYS_D01_LASTSTAND_OK"),
                 ("redcrack_after_laststand", "SYS_D01_REDCRACK"), ("after_laststand_redcrack", "@shown9")]}


def shots(out: Path, name: str, tr, end: int, marks: dict) -> None:
    import subprocess
    from xt_cli import EXE, XTFRAME
    named = {}
    for shot, key in SHOTS[name]:
        if key.startswith("@"):        # E7: a mark of the recording (a round shown, the record open, a vn line)
            # E8: a choice (`chosen`, before the lock) or a pointer position (`hover`) is shot on its mark
            named[shot] = marks[key[1:]] + (0 if key.startswith(("@chosen", "@hover")) else 10)
            continue
        pt = cd.pattern("zh-TW", key)
        port = "d1debate.sys_line" if key.startswith(("SYS_", "SCR_D01_S07_")) else "d1debate.speech"
        named[shot] = next(t for t, p, v, c in tr.ticks if "d1debate.line_seq" in c and port in p
                           and pt.match(p[port])) + 40
    out.mkdir(parents=True, exist_ok=True)
    for lang in ("zh-TW", "en"):
        tmp = Path(tempfile.mkdtemp(prefix="d1linesshots-"))
        try:
            at = ",".join(str(t) for t in sorted(set(named.values())))
            p = subprocess.run([str(EXE), "shot", "--game", f"tests/d1play_harness{name}", "--replay",
                                str(TESTS / f"d1_lines_{name}.atrec"), "--at", at, "--out", str(tmp),
                                "--lang", lang], capture_output=True, cwd=ROOT,
                               env=dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME))
            if p.returncode != 0:
                raise SystemExit(f"shot failed: {p.stderr.decode('utf-8', 'replace')}")
            for shot, t0 in named.items():
                shutil.copyfile(tmp / f"shot-{t0:06d}.png", out / f"{shot}_{lang}.png")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    compile_game()
    tw = TempWatch().__enter__()   # tests/tempwatch.py: only what this run creates counts as a leak
    fails: list[str] = []
    try:
        for name, rt in SCENARIOS.items():
            gd.build_harness(name, rt)
            end, marks = record(name, rt)
            tr = check(name, rt, end, marks, fails)
            if "--shots" in sys.argv and name in SHOTS:
                shots(Path(sys.argv[sys.argv.index("--shots") + 1]), name, tr, end, marks)
    finally:
        for name in SCENARIOS:
            shutil.rmtree(gd.harness_dir(name), ignore_errors=True)
            (TESTS / f"d1_lines_{name}.atrec").unlink(missing_ok=True)
    tw.__exit__(None, None, None)
    left = tw.leaks
    if left:
        fails.append("temp")
        print("FAIL temp: left behind: " + ", ".join(left))
    print("ok" if not fails else f"FAILED: {', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
