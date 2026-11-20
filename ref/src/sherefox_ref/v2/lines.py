"""What the D01 debate screen says, line by line (v2 demo 4.3; ch §2 S07, §9, §11, §12.0-§12.4).

This is the oracle of the debate UI's playback (tools/gen_debui_v2.py, docs/flows.md §4.12): a pure function of the
round's records (the engine's d1Events, which equal the ref events, debate-engine-v2 §2.3) and of the state, so the
UI and the tests read the same selection rule.

* ``tell_lines``: the lines shown with the tell, before the player chooses (v2 demo E5, design 6a94528 / 93d037b; ch
  §11 「亞瑟提示的時機」「其他台詞的時機」): on a clear tell his own tell line ``TELL_D01_<action>_n`` (the lines of
  that action in turn, per debate; never on a vague tell: it would tell his real action), then at most one hint of
  Arthur's, the first of this list whose condition holds and whose uses are not spent (a spent one falls through to
  the next): 1 ``HINT_LAST`` his last card's tell, the dying gasp included (every time); 2 ``HINT_SLIP`` a half
  sentence (every time); 3 ``HINT_KEY`` the tell box holds the keystone (once per debate); 4 ``HINT_NOCUT`` the tell
  box holds a lie and no claim in this round's picker that shows as 正論 is in its breakable list (sophistry does not
  count; once); 5 ``HINT_FACT`` the tell box holds a favourable fact (once); 6 the action hint
  ``HINT_ASSERT``/``PUSH``/``REBUT``/``STALL``, on a clear tell only (once per action). 3-5 read the tell box's card,
  clear or vague. In the endgame the P05 beat ``BEAT_D01_LASTCARD_1`` comes before Arthur's hint and the dying gasp's
  S07 L010 (his) after it (ch §12.1 R9, §12.3 R5). None in the §7.5 round.
* ``round_steps``: the playback of one round. Every record gives at most one main step (his or her spoken line and
  a system line shown together), with extra steps before (``pre``) or after (``post``) it for the S07 lines, the
  ``BEAT_D01_*`` interludes and the §9 / §11 lines that have a speaker of their own. After the last record, one tail
  step (破竹維持). Empty steps are dropped. E5 (plan E5's timing list): 破竹 up -> SHF_HACHIKU_n, the debate's first
  time ART_HACHIKU after it; his first 破防 of the debate -> SHF_SHAKEN (the broken record); he enters 困獸 ->
  ART_CORNERED; a sophistry link lands (not a psych card) -> SYS_D01_CRACK after the link's other lines; after the
  last record the tail steps in order: 破竹維持, the debate's first psych card SYS_D01_PSYCH_NOTE, a private matter
  said SYS_D01_PRIVATE (once per claim), cover set and not triggered SYS_D01_COVER_WASTED (a normal round the debate
  goes on after). The chapter shows the psych note (B R1) and the private matter (C R6) after the clash, which the tail
  agrees with; the order among the tail lines is not shown and follows "new after old".
* ``OPENING`` / ``outro``: S07 around the debate (L001-L003 before it as dialogue, L004 when it starts, L012-L015 after
  a win, L017-L019 after a loss: L016 is the loss line inside the debate).

Speakers are string keys (``SPK_*``); a staging beat has no name plate (``""``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import known as K
from .model import CATCH, OA, PA, State

SH, CE, AR = "SPK_SHEREFOX", "SPK_D01_CEDRIC", "SPK_ARTHUR"
MRS, BRI, MAR, IRE, INS = "SPK_MRS_HYDE", "SPK_BRIGGS", "SPK_MARTHA", "SPK_IRENE", "SPK_INSPECTOR_BASKERVILLE"
STAGE = ""

PRE_LINES = ("SCR_D01_S07_L001", "SCR_D01_S07_L002", "SCR_D01_S07_L003")     # dialogue before the debate
OPENING_SYS = "SCR_D01_S07_L004"                                               # when the debate starts
WIN_LINES = ("SCR_D01_S07_L012", "SCR_D01_S07_L013", "SCR_D01_S07_L014", "SCR_D01_S07_L015")
LOSS_LINES = ("SCR_D01_S07_L017", "SCR_D01_S07_L018", "SCR_D01_S07_L019")    # L016 is shown in the debate

ACTION_HINT = {OA.ATTACK: "TELL_D01_HINT_ASSERT", OA.FORCE: "TELL_D01_HINT_PUSH", OA.REBUT: "TELL_D01_HINT_REBUT",
               OA.PARRY: "TELL_D01_HINT_STALL"}
FOG = ("FOG_D01_1", "FOG_D01_2", "FOG_D01_3")
# only 06B refuted with the picked-up handkerchief (ch §12.0 BEAT_D01_REFUTED_1/2; design e62621f: 04C cannot be
# refuted)
KITCHEN_REFUTE = ("E07", ("06B",))

_PKG = Path(__file__).resolve().parents[4] / "source" / "localization" / "d01" / "strings_d01.json"


def package_keys() -> set[str]:
    """The D01 localization package's keys (the fallbacks below depend on which lines exist)."""
    return set(json.loads(_PKG.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class Step:
    who: str = ""     # speaker key of the spoken line ("" with a line = staging, no name plate)
    line: str = ""    # spoken line key
    sys: str = ""     # system line key

    def empty(self) -> bool:
        return not self.line and not self.sys


@dataclass
class Memo:
    """What the playback remembers across the rounds of one debate."""
    hints: set = field(default_factory=set)     # Arthur's hints already shown
    tells: dict = field(default_factory=dict)    # his tell lines shown per action (they take turns)
    clashed: bool = False                        # BEAT_D01_CLASH_* played (first clash only)
    hachiku: bool = False                        # 破竹 went up once (STATE_D01_ART_HACHIKU)
    shaken: bool = False                         # he was in 破防 once (STATE_D01_SHF_SHAKEN)
    psych_noted: bool = False                    # SYS_D01_PSYCH_NOTE shown
    privates: set = field(default_factory=set)   # private-matter claims announced (SYS_D01_PRIVATE)
    nobreak: bool = False                        # E7: SYS_D01_CHAIN_NOBREAK shown (once per debate)
    cut_opens: int = 0                           # E8: SHF_D01_CUT_OPEN_1 / _2 played (they take turns)
    key_open: bool = False                       # E8: SHF_D01_CUT_OPEN_3 played (the keystone, once per debate)


def outro(outcome: str) -> tuple[str, ...]:
    return WIN_LINES if outcome == "win" else LOSS_LINES


def outro_cue(outcome: str) -> str:
    return "postWin" if outcome == "win" else "postLose"


# ------------------------------------------------------------------------------------------------ the tell


def can_cut(s: State, card: str) -> bool:
    """A claim in this round's picker that shows as 正論 and breaks the card (ch §12.0 TELL_D01_HINT_NOCUT)."""
    brk = s.ch.breakers.get(card, ())
    return any(not v.soph and v.id in brk for v in K.claim_list(s) if not K.is_catch(v.id))


LAST_HINT, SLIP_HINT = "TELL_D01_HINT_LAST", "TELL_D01_HINT_SLIP"
KEY_HINT, NOCUT_HINT, FACT_HINT = "TELL_D01_HINT_KEY", "TELL_D01_HINT_NOCUT", "TELL_D01_HINT_FACT"
EVERY_TIME = (LAST_HINT, SLIP_HINT)
TELL_WORD = {OA.ATTACK: "ASSERT", OA.FORCE: "PUSH", OA.REBUT: "REBUT", OA.PARRY: "STALL"}


def tell_keys(keys: set, act) -> list[str]:
    """His own tell lines for an action (TELL_D01_<ACTION>_1, _2, ... as the package has them)."""
    word = TELL_WORD.get(act)
    out = []
    while word and f"TELL_D01_{word}_{len(out) + 1}" in keys:
        out.append(f"TELL_D01_{word}_{len(out) + 1}")
    return out


def hint(s: State, tell, memo: Memo) -> str | None:
    """Arthur's hint for the tell (rule items 1-6 above), not yet marked used."""
    clear = tell.clarity.value == "clear"
    cd = s.ch.cards.get(tell.card) if tell.card else None
    cands = []
    if s.endgame is not None:
        cands.append(LAST_HINT)
    if tell.partial:
        cands.append(SLIP_HINT)
    if cd is not None and cd.keystone:
        cands.append(KEY_HINT)
    if cd is not None and cd.is_lie and not can_cut(s, tell.card):
        cands.append(NOCUT_HINT)
    if cd is not None and cd.is_fact and cd.kind != "unfav":
        cands.append(FACT_HINT)
    if clear and tell.shown[0] in ACTION_HINT:
        cands.append(ACTION_HINT[tell.shown[0]])
    return next((k for k in cands if k in EVERY_TIME or k not in memo.hints), None)


def tell_lines(s: State, tell, memo: Memo, keys: set | None = None) -> list[tuple[str, str]]:
    """[(speaker, key)] shown with the tell of the round about to be chosen (state s, the AI's tell), in order.
    Marks the hint used and turns his tell line in `memo`."""
    if s.outcome or s.player_locked or tell is None:
        return []
    keys = package_keys() if keys is None else keys
    out: list[tuple[str, str]] = []
    if tell.clarity.value == "clear" and s.endgame is None:
        act = tell.shown[0]
        own = tell_keys(keys, act)
        if own:
            n = memo.tells.get(act, 0)
            memo.tells[act] = n + 1
            out.append((CE, own[n % len(own)]))
    if s.endgame is not None and s.endgame["card"] == "P05":
        out.append((AR, "BEAT_D01_LASTCARD_1"))
    h = hint(s, tell, memo)
    if h is not None:
        memo.hints.add(h)
        out.append((AR, h))
    if s.endgame is not None and s.endgame["dying"]:
        out.append((CE, "SCR_D01_S07_L010"))
    return out


# ------------------------------------------------------------------------------------------------ records


def records(events: list, before: State) -> list[dict]:
    """The engine's records (debate-engine-v2 §2.3) of a round's ref events, as dicts with `k` = the record kind;
    sub-records (redCrackRemoved, ronpaNode, lastCardRemoved, lastStandDestroyed, reverseRonpaNode) included."""
    ch = before.ch
    chain = [n.claim for n in before.player_chain]
    out: list[dict] = []
    for e in events:
        k = e["kind"]
        if k == "round":
            out.append({"k": "round"})
        elif k == "player_damage":
            out.append({"k": "pDmg", "amount": e["amount"], "cause": e["cause"], "hp": e["hp"]})
        elif k == "opp_damage":
            out.append({"k": "oDmg", "amount": e["amount"], "cause": e["cause"], "hp": e["hp"]})
        elif k == "opp_heal":
            out.append({"k": "oHeal"})
        elif k == "heal_void":
            out.append({"k": "healVoid"})
        elif k == "reraise":
            out.append({"k": "reraise", "card": e["card"]})
        elif k == "psych_event":
            out.append({"k": "psych"})
        elif k == "opp_attach":
            out.append({"k": "oAttach", "card": e["card"]})
        elif k == "player_attach":
            f = e["factors"]
            prev = chain[-1] if "continuation" in f and chain else ""
            out.append({"k": "pAttach", "claim": e["claim"], "prev": prev})
            chain.append(e["claim"])
        elif k == "red_crack":
            out.append({"k": "redCrack"})
            out += [{"k": "redCrackRemoved"} for c in chain if c in e["removed"]]
            chain = [c for c in chain if c not in e["removed"]]
        elif k == "exposed":
            out.append({"k": "exposed"})
        elif k == "refuted":
            out.append({"k": "refuted", "claim": e["claim"], "line": e["line"], "reveals": e["reveals"]})
        elif k == "blocked":
            out.append({"k": "blocked"})
        elif k == "intercept":
            out.append({"k": "intercept", "claim": e["claim"], "card": e["card"], "ok": e["ok"],
                        "keystone": e.get("keystone", False), "parried": e.get("blocked_by_parry", False)})
        elif k == "broken":
            out.append({"k": "broken"})
        elif k == "dismantle":
            out.append({"k": "dismantle", "claim": e["claim"], "card": e["card"], "ok": e["ok"]})
        elif k == "stall":
            out.append({"k": "stall", "vs": e["vs"], "repeat": e["repeat"]})
        elif k == "guard_saved":
            out.append({"k": "guardSaved"})
        elif k == "hachiku":
            out.append({"k": "hachiku", "before": e["before"], "after": e["after"]})
        elif k == "shisshu":
            out.append({"k": "shisshu", "on": e["on"]})
        elif k == "threshold_crossed":
            out.append({"k": "crossed", "stat": e["stat"]})
        elif k == "debate_over":
            out.append({"k": "over", "outcome": e["outcome"], "reason": e["reason"]})
        elif k == "reverse_ronpa":
            out.append({"k": "reverseRonpa"})
            out += [{"k": "reverseRonpaNode"} for _ in e["chain"]]
        elif k == "ronpa":
            out.append({"k": "ronpa", "via": e["via"]})
            out += [{"k": "ronpaNode"} for _ in e["chain"]]
        elif k == "endgame":
            out.append({"k": "endgame", "trigger": e["trigger"]})
        elif k == "last_card":
            if e["cut"]:
                out.append({"k": "lastCard", "card": e["card"], "cut": True, "dying": False})
            elif e.get("dying"):
                out.append({"k": "lastCard", "card": e["card"], "cut": False, "dying": True})
            else:
                out.append({"k": "lastCard", "card": e["card"], "cut": False, "dying": False})
                out += [{"k": "lastCardRemoved"} for c in chain if c in e["removed"]]
        elif k == "last_stand":
            out.append({"k": "lastStand", "ok": e["ok"]})
            if e["ok"]:
                out += [{"k": "lastStandDestroyed"} for _ in e["destroyed"]]
        elif k == "rule3_armed":
            out.append({"k": "rule3Armed"})
        else:
            raise ValueError(f"unmapped ref event {k}")
    return out


# ------------------------------------------------------------------------------------------------ one round


def _card_line(keys: set, card: str, part: str) -> str:
    """CARD_D01_<card>_<PART>; a 強辯 / 改口 line the package does not have falls back to the 立論 line."""
    state = f"CARD_D01_{card}_STATE"
    if part == "STATE":
        return state
    k = f"CARD_D01_{card}_{part}"
    return k if k in keys else state


def _down_line(keys: set, s: State, card: str) -> str:
    k = f"CARD_D01_{card}_DOWN"
    if k in keys:
        return k
    return "REACT_D01_FACT_SOPH_1" if s.ch.cards[card].is_fact else "REACT_D01_LIE_SOPH"


def _react(keys: set, claim: str, soph: bool, s: State) -> str:
    """His reaction to her link landing (§9): the claim's own, else the sophistry one, else the issue's."""
    if not K.is_catch(claim):
        for k in (f"REACT_D01_{claim}", f"REACT_D01_{claim}_1"):
            if k in keys:
                return k
    if soph:
        return "REACT_D01_SOPH"
    issue = s.ch.cards[claim.split(":")[1]].issue if K.is_catch(claim) else s.ch.claims[claim].issue
    return f"REACT_D01_ISSUE_{ {'機': 'OPP', '法': 'METHOD', '動': 'MOTIVE'}[issue] }"


def _claim_line(s: State, claim: str) -> str:
    if K.is_catch(claim):
        return f"CARD_D01_{claim.split(':')[1]}_CATCH"
    return f"CLM_D01_{claim}_LINE"


ISSUE_KEY = {"機": "OPP", "法": "METHOD", "動": "MOTIVE"}


def chain_issues(s: State, ids: list[str], cards: bool = False) -> list[str]:
    """E7: the issues a chain covers ({issues} of SYS_D01_CHAIN_READY / REV_READY): their ISSUE_D01_<x> keys in the
    order the chain first reaches them (ch §12.1 R8 機、法、動; §12.4 R6-R7 his chain F1 → L2 → F2: 法、機)."""
    out: list[str] = []
    for i in ids:
        if cards:
            iss = s.ch.cards[i].issue
        else:
            iss = s.ch.cards[i.split(":")[1]].issue if K.is_catch(i) else s.ch.claims[i].issue
        key = f"ISSUE_D01_{ISSUE_KEY[iss]}"
        if key not in out:
            out.append(key)
    return out


def link_key(keys: set, s: State, prev: str, claim: str) -> str:
    """Her 承接 line (ch §8) when her link follows `prev`: LINK_D01_<prev>_<claim>; a pair the table marks ↔ (both
    directions in ch.continuations) has one line for both orders (E7: 03A after 02A and 02A after 03A alike)."""
    if not prev:
        return ""
    k = f"LINK_D01_{prev}_{claim}"
    if k in keys:
        return k
    rev = f"LINK_D01_{claim}_{prev}"
    both = (prev, claim) in s.ch.continuations and (claim, prev) in s.ch.continuations
    return rev if both and rev in keys else ""


def excl_other(s: State, claim: str | None) -> str | None:
    """E7 (ch §7 互斥表): the claim of her public record that `claim` contradicts (the red crack), the earliest
    record entry when there are two; None for none."""
    if not claim or K.is_catch(claim):
        return None
    excl = set(s.ch.claims[claim].exclusive)
    return next((r.claim for r in s.record if r.claim in excl), None)


def excl_keys(claim: str, other: str) -> tuple[str, str]:
    """EXCL_D01_<a>_<b>_CATCH / _SELL, the pair in id order (ch §7)."""
    a, b = sorted((claim, other))
    return f"EXCL_D01_{a}_{b}_CATCH", f"EXCL_D01_{a}_{b}_SELL"


CUT_OPEN = ("SHF_D01_CUT_OPEN_1", "SHF_D01_CUT_OPEN_2")
CUT_OPEN_KEY = "SHF_D01_CUT_OPEN_3"


def cut_open(memo: Memo, keystone: bool) -> str:
    """E8 (design ruling): Sherefox's opener before her claim line when her cut lands in a normal round. The keystone
    (L2) gets _3 the first time; every other landed cut takes _1 and _2 in turn, from _1. Marks it in `memo`."""
    if keystone and not memo.key_open:
        memo.key_open = True
        return CUT_OPEN_KEY
    k = CUT_OPEN[memo.cut_opens % len(CUT_OPEN)]
    memo.cut_opens += 1
    return k


def nobreak_now(s: State, recs: list, s2: State) -> bool:
    """E7 (design ruling): her link landed and her chain is long enough for a Break, but he is not in 破防 (at the end
    of the round, when the Break is judged), so no Break."""
    return (any(r["k"] == "pAttach" for r in recs) and len(s2.player_chain) >= s.ch.ronpa_len
            and s2.broken_until < s.round)


def round_steps(s: State, pa, oa, ev: list, s2: State, memo: Memo, keys: set | None = None) -> list[Step]:
    """The steps the screen shows for one round (state s, player action pa, opponent action oa as resolved, ref events
    ev, state after s2), in order. Updates `memo` (the once-per-debate lines)."""
    keys = package_keys() if keys is None else keys
    ch = s.ch
    recs = records(ev, s)
    mode = "endgame" if s.endgame is not None else "laststand" if s.player_locked else "normal"
    claim = pa.claim
    if claim == CATCH:
        claim = f"{CATCH}:{s.catch_card}"
    view = K.view(s, claim) if claim else None
    soph = bool(view and view.soph)
    psych = bool(view and view.psych_card)
    crack = bool(view and view.red_crack)
    carried = set(s.loadout.carried)
    over = s2.outcome is not None
    dying_next = bool(s2.endgame and s2.endgame["dying"])
    lc_card = s.endgame["card"] if s.endgame else None
    first_p1 = claim in ("P1A", "P1B") and not any(r.claim in ("P1A", "P1B") for r in s.record)
    appraisal_soph = bool(claim and not K.is_catch(claim) and soph and
                          any(k in s.known and k in ch.appraisals for k in ch.claims[claim].conflicts))
    steps: list[Step] = []
    pat = False                      # our link landed earlier this round (CLASH)
    int_blk = False                  # the cut was barred by last round's sidestep
    for i, r in enumerate(recs):
        k = r["k"]
        nx = recs[i + 1] if i + 1 < len(recs) else {"k": ""}
        pre: list[Step] = []
        post: list[Step] = []
        who = line = sysk = ""
        # -------- the record's main lines (tools/gen_debui_v2.py speech / sysl, first match)
        if k == "round":
            if crack:
                pre.append(Step(AR, "BEAT_D01_REDCRACK_1"))
            if claim == "09A":
                pre.append(Step(AR, "BEAT_D01_09A_1"))
            if mode == "endgame" and not s.endgame["dying"]:
                pre.append(Step(sys="SCR_D01_S07_L011"))
            cut = next((x for x in recs if x["k"] == "intercept" and x["ok"]), None)
            if mode == "normal" and cut is not None:     # E8: right before her claim line
                pre.append(Step(SH, cut_open(memo, ch.cards[cut["card"]].keystone)))
            if claim:
                who, line = SH, _claim_line(s, claim)
            elif pa.kind == PA.STALL:
                who, line = SH, FOG[(s.round - 1) % 3]
            if claim == "06B" and "E07" in carried:
                post.append(Step(AR, "BEAT_D01_SOPH_06B_1"))
            elif claim == "06C":
                post.append(Step(AR, "BEAT_D01_SOPH_06C_1"))
            elif appraisal_soph:
                post.append(Step(AR, "BEAT_D01_SOPH_03C_1"))
            if first_p1:
                post.append(Step(STAGE, "BEAT_D01_P1A_1"))
        elif k == "pAttach":
            pat = True
            c = r["claim"]
            link = link_key(keys, s, r["prev"], c)
            if link:
                who, line = SH, link
            else:
                who, line = CE, _react(keys, c, soph, s)
            sysk = "SYS_D01_ATTACH"
            if c == "09A":
                pre.append(Step(IRE, "REACT_D01_09A_3"))
                post.append(Step(MRS, "REACT_D01_09A_2"))
            if first_p1:
                post.append(Step(AR, "BEAT_D01_P1A_2"))
            if c == "02C":
                post.append(Step(MRS, "BEAT_D01_02C_1"))
            if c == "07A":
                post += [Step(MAR, "BEAT_D01_07A_1"), Step(BRI, "BEAT_D01_07A_2")]
            if soph and not psych:      # E5: a sophistry link landed (a psych card leaves no crack)
                post.append(Step(sys="SYS_D01_CRACK"))
            if not memo.nobreak and nobreak_now(s, recs, s2):     # E7: once per debate
                memo.nobreak = True
                post.append(Step(sys="SYS_D01_CHAIN_NOBREAK"))
        elif k == "broken":             # E5: his first 破防 of the debate
            if not memo.shaken:
                memo.shaken = True
                who, line = SH, "STATE_D01_SHF_SHAKEN"
        elif k == "oAttach":
            card = r["card"]
            who, line = CE, _card_line(keys, card, "PUSH" if oa.kind == OA.FORCE else "STATE")
            if ch.cards[card].kind == "unfav":
                sysk = "SYS_D01_SLIP_NODMG"
        elif k == "reraise":
            who, line = CE, _card_line(keys, r["card"], "RETRACT")
        elif k == "refuted":
            who, line = CE, r["line"]
            if r["reveals"]:
                sysk = "SYS_D01_NOW_KNOWN"
            via = next((v for v, ln in ch.claims[r["claim"]].opp_refute if ln == r["line"]), None)
            if via == KITCHEN_REFUTE[0] and r["claim"] in KITCHEN_REFUTE[1]:
                post += [Step(BRI, "BEAT_D01_REFUTED_1"), Step(MAR, "BEAT_D01_REFUTED_2")]
            if via in ch.evidence:
                post += [Step(SH, "BEAT_D01_REFUTED_3"), Step(AR, "BEAT_D01_REFUTED_4")]
        elif k == "intercept":
            int_blk = r["parried"]
            if r["ok"]:
                who, line = CE, _knocked(keys, s, r, soph)
                cd = ch.cards[r["card"]]
                if r["keystone"]:
                    sysk = "SYS_D01_KEY_BREAK"
                elif cd.keystone:
                    sysk = "SYS_D01_KEY_NORMAL"
                elif cd.is_fact:
                    sysk = "SYS_D01_DENY_FACT"
        elif k == "dismantle":
            if r["ok"]:
                who, line = CE, _knocked(keys, s, r, soph)
                if ch.cards[r["card"]].is_fact:
                    sysk = "SYS_D01_DENY_FACT"
        elif k == "blocked":
            who, line, sysk = CE, "REACT_D01_BLOCK", "SYS_D01_BLOCKED"
        elif k == "oDmg":
            cause = r["cause"]
            if cause == "whiff":
                who, line = CE, "REACT_D01_FOOLED"
                if pa.kind == PA.DISMANTLE:
                    sysk = "SYS_D01_OPP_REBUT_MISS"
            elif cause == "intercept":
                sysk = ("SYS_D01_CUT_SOPH" if soph else
                        "SYS_D01_CUT_PUSH" if r["amount"] > 20 else "SYS_D01_CUT_OK")
                if claim == "07A":
                    post += [Step(MAR, "BEAT_D01_07A_1"), Step(BRI, "BEAT_D01_07A_2")]
            elif cause == "dismantle":
                sysk = "SYS_D01_DISMANTLE"
        elif k == "guardSaved":
            who, line, sysk = AR, "STATE_D01_ART_COVER", "SYS_D01_COVER"
        elif k == "hachiku":
            if r["after"] > r["before"]:
                who, line = SH, f"STATE_D01_SHF_HACHIKU_{min(3, r['after'])}"
                if not memo.hachiku:        # E5: the first time 破竹 goes up in this debate
                    memo.hachiku = True
                    post.append(Step(AR, "STATE_D01_ART_HACHIKU"))
        elif k == "ronpa":
            if r["via"] == "chain":     # E7: the Break by chain length and issues (a keystone Break: KEY_BREAK)
                pre.append(Step(sys="SYS_D01_CHAIN_READY"))
            who, line = SH, "STATE_D01_SHF_BREAK"
            if not over:
                sysk = "SCR_D01_S07_L005"
        elif k == "reverseRonpa":
            pre.append(Step(sys="SYS_D01_REV_READY"))     # E7: right before SYS_D01_REVERSE
            who, line, sysk = CE, "BEAT_D01_REVERSE_1", "SYS_D01_REVERSE"
        elif k == "lastCard":
            if r["cut"]:
                who, line, sysk = CE, _down_line(keys, s, r["card"]), "SYS_D01_CUT_WIN"
            elif not r["dying"] and nx["k"] != "lastCardRemoved":
                post += _after_last_card(over)
        elif k == "lastCardRemoved":
            if nx["k"] != "lastCardRemoved":
                sysk = "SYS_D01_LASTCARD_REMOVE"
                post += _after_last_card(over)
        elif k == "lastStand":
            if r["ok"]:
                sysk = "SYS_D01_LASTSTAND_OK"
            else:
                who, line, sysk = CE, "BEAT_D01_LASTSTAND_FAIL_1", "SYS_D01_LASTSTAND_FAIL"
        elif k == "crossed":
            sysk = "SYS_D01_PSYCH_CROSS"
            if r["stat"] == "G":
                who, line = AR, "BEAT_D01_GUILT_1"
            elif r["stat"] == "A":
                who, line = CE, "BEAT_D01_ANGER_1"
            elif r["stat"] == "P":          # E5: he is cornered (困獸)
                post.append(Step(AR, "STATE_D01_ART_CORNERED"))
        elif k == "stall":
            who, line = CE, "REACT_D01_FOGGED"
            if r["vs"] == "rebut" and not r["repeat"]:
                sysk = "SYS_D01_FOOLED"
        elif k == "oHeal":
            sysk = "SYS_D01_STALL_HEAL"
        elif k == "shisshu":
            if r["on"]:
                sysk = "SYS_D01_BREACH_HINT"
                post += [Step(SH, "STATE_D01_SHF_BREACHED"), Step(AR, "STATE_D01_ART_BREACHED")]
        elif k == "endgame":
            if r["trigger"] == "zero" and not over:
                sysk = "SCR_D01_S07_L006"
            if dying_next and not over:
                post.append(Step(sys="SCR_D01_S07_L009"))
        elif k == "healVoid":   # his last card's recovery voided by 困獸 (a sidestep's voided heal has no line)
            if mode == "endgame" and not over:
                sysk = "SYS_D01_LASTCARD_CORNERED"
        elif k == "over":
            if r["reason"] == "surrender":
                pre += [Step(sys="SCR_D01_S07_L007"), Step(CE, "SCR_D01_S07_L008")]
            if r["reason"] == "round_limit":
                sysk = "UI_V2_TIME_UP"
                if r["outcome"] == "loss":
                    post.append(Step(sys="SCR_D01_S07_L016"))
            elif r["reason"] == "second_zero":
                sysk = "SYS_D01_ZERO_WIN"
            elif r["outcome"] == "win":
                sysk = "SYS_D01_WIN"
            else:
                sysk = "SCR_D01_S07_L016"
        elif k == "pDmg":
            cause = r["cause"]
            act = pa.kind
            if cause == "argument" and act == PA.STALL:
                sysk = "SYS_D01_FOG_TAKE"
            elif cause == "argument" and pat:
                sysk = "SYS_D01_CLASH"
                if not memo.clashed:
                    memo.clashed = True
                    pre += [Step(CE, "BEAT_D01_CLASH_1"), Step(SH, "BEAT_D01_CLASH_2")]
            elif cause == "exposed":
                sysk = "SYS_D01_EXPOSED"
            elif cause == "refuted":
                sysk = "SYS_D01_REFUTED"
            elif cause == "contradiction":
                sysk = "SYS_D01_REDCRACK"
                other = excl_other(s, claim)    # E7 (ch §7): he catches the contradiction, she hard-sells
                if other:
                    ck, sk = excl_keys(claim, other)
                    pre += [Step(CE, ck), Step(SH, sk)]
            elif cause == "whiff" and act == PA.INTERCEPT and nx["k"] == "oDmg":
                sysk = "SYS_D01_BOTH_REBUT"
            elif cause == "whiff" and act == PA.INTERCEPT and nx["k"] in ("oHeal", "healVoid"):
                sysk = "SYS_D01_CUT_EMPTY"
            elif cause == "whiff" and act == PA.INTERCEPT and nx["k"] == "oAttach" and int_blk:
                sysk = "SYS_D01_CUT_SEALED"
            elif (cause == "whiff" and act == PA.INTERCEPT and nx["k"] == "oAttach") or cause == "bad_cut":
                sysk = "SYS_D01_MISS_WRONG"
            elif cause == "whiff" and act == PA.DISMANTLE and nx["k"] == "dismantle":
                fact = ch.cards[nx["card"]].is_fact
                sysk = "SYS_D01_TOPPLE_MISS_FACT" if fact and not soph else "SYS_D01_TOPPLE_MISS_WRONG"
            elif cause == "fact_miss":
                sysk = "SYS_D01_MISS_FACT"
            elif cause == "stalemate" and act == PA.STALL:
                sysk = "SYS_D01_FOG_STALL"
            elif cause == "stall_repeat":
                sysk = "SYS_D01_FOG_REPEAT"
            elif cause == "dying":
                sysk = "SYS_D01_DESPERATE_HIT"
            elif cause == "last_card":
                pre.append(Step(CE, _card_line(keys, lc_card, "STATE")))
                if lc_card == "P05":
                    if s.cracks >= 1:
                        pre += [Step(CE, "BEAT_D01_LASTCARD_4"), Step(INS, "BEAT_D01_LASTCARD_2")]
                    else:
                        pre.append(Step(INS, "BEAT_D01_LASTCARD_3"))
                if over or nx["k"] == "healVoid":
                    sysk = "SYS_D01_LASTCARD_NOHEAL"
                elif nx["k"] == "lastCard":
                    sysk = "SYS_D01_LASTCARD_HIT"
        steps += pre + [Step(who, line, sysk)] + post
    # tail (after the last record): 破竹 held (E4: ≥ 1 layer, no layer added, not reset; a normal round the debate
    # goes on after); E5: the first psych card of the debate, a private matter said (once per claim), cover set and
    # not triggered (a normal round the debate goes on after)
    if mode == "normal" and not over and s.hachiku >= 1 and s2.hachiku == s.hachiku:
        steps.append(Step(sys="SYS_D01_HACHIKU_KEEP"))
    if psych and not memo.psych_noted:
        memo.psych_noted = True
        steps.append(Step(sys="SYS_D01_PSYCH_NOTE"))
    if claim and not K.is_catch(claim) and ch.claims[claim].private and claim not in memo.privates:
        memo.privates.add(claim)
        steps.append(Step(sys="SYS_D01_PRIVATE"))
    if mode == "normal" and not over and pa.guard and not any(r["k"] == "guardSaved" for r in recs):
        steps.append(Step(sys="SYS_D01_COVER_WASTED"))
    return [st for st in steps if not st.empty()]


def _knocked(keys: set, s: State, r: dict, soph: bool) -> str:
    """His line when her cut / dismantle knocks his link down: a fact (only sophistry does that), a lie by
    sophistry, the claim's own cut line (cuts only), else the card's knocked-down line."""
    card = r["card"]
    if s.ch.cards[card].is_fact:
        return "REACT_D01_FACT_SOPH_1" if s.round % 2 == 1 else "REACT_D01_FACT_SOPH_2"
    if soph:
        return "REACT_D01_LIE_SOPH"
    cut = f"CUT_D01_{r['claim']}_{card}"
    if r["k"] == "intercept" and cut in keys:
        return cut
    return _down_line(keys, s, card)


def _after_last_card(over: bool) -> list[Step]:
    out = [Step(SH, "BEAT_D01_LASTCARD_5")]
    if not over:
        out.append(Step(AR, "BEAT_D01_LASTCARD_6"))
    return out


def debate_steps(rounds: list, tells: list, keys: set | None = None) -> list[dict]:
    """The whole debate: per round {'tell': [(speaker, key)], 'steps': [Step]}; `rounds` = [(state before, pa,
    oa)], `tells` = the AI's tell shown for each round (None in the §7.5 round). The opening step (L004) is not
    included (OPENING_SYS)."""
    from .resolve import resolve_round
    keys = package_keys() if keys is None else keys
    memo = Memo()
    out = []
    for (s, pa, oa), tl in zip(rounds, tells):
        s2, ev = resolve_round(s, pa, oa)
        tell = tell_lines(s, tl, memo, keys)
        out.append({"tell": tell, "steps": round_steps(s, pa, oa, ev, s2, memo, keys)})
    return out
