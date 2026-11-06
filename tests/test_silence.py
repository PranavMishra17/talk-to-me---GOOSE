from proxy_core.silence import SilenceLadder


def test_order_and_once():
    s = SilenceLadder("goose")
    assert s.tick(5, None, False) is None
    assert s.tick(6, None, False) == "nudge"
    assert s.tick(7, None, False) is None  # once only
    assert s.tick(12, "goose", False) == "restate"
    assert s.tick(25, None, False) == "close"
    assert s.tick(99, None, False) is None


def test_no_skipping_rungs():
    s = SilenceLadder("goose")
    assert [s.tick(30, None, False) for _ in range(4)] == ["nudge", "restate", "close", None]


def test_suppressed():
    s = SilenceLadder("goose")
    assert s.tick(30, "maya", False) is None
    assert s.tick(30, "human", False) is None
    assert s.tick(30, None, True) is None
    assert s.tick(30, None, False) == "nudge"


def test_reset():
    s = SilenceLadder("goose")
    s.tick(6, None, False)
    s.reset()
    assert s.tick(6, None, False) == "nudge"
