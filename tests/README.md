# Tests

Headless playthrough checks for the flows (`docs/flows.md`). They replay recorded title/paper/vn clicks with
`xtatrium run --replay ... --ports` and compare the UI port trace with the data tables (`data/*.json`,
`strings/*.csv`).

## Prerequisites

- The XTAtrium CLI at framework commit 5aad137 or later (AT-046: `atrium.ui.list` field references and
  `atrium.textf`; AT-047: `bare` value arrays; the flows do not compile on older builds): the SDK built with
  `pwsh <XTAtrium>\tools\install-sdk.ps1 -Out <sdk-dir>`, or a Release build of an XTAtrium checkout
  (`dotnet build src\XTAtrium.Headless -c Release`). No location is assumed; see Environment below.
- The packed UI bundle: `xtatrium pack --game .` (after any change under `ui/`).
- AT-036 (`xtatrium compile --game`, framework 4352f29 or later): `check_case.py`, `check_playthrough.py` and
  `check_debate_play.py` first run `xtatrium compile --game <repo root>` (`tests/xt_cli.py` `compile_game`)
  and stop when an endpoint does not resolve. By hand: `xtatrium compile --game .`.
- The XTFrame converter (`xtframe-import`), only needed to re-import `ui/boards`: the npm package
  `@xtframe/converter-win32-x64` is not published, so install it from a local tarball of the XTFrame distribution:
  `npm install --no-save <path-to-xtframe-converter-win32-x64-0.15.0.tgz>` (the binary is then
  `node_modules\@xtframe\converter-win32-x64\bin\xtframe-import.exe`). It is deliberately not in `package.json`.
