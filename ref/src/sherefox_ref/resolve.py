"""resolve_round: one simultaneous round, settled in 系統規格 A-1 order.

    1 節點變化 -> 2 對手受傷 (+論破) -> 3 玩家受傷 -> 4 補強回復 -> 5 狀態
    (6 決定下一手 lives in policy.py), then the A-1 step-1 restate for the next round.

The restate (重述) of round r+1 is performed at the end of resolve_round(r) so that the
state between rounds is exactly the board the player sees under the next tell.
"""

from __future__ import annotations

from dataclasses import replace

from . import events as E
from .model import (
    ATTACKS,
    BREAKER,
    OA,
    PA,
    CAT_PERSON,
    CAT_SCANDAL,
    BoardNode,
    DebateState,
    OpponentAction,
    PlayerAction,
    RoundLog,
    tag_category,
)
from .rules import (
    IllegalAction,
    break_threshold_met,
    chain_damage_breakdown,
    claim_damage,
    count_links,
    counter_damage,
    segment_links,
    segment_tags,
)

# 系統規格 4.7 大字一覽: full-screen priorities (smaller plays first).
FULL_PRIORITY = {
    "CUT_DOUBLE": 1,
    "CUT_COUNTER": 2,
    "CUT_RONPA": 3,
    "CUT_REVERSE": 4,
    "CUT_BRINK": 5,
    "CUT_SHAKEN": 6,
    "CUT_KONJU": 7,
    "CUT_SHISSHU": 8,
    "CUT_HACHIKU3": 9,
}


# --------------------------------------------------------------------------- helpers


def _visible_nodes(state: DebateState) -> tuple[str, ...]:
    return state.node_ids()


def _recover_one(state_nodes, removed, case, cause, ev):
    """A-2 回復來源: hand (missed evidence; not modelled for Ch.1-3 fixtures, which
    assume full collection) -> removed script nodes. 'Last stand' when nothing else.
    Several removed script nodes come back in node-pool order (ruling B19)."""
    normal = [n for n in state_nodes if n.kind != "fragile"]
    if len(normal) >= case.node_cap:
        return state_nodes, removed
    pool_ids = [n.id for n in case.node_pool]
    candidates = [nid for nid in pool_ids if nid in removed]
    if candidates:
        nid = candidates[0]
        removed = tuple(r for r in removed if r != nid)
        ev.append(E.NodeAdded(nid, "normal", cause))
        return state_nodes + (BoardNode(nid),), removed
    if not normal:
        ev.append(E.NodeAdded("LAST_STAND", "last_stand", cause))
        return state_nodes + (BoardNode("LAST_STAND", "last_stand"),), removed
    return state_nodes, removed


def _remove_node(nodes, removed, nid, cause, ev, track=True):
    nodes = tuple(n for n in nodes if n.id != nid)
    if track and not nid.startswith("F") and nid not in ("LAST_STAND",):
        removed = removed + (nid,)
    ev.append(E.NodeRemoved(nid, cause))
    return nodes, removed


def _staging(pa: PlayerAction, oa: OpponentAction) -> str:
    p_atk = pa.kind in (PA.SOLID, PA.SOPHISTRY)
    o_atk = oa.kind in ATTACKS
    if p_atk and o_atk:
        return "clash"
    if p_atk:
        return "player_attack_vs_defense"
    if o_atk:
        return "defense_vs_attack"
    return "standoff"


def _finalize_cutins(raw: list) -> list:
    """4.7 優先順序與佇列: at most one full-screen cut-in per round (smallest priority);
    the others become stamps in order of occurrence. Same stamp at most once per round."""
    fulls = [e for e in raw if isinstance(e, E.CutIn) and e.level == "full"]
    play = min(fulls, key=lambda e: e.priority) if fulls else None
    out, seen_stamps = [], set()
    for e in raw:
        if isinstance(e, E.CutIn):
            if e.level == "full":
                if e is play:
                    out.append(replace(e, played_full=True))
                else:
                    out.append(replace(e, level="stamp", demoted=True))
                continue
            if e.id in seen_stamps:
                continue
            seen_stamps.add(e.id)
        out.append(e)
    return out


