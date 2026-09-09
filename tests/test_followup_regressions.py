import copy
import json
import importlib.util
import os
import sys
from datetime import datetime
import uuid
from importlib.machinery import SourceFileLoader
from pathlib import Path

import learning


def load_task_panel(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    name = "task_panel_followup_{}".format(uuid.uuid4().hex)
    path = Path(__file__).parents[1] / "task-panel.pyw"
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(path)))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def stage_task(panel, evidence, response_refs=True, complete=True):
    pack = learning.resolve_pack(pack_id="python-intro", pack_version="v2")
    template = learning.get_stage_template(pack, "python.stage.control-flow")
    proposal = {
        "stage_id": template["id"], "template_revision": template["template_revision"],
        "pack_id": pack["id"], "pack_version": pack["version"],
        "title": "控制流综合", "description": "遍历输入并分类。",
        "required_skill_ids": list(template["required_skill_ids"]),
        "supporting_skill_ids": [], "materials": [{"id": "values", "values": [1, 2, 3]}],
        "expected_output": template["outcome_shape"],
        "acceptance": template["evidence_contract"]["threshold"],
        "integration_behavior": template["integration_behavior"],
        "outcome_shape": template["outcome_shape"],
        "skill_checks": copy.deepcopy(template["skill_checks"]),
    }
    task = learning.instantiate_stage_task(pack, template["id"], proposal)
    task.update({"id": "stage-followup", "status": "doing", "evidence": []})
    observations = [
        {"skill_id": "python.control.branch", "status": "passed", "evidence": "I say I passed"},
        {"skill_id": "python.control.loop", "status": "passed", "evidence": "I say I passed"},
    ] if complete else [{"skill_id": "python.control.branch", "status": "passed", "evidence": "I say I passed"}]
    task["response"] = {
        "status": "passed", "skill_observations": observations,
        "evidence_refs": [evidence] if response_refs else [],
    }
    return task


def trusted_sandbox_facts(panel):
    original = panel.stage_evidence_facts

    def with_sandbox(evidence):
        facts = original(evidence)
        for fact in facts:
            if fact.get("exists") and str(fact.get("path", "")).endswith(".py"):
                fact["safe_execution"] = {
                    "source": "docker", "skipped": False, "ok": True,
                    "all_materials": True, "branch_loop_same_output": True,
                    "stdout": "verified output",
                }
        return facts

    return with_sandbox


def save_state(panel, task, goal=None):
    goal = goal or {"id": "g1", "title": "Python", "outcome": "完成程序", "success_criteria": ["程序可运行"]}
    state = {
        "goals": [goal], "active_goal": 0,
        "tasks_by_goal": {goal["id"]: [task]}, "flags_by_goal": {goal["id"]: [False]},
        "user_models_by_goal": {goal["id"]: {}},
    }
    panel.sc(state)


def test_real_stage_evaluation_rejects_self_reported_pass_for_invalid_artifact(monkeypatch, tmp_path):
    panel = load_task_panel(monkeypatch, tmp_path)
    source = tmp_path / "not-a-program.txt"
    source.write_text("not a program, no loop or branch", encoding="utf-8")
    stored = panel.STORE.add_attachment(source)
    task = stage_task(panel, stored)
    task["evidence"] = [stored]
    save_state(panel, task)

    result = panel.evaluate_task(0)
    reloaded = panel.lc()
    ledger = reloaded["user_model"]["integration_evidence"][0]

    assert result["status"] in {"needs_review", "partial", "failed"}
    assert reloaded["tasks"][0]["acceptance_result"]["status"] != "passed"
    assert ledger["status"] != "passed"
    assert reloaded.get("goal_completed") is not True


def test_real_stage_evaluation_does_not_treat_dead_code_as_execution(monkeypatch, tmp_path):
    panel = load_task_panel(monkeypatch, tmp_path)
    source = tmp_path / "dead_code.py"
    source.write_text(
        "if False:\n"
        "    for value in []:\n"
        "        print(value)\n",
        encoding="utf-8",
    )
    stored = panel.STORE.add_attachment(source)
    task = stage_task(panel, stored)
    save_state(panel, task)

    result = panel.evaluate_task(0)
    reloaded = panel.lc()
    ledger = reloaded["user_model"]["integration_evidence"][0]

    assert result["status"] in {"blocked", "needs_review"}, result
    assert reloaded["tasks"][0]["acceptance_result"]["status"] != "passed"
    assert ledger["status"] != "passed"


