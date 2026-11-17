import solution


def test_object_in_prose():
    assert solution.parse_choice('sure, {"choice": "b"} thanks') == "b"


def test_missing():
    assert solution.parse_choice("no json here") is None


def test_wrong_shape():
    assert solution.parse_choice('{"choice": 1}') is None
