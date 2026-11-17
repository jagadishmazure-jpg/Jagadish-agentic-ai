import solution


def test_payload():
    assert solution.health() == {"status": "ok"}