def _cut(cid: str, side: str | None) -> E.CutIn:
    return E.CutIn(cid, "full", FULL_PRIORITY[cid], side)


def _stamp(cid: str, side: str | None) -> E.CutIn:
    return E.CutIn(cid, "stamp", None, side)


# --------------------------------------------------------------------------- validation


def _parry_refutes(state: DebateState, pa: PlayerAction, node_id: str) -> bool:
    case = state.case
    nd = case.node_def(node_id)
    if pa.segment:
        return any(c in nd.refuters for c in pa.segment)
    return pa.card is not None and pa.card in nd.refuters


def _validate(state: DebateState, pa: PlayerAction, oa: OpponentAction, break_round: bool):
    case = state.case
    if pa.assist and state.assist_left <= 0:
        raise IllegalAction("assist already spent")
    if oa.kind in ATTACKS and oa.lit not in _visible_nodes(state):
        raise IllegalAction(f"opponent attacks node {oa.lit} that is not on the board")
    if oa.kind not in case.opponent.available and not oa.scripted:
        raise IllegalAction(f"{case.opponent.name} cannot use {oa.kind}")
    links = []
    if pa.kind in (PA.SOLID, PA.SOPHISTRY):
        if pa.kind == PA.SOPHISTRY and not case.sophistry_unlocked:
            # Ruling B20: 詭辯 is usable in Ch.2-3; only the 破竹 read-right table treats it
            # as locked before Ch.4.
            pass
        links = segment_links(state, pa.segment)
        s, p = count_links(links)
        if pa.kind == PA.SOLID and p:
            raise IllegalAction("MSG_DEB_NOSOLID: segment has a sophistry link")
        if pa.kind == PA.SOPHISTRY and not p:
            raise IllegalAction("MSG_DEB_NOSOPH: segment has no sophistry link")
        target = pa.target or oa.lit
        if target not in _visible_nodes(state):
            raise IllegalAction(f"target {target} not visible")
        tnode = next(n for n in state.nodes if n.id == target)
        if tnode.kind != "fragile":
            if not (segment_tags(case, pa.segment) & set(case.node_def(target).tags)):
                raise IllegalAction("MSG_DEB_NOTAG")
    elif pa.kind == PA.PARRY:
        if case.shissu_enabled and state.shissu_left > 0:
            raise IllegalAction("MSG_DEB_NOPARRY_SHISSHU")
        if oa.lit is None:
            raise IllegalAction("parry needs a lit node")
        if pa.segment:
            if not (break_round or state.in_tail):
                raise IllegalAction("a chain can be chosen for parry only in the break round / tail")
            links = segment_links(state, pa.segment)
        elif pa.card is None or pa.card not in state.board.all_cards():
            raise IllegalAction("parry needs a card")
        # A-5 / 4.x parry picker: only appraised cards are listed (數值總表 五:
        # 「R1 反駁需要已鑑定的 E02_02」).
        for cid in pa.segment or (pa.card,):
            if not case.card(cid).fully_revealed:
                raise IllegalAction(f"UI_DEB_NOPARRY_NOCARD: {cid} is not appraised")
        if not _parry_refutes(state, pa, oa.lit):
            raise IllegalAction("UI_DEB_NOPARRY_NOCARD: no refuter of the lit node")
    return links


# --------------------------------------------------------------------------- main


