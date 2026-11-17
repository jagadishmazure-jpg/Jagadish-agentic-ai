import solution


def test_one_address():
    assert solution.redact_emails("write ada@example.com today") == "write [redacted] today"


def test_two_addresses():
    text = "a@example.com and b.smith@example.org"
    assert solution.redact_emails(text) == "[redacted] and [redacted]"


def test_no_address():
    assert solution.redact_emails("no address here") == "no address here"
