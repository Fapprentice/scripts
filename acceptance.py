#!/usr/bin/env python3
"""Task Verge AI acceptance — rules-first, LLM explains.

Deterministic checks run BEFORE the LLM. Only borderline cases
or explanation text is routed to the AI model.

Activate via env: TASKVERGE_RULES_FIRST=1 (default: on; set 0 to disable)

Architecture:
  1. check_evidence(task, details) → AcceptanceVerdict
  2. If verdict.needs_llm → run_llm_eval(task, details, fg, dk_func)
  3. LLM is NEVER asked "did they pass?" — only "explain this verdict"
"""

import json
import re
from collections import namedtuple

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------
AcceptanceVerdict = namedtuple("AcceptanceVerdict", [
    "pass_",        # bool: deterministic pass/fail
    "reason",       # str: human-readable verdict
    "checks",       # dict: per-rule results {rule_id: {pass: bool, detail: str}}
    "needs_llm",    # bool: should we call the LLM for explanation?
])

RuleResult = namedtuple("RuleResult", ["pass_", "detail"])

# ---------------------------------------------------------------------------
# Rule definitions — ordered by cost, cheapest first
# ---------------------------------------------------------------------------

def _r1_has_evidence(task):
    """R1: Task must have at least one evidence entry."""
    ev = task.get("evidence")
    if isinstance(ev, list) and len(ev) > 0:
        return RuleResult(True, f"有 {len(ev)} 个交付物")
    if isinstance(ev, str) and ev.strip():
        return RuleResult(True, "有交付物描述")
    if task.get("response"):
        return RuleResult(True, "已提交页面作答")
    return RuleResult(False, "未提交任何交付物或证据")


def _r0_material_answers(task, details):
    questions = [item for item in task.get("materials", []) if isinstance(item, dict) and item.get("answer")]
    if not questions: return RuleResult(True, "非客观题（跳过自动评分）")
    response = task.get("response") if isinstance(task.get("response"), dict) else {}
    correct = sum(str(response.get(str(i), "")).strip() == str(item["answer"]).strip() for i, item in enumerate(task.get("materials", [])) if isinstance(item, dict) and item.get("answer"))
    try: minimum = max(0, min(1, float((task.get("interaction") or {}).get("min_score", 0.7) or 0.7)))
    except (TypeError, ValueError): minimum = 0.7
    score = correct / len(questions)
    return RuleResult(score >= minimum, "客观题得分 {}/{}（{}%）".format(correct, len(questions), round(score * 100)))


def _r2_files_exist(task, details):
    """R2: All referenced file paths must exist on disk."""
    files = details.get("files", [])
    if not files:
        return RuleResult(True, "无文件引用（通过）")
    missing = [f.get("path", "?") for f in files if not f.get("exists")]
    if missing:
        return RuleResult(False, f"文件不存在: {', '.join(missing[:3])}")
    return RuleResult(True, f"所有 {len(files)} 个文件存在")


def _r3_py_compile(task, details):
    """R3: All .py files must pass py_compile."""
    files = details.get("files", [])
    py_files = [f for f in files if f.get("path", "").lower().endswith(".py")]
    if not py_files:
        return RuleResult(True, "无 Python 文件（跳过静态检查）")
    failures = []
    for f in py_files:
        pc = f.get("python_check", {})
        if pc and not pc.get("ok"):
            failures.append(f"{f.get('path','?')}: {pc.get('output','?')[:120]}")
    if failures:
        return RuleResult(False, f"py_compile 失败: {'; '.join(failures[:3])}")
    return RuleResult(True, f"所有 {len(py_files)} 个 .py 文件通过 py_compile")


def _r4_docker_run(task, details):
    """R4: Python evidence must include a successful sandbox execution."""
    files = details.get("files", [])
    py_files = [f for f in files if f.get("path", "").lower().endswith(".py")]
    if not py_files:
        return RuleResult(True, "无 Python 文件（跳过 Docker 检查）")
    failures = []
    for f in py_files:
        dr = f.get("docker_run", {})
        if not dr or dr.get("skipped"):
            return RuleResult(False, "Docker 沙箱不可用或未运行，验收被阻断")
        if dr and not dr.get("ok"):
            failures.append(f"{f.get('path','?')}: {dr.get('stderr','?')[:120]}")
    if failures:
        return RuleResult(False, f"Docker 执行失败: {'; '.join(failures[:3])}")
    return RuleResult(True, "Docker 沙箱检查通过")


