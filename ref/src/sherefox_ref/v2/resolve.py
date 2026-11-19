"""resolve_round: one simultaneous round of the v2 debate (00_core_rules.md §5.3).

    1 tell (policy.py) -> 2 choice -> 3 reveal and settle (§6.3 duel table, §6.4, §7.1)
    -> 4 psych update (events, then thresholds, §8) -> 5 stance check
       (破防/失守 -> 論破 -> 歸零 -> 失常) -> round limit -> start of the next round

The start of round r+1 (natural psych decay, R-11) is applied at the end of
resolve_round(r), so the state between rounds is exactly what the opponent decides on
and what the player sees under the next tell. ``State.psych_end`` keeps the values after
round r's events and before the decay (the 心理 column of ch §12).

Two special rounds use the same entry point:
* endgame round (§7.4): opponent action ``OA.LAST``; player ``PA.CUT`` or ``PA.ACCEPT``;
* §7.5 round after a reverse ronpa: opponent ``OA.NONE``; player ``PA.LAST_STAND`` or
  ``PA.ACCEPT``.

resolve_round is pure: the input state is deep-copied, never mutated.
"""

from __future__ import annotations

from copy import deepcopy

from . import known as K
from .model import (
    ACTIONS, BASE_CATCH, BASE_PROPER, BASE_SOPH, BROKEN_BONUS, COMBO_CAP, COMBO_STEP,
    COMEBACK_RATIO, CONTINUATION, CONTRADICTION, DISMANTLE_DMG, DYING_DMG, EXPOSED,
    FACT_MISS, FEW_OPTIONS_AT, FORCE_MULT, HACHIKU_MAX, HACHIKU_STEP, HEAL, INTERCEPT_DMG,
    INTERCEPT_FORCE_EXTRA, KEY_HP_RATIO, LAST_BAD_CUT, LAST_HEAL_CAP, LAST_HEAL_PER_CRACK,
    LAST_PER_CRACK, LAST_PICKED_EXTRA, LAST_ZERO_C_DMG, LAST_ZERO_C_HEAL, OA, PA,
    RAGE_FORCE_MULT, REFUTED, RERAISE_MULT, SHISSHU_MULT, STALEMATE, STALL_REPEAT_EXTRA,
    WHIFF, A, G, IllegalAction, ONode, OpponentAction, P, PlayerAction, PNode,
    RecordEntry, State,
)

STAT = ("P", "G", "A")


def combo_mult(combo: int) -> float:
    return 1.0 + COMBO_STEP * (min(combo, COMBO_CAP) - 1)


class _Round:
    """Per-round scratch flags."""

    def __init__(self, s: State):
        self.r = s.round
        self.broken_start = s.broken_now()  # §7.1 / R-25: modifiers use the round-start state
        self.hachiku_start = s.hachiku
        self.shisshu_start = s.shisshu
        self.opp_hp_start = s.opp_hp
        self.hp0 = s.player_hp
        self.p_att = False
        self.o_att = False
        self.read_ok = False
        self.read_bad = False
        self.hurt = False  # he hurt the player this round (§7.2 破竹 condition)
        self.guard_trigger = False
        self.key_ronpa = False
        self.p_dmg = 0.0  # 論證 dealt this round (§7.3 simultaneous-ronpa comparison)
        self.o_dmg = 0.0
        self.p_events: list = []  # player-side events [(name, (P, G, A))]
        self.o_event = None  # opponent-side event name
        self.shisshu_next = False
        self.knocked_lie = None
        self.player_soph = False
        self.next_clear = False


# --------------------------------------------------------------------------- small helpers


# Damage the opponent deals the player (§7.2 失守 +25% applies to these only).
OPP_DEALT = frozenset({"argument", "exposed", "refuted", "last_card", "dying"})


def _hurt_player(s: State, rd: _Round, amount: float, cause: str, ev: list) -> float:
    # SPEC-QUESTION, decided by the design owner (rules 0.6): 失守 +25% applies only to
    # damage he deals the player: his 論證, 拆穿 25, 駁倒 15 and the last card's hit
    # (incl. the dying gasp). Not to costs the player causes herself: red crack −10, a
    # whiffed cut's −5/−10, 打迷糊仗 penalties (−3, bystander −3), mutual whiffs, a bad
    # endgame cut's −5.
    if rd.shisshu_start and cause in OPP_DEALT:
        amount *= SHISSHU_MULT
    s.player_hp -= amount
    ev.append({"kind": "player_damage", "amount": amount, "cause": cause, "hp": s.player_hp})
    return amount


def _hurt_opp(s: State, amount: float, cause: str, ev: list) -> None:
    s.opp_hp -= amount
    ev.append({"kind": "opp_damage", "amount": amount, "cause": cause, "hp": s.opp_hp})


