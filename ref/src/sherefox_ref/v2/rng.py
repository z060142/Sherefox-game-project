"""The v2 debate's random streams: a Python port of XTAtrium's `atrium.rng.stream` node (XTAtrium 04 §4.3).

`Stream` is bit-for-bit the node: xoshiro128** 1.1 state s0..s3 (the algorithm of the framework's Simulation.Rng),
seeded by expanding a 64-bit seed with SplitMix64 (the low 32 bits of four successive outputs become s0, s1, s2,
s3), and `roll(n)` is an unbiased integer in [0, n) by Lemire's multiply-shift rejection (Rng.NextInt(0, n)). The
number conversions are the node's: a seed is rounded half away from zero, clamped into ±2^53 and taken as a 64-bit
two's complement; n is rounded half away from zero and clamped at 2147483647; n < 1 gives 0 and consumes nothing.

`DebateRng` is the debate's randomness (docs/debate-engine-v2.md §3.4): one stream per draw of the policy's trace
contract (policy.py: tendency, clarity, base, slip, decoy), each seeded from the debate seed as seed * 8 + k with k
the draw's number in the contract. Each stream is drawn at most once per decision, so the engine can draw each
from its own `atrium.rng.stream` node in one dispatch; a stream's draws never depend on its own earlier values in
the same decision (one node cannot gate its own roll: XTAtrium 04 §4.3, cycles include pulse edges).
"""

from __future__ import annotations

import math

M32 = (1 << 32) - 1
M64 = (1 << 64) - 1
MAX_SEED = 1 << 53
MAX_N = 2147483647

# the draws of the policy's trace contract, numbered as in policy.py
DRAWS = ("tendency", "clarity", "base", "slip", "decoy")
SEED_STRIDE = 8


def _round_away(x: float) -> float:
    """Math.Round(x, MidpointRounding.AwayFromZero) for a finite double."""
    a = abs(x)
    r = math.floor(a)
    if a - r >= 0.5:  # exact: a - floor(a) has no rounding error
        r += 1
    return -float(r) if x < 0 else float(r)


def to_seed(x) -> int:
    """The node's seed of a number: non-finite 0; rounded half away from zero; clamped into ±2^53; 64-bit."""
    if isinstance(x, int):
        r = x
    else:
        if not math.isfinite(x):
            return 0
        r = int(_round_away(float(x)))
    r = max(-MAX_SEED, min(MAX_SEED, r))
    return r & M64


def to_n(x) -> int:
    """The node's n of a roll: non-finite 0; rounded half away from zero; clamped at 2147483647."""
    if isinstance(x, int):
        r = x
    else:
        if not math.isfinite(x):
            return 0
        r = int(_round_away(float(x)))
    return max(-(1 << 31), min(MAX_N, r))


def _rotl(x: int, k: int) -> int:
    return ((x << k) | (x >> (32 - k))) & M32


class Stream:
    """One `atrium.rng.stream`: its own xoshiro128** state, seeded from an integer."""

    def __init__(self, seed=0):
        self.reset(seed)

    def reset(self, seed) -> None:
        x = to_seed(seed)
        s = []
        for _ in range(4):
            x = (x + 0x9E3779B97F4A7C15) & M64
            z = x
            z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M64
            z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M64
            s.append((z ^ (z >> 31)) & M32)
        self.s = s

    def next_u32(self) -> int:
        s0, s1, s2, s3 = self.s
        result = (_rotl((s1 * 5) & M32, 7) * 9) & M32
        t = (s1 << 9) & M32
        s2 ^= s0
        s3 ^= s1
        s1 ^= s2
        s0 ^= s3
        s2 ^= t
        s3 = _rotl(s3, 11)
        self.s = [s0, s1, s2, s3]
        return result

    def roll(self, n) -> int:
        """Unbiased integer in [0, n) (Rng.NextInt(0, n)); 0 without consuming state when n < 1."""
        rng = to_n(n)
        if rng < 1:
            return 0
        m = self.next_u32() * rng
        low = m & M32
        if low < rng:
            threshold = ((1 << 32) - rng) % rng
            while low < threshold:
                m = self.next_u32() * rng
                low = m & M32
        return m >> 32


class DebateRng:
    """The streams of one debate, seeded from the debate seed (stream k: seed * 8 + k, k = 1..5 as in DRAWS)."""

    def __init__(self, seed: int):
        self.seed = seed
        self.streams = {name: Stream(stream_seed(seed, name)) for name in DRAWS}

    def for_draw(self, name: str) -> Stream:
        return self.streams[name]


def stream_seed(seed: int, name: str) -> int:
    return seed * SEED_STRIDE + DRAWS.index(name) + 1
