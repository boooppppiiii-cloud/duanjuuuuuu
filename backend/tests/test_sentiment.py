from app.services.sentiment import local_analysis


def test_local_analysis_detects_purchase_intent_without_api():
    result = local_analysis("I love this! Where can I watch the full episode?")

    assert result["sentiment"] == "positive"
    assert result["user_status"] == "potential_buyer"
    assert result["analysis_source"] == "local"


def test_local_analysis_escalates_payment_issue():
    result = local_analysis("I was charged twice, please refund my payment")

    assert result["ticket_type"] == "payment_error"
    assert result["severity"] == "high"
    assert result["needs_human"] is True
    assert result["user_status"] == "churned"


def test_local_analysis_escalates_playback_issue():
    result = local_analysis("Episode 8 cannot play and only shows a black screen")

    assert result["ticket_type"] == "playback_issue"
    assert result["severity"] == "medium"
    assert result["needs_human"] is True
