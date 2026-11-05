# Tests

Headless playthrough checks for the flows (`docs/flows.md`). They replay recorded title/paper/vn clicks with
`xtatrium run --replay ... --ports` and compare the UI port trace with the data tables (`data/*.json`,
`strings/*.csv`).

## Prerequisites

- An XTAtrium checkout with a Release build of the CLI:
  `dotnet build src\XTAtrium.Headless -c Release` (run inside the XTAtrium checkout).
- The packed UI bundle: `xtatrium pack --game E:\coding4\Sherefox` (after any change under `ui/`).
- [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv` or `pip install uv`); the scripts use the standard
  library only.

Environment (both optional):

| Variable | Default |
|---|---|
| `XTATRIUM` | `E:/coding4/XTArtrium` (the checkout whose `src/XTAtrium.Headless/bin/Release/net10.0/xtatrium.exe` is used) |
| `XTATRIUM_XTFRAME_DIR` | `<XTATRIUM>/artifacts/xtframe` |

## Run

From the project root:

```
uv run tests/check_playthrough.py
uv run tests/check_playthrough.py --frames <dir>     # also writes title.png, vn_line.png, paper_ch2.png
```

It regenerates the recordings first (`tests/gen_playthrough.py`, from the `steps` and `script` tables), then runs:

| Check | Recording | What it asserts |
|---|---|---|
| data | — | every vn scene of Ch.1-3 starts with its heading row and has only playable lines after it |
| `ch1_playthrough[zh-TW]`, `[en]` | `ch1_playthrough.atrec` (`--lang en` for the second) | each of Ch.1's 21 playable lines is shown once, in order, with the right text and name plate, while vn is the only visible main screen; the Ch.1 paper shows both pages; the run ends on the Ch.2 opening paper, page 1, with the Ch.1 result strip; nothing on stderr |
| `full_run` | `full_run.atrec` | all 54 playable lines of Ch.1-3 in order; the four papers (CH01..CH04_OPEN) with their result strips; the run ends on the title's end card (`title.ended`) |
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
