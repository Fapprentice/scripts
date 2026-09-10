import copy
import importlib.util
import json
import sys
import uuid
from datetime import datetime
from importlib.machinery import SourceFileLoader
from pathlib import Path

import acceptance
import adaptive
import learning
from task_service import TaskService
from utils import normalize_tasks, task_text


def load_panel(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    name = "task_panel_business_{}".format(uuid.uuid4().hex)
    path = Path(__file__).parents[1] / "task-panel.pyw"
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(path)))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_b01_keywords_are_not_acceptance():
    result = acceptance._r5_output_keywords(
        {"expected_output": "可运行程序"}, {"text": "可运行程序", "files": []})
    assert result.pass_ is False


def test_b02_llm_verdict_is_typed_and_consistent():
    task = {"title": "交付", "expected_output": "结果", "acceptance": "结果可核验"}
    details = {"text": "结果", "files": []}
    malformed = acceptance.run_llm_eval(task, details, {}, lambda *_: {"pass": "false"})
    valid = acceptance.run_llm_eval(task, details, {}, lambda *_: {"pass": True, "uncertainty": 0})
    assert malformed["status"] == "needs_review" and malformed["pass"] is False
    assert valid["status"] == "passed" and valid["pass"] is True


def test_b03_python_acceptance_stays_blocked_without_sandbox():
    result = acceptance._r4_docker_run(
        {"evidence": ["x.py"]},
        {"files": [{"path": "x.py", "docker_run": {"skipped": True}}]},
    )
    assert result.pass_ is False
    assert "阻断" in result.detail


def test_b03_manual_review_survives_panel_roundtrip(monkeypatch, tmp_path):
    panel = load_panel(monkeypatch, tmp_path)
    contract = {"outcome": "交付", "success_criteria": ["标准"]}
    task = learning.outcome_task(contract, {})
    task.update({"id": "outcome", "status": "doing"})
    state = {"goals": [{"id": "g1", "title": "目标", **contract}], "active_goal": 0,
             "tasks_by_goal": {"g1": [task]}, "flags_by_goal": {"g1": [False]}}
    panel.sc(state)
    panel.install_services()
    current = panel.ensure_goal_state(panel.lc())
    ok, _ = panel.ACCEPTANCE.manual_accept(current, 0, "已人工检查交付物")
    current = panel.lc()
    assert ok is True
    assert current["tasks"][0]["manual_review"]["reason"] == "已人工检查交付物"
    assert current["tasks"][0]["acceptance_result"]["status"] == "passed"


def test_b04_contract_change_invalidates_outcome_task(monkeypatch, tmp_path):
    panel = load_panel(monkeypatch, tmp_path)
    contract = {"outcome": "交付", "success_criteria": ["标准一"]}
    task = learning.outcome_task(contract, {})
    task.update({"id": "outcome", "status": "doing", "criteria": copy.deepcopy(task["criteria"])})
    state = {"goals": [{"id": "g1", "title": "目标", **contract}], "active_goal": 0,
             "tasks_by_goal": {"g1": [task]}, "flags_by_goal": {"g1": [False]}}
    panel.sc(state)
    state = panel.lc()
    state["goals"][0]["success_criteria"] = ["标准二"]
    panel.sc(state)
    current = panel.ensure_goal_state(panel.lc())
    assert current["goal_completed"] is False
    panel.install_services()
    assert panel.evaluate_task(0)["status"] == "blocked"
    assert panel.lc()["tasks"][0]["acceptance_result"]["status"] == "blocked"


def test_b04_outcome_change_same_criteria_stays_blocked(monkeypatch, tmp_path):
    panel = load_panel(monkeypatch, tmp_path)
    old = {"outcome": "命令行版本", "success_criteria": ["输出42"]}
    task = learning.outcome_task(old, {})
    task.update({"id": "outcome", "status": "doing", "criterion_evidence": {"输出42": "42"}})
    state = {"goals": [{"id": "g1", "title": "目标", "outcome": "网页版成果",
                         "success_criteria": ["输出42"]}], "active_goal": 0,
             "tasks_by_goal": {"g1": [task]}, "flags_by_goal": {"g1": [False]}}
    panel.sc(state)
    panel.install_services()
    monkeypatch.setattr(panel, "valid_deepseek_key", lambda _key: True)
    def judge(messages, *_):
        payload = json.loads(messages[-1]["content"])
        return {"criterion_id": payload["criterion_id"], "pass": True, "uncertainty": 0}
    monkeypatch.setattr(panel, "deepseek_json", judge)
    assert panel.evaluate_task(0)["status"] == "blocked"
    assert panel.lc()["goal_completed"] is False


