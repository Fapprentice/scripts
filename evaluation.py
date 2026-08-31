"""Versioned, deterministic-first evaluation for Task Verge's complete AI chain."""

from __future__ import annotations

import hashlib
import argparse
import json
import math
import subprocess
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_CORPUS = ROOT / "evals" / "golden.json"
DEFAULT_THRESHOLDS = {
    "critical_failures": 0,
    "missing_material_rate": 0.0,
    "unsupported_key_rate": 0.0,
    "criterion_coverage": 0.95,
    "false_pass_rate": 0.02,
    "acceptance_flip_rate": 0.0,
    "task_set_overlap": 0.8,
}
STAGES = ("goal_quality", "goal_to_task", "task_to_materials", "materials_to_key", "evidence_to_acceptance", "skill_map")


def criterion_records(criteria):
    records = []
    for text in criteria or []:
        value = str(text).strip()
        if value:
            records.append({"id": "criterion-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:10],
                            "text": value})
    return records


def load_cases(path=DEFAULT_CORPUS):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = data.get("cases", data) if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise ValueError("evaluation corpus must contain a case list")
    defaults = data.get("defaults", {}) if isinstance(data, dict) else {}
    cases = [{**defaults, **case, "goal": {**defaults.get("goal", {}), **case.get("goal", {})},
              "artifact": {**defaults.get("artifact", {}), **case.get("artifact", {})}}
             for case in cases]
    ids = [case.get("id") for case in cases]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("evaluation case ids must be present and unique")
    return cases


def _score(stage, criterion_id, passed, value, reason, evidence=(), critical=True, scorer="deterministic-v1"):
    return {"stage": stage, "criterion_id": criterion_id, "scorer_version": scorer,
            "value": round(float(value), 4), "pass": bool(passed), "critical": bool(critical),
            "reason": reason, "evidence": list(evidence)}


def _ids(rows):
    return {str(row.get("id")) for row in rows if isinstance(row, dict) and row.get("id")}


def _contradictions(goal):
    values = [str(x).casefold() for x in goal.get("constraints", [])]
    pairs = (("不得", "必须"), ("禁止", "允许"), ("离线", "仅云端"), ("无预算", "付费"))
    joined = "\n".join(values)
    return ["{} / {}".format(a, b) for a, b in pairs if a in joined and b in joined]


def _goal_scores(case, metrics):
    goal = case.get("goal", {})
    criteria = goal.get("success_criteria", [])
    observable = bool(str(goal.get("final_outcome", "")).strip())
    valid_criteria = [x for x in criteria if isinstance(x, dict) and x.get("id") and x.get("text")]
    contradictions = _contradictions(goal)
    metrics["goal_criterion_count"] = len(valid_criteria)
    metrics["contradictions"] = contradictions
    return [
        _score("goal_quality", "outcome_observability", observable, int(observable),
               "最终成果可观察" if observable else "缺少最终成果"),
        _score("goal_quality", "criterion_verifiability", bool(valid_criteria) and len(valid_criteria) == len(criteria),
               len(valid_criteria) / max(1, len(criteria)), "成功标准必须具有稳定 ID 和文本"),
        _score("goal_quality", "non_contradiction", not contradictions, int(not contradictions),
               "目标约束无冲突" if not contradictions else "目标约束冲突: " + ", ".join(contradictions)),
    ]


def _goal_task_scores(case, artifact, metrics):
    criteria = _ids(case.get("goal", {}).get("success_criteria", []))
    tasks = [x for x in artifact.get("tasks", []) if isinstance(x, dict)]
    covered = set().union(*(set(map(str, x.get("criterion_ids", []))) for x in tasks)) if tasks else set()
    uncovered = sorted(criteria - covered)
    relevant = [x for x in tasks if criteria.intersection(map(str, x.get("criterion_ids", [])))]
    actionable = [x for x in tasks if x.get("title") and x.get("expected_output") and x.get("acceptance") and x.get("estimated_minutes")]
    metrics.update({"criterion_coverage": len(criteria & covered) / max(1, len(criteria)),
                    "uncovered_criteria": uncovered,
                    "task_relevance": len(relevant) / max(1, len(tasks))})
    return [
        _score("goal_to_task", "criterion_coverage", not uncovered and bool(criteria), metrics["criterion_coverage"],
               "所有成功标准均有任务覆盖" if not uncovered else "未覆盖: " + ", ".join(uncovered)),
        _score("goal_to_task", "task_relevance", len(relevant) == len(tasks) and bool(tasks), metrics["task_relevance"],
               "任务均关联成功标准" if len(relevant) == len(tasks) and tasks else "存在无关或缺失任务"),
        _score("goal_to_task", "actionability", len(actionable) == len(tasks) and bool(tasks),
               len(actionable) / max(1, len(tasks)), "任务需包含动作、交付物、时长和验收规则"),
    ]


