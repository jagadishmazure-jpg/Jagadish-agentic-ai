import solution


def test_billing_wins():
    assert solution.route("Please refund this invoice") == "billing"


def test_tech():
    assert solution.route("VPN password reset") == "tech"


def test_general():
    assert solution.route("hello there") == "general"