def _heal_opp(s: State, ev: list) -> None:
    """周旋 +5 (§6.2); void while pressure is over (§8.3 困獸)."""
    if s.over[P]:
        ev.append({"kind": "heal_void"})
        return
    before = s.opp_hp
    s.opp_hp = min(s.ch.opp_max_hp, s.opp_hp + HEAL)
    ev.append({"kind": "opp_heal", "before": before, "hp": s.opp_hp})


def _reraise(s: State, ev: list) -> None:
    """周旋 re-raises a knocked-down lie (§6.2, R-27): the card knocked last round (rule ①
    "那張牌") if any, else the oldest. It goes back to hand and is played before L3
    (ch §11 出牌順序)."""
    if not s.knocked:
        return
    cid = s.flag_knocked_lie if s.flag_knocked_lie in s.knocked else s.knocked[0]
    s.knocked.remove(cid)
    s.hand.append(cid)
    s.reraised.append(cid)
    ev.append({"kind": "reraise", "card": cid})


def _remove_from_hand(s: State, cid: str) -> None:
    s.hand.remove(cid)
    if cid in s.reraised:
        s.reraised.remove(cid)


def _psych_add(s: State, name: str, delta, ev: list) -> None:
    for i in range(3):
        s.psych[i] = max(0.0, min(100.0, s.psych[i] + delta[i]))
    ev.append({"kind": "psych_event", "event": name, "delta": list(delta), "psych": list(s.psych)})


def _claim_effect(s: State, rd: _Round, claim_id: str) -> None:
    """Scripted 心理作用 of a claim (heart-knot / weakness / private), fired when the claim
    attaches or cuts successfully (§8.1, R-20), once per debate where marked."""
    if K.is_catch(claim_id):
        return
    c = s.ch.claims[claim_id]
    if c.psych is None:
        return
    if c.psych_once and claim_id in s.psych_used:
        return
    s.psych_used.add(claim_id)
    rd.p_events.append((c.psych_kind or "psych_card", c.psych))


def few_options_count(s: State) -> int:
    """§5.2 (R-28, V-10): lies + favourable facts + picked-up items still in hand; cards on
    his chain do not count; a re-raised card counts once it is back in hand.
    SPEC-QUESTION: the picked-up item kept as the last card is not counted (it is not a
    normal play)."""
    return sum(1 for c in s.hand if s.ch.cards[c].kind in ("lie", "fav", "pickup"))


def _refuting_line(s: State, claim_id: str) -> str | None:
    """§3.1 對手能否駁倒: via a picked-up evidence item (V-09: information, never consumed)
    or via a fact card standing on his chain."""
    if K.is_catch(claim_id):
        return None
    for via, line in s.ch.claims[claim_id].opp_refute:
        if via in s.picked:
            return line
        if via in s.ch.cards and via in [n.card for n in s.opp_chain]:
            return line
    return None


def _set_broken(s: State, rd: _Round, cause: str, ev: list) -> None:
    s.broken_until = max(s.broken_until, rd.r + 1)  # "持續到下一回合結束" (§7.2)
    ev.append({"kind": "broken", "cause": cause, "until": s.broken_until})


# --------------------------------------------------------------------------- attach


def _opp_attach(s: State, rd: _Round, oa: OpponentAction, ev: list, factor: float = 1.0,
                damage: bool = True) -> None:
    ch = s.ch
    cd = ch.cards[oa.card]
    _remove_from_hand(s, oa.card)
    s.opp_chain.append(ONode(oa.card, cd.issue))
    s.opp_combo += 1
    rd.o_att = True
    # SPEC-QUESTION (rules vs sim/engine.py): ch §12.2 R4 / §12.4 R3: a node that lands counts as 成功打中玩家 (§8.2 "接上") even
    # when it deals no damage. sim/engine.py gives no event for an unfavourable fact.
    rd.o_event = "hit_player"
    ev.append({"kind": "opp_attach", "card": oa.card, "combo": s.opp_combo})
    if cd.kind == "unfav":
        s.catch_next = oa.card  # §6.5; V-01: no 論證
        return
    if not damage:
        return
    # SPEC-QUESTION (rules vs sim/engine.py): §7.1: base x his combo (x 強辯 1.25, x 1.25 more while angry, §8.3). No continuation
    # bonus for him (ch §12.4 R7: L4 after F2, same issue, 16x1.75x1.25 = 35); sim/engine.py
    # applies x1.2 to him too.
    d = ch.opp_base_damage * combo_mult(s.opp_combo)
    if oa.kind == OA.FORCE:
        d *= FORCE_MULT
        if s.over[A]:
            d *= RAGE_FORCE_MULT
    d *= factor
    rd.o_dmg = _hurt_player(s, rd, d, "argument", ev)
    rd.hurt = rd.hurt or rd.o_dmg > 0


