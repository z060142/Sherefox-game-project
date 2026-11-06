# Sherefox localization table (zh-TW / en), Ch.1-3 prototype

All files are UTF-8 (CSV files have a BOM). Build this table with the glossary first; every file follows `glossary.csv`.

## Files and row counts (data rows, excluding header)

| File | Rows | Content |
| :--- | ---: | :--- |
| glossary.csv | 166 | term_zh, term_en, part_of_speech, note (names, places, game terms) |
| ui_strings.csv | 760 | ID, category, zh-TW, en, note. 614 text strings (systems.md section 8 + Arthur/Sherefox hint lines + Ch.1-3 transition newspaper) plus 51 brush-banner rows (4.7 / 8.14), 46 evidence-tag value rows (TAG_*), 3 per-chapter investigation openers (ART_OPEN_CH0x), 3 chapter titles (CHAP_0x_TITLE), 10 opponent gestures (GESTURE_*), the prototype's 「待續」 card (UI_TO_BE_CONTINUED), 4 paper-screen keys (UI_PAPER_*), 9 investigation/board labels (UI_INV_*, UI_BOARD_*), 7 title-screen keys (UI_TITLE_*, UI_CHAP_NO), 3 debate HUD headings (UI_DEB_GOSSIP, UI_DEB_PREVIEW_LABEL, UI_DEB_STATUS_LABEL), 3 result/paper labels (UI_PAPER_PREV_CASE, UI_RES_UNACHIEVED, UI_RES_TRUST_LABEL), the tag-list separator (UI_TAG_SEP), 3 stage names (UI_STAGE_*), UI_DEB_NOSOPH_REASON and UI_DEB_PREVIEW_HACHIKU |
| tutorial.csv | 190 | ID, chapter, zh-TW, en, note. 95 tutorials (all of section 7, Ch.1-12), two rows each (_TITLE, _BODY) |
| evidence_ch01-03.csv | 255 | ID, zh-TW, en, note. 24 evidence items (NAME, TAGS, DESC, REASON_A/B/C), 2 Ch.3 warm-up decoy observation cards (OBS_CH03_01/02: NAME, TAGS, DESC), 4 opening headlines (+ sub; HEAD_CH04 is the prototype-ending teaser), 12 claim nodes (9 main + the Ch.3 warm-up claim + 2 tail second claims), G-01 and its substitute (G-01_SUB = Case tab S-01), 45 hotspots (HS_*: 45 names, 20 case-note lines, 9 hints, plus HS_CH03_01_NOTE_REPORT), 5 scene names (SCENE_*), and G-01_DESC / G-01_REASON / S-01_DESC |
| script_ch01-03.csv | 505 | ID, speaker_zh, speaker_en, zh-TW, en, note. Ch.1 = 139, Ch.2 = 171, Ch.3 = 192 (incl. 4 warm-up failure lines SCR_CH03_S04_F001-F004 and 2 wrong-card retorts SCR_CH03_S04_W001-W002), plus Ch.4 S01 = 3 (the opening paper only, used as the prototype-ending teaser) |
| strings.json | 1710 | `{"<ID>": {"zh-TW": "...", "en": "..."}}`, merge of ui + tutorial + evidence + script (glossary excluded) |

## ID scheme

