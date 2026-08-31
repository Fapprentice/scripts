import json

import evaluation


def _case(**overrides):
    case = {
        "id": "case-1",
        "version": 1,
        "slices": ["learning"],
        "goal": {
            "id": "goal-1",
            "final_outcome": "通过可复现的 Python 程序证明掌握循环",
            "success_criteria": [
                {"id": "c1", "text": "程序输出 1 到 5"},
                {"id": "c2", "text": "提交运行结果"},
            ],
            "constraints": ["30 分钟内完成"],
        },
        "expected": {"decision": "pass"},
    }
    case.update(overrides)
    return case


def _artifact(**overrides):
    artifact = {
        "tasks": [{
            "id": "t1", "title": "实现循环", "description": "编写并运行程序",
            "criterion_ids": ["c1", "c2"], "estimated_minutes": 20,
            "expected_output": "程序和运行结果", "acceptance": "输出 1 到 5",
            "materials": [{"id": "m1", "type": "code", "content": "for i in range(1, 6): print(i)"}],
            "answer_key": [{"id": "k1", "material_ids": ["m1"], "criterion_id": "c1", "answer": "1 2 3 4 5"}],
        }],
        "evidence": [{"task_id": "t1", "criterion_ids": ["c1", "c2"], "content": "1 2 3 4 5"}],
        "acceptance": {"decision": "accepted", "criterion_ids": ["c1", "c2"]},
        "metadata": {"model": "fixture", "prompt_version": "v1"},
    }
    artifact.update(overrides)
    return artifact


def test_evaluate_case_scores_the_complete_chain():
    run = evaluation.evaluate_case(_case(), _artifact())
    assert run["decision"] == "pass"
    assert {score["stage"] for score in run["scores"]} == {
        "goal_quality", "goal_to_task", "task_to_materials",
        "materials_to_key", "evidence_to_acceptance",
    }
    assert run["first_failing_stage"] is None


def test_uncovered_success_criterion_is_a_hard_failure():
    artifact = _artifact()
    artifact["tasks"][0]["criterion_ids"] = ["c1"]
    run = evaluation.evaluate_case(_case(), artifact)
    assert run["decision"] == "fail"
    assert run["first_failing_stage"] == "goal_to_task"
    assert "c2" in run["metrics"]["uncovered_criteria"]


def test_missing_material_and_unsupported_key_are_reported_separately():
    artifact = _artifact()
    artifact["tasks"][0]["materials"] = []
    artifact["tasks"][0]["answer_key"][0]["material_ids"] = ["missing"]
    run = evaluation.evaluate_case(_case(), artifact)
    failed = {(x["stage"], x["criterion_id"]) for x in run["scores"] if not x["pass"]}
    assert ("task_to_materials", "material_sufficiency") in failed
    assert ("materials_to_key", "answer_support") in failed


def test_skill_map_rejects_unknown_and_blocked_skills():
    artifact = _artifact()
    artifact["tasks"][0]["skill_id"] = "invented.skill"
    artifact["skill_map"] = {
        "coverage": True,
        "pack_id": "python-intro",
        "nodes": [{"id": "python.control.loop", "mastery_evidence": {"threshold": "输出可复现"}}],
        "edges": [],
        "blocked": ["invented.skill"],
    }
    run = evaluation.evaluate_case(_case(), artifact)
    assert run["decision"] == "fail"
    assert run["first_failing_stage"] == "skill_map"


def test_skill_map_coverage_gap_and_skipped_focus_fail():
    gap = evaluation.evaluate_case(_case(), {"skill_map": {
        "coverage": False, "gaps": ["口语"], "pack_id": "cet4",
        "nodes": [{"id": "cet4.vocab.high_freq", "mastery_evidence": {"threshold": "8/10"}}],
        "edges": [],
    }})
    assert gap["decision"] == "fail"
    skipped = evaluation.evaluate_case(_case(), {"skill_map": {
        "coverage": True, "pack_id": "cet4",
        "focus": {"skill_id": "cet4.listening.short_dialogue"},
        "nodes": [{"id": "cet4.listening.short_dialogue", "band": "skipped",
                    "mastery_evidence": {"threshold": "4/5"}}],
        "edges": [],
    }})
    assert skipped["decision"] == "fail"


def test_ambiguous_semantic_result_defers_instead_of_passing():
    case = _case(semantic_checks=[{"id": "relevance", "stage": "goal_to_task", "rubric": "任务直接服务目标"}])
    run = evaluation.evaluate_case(case, _artifact(), semantic_judge=lambda *_: {
        "criterion_id": "relevance", "score": 0.5, "pass": False,
        "uncertainty": 0.6, "reason": "证据不足", "evidence": [],
    })
    assert run["decision"] == "needs_review"


def test_release_gate_rejects_false_pass_and_instability():
    runs = [
        dict(evaluation.evaluate_case(_case(expected={"decision": "fail"}), _artifact()), repeat_group="g"),
        dict(evaluation.evaluate_case(_case(), _artifact()), repeat_group="g"),
        dict(evaluation.evaluate_case(_case(), _artifact(tasks=[])), repeat_group="g"),
    ]
    report = evaluation.evaluate_suite(runs)
    assert report["release"]["pass"] is False
    assert report["metrics"]["false_pass_rate"] > 0
    assert report["metrics"]["acceptance_flip_rate"] > 0


