#!/usr/bin/env python3
"""Adaptive goal loop: judge feedback, adjust tasks, learn user patterns."""

import copy
import time
from datetime import datetime

from learning import (ability_profile, diagnostic_dimensions, due_review_task, fallback_task_templates as learning_fallback_templates, initial_diagnostic_tasks, is_generic_planning_task, knowledge_graph, learning_focus, merge_knowledge_graph, next_learning_task,
                      normalize_diagnostic_dimensions, set_diagnostic_dimensions,
                      task_consistency_issues, task_semantic_key,
                      record_learning_outcome, sync_task_graph, task_is_unlocked)
from utils import task_actual_minutes


OUTCOME_POINTS = {"accepted": 10, "partial": 2, "skipped": -5, "failed": -3}


def record_outcome(state, outcome, now=None):
    """Apply the small, explainable motivation loop to state."""
    outcome = str(outcome or "failed")
    points = OUTCOME_POINTS.get(outcome, 0)
    model = state.setdefault("user_model", {})
    motivation = state.setdefault("motivation", {"points": 0, "streak": 0, "best_streak": 0, "history": []})
    motivation["points"] = int(motivation.get("points", 0) or 0) + points
    if outcome == "accepted":
        motivation["streak"] = int(motivation.get("streak", 0) or 0) + 1
        motivation["best_streak"] = max(int(motivation.get("best_streak", 0) or 0), motivation["streak"])
    elif outcome in {"skipped", "failed"}:
        motivation["streak"] = 0
    motivation["history"] = (motivation.get("history", []) + [{"outcome": outcome, "points": points,
        "ts": datetime.fromtimestamp(now or time.time()).isoformat()}])[-100:]
    model["motivation_points"] = motivation["points"]
    model["streak"] = motivation["streak"]
    return {"outcome": outcome, "points": points, "total": motivation["points"], "streak": motivation["streak"]}


KINDS = {"too_hard", "too_easy", "no_time", "stuck", "wrong_direction"}


def goal_readiness(details):
    details = details or {}
    checks = (
        ("outcome", "最终成果"), ("deadline", "目标日期"), ("baseline", "当前基础"),
        ("success_criteria", "成功标准"), ("constraints", "现实约束"),
    )
    missing = [label for key, label in checks if not details.get(key)]
    questions = {
        "最终成果": "最终要交付什么可见成果？",
        "目标日期": "希望在哪一天前完成？",
        "当前基础": "现在已经做到哪一步？",
        "成功标准": "满足哪些可核验条件才算成功？",
        "现实约束": "每天时间、工具或资源有什么限制？",
    }
    score = round((len(checks) - len(missing)) * 100 / len(checks))
    return {"score": score, "ready": not missing, "missing": missing,
            "questions": [questions[label] for label in missing]}


def record_task_outcome(task, passed, now=None):
    now = now or time.time()
    if task.get("started_at"):
        try:
            elapsed = max(0, now - datetime.fromisoformat(task["started_at"]).timestamp())
            task["actual_seconds"] = round(float(task.get("actual_seconds", 0) or 0) + elapsed, 3)
        except (TypeError, ValueError):
            pass
        task["started_at"] = ""
    if passed:
        task["completed_at"] = datetime.fromtimestamp(now).isoformat()
    return task


def classify_feedback(text, kind=""):
    if kind in KINDS:
        return kind
    text = str(text or "").lower()
    rules = (
        ("wrong_direction", ("方向不对", "偏离", "不相关")),
        ("too_easy", ("太简单", "太容易")),
        ("no_time", ("没时间", "来不及", "时间不够")),
        ("stuck", ("卡住", "不会", "不知道怎么")),
        ("too_hard", ("太难", "做不到", "难度太高")),
    )
    return next((name for name, words in rules if any(word in text for word in words)), "stuck")


