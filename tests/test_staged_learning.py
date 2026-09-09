import copy

import pytest

import learning
from utils import normalize_task


def _stage_pack():
    return learning.resolve_pack(pack_id="python-intro", pack_version="v2")


def _proposal(template):
    return {
        "stage_id": template["id"],
        "template_revision": template["template_revision"],
        "pack_id": "python-intro",
        "pack_version": "v2",
        "title": "控制流综合：筛选并汇总温度",
        "description": "遍历一组温度，用分支筛选并生成一份汇总结果。",
        "required_skill_ids": list(template["required_skill_ids"]),
        "supporting_skill_ids": [],
        "materials": [{"id": "temperatures", "values": [18, 25, 31]}],
        "expected_output": "一个同时使用循环和分支的可运行程序及输出",
        "acceptance": template["evidence_contract"]["threshold"],
        "integration_behavior": template["integration_behavior"],
        "outcome_shape": template["outcome_shape"],
        "skill_checks": copy.deepcopy(template["skill_checks"]),
    }


def test_resolve_pack_uses_bound_version_and_latest_for_new_goal():
    latest = learning.resolve_pack(pack_id="python-intro")
    bound = learning.resolve_pack({"user_model": {"pack_id": "python-intro", "pack_version": "v1"}})
    assert latest["version"] == "v2"
    assert bound["version"] == "v1"
    assert "stages" not in bound



def test_match_pack_prefers_bound_version_then_latest_stable(monkeypatch):
    packs = [
        {"id": "python-intro", "version": "v1", "match": ["python"]},
        {"id": "python-intro", "version": "v2", "match": ["python"], "release_status": "stable"},
        {"id": "python-intro", "version": "v3", "match": ["python"], "release_status": "draft"},
    ]
    monkeypatch.setattr(learning, "_PACK_CACHE", packs)
    contract = {"outcome": "学习 python"}
    assert learning.match_pack(contract)["version"] == "v2"
    state = {"user_model": {"pack_id": "python-intro", "pack_version": "v1"}}
    assert learning.match_pack(contract, state)["version"] == "v1"


def test_stage_normalized_fields_round_trip_without_skill_identity():
    pack = _stage_pack()
    template = learning.get_stage_template(pack, "python.stage.control-flow")
    first = normalize_task(learning.instantiate_stage_task(pack, template["id"], _proposal(template)))
    replay = normalize_task(first)
    stage_fields = (
        "task_kind", "stage_id", "template_revision", "pack_id", "pack_version",
        "required_skill_ids", "supporting_skill_ids", "integration_behavior",
        "outcome_shape", "skill_checks", "evidence_contract", "evidence_target",
    )
    assert {field: replay[field] for field in stage_fields} == {field: first[field] for field in stage_fields}
    assert replay["skill_id"] == replay["primary_skill_id"] == ""
    assert replay["observations_required"] is True


def test_python_control_flow_template_is_well_formed():
    template = learning.get_stage_template(_stage_pack(), "python.stage.control-flow")
    assert template["required_skill_ids"] == ["python.control.branch", "python.control.loop"]
    assert learning.validate_stage_template(_stage_pack(), template) == []


def test_valid_proposal_instantiates_explicit_stage_without_skill_id():
    pack = _stage_pack()
    template = learning.get_stage_template(pack, "python.stage.control-flow")
    task = learning.instantiate_stage_task(pack, template["id"], _proposal(template))
    assert task["task_kind"] == "stage"
    assert task["stage_id"] == template["id"]
    assert task["skill_id"] == task["primary_skill_id"] == ""
    assert task["evidence_target"] == "integration"
    assert task["required_skill_ids"] == template["required_skill_ids"]


@pytest.mark.parametrize("change", [
    lambda p: p.update(required_skill_ids=["python.control.loop"]),
    lambda p: p.update(pack_version="v1"),
    lambda p: p.update(materials=[]),
    lambda p: p.update(integration_behavior="做两道独立练习"),
])
def test_invalid_proposals_are_rejected(change):
    pack = _stage_pack()
    template = learning.get_stage_template(pack, "python.stage.control-flow")
    proposal = _proposal(template)
    change(proposal)
    with pytest.raises(ValueError):
        learning.instantiate_stage_task(pack, template["id"], proposal)


def test_pack_stage_requires_observations_even_for_legacy_pass_input():
    pack = _stage_pack(); template = learning.get_stage_template(pack, "python.stage.control-flow")
    task = learning.instantiate_stage_task(pack, template["id"], _proposal(template))
    result = learning.evaluate_stage_outcome(task, {"status": "passed", "evidence_refs": ["run.txt"]})
    assert result["status"] == "partial"


def test_stage_pass_requires_evidence_on_each_required_observation():
    pack = _stage_pack(); template = learning.get_stage_template(pack, "python.stage.control-flow")
    task = learning.instantiate_stage_task(pack, template["id"], _proposal(template))
    result = learning.evaluate_stage_outcome(task, {
        "status": "passed", "evidence_refs": ["run.txt"],
        "skill_observations": [
            {"skill_id": "python.control.branch", "status": "passed"},
            {"skill_id": "python.control.loop", "status": "passed", "evidence": "loop output"},
        ],
    })
    assert result["status"] == "partial"