def test_production_sample_is_redacted_and_can_be_promoted(tmp_path):
    sample_path = tmp_path / "samples.jsonl"
    evaluation.record_production_sample(sample_path, {
        "goal": "secret goal", "model": "deepseek", "failure_stage": "materials_to_key",
        "user_content": "private answer", "criterion_ids": ["c1"],
    })
    stored = json.loads(sample_path.read_text(encoding="utf-8").splitlines()[0])
    assert "secret goal" not in json.dumps(stored)
    assert "private answer" not in json.dumps(stored)
    assert stored["content_retained"] is False

    corpus = tmp_path / "regressions.jsonl"
    promoted = evaluation.promote_sample(stored, corpus, "fail", "two-reviewer adjudication")
    assert promoted["human_label"] == "fail"
    assert json.loads(corpus.read_text(encoding="utf-8"))["source_sample_id"] == stored["id"]


def test_versioned_golden_corpus_has_required_risk_coverage():
    cases = evaluation.load_cases(evaluation.DEFAULT_CORPUS)
    assert len(cases) >= 20
    tags = {tag for case in cases for tag in case.get("risk_tags", [])}
    assert {"irrelevant_task", "criterion_omission", "missing_materials", "unsupported_key",
            "false_acceptance", "contradiction", "paraphrase", "ambiguous"} <= tags
    assert all(case.get("id") and case.get("version") for case in cases)


def test_golden_negative_cases_count_as_success_when_correctly_rejected():
    cases = evaluation.load_cases(evaluation.DEFAULT_CORPUS)
    runs = [evaluation.evaluate_case(case, case["artifact"]) for case in cases
            if not case.get("semantic_checks")]
    report = evaluation.evaluate_suite(runs)
    assert report["metrics"]["regressions"] == 0
    assert report["release"]["pass"] is True


def test_human_calibration_reports_confusion_and_agreement():
    labels = [
        {"id": "1", "reviewer_a": "pass", "reviewer_b": "pass", "adjudicated": "pass", "judge": "pass"},
        {"id": "2", "reviewer_a": "fail", "reviewer_b": "needs_review", "adjudicated": "fail", "judge": "pass"},
    ]
    metrics = evaluation.calibrate_judge(labels)
    assert metrics["double_reviewed"] == 2
    assert metrics["reviewer_agreement"] == 0.5
    assert metrics["false_pass_rate"] == 1.0
    assert metrics["confusion"]["fail->pass"] == 1


def test_semantic_judge_contract_rejects_unstructured_output():
    case = _case(semantic_checks=[{"id": "relevance", "stage": "goal_to_task", "rubric": "相关性"}])
    run = evaluation.evaluate_case(case, _artifact(), semantic_judge=lambda *_: {"pass": True})
    assert run["decision"] == "needs_review"
    semantic = next(x for x in run["scores"] if x["criterion_id"] == "relevance")
    assert semantic["pass"] is False
    assert "结构" in semantic["reason"]


def test_model_judge_is_criterion_scoped_and_versioned():
    captured = {}
    def model_call(messages):
        captured["messages"] = messages
        return {"criterion_id": "relevance", "score": 0.9, "pass": True,
                "uncertainty": 0.1, "reason": "直接覆盖", "evidence": ["t1"]}
    judge = evaluation.make_semantic_judge(model_call, "deepseek-rubric-v2")
    result = judge({"id": "relevance", "stage": "goal_to_task", "rubric": "任务直接服务目标"}, _case(), _artifact())
    assert result["scorer_version"] == "deepseek-rubric-v2"
    prompt = json.dumps(captured["messages"], ensure_ascii=False)
    assert "任务直接服务目标" in prompt
    assert "criterion_id" in prompt


def test_generation_gate_uses_stable_criterion_ids_without_requiring_evidence():
    criteria = evaluation.criterion_records(["输出正确", "附运行截图"])
    reordered = evaluation.criterion_records(["附运行截图", "输出正确"])
    assert {x["text"]: x["id"] for x in criteria} == {x["text"]: x["id"] for x in reordered}
    case = _case(goal={"id": "g", "final_outcome": "程序可运行",
                       "success_criteria": criteria, "constraints": []})
    artifact = _artifact(evidence=[], acceptance={})
    artifact["tasks"][0]["criterion_ids"] = [x["id"] for x in criteria]
    run = evaluation.evaluate_generation(case, artifact)
    assert run["decision"] == "pass"
    assert all(x["stage"] != "evidence_to_acceptance" for x in run["scores"])


def test_suite_reports_slice_uncertainty_and_task_set_stability():
    run_a = evaluation.evaluate_case(_case(), _artifact())
    run_b = evaluation.evaluate_case(_case(), _artifact(tasks=[dict(_artifact()["tasks"][0], id="t2")]))
    for run in (run_a, run_b):
        run["repeat_group"] = "same-prompt"
        run["slices"] = ["learning"]
    report = evaluation.evaluate_suite([run_a, run_b])
    assert report["metrics"]["sample_count"] == 2
    assert "standard_error" in report["metrics"]
    assert report["metrics"]["slices"]["learning"]["cases"] == 2
    assert report["metrics"]["task_set_overlap"] == 0.0


def test_raw_production_content_requires_explicit_consent(tmp_path):
    path = tmp_path / "samples.jsonl"
    sample = evaluation.record_production_sample(path, {"user_content": "private"}, retain_content=True)
    assert sample["content_retained"] is False
    sample = evaluation.record_production_sample(path, {"user_content": "private"}, retain_content=True, consent=True)
    assert sample["content"] == "private"


def test_candidate_comparison_reports_metric_deltas():
    baseline = {"metrics": {"false_pass_rate": 0.01, "criterion_coverage": 0.95}}
    candidate = {"metrics": {"false_pass_rate": 0.0, "criterion_coverage": 1.0}}
    delta = evaluation.compare_reports(baseline, candidate)
    assert delta["false_pass_rate"] == -0.01
    assert delta["criterion_coverage"] == 0.05