def test_b05_goal_completion_is_scoped_by_goal(monkeypatch, tmp_path):
    panel = load_panel(monkeypatch, tmp_path)
    goals = [{"id": "g1", "title": "一", "outcome": "一", "success_criteria": ["一"]},
             {"id": "g2", "title": "二", "outcome": "二", "success_criteria": ["二"]}]
    state = {"goals": goals, "active_goal": 0, "tasks_by_goal": {"g1": [], "g2": []},
             "flags_by_goal": {"g1": [], "g2": []}, "goal_completed_by_goal": {"g1": True, "g2": False},
             "contract_fingerprint_by_goal": {"g1": panel.contract_fingerprint({"outcome": "一", "success_criteria": ["一"]}),
                                               "g2": panel.contract_fingerprint({"outcome": "二", "success_criteria": ["二"]})}}
    assert panel.ensure_goal_state(state)["goal_completed"] is True
    state["active_goal"] = 1
    assert panel.ensure_goal_state(state)["goal_completed"] is False


def test_b06_coverage_does_not_use_one_substring_as_full_explanation():
    pack = learning.resolve_pack(pack_id="python-intro", pack_version="v2")
    assert learning.coverage_gaps(pack, {"success_criteria": ["程序可运行并支持参数"]})


def test_b06_outcome_eligibility_blocks_uncovered_pack_contract():
    state = {"user_model": {"pack_id": "python-intro", "pack_version": "v1"}}
    contract = {"outcome": "Python", "success_criteria": ["程序可运行并支持参数"]}
    assert learning.SkillMap.load(state, contract).ok is False
    assert learning.outcome_eligibility(state, contract)["eligible"] is False


def test_b07_uncovered_map_never_becomes_user_task():
    assert learning.plan_learning_tasks(
        {"user_model": {}}, "掌握未覆盖技能", {"outcome": "掌握未覆盖技能", "success_criteria": ["新标准"]}, 3) == []


def test_b07_validated_internal_map_repair_can_unlock_planning(monkeypatch, tmp_path):
    panel = load_panel(monkeypatch, tmp_path)
    contract = {"outcome": "Python", "success_criteria": ["非精确标准"]}
    state = panel.ensure_goal_state({"goals": [{"id": "g1", "title": "Python", **contract}], "active_goal": 0})
    learning.SkillMap.load(state, contract)
    monkeypatch.setattr(panel, "dk", lambda: "configured-test-key")
    monkeypatch.setattr(panel, "valid_deepseek_key", lambda _key: True)
    monkeypatch.setattr(panel, "deepseek_json", lambda *_: {"knowledge_graph": {"nodes": [{
        "id": "python.extra", "title": "额外节点", "core_behavior": "独立完成额外能力",
        "mastery_evidence": {"behavior": "提交结果", "threshold": "结果可核验", "counterexample": "只描述不提交"},
        "prerequisites": []}]}, "coverage": {"非精确标准": ["python.extra"]}})
    assert panel.repair_learning_map(state, contract) is True
    assert learning.SkillMap.load(state, contract).ok is True


def test_b08_failed_diagnostic_revokes_baseline_skip():
    state = {"user_model": {}}
    skill_map = learning.SkillMap.load(state, {"outcome": "英语四级", "success_criteria": ["听力、阅读、写作达到考试要求"],
                                                "baseline": "听力已经达到考试要求"})
    skill_map.apply_outcome("cet4.listening.short_dialogue", {"task_passed": False})
    skill = state["user_model"]["skills"]["cet4.listening.short_dialogue"]
    assert skill.get("skip_reason") is None
    assert skill["band"] != "skipped"