def _material_scores(artifact, metrics):
    tasks = [x for x in artifact.get("tasks", []) if isinstance(x, dict)]
    material_tasks = [x for x in tasks if x.get("requires_materials") or x.get("answer_key") or x.get("materials")]
    complete = [x for x in material_tasks if x.get("materials")]
    material_ids = set().union(*(_ids(x.get("materials", [])) for x in tasks)) if tasks else set()
    keys = [key for task in tasks for key in task.get("answer_key", []) if isinstance(key, dict)]
    unsupported = [key.get("id", "unknown") for key in keys
                   if not set(map(str, key.get("material_ids", []))) or
                   not set(map(str, key.get("material_ids", []))).issubset(material_ids)]
    metrics["missing_material_rate"] = (len(material_tasks) - len(complete)) / max(1, len(material_tasks))
    metrics["unsupported_key_rate"] = len(unsupported) / max(1, len(keys))
    metrics["unsupported_keys"] = unsupported
    return [
        _score("task_to_materials", "material_sufficiency", len(complete) == len(material_tasks),
               1 - metrics["missing_material_rate"], "执行材料完整" if len(complete) == len(material_tasks) else "材料型任务缺少材料"),
        _score("materials_to_key", "answer_support", not unsupported, 1 - metrics["unsupported_key_rate"],
               "答案均由材料支持" if not unsupported else "答案缺少材料依据: " + ", ".join(map(str, unsupported))),
    ]


def _skill_map_scores(case, artifact, metrics):
    skill_map = artifact.get("skill_map") or case.get("skill_map") or {}
    if not skill_map or not (skill_map.get("nodes") or skill_map.get("pack_id")):
        return []
    nodes = [x for x in skill_map.get("nodes", []) if isinstance(x, dict)]
    edges = [x for x in skill_map.get("edges", []) if isinstance(x, dict)]
    tasks = [x for x in artifact.get("tasks", []) if isinstance(x, dict)]
    known = {str(node.get("id") or "") for node in nodes}
    missing_contract = [node.get("id") for node in nodes if not (node.get("mastery_evidence") or {}).get("threshold")]
    unknown = [task.get("skill_id") for task in tasks if task.get("skill_id") and str(task.get("skill_id")) not in known]
    blocked = [task.get("skill_id") for task in tasks if task.get("skill_id") and str(task.get("skill_id")) in set(skill_map.get("blocked") or [])]
    metrics["unknown_skill_ids"] = unknown
    metrics["blocked_skill_ids"] = blocked
    coverage = bool(skill_map.get("coverage", True)) and not skill_map.get("gaps")
    skipped = [node.get("id") for node in nodes if node.get("band") == "skipped"]
    focus = (skill_map.get("focus") or {}).get("skill_id")
    skip_ok = not (focus and focus in skipped)
    return [
        _score("skill_map", "map_coverage", coverage, int(coverage),
               "技能地图覆盖最终成果" if coverage else "技能地图未覆盖最终成果"),
        _score("skill_map", "node_contract", not missing_contract, int(not missing_contract),
               "节点均有掌握证据" if not missing_contract else "缺少掌握证据: " + ", ".join(map(str, missing_contract))),
        _score("skill_map", "task_skill_anchor", not unknown, int(not unknown),
               "学习任务均锚定技能地图" if not unknown else "未知技能: " + ", ".join(map(str, unknown))),
        _score("skill_map", "hard_unlock", not blocked, int(not blocked),
               "未生成未解锁节点" if not blocked else "未解锁: " + ", ".join(map(str, blocked))),
        _score("skill_map", "baseline_skip", skip_ok, int(skip_ok),
               "焦点不落在已跳过节点" if skip_ok else "焦点落在已跳过节点"),
        _score("skill_map", "standard_hold", not skill_map.get("lowered_standard"), int(not skill_map.get("lowered_standard")),
               "反馈未降低成功标准" if not skill_map.get("lowered_standard") else "反馈降低了成功标准"),
        _score("skill_map", "proposal_lock", not skill_map.get("proposal_error"), int(not skill_map.get("proposal_error")),
               "提案锁定 pack 版本" if not skill_map.get("proposal_error") else "提案未锁定 pack 版本: " + str(skill_map.get("proposal_error"))),
    ]


