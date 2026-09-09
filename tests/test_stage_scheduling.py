from copy import deepcopy
from datetime import datetime, timedelta, timezone

import learning

NOW = datetime(2026, 1, 10, tzinfo=timezone.utc)


def _ready_state():
    state = {"user_model": {}}
    pack = learning.resolve_pack(pack_id="python-intro", pack_version="v2")
    learning._bind_pack(state, pack)
    for skill_id in ("python.syntax.names", "python.syntax.types", "python.control.branch", "python.control.loop"):
        state["user_model"]["skills"][skill_id].update({"contract_met": True, "mastery": 1.0})
    return state, pack


def _proposal(pack, minutes=25):
    template = learning.get_stage_template(pack, "python.stage.control-flow")
    return {
        "stage_id": template["id"], "template_revision": template["template_revision"],
        "pack_id": pack["id"], "pack_version": pack["version"],
        "title": "控制流综合", "description": "循环处理数据并在循环内分类。",
        "required_skill_ids": list(template["required_skill_ids"]), "supporting_skill_ids": [],
        "materials": [{"id": "values", "values": [1, 2, 3]}],
        "estimated_minutes": minutes, "expected_output": "程序和统一汇总输出",
        "acceptance": template["evidence_contract"]["threshold"],
        "integration_behavior": template["integration_behavior"], "outcome_shape": template["outcome_shape"],
        "skill_checks": deepcopy(template["skill_checks"]),
    }


def test_stage_proposals_are_derived_only_from_bound_skill_pack():
    state, pack = _ready_state()
    proposals = learning.stage_proposals(state, {"outcome": "Python"})
    assert [item["stage_id"] for item in proposals] == ["python.stage.control-flow"]
    assert proposals[0]["required_skill_ids"] == ["python.control.branch", "python.control.loop"]


def test_stage_candidate_requires_mastery_prerequisites_budget_and_valid_materials():
    state, pack = _ready_state()
    proposal = _proposal(pack)
    assert learning.stage_candidate_pool(state, [proposal], NOW, budget_minutes=25)[0]["task_kind"] == "stage"
    state["user_model"]["skills"]["python.control.loop"]["contract_met"] = False
    assert learning.stage_candidate_pool(state, [proposal], NOW, budget_minutes=25) == []
    state, pack = _ready_state()
    assert learning.stage_candidate_pool(state, [_proposal(pack, 26)], NOW, budget_minutes=25) == []
    invalid = _proposal(pack); invalid["materials"] = []
    assert learning.stage_candidate_pool(state, [invalid], NOW, budget_minutes=25) == []


def test_due_required_skill_blocks_only_when_severely_overdue_and_optional_never_blocks():
    state, pack = _ready_state()
    proposal = _proposal(pack)
    state["user_model"]["skills"]["python.control.loop"]["review_due_at"] = (NOW - timedelta(days=8)).isoformat()
    assert learning.stage_candidate_pool(state, [proposal], NOW, 30) == []
    state["user_model"]["skills"]["python.control.loop"]["review_due_at"] = (NOW - timedelta(days=1)).isoformat()
    state["user_model"]["skills"]["python.syntax.types"]["review_due_at"] = (NOW - timedelta(days=30)).isoformat()
    assert learning.stage_candidate_pool(state, [proposal], NOW, 30)


def test_severe_due_review_precedes_eligible_stage():
    state, pack = _ready_state(); proposal = _proposal(pack)
    skill = state["user_model"]["skills"]["python.control.branch"]
    skill["review_due_at"] = (NOW - timedelta(days=8)).isoformat()
    task = learning.next_learning_task(state, NOW, budget_minutes=30, stage_proposals=[proposal])
    assert task["task_kind"] == "node" and task["learning_task_type"] == "review"


def test_learning_day_aging_is_persisted_and_next_task_can_schedule_explicit_stage():
    state, pack = _ready_state(); proposal = _proposal(pack)
    first = learning.stage_candidate_pool(state, [proposal], NOW, 30)[0]
    later = learning.stage_candidate_pool(state, [proposal], NOW + timedelta(days=3), 30)[0]
    assert first["eligible_learning_days"] == 0
    assert later["eligible_learning_days"] == 3
    assert learning.next_learning_task(state, NOW, budget_minutes=30, stage_proposals=[proposal])["stage_id"] == proposal["stage_id"]


