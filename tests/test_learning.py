from datetime import datetime, timedelta, timezone

import learning


def test_learning_fallback_uses_concrete_practice_not_generic_planning():
    tasks = learning.fallback_task_templates("英语四级")
    assert len(tasks) == 3
    assert all(task["type"] != "plan" and task["skill_id"] for task in tasks)
    assert tasks[0]["skill_id"] == "cet4.vocab.high_freq"
    assert not any("最小可交付成果" in task["title"] for task in tasks)


def test_learning_rejects_generic_planning_task():
    task = {"title": "明确“英语四级”今天的最小可交付成果", "description": "写下完成定义和边界"}
    assert learning.is_generic_planning_task("英语四级", task)
    assert not learning.is_generic_planning_task("发布个人网站", task)


def test_learning_task_consistency_and_semantic_duplicates():
    contradictory = {
        "title": "闭卷默写5个四级高频词",
        "description": "如果写不出，允许先看1个词。",
        "expected_output": "5个词汇",
        "learning_task_type": "recall",
    }
    assert "closed_book_conflict" in learning.task_consistency_issues(contradictory)
    assert learning.task_semantic_key(contradictory) == learning.task_semantic_key({
        "title": "回忆10个目标单词", "learning_task_type": "recall",
    })
    assert "quantity_mismatch" in learning.task_consistency_issues({
        "title": "完成10道练习", "description": "完成5道题", "expected_output": "5份答案",
    })


def test_initial_ability_diagnostics_complete_and_record_scores():
    state = {"user_model": {}}
    tasks = learning.initial_diagnostic_tasks(state, "英语四级", 2)
    assert [task["skill_id"] for task in tasks] == ["cet4.vocab.high_freq", "cet4.reading.main_idea"]
    assert len(tasks[0]["materials"]) == 30
    assert tasks[0]["interaction"]["type"] == "choice"
    learning.record_learning_outcome(state, dict(tasks[0], recall_rating="good", evidence=["answers"]), True, NOW)
    learning.SkillMap.load(state, {"outcome": "通过英语四级考试", "success_criteria": ["过线"], "baseline": ""})
    learning.SkillMap(state, ok=True).apply_outcome(tasks[0]["skill_id"], {"task_passed": True, "evidence": ["answers"], "recall_rating": "good"})
    remaining = learning.initial_diagnostic_tasks(state, "英语四级", 2)
    assert remaining[0]["skill_id"] != "cet4.vocab.high_freq"


def test_stm32_fallback_diagnostics_are_domain_specific():
    tasks = learning.initial_diagnostic_tasks({"user_model": {}}, "stm32", 2)
    assert [task["skill_id"] for task in tasks] == ["stm32.project_setup", "stm32.gpio"]
    assert all("STM32" in task["title"] for task in tasks)


def test_material_dependent_task_is_rejected_without_materials():
    task = {"title": "从30个四级高频词中选出正确中文释义", "description": "完成30道选择题",
            "expected_output": "30个答案", "learning_task_type": "diagnostic"}
    assert "missing_materials" in learning.task_consistency_issues(task)


