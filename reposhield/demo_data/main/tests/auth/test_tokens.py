from auth.tokens import issue_token, verify_token


def test_roundtrip():
    assert verify_token(issue_token("ana", "s"), "s") == "ana"


def test_expired_token_rejected():
    token = issue_token("ana", "s", ttl=10, now=1000)
    assert verify_token(token, "s", now=2000) is None


def test_tampered_token_rejected():
    token = issue_token("ana", "s")
    assert verify_token(token + "x", "s") is None
    assert verify_token(token, "other-secret") is None