def _acceptance_scores(case, artifact, metrics):
    criteria = _ids(case.get("goal", {}).get("success_criteria", []))
    evidence = [x for x in artifact.get("evidence", []) if isinstance(x, dict)]
    evidenced = set().union(*(set(map(str, x.get("criterion_ids", []))) for x in evidence)) if evidence else set()
    accepted = artifact.get("acceptance", {}).get("decision") == "accepted"
    accepted_ids = set(map(str, artifact.get("acceptance", {}).get("criterion_ids", [])))
    sufficient = bool(evidence) and criteria.issubset(evidenced) and criteria.issubset(accepted_ids)
    false_acceptance = accepted and not sufficient
    metrics.update({"evidence_coverage": len(criteria & evidenced) / max(1, len(criteria)),
                    "false_acceptance": false_acceptance})
    return [_score("evidence_to_acceptance", "evidence_alignment", sufficient and accepted,
                   len(criteria & evidenced) / max(1, len(criteria)),
                   "证据与验收决定覆盖全部标准" if sufficient and accepted else "证据或验收决定未覆盖全部标准")]


def _semantic_scores(case, artifact, judge):
    scores = []
    for check in case.get("semantic_checks", []):
        if judge is None:
            result = {"score": 0, "pass": False, "uncertainty": 1, "reason": "未配置语义裁判", "evidence": []}
        else:
            result = judge(check, case, artifact) or {}
        required = {"criterion_id", "score", "pass", "uncertainty", "reason", "evidence"}
        if not isinstance(result, dict) or not required.issubset(result):
            result = {"score": 0, "pass": False, "uncertainty": 1,
                      "reason": "语义裁判返回结构不完整", "evidence": []}
        uncertainty = max(0.0, min(1.0, float(result.get("uncertainty", 1))))
        scores.append(_score(check.get("stage", "goal_to_task"), check["id"], result.get("pass", False),
                             result.get("score", 0), result.get("reason", "语义裁判无理由"),
                             result.get("evidence", []), critical=True,
                             scorer=str(result.get("scorer_version", "semantic-v1"))))
        scores[-1]["uncertainty"] = uncertainty
    return scores


