import solution


def test_under_budget():
    assert solution.should_stop(2, 8) is False


def test_at_budget():
    assert solution.should_stop(8, 8) is True


def test_zero():
    assert solution.should_stop(0, 0) is True
