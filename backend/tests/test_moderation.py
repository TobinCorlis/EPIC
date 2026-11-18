from app.services.moderation import evaluate_topic_alignment


def test_pivot_phrasing_is_flagged_for_review_and_not_labelled_off_topic():
    result = evaluate_topic_alignment(
        "Should the city adopt congestion pricing?",
        "What about the mayor's personal travel expenses?",
    )
    assert result.on_topic is True
    assert result.needs_review is True
    assert "whataboutism" not in (result.note or "").lower()
    assert "off-topic" in (result.note or "").lower()


def test_accepts_related_submission_without_a_review_flag():
    result = evaluate_topic_alignment(
        "Should the city adopt congestion pricing?",
        "Congestion pricing may reduce traffic in the city center.",
    )
    assert result.on_topic is True
    assert result.needs_review is False


def test_missing_shared_words_flags_a_long_submission_for_review():
    result = evaluate_topic_alignment(
        "Should the city adopt congestion pricing?",
        "Blue whales migrate across open ocean basins during the cold season each year and return when conditions change.",
    )
    assert result.on_topic is True
    assert result.needs_review is True