def assess_feedback(state, task_index, text, kind="", source="user", now=None):
    tasks = state.get("tasks", [])
    if task_index < 0 or task_index >= len(tasks):
        raise IndexError("task index out of range")
    task = tasks[task_index]
    kind = classify_feedback(text, kind)
    estimate = max(5, int(task.get("estimated_minutes", 30) or 30))
    actual = max(0, int(task_actual_minutes(task)))
    attempts = max(0, int(task.get("attempts", 0) or 0))
    failed = task.get("acceptance_result", {}).get("pass") is False and bool(task.get("acceptance_result"))

    evidence = []
    score = 0.2
    if attempts >= 2:
        score += 0.25; evidence.append("已尝试 {} 次".format(attempts))
    if actual >= estimate:
        score += 0.25; evidence.append("实际投入 {} 分钟，达到预计时长".format(actual))
    if failed:
        score += 0.25; evidence.append("最近一次验收未通过")
    if task.get("evidence"):
        score += 0.1; evidence.append("已有过程证据")
    if source == "system":
        score += 0.15; evidence.append("由执行数据触发")
    score = min(1.0, score)

    if kind == "wrong_direction":
        action, automatic = "realign", False
        reason = "方向变更会影响目标，需用户确认后再调整"
    elif kind == "too_easy":
        action, automatic = "raise_challenge", score >= 0.45
        reason = "提高验证深度，不增加无关工作"
    elif kind == "no_time":
        action, automatic = "reduce_load", score >= 0.55
        reason = "减少当日负荷，保留原验收标准"
    elif score >= 0.55:
        action, automatic = "split_task", True
        reason = "证据支持存在真实阻力，先拆出最小可验证步骤"
    else:
        action, automatic = "diagnose", False
        reason = "证据不足，先完成一次最小尝试再判断是否降负荷"

    return {
        "id": "feedback_{}".format(int((now or time.time()) * 1000)),
        "ts": datetime.now().isoformat(), "source": source, "task_id": task.get("id", ""),
        "task_index": task_index, "kind": kind, "text": str(text or "").strip(),
        "confidence": round(score, 2), "evidence": evidence, "decision": action,
        "automatic": automatic, "reason": reason, "applied": False,
    }


