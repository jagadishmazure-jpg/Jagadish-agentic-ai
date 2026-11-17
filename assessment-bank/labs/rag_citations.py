import solution


def test_cited():
    assert solution.sentences_are_cited("Carry over 5 days [HR-PTO-2].")


def test_bare_sentence():
    assert solution.sentences_are_cited("Carry over 5 days.") is False


def test_empty():
    assert solution.sentences_are_cited("")