def test_b09_next_cycle_preserves_unfinished_work_and_evidence():
    task = {"id": "stable", "status": "partial", "response": "answer", "evidence": ["proof.txt"],
            "actual_seconds": 42, "started_at": "2026-01-01T00:00:00"}
    state = {"tasks": [task]}
    adaptive.prepare_next_cycle(state)
    assert state["tasks"][0]["id"] == "stable"
    assert state["tasks"][0]["response"] == "answer"
    assert state["tasks"][0]["evidence"] == ["proof.txt"]
    assert state["tasks"][0]["started_at"] == ""


def test_b09_diagnostic_regeneration_keeps_unfinished_task(monkeypatch, tmp_path):
    panel = load_panel(monkeypatch, tmp_path)
    state = panel.ensure_goal_state({"goals": [{"id": "g1", "title": "目标", "success_criteria": ["标准"]}],
                                     "active_goal": 0, "tasks": [{"id": "keep", "title": "续接", "status": "paused",
                                     "response": "已做", "evidence": ["proof"]}]})
    panel.save_diagnostic_plan(state, [{"title": "新诊断", "description": "新的诊断动作", "type": "practice"}])
    assert state["tasks"][0]["id"] == "keep"
    assert state["tasks"][0]["response"] == "已做"


def test_b09_repeated_diagnostic_generation_deduplicates_tasks(monkeypatch, tmp_path):
    panel = load_panel(monkeypatch, tmp_path)
    state = panel.ensure_goal_state({"goals": [{"id": "g1", "title": "目标"}], "active_goal": 0,
                                     "task_gen": {"task_count": 1}, "tasks": []})
    raw = [{"title": "新诊断", "description": "新的诊断动作", "type": "practice"}]
    panel.save_diagnostic_plan(state, raw)
    first_ids = [task["id"] for task in state["tasks"]]
    panel.save_diagnostic_plan(state, raw)
    assert [task["id"] for task in state["tasks"]] == first_ids


def test_b10_archives_are_distinct_and_idempotent_by_cycle(monkeypatch, tmp_path):
    panel = load_panel(monkeypatch, tmp_path)
    state = {"goals": [{"id": "g1", "title": "目标"}], "active_goal": 0, "tasks": [], "cycle_id": "c1"}
    state = panel.ensure_goal_state(state)
    first = panel.daily_archive(state)
    state["cycle_id"] = "c2"
    panel.daily_archive(state)
    panel.daily_archive(state)
    assert first["cycle_id"] == "c1"
    assert [row["cycle_id"] for row in state["archives"]] == ["c1", "c2"]


def test_b10_same_cycle_is_kept_across_days(monkeypatch, tmp_path):
    panel = load_panel(monkeypatch, tmp_path)
    state = panel.ensure_goal_state({"goals": [{"id": "g1", "title": "目标"}], "active_goal": 0,
                                     "tasks": [], "cycle_id": "c1"})
    day = ["2026-09-10"]
    monkeypatch.setattr(panel, "today", lambda: day[0])
    panel.daily_archive(state)
    day[0] = "2026-09-11"
    panel.daily_archive(state)
    assert [(row["cycle_id"], row["date"]) for row in state["archives"]] == [("c1", "2026-09-10"), ("c1", "2026-09-11")]


def test_b11_split_resets_new_child_execution_fields():
    task = {"id": "t1", "title": "交付", "status": "doing", "started_at": datetime.now().isoformat(),
            "response": "old", "evidence": ["old.txt"], "acceptance_result": {"status": "failed"},
            "estimated_minutes": 30, "acceptance": "可核验"}
    state = {"tasks": [task]}
    decision = {"task_index": 0, "decision": "split_task", "reason": "证据支持存在真实阻力"}
    adaptive.apply_decision(state, decision)
    assert state["tasks"][0]["status"] == "pending"
    assert "response" not in state["tasks"][0]
    assert state["tasks"][1]["acceptance"] == "可核验"


