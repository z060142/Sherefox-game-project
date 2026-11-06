# Tests

Headless playthrough checks for the flows (`docs/flows.md`). They replay recorded title/paper/vn clicks with
`xtatrium run --replay ... --ports` and compare the UI port trace with the data tables (`data/*.json`,
`strings/*.csv`).

## Prerequisites

- The XTAtrium CLI at framework commit 5aad137 or later (AT-046: `atrium.ui.list` field references and
  `atrium.textf`; AT-047: `bare` value arrays; the flows do not compile on older builds): the SDK built with
  `pwsh <XTAtrium>\tools\install-sdk.ps1 -Out E:\coding4\xtatrium-sdk`, or a Release build of an XTAtrium checkout
  (`dotnet build src\XTAtrium.Headless -c Release`).
- The packed UI bundle: `xtatrium pack --game E:\coding4\Sherefox` (after any change under `ui/`).
- AT-036 (`xtatrium compile --game`, framework 4352f29 or later): `check_case.py`, `check_playthrough.py` and
  `check_debate_play.py` first run `xtatrium compile --game E:\coding4\Sherefox` (`tests/xt_cli.py` `compile_game`)
  and stop when an endpoint does not resolve. By hand: `xtatrium compile --game E:\coding4\Sherefox`.
- [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv` or `pip install uv`); the scripts use the standard
  library only.

Environment (both optional):

| Variable | Default |
|---|---|
| `XTATRIUM_EXE` | — (the CLI to use; overrides the rest) |
| `XTATRIUM_SDK` | `E:/coding4/xtatrium-sdk` (used by `check_playthrough.py` and `check_case.py` when it exists and `XTATRIUM` is not set) |
| `XTATRIUM` | `E:/coding4/XTArtrium` (the checkout whose `src/XTAtrium.Headless/bin/Release/net10.0/xtatrium.exe` is used) |
| `XTATRIUM_XTFRAME_DIR` | the SDK's `xtframe/`, or `<XTATRIUM>/artifacts/xtframe` |

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
xtatrium run --game E:/coding4/Sherefox --replay tests/ch1_playthrough.atrec --ticks 447 --ports
xtatrium play --game E:/coding4/Sherefox --replay tests/ch1_playthrough.atrec
```

The recordings name the game as `E:/coding4/Sherefox` in their header; pass `--game` with exactly that string, or
the CLI warns that the recording's game differs. The recordings carry no hash checkpoints (they are generated, not
recorded), so give `--ticks` (printed by `uv run tests/gen_playthrough.py`).

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
| `ch2_tailwrong` (`play_harness`) | `ch2_debate`'s route up to R4 (the break), R5 (the tail) answered with an observe | the tail's result line is `SCR_CH02_S05_L047` (「（若尾聲出錯牌）」, design confirmed), not `MSG_TAIL_WRONG` |
| `ch3_warmfail` (`warmfail_harness`: the game with the warmup's mistake limit 0) | Ch.3 from the title: paper, vn, the warmup (E03_05), up to the investigation | the failure wrap-up S04 F001-F004 (`script.cue` postLose) instead of L006-L009, the investigation opening with `ART_NO_REPORT` (the case's trust 2), the music moments (`--trace`: BGM01, BGM02, BGM07, BGM05; `docs/flows.md` §4.10). The shipped warmup cannot be failed (both hand cards refute the claim), hence the harness |

M5c also checks, in `ch1_debate` / `ch2_debate` / `ch3_debate`, the result's 讀對預兆 row (`UI_RES_READS`, hit = the ref
route's reads, `tests/debate_routes.py` `round_read`), in `ch2_debate` the `preview_vs` of every round (the ref
resolution of the locked action against the opponent's actual action; the harness tells are clear), and in
`ch3_debate` the warmup's passed wrap-up (L006-L009, postWin).

Texts the flows fill with `atrium.textf` (the counters, the round, the cost line) are compared with the zh-TW
template filled the same way (`zf()`), not with a pre-expanded key.

The story playthroughs (`check_playthrough.py`) now go through every warmup, debate and result step the shortest
sure way (`gen_debate_play.minimal`: the opening lines, the warmup's first card and its wrap-up lines, observe until
the debate ends, continue, the lose lines), so their line lists include the result scenes' lose branch and the
papers' strips are the lose variants. Their investigations click once per reaction line, press 結束蒐證 twice (the
first press warns) and close the missed-cards message (`gen_case.end`).
`check_debate.py`, `check_policy.py` and `check_playthrough.py` use the CLI of `tests/xt_cli.py` (`XTATRIUM_EXE`,
else the installed SDK, else the `XTATRIUM` checkout).