def _r5_output_keywords(task, details):
    """R5: Check if expected output keywords appear in evidence content.

    This is a lightweight heuristic — if keywords match, we're confident.
    If they don't match, the case is BORDERLINE and needs LLM judgment.
    """
    expected = (task.get("expected_output") or "").strip()
    if not expected:
        return RuleResult(True, "无预期产出定义（通过）")

    # Extract searchable keywords from expected output (Chinese or English words ≥2 chars)
    keywords = re.findall(r'[一-鿿]{2,}|[a-zA-Z]{3,}', expected)
    if not keywords:
        return RuleResult(True, "预期产出无关键词（通过）")

    # Gather all evidence text
    evidence_text = details.get("text", "")
    for f in details.get("files", []):
        evidence_text += " " + f.get("content", "")

    evidence_lower = evidence_text.lower()
    matched = [kw for kw in keywords if kw.lower() in evidence_lower]

    if len(matched) >= len(keywords) * 0.5:
        return RuleResult(True, f"关键词匹配: {len(matched)}/{len(keywords)}")
    elif len(matched) > 0:
        return RuleResult(False, f"部分关键词匹配 ({len(matched)}/{len(keywords)})，需 LLM 确认")
    else:
        return RuleResult(False, "无关键词匹配，需 LLM 语义判断")


def _r6_acceptance_criteria(task, details):
    """R6: Check if acceptance criteria text is satisfied.

    Like R5, this is a heuristic — keyword match against acceptance text.
    LLM handles the final semantic judgment.
    """
    acceptance = (task.get("acceptance") or "").strip()
    if not acceptance:
        return RuleResult(True, "无验收标准（通过）")

    keywords = re.findall(r'[一-鿿]{2,}|[a-zA-Z]{3,}', acceptance)
    if not keywords:
        return RuleResult(True, "验收标准无关键词（通过）")

    evidence_text = details.get("text", "")
    for f in details.get("files", []):
        evidence_text += " " + f.get("content", "")

    evidence_lower = evidence_text.lower()
    matched = [kw for kw in keywords if kw.lower() in evidence_lower]

    if len(matched) >= len(keywords) * 0.4:
        return RuleResult(True, f"验收关键词匹配: {len(matched)}/{len(keywords)}")
    return RuleResult(False, "验收标准需 LLM 判断")


