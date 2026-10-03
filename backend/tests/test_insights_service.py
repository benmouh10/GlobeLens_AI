"""
Hermetic unit tests for the pure analytics helpers.

These import nothing that needs a database, cache or LLM, so they are safe to
gate CI on. They pin the exact wording and ranking rules the product relies on:
the sentence talks about the sources behind what a user saved (never what they
"read"), and a topic with no prior coverage is reported as new rather than as an
infinite percentage jump.
"""
from app.services.insights_service import build_topic_trends, weekly_bias_message


class TestWeeklyBiasMessage:
    def test_silent_below_three_saved_events(self):
        ids = ["a", "b"]
        leans = {"a": {"LEFT"}, "b": {"RIGHT"}}
        assert weekly_bias_message(ids, leans) is None

    def test_silent_when_none_of_the_events_have_source_leans(self):
        ids = ["a", "b", "c"]
        leans = {"a": {"LEFT"}, "b": {"LEFT"}}
        assert weekly_bias_message(ids, leans) is None

    def test_reports_sources_behind_saves_not_browsing(self):
        ids = ["a", "b", "c"]
        leans = {"a": {"LEFT"}, "b": {"LEFT"}, "c": {"CENTER"}}
        message = weekly_bias_message(ids, leans)
        assert message == (
            "This week, 67% of the sources behind the 3 events you saved lean left."
        )
        assert "read" not in message.lower()

    def test_center_is_its_own_bucket(self):
        ids = ["a", "b", "c"]
        leans = {"a": {"CENTER"}, "b": {"CENTER"}, "c": {"RIGHT"}}
        assert weekly_bias_message(ids, leans).endswith("lean center.")

    def test_center_left_and_center_right_count_toward_their_sides(self):
        ids = ["a", "b", "c"]
        leans = {"a": {"CENTER_LEFT"}, "b": {"CENTER_LEFT"}, "c": {"CENTER_RIGHT"}}
        assert weekly_bias_message(ids, leans).endswith("lean left.")


class TestBuildTopicTrends:
    def test_new_topic_is_flagged_and_has_no_percentage(self):
        topics = build_topic_trends({"TECHNOLOGY": 2}, {}, limit=6)
        assert topics == [
            {
                "topic": "TECHNOLOGY",
                "current": 2,
                "previous": 0,
                "delta": 2,
                "change_pct": None,
                "direction": "up",
                "is_new": True,
            }
        ]

    def test_growth_reports_percentage_and_direction(self):
        topics = build_topic_trends({"POLITICS": 3}, {"POLITICS": 2}, limit=6)
        assert topics[0]["delta"] == 1
        assert topics[0]["change_pct"] == 50
        assert topics[0]["direction"] == "up"
        assert topics[0]["is_new"] is False

    def test_decline_reports_negative_values(self):
        topics = build_topic_trends({"WORLD": 1}, {"WORLD": 4}, limit=6)
        assert topics[0]["delta"] == -3
        assert topics[0]["change_pct"] == -75
        assert topics[0]["direction"] == "down"

    def test_flat_topic_keeps_zero_delta(self):
        topics = build_topic_trends({"SPORTS": 2}, {"SPORTS": 2}, limit=6)
        assert topics[0]["delta"] == 0
        assert topics[0]["direction"] == "flat"
        assert topics[0]["change_pct"] == 0

    def test_topic_only_in_previous_window_shows_decline(self):
        topics = build_topic_trends({}, {"ECONOMY": 3}, limit=6)
        assert topics[0]["topic"] == "ECONOMY"
        assert topics[0]["current"] == 0
        assert topics[0]["delta"] == -3

    def test_sorted_by_gain_then_truncated_to_limit(self):
        current = {"TECHNOLOGY": 5, "POLITICS": 4, "WORLD": 1}
        previous = {"TECHNOLOGY": 1, "POLITICS": 1, "WORLD": 1}
        topics = build_topic_trends(current, previous, limit=2)
        assert [t["topic"] for t in topics] == ["TECHNOLOGY", "POLITICS"]
