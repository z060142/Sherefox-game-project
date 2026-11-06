"""The xtatrium CLI the checks run (shared by every tests/check_*.py).

Resolution order (no machine-specific defaults):
1. XTATRIUM_EXE: the CLI to use.
2. XTATRIUM_SDK: an installed SDK directory holding xtatrium(.exe) (used when XTATRIUM is not set).
3. XTATRIUM: an XTAtrium checkout; its Release build of src/XTAtrium.Headless is used.
4. `xtatrium` on PATH.
When none of them yields an existing executable the import fails with a message. The XTFrame runtime directory is
XTATRIUM_XTFRAME_DIR, else the SDK's xtframe/, the checkout's artifacts/xtframe, or xtframe/ next to the CLI.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_NAME = "xtatrium.exe" if os.name == "nt" else "xtatrium"


def _resolve() -> tuple[Path, Path]:
    env = os.environ
    if env.get("XTATRIUM_EXE"):
        exe = Path(env["XTATRIUM_EXE"])
        return exe, exe.parent / "xtframe"
    if env.get("XTATRIUM_SDK") and not env.get("XTATRIUM"):
        sdk = Path(env["XTATRIUM_SDK"])
        if (sdk / _NAME).exists():
            return sdk / _NAME, sdk / "xtframe"
    if env.get("XTATRIUM"):
        root = Path(env["XTATRIUM"])
        exe = root / "src" / "XTAtrium.Headless" / "bin" / "Release" / "net10.0" / _NAME
        if exe.exists():
            return exe, root / "artifacts" / "xtframe"
    found = shutil.which("xtatrium")
    if found:
        return Path(found), Path(found).parent / "xtframe"
    raise SystemExit(
        "error: the xtatrium CLI was not found. Set XTATRIUM_EXE (the executable), XTATRIUM_SDK (an installed SDK "
        "directory) or XTATRIUM (a framework checkout with a Release build of src/XTAtrium.Headless), or put "
        "xtatrium on PATH (see tests/README.md).")


EXE, _XTFRAME = _resolve()
XTFRAME = os.environ.get("XTATRIUM_XTFRAME_DIR", str(_XTFRAME))


def compile_game(game: Path = Path(__file__).resolve().parent.parent) -> None:
    """`xtatrium compile --game` (AT-036): every flow of the game compiled with its endpoints resolved as `run`
    resolves them; the checks that pack or run the game call it first, so an endpoint error stops them at once."""
    import subprocess
    env = dict(os.environ, XTATRIUM_XTFRAME_DIR=XTFRAME)
    p = subprocess.run([str(EXE), "compile", "--game", str(game)], capture_output=True, text=True, encoding="utf-8",
                       env=env)
    if p.returncode != 0:
        raise SystemExit(f"FAIL xtatrium compile --game {game} (exit {p.returncode})\n{p.stdout}{p.stderr}")
    print(p.stdout.strip() or "compile: ok")