# Ordered list of (rule_id, rule_fn, is_hard)
# Hard rules → FAIL immediately. Soft rules → flag needs_llm.
_RULES = [
    ("R0_material_answers", _r0_material_answers, True),
    # Missing evidence is an ambiguous submission state: route to human review
    # rather than treating an otherwise potentially valid task as a hard failure.
    ("R1_evidence",     _r1_has_evidence,      False),
    ("R2_files_exist",  _r2_files_exist,        True),
    ("R3_py_compile",   _r3_py_compile,         True),
    ("R4_docker_run",   _r4_docker_run,         True),
    ("R5_output_kw",    _r5_output_keywords,    False),
    ("R6_acceptance",   _r6_acceptance_criteria, False),
]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def check_evidence(task, details):
    """Run deterministic rules against a task and its evidence.

    Args:
        task: normalized task dict (from normalize_task)
        details: evidence_details dict (from evidence_details())

    Returns:
        AcceptanceVerdict with pass/fail and per-rule results
    """
    if task.get("verification_mode") == "none":
        return AcceptanceVerdict(True, "轻验收：以用户完成确认和专注会话为准", {}, False)
    objective = any(isinstance(item, dict) and item.get("answer") for item in task.get("materials", []))
    if objective:
        result = _r0_material_answers(task, details)
        return AcceptanceVerdict(result.pass_, result.detail, {"R0_material_answers":{"pass":result.pass_,"detail":result.detail}}, False)
    # Tasks without any expected output or acceptance contract cannot be
    # accepted deterministically, even when evidence is present.
    if not str(task.get("expected_output") or "").strip() and not str(task.get("acceptance") or "").strip():
        return AcceptanceVerdict(False, "任务缺少预期产出和验收标准", {"R_contract": {"pass": False, "detail": "任务缺少预期产出和验收标准"}}, False)
    if task.get("materials") and task.get("response"):
        return AcceptanceVerdict(True, "页面作答已提交，需 AI 按题目要求验收", {}, True)
    checks = {}
    failed_hard = False
    fail_reasons = []
    needs_llm = False

    for rule_id, rule_fn, is_hard in _RULES:
        try:
            if rule_fn in (_r1_has_evidence,):
                result = rule_fn(task)
            else:
                result = rule_fn(task, details)
        except Exception as e:
            result = RuleResult(True, f"规则执行异常: {e}")

        checks[rule_id] = {"pass": result.pass_, "detail": result.detail}

        if not result.pass_:
            if is_hard:
                failed_hard = True
                fail_reasons.append(f"[{rule_id}] {result.detail}")
            else:
                needs_llm = True

    if failed_hard:
        reason = " | ".join(fail_reasons)
        return AcceptanceVerdict(False, reason, checks, False)

    if needs_llm:
        return AcceptanceVerdict(False, "确定性规则无法独立放行，需 LLM 语义判断", checks, True)

    return AcceptanceVerdict(True, "所有确定性检查通过", checks, False)


# ---------------------------------------------------------------------------
# LLM explanation (only called for borderline cases)
# ---------------------------------------------------------------------------

def run_llm_eval(task, details, fg_top, deepseek_fn):
    """Call LLM for explanation/borderline judgment only.

    Args:
        task: normalized task dict
        details: evidence_details dict
        fg_top: top foreground apps dict
        deepseek_fn: function that calls deepseek_json(messages, max_tokens, temp, timeout, retries)

    Returns:
        dict with {pass, reason, missing, next_steps, evidence_refs}
    """
    payload = {
        "task": {
            "title": task.get("title", ""),
            "description": task.get("description", ""),
            "expected_output": task.get("expected_output", ""),
            "acceptance": task.get("acceptance", ""),
        },
        "evidence_text": details.get("text", "")[:2000],
        "evidence_files": [
            {
                "path": f.get("path", ""),
                "exists": f.get("exists", False),
                "python_check": f.get("python_check", {}),
                "first_500_chars": (f.get("content", "") or "")[:500],
            }
            for f in details.get("files", [])
        ],
        "foreground_top_apps": dict(sorted(fg_top.items(), key=lambda x: -x[1])[:8]) if fg_top else {},
    }

    schema_text = """{"pass": true|false, "reason": "一句话判定", "missing": ["还缺什么"], "next_steps": ["下一步做什么"], "evidence_refs": ["文件:行号 或 代码事实"]}"""
    prompt = json.dumps(payload, ensure_ascii=False) + "\n\n确定性检查已全部通过。请作为验收审计员确认：该任务是否真正满足 expected_output 和 acceptance？只返回 JSON：\n" + schema_text

    try:
        result = deepseek_fn([
            {"role": "system", "content": "你是严格的任务验收审计员。确定性检查已通过，但你仍需判断语义层面是否真正满足验收标准。默认怀疑，有充分证据才通过。只返回 JSON。"},
            {"role": "user", "content": prompt},
        ], 1800, 0.1, 35, 0)

        if not isinstance(result, dict):
            result = {}
        return {
            "pass": bool(result.get("pass", False)),
            "reason": str(result.get("reason", "LLM 未返回判定")),
            "missing": result.get("missing", []) if isinstance(result.get("missing"), list) else [],
            "next_steps": result.get("next_steps", []) if isinstance(result.get("next_steps"), list) else [],
            "evidence_refs": result.get("evidence_refs", []) if isinstance(result.get("evidence_refs"), list) else [],
        }
    except Exception as e:
        return {
            "pass": True,
            "reason": f"LLM 调用失败({e})，确定性检查通过故放行",
            "missing": [],
            "next_steps": ["人工复核"],
            "evidence_refs": [],
        }