def resolve_round(
    state: DebateState, pa: PlayerAction, oa: OpponentAction
) -> tuple[DebateState, list]:
    if state.over:
        raise IllegalAction("debate is over")
    if state.in_tail:
        return _resolve_tail(state, pa, oa)

    case = state.case
    hp_model = case.player_max_hp is not None
    break_round = state.shaken == "armed"
    links = _validate(state, pa, oa, break_round)
    ev: list = []
    r = state.round

    hk_on = case.hachiku_mode == "on"
    stacks = state.hachiku if hk_on else 0
    n_start = state.normal_node_count()
    o_atk = oa.kind in ATTACKS
    in_shissu = case.shissu_enabled and state.shissu_left > 0
    konju_active = case.konju_enabled and state.konju_left > 0

    nodes, removed = state.nodes, state.removed
    php, ohp = state.player_hp, state.opp_hp
    fragile_seq = state.fragile_seq
    infamy = state.infamy
    assist_left = state.assist_left
    snapped = tuple((l, u) for l, u in state.snapped if u >= r)
    contradictions = state.contradictions
    golden_used = state.golden_used
    break_label = state.break_label

    ev.append(E.Reveal(r, pa.kind.value, oa.kind.value, _staging(pa, oa)))

    # 援護 is spent at lock, trap or not (A-7, 4.4)
    if pa.assist:
        assist_left -= 1

    is_attack = pa.kind in (PA.SOLID, PA.SOPHISTRY)
    trapped = pa.kind == PA.SOPHISTRY and oa.kind == OA.TRAP
    hit = is_attack and not trapped  # A-4 「打中」: valid segment shown, not trap-voided
    intercept = pa.kind == PA.PARRY and o_atk  # Ch.1-3: attacks always target the lit node
    target = (pa.target or oa.lit) if is_attack else None
    s_links, p_links = count_links(links)

    # ---- break attempt (A-8) -------------------------------------------------------
    break_attempt = False
    break_ok = False
    break_via = None
    if break_round and pa.kind == PA.SOLID:
        break_attempt = break_threshold_met(state, pa.segment, links)
        break_ok = break_attempt
        break_via = "solid"
    elif break_round and pa.kind == PA.PARRY and pa.segment:
        break_attempt = break_threshold_met(state, pa.segment, links)
        if not break_attempt:
            raise IllegalAction("parry-break chain does not meet the break threshold")
        break_ok = intercept
        break_via = "parry"

    # ---- step 1: node changes -------------------------------------------------------
    fragile_consumed = False
    removed_claim_nodes: list[str] = []
    if hit:
        fr = [n for n in nodes if n.kind == "fragile"]
        if fr:
            # Ruling B6: the next attack that hits consumes one fragile node (+10).
            nodes, removed = _remove_node(nodes, removed, fr[0].id, "fragile_hit", ev, track=False)
            fragile_consumed = True
    if pa.kind == PA.SOLID and not break_ok:
        tdef_ref = case.node_def(target).refuters if target and not target.startswith("F") else frozenset()
        limit = 2 if len(pa.segment) >= 4 else 1
        removed_n = 0
        if target in [n.id for n in nodes] and any(c in tdef_ref for c in pa.segment):
            nodes, removed = _remove_node(nodes, removed, target, "chain", ev)
            removed_claim_nodes.append(target)
            removed_n += 1
            # SPEC-QUESTION: with >=4 cards A-2 removes "目標節點＋另一個" node. Implemented
            # only as an addition to a removed target (the conservative reading); the
            # choice among several candidates follows board order.
            if removed_n < limit:
                for n in list(nodes):
                    if n.kind == "normal" and any(c in case.node_def(n.id).refuters for c in pa.segment):
                        nodes, removed = _remove_node(nodes, removed, n.id, "chain", ev)
                        removed_claim_nodes.append(n.id)
                        break
    if intercept and not break_ok:
        nodes, removed = _remove_node(nodes, removed, oa.lit, "parry", ev)
        removed_claim_nodes.append(oa.lit)
    if pa.kind == PA.OBSERVE and oa.kind in (OA.REINFORCE, OA.TRAP):
        fragile_seq += 1
        fid = f"F{fragile_seq}"
        nodes = nodes + (BoardNode(fid, "fragile"),)
        ev.append(E.NodeAdded(fid, "fragile", "observe"))
    if oa.kind == OA.REINFORCE:
        nodes, removed = _recover_one(nodes, removed, case, "reinforce", ev)

    # Ch.1 contradiction counter (A-13): parry cutting a claim, or a solid chain against a
    # reinforce, that removes a node, counts 1 each.
    # SPEC-QUESTION: whether re-removing a node that came back via restate counts again is
    # unspecified; implemented: every qualifying removal counts.
    if case.contradiction_target is not None and not break_ok:
        if (intercept and oa.lit in removed_claim_nodes) or (
            pa.kind == PA.SOLID and oa.kind == OA.REINFORCE and removed_claim_nodes
        ):
            contradictions += 1
            ev.append(E.ContradictionCounted(contradictions, removed_claim_nodes[0]))

    # stamps for the reveal
    if is_attack and o_atk:
        ev.append(_stamp("STAMP_CLASH", None))
    if intercept:
        ev.append(_stamp("STAMP_PARRY", "player"))
    if pa.kind == PA.PARRY and not o_atk:
        # SPEC-QUESTION: parry vs trap is a double whiff; 4.7 says "兩次落空只蓋一枚" but not
        # on which side. Implemented: one stamp on the player's side.
        ev.append(_stamp("STAMP_WHIFF", "player"))
    elif pa.kind == PA.SOLID and oa.kind == OA.TRAP:
        ev.append(_stamp("STAMP_WHIFF", "opponent"))

    # ---- step 2: damage to the opponent --------------------------------------------
    opp_zero = False
    if is_attack and not trapped:
        half = o_atk or (pa.kind == PA.SOLID and oa.kind == OA.REINFORCE and not break_ok)
        # Ruling B7: a solid-chain break is exempt from the 補強 halving only; the clash x0.5
        # against an attack still applies (Ch.2 mistake variant: 15.75).
        dmg, steps = chain_damage_breakdown(
            s_links, p_links, break_round, stacks, half, fragile_consumed
        )
    elif intercept:
        dmg, steps = counter_damage(stacks)
    else:
        dmg, steps = 0.0, ()
    if hp_model and dmg:
        before = ohp
        ohp = ohp - dmg
        ev.append(E.DamageToOpponent(dmg, "chain" if is_attack else "counter", before, ohp, steps))
    if break_ok:
        nodes_ids = [n.id for n in nodes]
        for nid in nodes_ids:
            nodes, removed = _remove_node(nodes, removed, nid, "break", ev, track=False)
        removed = ()
        label = None
        gu = ()
        seg = pa.segment or ((pa.card,) if pa.card else ())
        golden = tuple(c for c in seg if case.card(c).is_golden)
        if case.golden_primary:
            # Ruling B17: the secondary route (E03_02 -> E03_03) is allowed while G-01 is held;
            # any break meeting the early threshold is accepted and only labelled.
            label = "primary" if case.golden_primary <= set(seg) else "alternative"
            gu = golden if label == "primary" else ()
        else:
            gu = golden
        golden_used = golden_used + tuple(g for g in gu if g not in golden_used)
        break_label = label
        ev.append(E.BreakResult(True, break_via, label, gu))
        ev.append(_cut("CUT_RONPA", "player"))
        if hp_model:
            before = ohp
            amount = case.opp_max_hp * case.break_pct / 100
            # Ruling B8: in the break round the result after the chain/counter and the break
            # deduction is floored at 1 even when the chain alone reached <= 0; the
            # opponent's attack still resolves (step 3), then the tail starts.
            ohp = max(1.0, ohp - amount)
            ev.append(E.DamageToOpponent(amount, "break", before, ohp, (("break_pct", case.break_pct),)))
    elif hp_model and ohp is not None and ohp <= 0:
        opp_zero = True  # early culprit may be zeroed directly (A-8 last bullet)
        ohp = 0.0
    elif break_round and pa.kind == PA.PARRY and pa.segment and not intercept:
        ev.append(E.BreakResult(False, "parry"))
        ev.append(E.Message("MSG_DEB_PARRY_BREAK_MISS"))

    # ---- step 3: damage to the player ---------------------------------------------
    full_rush_taken = False
    trap_crit = False
    assisted = state.assisted_links
    if not opp_zero:
        if o_atk and not intercept:
            dmg_p, steps_p = claim_damage(
                case, n_start, oa.kind == OA.RUSH, konju_active, r, pa.kind == PA.OBSERVE
            )
            full_rush_taken = oa.kind == OA.RUSH and pa.kind != PA.OBSERVE
            if hp_model:
                before = php
                php = php - dmg_p
                ev.append(
                    E.DamageToPlayer(dmg_p, "rush" if oa.kind == OA.RUSH else "claim", before, php, steps_p)
                )
        if trapped:
            ev.append(_stamp("STAMP_TRAP", "player"))
            soph = [(a, b) for a, b, k in links if k == "sophistry"]
            unassisted = [l for l in soph if frozenset(l) not in state.assisted_links]
            if pa.assist and unassisted:
                # A-7: assist blocks the crit; the caught link becomes 'assisted'.
                # SPEC-QUESTION: "最後建立的" link order is not in the data; the last link in
                # segment order is taken as the most recently created.
                caught = unassisted[-1]
                ev.append(E.Message("ASSIST_BLOCKED"))
                ev.append(_stamp("STAMP_ASSIST", "player"))
                assisted = state.assisted_links | {frozenset(caught)}
            elif unassisted:
                caught = unassisted[-1]
                trap_crit = True
                if hp_model:
                    before = php
                    php = php - 25
                    ev.append(E.DamageToPlayer(25.0, "trap_crit", before, php, (("crit", 25.0),)))
                snapped = snapped + ((frozenset(caught), r + 1),)
                ev.append(E.LinkSnapped(caught[0], caught[1], r + 1))
                ev.append(E.InfamyChanged(infamy, infamy + 1))
                infamy += 1
            # else: every sophistry link already assisted -> voided, no crit, no infamy
        if pa.assist and oa.kind != OA.TRAP:
            ev.append(E.Message("MSG_DEB_ASSIST_WASTED"))
    if pa.assist:
        ev.append(E.AssistSpent(wasted=oa.kind != OA.TRAP))
    assisted_links = assisted

    # ---- step 4: reinforce recovery -------------------------------------------------
    reinforce_success = oa.kind == OA.REINFORCE and not hit
    if hp_model and reinforce_success and not opp_zero:
        before = ohp
        ohp = min(case.opp_max_hp, ohp + case.opp_max_hp / 10)
        ev.append(E.OpponentHealed(ohp - before, before, ohp))

    # ---- ends --------------------------------------------------------------------------
    over = False
    outcome = state.outcome
    end_reason = None
    if opp_zero:
        over, outcome, end_reason = True, "win", "opponent_zero"
    elif hp_model and php is not None and php <= 0:
        over, outcome, end_reason = True, "loss", "player_zero"

    # ---- step 5: statuses -----------------------------------------------------------
    shaken_trigger = False
    scandal_trigger = False
    if not over:
        if case.contradiction_target is not None:
            # Ch.1 shaken comes only from contradictions (A-13): the 2nd one, and after a
            # missed break round every later one (ruling B21). The generic A-8 triggers are
            # not applied to the tutorial debate.
            if contradictions > state.contradictions and contradictions >= case.contradiction_target:
                shaken_trigger = True
        else:
            if intercept and oa.kind == OA.RUSH:
                shaken_trigger = True
            if pa.kind == PA.SOLID and hit and target and not target.startswith("F"):
                tdef = case.node_def(target)
                if any(case.card(c).is_scandal for c in pa.segment) and (
                    {tag_category(t) for t in tdef.tags} & {CAT_PERSON, CAT_SCANDAL}
                ):
                    shaken_trigger = True
                    scandal_trigger = True
                if len(pa.segment) >= 4:
                    if case.breakline_pct is None or ohp <= case.opp_max_hp * case.breakline_pct / 100:
                        # SPEC-QUESTION: breakline checked on HP after this hit (mid/late only).
                        shaken_trigger = True
            if is_attack and hit and any(BREAKER in case.card(c).flags for c in pa.segment):
                shaken_trigger = True

    shaken = state.shaken
    in_tail = False
    tail_left = 0
    if over:
        pass
    elif break_ok:
        shaken = "held"
    elif break_round:
        if shaken_trigger:
            shaken = "armed"  # A-8: re-trigger in the break round restarts the count
        else:
            shaken = "none"
            ev.append(E.StatusLost("shaken", "opponent", "break_round_passed"))
    elif shaken_trigger:
        shaken = "armed"
    if shaken_trigger and not break_ok and not over:
        ev.append(E.StatusGained("shaken", "opponent", 2))
        ev.append(_cut("CUT_SHAKEN", "opponent"))

    # 失守 -> 破竹 -> 困獸 (A-15 order)
    shissu_left = state.shissu_left
    shissu_trigger = False
    if case.shissu_enabled and not over:
        if break_ok:
            if shissu_left:
                ev.append(E.StatusLost("shissu", "player", "break"))
            shissu_left = 0
        else:
            shissu_trigger = (full_rush_taken and is_attack) or trap_crit
            if shissu_trigger:
                shissu_left = 1
                ev.append(E.StatusGained("shissu", "player", 1))
                ev.append(_cut("CUT_SHISSHU", "player"))
            elif shissu_left:
                shissu_left -= 1
                if not shissu_left:
                    ev.append(E.StatusLost("shissu", "player", "expired"))

    hachiku = state.hachiku
    if case.hachiku_mode in ("on", "preview") and not over:
        if o_atk:
            right = intercept or (in_shissu and pa.kind == PA.OBSERVE)
        elif oa.kind == OA.REINFORCE:
            right = (pa.kind == PA.SOPHISTRY and case.sophistry_unlocked) or pa.kind == PA.OBSERVE
        else:  # trap
            right = pa.kind in (PA.SOLID, PA.OBSERVE)
        right = right or scandal_trigger or break_ok
        new = min(3, hachiku + 1) if right else 0
        if shissu_trigger:
            new = 0
        preview = case.hachiku_mode == "preview"
        # SPEC-QUESTION: Ch.1 shows a 破竹 gauge "作為預覽"; whether preview stacks get stamps
        # is unstated. Implemented: HachikuChanged(preview=True) only, no cut-ins.
        ev.append(E.HachikuChanged(hachiku, new, preview))
        if not preview:
            if new > hachiku:
                if new == 3:
                    ev.append(_cut("CUT_HACHIKU3", "player"))
                else:
                    ev.append(_stamp(f"STAMP_HACHIKU{new}", "player"))
            elif new < hachiku:
                # 「斷」 small stamp; 4.7 gives it no ID.
                ev.append(_stamp("STAMP_HACHIKU_LOST", "player"))
        hachiku = new

    parry_count = state.parry_count + (1 if intercept else 0)
    konju_left = state.konju_left
    konju_parry_used, konju_hp_used = state.konju_parry_used, state.konju_hp_used
    if case.konju_enabled and not over:
        was_active = konju_left > 0
        if break_ok:
            if konju_left:
                ev.append(E.StatusLost("konju", "opponent", "break"))
            konju_left = 0
            # A-15: conditions met in the break round neither trigger nor are consumed.
        else:
            if was_active:
                konju_left -= 1
                if not konju_left:
                    ev.append(E.StatusLost("konju", "opponent", "expired"))
            # SPEC-QUESTION: "不占用該條件" after a break-round coincidence implies the
            # condition stays available; implemented as level checks (>=2 intercepts,
            # HP <= 30%) gated by per-debate 'used' flags. Meeting a condition while 困獸 is
            # active has no effect and does not consume it.
            cond_parry = parry_count >= 2 and not konju_parry_used
            cond_hp = (
                hp_model and ohp <= case.opp_max_hp * 30 / 100 and not konju_hp_used
            )
            if (cond_parry or cond_hp) and not was_active:
                konju_left = 2
                konju_parry_used = konju_parry_used or cond_parry
                konju_hp_used = konju_hp_used or cond_hp
                ev.append(E.StatusGained("konju", "opponent", 2))
                ev.append(_cut("CUT_KONJU", "opponent"))

    # behaviour-rule memory (A-3); scripted rounds do not trigger rules (A-11)
    rule3_fired, rule3_pending = state.rule3_fired, state.rule3_pending
    if not oa.scripted:
        last_node_removed = bool(removed_claim_nodes) or (break_ok and bool(state.nodes))
        # Ruling B14: removing a fragile node does not trigger rule 1.
        last_reinforce_success = reinforce_success
        no_reinforce_next = pa.kind == PA.SOLID and oa.kind == OA.TRAP
        must_attack_next = pa.kind == PA.OBSERVE and oa.kind == OA.TRAP
        if hp_model and not rule3_fired and ohp is not None and ohp <= case.opp_max_hp / 2:
            # Ruling B9 / 數值總表 四: the first time <= 50%.
            rule3_fired = True
            rule3_pending = True
            # SPEC-QUESTION: when this first happens in a break round, the forced rush is
            # pre-empted by the scripted tail; the model keeps it pending (it fires after a
            # voided break). Whether it is lost instead is unspecified.
    else:
        last_node_removed = state.last_node_removed
        last_reinforce_success = state.last_reinforce_success
        no_reinforce_next = state.no_reinforce_next
        must_attack_next = state.must_attack_next
    next_clear = "observe" if (pa.kind == PA.OBSERVE and o_atk) else None

    # Ch.1 end conditions (rulings A4, B21, D15): 2 contradictions by the end of round 3,
    # then the break; a missed break round can be re-entered after the next contradiction;
    # no break by the end of round 6 -> 未達成. There is no loss.
    if case.contradiction_target is not None and not over:
        if break_ok:
            over, outcome, end_reason = True, "win", "break"
        elif r >= case.contradiction_deadline and contradictions < case.contradiction_target:
            over, outcome, end_reason = True, "unachieved", "contradiction_deadline"
        elif case.round_cap is not None and r >= case.round_cap:
            over, outcome, end_reason = True, "unachieved", "round_cap"

    # tail start (A-9)
    if break_ok and case.tail is not None and not over:
        in_tail = True
        tail_left = case.tail_rounds
    elif break_ok and case.tail is None and not over:
        over, outcome, end_reason = True, "win", "break_no_tail"

    if over:
        ev.append(E.DebateEnded(outcome, end_reason))

    # ---- restate for the next round (A-1 step 1) ------------------------------------
    if not over:
        if in_tail:
            sc = case.tail.second_claim
            nodes = (BoardNode(sc.id, "second_claim"),)
            ev.append(E.TailStarted(tail_left, sc.id))
            ev.append(E.NodeAdded(sc.id, "second_claim", "tail_start"))
            ev.append(E.StatusGained("tail", "opponent", tail_left))
            if case.shissu_enabled and shissu_left:
                shissu_left = 0
                ev.append(E.StatusLost("shissu", "player", "tail_start"))
        else:
            nodes, removed = _recover_one(nodes, removed, case, "restate", ev)

    ev = _finalize_cutins(ev)
    new_state = replace(
        state,
        round=r + 1,
        player_hp=php,
        opp_hp=ohp,
        nodes=nodes,
        removed=removed,
        fragile_seq=fragile_seq,
        shaken=shaken,
        in_tail=in_tail,
        tail_rounds_left=tail_left,
        hachiku=hachiku,
        konju_left=konju_left,
        konju_parry_used=konju_parry_used,
        konju_hp_used=konju_hp_used,
        parry_count=parry_count,
        shissu_left=shissu_left,
        assist_left=assist_left,
        infamy=infamy,
        snapped=snapped,
        assisted_links=assisted_links,
        opp_history=state.opp_history + (oa.kind,),
        last_player_action=pa.kind,
        last_node_removed=last_node_removed,
        last_reinforce_success=last_reinforce_success,
        no_reinforce_next=no_reinforce_next,
        must_attack_next=must_attack_next,
        rule3_fired=rule3_fired,
        rule3_pending=rule3_pending,
        next_clear_basis=next_clear,
        contradictions=contradictions,
        outcome=outcome,
        over=over,
        golden_used=golden_used,
        break_label=break_label,
    )
    log = RoundLog(
        r, pa, oa, (state.player_hp, php), (state.opp_hp, ohp),
        (state.node_ids(), new_state.node_ids()), (state.hachiku, hachiku), tuple(ev),
    )
    return replace(new_state, log=state.log + (log,)), ev


