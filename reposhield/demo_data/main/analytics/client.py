EVENTS = []


def track(event: str, **props) -> None:
    EVENTS.append({"event": event, **props})