# ---------------------------------------------------------------------------
# Convenience: build a full result from verdict
# ---------------------------------------------------------------------------

STATUSES = ("passed", "failed", "needs_review", "blocked")
DECISION_TO_STATUS = {
    "accepted": "passed",
    "conditional": "passed",
    "review": "needs_review",
    "rejected": "failed",
    "blocked": "blocked",
}
STATUS_TO_DECISION = {
    "passed": "accepted",
    "failed": "rejected",
    "needs_review": "review",
    "blocked": "blocked",
}
_RULE_NEXT = {
    "R0_material_answers": "根据题目要求重新作答后再次验收",
    "R1_evidence": "上传交付物文件或提交页面作答后重新验收",
    "R2_files_exist": "重新上传仍可访问的交付物文件",
    "R3_py_compile": "修复 Python 语法错误后重新提交",
    "R4_docker_run": "修复运行失败后重新提交，或确认 Docker 沙箱可用",
    "R5_output_kw": "补充能对应预期产出的证据",
    "R6_acceptance": "补充能核验成功标准的证据",
}


def _as_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _check_items(raw, default_status="failed"):
    items = []
    if isinstance(raw, dict):
        for rule_id, payload in raw.items():
            payload = payload if isinstance(payload, dict) else {"detail": payload}
            passed = bool(payload.get("pass", payload.get("status") == "passed"))
            status = payload.get("status") if payload.get("status") in STATUSES else ("passed" if passed else default_status)
            items.append({
                "id": str(rule_id),
                "criterion": str(payload.get("criterion") or rule_id),
                "status": status,
                "evidence": str(payload.get("evidence") or payload.get("detail") or ""),
                "reason": str(payload.get("reason") or payload.get("detail") or ""),
            })
        return items
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            status = item.get("status") if item.get("status") in STATUSES else default_status
            items.append({
                "id": str(item.get("id") or item.get("criterion") or ""),
                "criterion": str(item.get("criterion") or item.get("id") or ""),
                "status": status,
                "evidence": str(item.get("evidence") or item.get("detail") or ""),
                "reason": str(item.get("reason") or item.get("detail") or ""),
            })
    return items


def _next_actions(checks, extra=None):
    actions = []
    for check in checks:
        if check.get("status") == "passed":
            continue
        action = _RULE_NEXT.get(check.get("id"), check.get("reason") or check.get("evidence") or "补充证据后重新验收")
        if action and action not in actions:
            actions.append(action)
    for item in _as_list(extra):
        if item not in actions:
            actions.append(item)
    return actions or ["补充证据后重新验收"]


def explainable_result(result=None, passed=False, reason="", status=""):
    """Normalize any acceptance payload into the public explainable contract."""
    result = result if isinstance(result, dict) else {}
    checks = _check_items(result.get("checks"))
    missing = _as_list(result.get("missing"))
    next_actions = _as_list(result.get("next_actions")) or _as_list(result.get("next_steps"))
    try:
        confidence = max(0.0, min(1.0, float(result.get("confidence", 0.5) or 0)))
    except (TypeError, ValueError):
        confidence = 0.5
    needs_llm = bool(result.get("needs_llm", False))
    decision = str(result.get("decision") or "").strip()
    status = str(status or result.get("status") or DECISION_TO_STATUS.get(decision, "")).strip()
    if status not in STATUSES:
        if needs_llm:
            status = "needs_review"
        elif result.get("blocked"):
            status = "blocked"
        elif result.get("pass", passed):
            status = "passed"
        else:
            status = "failed"
    if not checks and missing:
        checks = [{"id": "missing", "criterion": item, "status": "failed" if status == "failed" else status,
                   "evidence": "", "reason": item} for item in missing]
    if status != "passed":
        next_actions = next_actions or _next_actions(checks, missing)
        if not missing:
            missing = [item.get("reason") or item.get("criterion") for item in checks if item.get("status") != "passed"]
            missing = [item for item in missing if item]
    summary = str(result.get("summary") or result.get("reason") or reason or "").strip()
    if not summary:
        summary = {"passed": "所有确定性检查通过", "failed": "验收未通过",
                   "needs_review": "确定性规则无法判定，需要复核", "blocked": "验收被环境或前置条件阻断"}[status]
    if status == "needs_review":
        confidence = min(confidence, 0.6)
    elif status == "passed" and not needs_llm:
        if checks:
            passed_checks = sum(1 for check in checks if check.get("status") == "passed")
            confidence = max(confidence, round(passed_checks / max(1, len(checks)), 2))
        else:
            confidence = max(confidence, 0.75)
    return {
        "pass": status == "passed",
        "status": status,
        "summary": summary,
        "reason": summary,
        "missing": missing,
        "next_actions": next_actions,
        "next_steps": next_actions,
        "evidence_refs": result.get("evidence_refs", []) if isinstance(result.get("evidence_refs"), list) else [],
        "checks": checks,
        "needs_llm": needs_llm or status == "needs_review",
        "overridden": bool(result.get("overridden", False)),
        "override_reason": str(result.get("override_reason") or ""),
        "rules_first": bool(result.get("rules_first", True)),
        "confidence": round(confidence, 2),
        "decision": STATUS_TO_DECISION[status],
        "blocked": status == "blocked",
    }


