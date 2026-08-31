from datetime import datetime

import adaptive
import learning


def state(task=None):
    return {"tasks": [task or {
        "id": "t1", "title": "完成原型", "status": "doing", "estimated_minutes": 30,
        "attempts": 2, "actual_minutes": 35, "acceptance": "原型可以运行",
        "evidence": ["notes.txt"], "acceptance_result": {},
    }]}


def test_goal_readiness_asks_only_missing_questions():
    result = adaptive.goal_readiness({"outcome": "发布产品", "success_criteria": ["20 人使用"]})
    assert result["score"] == 40
    assert result["ready"] is False
    assert "最终成果" not in result["missing"]
    assert "希望在哪一天前完成？" in result["questions"]
    assert result["contract"]["outcome"] == "发布产品"
    assert result["contract"]["success_criteria"] == ["20 人使用"]


def test_goal_contract_normalizes_only_user_commitments():
    contract = adaptive.goal_contract({"outcome": "  上线  ", "deadline": 20261231,
                                      "baseline": None, "success_criteria": [" 可访问 ", ""],
                                      "constraints": "每天 30 分钟", "ignored": "plan"})
    assert contract == {"outcome": "上线", "deadline": "20261231", "baseline": "",
                        "success_criteria": ["可访问"], "constraints": ["每天 30 分钟"]}


def test_too_easy_deepens_node_demonstration_without_lowering_standard():
    c = {
        "tasks": [{
            "id": "t1", "title": "高频词汇", "status": "doing",
            "estimated_minutes": 15, "attempts": 2, "actual_minutes": 20,
            "acceptance": "至少 8/10 正确", "skill_id": "cet4.vocab.high_freq",
            "demonstration": "recall", "evidence": ["answers.txt"],
            "acceptance_result": {"pass": True},
        }],
        "user_model": {"skills": {
            "cet4.vocab.high_freq": {
                "demonstration": "recall",
                "mastery_evidence": {"threshold": "至少 8/10 正确"},
                "prerequisites": [],
            },
        }},
    }
    result = adaptive.record_feedback(c, 0, "太简单", "too_easy")
    assert result["applied"] is True
    skill = c["user_model"]["skills"]["cet4.vocab.high_freq"]
    assert skill["demonstration"] == "practice"
    assert "独立验证" in c["tasks"][0]["acceptance"]
    assert "至少 8/10 正确" in c["tasks"][0]["acceptance"]


def test_unproven_difficulty_does_not_lower_standard():
    c = state({"id": "t1", "title": "完成原型", "status": "pending",
               "estimated_minutes": 30, "attempts": 0, "acceptance": "原型可以运行"})
    result = adaptive.record_feedback(c, 0, "太难了", "too_hard")
    assert result["decision"] == "diagnose"
    assert result["applied"] is False
    assert c["tasks"][0]["acceptance"] == "原型可以运行"


def test_supported_difficulty_splits_without_lowering_original_standard():
    c = state()
    result = adaptive.record_feedback(c, 0, "我卡住了", "stuck")
    assert result["applied"] is True
    assert len(c["tasks"]) == 2
    assert c["tasks"][1]["acceptance"] == "原型可以运行"
    assert c["tasks"][1]["depends_on"] == [c["tasks"][0]["id"]]


def test_minimum_step_is_not_split_again():
    c = state()
    adaptive.record_feedback(c, 0, "我卡住了", "stuck")
    result = adaptive.record_feedback(c, 0, "还是卡住", "stuck")
    assert result["decision"] == "diagnose"
    assert result["applied"] is False
    assert len(c["tasks"]) == 2
    assert c["tasks"][0]["title"] == "最小步骤：完成原型"


def test_wrong_direction_requires_confirmation():
    c = state()
    result = adaptive.record_feedback(c, 0, "方向不对", "wrong_direction")
    assert result["decision"] == "realign"
    assert result["automatic"] is False
    assert c["tasks"][0]["acceptance"] == "原型可以运行"


def test_confirmed_wrong_direction_realigns_skill_edge():
    c = {
        "tasks": [{
            "id": "t1", "title": "限时短文", "status": "doing",
            "estimated_minutes": 30, "attempts": 2, "actual_minutes": 35,
            "acceptance": "不少于 120 词并记录用时", "skill_id": "cet4.writing.essay",
            "evidence": ["draft.txt"], "acceptance_result": {},
        }],
        "user_model": {},
    }
    learning.SkillMap.load(c, {
        "outcome": "通过英语四级考试",
        "success_criteria": ["听力、阅读、写作达到考试要求"],
        "baseline": "",
    })
    result = adaptive.record_feedback(c, 0, "方向不对", "wrong_direction", auto_apply=False)
    assert result["applied"] is False
    result["confirmed"] = True
    adaptive.apply_decision(c, result)
    assert result["applied"] is True
    assert c["tasks"][0]["acceptance"] == "不少于 120 词并记录用时"
    meta = c["user_model"]["skills"]["cet4.writing.essay"]["prerequisite_meta"]["cet4.writing.outline"]
    assert meta["kind"] == "soft"