def test_stage_settlement_persists_integration_once_without_changing_mastery():
    state, pack = _ready_state(); task = dict(_proposal(pack), id="stage-1", task_kind="stage")
    before = deepcopy(state["user_model"]["skills"])
    outcome = {"status": "passed", "evidence_refs": ["run.txt"], "skill_observations": [
        {"skill_id": "python.control.branch", "status": "passed", "evidence": "two paths"},
        {"skill_id": "python.control.loop", "status": "passed", "evidence": "all inputs looped"},
    ], "evidence_facts": [{"path": "run.py", "exists": True, "python_ok": True,
                                "content": "for value in [1]:\n    if value:\n        print(value)\n",
                                "safe_execution": {"source": "docker", "skipped": False, "ok": True,
                                                    "all_materials": True, "branch_loop_same_output": True,
                                                    "stdout": "verified"}}]}
    evidence = learning.record_stage_outcome(state, task, outcome, NOW)
    again = learning.record_stage_outcome(state, task, outcome, NOW)
    assert evidence == again
    assert len(state["user_model"]["integration_evidence"]) == 1
    assert [event["kind"] for event in state["events"]] == ["stage_completed"]
    assert state["user_model"]["skills"] == before


def test_stage_failure_then_valid_retry_updates_one_ledger_record_once():
    state, pack = _ready_state(); task = dict(_proposal(pack), id="stage-retry", task_kind="stage")
    failed = learning.record_stage_outcome(state, task, {"status": "partial", "evidence_refs": ["bad.txt"]}, NOW)
    failed_status = failed["status"]
    passed = learning.record_stage_outcome(state, task, {"status": "passed", "evidence_refs": ["run.txt"], "skill_observations": [
        {"skill_id": "python.control.branch", "status": "passed", "evidence": "two paths"},
        {"skill_id": "python.control.loop", "status": "passed", "evidence": "all inputs looped"},
    ], "evidence_facts": [{"path": "run.py", "exists": True, "python_ok": True,
                                "content": "for value in [1]:\n    if value:\n        print(value)\n",
                                "safe_execution": {"source": "docker", "skipped": False, "ok": True,
                                                    "all_materials": True, "branch_loop_same_output": True,
                                                    "stdout": "verified"}}]}, NOW)
    duplicate = learning.record_stage_outcome(state, task, {"status": "passed", "evidence_refs": ["run.txt"], "skill_observations": [
        {"skill_id": "python.control.branch", "status": "passed", "evidence": "two paths"},
        {"skill_id": "python.control.loop", "status": "passed", "evidence": "all inputs looped"},
    ], "evidence_facts": [{"path": "run.py", "exists": True, "python_ok": True,
                                "content": "for value in [1]:\n    if value:\n        print(value)\n",
                                "safe_execution": {"source": "docker", "skipped": False, "ok": True,
                                                    "all_materials": True, "branch_loop_same_output": True,
                                                    "stdout": "verified"}}]}, NOW)
    assert failed_status == "partial"
    assert passed["status"] == duplicate["status"] == "passed"
    assert len(state["user_model"]["integration_evidence"]) == 1
    assert len(state["user_model"]["integration_evidence"][0]["attempts"]) == 2
    assert [event["kind"] for event in state["events"]] == ["stage_completed"]


def test_stage_failure_and_needs_review_do_not_rollback_or_emit_growth():
    for status in ("failed", "needs_review", "blocked", "partial"):
        state, pack = _ready_state(); task = dict(_proposal(pack), id="stage-" + status, task_kind="stage")
        before = deepcopy(state["user_model"]["skills"])
        learning.record_stage_outcome(state, task, {"status": status, "evidence_refs": ["x"]}, NOW)
        assert state["user_model"]["skills"] == before
        assert state.get("events", []) == []
        assert state["user_model"]["integration_evidence"][-1]["status"] == status