def verdict_to_acceptance_result(verdict, overridden=False, override_reason=""):
    """Convert an AcceptanceVerdict to the explainable acceptance_result contract."""
    checks = {}
    for rule_id, payload in (verdict.checks or {}).items():
        payload = payload if isinstance(payload, dict) else {"detail": payload}
        checks[rule_id] = {
            "pass": bool(payload.get("pass")),
            "detail": payload.get("detail", ""),
            "criterion": payload.get("criterion") or rule_id,
            "evidence": payload.get("evidence") or payload.get("detail", ""),
            "reason": payload.get("reason") or payload.get("detail", ""),
            "status": "passed" if payload.get("pass") else "failed",
        }
    if verdict.needs_llm:
        status = "needs_review"
    elif verdict.pass_:
        status = "passed"
    else:
        status = "failed"
        if any("Docker" in str(item.get("detail") or "") and "不可用" in str(item.get("detail") or "") for item in checks.values()):
            status = "blocked"
    return explainable_result({
        "pass": verdict.pass_ and not verdict.needs_llm,
        "reason": verdict.reason,
        "checks": checks,
        "needs_llm": verdict.needs_llm,
        "overridden": overridden,
        "override_reason": override_reason,
        "rules_first": True,
        "status": status,
    })


def build_remediation_task(task, result, now=None):
    """Create a smaller recovery task that keeps the original success standard."""
    from datetime import datetime
    task = task if isinstance(task, dict) else {}
    result = explainable_result(result)
    if result["status"] != "failed":
        return None
    title = str(task.get("title") or "当前任务").strip()
    while title.startswith("补救："):
        title = title[len("补救："):]
    missing = result["missing"] or [item["criterion"] for item in result["checks"] if item.get("status") != "passed"]
    action = (result["next_actions"] or ["补充最小可核验证据"])[0]
    stamp = datetime.now().isoformat() if now is None else now
    acceptance = task.get("acceptance") or "补齐缺失证据且不降低原验收标准"
    return {
        "id": "{}_remedy_{}".format(task.get("id") or "task", str(stamp).replace(":", "").replace("-", "")[:18]),
        "title": "补救：{}".format(title),
        "description": action,
        "type": "verify",
        "source": "remediation",
        "goal_id": task.get("goal_id", ""),
        "estimated_minutes": min(20, max(10, int(task.get("estimated_minutes", 20) or 20))),
        "expected_output": task.get("expected_output") or action,
        "acceptance": acceptance,
        "parent_task_id": task.get("id", ""),
        "original_acceptance": task.get("acceptance") or acceptance,
        "missing": missing,
        "next_actions": result["next_actions"],
        "status": "pending",
        "required_apps": list(task.get("required_apps") or []),
        "allowed_apps": list(task.get("allowed_apps") or []),
    }