def _player_attach(s: State, rd: _Round, claim_id: str, soph: bool, crack: bool, ev: list) -> None:
    ch = s.ch
    catch = K.is_catch(claim_id)
    if catch:
        issue, base, psych_card = ch.cards[s.catch_card].issue, BASE_CATCH, False
    else:
        c = ch.claims[claim_id]
        issue, psych_card = c.issue, c.psych_card
        base = BASE_SOPH if soph else BASE_PROPER
    prev = s.player_chain[-1] if s.player_chain else None
    s.player_chain.append(PNode(claim_id, issue, soph, crack, psych_card))
    s.player_combo += 1
    rd.p_att = True
    factors = {"base": base, "combo": combo_mult(s.player_combo)}
    d = base * factors["combo"]
    if prev is not None and (prev.issue == issue or (prev.claim, claim_id) in ch.continuations):
        d *= CONTINUATION
        factors["continuation"] = CONTINUATION
    if not catch and claim_id in s.knocked_claims:
        d *= RERAISE_MULT
        factors["reraise"] = RERAISE_MULT
    h = 1.0 + HACHIKU_STEP * rd.hachiku_start
    d *= h
    factors["hachiku"] = h
    if rd.broken_start:
        d *= BROKEN_BONUS
        factors["broken"] = BROKEN_BONUS
    rd.p_dmg = d
    ev.append({"kind": "player_attach", "claim": claim_id, "combo": s.player_combo,
               "factors": factors, "damage": d})
    _hurt_opp(s, d, "argument", ev)


# --------------------------------------------------------------------------- claim use


def _use_claim(s: State, rd: _Round, pa: PlayerAction, use: str, ev: list):
    """Validate a claim, pay a red crack, write the public record. Returns (view, crack)."""
    if pa.claim is None:
        raise IllegalAction(f"{pa.kind.value} needs a claim")
    if K.is_catch(pa.claim) and use != "argue":
        raise IllegalAction("抓住他的話 is an argue option only")
    v = K.view(s, pa.claim)
    if not v.available:
        raise IllegalAction(f"claim {pa.claim} is not available")
    if use == "argue" and v.standing:
        raise IllegalAction(f"claim {pa.claim} is already on the chain (§3.4)")
    claim_id = pa.claim
    if K.is_catch(claim_id) and claim_id == "CATCH":
        claim_id = f"CATCH:{s.catch_card}"
    # §3.2 psych card: settled as 詭辯 but no crack; §7.4 c: one crack per action (R-16)
    crack = (v.soph and not v.psych_card) or v.red_crack
    if v.red_crack:
        _hurt_player(s, rd, CONTRADICTION, "contradiction", ev)
        old = [n for n in s.player_chain if n.claim in s.ch.claims[claim_id].exclusive]
        for n in old:
            s.player_chain.remove(n)
            s.knocked_claims.add(n.claim)
        ev.append({"kind": "red_crack", "claim": claim_id, "removed": [n.claim for n in old]})
    if crack:
        s.cracks += 1
    s.record.append(RecordEntry(rd.r, claim_id, use, v.soph, crack, v.true))
    if not K.is_catch(claim_id):
        c = s.ch.claims[claim_id]
        if c.psych_card:
            s.psych_card_uses += 1
        if c.private:
            # SPEC-QUESTION: §10 "每次公開私事" counted when the claim is said (any outcome);
            # its 心理作用 only fires when it lands or cuts (§8.1).
            s.privates += 1
    rd.player_soph = v.soph
    return claim_id, v, crack


# --------------------------------------------------------------------------- normal round


