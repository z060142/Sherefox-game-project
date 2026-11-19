"""The v2 debate's random streams (rng.py): the port of XTAtrium's atrium.rng.stream."""

from sherefox_ref.v2.rng import DRAWS, DebateRng, Stream, stream_seed, to_n, to_seed


def test_reference_sequences_of_the_framework_node():
    s = Stream(0)
    assert [s.roll(6) for _ in range(8)] == [4, 1, 0, 3, 3, 5, 1, 3]
    s = Stream(12345)
    assert [s.roll(100) for _ in range(8)] == [25, 21, 77, 30, 24, 83, 64, 99]


def test_same_seed_same_sequence_and_reset():
    a, b = Stream(77), Stream(77)
    xs = [a.roll(1000) for _ in range(50)]
    assert xs == [b.roll(1000) for _ in range(50)]
    a.reset(77)
    assert [a.roll(1000) for _ in range(50)] == xs


def test_n_below_one_gives_zero_and_consumes_nothing():
    a, b = Stream(5), Stream(5)
    assert [a.roll(0), a.roll(-3), a.roll(0.4)] == [0, 0, 0]
    assert a.s == b.s
    assert a.roll(10) == b.roll(10)


def test_number_conversions():
    assert to_seed(2.5) == 3 and to_seed(-2.5) == (-3) & ((1 << 64) - 1)
    assert to_seed(float("nan")) == 0 and to_seed(1e300) == 1 << 53
    assert to_n(2.5) == 3 and to_n(0.5) == 1 and to_n(0.49) == 0 and to_n(1e12) == 2147483647
    s1, s2 = Stream(6), Stream(5.5)  # rounded half away from zero
    assert s1.s == s2.s


def test_unbiased_roll_stays_in_range_for_large_n():
    s = Stream(3)
    for n in (1, 2, 3, 7, 1 << 30, 2147483647):
        for _ in range(20):
            assert 0 <= s.roll(n) < n


def test_debate_streams_are_seeded_per_draw():
    d = DebateRng(42)
    for k, name in enumerate(DRAWS, start=1):
        assert stream_seed(42, name) == 42 * 8 + k
        assert d.for_draw(name).s == Stream(42 * 8 + k).s
    # streams are independent: rolling one leaves the others alone
    d.for_draw("base").roll(100)
    assert d.for_draw("clarity").s == Stream(42 * 8 + 2).s
