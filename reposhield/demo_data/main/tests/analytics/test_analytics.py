from analytics.client import EVENTS, track


def test_track_appends():
    n = len(EVENTS)
    track("x", a=1)
    assert EVENTS[-1] == {"event": "x", "a": 1} and len(EVENTS) == n + 1