def _normal_round(s: State, rd: _Round, pa: PlayerAction, oa: OpponentAction, ev: list) -> None:
    ch = s.ch
    r = rd.r
    if oa.kind not in ACTIONS:
        raise IllegalAction(f"opponent action {oa.kind} in a normal round")
    if oa.kind in (OA.ATTACK, OA.FORCE):
        if oa.card is None or oa.card not in s.hand:
            raise IllegalAction(f"card {oa.card} is not in his hand")
    elif oa.card is not None:
        raise IllegalAction("only 立論/強辯 carry a card")
    if pa.kind not in (PA.ARGUE, PA.INTERCEPT, PA.DISMANTLE, PA.STALL):
        raise IllegalAction(f"player action {pa.kind} in a normal round")
    if pa.guard:
        if s.guard_used:
            raise IllegalAction("援護 already used")
        s.guard_used = True
    attacks = oa.kind in (OA.ATTACK, OA.FORCE)
    s.opp_history.append(oa.kind)
    if attacks:
        s.next_unfav = False
    if pa.kind == PA.STALL:
        s.stall_streak += 1
        s.stalls += 1
    else:
        s.stall_streak = 0

    if pa.kind == PA.ARGUE:
        claim_id, v, crack = _use_claim(s, rd, pa, "argue", ev)
        soph = v.soph
        if oa.kind == OA.REBUT:
            rd.read_bad = True
            line = None if soph else _refuting_line(s, claim_id)
            if soph:  # 被拆穿 (§6.3)
                _hurt_player(s, rd, EXPOSED, "exposed", ev)
                s.player_combo = 0
                rd.shisshu_next = rd.hurt = rd.guard_trigger = True
                rd.o_event = "hit_player"
                ev.append({"kind": "exposed", "claim": claim_id})
            elif line is not None:  # 被駁倒 (R-05, R-08)
                _hurt_player(s, rd, REFUTED, "refuted", ev)
                s.player_combo = 0
                s.voided.add(claim_id)
                reveal = ch.refute_lines.get(line)
                if reveal:
                    s.known.add(reveal)  # §3.2 / R-06
                rd.shisshu_next = rd.hurt = rd.guard_trigger = True
                rd.o_event = "hit_player"
                ev.append({"kind": "refuted", "claim": claim_id, "line": line, "reveals": reveal})
            else:
                ev.append({"kind": "blocked", "claim": claim_id})
        else:
            if oa.kind == OA.PARRY:
                _heal_opp(s, ev)
            _player_attach(s, rd, claim_id, soph, crack, ev)
            if K.is_catch(claim_id):
                s.known.add(s.catch_card)  # §6.5: the caught line becomes known
            _claim_effect(s, rd, claim_id)
            if attacks:
                _opp_attach(s, rd, oa, ev)  # both attach: 破竹 kept, no gain (§7.2)
            else:
                rd.read_ok = True
                _reraise(s, ev)

    elif pa.kind == PA.INTERCEPT:
        claim_id, v, crack = _use_claim(s, rd, pa, "intercept", ev)
        c = ch.claims[claim_id]
        if attacks:
            cd = ch.cards[oa.card]
            blocked = s.no_intercept_round == r  # §6.3: "下回合對手的立論無法被截斷"
            if v.soph:
                ok = cd.issue == c.issue  # §6.4: 詭辯 succeeds on the same issue
            else:
                ok = cd.is_lie and claim_id in ch.breakers.get(oa.card, ())
            if ok and not blocked:
                dmg = INTERCEPT_DMG + (INTERCEPT_FORCE_EXTRA if oa.kind == OA.FORCE else 0.0)
                _hurt_opp(s, dmg, "intercept", ev)  # fixed damage: no 破竹 / 破防 (R-26)
                s.opp_combo = 0
                _remove_from_hand(s, oa.card)
                if cd.is_lie:
                    s.knocked.append(oa.card)
                    rd.knocked_lie = oa.card
                    rd.p_events.append(("lie_down_soph" if v.soph else "lie_down_proper", None))
                else:
                    s.denials += 1  # §6.4 否定事實
                    rd.p_events.append(("fact_down_soph", None))
                _set_broken(s, rd, "intercepted", ev)
                rd.read_ok = True
                # §7.3 抓漏洞; R-25 round-start state. SPEC-QUESTION, accepted by the design
                # owner (rules 0.6): a 詭辯 cut on the keystone triggers it under the same
                # conditions.
                if cd.keystone and (rd.broken_start or rd.opp_hp_start <= KEY_HP_RATIO * ch.opp_max_hp):
                    rd.key_ronpa = True
                ev.append({"kind": "intercept", "claim": claim_id, "card": oa.card, "ok": True,
                           "keystone": rd.key_ronpa})
                _claim_effect(s, rd, claim_id)
            else:
                # SPEC-QUESTION, accepted by the design owner (rules 0.6): a 詭辯 cut on
                # another issue fails like a wrong-claim cut: −5 and his node lands with
                # damage (also on a fact).
                rd.read_bad = rd.guard_trigger = True
                ev.append({"kind": "intercept", "claim": claim_id, "card": oa.card, "ok": False,
                           "blocked_by_parry": blocked})
                if cd.is_lie or blocked or v.soph:
                    _hurt_player(s, rd, WHIFF, "whiff", ev)
                    _opp_attach(s, rd, oa, ev)
                else:  # a fact: −10, his node lands, no 論證 (§6.4)
                    _hurt_player(s, rd, FACT_MISS, "fact_miss", ev)
                    _opp_attach(s, rd, oa, ev, damage=False)
                    if cd.kind == "unfav":
                        s.catch_next = None  # 錯過接話機會
        elif oa.kind == OA.REBUT:  # 互相落空
            rd.read_bad = rd.guard_trigger = True
            _hurt_player(s, rd, WHIFF, "whiff", ev)
            _hurt_opp(s, WHIFF, "whiff", ev)
            rd.o_event = "own_rebut_whiff"
            # SPEC-QUESTION: 互相落空 read as his 反駁落空 -> 破防 + his whiff event (§7.2
            # literal; sim/engine.py does the same).
            _set_broken(s, rd, "rebut_whiff", ev)
        else:  # vs 周旋
            rd.read_bad = rd.guard_trigger = True
            _hurt_player(s, rd, WHIFF, "whiff", ev)
            # SPEC-QUESTION: "下回合" read literally as the next round only (sim keeps it
            # until he next attacks).
            s.no_intercept_round = r + 1
            _heal_opp(s, ev)
            _reraise(s, ev)

    elif pa.kind == PA.DISMANTLE:
        claim_id, v, crack = _use_claim(s, rd, pa, "dismantle", ev)
        c = ch.claims[claim_id]
        node = next((n for n in s.opp_chain if n.card == pa.target), None)
        if node is None:
            raise IllegalAction(f"{pa.target} is not on his chain")
        cd = ch.cards[node.card]
        ok = (cd.issue == c.issue) if v.soph else (cd.is_lie and claim_id in ch.breakers.get(node.card, ()))
        if ok:
            s.opp_chain.remove(node)
            _hurt_opp(s, DISMANTLE_DMG, "dismantle", ev)
            s.opp_combo = 0  # R-02
            if cd.is_lie:
                s.knocked.append(node.card)
                rd.knocked_lie = node.card
                rd.p_events.append(("lie_down_soph" if v.soph else "lie_down_proper", None))
            else:
                s.denials += 1
                rd.p_events.append(("fact_down_soph", None))
            # SPEC-QUESTION, decided by the design owner (rules 0.6): a successful 拆台 is a
            # correct read only if he did not hurt the player this round (one definition,
            # §7.2). read_ok is set here; the 破竹/失守 step below requires `not rd.hurt`,
            # and read_bad stays False, so a 拆台 while his new node lands with damage holds
            # 破竹 (no add, no reset) and keeps 失守.
            rd.read_ok = True
            _claim_effect(s, rd, claim_id)
        else:
            rd.read_bad = rd.guard_trigger = True
            # E4 (design 3689f6d): a 詭辯 that misses costs −5 whatever the node is, on a
            # cut or a dismantle (otherwise the cost would tell the line's truth); −10 only
            # for a 正論 against a fact.
            _hurt_player(s, rd, FACT_MISS if (cd.is_fact and not v.soph) else WHIFF, "whiff", ev)
        ev.append({"kind": "dismantle", "claim": claim_id, "card": node.card, "ok": ok})
        if attacks:
            _opp_attach(s, rd, oa, ev)
        elif oa.kind == OA.REBUT:
            _hurt_opp(s, WHIFF, "whiff", ev)
            rd.o_event = "own_rebut_whiff"
            _set_broken(s, rd, "rebut_whiff", ev)
        else:
            _heal_opp(s, ev)
            _reraise(s, ev)

    else:  # 打迷糊仗
        repeat = s.stall_streak >= 2  # §6.3: from the 2nd in a row, no halving / 破防
        # SPEC-QUESTION (rules vs sim/engine.py): 被打迷糊仗 fires vs a rebuttal too, beside
        # his own 反駁落空 (one event per side, 01_numbers §2.5; ch §12.2 R2, §12.3 R2);
        # sim/engine.py gives only the whiff. On a repeat, no new 破防 (§6.3); sim/engine.py
        # line ~698 still sets it.
        rd.p_events.append(("stalled", None))
        if attacks:
            _opp_attach(s, rd, oa, ev, factor=1.0 if repeat else 0.5)
            rd.read_bad = True  # sim ASSUMPTION-11 (rules silent)
        elif oa.kind == OA.REBUT:
            _hurt_opp(s, WHIFF, "whiff", ev)  # sim ASSUMPTION-08: −5 kept on a repeat
            rd.o_event = "own_rebut_whiff"
            if not repeat:
                _set_broken(s, rd, "rebut_whiff", ev)
                rd.next_clear = True
                rd.read_ok = True
        else:
            # SPEC-QUESTION: 周旋 still heals and re-raises (§6.2); the duel cell only says
            # 雙方各 −3. sim/engine.py skips the heal here.
            _heal_opp(s, ev)
            _reraise(s, ev)
            _hurt_player(s, rd, STALEMATE, "stalemate", ev)
            _hurt_opp(s, STALEMATE, "stalemate", ev)
        if repeat:
            _hurt_player(s, rd, STALL_REPEAT_EXTRA, "stall_repeat", ev)
        ev.append({"kind": "stall", "vs": oa.kind.value, "repeat": repeat})

    # 援護 (§5.3 step 2)
    if pa.guard and rd.guard_trigger:
        s.player_hp = max(s.player_hp, rd.hp0)
        rd.shisshu_next = False
        ev.append({"kind": "guard_saved", "hp": s.player_hp})

    # 破竹 (§7.2, R-09) and 失守 (§7.2, V-11: cleared by the same "correct read")
    good_read = rd.read_ok and not rd.hurt
    before = s.hachiku
    if good_read:
        s.hachiku = min(HACHIKU_MAX, s.hachiku + 1)
    elif rd.read_bad:
        s.hachiku = 0
    if s.hachiku != before:
        ev.append({"kind": "hachiku", "before": before, "after": s.hachiku})
    if s.shisshu and good_read:
        s.shisshu = False
        ev.append({"kind": "shisshu", "on": False})
    if rd.shisshu_next:
        s.shisshu = True
        ev.append({"kind": "shisshu", "on": True})

    s.next_clear = rd.next_clear
    s.flag_player_soph = rd.player_soph
    s.flag_knocked_lie = rd.knocked_lie
    s.flag_hit_player = rd.o_event == "hit_player"
    s.rule3_pending = False

    _psych_step(s, rd, ev)
    if s.outcome:
        return
    _stance(s, rd, ev)