def make_semantic_judge(model_call, scorer_version):
    """Adapt a JSON model call to the narrow criterion-level judge interface."""
    def judge(check, case, artifact):
        payload = {"criterion_id": check["id"], "rubric": check.get("rubric", ""),
                   "goal": case.get("goal", {}), "tasks": artifact.get("tasks", []),
                   "materials_and_keys": [{"task_id": x.get("id"), "materials": x.get("materials", []),
                                            "answer_key": x.get("answer_key", [])}
                                           for x in artifact.get("tasks", [])],
                   "evidence": artifact.get("evidence", []), "acceptance": artifact.get("acceptance", {})}
        messages = [
            {"role": "system", "content": "你是严格的评测裁判。只评当前 criterion，不做整体印象评分。只返回 JSON，字段必须为 criterion_id、score(0-1)、pass、uncertainty(0-1)、reason、evidence。证据不足时 pass=false 且 uncertainty>=0.25。"},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        result = model_call(messages)
        if isinstance(result, dict):
            result = dict(result); result["scorer_version"] = scorer_version
        return result
    return judge


def evaluate_case(case, artifact, semantic_judge=None):
    """Score one immutable goal-to-acceptance artifact bundle."""
    metrics = {}
    scores = (_goal_scores(case, metrics) + _goal_task_scores(case, artifact, metrics) +
              _material_scores(artifact, metrics) + _acceptance_scores(case, artifact, metrics) +
              _skill_map_scores(case, artifact, metrics) +
              _semantic_scores(case, artifact, semantic_judge))
    uncertain = any(x.get("uncertainty", 0) >= 0.25 for x in scores)
    critical = [x for x in scores if x["critical"] and not x["pass"]]
    decision = "needs_review" if uncertain else "fail" if critical else "pass"
    first = next((stage for stage in STAGES if any(not x["pass"] and x["stage"] == stage for x in scores)), None)
    return {"case_id": case["id"], "case_version": case.get("version", 1),
            "timestamp": datetime.now(timezone.utc).isoformat(), "decision": decision,
            "expected_decision": case.get("expected", {}).get("decision"),
            "first_failing_stage": first, "scores": scores, "metrics": metrics,
            "metadata": dict(artifact.get("metadata", {})), "slices": list(case.get("slices", [])),
            "task_ids": sorted(_ids(artifact.get("tasks", [])))}


def evaluate_generation(case, artifact, semantic_judge=None):
    """Gate a generated plan before user evidence exists."""
    metrics = {}
    scores = (_goal_scores(case, metrics) + _goal_task_scores(case, artifact, metrics) +
              _material_scores(artifact, metrics) + _skill_map_scores(case, artifact, metrics) +
              _semantic_scores(case, artifact, semantic_judge))
    uncertain = any(x.get("uncertainty", 0) >= 0.25 for x in scores)
    failed = any(x["critical"] and not x["pass"] for x in scores)
    decision = "needs_review" if uncertain else "fail" if failed else "pass"
    first = next((stage for stage in STAGES if any(not x["pass"] and x["stage"] == stage for x in scores)), None)
    return {"case_id": case["id"], "case_version": case.get("version", 1), "decision": decision,
            "first_failing_stage": first, "scores": scores, "metrics": metrics,
            "metadata": dict(artifact.get("metadata", {})), "slices": list(case.get("slices", []))}


def evaluate_suite(runs, thresholds=None):
    thresholds = dict(DEFAULT_THRESHOLDS, **(thresholds or {}))
    total = max(1, len(runs))
    false_passes = sum(x.get("decision") == "pass" and x.get("expected_decision") == "fail" for x in runs)
    groups = defaultdict(set)
    task_groups = defaultdict(list)
    for run in runs:
        if run.get("repeat_group"):
            groups[run["repeat_group"]].add(run.get("decision"))
            task_groups[run["repeat_group"]].append(set(run.get("task_ids", [])))
    positive = [x for x in runs if x.get("expected_decision") == "pass"]
    metric_runs = positive or runs
    metric_total = max(1, len(metric_runs))
    regressions = [x for x in runs if x.get("expected_decision") and x.get("decision") != x.get("expected_decision")]
    overlaps = []
    for sets in task_groups.values():
        for index, left in enumerate(sets):
            for right in sets[index + 1:]:
                overlaps.append(len(left & right) / max(1, len(left | right)))
    correct_rate = (len(runs) - len(regressions)) / total
    slice_rows = {}
    for name in sorted({name for run in runs for name in run.get("slices", [])}):
        rows = [run for run in runs if name in run.get("slices", [])]
        slice_rows[name] = {"cases": len(rows),
                            "regressions": sum(run.get("expected_decision") and run.get("decision") != run.get("expected_decision") for run in rows),
                            "needs_review": sum(run.get("decision") == "needs_review" for run in rows)}
    metrics = {
        "cases": len(runs),
        "sample_count": len(runs),
        "standard_error": math.sqrt(correct_rate * (1 - correct_rate) / total),
        "regressions": len(regressions),
        "regression_case_ids": [x.get("case_id") for x in regressions],
        "critical_failures": len(regressions),
        "missing_material_rate": sum(x.get("metrics", {}).get("missing_material_rate", 0) for x in metric_runs) / metric_total,
        "unsupported_key_rate": sum(x.get("metrics", {}).get("unsupported_key_rate", 0) for x in metric_runs) / metric_total,
        "criterion_coverage": sum(x.get("metrics", {}).get("criterion_coverage", 0) for x in metric_runs) / metric_total,
        "false_pass_rate": false_passes / total,
        "acceptance_flip_rate": sum(len(v) > 1 for v in groups.values()) / max(1, len(groups)),
        "task_set_overlap": sum(overlaps) / len(overlaps) if overlaps else 1.0,
        "needs_review_rate": sum(x.get("decision") == "needs_review" for x in runs) / total,
        "stage_failures": dict(Counter(x.get("first_failing_stage") for x in runs if x.get("first_failing_stage"))),
        "slices": slice_rows,
    }
    checks = {
        "critical_failures": metrics["critical_failures"] <= thresholds["critical_failures"],
        "missing_material_rate": metrics["missing_material_rate"] <= thresholds["missing_material_rate"],
        "unsupported_key_rate": metrics["unsupported_key_rate"] <= thresholds["unsupported_key_rate"],
        "criterion_coverage": metrics["criterion_coverage"] >= thresholds["criterion_coverage"],
        "false_pass_rate": metrics["false_pass_rate"] <= thresholds["false_pass_rate"],
        "acceptance_flip_rate": metrics["acceptance_flip_rate"] <= thresholds["acceptance_flip_rate"],
        "task_set_overlap": metrics["task_set_overlap"] >= thresholds["task_set_overlap"],
    }
    return {"metrics": metrics, "thresholds": thresholds, "release": {"pass": all(checks.values()), "checks": checks}}


def compare_reports(baseline, candidate):
    shared = set(baseline.get("metrics", {})) & set(candidate.get("metrics", {}))
    return {key: round(float(candidate["metrics"][key]) - float(baseline["metrics"][key]), 6)
            for key in sorted(shared)
            if isinstance(baseline["metrics"][key], (int, float)) and
            isinstance(candidate["metrics"][key], (int, float))}


def calibrate_judge(labels):
    """Compare a pinned judge with double-reviewed, adjudicated human labels."""
    rows = [x for x in labels if x.get("reviewer_a") and x.get("reviewer_b") and
            x.get("adjudicated") and x.get("judge")]
    total = max(1, len(rows))
    confusion = Counter("{}->{}".format(x["adjudicated"], x["judge"]) for x in rows)
    human_fails = sum(x["adjudicated"] == "fail" for x in rows)
    return {"double_reviewed": len(rows),
            "reviewer_agreement": sum(x["reviewer_a"] == x["reviewer_b"] for x in rows) / total,
            "judge_agreement": sum(x["adjudicated"] == x["judge"] for x in rows) / total,
            "false_pass_rate": sum(x["adjudicated"] == "fail" and x["judge"] == "pass" for x in rows) / max(1, human_fails),
            "confusion": dict(confusion)}


def run_corpus(path=DEFAULT_CORPUS, semantic_judge=None, run_log=None):
    cases = load_cases(path)
    runs = []
    for case in cases:
        run = evaluate_case(case, case.get("artifact", {}), semantic_judge)
        if case.get("repeat_group"):
            run["repeat_group"] = case["repeat_group"]
        runs.append(run)
        if run_log:
            write_run(run_log, run)
    return {"runs": runs, "report": evaluate_suite(runs), "revision": git_revision()}


def _main(argv=None):
    parser = argparse.ArgumentParser(description="Run Task Verge AI quality gates")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--run", action="store_true", help="run the versioned golden corpus")
    action.add_argument("--calibrate", metavar="PATH", help="report double-reviewed judge calibration")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--log", help="optional JSONL run log")
    parser.add_argument("--json", action="store_true", help="print the complete JSON result")
    args = parser.parse_args(argv)
    if args.calibrate:
        data = json.loads(Path(args.calibrate).read_text(encoding="utf-8"))
        result = calibrate_judge(data.get("labels", []))
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else
              "Judge calibration: {} labels, agreement={:.1%}, false-pass={:.1%}".format(
                  result["double_reviewed"], result["judge_agreement"], result["false_pass_rate"]))
        return 0 if result["double_reviewed"] and result["false_pass_rate"] <= DEFAULT_THRESHOLDS["false_pass_rate"] else 1
    result = run_corpus(args.corpus, run_log=args.log)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        report = result["report"]
        print("AI eval: {} cases, {} regressions, release={}".format(
            report["metrics"]["cases"], report["metrics"]["regressions"],
            "PASS" if report["release"]["pass"] else "FAIL"))
        for name, passed in report["release"]["checks"].items():
            print("  {} {}".format("PASS" if passed else "FAIL", name))
    return 0 if result["report"]["release"]["pass"] else 1


