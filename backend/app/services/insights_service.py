"""
GlobeLens AI — InsightsService

Pure helpers behind the analytics endpoints. Deliberately free of database,
cache and framework imports so they can be unit-tested without a running
stack, and so a query change cannot silently alter the wording the product
shows a user about their own reading.
"""
from typing import Iterable, Optional

# Leans grouped into the three buckets a plain-language sentence can name.
LEFT_LEANS = {"LEFT", "CENTER_LEFT"}
RIGHT_LEANS = {"RIGHT", "CENTER_RIGHT"}


def weekly_bias_message(weekly_ids: Iterable, leans_per_event: dict) -> Optional[str]:
    """
    Describe the source spread of the events saved in the last seven days.

    Deliberately silent below three saved events: a couple of saves say nothing
    about reading habits, and the product does not assert conclusions about a
    reader from too little data. The wording reports the sources behind the
    saves, never what the user "read".
    """
    counts = {"left": 0, "center": 0, "right": 0}
    events = 0
    for event_id in weekly_ids:
        leans = leans_per_event.get(event_id)
        if not leans:
            continue
        events += 1
        for name in leans:
            if name in LEFT_LEANS:
                counts["left"] += 1
            elif name in RIGHT_LEANS:
                counts["right"] += 1
            else:
                counts["center"] += 1

    total = sum(counts.values())
    if events < 3 or total == 0:
        return None

    bucket, hits = max(counts.items(), key=lambda kv: kv[1])
    if hits == 0:
        return None
    share = round((hits / total) * 100)
    return (
        f"This week, {share}% of the sources behind the {events} events you "
        f"saved lean {bucket}."
    )


def build_topic_trends(current: dict, previous: dict, limit: int) -> list:
    """
    Compare per-topic counts across two adjacent windows.

    A topic with no events in the previous window is reported as new rather
    than as an infinite percentage increase, and the list is ordered biggest
    gainer first so "topics gaining coverage" reads from the top.
    """
    topics = []
    for topic in set(current) | set(previous):
        cur = current.get(topic, 0)
        prev = previous.get(topic, 0)
        delta = cur - prev
        topics.append({
            "topic": topic,
            "current": cur,
            "previous": prev,
            "delta": delta,
            "change_pct": round(delta / prev * 100) if prev else None,
            "direction": "up" if delta > 0 else "down" if delta < 0 else "flat",
            "is_new": prev == 0 and cur > 0,
        })

    # Biggest gainers first, then the largest topics as a tie-break.
    topics.sort(key=lambda t: (t["delta"], t["current"]), reverse=True)
    return topics[:limit]