# --------------------------------------------------------------------------- psych (§8)


def _psych_step(s: State, rd: _Round, ev: list) -> None:
    """§5.3 step 4. One event per action (R-10): the player's action, then his action
    (01_numbers §2.5); scripted claim effects stack on a cut (§8.1 names cuts explicitly)."""
    table = s.ch.psych_events
    for name, delta in rd.p_events:
        _psych_add(s, name, delta if delta is not None else table[name], ev)
    if rd.o_event:
        _psych_add(s, rd.o_event, table[rd.o_event], ev)
    if not s.few_fired and few_options_count(s) <= FEW_OPTIONS_AT:
        s.few_fired = True  # ch §10: once per debate
        _psych_add(s, "few_options", table["few_options"], ev)
    thr = s.ch.psych_threshold
    for i in range(3):
        now = s.psych[i] >= thr[i]
        if now and not s.over[i]:
            s.crossed[i] = True
            ev.append({"kind": "threshold_crossed", "stat": STAT[i]})
            if not s.endgame:
                _set_broken(s, rd, f"crossed_{STAT[i]}", ev)  # §7.2
            if i == P:
                s.next_unfav = True  # §8.3: the next 立論 plays an unfavourable fact
        s.over[i] = now
    s.psych_end = tuple(s.psych)
    if s.psych[G] >= 100.0:
        # SPEC-QUESTION, accepted by the design owner (rules 0.6): a guilt confession is
        # grade 1 if c = 0, else 2.
        _win(s, 1 if s.cracks == 0 else 2, "confession", ev)