def test_passive_overrun_adjusts_once():
    c = state({"id": "t1", "title": "任务", "status": "doing", "estimated_minutes": 10,
               "attempts": 1, "started_at": "2026-01-01T00:00:00", "acceptance": "完成"})
    first = adaptive.passive_review(c, now=1767227400)
    second = adaptive.passive_review(c, now=1767227400)
    assert first and first["source"] == "system"
    assert second is None


def test_review_updates_model_for_next_cycle():
    c = {"tasks": [
        {"id": "a", "status": "done", "estimated_minutes": 20, "actual_minutes": 20,
         "acceptance_result": {"pass": True}},
        {"id": "b", "status": "pending", "estimated_minutes": 40, "actual_minutes": 80,
         "acceptance_result": {"pass": False, "missing": ["测试"]}},
    ], "feedback_history": [{"kind": "stuck"}]}
    review = adaptive.complete_review(c, {"code.exe": 600})
    assert review["completion_rate"] == 0.5
    assert review["acceptance_rate"] == 0.5
    assert c["user_model"]["common_friction"] == "stuck"
    assert c["next_cycle_context"]["unfinished"] == ["b"]


def test_prepare_next_cycle_keeps_only_unfinished_work():
    c = {"tasks": [{"id": "a", "status": "done"}, {"id": "b", "status": "deferred", "started_at": "x"}]}
    adaptive.prepare_next_cycle(c)
    assert [task["id"] for task in c["tasks"]] == ["b"]
    assert c["tasks"][0]["status"] == "pending"
    assert c["done_flags"] == [False]


def test_full_adaptive_cycle_preserves_goal_standard():
    c = state()
    original = c["tasks"][0]["acceptance"]
    decision = adaptive.record_feedback(c, 0, "卡住了", "stuck")
    assert decision["applied"] is True
    assert c["tasks"][1]["acceptance"] == original
    c["tasks"][0]["status"] = "done"
    c["tasks"][0]["acceptance_result"] = {"pass": True}
    review = adaptive.complete_review(c)
    assert review["total"] == 2
    assert c["user_model"]["review_count"] == 1
    adaptive.prepare_next_cycle(c)
    assert len(c["tasks"]) == 1
    assert c["tasks"][0]["acceptance"] == original


def test_learning_outcome_updates_mastery_and_due_review():
    c = {"user_model": {}}
    task = {"skill_id": "python.loops", "prerequisites": ["python.basics"]}
    skill = adaptive.record_learning_outcome(c, task, True, now=1767225600)
    assert skill["mastery"] == 1.0
    assert (datetime.fromisoformat(skill["review_due_at"]) - datetime.fromtimestamp(1767225600).astimezone()).seconds == 600
    assert skill["fsrs_state"] == "Learning"
    assert skill["stability"] > 0
    assert len(c["user_model"]["fsrs_review_logs"]) == 1
    adaptive.record_learning_outcome(c, task, False, now=1767312000)
    assert skill["mastery"] == 0.0
    assert skill["last_rating"] == "Again"


def test_learning_focus_prefers_due_then_weakest_ready():
    c = {"user_model": {"skills": {
        "basics": {"mastery": 0.8, "review_due_at": "2026-02-01T00:00:00"},
        "loops": {"mastery": 0.4, "prerequisites": ["basics"], "review_due_at": "2026-01-01T00:00:00"},
        "advanced": {"mastery": 0.1, "prerequisites": ["loops"]},
    }}}
    assert adaptive.learning_focus(c, now=1767225600)["skill_id"] == "loops"


def test_due_review_task_is_strict_and_targets_due_skill():
    c = {"user_model": {"skills": {
        "basics": {"mastery": 0.8},
        "loops": {"mastery": 0.4, "prerequisites": ["basics"], "review_due_at": "2026-01-01T00:00:00"},
    }}}
    task = adaptive.due_review_task(c, now=1767225600)
    assert task["skill_id"] == "loops"
    assert task["learning_task_type"] == "review"
    assert task["verification_mode"] == "strict"


def test_due_review_task_skips_future_review():
    c = {"user_model": {"skills": {
        "loops": {"mastery": 0.4, "review_due_at": "2027-01-01T00:00:00"},
    }}}
    assert adaptive.due_review_task(c, now=1767225600) is None