def write_run(path, run):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(run, ensure_ascii=False, sort_keys=True) + "\n")


def record_production_sample(path, event, retain_content=False, consent=False):
    """Persist privacy-safe metadata; raw user content requires explicit consent."""
    identity = json.dumps({k: event.get(k) for k in ("model", "failure_stage", "criterion_ids")}, sort_keys=True)
    retain_content = bool(retain_content and consent)
    sample = {"id": "sample-" + uuid.uuid4().hex, "timestamp": datetime.now(timezone.utc).isoformat(),
              "fingerprint": hashlib.sha256(identity.encode()).hexdigest()[:16],
              "model": event.get("model", ""), "failure_stage": event.get("failure_stage", ""),
              "criterion_ids": list(event.get("criterion_ids", [])), "content_retained": bool(retain_content)}
    if retain_content:
        sample["content"] = event.get("user_content", "")
    write_run(path, sample)
    return sample


def promote_sample(sample, corpus_path, human_label, adjudication):
    if human_label not in ("pass", "fail", "needs_review") or not str(adjudication).strip():
        raise ValueError("promotion requires an adjudicated human label")
    record = {"id": "regression-" + uuid.uuid4().hex, "version": 1,
              "source_sample_id": sample["id"], "human_label": human_label,
              "adjudication": str(adjudication).strip(), "risk_tags": [sample.get("failure_stage", "production")]}
    write_run(corpus_path, record)
    return record


def git_revision():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(_main())
