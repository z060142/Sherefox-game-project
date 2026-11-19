# Sherefox localization table (zh-TW / en), demo chapter D01《守靈夜消失的遺囑》

Source: `v2/11_demo_chapter.md`. Every displayed line in the chapter carries its ID in backticks beside the text, so the chapter and these files cannot drift. Conventions follow `localization/README.md` (v1 package) unless noted here.

All files are UTF-8 (CSV files have a BOM).

## Status

| Push | Content | State |
| --- | --- | --- |
| 1 | Everything the debate needs: claims, opponent cards, cut/refute/contradiction/link lines, reactions, tells, state lines, system templates, situational beats, warm-up (S04) and debate framing (S07) | done |
| 2 | Investigation: evidence, hotspots, person notes, observations, appraisals, carry screen (S05/S06) | done |
| 3 | Story scenes: S01–S03, S08–S11, and scene headings `SCR_D01_Sxx_TITLE` | done |
| 4 | English column for every row, final CSV ↔ JSON check | done |

## Files

| File | Rows | Content |
| --- | ---: | :--- |
| script_d01.csv | 354 | ID, speaker_zh, speaker_en, zh-TW, en, note. Spoken lines and system lines |
| evidence_d01.csv | 223 | ID, zh-TW, en, note. Labels and texts shown on cards, chains and lists |
| strings_d01.json | 577 | `{ID: {"zh-TW", "en"}}`, merge of the two CSVs above |
| ui_strings_d01.csv | — | written by Sherefox遊戲企劃, not part of this build; not merged into strings_d01.json |

## ID scheme

| Prefix | Meaning | File |
| --- | --- | --- |
| `ISSUE_D01_{OPP,METHOD,MOTIVE}` (+`_SHORT`) | issue names 機會／手法／動機 (short: 機／法／動) | evidence |
| `CLM_D01_<id>` / `CLM_D01_<id>_LINE` | claim short label (shown on the chain and in the claim picker) / Sherefox's spoken line. `<id>` = 01A … 12A, P1A, P1B | evidence |
| `CARD_D01_<card>` | opponent card short label (his chain). `<card>` = L1–L4, F1, F2, U1, U2, P05, P06, P07, K1 | evidence |
| `CLM_D01_<id>_SHORT` / `CARD_D01_<card>_SHORT` | short label for chain nodes and the Public Record, right after the full label. en max 28 characters including spaces; zh-TW copies the full label. Full labels are unchanged and still used in the claim picker and card lists | evidence |
| `CARD_D01_<card>_STATE / _PUSH / _RETRACT / _DOWN` | 立論 / 強辯 / 周旋改口 (re-raised, softened) / knocked down by a 正論 | script |
| `CARD_D01_U*_TELL / _CATCH` | half-sentence shown in the tell before a slip / Sherefox's 「抓住他的話」 line | script |
| `CUT_D01_<claim>_<card>` | his reaction when that claim cuts that card (replaces `_DOWN`) | script |
| `REFUTE_D01_<claim>` / `REFUTE_D01_<claim>_FACT` | his 駁倒＋嫁禍 line / the fact the player knows afterwards | script / evidence |
| `EXCL_D01_<a>_<b>_CATCH / _SELL` | contradiction: his catch / Sherefox's hard sell | script |
| `EXCL_D01_TEMPLATE` | template for catches, `{a}` `{b}` | script |
| `LINK_D01_<a>_<b>` | 承接 line (replaces the claim line) | script |
| `REACT_D01_*` | his reactions: `ISSUE_OPP/METHOD/MOTIVE` (per issue), `SOPH` (any sophistry node), `<claim>` (special), `FACT_SOPH_1/2`, `LIE_SOPH`, `BLOCK`, `FOOLED`, `FOGGED` | script |
| `SHF_D01_CUT_OPEN_1–3` | Sherefox's opener when cutting (1–2 shared, 3 this chapter) | script |
| `TELL_D01_GESTURE_<ACTION>` | gesture text; ACTION = ASSERT (立論), PUSH (強辯), REBUT (反駁), STALL (周旋) | script |
| `TELL_D01_<ACTION>_n` / `TELL_D01_HINT_*` | his tell lines / Arthur's hints | script |
| `STATE_D01_ART_* / STATE_D01_SHF_*` | Arthur's and Sherefox's state lines | script |
| `SYS_D01_*` | system lines, written as templates | script |
| `BEAT_D01_*` | situational beats (condition in the note) | script |
| `FOG_D01_n` | Sherefox's 打迷糊仗 lines | script |
| `OBS_D01_W1–W3` | warm-up observation cards | evidence |
| `E_D01_<nn>_NAME / _DESC`, `C_D01_P1_NAME / _DESC` | evidence and psych card name / description | evidence |
| `HS_D01_<nn>_NAME / _DESC` / `HS_D01_<nn>_ART` | hotspot name / description / Arthur's comment | evidence / script |
| `SCENE_D01_<PLACE>` | investigation locations (PARLOR, STUDY, BASEMENT, ATTIC, BEDROOM, HALL) | evidence |
| `PN_D01_<n>_NAME / _TEXT`, `OBS_D01_01_NAME / _TEXT` | person notes and observation: title / text | evidence |
| `APR_D01_<nn>_LINE` / `_RESULT` | Arthur's appraisal line / the result note added to the evidence | script / evidence |
| `SCR_D01_S<scene>_L<line>` / `SCR_D01_S<scene>_TITLE` | scene script lines (S01–S11) / scene headings. S05 has no lines of its own (its hotspots are `HS_D01_*`). S09 rows carry the newspaper version and condition in the note, S10 rows the notes version and condition | script |