- UI: original IDs from systems.md (UI_, BTN_, MSG_, WARN_, ART_, SHF_, NEWS_, CUT_, STAMP_).
  - Duplicate IDs in the source were renamed with a suffix: `UI_NOTES_TITLE_DUP2` (Arthur's Opponent Notes; `UI_NOTES_TITLE` = Case Notes) and `UI_SET_SHAKE_DUP2` (Screen Shake Intensity; `UI_SET_SHAKE` = Screen Shake).
  - Derived IDs: `<CUT/STAMP id>_SUB` (English subtitle shown under a banner; zh-TW is empty because zh-TW shows no subtitle), `<CUT/STAMP id>_LOG` (backlog line, e.g. 【論破】), `STAMP_HACHIKU_LOST` (only listed in 8.14), `NEWS_xx_yy_SUB` (second line of a transition newspaper).
- Tutorials: `TUT_<ch>_<nn>_TITLE` / `_BODY`; trigger text is in the note.
- Evidence: `E<ch>_<nn>_NAME|TAGS|DESC|REASON_A|REASON_B|REASON_C` (A = correct rationale, B/C = wrong); `HEAD_CH0x` / `HEAD_CH0x_SUB`; `CLM_CH0x_Nn` (claim node text); `G-01`, `G-01_SUB`.
- Evidence tags: `TAG_<TIME|PLACE|PERSON|PHYSICAL|SCANDAL>_<ASCII slug>`, one row per distinct tag value used in Ch.1-3 (value only; the category label comes from `UI_TAG_<category>`, displayed as 【類別：值】 / [Category: value]). Which cards carry which value, the graze (※) flags and the appraisal flags live in the Case tab 「標籤值」 tables, not here.
- Hotspots: `HS_CH0x_nn_NAME` for every hotspot; inspect-only hotspots also have `_NOTE` (the Case Notes line) and some have `_HINT`. HS_CH03_23 is the conditional S-01 hotspot (only when G-01 is missing). Mirrors the Case tab 「調查點」 tables.
- Claims: `CLM_CH03_W1` = Ch.3 warm-up claim; `CLM_CH0x_T1` = tail second claim (Ch.2, Ch.3).
- `ART_OPEN_CH0x` = Arthur's investigation opening line per chapter (systems.md 1.4); `CHAP_0x_TITLE` = chapter title; `GESTURE_<OPPONENT>_<ACTION>` = opponent gesture text from the Case tab behaviour tables (ACTION = ASSERT, ONSLAUGHT, REINFORCE, TRAP).
- Script: `SCR_CH<ch>_S<scene>_L<line>` (line is 3-digit, per scene, in source order; L001 of each scene is the scene heading). Scene `S90` = the "Debate Line Library" (opponent tell/action lines, Sherefox/Arthur state lines) that sits between scenes 4/5 and the main debate in the source; its `note` column says which category and gesture each line belongs to.

## Conventions

- Brush-banner words stay Chinese in both languages (論破, 逆論破 / 逆・論破, 二連論破, 反擊論破, 絕境, 動搖, 破竹, 困獸, 失守; stamps 截, 中計, 落空, 交鋒, 看穿, 援護, 斷). The en column holds the same Chinese; the English gloss is in the note (`gloss: BREAK`). The glosses are the English subtitles that systems.md 8.14 already specifies. UI_BREAK / UI_DOUBLE_BREAK / UI_REVERSE_BREAK / UI_COUNTER_BREAK (8.7 title cards) follow the same rule.
- Inside ordinary sentences these terms use the glossary English: Break, Reverse Break, Double Break, Counter Break, At the Brink, Shaken, Cornered, Breached, Unstoppable, Cut-In, Clash, Cover.
- Placeholders (`{n}`, `{name}`, ...), `×`, `−`, 【】 and the 【印：…】 / 【大字：…】 cue markers are preserved; a build check confirmed that every UI string keeps the same placeholder set.
- Script rows: outer 「」 around whole-line quotes were removed (the speaker column carries who is speaking); stage directions in （） become ( ). Arthur's Tell-hint lines had a trailing action tag （主張）etc.; that tag moved to the note (`action: Assert`).
- British spelling. Voices: Sherefox playful with adapted puns, Arthur dry straight man, Baskerville pompous ("this Inspector", "Miss Fox"), Wolfhart formal with long subordinate clauses and passive voice. Sherefox's catchphrase 「等一下，我快解開了！」 = "Hold on—I've almost cracked it!"; 「等一下，我已經徹底解開了！」 = "Hold on—I've completely cracked it!".
- Adapted puns (noted in the note column): 「閥」網恢恢 -> "valve-id reasoning"; 駁 (barge / rebut) -> sinking-barge image; 布丁綁架 -> "puddingnapping".
- Transition newspapers are merged (systems.md 3.3): the front page is the next chapter's S01 opening paper and the previous case's NEWS_xx_WIN/NOTO/LOSE goes in the sidebar. The old second-page teasers `NEWS_xx_NEXT` (and `NEWS_03_NEXT_SUB`) were retired in favour of each chapter's S01 lines and removed from ui_strings.csv and strings.json. The prototype ends on Ch.4's opening paper (SCR_CH04_S01_*, HEAD_CH04/_SUB, with Ch.3's result in the sidebar), then UI_TO_BE_CONTINUED.
- Newspaper: 《倫敦提燈報》 = The London Lantern everywhere (canon fix). The Script tab still prints 【倫敦晨報…】 as its masthead in the Chinese text; the English column uses The London Lantern. Regional editions: 約克郡晨報 = The Yorkshire Morning Post, 高地週刊 = The Highland Weekly.

## Source problems noticed (translated by intended meaning; flagged in notes)

- Script Ch.1 S04: 「那牢應該去當鐘錶匠」, "牢" is a typo for 牠.
- Script Ch.3 S06 last line: 「全場噴然」, intended 嘩然.
- NEWS_02_WIN headline says the attendant 調快 (sped up) the clock, but the Ch.2 story has it set 3 minutes slow (調慢); English says "tampered with" to stay safe.
- Script line "G-01" appears in Ch.3 S06 as an evidence reference; kept as is.
- Fitch refers to himself as 小人 (humble self-reference); rendered as formal servile English ("Master", "if you will permit me") rather than a literal "this humble one".

## Not translated / out of scope

- Audio asset tables (SFX_*), screen IDs (SCR_* in 4.1), numeric rules and design tables, Appendix A.
- Script tab Ch.4 and later, Case tab Ch.4, transition-newspaper rows for Ch.4 and later (NEWS_04_* onward, NEWS_SIDE_04+). Tutorials for all chapters (TUT_01 to TUT_12) were translated because they belong to section 7.
- Case tab design tables (behaviour tables, recommended routes, numeric cards, results notes, character role tables) are design data, not player text.
- Appraisal type per evidence is kept as Chinese in the note, not translated.
- Everything else in scope was translated; nothing was unreadable.
