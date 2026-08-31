"""SkillMap is the plan source for learning goals."""
from datetime import datetime, timezone

import learning


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
CET4 = {
    "outcome": "通过英语四级考试",
    "deadline": "2027-06-01",
    "baseline": "",
    "success_criteria": ["听力、阅读、写作达到考试要求"],
    "constraints": ["每天 60 分钟"],
}


def test_learning_goal_without_map_cannot_dispatch_ordinary_tasks():
    state = {"user_model": {}}
    result = learning.SkillMap.load(state, {"outcome": "掌握日语五十音", "success_criteria": ["能默写五十音"], "baseline": ""})
    assert result.ok is False
    task = learning.next_learning_task(state, NOW)
    assert task is None or task.get("source") == "map_patch"


def test_cet4_pack_is_plan_source_and_blocks_unknown_skill_ids():
    state = {"user_model": {}}
    skill_map = learning.SkillMap.load(state, CET4)
    assert skill_map.ok is True
    assert skill_map.pack_id == "cet4"
    focus = skill_map.focus(now=NOW)
    assert focus["skill_id"] == "cet4.vocab.high_freq"
    task = skill_map.next_task(now=NOW)
    assert task["skill_id"] == "cet4.vocab.high_freq"
    assert "8/10" in task["acceptance"]
    assert skill_map.unlock("cet4.vocab.collocation") is False
    assert learning.task_in_map(skill_map, {"skill_id": "invented.skill"}) is False


def test_cycle_proposal_is_rejected():
    state = {"user_model": {}}
    graph = learning.merge_knowledge_graph(state, {"nodes": [
        {"id": "basics", "title": "基础", "prerequisites": ["loops"]},
        {"id": "loops", "title": "循环", "prerequisites": ["basics"]},
    ]})
    assert graph.get("error") == "cycle"
    assert not graph.get("edges")


def test_hard_prerequisite_blocks_unlock_soft_does_not():
    state = {"user_model": {}}
    skill_map = learning.SkillMap.load(state, CET4)
    assert skill_map.unlock("cet4.writing.essay") is False
    skill_map.apply_outcome("cet4.writing.outline", {"task_passed": True, "evidence": ["outline.txt"]})
    assert skill_map.unlock("cet4.writing.essay") is True


def test_task_pass_without_node_contract_does_not_master_skill():
    state = {"user_model": {}}
    skill_map = learning.SkillMap.load(state, {
        "outcome": "写出可运行的 Python 小程序",
        "success_criteria": ["程序可运行"],
        "baseline": "",
    })
    skill_map.apply_outcome("python.control.loop", {
        "task_passed": True, "recall_rating": "easy", "evidence": [],
    })
    skill = state["user_model"]["skills"]["python.control.loop"]
    assert skill.get("contract_met") is not True


def test_recall_rating_only_required_for_recall_demonstration():
    state = {"user_model": {}}
    skill_map = learning.SkillMap.load(state, CET4)
    assert learning.requires_recall_rating({"skill_id": "cet4.vocab.high_freq"}, state) is True
    assert learning.requires_recall_rating({"skill_id": "cet4.writing.essay"}, state) is False


def test_baseline_skips_listening_subgraph():
    state = {"user_model": {}}
    skill_map = learning.SkillMap.load(state, dict(CET4, baseline="听力已经达到考试要求"))
    skill_map.apply_baseline("听力已经达到考试要求")
    listening = state["user_model"]["skills"]["cet4.listening.short_dialogue"]
    assert listening["band"] == "skipped"
    assert listening["skip_reason"] == "baseline"
    assert skill_map.focus(now=NOW)["skill_id"] != "cet4.listening.short_dialogue"
    vocab = state["user_model"]["skills"]["cet4.vocab.high_freq"]
    assert vocab.get("band") != "skipped"


def test_unskip_returns_baseline_skip_to_unlearned():
    state = {"user_model": {}}
    skill_map = learning.SkillMap.load(state, dict(CET4, baseline="听力已经达到考试要求"))
    skill_map.unskip("cet4.listening.short_dialogue")
    skill = state["user_model"]["skills"]["cet4.listening.short_dialogue"]
    assert skill["band"] == "unlearned"
    assert not skill.get("skip_reason")
    skill_map.apply_baseline("听力已经达到考试要求")
    assert state["user_model"]["skills"]["cet4.listening.short_dialogue"]["band"] == "unlearned"


def test_coverage_requires_sinks_for_success_criteria():
    state = {"user_model": {}}
    skill_map = learning.SkillMap.load(state, {
        "outcome": "通过英语四级考试",
        "success_criteria": ["口语达到考试要求"],
        "baseline": "",
    })
    assert skill_map.ok is False
    assert "口语达到考试要求" in skill_map.gaps


def test_plan_learning_tasks_uses_pack_frontier():
    state = {"user_model": {}}
    tasks = learning.plan_learning_tasks(state, "英语四级", CET4, 3)
    assert [task["skill_id"] for task in tasks] == [
        "cet4.vocab.high_freq", "cet4.reading.main_idea", "cet4.listening.short_dialogue",
    ]
    assert all(task.get("source") in ("pack", "ability_diagnostic") for task in tasks)


