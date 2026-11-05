"""Portable deterministic RNG for the opponent policy.

SplitMix64 is used because it is trivial to port bit-for-bit to other languages
(C#: ulong arithmetic with unchecked wraparound). The policy only ever calls
``roll(n)``; the order of ``roll`` calls is part of the trace contract and is
documented in ``policy.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

_MASK = (1 << 64) - 1


@dataclass
class SplitMix64:
    state: int

    def next_u64(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & _MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK
        return z ^ (z >> 31)

    def roll(self, n: int) -> int:
        """Uniform-ish integer in [0, n). Defined as next_u64() % n (bias accepted)."""
        if n <= 0:
            raise ValueError("roll(n) needs n > 0")
        return self.next_u64() % n


class ScriptedRng:
    """Replays a fixed list of roll results; used to force policy branches in tests."""

    def __init__(self, values: list[int]):
        self._values = list(values)
        self.calls: list[tuple[int, int]] = []

    def roll(self, n: int) -> int:
        if not self._values:
            raise AssertionError("ScriptedRng exhausted")
        v = self._values.pop(0)
        if not 0 <= v < n:
            raise AssertionError(f"scripted roll {v} out of range for n={n}")
        self.calls.append((n, v))
        return v
