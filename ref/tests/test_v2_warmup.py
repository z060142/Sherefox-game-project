"""The v2 demo D01 warm-up (ch §2 S04): the line order and the outcome for each kind of run."""

import pytest

from sherefox_ref.v2.data import load_chapter
from sherefox_ref.v2.warmup import play


def test_clean_pass():
    r = play(["W1", "W2", "W3"])
    assert r.shown == ("L001", "L002", "L003", "L004", "L006", "L007", "L008", "L009", "L010", "L011", "L012", "L013")
    assert (r.outcome, r.mistakes) == ("pass_clean", 0)


def test_pass_with_mistakes_repeats_the_point_and_drops_l013():
    r = play(["W2", "W1", "W2", "W1", "W3"])   # W1 again for point 3: already used, so wrong
    assert r.shown == ("L001", "L002", "L005", "L002", "L003", "L004", "L006", "L007", "L008", "L009", "L005", "L009",
                       "L010", "L011", "L012")
    assert (r.outcome, r.mistakes) == ("pass", 2)


def test_three_mistakes_fail():
    r = play(["W3", "W1", "W1", "W3", "W2"])   # the third mistake ends it at once: no L005 before L014
    assert r.shown == ("L001", "L002", "L005", "L002", "L003", "L004", "L006", "L005", "L006", "L014", "L015")
    assert (r.outcome, r.mistakes, r.used) == ("fail", 3, 4)
    r = play(["W2", "W3", "W1", "W1", "W1"])
    assert r.shown == ("L001", "L002", "L005", "L002", "L005", "L002", "L003", "L004", "L006", "L014", "L015")
    assert (r.outcome, r.mistakes, r.used) == ("fail", 3, 4)


def test_outcomes_set_the_appraisal_limit():
    ch = load_chapter()
    assert [ch.warmup[o]["appraisal_limit"] for o in ("pass_clean", "pass", "fail")] == [2, 2, 1]


def test_unfinished_picks_raise():
    with pytest.raises(ValueError):
        play(["W1"])
