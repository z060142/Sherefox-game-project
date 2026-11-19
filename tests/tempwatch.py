"""The temp-leak check of the D01 checks (tests/README.md): count only what this run creates.

`%TEMP%` is shared with every other process on the machine, so "new entries named tmp*" also caught files that
unrelated programs create there (tmp<guid>.tmp). Instead a run gets its own directory under %TEMP%
(`sherefox-run-*`): the check points TEMP / TMP / TMPDIR and Python's tempfile at it for itself and for every child
process (the xtatrium CLI included), so anything our tools leave behind lands there. At the end:

- anything still in the run directory is a leak (ours, by construction);
- in the real %TEMP%, a new entry with one of our own prefixes is a leak too (a tool that ignores TEMP);

then the run directory is removed. Nothing else in %TEMP% is looked at.

    with TempWatch() as tw:
        ... run the checks ...
    leaks = tw.leaks   # set on exit
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

# every prefix our tools give a temp entry (tests/*.py mkdtemp / TemporaryDirectory prefixes)
OUR_PREFIXES = ("sherefox-", "d1shots-", "d1m3shots-", "d1storyshots-", "d1linesshots-", "d1fullshots-")
ENV = ("TEMP", "TMP", "TMPDIR")


class TempWatch:
    def __init__(self) -> None:
        self.real = Path(tempfile.gettempdir())
        self.dir: Path | None = None
        self.leaks: list[str] = []
        self._env: dict = {}
        self._before: set[str] = set()

    def __enter__(self) -> "TempWatch":
        self._before = {n for n in os.listdir(self.real) if n.startswith(OUR_PREFIXES)}
        self.dir = Path(tempfile.mkdtemp(prefix="sherefox-run-", dir=self.real))
        self._env = {k: os.environ.get(k) for k in ENV}
        for k in ENV:
            os.environ[k] = str(self.dir)
        self._tempdir = tempfile.tempdir
        tempfile.tempdir = str(self.dir)
        import atexit
        atexit.register(shutil.rmtree, self.dir, True)   # a check that stops early still removes the run directory
        return self

    def __exit__(self, *exc) -> None:
        tempfile.tempdir = self._tempdir
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        inside = sorted(os.listdir(self.dir)) if self.dir and self.dir.exists() else []
        outside = sorted(n for n in os.listdir(self.real) if n.startswith(OUR_PREFIXES) and n not in self._before
                         and self.dir is not None and n != self.dir.name)
        self.leaks = [f"{self.dir.name}/{n}" for n in inside] + outside
        if self.dir is not None:
            shutil.rmtree(self.dir, ignore_errors=True)