def test_b11_split_intermediate_does_not_grant_mastery():
    state = {"user_model": {"skills": {"node": {"band": "learning", "contract_met": False}}},
             "tasks": [{"id": "t1", "title": "节点", "status": "pending", "task_kind": "node",
                         "skill_id": "node", "primary_skill_id": "node", "acceptance": "可核验"}]}
    adaptive.apply_decision(state, {"task_index": 0, "decision": "split_task", "reason": "有真实阻力"})
    service = __import__("acceptance_service").AcceptanceService(
        normalize=lambda tasks, *_: tasks, text=task_text, sync_pct=lambda _: None,
        save=lambda _: None, event=lambda *_: None, learning_outcome=learning.record_learning_outcome)
    assert service.persist_result(state, 0, {"pass": True, "status": "passed", "reason": "中间步骤完成"})[0]
    assert state["user_model"]["skills"]["node"]["contract_met"] is not True


def test_b12_only_one_task_runs_and_done_task_cannot_restart():
    events = []
    service = TaskService(text=str, normalize=lambda tasks, *_: tasks, goal_id=lambda _: "g1",
                           sync_pct=lambda _: None, save=lambda _: None, event=lambda *_args: events.append(_args),
                           undo=lambda *_: None, compact=lambda _: None)
    state = {"tasks": [{"id": "a", "status": "doing", "started_at": datetime.now().isoformat()},
                       {"id": "b", "status": "pending"}], "done_flags": [False, False]}
    assert service.set_status(state, 1, "doing")[0]
    assert state["tasks"][0]["status"] == "paused"
    state["tasks"][1]["status"] = "done"
    state["done_flags"][1] = True
    assert service.set_status(state, 1, "doing")[0] is False


def test_b12_duplicate_doing_is_idempotent_with_real_normalizer():
    service = TaskService(text=task_text, normalize=normalize_tasks, goal_id=lambda _: "g1",
                          sync_pct=lambda _: None, save=lambda _: None, event=lambda *_: None,
                          undo=lambda *_: None, compact=lambda _: None)
    state = {"tasks": [{"id": "a", "title": "任务", "status": "pending"}], "done_flags": [False]}
    assert service.set_status(state, 0, "doing")[0]
    started_at = state["tasks"][0]["started_at"]
    attempts = state["tasks"][0]["attempts"]
    assert service.set_status(state, 0, "doing")[0]
    assert state["tasks"][0]["status"] == "doing"
    assert state["tasks"][0]["started_at"] == started_at
    assert state["tasks"][0]["attempts"] == attempts
def test_b01_manual_review_expires_when_contract_changes(monkeypatch, tmp_path):
    panel = load_panel(monkeypatch, tmp_path)
    old = {"outcome": "交付", "success_criteria": ["输出42"]}
    task = learning.outcome_task(old, {})
    task.update({"id": "outcome", "status": "doing"})
    state = {"goals": [{"id": "g1", "title": "目标", **old}], "active_goal": 0,
             "tasks_by_goal": {"g1": [task]}, "flags_by_goal": {"g1": [False]}}
    panel.sc(state); panel.install_services()
    current = panel.ensure_goal_state(panel.lc())
    assert panel.ACCEPTANCE.manual_accept(current, 0, "已人工检查旧成果")[0] is True
    changed_evidence = panel.lc()
    changed_evidence["tasks"][0]["criterion_evidence"] = {"changed": [{"kind": "direct_text", "text": "证据版本二"}]}
    panel.save_goal_state(changed_evidence); panel.sc(changed_evidence)
    assert panel.evaluate_task(0)["status"] == "blocked"
    changed = panel.lc()
    changed["goals"][0]["success_criteria"] = ["输出42", "导出CSV"]
    panel.sc(changed)
    result = panel.evaluate_task(0)
    assert result["status"] == "blocked"
    assert panel.lc()["goal_completed"] is False

def test_b02_client_task_replacement_cannot_inject_manual_review(monkeypatch, tmp_path):
    panel = load_panel(monkeypatch, tmp_path)
    contract = {"outcome": "交付", "success_criteria": ["输出42"]}
    state = {"goals": [{"id": "g1", "title": "目标", **contract}], "active_goal": 0}
    panel.sc(state); panel.install_services()
    raw = {"id": "injected", "title": "交付", "task_kind": "outcome", "status": "doing",
           "criteria": [{"id": "criterion-x", "text": "输出42"}], "criterion_ids": ["criterion-x"],
           "manual_review": {"reason": "injected"}}
    assert panel.TASKS.replace(panel.ensure_goal_state(panel.lc()), [raw], "client task replacement")[0]
    current = panel.lc()
    assert not current["tasks"][0].get("manual_review")
    assert panel.evaluate_task(0)["status"] != "passed"