def test_real_stage_evaluation_does_not_split_response_and_ledger_evidence(monkeypatch, tmp_path):
    panel = load_task_panel(monkeypatch, tmp_path)
    source = tmp_path / "control_flow.py"
    source.write_text(
        "for value in [1, 2, 3]:\n"
        "    if value > 1:\n"
        "        print('high')\n"
        "    else:\n"
        "        print('low')\n",
        encoding="utf-8",
    )
    stored = panel.STORE.add_attachment(source)
    task = stage_task(panel, stored)
    save_state(panel, task)
    monkeypatch.setattr(panel, "stage_evidence_facts", trusted_sandbox_facts(panel))

    result = panel.evaluate_task(0)
    reloaded = panel.lc()
    task_result = reloaded["tasks"][0]["acceptance_result"]
    ledger = reloaded["user_model"]["integration_evidence"][0]

    assert result["status"] == "passed", result
    assert task_result["status"] == ledger["status"] == "passed"
    assert reloaded["tasks"][0]["status"] == "done"
    assert ledger["evidence_refs"] == [stored]


def test_real_stage_partial_retry_updates_same_ledger_after_reload(monkeypatch, tmp_path):
    panel = load_task_panel(monkeypatch, tmp_path)
    source = tmp_path / "control_flow_retry.py"
    source.write_text(
        "for value in [1, 2, 3]:\n"
        "    if value > 1:\n"
        "        print('high')\n"
        "    else:\n"
        "        print('low')\n",
        encoding="utf-8",
    )
    stored = panel.STORE.add_attachment(source)
    task = stage_task(panel, stored, complete=False)
    save_state(panel, task)
    monkeypatch.setattr(panel, "stage_evidence_facts", trusted_sandbox_facts(panel))

    partial = panel.evaluate_task(0)
    first = panel.lc()
    assert partial["status"] == "partial"
    assert first["user_model"]["integration_evidence"][0]["status"] == "partial"

    retry = first["tasks"][0]
    retry["response"] = stage_task(panel, stored, complete=True)["response"]
    first["tasks_by_goal"]["g1"] = first["tasks"]
    panel.sc(first)
    passed = panel.evaluate_task(0)
    reloaded = panel.lc()
    ledger = reloaded["user_model"]["integration_evidence"][0]

    assert passed["status"] == "passed"
    assert reloaded["tasks"][0]["acceptance_result"]["status"] == ledger["status"] == "passed"
    assert len(ledger["attempts"]) == 2


def test_real_evaluation_after_pause_does_not_recount_closed_timer_segment(monkeypatch, tmp_path):
    panel = load_task_panel(monkeypatch, tmp_path)
    task = {
        "id": "timer-followup", "title": "暂停后的验收", "type": "behavior",
        "verification_mode": "none", "status": "paused", "actual_seconds": 600,
        "started_at": datetime.fromtimestamp(1_700_000_000).isoformat(),
    }
    save_state(panel, task)
    panel.install_services()
    monkeypatch.setattr(panel.time, "time", lambda: 1_700_000_600)

    result = panel.evaluate_task(0)
    reloaded = panel.lc()

    assert result["ok"] is True
    assert reloaded["tasks"][0]["actual_seconds"] == 600
    assert reloaded["tasks"][0]["started_at"] == ""


def test_real_outcome_evaluation_does_not_pass_copied_criterion(monkeypatch, tmp_path):
    panel = load_task_panel(monkeypatch, tmp_path)
    contract = {"outcome": "完成程序", "success_criteria": ["输出正确"]}
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("完全无关的临时文件", encoding="utf-8")
    panel.install_services()

    for index, evidence in enumerate((
        ["输出正确"],
        ["输出正确是我尚未达到的标准"],
        [str(unrelated)],
    )):
        task = learning.outcome_task(contract, {})
        task.update({"id": "outcome-followup-{}".format(index), "status": "doing", "criterion_evidence": {
            task["criterion_ids"][0]: evidence,
        }})
        save_state(panel, task, {"id": "g1", "title": "Python", **contract})
        result = panel.evaluate_task(0)
        assert result["status"] in {"needs_review", "failed"}, result
        assert panel.lc().get("goal_completed") is not True


