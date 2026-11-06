# Sherefox (狐耳摩斯) game project

- A 2D detective AVG built on XTAtrium (game logic: Atrium Script `.xtflow`, data tables) with XTFrame UI for every screen. It lives outside the XTAtrium repo and is run by pointing XTAtrium at this directory.
- Design source of truth: the Claude Docs design doc 《狐耳摩斯》第一作 遊戲企劃案 (https://claude.ai/artifact/LQDVV6KG7qX32iaqWw4Pv2). Precedence when tabs disagree: 數值總表 > 系統規格 (incl. Appendix A) > 各章設計 > 完整劇本 > 設計總覽. Snapshots for offline reading are in `docs/design/` (`_raw/` = machine-converted text; may be stale, the live doc wins).
- Do not invent design. If the doc is silent or contradictory, stop and report the question.
- Never route around XTAtrium: no game-side C#. Missing framework capability = a generic request to the XTAtrium framework owner, not a workaround in this repo.
- Current milestone: playable prototype of Ch.1-3, bilingual zh-TW / en with a runtime switch. Calligraphy cut-ins stay Chinese in both languages.

## Conventions
- Code, identifiers, comments, commit messages, CLI output: English. Design notes under `docs/`: 繁體中文 (台灣).
- Python tooling uses uv (`uv run tools/...`); no global installs.
- Strings are keyed by the design doc's IDs (系統規格 §八/§七 IDs; script lines `SCR_CH01_S<scene>_L<line>`); never hard-code display text in logic.
- Determinism: no wall clock, no unseeded randomness, no iteration order that depends on hash maps.
- Commit prefixes: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`, `test:`.

## Running
- Run from the repo root with the game given as `.`. Machine-specific locations are never written in this repo; they come from environment variables (on this machine see your local notes): `XTATRIUM_SDK` (installed SDK directory, built from the framework repo with `tools/install-sdk.ps1 -Out <dir>`; rebuild after framework bumps), `XTATRIUM` (framework checkout), `XTATRIUM_EXE` (the CLI itself), `XTATRIUM_XTFRAME_DIR` (XTFrame runtime). With none set, `xtatrium` on PATH is used. Details in `tests/README.md`.
- SDK: `"$XTATRIUM_SDK/xtatrium" pack|run|play|publish --game .`.
- Look things up with the CLI instead of reading framework docs, manifests or the node catalog: `xtatrium inspect --game . [--signals|--ports|--tables|--collections|--strings|--nodes] [--filter GLOB] [--json]` lists every signal, UI port (write as `ui#<ui>.<port>`), table with columns, collection, string coverage and node signature; `xtatrium schema game|prefab|scene|xtflow` is the field reference. Open the framework docs only for behaviour these don't answer.
- From the framework dev repo instead: `dotnet run --project <XTATRIUM>/src/XTAtrium.Headless -c Release -- <command> --game .`.
- Data: `uv run tools/build_data.py`; flows: `uv run tools/gen_flows.py`, `uv run tools/gen_debate.py`; checks: `uv run tests/check_playthrough.py`, `tests/check_debate.py`, `tests/check_policy.py`.

## Layout
- `docs/design/` design snapshots and notes; `data/` game data tables (generated or authored JSON); `strings/` localization; `flows/` orchestration graphs; `ui/` boards and UI project; `tools/` build/extraction scripts (Python, uv); `ref/` executable reference model of the rules (Python) used as golden traces.