def test_b03_stage_manual_review_keeps_hard_eligibility_gate(monkeypatch, tmp_path):
    panel = load_panel(monkeypatch, tmp_path)
    pack = learning.resolve_pack(pack_id="python-intro", pack_version="v2")
    template = learning.get_stage_template(pack, "python.stage.control-flow")
    proposal = {"stage_id": template["id"], "template_revision": template["template_revision"],
                "pack_id": "python-intro", "pack_version": "v2", "title": "阶段挑战",
                "description": template["integration_behavior"], "required_skill_ids": list(template["required_skill_ids"]),
                "supporting_skill_ids": [], "materials": [{"id": "input", "values": [1, 2]}],
                "expected_output": template["outcome_shape"], "acceptance": template["evidence_contract"]["threshold"],
                "integration_behavior": template["integration_behavior"], "outcome_shape": template["outcome_shape"],
                "skill_checks": copy.deepcopy(template["skill_checks"])}
    task = learning.instantiate_stage_task(pack, template["id"], proposal)
    skills = {skill_id: {"contract_met": False, "prerequisites": []} for skill_id in template["required_skill_ids"]}
    state = {"goals": [{"id": "g1", "title": "Python", "outcome": "Python",
                         "success_criteria": ["程序可运行"]}], "active_goal": 0,
             "user_model": {"pack_id": "python-intro", "pack_version": "v2", "skills": skills},
             "user_models_by_goal": {"g1": {"pack_id": "python-intro", "pack_version": "v2", "skills": copy.deepcopy(skills)}},
             "tasks_by_goal": {"g1": [task]}, "flags_by_goal": {"g1": [False]}}
    panel.sc(state); panel.install_services()
    current = panel.ensure_goal_state(panel.lc())
    assert panel.ACCEPTANCE.manual_accept(current, 0, "人工检查阶段证据")[0] is False
    assert learning.record_stage_outcome(current, current["tasks"][0], {"manual_review": {"reason": "绕过"}})["status"] == "blocked"
    for skill in current["user_model"]["skills"].values():
        skill["contract_met"] = True
    panel.save_goal_state(current); panel.sc(current)
    assert panel.ACCEPTANCE.manual_accept(panel.ensure_goal_state(panel.lc()), 0, "已检查完整阶段证据")[0] is True
    assert panel.lc()["user_model"].get("integration_evidence")

def test_b04_contract_change_regenerates_current_outcome_and_keeps_history(monkeypatch, tmp_path):
    panel = load_panel(monkeypatch, tmp_path)
    old = {"outcome": "交付程序", "success_criteria": ["输出42"]}
    new = {"outcome": "交付程序", "success_criteria": ["输出42", "导出CSV"]}
    old_task = learning.outcome_task(old, {})
    old_task.update({"id": "old-outcome", "status": "doing"})
    state = {"goals": [{"id": "g1", "title": "目标", **new}], "active_goal": 0,
             "tasks_by_goal": {"g1": [old_task]}, "flags_by_goal": {"g1": [False]}}
    panel.sc(state)
    current = panel.ensure_goal_state(panel.lc())
    panel.save_diagnostic_plan(current, [learning.outcome_task(new, {})])
    outcomes = [task for task in current["tasks"] if task.get("task_kind") == "outcome"]
    assert len(outcomes) == 1
    assert {row["text"] for row in outcomes[0]["criteria"]} == set(new["success_criteria"])
    assert current["task_history"][0]["id"] == "old-outcome"
    outcomes[0]["status"] = "doing"
    outcomes[0]["criterion_evidence"] = {row["id"]: [{"kind": "direct_text", "text": row["text"]}] for row in outcomes[0]["criteria"]}
    panel.save_goal_state(current); panel.sc(current); panel.install_services()
    monkeypatch.setattr(panel, "valid_deepseek_key", lambda _key: True)
    monkeypatch.setattr(panel, "dk", lambda: "configured-test-key")
    def judge(messages, *_):
        payload = json.loads(messages[-1]["content"])
        return {"criterion_id": payload["criterion_id"], "pass": True, "uncertainty": 0}
    monkeypatch.setattr(panel, "deepseek_json", judge)
    assert panel.evaluate_task(0)["status"] == "passed"