# --------------------------------------------------------------------------- stance (§5.3 step 5)


def _stance(s: State, rd: _Round, ev: list) -> None:
    ch = s.ch
    need, issues = ch.ronpa_len, ch.ronpa_issues
    ronpa = rd.key_ronpa or (
        rd.p_att and s.broken_now() and len(s.player_chain) >= need
        and len({n.issue for n in s.player_chain}) >= issues
    )
    # SPEC-QUESTION: §7.3 reverse ronpa is symmetric (2 issues too). Read literally, an unfavourable fact landing counts as
    # "接上一節" (sim/engine.py excludes it).
    rev = (
        rd.shisshu_start and rd.o_att and len(s.opp_chain) >= need
        and len({n.issue for n in s.opp_chain}) >= issues
    )
    if ronpa and rev:  # §7.3: the higher 論證 this round wins; tie -> player (sim)
        if rd.p_dmg >= rd.o_dmg:
            rev = False
        else:
            ronpa = False
    if rev:
        s.player_hp = 1.0
        s.player_combo = 0  # §5.1 (ch §12.4 R7 shows 3: SPEC-QUESTION)
        s.player_locked = True
        ev.append({"kind": "reverse_ronpa", "chain": [n.card for n in s.opp_chain]})
        return
    if s.player_hp <= 0 and s.opp_hp <= 0:
        s.both_zero = True  # §6.3: player wins, one grade lower (min 4)
        s.player_hp = 1.0
        _enter_endgame(s, "zero", ev)
    elif s.player_hp <= 0:
        _lose(s, "zero", ev)
    elif ronpa:
        ev.append({"kind": "ronpa", "via": "keystone" if rd.key_ronpa else "chain",
                   "chain": [n.claim for n in s.player_chain]})
        _enter_endgame(s, "ronpa", ev)
    elif s.opp_hp <= 0:
        _enter_endgame(s, "zero", ev)  # R-13


def _win(s: State, grade: int, reason: str, ev: list) -> None:
    if s.both_zero:
        grade = min(4, grade + 1)
    s.outcome, s.grade, s.end_reason = "win", grade, reason
    s.endgame = None
    ev.append({"kind": "debate_over", "outcome": "win", "grade": grade, "reason": reason})


def _lose(s: State, reason: str, ev: list) -> None:
    s.player_hp = max(0.0, s.player_hp)
    s.outcome, s.grade, s.end_reason = "loss", 5, reason
    s.endgame = None
    ev.append({"kind": "debate_over", "outcome": "loss", "grade": 5, "reason": reason})


