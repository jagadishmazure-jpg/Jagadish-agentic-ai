import solution


def test_empty():
    assert solution.estimate_tokens("") == 0


def test_short():
    assert solution.estimate_tokens("abcd") == 1


def test_longer():
    assert solution.estimate_tokens("a" * 8) == 2