def test_uncovered_learning_goal_plans_map_patch_only():
    state = {"user_model": {}}
    tasks = learning.plan_learning_tasks(
        state, "掌握日语五十音", {"outcome": "掌握日语五十音", "success_criteria": ["能默写五十音"]}, 3)
    assert len(tasks) == 1
    assert tasks[0]["source"] == "map_patch"
    assert not tasks[0].get("skill_id")


def test_confirmed_wrong_direction_demotes_hard_edge_without_lowering_contract():
    state = {"user_model": {}, "tasks": [{
        "id": "t1", "skill_id": "cet4.writing.essay",
        "acceptance": "不少于 120 词并记录用时", "status": "pending",
    }]}
    skill_map = learning.SkillMap.load(state, CET4)
    original = state["tasks"][0]["acceptance"]
    skill_map.apply_feedback({
        "kind": "wrong_direction", "confirmed": True,
        "skill_id": "cet4.writing.essay", "task_id": "t1",
        "from": "cet4.writing.outline", "to": "cet4.writing.essay",
    })
    meta = state["user_model"]["skills"]["cet4.writing.essay"]["prerequisite_meta"]["cet4.writing.outline"]
    assert meta["kind"] == "soft"
    assert state["tasks"][0]["acceptance"] == original
    assert CET4["success_criteria"] == ["听力、阅读、写作达到考试要求"]


def test_unconfirmed_wrong_direction_does_not_edit_edges():
    state = {"user_model": {}}
    skill_map = learning.SkillMap.load(state, CET4)
    skill_map.apply_feedback({
        "kind": "wrong_direction", "confirmed": False,
        "skill_id": "cet4.writing.essay",
        "from": "cet4.writing.outline", "to": "cet4.writing.essay",
    })
    meta = state["user_model"]["skills"]["cet4.writing.essay"]["prerequisite_meta"]["cet4.writing.outline"]
    assert meta["kind"] == "hard"


def test_ai_proposal_extends_pack_without_changing_version_or_pack_edges():
    state = {"user_model": {}}
    skill_map = learning.SkillMap.load(state, CET4)
    result = learning.propose_nodes(state, {
        "pack_id": "cet4", "pack_version": "v1",
        "nodes": [{
            "id": "cet4.writing.speech", "title": "口头陈述提纲",
            "description": "把写作提纲改成口头陈述。",
            "demonstration": "explain",
            "mastery_evidence": {"behavior": "口头讲清三点理由", "threshold": "三点均可展开", "counterexample": "只有主题句"},
            "prerequisites": ["cet4.writing.outline"],
            "prerequisite_meta": {"cet4.writing.outline": {"kind": "soft", "rationale": "口头陈述建立在已有提纲上"}},
        }],
    })
    assert result.get("error") in (None, "")
    assert state["user_model"]["pack_version"] == "v1"
    assert "cet4.writing.speech" in state["user_model"]["skills"]
    outline_kind = state["user_model"]["skills"]["cet4.writing.essay"]["prerequisite_meta"]["cet4.writing.outline"]["kind"]
    assert outline_kind == "hard"


def test_ai_proposal_rejects_pack_version_mismatch_and_missing_contract():
    state = {"user_model": {}}
    learning.SkillMap.load(state, CET4)
    mismatched = learning.propose_nodes(state, {"pack_id": "cet4", "pack_version": "v9", "nodes": [
        {"id": "cet4.extra", "title": "额外", "mastery_evidence": {"threshold": "可检查"}, "prerequisites": []},
    ]})
    assert mismatched.get("error") == "pack_version"
    assert "cet4.extra" not in state["user_model"]["skills"]
    incomplete = learning.propose_nodes(state, {"pack_id": "cet4", "pack_version": "v1", "nodes": [
        {"id": "cet4.extra", "title": "额外", "prerequisites": ["cet4.vocab.high_freq"]},
    ]})
    assert incomplete.get("error") == "node_contract"
    assert "cet4.extra" not in state["user_model"]["skills"]


def test_too_hard_feedback_inserts_soft_prerequisite_without_changing_contract():
    state = {"user_model": {"skills": {}}, "tasks": [{
        "id": "t1", "skill_id": "cet4.writing.outline",
        "acceptance": "三点理由均可展开成段落",
        "status": "pending", "title": "写作提纲",
    }]}
    skill_map = learning.SkillMap.load(state, CET4)
    skill_map.apply_outcome("cet4.reading.main_idea", {"task_passed": True, "evidence": ["main.txt"]})
    skill_map.apply_outcome("cet4.reading.detail", {"task_passed": True, "evidence": ["detail.txt"]})
    original = state["tasks"][0]["acceptance"]
    skill_map.apply_feedback({"kind": "too_hard", "task_id": "t1", "skill_id": "cet4.writing.outline"})
    assert state["tasks"][0]["acceptance"] == original
    assert any(task.get("skill_id") == "cet4.reading.inference" for task in state["tasks"])

