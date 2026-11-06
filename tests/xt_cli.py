"""The xtatrium CLI the checks run (shared by every tests/check_*.py).

XTATRIUM_EXE overrides everything; else the installed SDK (XTATRIUM_SDK, default E:/coding4/xtatrium-sdk) when it
exists and XTATRIUM is not set; else the Release build of the XTAtrium checkout (XTATRIUM, default
E:/coding4/XTArtrium). Its XTFrame runtime: XTATRIUM_XTFRAME_DIR, else the SDK's xtframe/ or the checkout's
artifacts/xtframe.
"""

from __future__ import annotations

import os
from pathlib import Path

_NAME = "xtatrium.exe" if os.name == "nt" else "xtatrium"
XTATRIUM = Path(os.environ.get("XTATRIUM", "E:/coding4/XTArtrium"))
SDK = Path(os.environ.get("XTATRIUM_SDK", "E:/coding4/xtatrium-sdk"))
if os.environ.get("XTATRIUM_EXE"):
    EXE = Path(os.environ["XTATRIUM_EXE"])
    _XTFRAME = EXE.parent / "xtframe"
elif (SDK / _NAME).exists() and "XTATRIUM" not in os.environ:
    EXE, _XTFRAME = SDK / _NAME, SDK / "xtframe"
else:
    EXE = XTATRIUM / "src" / "XTAtrium.Headless" / "bin" / "Release" / "net10.0" / _NAME
    _XTFRAME = XTATRIUM / "artifacts" / "xtframe"
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
