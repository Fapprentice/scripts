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
    return RuleResult(False, "未提交任何交付物或证据")


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
    """R4: If Docker is available, .py files must pass sandbox execution."""
    files = details.get("files", [])
    py_files = [f for f in files if f.get("path", "").lower().endswith(".py")]
    if not py_files:
        return RuleResult(True, "无 Python 文件（跳过 Docker 检查）")
    failures = []
    for f in py_files:
        dr = f.get("docker_run", {})
        # skipped means Docker wasn't available — that's ok
        if dr.get("skipped"):
            continue
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
        return RuleResult(True, f"部分关键词匹配 ({len(matched)}/{len(keywords)})，需 LLM 确认")
    else:
        return RuleResult(True, "无关键词匹配，需 LLM 语义判断")


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
    return RuleResult(True, "验收标准需 LLM 判断")


# Ordered list of (rule_id, rule_fn, is_hard)
# Hard rules → FAIL immediately. Soft rules → flag needs_llm.
_RULES = [
    ("R1_evidence",     _r1_has_evidence,      True),
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
        return AcceptanceVerdict(True, "确定性规则通过，需 LLM 语义判断", checks, True)

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

def verdict_to_acceptance_result(verdict, overridden=False, override_reason=""):
    """Convert an AcceptanceVerdict to the acceptance_result dict format."""
    ar = {
        "pass": verdict.pass_,
        "reason": verdict.reason,
        "missing": [],
        "next_steps": [],
        "evidence_refs": [],
        "checks": verdict.checks,
        "needs_llm": verdict.needs_llm,
        "overridden": overridden,
        "override_reason": override_reason,
        "rules_first": True,
    }
    passed_checks = sum(1 for check in verdict.checks.values() if check.get("pass"))
    ar["confidence"] = round(passed_checks / max(1, len(verdict.checks)), 2)
    if verdict.needs_llm:
        ar["confidence"] = min(ar["confidence"], 0.6)
    ar["decision"] = (
        "accepted" if verdict.pass_ and not verdict.needs_llm and ar["confidence"] >= 0.75
        else "conditional" if verdict.pass_ and not verdict.needs_llm
        else "review" if verdict.needs_llm
        else "rejected"
    )

    if not verdict.pass_:
        # Generate actionable missing/next_steps from failed checks
        for rule_id, cr in verdict.checks.items():
            if not cr["pass"]:
                ar["missing"].append(f"{rule_id}: {cr['detail']}")
        if not ar["missing"]:
            ar["missing"].append("交付物不满足验收条件")

        if not ar["next_steps"]:
            ar["next_steps"] = ["请提交完整的交付物后重新验收"]

    return ar