def _enter_endgame(s: State, trigger: str, ev: list) -> None:
    """§7.4: ronpa or zero lock him at 1; his chain is destroyed on a ronpa (destroyed nodes
    never return, §6.2). The last card, if any, is played next round."""
    if trigger == "ronpa":
        s.opp_chain = []
        s.ronpa_done = True
    s.opp_combo = 0
    hp_end = 1.0 if trigger == "ronpa" else 0.0
    c = s.cracks
    ev.append({"kind": "endgame", "trigger": trigger, "cracks": c})
    if s.last_card_used:  # no last card left: this ends it (§7.4 last bullet)
        s.opp_hp = hp_end
        # a used last card always hit (an intercepted one ends the debate)
        _win(s, 3 if s.ronpa_done else 4, f"second_{trigger}", ev)
    elif s.over[G]:  # gives up (§7.4, §8.3)
        s.opp_hp = hp_end
        _win(s, (1 if c == 0 else 2) if trigger == "ronpa" else 4, "surrender", ev)
    elif c == 0 and not s.picked:
        if s.scripted_last is None:
            s.opp_hp = hp_end
            _win(s, 1 if trigger == "ronpa" else 4, "clean", ev)
        else:
            # 垂死反撲 (R-14). SPEC-QUESTION (rules silent, engine vs chapter): played as its
            # own round (ch §12.1 R9); sim/engine.py resolves it inside the ronpa round.
            s.opp_hp = 1.0
            s.endgame = {"trigger": trigger, "card": s.scripted_last, "dying": True}
    else:
        card = s.reserved_last or s.scripted_last
        s.opp_hp = 1.0
        if card is None:
            s.opp_hp = hp_end
            _win(s, (1 if c == 0 else 2) if trigger == "ronpa" else 4, "no_last_card", ev)
        else:
            s.endgame = {"trigger": trigger, "card": card, "dying": False}


# --------------------------------------------------------------------------- endgame round (§7.4)


def _endgame_round(s: State, rd: _Round, pa: PlayerAction, oa: OpponentAction, ev: list) -> None:
    ch = s.ch
    eg = s.endgame
    card = eg["card"]
    if oa.kind != OA.LAST or oa.card != card:
        raise IllegalAction(f"endgame round: he plays {card}")
    if pa.kind not in (PA.CUT, PA.ACCEPT):
        raise IllegalAction("endgame round: cut or accept only (R-03)")
    s.opp_history.append(OA.LAST)
    c0 = s.cracks
    ronpa = eg["trigger"] == "ronpa"
    bad_cut = False
    if pa.kind == PA.CUT:
        claim_id, v, _ = _use_claim(s, rd, pa, "cut", ev)
        if claim_id in ch.breakers.get(card, ()):
            ev.append({"kind": "last_card", "card": card, "cut": True})
            if eg["dying"]:
                _win(s, 1 if ronpa else 4, "dying_cut", ev)
            else:
                _win(s, (1 if c0 == 0 else 2) if ronpa else 4, "last_card_cut", ev)
            s.psych_end = tuple(s.psych)
            return
        bad_cut = True
    if bad_cut:
        _hurt_player(s, rd, LAST_BAD_CUT, "bad_cut", ev)
    rd.o_event = "hit_player"
    if eg["dying"]:  # hits for 10, no heal, grade unchanged (R-14)
        _hurt_player(s, rd, DYING_DMG, "dying", ev)
        ev.append({"kind": "last_card", "card": card, "cut": False, "dying": True})
        _psych_step(s, rd, ev)
        if s.player_hp <= 0:
            _lose(s, "dying", ev)  # sim ASSUMPTION-32
        elif not s.outcome:
            _win(s, 1 if ronpa else 4, "dying_hit", ev)
        return
    # SPEC-QUESTION: c is not reset after the last card (sim ASSUMPTION-10 resets it); §10
    # reputation counts every crack on the record (ch §12.3 結算: 3 cracks).
    s.last_card_used = True
    s.reversed = True
    removed = [n.claim for n in s.player_chain if n.cracked]
    s.player_chain = [n for n in s.player_chain if not n.cracked]
    s.knocked_claims.update(removed)
    s.player_combo = 0
    s.hachiku = 0  # V-07
    s.broken_until = 0  # sim/engine.py (rules silent)
    picked = ch.cards[card].kind == "pickup"
    extra = LAST_PICKED_EXTRA if picked else 0.0
    if c0 == 0:
        dmg, heal = LAST_ZERO_C_DMG + extra, LAST_ZERO_C_HEAL
    else:
        dmg, heal = LAST_PER_CRACK * c0 + extra, min(LAST_HEAL_CAP, LAST_HEAL_PER_CRACK * c0)
    _hurt_player(s, rd, dmg, "last_card", ev)
    if s.over[P]:
        # SPEC-QUESTION: §8.3 困獸 voids "可信度回復類效果"; read as also voiding this
        # recovery (he stays at 1, unlocked).
        ev.append({"kind": "heal_void"})
    else:
        s.opp_hp = ch.opp_max_hp * heal
    s.endgame = None
    ev.append({"kind": "last_card", "card": card, "cut": False, "removed": removed,
               "damage": dmg, "opp_hp": s.opp_hp})
    s.flag_hit_player = True
    s.flag_player_soph = rd.player_soph
    s.flag_knocked_lie = None
    _psych_step(s, rd, ev)
    if s.player_hp <= 0 and not s.outcome:
        _lose(s, "last_card", ev)