- Run every command from the repository root; the game is always given as `.` (a relative path).
- [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv` or `pip install uv`); the scripts use the standard
  library only.

Environment (no personal defaults; the checks stop with a message when no CLI is found):

| Variable | Meaning |
|---|---|
| `XTATRIUM_EXE` | the CLI to use; overrides the rest |
| `XTATRIUM_SDK` | the installed SDK directory (holds `xtatrium.exe` and `xtframe/`); used by every check when `XTATRIUM` is not set |
| `XTATRIUM` | an XTAtrium checkout; its `src/XTAtrium.Headless/bin/Release/net10.0/xtatrium.exe` is used |
| `XTATRIUM_XTFRAME_DIR` | the XTFrame runtime directory; default the SDK's `xtframe/`, `<XTATRIUM>/artifacts/xtframe`, or `xtframe/` next to the CLI |

Order: `XTATRIUM_EXE`, then `XTATRIUM_SDK`, then `XTATRIUM`, then `xtatrium` on `PATH`. Localization packages are imported
with `uv run tools/build_data.py --import-localization <dir>` (the design repo's `localization/`,
github.com/z060142/research-prototype-2); the directory is always an argument.

## Run

From the project root:

```
uv run tests/check_playthrough.py
uv run tests/check_playthrough.py --frames <dir>     # also writes title.png, vn_line.png, paper_ch2.png
```

It regenerates the recordings first (`tests/gen_playthrough.py`, from the `steps` and `script` tables), then runs:

| Check | Recording | What it asserts |
|---|---|---|
| data | — | `script.playable` and `script.sceneKey` follow their rules (`docs/data-schema.md` §3); every vn scene of Ch.1-3 has playable rows |
| `ch1_playthrough[zh-TW]`, `[en]` | `ch1_playthrough.atrec` (`--lang en` for the second) | each of Ch.1's 21 playable lines is shown once, in order, with the right text and name plate, while vn is the only visible main screen; the Ch.1 paper shows both pages; the run ends on the Ch.2 opening paper, page 1, with the Ch.1 result strip; nothing on stderr |
| `full_run` | `full_run.atrec` | every line of Ch.1-3 the story shows, in order (the vn scenes, the debate and warmup scenes' opening lines and the warmup's wrap-up, `script.cue`, and the result scenes' lose lines); the four papers (CH01..CH04_OPEN) with every port that has a `papers` column (result strip, side column, advert, picture id); the title's end card (`title.ended`); a click on the card emits `title.end_dismiss` and clears `title.ended` with the title still the only main screen, and the chapter list then starts Ch.3 (its lines again, up to a second end card); Enter on the card dismisses it too, and the Ch.3 entry, clicked again with the same value (AT-040 `.emitted`), then opens the Ch.3 paper, where the run ends |
| `lang_toggle` | `lang_toggle.atrec` | the title's language toggle flips `title.lang_en` (true, false, true); the Ch.1 paper and first line are then in English |

Exit code 0 and a final `ok` line when everything passes; each failure is printed as `FAIL ...`.

`--frames` replays `ch1_playthrough` with `--ui-frames` into `<dir>/_ppm` (about 340 full-size PPM frames, ~1 GB,
deleted afterwards) and converts three of them to PNG.

## Replaying by hand

```
xtatrium run --game . --replay tests/ch1_playthrough.atrec --ticks 447 --ports
xtatrium play --game . --replay tests/ch1_playthrough.atrec
```

The recordings name the game as `.` in their header (`tests/play_harness` for the debate recordings that run against
the harness copy); run from the repository root and pass `--game` with exactly that string, or the CLI warns that the
recording's game differs. The recordings carry no hash checkpoints (they are generated, not
recorded), so give `--ticks` (printed by `uv run tests/gen_playthrough.py`).

## Settings overlay

```
uv run tests/check_settings.py
```

It regenerates `tests/settings.atrec` (`tests/gen_playthrough.py` `settings`) and replays it with `--ports`: the
title's Quit Game emits `title.quit` (a no-op headless; main feeds `atrium.app.quit` from it); the title's Settings
opens the overlay, Esc closes it; on Ch.1's opening paper F1 opens it, Backspace closes it, Esc with no overlay open
opens it and a click on the dimmed screen closes it (the paper stays on page 1); English / 繁體中文 flip the title's
`lang_en` and `settings.lang_sel`, and `settings.current` follows the language; 大字譯名 goes off and on (a click on
On while it is on sends nothing); every `res_options` write is the selected auto option only (`display.native*` are 0
headless). It also checks the game.json `display` block and that the settings surface is modal, right below cutin.

## Investigation area arrows

```
uv run tests/check_nav.py
```

It replays `tests/ch3_warmfail.atrec` (ending in Ch.3's investigation) plus clicks appended in a temporary copy:
▶ twice, then ◀ twice; each must reach its arrow and emit `nav` (+1 / -1). Regression for the area name covering ◀.

## Music and the debate jingles

```
uv run tests/check_music.py
```

It checks the game.json `audio` block against the files under `audio/` and `tools/gen_flows.py` `MUSIC` (loop
points), `flowBgm` (play, fade), the music flow's commands (the crossfade play, the cut's play after a 0.2 s timer,
the stop) and the jingle `sound` nodes; then `data/bgmCues.json` against the design's cue table
(`source/staging/bgm_cues_ch01-03.csv`): every cue reaches a shown line with its track after the fallback and its
fade (the Ch.3 cues past the warm-up and the Ch.4 teaser are only checked here). Then it replays
`tests/ch1_debate.atrec`, `tests/ch2_lose.atrec` and `tests/ch3_warmfail.atrec` with `--trace` (into a temporary
directory that is deleted). The music commands do not reach the trace, so it reads the music flow's own values (located
with `compile --emit ir`). The expected sequence of (track, fade) is derived from the route of each replay (`ROUTES`:
the moments and scenes it passes through) with `bgmCues` and `flowBgm`, and printed; `world.bgm` must follow it tick
by tick, each change must make exactly its commands (cross: one play with a 1.5 s fade-in; cut: a 0.2 s stop, then a
play at full volume 0.2 s later; silence: one stop), and `atrium.music.playing` must follow within two ticks. Ch.1:
BGM01 -> BGM11 (paper) -> BGM02 -> BGM04 (cut, S03 L004) -> BGM05 -> BGM06 -> BGM12 -> BGM11 -> BGM12 (notes) ->
BGM11 (Ch.2 paper) and one `SFX_DEB_WIN`; Ch.2 lost twice: one `SFX_DEB_LOSE` per defeat, the lose lines end in
silence (out); Ch.3 to the investigation: BGM03 at S03, BGM04 (cut) at S03 L003. It takes a few minutes (the traces
are large).

## Investigation and clue board

```
uv run tests/check_case.py
uv run tests/check_case.py --frames <dir>     # also writes inv_ch1/2.png, popup_card.png, evbook.png, board_*.png
```

It regenerates `tests/ch1_case.atrec` and `tests/ch2_case.atrec` (`tests/gen_case.py`), replays each with `--ports`
and `--dump`, and checks the port trace, the JSON written into the list ports (`write ... document.<port>` lines of
the port log; a list port reads back as an empty string) and the collections at the end (`docs/flows.md` §6):

| Recording | Route | What it asserts |
|---|---|---|
| `ch1_case` | Ch.1: all 10 hotspots (one click per reaction line), Sherefox's hint, end (nothing left: no warning); chain E01_01 -> E01_04 and every reason correct; to the debate | hotspot list (10 rows, types, all visited at the end), popup kinds, the reaction lines under the popups (`hotspots.lines`, in order, with their name plates), Ch.1 ticks / appraisals hidden, hint lines (`WARN_INV_END_ZERO` by itself after the last spot, §1.7), `held`, no opponent hand, drawer / slots / links / chain plate, ART_SOLID, `debBoard*` equal to the ref board `fixtures.ch1_board`, no golden clue, the debate step opening on the vn with its pre line |
| `ch2_case` | Ch.2: six evidence spots and one inspect spot (E02_05 missed), E02_01 appraised in the evidence book, Arthur's hint; E02_02 and E02_07 appraised on the board, chain I E02_03 -> E02_02 -> E02_04 (E02_04 wrong reason), E02_06 tried next to E02_04 (bounced), chain II E02_06 -> E02_01 -> E02_07 | ticks 8 -> 1, popup kinds (testimony 3, the missed-cards message 4), the reaction lines, the scene name, hint and remark sequences (ART_TIME_LOW, the cards' appraisal lines `evidence.appraisalKey` on the board and as the evidence book's `remark`, `WARN_INV_END` with `{left}` on the first press of 結束蒐證, ART_SOLID, ART_SOPH_1, ART_INVALID), `MSG_INV_MISSED` with `{n}` = 1, appraisals 3 -> 0, the book's card list, `oppHand` = [E02_05], an invalid link shown before the bounce, final links and chain plates (dmg 32.2 / 28), `debBoard*` equal to the ref board for the same route (`ch2_case` with E02_04's reason wrong), `golden` = [G-01] |

The board clicks go to element positions of the boards; the detail panel's reason rows move with the text above them,
so `gen_case.reason_xy` computes them from the strings (a line-count model of the panel).

## Debate engine

`uv run tests/check_debate.py` regenerates the debate engine (`tools/gen_debate.py`), replays every route of
`tests/debate_routes.py` through the reference model `ref/`, writes the harness project `tests/debate_harness/`
and runs it headless once, then prints PASS / FAIL per route with the first diverging round and field. Options:
`--route NAME` (repeatable), `--keep` (keeps the dump in `tests/debate_harness/out/`), `--verbose`. See
`docs/debate-engine.md` §6.

`uv run tests/check_policy.py` checks the opponent AI (`docs/debate-engine.md` §3.4, §6.2): for every situation it
computes the exact distribution of the reference policy (`ref/` `decide_next`, every choice enumerated with its
probability), runs the harness `tests/policy_harness/` headless with `--seed 1..4` in parallel (4000 decisions per
situation in all), and compares the observed frequencies of every tell outcome, lit node and tell line (|z| <= 4,
outcomes the reference cannot produce must never occur); free-play debates driven by the engine's own decisions are
replayed in `ref/`. It also asserts the hard rules on every decision. Options: `--samples N`, `--seeds K`,
`--verbose` (per-cell table). About 30 s.

## Debates, result and consequences (M4c)

```
uv run tests/check_debate_play.py
```

It regenerates the recordings and the scripted-opponent harness (`tests/gen_debate_play.py`; `tests/play_harness/` is a
generated copy of the game whose `debScript` also plays the opponent moves of the ref routes `ch2_route` and
`ch3_route` (keys `CH02_MAIN:<round>` / `CH03_MAIN:<round>`) — game paths
may not leave the game directory — do not edit it), replays them with `--ports` and `--dump` and checks
(`docs/flows.md` §4.8, §4.9):

| Recording | Route | What it asserts |
|---|---|---|
| `ch1_debate` (game) | `ch1_case`'s board; the opening line; R1 rebut E01_06, R2 solid E01_01 -> E01_04, R3 rebut E01_03 against the G2 script rows; the confession | the reveal pairs, the nodes and statuses shown after each round equal the ref route `ch1_route`; the cut-in sequence equals the ref records (full-screen played -> `big`, stamps, demoted 破竹 3 -> the 破竹 stamp); the contradiction counter; the opening line (`script.cue` pre) before the debate; Arthur's confession (S05 L027-L035, `postWin`) on the vn after it; result win, `ART_RES_CLEAN`, no closing line (already played); the result scene's win lines and the notes; the Ch.2 paper strip |
| `ch2_debate` (`play_harness`) | every evidence spot, three appraisals, the ref board `ch2_board`, the five rounds of `ch2_route` | per round: HP of both sides, nodes, 破竹, 動搖, 尾聲 equal the ref; cut-ins; the opening line; Wolfhart's cup (S05 L041-L042, `postWin`) after the debate; result win / comment / Fitch's line; win lines; the Ch.3 paper shows `NEWS_02_WIN`; E02_08 in `held` (F3), G-01 kept, no costs |
| `ch3_debate` (`play_harness`) | `ch2_debate`'s route (G-01 earned), then Ch.3: paper and vn, the warmup (E03_05), the three scenes (E03_07, E03_04 / E03_03, E03_08 / E03_06; nav with E), E03_02 and E03_04 appraised on the board, the ref board `ch3_board` (G-01 is the ninth drawer card: the drawer is scrolled down with the wheel to reach it), the five rounds of `ch3_route`, the result, the win lines, the notes, the final paper | per round of the Ch.3 debate (from `debate_ticks.json` `ch3_debate_from`): HP, nodes (the tail's second claim T1 included), 破竹, 動搖, 尾聲 equal the ref; cut-ins; the warmup's opening and wrap-up lines; the debate's opening line; the scene names in order; `MSG_INV_MISSED_NONE` after both investigations; result win, `ART_RES_CLEAN`, Pierce's line, trust 3 -> 4; win lines and notes; the final paper shows `NEWS_03_WIN`; G-01 kept, no opponent hand |
| `ch2_lose` (game, seeded AI) | `ch2_case`'s first chain (E02_04 left in the drawer with a wrong reason); R1 sophistry on E02_03 -> E02_02 with 臨場硬接 E02_04, the opponent notes opened (N, its three tabs, Escape); observe every round until the debate is lost; the defeat review (Escape); retry (no opening line); lost again; review; continue | 臨場硬接 offered, its only candidate E02_04 (ref `link_kind`: sophistry), the picker title, the chain E02_03 -> E02_02 -> E02_04 with the new dashed link, R1's damage = ref `chain_damage_breakdown`; the board restored after the retry; two defeat screens (win 0, `ART_RES_LOSE`, retry offered), each after a review (notes, tab 2), the log rows (one a round, R1 misread with its `ART_REVIEW_*` line) agreeing with the result's 讀對預兆 row, the gestures; the cost line (E02_01 seized), the opening line played once, the lose lines, the Ch.3 paper shows `NEWS_02_LOSE`, G-01 removed, no E02_08, the missed card's hand |
| `ch2_tailwrong` (`play_harness`) | `ch2_debate`'s route up to R4 (the break), R5 (the tail) answered with an observe | the tail's result line is `SCR_CH02_S05_L047` (design confirmed; ruling G6: the localization dropped its 「（若尾聲出錯牌）」 author note), not `MSG_TAIL_WRONG` |
| `ch3_warmfail` (game) | Ch.3 from the title: paper, vn, the warmup presenting OBS_CH03_01, OBS_CH03_02, OBS_CH03_01 (ruling G5: three mistakes), up to the investigation | the picker lists the whole hand (E03_05, E03_02, OBS_CH03_01, OBS_CH03_02); three warmup rounds; `MSG_WARMUP_WRONG` three times, each followed by the inspector's retort on the vn (W001, W002, W001: `script.cue` `wrong:<card>`); the failure wrap-up S04 F001-F004 (postLose) instead of L006-L009; `caseMod.trust` −1; the investigation opening with `ART_NO_REPORT` (the case's trust 2) and no E03_01; no observation card in `held`; the music (`--trace`, `world.bgm`: BGM01, BGM11, BGM02, BGM03, BGM04, BGM07, BGM05; the scene cues, `docs/flows.md` §4.10) |
| `ch3_warmone` (game) | the same with OBS_CH03_02, then E03_05 (one mistake) | its retort (W002) after one `MSG_WARMUP_WRONG`, no `MSG_WARMUP_PERFECT`; passed: L006-L009 (postWin), not F001-F004; `caseMod.trust` 0 (A-13: only zero mistakes give +1), so the police report E03_01 is held (trust 3); no observation card in `held`; the same music |

M5c also checks, in `ch1_debate` / `ch2_debate` / `ch3_debate`, the result's 讀對預兆 row (`UI_RES_READS`, hit = the ref
route's reads, `tests/debate_routes.py` `round_read`), in `ch2_debate` the `preview_vs` of every round (the ref
resolution of the locked action against the opponent's actual action; the harness tells are clear), and in
`ch3_debate` the warmup's passed wrap-up (L006-L009, postWin), and that no observation card (OBS_CH03_*) appears outside the warmup's picker (no port write, not in `held`).

Texts the flows fill with `atrium.textf` (the counters, the round, the cost line) are compared with the zh-TW
template filled the same way (`zf()`), not with a pre-expanded key.

The story playthroughs (`check_playthrough.py`) now go through every warmup, debate and result step the shortest
sure way (`gen_debate_play.minimal`: the opening lines, the warmup's first card and its wrap-up lines, observe until
the debate ends, continue, the lose lines), so their line lists include the result scenes' lose branch and the
papers' strips are the lose variants. Their investigations click once per reaction line, press 結束蒐證 twice (the
first press warns) and close the missed-cards message (`gen_case.end`).
`check_debate.py`, `check_policy.py` and `check_playthrough.py` use the CLI of `tests/xt_cli.py` (`XTATRIUM_EXE`,
else the installed SDK, else the `XTATRIUM` checkout).

## v2 demo: the D01 debate screen (M2)

```
uv run tests/check_debate_v2.py                 # the engine against the ref (unchanged by M2)
uv run tests/check_d1_play.py [--shots DIR]
```

`check_d1_play.py` regenerates the recordings (`tests/gen_d1_play.py`) and replays them with `--ports`. Each one starts
at the title's v2 entry and plays the whole D01 debate by clicking the `d1debate` screen (action, evidence, claim,
target, cover, lock, one click per playback record), then the outcome panel's back to title.

| Check | Recording | What it asserts |
|---|---|---|
| `route A`, `route A [en]` | `d1_routeA.atrec` on `tests/d1play_harnessA` | ref route A (ch §12.1) with Cedric's moves pinned through the engine's `d1OppAct`／`d1OppCard` test hook (a flow the harness adds): the outcome panel shows grade 1 and 9 rounds, a win; round 9 was shown; back to title leaves only the title; nothing on stderr |
| `route B`, `route C [en]` | `d1_routeB.atrec`, `d1_routeC.atrec` on `tests/d1play_harnessB`, `C` | ref routes B (talking board, seize his words, he gives up: grade 1, 5 rounds) and C (sophistry, a private matter, the picked-up keys as his last card taken, a second endgame: grade 3, 10 rounds), each with its own loadout |
| `route D` | `d1_routeD.atrec` on `tests/d1play_harnessD` | ref route D (ch §12.4; the harness also swaps in route D's loadout): grade 5, 8 rounds, a loss (Reverse Break, then the last card fails; route D names L1 as the target, no longer on his chain, so no target is clicked: same result) |
| `seeded AI (seed 3)` | `d1_bot.atrec` on the game itself | nothing pinned: the engine's AI on the debate seed the UI draws from the run's rng (`check_debate_v2.py` `ui_debate_seed`) against the moves of ref `play.bot` on the same seed; the outcome matches ref |

Since v2 demo 4.3 each recording also clicks S07 L001-L003 on the vn before the debate, skips the opening step (S07
L004) and clicks the lines after it (L012-L015 after a win, L017-L019 after a loss) before the outcome panel. For the
four routes the check also compares the whole playback step by step with ref `sherefox_ref.v2.lines` (name plate, line
and system line of every step, in order; the opening step; the tell line `hint_who` / `hint` of every round, from
the AI's tell on the debate seed the UI draws), a hand-written sample of the chapter's §12 text for two to four
rounds per route (`CHAPTER_SAMPLE`, `CHAPTER_TELL`: the lines must show in the chapter's order, so a reading that
ref and the game share is still checked against the chapter), and the S07 lines on the vn with their name plates.

The harnesses (`tests/d1play_harnessA/` … `D/`, copies of the game; gitignored) are deleted when the check ends, and the
check fails if it leaves a `tmp*`／`d1shots-*` entry in `%TEMP%`. `--shots DIR` also writes review screenshots in
zh-TW and en (`xtatrium shot`): the claim picker in an ordinary round, a playback line, the 論破 cut-in, the endgame
prompt with the last gasp, the §7.5 round, both outcome panels.

The four routes also check every round's playback lines (E3, `check_lines`): from the ref's events of the round,
the system lines ch §12.0 calls for among BOTH_REBUT, CUT_EMPTY, MISS_WRONG, TOPPLE_MISS_FACT／WRONG, FOOLED,
FOG_REPEAT, CLASH, LASTCARD_HIT／NOHEAL／REMOVE, ZERO_WIN, KEY_BREAK／NORMAL, DENY_FACT and S07 L005／L006 are shown with
their numbers, none of the others is, and the 斷 stamp shows exactly when the player's combo resets (ruling 7).

```
uv run tests/check_d1_lines.py [--shots DIR]
```

Scripted debates (forced opponent, route A's loadout unless noted, harnesses `tests/d1play_harnessS1` … `S5`, recordings
`tests/d1_lines_S*.atrec`; all deleted at the end) for the lines the routes do not reach, with the same per-round
`check_lines`:

| Check | What it asserts |
|---|---|
| `S1` | 截斷 vs his 反駁 (BOTH_REBUT, no FOOLED), a clash, a 正論 拆台 on his fact (TOPPLE_MISS_FACT −10), a 拆台 that does not break L1 (TOPPLE_MISS_WRONG −5), 打迷糊仗 vs 反駁 twice (FOOLED once, then FOG_REPEAT), a sophistry cut on a fact (DENY_FACT), a 破竹 drop with the combo kept (no 斷) and an exposure with combo 1 (斷); English chosen in the settings overlay before round 4 (lines, round counter, `hachiku_text`, the record's rounds follow); no evidence chosen when a round starts (R4) |
| `S2` | a Break with one crack, his last card taken: LASTCARD_HIT with his recovery and LASTCARD_REMOVE, the debate goes on, then ZERO_WIN on the second zero; the Break round is clicked on `ui#cutin` and `ui#d1debate` while the cut-in plays; grade 3, a win |
| `S3` | both sides stall to round 20: a loss on credibility as ref says, UI_V2_TIME_UP |
| `S4` | E4, a loadout with the talking board: 破竹 held at 3 (HACHIKU_KEEP after the round's last system line, never at 0), 困獸 from round 5 (a sidestep's voided heal says nothing), his last card P05 hits with the recovery voided (LASTCARD_NOHEAL then LASTCARD_CORNERED), then ZERO_WIN |
| `S5` | E4: a cut sealed by last round's sidestep (CUT_SEALED), a sophistry 拆台 on another issue's fact (TOPPLE_MISS_WRONG −5), a sophistry 拆台 that knocks down a fact while he rebuts (DENY_FACT, OPP_REBUT_MISS) |

`--shots DIR` writes a TOPPLE_MISS_FACT line (S1) and a LASTCARD_HIT line (S2) in zh-TW and en.

## v2 demo: the D01 chapter (M3)

```
uv run tests/check_d1_m3.py [--shots DIR]
```

`check_d1_m3.py` regenerates `tests/d1_m3.atrec` (`tests/gen_d1_m3.py`) and replays it with `--ports` in zh-TW and en,
from the title's v2 entry (chapter 101; since M4a through the S01 paper, S02 / S03 and a clean warm-up, `gen_d1_story.py`
`story()`) to the debate's outcome panel:

