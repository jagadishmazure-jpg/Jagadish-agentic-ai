import solution


def test_small_set_stays_a_prompt():
    assert solution.choose(12) == "prompt"


def test_boundary():
    assert solution.choose(50) == "finetune"


def test_large_set():
    assert solution.choose(400) == "finetune"