# --------------------------------------------------------------------------- §7.5 round


def _last_stand(s: State, rd: _Round, pa: PlayerAction, oa: OpponentAction, ev: list) -> None:
    ch = s.ch
    if oa.kind != OA.NONE:
        raise IllegalAction("§7.5: he does not act")
    s.opp_history.append(OA.NONE)
    if pa.kind == PA.ACCEPT:
        _lose(s, "no_last_stand", ev)
        return
    if pa.kind != PA.LAST_STAND:
        raise IllegalAction("§7.5: last stand or accept only")
    v = K.view(s, pa.claim)
    if not v.available:
        raise IllegalAction(f"claim {pa.claim} is not available")
    s.record.append(RecordEntry(rd.r, pa.claim, "last_stand", v.soph, v.red_crack, v.true))
    if v.red_crack:
        s.cracks += 1

    def breaks(n):
        cd = ch.cards[n.card]
        return cd.is_lie and pa.claim in ch.breakers.get(n.card, ())

    nodes = [n for n in s.opp_chain if n.card == pa.target] if pa.target else s.opp_chain
    hit = next((n for n in nodes if breaks(n)), None)
    if v.soph or hit is None:
        ev.append({"kind": "last_stand", "claim": pa.claim, "target": pa.target, "ok": False})
        s.player_hp = 0.0
        _lose(s, "last_stand_failed", ev)
        return
    idx = s.opp_chain.index(hit)
    destroyed = [n.card for n in s.opp_chain[idx:]]
    del s.opp_chain[idx:]
    s.opp_combo = 0
    s.player_hp = ch.player_max_hp * COMEBACK_RATIO
    s.player_locked = False
    ev.append({"kind": "last_stand", "claim": pa.claim, "target": hit.card, "ok": True,
               "destroyed": destroyed, "hp": s.player_hp})
    if v.red_crack:  # V-12: back to 30%, then −10 (E8 design ruling: told as two steps, the −10 as a red crack)
        _hurt_player(s, rd, CONTRADICTION, "contradiction", ev)
    rd.p_events.append(("lie_down_proper", None))
    s.flag_player_soph = False
    s.flag_knocked_lie = None
    s.flag_hit_player = False
    _psych_step(s, rd, ev)


# --------------------------------------------------------------------------- entry point


def _begin_round(s: State) -> None:
    """Start of round s.round: natural decay (R-11, not in round 1); a state over its
    threshold ends once it falls below (§8.3)."""
    if s.round > 1:
        for i in range(3):
            s.psych[i] = max(0.0, s.psych[i] - s.ch.psych_decay[i])
            s.over[i] = s.psych[i] >= s.ch.psych_threshold[i]
    s.catch_card, s.catch_next = s.catch_next, None


def resolve_round(state: State, pa: PlayerAction, oa: OpponentAction) -> tuple[State, list]:
    if state.outcome:
        raise IllegalAction("the debate is over")
    s = deepcopy(state)
    rd = _Round(s)
    ev: list = [{"kind": "round", "round": s.round}]
    if s.player_locked:
        _last_stand(s, rd, pa, oa, ev)
    elif s.endgame:
        _endgame_round(s, rd, pa, oa, ev)
    else:
        _normal_round(s, rd, pa, oa, ev)
    # rule ③ (ch §11): first time <= 50%; the ronpa lock at 1 never counts (V-04)
    if (not s.outcome and not s.endgame and not s.rule3_fired
            and s.opp_hp <= s.ch.rule3_hp_ratio * s.ch.opp_max_hp):
        s.rule3_fired = s.rule3_pending = True
        ev.append({"kind": "rule3_armed"})
    if not s.outcome and s.round >= s.ch.max_rounds:
        # design-owner ruling: the audience leaves; higher credibility % wins, grade 4 at best
        mine = s.player_hp / s.ch.player_max_hp
        his = s.opp_hp / s.ch.opp_max_hp
        if mine > his:
            _win(s, 4, "round_limit", ev)
        else:
            _lose(s, "round_limit", ev)
    s.round += 1
    if not s.outcome:
        _begin_round(s)
    return s, ev
