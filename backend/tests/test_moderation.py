from app.services.moderation import evaluate_topic_alignment


def test_rejects_explicit_pivot():
    result = evaluate_topic_alignment(
        "Should the city adopt congestion pricing?",
        "What about the mayor's personal travel expenses?",
    )
    assert result.on_topic is False


def test_accepts_related_submission():
    result = evaluate_topic_alignment(
        "Should the city adopt congestion pricing?",
        "Congestion pricing may reduce traffic in the city center.",
    )
    assert result.on_topic is True