def apply_decision(state, decision):
    tasks = state.get("tasks", [])
    index = int(decision.get("task_index", -1))
    if index < 0 or index >= len(tasks) or decision.get("applied"):
        return decision
    task = tasks[index]
    action = decision.get("decision")

    if action == "split_task":
        if task.get("source") == "adaptive":
            decision.update(decision="diagnose", automatic=False,
                            reason="当前已经是最小步骤，不再重复拆分")
            return decision
        first = copy.deepcopy(task)
        first["id"] = "{}_step_{}".format(task.get("id", "task"), int(time.time()))
        title = task.get("title", "当前任务")
        while title.startswith("最小步骤："):
            title = title[len("最小步骤："):]
        first["title"] = "最小步骤：{}".format(title)
        first["text"] = first["title"]
        first["description"] = "先完成一个可检查的中间成果，并记录阻塞点。"
        first["estimated_minutes"] = max(10, min(30, int(task.get("estimated_minutes", 30) or 30) // 2))
        first["expected_output"] = "一个可检查的中间成果"
        first["acceptance"] = "已提交中间成果，并明确记录下一步或阻塞点"
        first["status"] = "pending"; first["evidence"] = []; first["acceptance_result"] = {}
        first["source"] = "adaptive"
        task["status"] = "pending"
        task["depends_on"] = list(dict.fromkeys([first["id"]] + list(task.get("depends_on", []))))
        task["adjustment_reason"] = decision.get("reason", "")
        tasks[index:index + 1] = [first, task]
    elif action == "raise_challenge":
        task["difficulty"] = min(5, int(task.get("difficulty", 2) or 2) + 1)
        if "独立验证" not in task.get("acceptance", ""):
            task["acceptance"] = (task.get("acceptance", "") + "；提供独立验证结果").strip("；")
    elif action == "reduce_load":
        for later in tasks[index + 1:]:
            if later.get("status") == "pending":
                later["status"] = "deferred"
        task["adjustment_reason"] = "保留当前核心任务，其余任务顺延"
    else:
        return decision

    decision["applied"] = True
    decision["applied_at"] = datetime.now().isoformat()
    state["tasks"] = tasks
    return decision


def record_feedback(state, task_index, text, kind="", source="user", auto_apply=True):
    decision = assess_feedback(state, task_index, text, kind, source)
    state.setdefault("feedback_history", []).append(decision)
    state["feedback_history"] = state["feedback_history"][-200:]
    profile = state.setdefault("user_model", {})
    counts = profile.setdefault("feedback_counts", {})
    counts[decision["kind"]] = int(counts.get(decision["kind"], 0) or 0) + 1
    profile["feedback_total"] = int(profile.get("feedback_total", 0) or 0) + 1
    if decision["confidence"] >= 0.55:
        profile["validated_feedback"] = int(profile.get("validated_feedback", 0) or 0) + 1
    profile["feedback_reliability"] = round(
        int(profile.get("validated_feedback", 0) or 0) / max(1, profile["feedback_total"]), 2)
    profile["updated_at"] = datetime.now().isoformat()
    if auto_apply and decision["automatic"]:
        apply_decision(state, decision)
    return decision


def passive_review(state, now=None):
    """Return at most one new automatic adjustment to avoid plan churn."""
    now = now or time.time()
    seen = state.setdefault("adaptive_signals", [])
    for index, task in enumerate(state.get("tasks", [])):
        if task.get("status") != "doing" or not task.get("started_at"):
            continue
        try:
            started = datetime.fromisoformat(task["started_at"]).timestamp()
        except (TypeError, ValueError):
            continue
        estimate = max(5, int(task.get("estimated_minutes", 30) or 30))
        elapsed = int((now - started) / 60)
        signal = "overrun:{}:{}".format(task.get("id", index), estimate)
        if elapsed >= estimate * 1.5 and signal not in seen:
            task["actual_seconds"] = elapsed * 60
            decision = record_feedback(state, index, "实际耗时明显超过预计", "too_hard", "system")
            seen.append(signal); state["adaptive_signals"] = seen[-100:]
            return decision
    return None


def complete_review(state, foreground=None):
    tasks = state.get("tasks", [])
    total = len(tasks)
    done = sum(1 for task in tasks if task.get("status") == "done")
    accepted = [task for task in tasks if task.get("acceptance_result")]
    passed = sum(1 for task in accepted if task["acceptance_result"].get("pass"))
    estimates = [max(5, int(task.get("estimated_minutes", 30) or 30)) for task in tasks]
    actuals = [max(0, int(task_actual_minutes(task))) for task in tasks]
    measured = [(actual, estimate) for actual, estimate in zip(actuals, estimates) if actual]
    overrun = round(sum(actual / estimate for actual, estimate in measured) / len(measured), 2) if measured else 1.0
    completion = round(done / total, 2) if total else 0.0
    friction = {}
    for row in state.get("feedback_history", []):
        kind = row.get("kind", "")
        if kind:
            friction[kind] = friction.get(kind, 0) + 1

    if completion < 0.5 or overrun > 1.4:
        capacity = 0.75
    elif completion > 0.85 and overrun <= 1.0:
        capacity = 1.1
    else:
        capacity = 1.0
    completed_minutes = [estimates[i] for i, task in enumerate(tasks) if task.get("status") == "done"]
    preferred = round(sum(completed_minutes) / len(completed_minutes)) if completed_minutes else 30
    review = {
        "ts": datetime.now().isoformat(), "completion_rate": completion,
        "acceptance_rate": round(passed / len(accepted), 2) if accepted else 0.0,
        "overrun_ratio": overrun, "done": done, "total": total,
        "common_friction": max(friction, key=friction.get) if friction else "",
        "capacity_factor": capacity, "preferred_task_minutes": max(10, min(90, preferred)),
        "top_apps": sorted((foreground or {}).items(), key=lambda row: -row[1])[:5],
    }
    profile = state.setdefault("user_model", {})
    profile.update({
        "capacity_factor": capacity,
        "preferred_task_minutes": review["preferred_task_minutes"],
        "common_friction": review["common_friction"],
        "last_completion_rate": completion,
        "last_acceptance_rate": review["acceptance_rate"],
        "updated_at": review["ts"],
    })
    profile["review_count"] = int(profile.get("review_count", 0) or 0) + 1
    state["last_review"] = review
    state["next_cycle_context"] = {
        "capacity_factor": capacity, "preferred_task_minutes": review["preferred_task_minutes"],
        "unfinished": [task.get("id") for task in tasks if task.get("status") != "done"],
        "acceptance_gaps": [task.get("acceptance_result", {}).get("missing", []) for task in tasks
                            if task.get("acceptance_result") and not task["acceptance_result"].get("pass")],
    }
    return review


def prepare_next_cycle(state):
    unfinished = []
    for task in state.get("tasks", []):
        if task.get("status") == "done":
            continue
        item = copy.deepcopy(task)
        item["status"] = "pending"
        item["started_at"] = ""
        unfinished.append(item)
    state["tasks"] = unfinished
    state["done_flags"] = [False] * len(unfinished)
    state["completion_pct"] = 0
    state["plan_locked"] = False
    state.setdefault("next_cycle_context", {})["started_at"] = datetime.now().isoformat()
    return unfinished