# --------------------------------------------------------------------------- tail


def _tail_correct(state: DebateState, pa: PlayerAction) -> bool:
    case = state.case
    spec = case.tail
    if spec.kind != "culprit_all_in":
        raise NotImplementedError(spec.kind)
    # A-9 犯人: 反駁，選擇器改選一段 2 張以上、只含實證、含第二說詞破解證物的鏈段
    if pa.kind != PA.PARRY or len(pa.segment) < spec.min_cards:
        return False
    links = segment_links(state, pa.segment)
    s, p = count_links(links)
    if p:
        return False
    return any(c in spec.second_claim.refuters for c in pa.segment)


def _resolve_tail(state: DebateState, pa: PlayerAction, oa: OpponentAction):
    case = state.case
    r = state.round
    ev: list = [E.Reveal(r, pa.kind.value, oa.kind.value, _staging(pa, oa))]
    if not oa.scripted:
        raise IllegalAction("tail rounds are scripted (A-11)")
    if pa.kind == PA.PARRY and case.shissu_enabled and state.shissu_left > 0:
        raise IllegalAction("MSG_DEB_NOPARRY_SHISSHU")
    if pa.kind == PA.OBSERVE:
        ev.append(E.Message("WARN_DEB_OBSERVE_TAIL"))
    correct = False
    try:
        correct = _tail_correct(state, pa)
    except IllegalAction:
        correct = False
    php, ohp = state.player_hp, state.opp_hp
    over, outcome, reason = False, None, None
    ev.append(E.TailResult(correct))
    if correct:
        ev.append(E.DamageToOpponent(ohp, "tail_finish", ohp, 0.0))
        ohp = 0.0
        over, outcome, reason = True, "win", "tail_finish"
    else:
        before = php
        php = php - case.tail_wrong
        ev.append(E.DamageToPlayer(case.tail_wrong, "tail_wrong", before, php, (("fixed", case.tail_wrong),)))
        if php <= 0:
            over, outcome, reason = True, "loss", "player_zero"

    # statuses: 破竹 unchanged; 困獸/失守 timers advance; nothing triggers (A-15, A-11)
    konju_left = max(0, state.konju_left - 1) if state.konju_left else 0
    shissu_left = max(0, state.shissu_left - 1) if state.shissu_left else 0
    ev.append(E.HachikuChanged(state.hachiku, state.hachiku, case.hachiku_mode == "preview"))

    tail_left = state.tail_rounds_left - 1
    nodes, removed = state.nodes, state.removed
    in_tail, shaken, voids = True, state.shaken, state.break_voids
    if over:
        ev.append(E.DebateEnded(outcome, reason))
    elif tail_left <= 0:
        # A-9: break voided -> opponent back to 25% of max, leave tail, shaken ends;
        # A-8: break threshold +1 card for the rest of the debate.
        ohp = case.opp_max_hp * 25 / 100
        voids += 1
        in_tail, shaken = False, "none"
        ev.append(E.BreakVoided(ohp, voids))
        ev.append(E.StatusLost("tail", "opponent", "voided"))
        ev.append(E.StatusLost("shaken", "opponent", "break_voided"))
        # SPEC-QUESTION: "節點照 A-1 回復" — the second-claim node is removed and the next
        # round restates normally (+1 from removed script nodes); A-1's "論破後的新階段從上限
        # 開始" could instead mean a refill to the cap.
        nodes = ()
        ev.append(E.NodeRemoved(state.case.tail.second_claim.id, "tail_void"))
        removed = tuple(n.id for n in case.node_pool)
        nodes, removed = _recover_one(nodes, removed, case, "restate", ev)
    new_state = replace(
        state,
        round=r + 1,
        player_hp=php,
        opp_hp=ohp,
        nodes=nodes,
        removed=removed,
        in_tail=in_tail,
        tail_rounds_left=max(0, tail_left),
        shaken=shaken,
        break_voids=voids,
        konju_left=konju_left,
        shissu_left=shissu_left,
        opp_history=state.opp_history + (oa.kind,),
        last_player_action=pa.kind,
        over=over,
        outcome=outcome if over else state.outcome,
    )
    log = RoundLog(
        r, pa, oa, (state.player_hp, php), (state.opp_hp, ohp),
        (state.node_ids(), new_state.node_ids()), (state.hachiku, state.hachiku), tuple(ev),
    )
    return replace(new_state, log=state.log + (log,)), ev
