"""The chapter's ending after the debate (ch §2 S08-S10, §13 結算畫面), from the final debate state.

A pure function of the finished State (and results.compute): the ordered S08 lines, the S09 newspaper version and
its addenda, the S10 notes version and its addenda, and what the result screen shows. Hidden-value ruling (v2 demo
plan §2.4, ticket 4.4): the screen shows the grade, the reputation change items and the favour changes; never the
reputation total, the truth score or its band (truth only picks the S10 version).

Facts the conditions use, each defined from the debate's public record (§2 公開紀錄; ref State.record: every claim
the player said, in any use - argue, intercept, dismantle, cut, last stand - including ones later knocked off,
voided or red-cracked):

- parentage public (公開過艾琳的身世): a claim marked 私事 in the data was said (d01: 09A, "艾琳是海德先生的女兒";
  ch §5.2 私事 column "艾琳的身世"). Counted when said, like the §10 reputation item (results / resolve).
- said 07A or 07B (Briggs explained): either claim is in the record. Route C cuts with 07A (red crack) and §12.3
  gives it S08 L004-L005, so a cut counts as "said".
- said 06B: 06B is in the record (route C: a cut; route D: argued, then refuted).
- used the talking board (用過通靈板): a claim of the psych-card evidence was said (P1A / P1B).
- denials / cracks: State.denials, State.cracks at the end (§6.4, §7.4 c).
- truth band: results.compute's truth % (§9): >= 70 full, 40-69 half, < 40 wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import known as K
from .model import State
from .results import Result, compute

S08, S09, S10 = "SCR_D01_S08_L", "SCR_D01_S09_L", "SCR_D01_S10_L"


def _l(prefix: str, *nums: int) -> list[str]:
    return [f"{prefix}{n:03d}" for n in nums]


# S09 versions by grade (ch §2 S09): headline + lead
PAPER_LINES = {"decent": _l(S09, 1, 2), "normal": _l(S09, 3, 4), "ugly": _l(S09, 5, 6)}
# S10 versions by truth band (ch §2 S10)
NOTE_LINES = {"full": _l(S10, 1, 2, 3), "half": _l(S10, 4, 5), "wrong": _l(S10, 6)}


@dataclass(frozen=True)
class Facts:
    win: bool
    parentage_public: bool
    briggs_explained: bool  # said 07A or 07B
    said_06b: bool
    board_used: bool
    denials: int
    cracks: int
    truth: int


@dataclass(frozen=True)
class Epilogue:
    facts: Facts
    s08: tuple[str, ...]  # ordered S08 line ids
    paper: str  # decent / normal / ugly
    paper_lines: tuple[str, ...]  # the version's headline and lead
    paper_addenda: tuple[str, ...]  # S09 L007 / L008, in order
    notes: str  # full / half / wrong
    note_lines: tuple[str, ...]
    note_addenda: tuple[str, ...]  # S10 L007 / L008 / L009, in order
    # the result screen (ch §13 結算畫面)
    grade: int
    rounds: int
    reputation: tuple[tuple[str, int, int], ...]  # (item, delta, count): count for cracks / private / denials
    favour: tuple[tuple[str, int], ...]  # (who, delta)

    @property
    def s09(self) -> tuple[str, ...]:
        return self.paper_lines + self.paper_addenda

    @property
    def s10(self) -> tuple[str, ...]:
        return self.note_lines + self.note_addenda


def facts(s: State, res: Result | None = None) -> Facts:
    res = res or compute(s)
    ch = s.ch
    said = {r.claim for r in s.record if not K.is_catch(r.claim)}
    return Facts(
        win=s.outcome == "win",
        parentage_public=any(ch.claims[c].private for c in said),
        briggs_explained=bool(said & {"07A", "07B"}),
        said_06b="06B" in said,
        board_used=any(ch.claims[c].psych_card for c in said),
        denials=s.denials,
        cracks=s.cracks,
        truth=res.truth,
    )


def s08_lines(f: Facts) -> list[str]:
    """ch §2 S08, in table order. SPEC-QUESTION: L001, L007, L008 are marked only 〔勝利〕 and play on every win,
    although §12's 結算台詞 rows name only some lines (§12.1 none, §12.2 L009-L010, §12.3 L001-L005): read as the
    notable conditional lines, not the full list."""
    if not f.win:
        return _l(S08, 11, 12)
    out = _l(S08, 1)
    if f.parentage_public:
        out += _l(S08, 2, 3)
    out += _l(S08, 4, 5) if f.briggs_explained else _l(S08, 6)
    out += _l(S08, 7, 8)
    if f.board_used:
        out += _l(S08, 9, 10)
    return out


def paper_addenda(f: Facts) -> list[str]:
    """ch §2 S09 addenda: L007 parentage public (any version); L008 denials >= 1 or cracks >= 3, on a win."""
    out = []
    if f.parentage_public:
        out += _l(S09, 7)
    if f.win and (f.denials >= 1 or f.cracks >= 3):
        out += _l(S09, 8)
    return out


def note_addenda(f: Facts) -> list[str]:
    """ch §2 S10 addenda: L007 07A / 07B never said (any version); L008 said 06B and truth < 70; L009 a loss.

    SPEC-QUESTION (L008): read literally, routes C (06B cut, truth 50, a win) and D (06B refuted, truth 60, a loss)
    both meet "說過 06B 且真相度 < 70%", but §12.3 gives route C only L004-L005 and §12.4 route D only L007 and L009.
    Conservative reading taken from the line itself: "我們讓他回家了" (Briggs was released: a win) and "卻沒有讓他
    說清楚" (he never explained: 07A / 07B not said). So L008 = a win, 06B said, 07A / 07B not said, truth < 70. It
    matches all four §12 endings; no route reaches it (test_epilogue covers it with a constructed state)."""
    out = []
    if not f.briggs_explained:
        out += _l(S10, 7)
    if f.win and f.said_06b and not f.briggs_explained and f.truth < 70:
        out += _l(S10, 8)
    if not f.win:
        out += _l(S10, 9)
    return out


def _count(item: str, s: State) -> int:
    return {"cracks": s.cracks, "private": s.privates, "denials": s.denials}.get(item, 0)


def epilogue(s: State) -> Epilogue:
    """The ending for a finished debate (State.outcome set)."""
    res = compute(s)
    f = facts(s, res)
    return Epilogue(
        facts=f,
        s08=tuple(s08_lines(f)),
        paper=res.newspaper,
        paper_lines=tuple(PAPER_LINES[res.newspaper]),
        paper_addenda=tuple(paper_addenda(f)),
        notes=res.note_version,
        note_lines=tuple(NOTE_LINES[res.note_version]),
        note_addenda=tuple(note_addenda(f)),
        grade=res.grade,
        rounds=res.rounds,
        reputation=tuple((k, d, _count(k, s)) for k, d in res.reputation),
        favour=res.favour,
    )