## Templates and placeholders

* `SYS_D01_*` rows with `{…}` are templates (note starts with `TEMPLATE`). Placeholders: `{name}` opponent name, `{hp}` `{hp_o}` `{hp_p}` `{hp_before}` `{hp_after}` credibility values, `{dmg}` `{dmg_p}` `{dmg_o}` damage, `{formula}` the damage formula text, `{issue}` `{issues}` issue names, `{n}` node count, `{c}` crack count, `{pct}` percent, `{claim}` claim label, `{fact}` a `REFUTE_D01_*_FACT`, `{gesture}` a `TELL_D01_GESTURE_*`, `{statement}` a card label or 「改口」「反駁」, `{action}` `{action1}` `{action2}` action names (UI strings), `{half}` a `CARD_D01_U*_TELL`, `{value}` 壓力／罪惡感／怒氣, `{person}` a character name, `{node}` a card label, `{chain}` card labels joined by →.
* `EXCL_D01_TEMPLATE` uses `{a}` `{b}`; the 10 templated rows in section 7 are already filled in.
* `BEAT_D01_REFUTED_3/4` use `{item}` (picked-up evidence name) and `{place}`.
* Calligraphy banners (論破, 逆論破, 動搖, 破竹, 困獸, 失守) and stamps stay Chinese in both languages; their banner strings live in the v1 `ui_strings.csv`.

## Conventions

* Outer 「」 around whole-line quotes are removed; quotes inside a sentence are kept (the speaker column carries who speaks). Stage directions in （） are kept in zh-TW and become ( ) in en.
* Condition markers 〔…〕 from the chapter are moved to the note (`cond: …`).
* English follows the v1 voice rules (British spelling; Sherefox playful, Arthur earnest, Baskerville pompous with "this Inspector" and "Miss Fox"). Cedric is formal and condescending.
* Terms follow `ui_strings_d01.csv`: Credibility, Sound / Sophistry, Argue, Rebut, Cut In, Knock Down, Muddy the Waters, Assert / Press / Sidestep, Guard Down, Seize His Words, Mind Game, Endgame, His Last Card, last gasp, Cover.
* Names: Sherefox addresses Cedric as "Mr Cedric", because "Mr Hyde" is the dead man. Aunt / Uncle for 嬸嬸 / 叔叔.
* 通靈板 / 靈應盤 = "talking board", never "Ouija" (that trademark dates from 1890; the chapter is set in 1888). 指示板 = planchette.
* 九點四十分 is "twenty to ten" in speech and prose; clock readings keep digits.

## Source fixes made during the English pass

Designer notes that had slipped into displayed text were moved to the note column (in both the chapter and the CSVs):
* SCR_D01_S04_L002/L006/L009 (correct answer), S04_L013, S04_L014, S08_L002 (regard and appraisal effects), S06_L011 (rule reference), S07_L009 (「垂死反撲」 marker).
* E_D01_12_DESC (「沒有用」), PN_D01_3_TEXT (completion hint), CUT_D01_03A_L1 (design note), HS_D01_12_ART (where the codicil is found), HS_D01_08/09/15_ART (「可鑑定」 marker).

Other fixes:
* SCR_D01_S06_L002 and S06_L009 are now templates (`{max}`, `{n}`, `{list}`).
* REFUTE_D01_06B now says the handkerchief carries the cook's initial, matching E_D01_07.
* HS_D01_23_DESC: the demand letter is addressed to 塞德里克・海德先生 ("C. Hyde, Esq."), not the late Mr Hyde.

## Check

Every CSV row equals its strings_d01.json entry (534 of 534). Every ID appears in `v2/11_demo_chapter.md`, except the `_SHORT` labels (added after delivery for screen space). Every en string keeps its zh-TW placeholder set, and no en string is empty.

## Changes after delivery

* S06 (carry screen): Arthur's comments now play only through the 「問亞瑟的意見」 button (UI_V2_CARRY_ASK_ARTHUR), in the priority order given in each row's note. New line SCR_D01_S06_L012 (priority 7, repeatable). L010 still plays automatically. The old 「待使用者決定」 flag on L008 is gone.
* Arthur's tell hints (`TELL_D01_HINT_*`): at most one per round, picked by the priority rule in chapter §11 ("亞瑟提示的時機"); the notes of the nine hint rows now say how often each plays. Strings unchanged.
* Short labels: 42 rows `CLM_D01_<id>_SHORT` (all 30 claims) and `CARD_D01_<card>_SHORT` (all 12 opponent cards), en max 28 characters, for chain nodes and the Public Record. Seize His Words has no label of its own (its node shows the caught card's label, so use that card's `_SHORT`).
* SCR_D01_S09_L004 en: "Mr Hyde was arrested" is now "Cedric Hyde was arrested" (Mr Hyde is the deceased). No other en string calls Cedric "Mr Hyde".
