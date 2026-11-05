# sherefox-ref

Executable reference model ("golden oracle") of the 狐耳摩斯 debate (論戰) rules for
Ch.1-3. Pure Python standard library; pytest is the only dev dependency.

## Setup

Install uv (https://docs.astral.sh/uv/): `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`
on Windows or `curl -LsSf https://astral.sh/uv/install.sh | sh` elsewhere. Then:

    uv sync
    uv run pytest            # route-table acceptance tests (xfail = design-doc findings)
    uv run python -m sherefox_ref.trace traces   # dump golden JSON traces of the routes

## Layout

- `src/sherefox_ref/model.py` — cards, nodes, board, case config, debate state, actions.
- `src/sherefox_ref/rules.py` — link judging, segment checks, damage formulas, break threshold.
- `src/sherefox_ref/resolve.py` — `resolve_round(state, player_action, opponent_action)`
  following 系統規格 A-1 settlement order; returns `(new_state, events)`.
- `src/sherefox_ref/policy.py` — opponent action choice, tells, fox instinct; driven by an
  injected chooser (`RngChooser(SplitMix64(seed))`); the draw order is a trace contract.
- `src/sherefox_ref/warmup.py` — 熱身小論戰 (A-13).
- `src/sherefox_ref/fixtures.py` — Ch.1 (Arthur), Ch.2 (Fitch), Ch.3 (Pierce + warmup).
- `src/sherefox_ref/trace.py` — golden traces of the recommended routes.

Every place where the design text is silent or contradictory is marked `SPEC-QUESTION`
in the source; inferred fixture data is marked `INFERRED`.