| Check | What it asserts |
|---|---|
| `chapter [zh-TW]`, `[en]` | every hotspot's note (name, description, Arthur's comment, what is taken, the note line; PN3 only once HS04 and HS05 are both seen), all six places done; the evidence list (13 items), A01 and A04 appraised (result, Arthur's line, the count runs out, E02 can no longer be appraised), E01's private views (none, 01A, 01B, 01C, 01D) and 01A chosen; the notes page (5); the carry screen's first-visit line (gone on the second visit after Back), Ask Arthur pressed nine times against the S06 priority order (L008, L004+L005, L003, L006, L007, L011, L012, L012, then L012 with route A's nine chosen), the no-room line, the confirm list (what stays), L010; the debate's claim picker starting on 01A when E01 is chosen and on nothing for evidence without a view; route A's result (grade 1, 9 rounds, a win); nothing on stderr |
| `loadout` | what reached the debate (`xtatrium trace` of the harness's mirror signals): `d1Carry` = route A's nine, `d1Appraised` = A01, A04, `d1Notes` = the five notes, `d1PrivNote[E01]` = 01A |

The harness `tests/d1m3_harness/` (route A's pinned opponent from `gen_d1_play.py` plus the mirror flow; gitignored) is
deleted when the check ends, and the check fails if it leaves a `tmp*`／`d1m3shots-*` entry in `%TEMP%`. `--shots DIR`
writes the review screenshots (zh-TW and en): each place with its hotspots, a hotspot note, the evidence list with an
appraisal and with a private view, the notes page, the carry screen (first visit, an Arthur line, the confirm list,
L010), a playback line with the formula names and a stamp; and `DIR/overlays/` (every hotspot rectangle with its id over
each place, with ImageMagick).

### D01 story (M4a)

```
uv run tests/check_d1_story.py [--shots DIR]
```

`check_d1_story.py` regenerates `tests/d1_story_{clean,pass,fail}.atrec` and `tests/d1_story_ticks.json`
(`tests/gen_d1_story.py`) and replays them with `--ports` in zh-TW and en, from the title's v2 entry:

| Check | What it asserts |
|---|---|
| `clean`, `pass`, `fail` `[zh-TW]`, `[en]` | the S01 paper (headline, dateline, lead, page 1, no strip or engraving); every S02 and S03 line in script order with its name plate, staging and the chapter tab, the vn the only main screen; every warm-up line in the reference model's order (`ref sherefox_ref.v2.warmup`) with its speaker, the point, the mistakes count, the observations, `choosing` exactly on a point; L013 only on a clean pass, L005 on a mistake, L014 + L015 on the third; `world.d1Warmup` = pass_clean / pass / fail (`xtatrium trace`, zh-TW run); the investigation follows with 2 / 2 / 1 appraisals; the clean run reaches the carry screen; nothing on stderr |

Picks: clean W1 W2 W3; pass W2 (wrong), W1, W2, W1 (already used: wrong), W3; fail W2, W3, W1, W1. `--shots DIR` writes
the S01 paper, S02 with the landlady, S03 with Briggs and with Cedric, a point with the three observations, a wrong pick
(L005), the success (L013) and the failure (L014, L015). `tests/check_music.py` replays `d1_story_clean` for the D01
cues. The check fails if it leaves a `tmp*`／`d1storyshots-*` entry in `%TEMP%`.

`check_d1_play.py` (M2) now enters through the title's dev shortcut (`v2dev`, the D01 debate row with route A's set).

## Edge smoothing, msaa 1 vs msaa 4 (report aid)

`uv run tests/aa_compare.py OUTDIR [--screens title,debate] [--zoom N]` uses `xtatrium shot` (no window, frame-exact) to
render `full_run.atrec` at one tick per screen with the software renderer (reference), wgpu `--msaa 1` and wgpu
`--msaa 4`. For each screen it prints, per GPU mode against software, the pixels whose largest channel difference
exceeds 16 and the largest difference (also in `report.json`), and writes `zoom_<screen>.png` (sw | m1 | m4, 3x
nearest-neighbour, source range labelled). It is not a pass/fail check. Rerun it whenever XTAtrium pins a new XTFrame
tag and report the numbers to the framework session. `--against OLDDIR` also compares each mode with an earlier run (for example an uncompressed bundle
against a BC7 one) and writes `zoom_vs_<screen>.png`; the stamp and calligraphy cut-in frames come from the debate
recordings. Keep each tag's output outside the repo for comparison.

### D01 debate music (4.3)

`tests/check_music.py` also regenerates `tests/gen_d1_play.py`'s recordings and replays routes A, B and D on their
harnesses (deleted afterwards): title BGM01, S07 L001's silence, BGM07 (cut) when the debate starts, BGM08 at his first
破防, BGM09 on 論破, silence from S07 L007 (B, he gives up) or the loss (D, L016) and at L015 (A, B), BGM09 again with
L012 after B's silence; BGM10 (no track) on D's Reverse Break sends no command.
