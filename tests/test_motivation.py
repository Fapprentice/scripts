import adaptive


def test_motivation_rewards_streak_and_resets_on_failure():
    state = {}
    assert adaptive.record_outcome(state, "accepted")["total"] == 10
    assert adaptive.record_outcome(state, "accepted")["streak"] == 2
    result = adaptive.record_outcome(state, "failed")
    assert result["total"] == 17
    assert result["streak"] == 0


def test_motivation_penalizes_skip():
    state = {}
    result = adaptive.record_outcome(state, "skipped")
    assert result["points"] == -5
    assert state["user_model"]["motivation_points"] == -5