def test_stage_outcome_requires_all_required_skill_observations_for_pass():
    pack = _stage_pack()
    template = learning.get_stage_template(pack, "python.stage.control-flow")
    task = learning.instantiate_stage_task(pack, template["id"], _proposal(template))
    outcome = learning.evaluate_stage_outcome(task, {
        "status": "passed", "evidence_refs": ["run.txt"],
        "skill_observations": [{"skill_id": "python.control.loop", "status": "passed"}],
    })
    assert outcome["status"] == "partial"


def test_stage_outcome_returns_actionable_failed_attribution():
    pack = _stage_pack()
    template = learning.get_stage_template(pack, "python.stage.control-flow")
    task = learning.instantiate_stage_task(pack, template["id"], _proposal(template))
    outcome = learning.evaluate_stage_outcome(task, {
        "status": "failed",
        "skill_observations": [{"skill_id": "python.control.branch", "status": "failed", "reason": "未出现两条路径"}],
    })
    assert outcome["attribution"] == [{"skill_id": "python.control.branch", "status": "failed", "reason": "未出现两条路径"}]


def test_outcome_requires_each_criterion_evidence_and_preserves_ids():
    task = learning.outcome_task({"outcome": "可运行程序", "success_criteria": ["输出正确", "记录运行"]}, {})
    assert task["task_kind"] == "outcome"
    assert task["locked"] is False
    partial = learning.evaluate_outcome(task, {"criterion_evidence": {task["criterion_ids"][0]: ["out.txt"]}})
    assert partial["status"] == "failed"
    assert len(partial["failed_criterion_ids"]) == 1
    complete = learning.evaluate_outcome(task, {"criterion_evidence": {
        task["criterion_ids"][0]: [{"kind": "direct_text", "text": "输出正确", "verified": True}],
        task["criterion_ids"][1]: [{"kind": "direct_text", "text": "记录运行", "verified": True}],
    }}, criterion_judge=lambda criterion, *_: {"criterion_id": criterion["id"], "pass": True, "uncertainty": 0})
    assert complete["status"] == "passed"


def test_outcome_does_not_pass_null_blank_or_unrelated_evidence():
    task = learning.outcome_task({"outcome": "结果", "success_criteria": ["输出正确"]}, {})
    criterion = task["criterion_ids"][0]
    for value in ([None], ["   "], ["与标准无关的说明"]):
        assert learning.evaluate_outcome(task, {"criterion_evidence": {criterion: value}})["status"] != "passed"


def test_outcome_eligibility_derives_required_skill_from_pack_coverage():
    state = {"user_model": {"pack_id": "python-intro", "pack_version": "v2", "skills": {"python.app.script": {"contract_met": False}}}}
    task = learning.outcome_task({"outcome": "结果", "success_criteria": ["程序可运行"]}, state)
    assert task["locked"] is True
    assert "python.app.script" in task["eligibility"]["missing_skill_ids"]


def test_outcome_failure_trace_is_criterion_scoped_and_does_not_reset_map():
    task = learning.outcome_task({"outcome": "结果", "success_criteria": ["标准一", "标准二"]}, {})
    failed_id = task["criterion_ids"][1]
    result = learning.evaluate_outcome(task, {"criterion_evidence": {
        task["criterion_ids"][0]: [{"kind": "direct_text", "text": "标准一", "verified": True}],
    }}, criterion_judge=lambda criterion, *_: {"criterion_id": criterion["id"], "pass": True, "uncertainty": 0})
    assert result["failed_criterion_ids"] == [failed_id]
    assert result["failure_trace"] == [{"criterion_id": failed_id, "criterion": "标准二",
        "next_action": "补充该成功标准对应的最小独立证据", "task_kind": "diagnostic", "evidence_target": "criterion"}]


def test_outcome_eligibility_requires_required_stage_but_not_optional_skills():
    state = {"user_model": {"skills": {"core": {"contract_met": True}}}}
    task = learning.outcome_task({"outcome": "结果", "success_criteria": ["可核验"]}, state, required_stage_ids=["python.stage.control-flow"])
    assert task["locked"] is True
    state["user_model"]["integration_evidence"] = [{"stage_id": "python.stage.control-flow", "status": "passed"}]
    assert learning.outcome_task({"outcome": "结果", "success_criteria": ["可核验"]}, state, required_stage_ids=["python.stage.control-flow"])["locked"] is False


def test_unfinished_map_patch_migrates_to_internal_repair_once():
    state = {"tasks": [{"id": "patch-1", "source": "map_patch", "title": "补图", "status": "pending"}], "done_flags": [False]}
    first = learning.migrate_legacy_tasks(state)
    second = learning.migrate_legacy_tasks(state)
    assert first["migrated"] == ["patch-1"]
    assert second["migrated"] == []
    assert state["tasks"] == []
    assert len([e for e in state["events"] if e["kind"] == "task_migrated_out"]) == 1
    assert state["internal_map_repairs"][0]["task_id"] == "patch-1"


def test_normalize_task_preserves_stage_contract_without_node_migration():
    pack = _stage_pack()
    template = learning.get_stage_template(pack, "python.stage.control-flow")
    task = normalize_task(learning.instantiate_stage_task(pack, template["id"], _proposal(template)))
    assert task["task_kind"] == "stage"
    assert task["skill_id"] == task["primary_skill_id"] == ""
    assert task["stage_id"] == "python.stage.control-flow"
    assert task["required_skill_ids"] == ["python.control.branch", "python.control.loop"]
    assert task["skill_checks"] == template["skill_checks"]