def test_p1_failed_recheck_reconciles_done_state_after_evidence_change(monkeypatch, tmp_path):
    panel = load_panel(monkeypatch, tmp_path)
    contract = {"outcome": "交付", "success_criteria": ["输出42"]}
    task = learning.outcome_task(contract, {})
    task.update({"id": "outcome-reconcile", "status": "doing"})
    unrelated = {"id": "unrelated", "title": "无关有效任务", "status": "done",
                 "acceptance_result": {"status": "passed", "pass": True}}
    panel.sc({"goals": [{"id": "g1", "title": "目标", **contract}], "active_goal": 0,
              "tasks_by_goal": {"g1": [task, unrelated]}, "flags_by_goal": {"g1": [False, True]}})
    panel.install_services()
    assert panel.ACCEPTANCE.manual_accept(panel.ensure_goal_state(panel.lc()), 0, "首次人工确认")[0] is True
    changed = panel.lc()
    changed["tasks"][0]["criterion_evidence"] = {"changed": [{"kind": "direct_text", "text": "新证据"}]}
    panel.save_goal_state(changed); panel.sc(changed)
    assert panel.evaluate_task(0)["status"] == "blocked"
    reloaded = panel.ensure_goal_state(panel.lc())
    assert reloaded["tasks"][0]["status"] != "done"
    assert reloaded["done_flags"] == [False, True]
    assert reloaded["completion_pct"] == 50
    assert reloaded["tasks"][1]["status"] == "done"
    assert reloaded["goal_completed"] is False
    assert reloaded["tasks"][0]["acceptance_result"]["status"] == "blocked"

def test_p1_manual_recheck_cannot_rebind_old_outcome_to_new_contract(monkeypatch, tmp_path):
    panel = load_panel(monkeypatch, tmp_path)
    old = {"outcome": "命令行结果", "success_criteria": ["输出42"]}
    current = {"outcome": "网页版结果", "success_criteria": ["输出42"]}
    task = learning.outcome_task(old, {})
    task.update({"id": "old-contract", "status": "doing"})
    panel.sc({"goals": [{"id": "g1", "title": "目标", **current}], "active_goal": 0,
              "tasks_by_goal": {"g1": [task]}, "flags_by_goal": {"g1": [False]}})
    panel.install_services()
    assert panel.ACCEPTANCE.manual_accept(panel.ensure_goal_state(panel.lc()), 0, "重新检查旧成果")[0] is False
    assert panel.ensure_goal_state(panel.lc())["goal_completed"] is False

def test_p1_repeated_valid_automatic_outcome_is_idempotent(monkeypatch, tmp_path):
    panel = load_panel(monkeypatch, tmp_path)
    contract = {"outcome": "交付", "success_criteria": ["输出42"]}
    task = learning.outcome_task(contract, {})
    task.update({"id": "auto-repeat", "status": "doing",
                 "criterion_evidence": {task["criterion_ids"][0]: [{"kind": "direct_text", "text": "输出42"}]}})
    panel.sc({"goals": [{"id": "g1", "title": "目标", **contract}], "active_goal": 0,
              "tasks_by_goal": {"g1": [task]}, "flags_by_goal": {"g1": [False]}})
    panel.install_services()
    monkeypatch.setattr(panel, "valid_deepseek_key", lambda _key: True)
    monkeypatch.setattr(panel, "dk", lambda: "configured-test-key")
    def judge(messages, *_):
        payload = json.loads(messages[-1]["content"])
        return {"criterion_id": payload["criterion_id"], "pass": True, "uncertainty": 0}
    monkeypatch.setattr(panel, "deepseek_json", judge)
    assert panel.evaluate_task(0)["status"] == "passed"
    first = panel.ensure_goal_state(panel.lc())
    assert panel.evaluate_task(0)["status"] == "passed"
    second = panel.ensure_goal_state(panel.lc())
    assert second["done_flags"] == [True]
    assert second["completion_pct"] == 100
    assert second["goal_completed"] is True
    assert second["tasks"][0]["acceptance_result"]["task_fingerprint"] == first["tasks"][0]["acceptance_result"]["task_fingerprint"]