def test_ai_dimensions_are_validated_persisted_and_reused():
    state = {"user_model": {}}
    raw = {"dimensions": [
        {"skill_id": "python.syntax", "title": "语法：闭卷解释", "description": "解释变量、分支和循环并给出例子",
         "estimated_minutes": 15, "expected_output": "三组解释和例子", "acceptance": "三组内容均完整"},
        {"skill_id": "python.debug", "title": "调试：定位错误", "description": "独立定位并修复一个运行错误",
         "estimated_minutes": 20, "expected_output": "修复代码和原因", "acceptance": "代码可运行且原因正确"},
        {"skill_id": "python.application", "title": "应用：完成小程序", "description": "独立完成一个可运行的小程序",
         "estimated_minutes": 30, "expected_output": "程序和运行结果", "acceptance": "程序可运行并满足输入输出要求"},
    ]}
    dimensions = learning.set_diagnostic_dimensions(state, raw, "sig-1", "ai")
    assert len(dimensions) == 3
    assert learning.diagnostic_dimensions("学习 Python", state) == dimensions
    assert state["user_model"]["ability_dimensions_signature"] == "sig-1"
    assert learning.initial_diagnostic_tasks(state, "学习 Python", 2)[0]["skill_id"] == "python.syntax"


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_fsrs_card_survives_serialization_and_graduates():
    state = {"user_model": {}}
    task = {"id": "t1", "skill_id": "loops", "estimated_minutes": 10, "attempts": 1}
    first = learning.record_learning_outcome(state, task, True, NOW)
    assert first["fsrs_state"] == "Learning"
    due = datetime.fromisoformat(first["review_due_at"])
    second = learning.record_learning_outcome(state, task, True, due)
    assert second["fsrs_state"] == "Review"
    assert datetime.fromisoformat(second["review_due_at"]) > due
    assert len(state["user_model"]["fsrs_review_logs"]) == 2


def test_failed_review_maps_to_again():
    state = {"user_model": {}}
    skill = learning.record_learning_outcome(state, {"skill_id": "loops"}, False, NOW)
    assert skill["last_rating"] == "Again"
    assert skill["mastery"] == 0


def test_explicit_recall_rating_reaches_fsrs():
    state = {"user_model": {}}
    skill = learning.record_learning_outcome(state, {"skill_id": "loops", "recall_rating": "easy"}, True, NOW)
    assert skill["last_rating"] == "Easy"


def test_graph_rejects_cycle_and_unlocks_reviewed_prerequisite():
    state = {"user_model": {}}
    learning.sync_task_graph(state, {"skill_id": "basics", "prerequisites": ["loops"]})
    learning.sync_task_graph(state, {"skill_id": "loops", "prerequisites": ["basics"]})
    skills = state["user_model"]["skills"]
    assert skills["loops"]["prerequisites"] == []
    skills["loops"].update({"fsrs_state": "Review", "mastery": 0.9})
    learning.sync_task_graph(state, {"skill_id": "advanced", "prerequisites": ["loops"]})
    graph = learning.knowledge_graph(state, NOW)
    assert "advanced" in graph["ready"]
    assert any(edge["from"] == "loops" and edge["to"] == "advanced" for edge in graph["edges"])


def test_due_review_uses_fsrs_due_time():
    state = {"user_model": {}}
    skill = learning.record_learning_outcome(state, {"skill_id": "loops"}, True, NOW)
    assert learning.due_review_task(state, NOW) is None
    due = datetime.fromisoformat(skill["review_due_at"]) + timedelta(seconds=1)
    assert learning.due_review_task(state, due)["skill_id"] == "loops"


def test_generated_graph_merges_nodes_and_blocks_descendants():
    state = {"user_model": {}}
    graph = learning.merge_knowledge_graph(state, {"nodes": [
        {"id": "basics", "title": "基础", "prerequisites": []},
        {"id": "loops", "title": "循环", "prerequisites": ["basics"]},
    ]})
    assert len(graph["nodes"]) == 2
    assert any(edge["from"] == "basics" and edge["to"] == "loops" for edge in graph["edges"])
    assert learning.task_is_unlocked(state, {"skill_id": "basics"})
    assert not learning.task_is_unlocked(state, {"skill_id": "loops", "prerequisites": ["basics"]})


def test_graph_frontier_generates_diagnostic_then_recall():
    state = {"user_model": {}}
    learning.merge_knowledge_graph(state, {"nodes": [{"id": "basics", "title": "基础", "prerequisites": []}]})
    first = learning.next_learning_task(state, NOW)
    assert first["skill_id"] == "basics"
    assert first["learning_task_type"] == "diagnostic"
    skill = learning.record_learning_outcome(state, dict(first, recall_rating="good"), True, NOW)
    second = learning.next_learning_task(state, datetime.fromisoformat(skill["review_due_at"]))
    assert second["learning_task_type"] == "review"