def test_real_outcome_evaluation_accepts_semantic_judge_positive(monkeypatch, tmp_path):
    panel = load_task_panel(monkeypatch, tmp_path)
    contract = {"outcome": "完成程序", "success_criteria": ["输出正确"]}
    source = tmp_path / "result.txt"
    source.write_text("程序实际输出：42", encoding="utf-8")
    stored = panel.STORE.add_attachment(source)
    task = learning.outcome_task(contract, {})
    task.update({"id": "outcome-positive", "status": "doing", "evidence": [stored], "criterion_evidence": {
        task["criterion_ids"][0]: [{"ref": stored, "content": "程序实际输出：42"}],
    }})
    save_state(panel, task, {"id": "g1", "title": "Python", **contract})
    panel.install_services()
    monkeypatch.setattr(panel, "valid_deepseek_key", lambda _key: True)
    monkeypatch.setattr(panel, "dk", lambda: "configured-for-test")
    monkeypatch.setattr(panel, "deepseek_json", lambda *_args: {
        "criterion_id": task["criterion_ids"][0], "pass": True, "uncertainty": 0,
        "reason": "证据内容与标准一致", "evidence": [stored],
    })

    result = panel.evaluate_task(0)
    reloaded = panel.lc()

    assert result["status"] == "passed"
    assert reloaded.get("goal_completed") is True


def test_real_outcome_judge_uses_verified_attachment_facts_and_direct_text(monkeypatch, tmp_path):
    panel = load_task_panel(monkeypatch, tmp_path)
    contract = {"outcome": "完成程序", "success_criteria": ["输出正确"]}
    real = tmp_path / "real.txt"
    real.write_text("真实附件内容", encoding="utf-8")
    target = panel.STORE.add_attachment(real)
    unrelated_source = tmp_path / "unrelated.txt"
    unrelated_source.write_text("无关真实内容", encoding="utf-8")
    unrelated = panel.STORE.add_attachment(unrelated_source)
    missing = str(tmp_path / "missing-output.txt")
    calls = []

    def judge(messages, *_args):
        payload = json.loads(messages[-1]["content"])
        criterion = payload["criterion"]
        reference = payload["reference"]
        content = payload["content"]
        calls.append((criterion["id"], reference, content))
        return {"criterion_id": criterion["id"], "pass": content == "真实附件内容", "uncertainty": 0}

    panel.install_services()
    monkeypatch.setattr(panel, "valid_deepseek_key", lambda _key: True)
    monkeypatch.setattr(panel, "dk", lambda: "configured-for-test")
    monkeypatch.setattr(panel, "deepseek_json", judge)

    cases = [
        ("missing", [{"ref": missing, "content": "伪造说明"}], "needs_review"),
        ("unrelated", [{"ref": unrelated, "content": "伪造说明"}], "needs_review"),
        ("attachment", [{"ref": target}], "passed"),
        ("direct-text", [{"kind": "direct_text", "text": "真实附件内容"}], "passed"),
    ]
    for name, evidence, expected in cases:
        task = learning.outcome_task(contract, {})
        task.update({"id": "outcome-evidence-" + name, "status": "doing", "evidence": [target, unrelated], "criterion_evidence": {
            task["criterion_ids"][0]: evidence,
        }})
        save_state(panel, task, {"id": "g1", "title": "Python", **contract})
        result = panel.evaluate_task(0)
        assert result["status"] in ({"failed", "needs_review"} if expected == "needs_review" else {expected}), (name, result)
        assert (panel.lc().get("goal_completed") is True) is (expected == "passed")

    assert all(content != "伪造说明" for _criterion, _reference, content in calls)
    assert any(content == "真实附件内容" for _criterion, _reference, content in calls)


def test_outcome_judge_requires_typed_matching_verdict():
    task = learning.outcome_task({"outcome": "结果", "success_criteria": ["输出正确"]}, {})
    criterion = task["criterion_ids"][0]
    for verdict in (
        {"pass": "false", "uncertainty": 0, "criterion_id": criterion},
        {"pass": True, "uncertainty": 0, "criterion_id": "wrong"},
        {"pass": True, "uncertainty": "not-a-number", "criterion_id": criterion},
    ):
        result = learning.evaluate_outcome(
            task,
            {"criterion_evidence": {criterion: [{"kind": "direct_text", "text": "输出正确"}]}},
            criterion_judge=lambda *_args, verdict=verdict: verdict,
        )
        assert result["status"] != "passed", verdict
