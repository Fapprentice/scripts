"""FSRS scheduling and the per-goal skill map."""

import acceptance
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from fsrs import Card, Rating, Scheduler, State
from utils import task_actual_minutes

PACKS_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "packs"
_PACK_CACHE = None


def load_packs():
    global _PACK_CACHE
    if _PACK_CACHE is None:
        packs = []
        if PACKS_DIR.exists():
            for path in sorted(PACKS_DIR.glob("*/v*.json")):
                packs.append(json.loads(path.read_text(encoding="utf-8")))
        _PACK_CACHE = packs
    return _PACK_CACHE


def _version_key(version):
    match = re.fullmatch(r"v(\d+)", str(version or "").strip())
    return int(match.group(1)) if match else -1


def resolve_pack(state=None, pack_id="", pack_version=""):
    """Resolve a goal's immutable bound pack, or the latest pack for a new goal."""
    model = (state or {}).get("user_model") if isinstance(state, dict) else {}
    model = model if isinstance(model, dict) else {}
    wanted_id = str(pack_id or model.get("pack_id") or "").strip()
    wanted_version = str(pack_version or model.get("pack_version") or "").strip()
    candidates = [pack for pack in load_packs() if not wanted_id or str(pack.get("id") or "") == wanted_id]
    if wanted_version:
        return next((pack for pack in candidates if str(pack.get("version") or "") == wanted_version), None)
    return max(candidates, key=lambda pack: _version_key(pack.get("version")), default=None)


def get_stage_template(pack, stage_id):
    if not isinstance(pack, dict):
        return None
    wanted = str(stage_id or "").strip()
    return next((stage for stage in pack.get("stages") or [] if isinstance(stage, dict) and str(stage.get("id") or "").strip() == wanted), None)


def validate_stage_template(pack, template):
    errors = []
    if not isinstance(pack, dict) or not isinstance(template, dict):
        return ["pack and template must be objects"]
    node_ids = {str(node.get("id") or "") for node in pack.get("nodes") or [] if isinstance(node, dict)}
    required = [str(item).strip() for item in template.get("required_skill_ids") or [] if str(item).strip()]
    optional = [str(item).strip() for item in template.get("optional_skill_ids") or [] if str(item).strip()]
    forbidden = [str(item).strip() for item in template.get("forbidden_skill_ids") or [] if str(item).strip()]
    if not str(template.get("id") or "").strip(): errors.append("stage id is required")
    if not isinstance(template.get("template_revision"), int) or template.get("template_revision", 0) < 1: errors.append("template revision is required")
    if not 2 <= len(required) <= 4 or len(required) != len(set(required)): errors.append("required skills must contain 2-4 unique ids")
    if any(skill_id not in node_ids for skill_id in required + optional + forbidden): errors.append("stage references unknown skills")
    if set(required) & (set(optional) | set(forbidden)): errors.append("stage skill sets must not overlap")
    checks = template.get("skill_checks") if isinstance(template.get("skill_checks"), dict) else {}
    if set(checks) != set(required) or any(not str(checks.get(skill_id) or "").strip() for skill_id in required): errors.append("skill checks must exactly cover required skills")
    evidence = template.get("evidence_contract") if isinstance(template.get("evidence_contract"), dict) else {}
    for field in ("integration_behavior", "outcome_shape"):
        if not str(template.get(field) or "").strip(): errors.append(field + " is required")
    if any(not str(evidence.get(field) or "").strip() for field in ("behavior", "threshold", "counterexample")): errors.append("complete evidence contract is required")
    if not isinstance(template.get("max_supporting_skills"), int) or template.get("max_supporting_skills", -1) < 0: errors.append("max supporting skills is invalid")
    if not isinstance(template.get("required_attributes"), list) or not isinstance(template.get("optional_attributes"), list): errors.append("attribute declarations are required")
    return errors


def validate_stage_proposal(pack, template, proposal):
    errors = list(validate_stage_template(pack, template))
    if not isinstance(proposal, dict): return errors + ["proposal must be an object"]
    exact = {"stage_id": template.get("id"), "template_revision": template.get("template_revision"), "pack_id": pack.get("id"), "pack_version": pack.get("version"), "required_skill_ids": template.get("required_skill_ids"), "integration_behavior": template.get("integration_behavior"), "outcome_shape": template.get("outcome_shape"), "skill_checks": template.get("skill_checks")}
    for field, expected in exact.items():
        if proposal.get(field) != expected: errors.append(field + " does not match template")
    supporting = [str(item).strip() for item in proposal.get("supporting_skill_ids") or [] if str(item).strip()]
    allowed = set(template.get("optional_skill_ids") or [])
    required = set(template.get("required_skill_ids") or [])
    forbidden = set(template.get("forbidden_skill_ids") or [])
    if len(supporting) != len(set(supporting)) or any(item in required or item in forbidden for item in supporting):
        errors.append("supporting skills overlap required or forbidden skills")
    if len(supporting) > template.get("max_supporting_skills", 0) or any(item not in allowed for item in supporting): errors.append("supporting skills exceed template bounds")
    if any(item in forbidden for item in proposal.get("required_skill_ids") or []):
        errors.append("proposal requires forbidden skills")
    materials = proposal.get("materials")
    if not isinstance(materials, list) or not materials or any(not isinstance(item, dict) or not item for item in materials):
        errors.append("materials must be a non-empty list of objects")
    for field in template.get("required_attributes") or []:
        value = proposal.get(field)
        if value is None or value == "" or value == [] or value == {}: errors.append(field + " is required")
    return errors


def evaluate_stage_outcome(task, outcome):
    """Evaluate a stage submission without mutating authoritative learning state."""
    task = task if isinstance(task, dict) else {}
    outcome = outcome if isinstance(outcome, dict) else {}
    status = str(outcome.get("status") or "").strip()
    allowed = {"passed", "failed", "partial", "blocked", "needs_review"}
    if status not in allowed:
        return {"status": "needs_review", "reason": "invalid stage status", "skill_observations": []}
    observations = outcome.get("skill_observations")
    observations = observations if isinstance(observations, list) else []
    evidence_refs = outcome.get("evidence_refs")
    evidence_refs = [item for item in evidence_refs if isinstance(item, str) and item.strip()] if isinstance(evidence_refs, list) else []
    evidence_facts = outcome.get("evidence_facts")
    evidence_facts = evidence_facts if isinstance(evidence_facts, list) else []
    pack = resolve_pack(pack_id=task.get("pack_id"), pack_version=task.get("pack_version"))
    template = get_stage_template(pack, task.get("stage_id")) if pack else None
    trusted_contract = bool(template and str(template.get("template_revision")) == str(task.get("template_revision")))
    required = [str(item).strip() for item in ((template or {}).get("required_skill_ids") if trusted_contract else task.get("required_skill_ids") or []) if str(item).strip()]
    by_skill = {str(item.get("skill_id") or "").strip(): item for item in observations if isinstance(item, dict)}
    # Legacy stage submissions may carry only a unified evidence reference;
    # when observations are supplied, every required skill must pass before the
    # result can remain passed. This keeps the stage seam backward compatible
    # without allowing partial observations to masquerade as a pass.
    missing_observations = not required or any(str(by_skill.get(skill_id, {}).get("status") or "") != "passed" for skill_id in required)
    missing_observation_evidence = any(
        not str(by_skill.get(skill_id, {}).get("evidence") or by_skill.get(skill_id, {}).get("detail") or "").strip()
        for skill_id in required
    )
    reason = str(outcome.get("reason") or "")
    if status == "passed" and (task.get("observations_required") or required) and (missing_observations or missing_observation_evidence or not evidence_refs):
        status = "partial"
    elif status == "passed" and observations and (missing_observations or missing_observation_evidence or not evidence_refs):
        status = "partial"
    elif status == "passed":
        if not trusted_contract:
            status, evidence_reason = "needs_review", "阶段合同版本无法确认"
        else:
            contract_task = dict(task, required_skill_ids=required, skill_checks=dict(template.get("skill_checks") or {}))
            status, evidence_reason = _stage_evidence_verdict(contract_task, evidence_facts)
        reason = reason or evidence_reason
    attribution = []
    for skill_id in required:
        item = by_skill.get(skill_id)
        if item and str(item.get("status") or "") in ("failed", "blocked"):
            attribution.append({"skill_id": skill_id, "status": str(item.get("status")), "reason": str(item.get("reason") or "该节点观察点未通过")})
    return {"status": status, "reason": reason,
            "skill_observations": observations, "attribution": attribution,
            "evidence_refs": evidence_refs}


def _stage_due_days(skill, now):
    due_at = skill.get("review_due_at")
    if not due_at:
        return 0
    try:
        return max(0, int((_utc(now) - datetime.fromisoformat(due_at).astimezone(timezone.utc)).total_seconds() // 86400))
    except (TypeError, ValueError):
        return 0


def _stage_learning_days(state, stage_id, now):
    model = state.setdefault("user_model", {})
    first_seen = model.setdefault("stage_first_eligible_at", {})
    key = str(stage_id or "")
    current = _utc(now)
    if key not in first_seen:
        first_seen[key] = current.isoformat()
        return 0
    try:
        return max(0, int((current - datetime.fromisoformat(first_seen[key]).astimezone(timezone.utc)).total_seconds() // 86400))
    except (TypeError, ValueError):
        return 0


def stage_proposals(state, contract=None):
    """Build proposals only from versioned Skill Pack stage templates."""
    state = state if isinstance(state, dict) else {}
    model = state.setdefault("user_model", {})
    pack = resolve_pack(state, model.get("pack_id", ""), model.get("pack_version", ""))
    proposals = []
    for template in (pack or {}).get("stages") or []:
        required = list(template.get("required_skill_ids") or [])
        proposals.append({
            "stage_id": template.get("id"),
            "template_revision": template.get("template_revision"),
            "pack_id": (pack or {}).get("id"),
            "pack_version": (pack or {}).get("version"),
            "title": template.get("title") or template.get("id"),
            "description": template.get("integration_behavior", ""),
            "required_skill_ids": required,
            "supporting_skill_ids": [],
            "materials": [{"id": "stage-input", "values": [1, 2, 3]}],
            "estimated_minutes": min(30, max(5, int(template.get("estimated_minutes") or 25))),
            "expected_output": template.get("outcome_shape", ""),
            "acceptance": (template.get("evidence_contract") or {}).get("threshold", ""),
            "integration_behavior": template.get("integration_behavior", ""),
            "outcome_shape": template.get("outcome_shape", ""),
            "skill_checks": dict(template.get("skill_checks") or {}),
        })
    return proposals


def stage_candidate_pool(state, proposals, now=None, budget_minutes=30):
    """Return valid, qualified stage tasks ordered by explainable priority."""
    state = state if isinstance(state, dict) else {}
    model = state.setdefault("user_model", {})
    pack = resolve_pack(state, model.get("pack_id", ""), model.get("pack_version", ""))
    if not pack:
        return []
    now_dt = _utc(now)
    try:
        budget = float(budget_minutes)
    except (TypeError, ValueError):
        budget = 0
    candidates = []
    for proposal in proposals or []:
        template = get_stage_template(pack, (proposal or {}).get("stage_id"))
        if not template or validate_stage_proposal(pack, template, proposal):
            continue
        minutes = float(proposal.get("estimated_minutes") or 0)
        if minutes <= 0 or minutes > budget:
            continue
        skills = _skills(state)
        blocked = False
        score = 45
        for skill_id in template.get("required_skill_ids") or []:
            skill = skills.get(skill_id) or {}
            if not skill.get("contract_met") or not _ready(skills, skill):
                blocked = True
                break
            if _stage_due_days(skill, now_dt) >= 3:
                blocked = True
                break
        if blocked:
            continue
        learning_days = _stage_learning_days(state, template["id"], now_dt)
        score += min(30, learning_days * 10)
        task = instantiate_stage_task(pack, template["id"], proposal)
        task["eligible_learning_days"] = learning_days
        task["stage_score"] = score
        task["stage_score_reason"] = "新合格 required stage 45 + 等待学习日修正 {}".format(min(30, learning_days * 10))
        candidates.append(task)
    return sorted(candidates, key=lambda item: (-item["stage_score"], str(item.get("stage_id") or "")))


def instantiate_stage_task(pack, stage_id, proposal):
    template = get_stage_template(pack, stage_id)
    if not template: raise ValueError("unknown stage template")
    errors = validate_stage_proposal(pack, template, proposal)
    if errors: raise ValueError("invalid stage proposal: " + "; ".join(errors))
    task = dict(proposal)
    task.update({"task_kind": "stage", "skill_id": "", "primary_skill_id": "", "evidence_target": "integration", "type": "challenge", "verification_mode": "strict", "source": "pack", "locked": False})
    task["evidence_contract"] = dict(template["evidence_contract"])
    task["observations_required"] = True
    return task

def stage_task_fingerprint(task):
    task = task if isinstance(task, dict) else {}
    payload = {key: task.get(key) for key in (
        "id", "stage_id", "template_revision", "pack_id", "pack_version",
        "required_skill_ids", "supporting_skill_ids", "integration_behavior",
        "outcome_shape", "skill_checks", "evidence_contract", "materials",
        "evidence", "response")}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def stage_eligibility(state, task):
    """Check the immutable stage contract and its hard skill prerequisites."""
    task = task if isinstance(task, dict) else {}
    pack = resolve_pack(state, task.get("pack_id"), task.get("pack_version"))
    template = get_stage_template(pack, task.get("stage_id"))
    errors = validate_stage_proposal(pack, template, task) if pack and template else ["stage pack or template is unavailable"]
    skills = _skills(state)
    required = [str(item).strip() for item in task.get("required_skill_ids") or [] if str(item).strip()]
    missing = [skill_id for skill_id in required
               if not (skills.get(skill_id) or {}).get("contract_met") or not _ready(skills, skills.get(skill_id) or {})]
    return {"eligible": not errors and not missing, "required_skill_ids": required,
            "missing_skill_ids": missing, "errors": errors}


def _stage_evidence_verdict(task, facts):
    files = [item for item in facts if isinstance(item, dict) and item.get("exists")]
    py_files = [item for item in files if str(item.get("path") or "").lower().endswith(".py")]
    if not py_files:
        return "needs_review", "缺少可核验的 Python 程序附件"
    # Reuse the existing hard acceptance gate. A compiled AST is not execution
    # evidence; only a server-produced sandbox result can enter the pass path.
    check = acceptance._r4_docker_run(task, {"files": [
        {"path": item.get("path", ""), "docker_run": item.get("safe_execution")}
        for item in py_files
    ]})
    if not check.pass_:
        return "blocked", check.detail
    executions = [item.get("safe_execution") for item in py_files
                  if isinstance(item.get("safe_execution"), dict)]
    if not executions or not all(
        execution.get("all_materials") is True and
        execution.get("branch_loop_same_output") is True
        for execution in executions
    ):
        return "needs_review", "沙箱运行成功，但缺少与阶段合同对应的完整性证明"
    return "passed", "受支持的沙箱运行与阶段合同检查通过"


def record_stage_outcome(state, task, outcome, now=None):
    """Persist integration evidence without changing node mastery."""
    state = state if isinstance(state, dict) else {}
    task = task if isinstance(task, dict) else {}
    manual = outcome.get("manual_review") if isinstance(outcome, dict) else None
    if isinstance(manual, dict) and str(manual.get("reason") or "").strip():
        eligibility = stage_eligibility(state, task)
        result = ({"status": "passed", "reason": "人工复核通过（未执行宿主机或沙箱代码）",
                   "skill_observations": [], "attribution": [], "evidence_refs": []}
                  if eligibility.get("eligible") else
                  {"status": "blocked", "reason": "阶段资格未满足，人工复核不能绕过",
                   "skill_observations": [], "attribution": [], "evidence_refs": []})
    else:
        result = evaluate_stage_outcome(task, outcome)
    evidence = state.setdefault("user_model", {}).setdefault("integration_evidence", [])
    task_id = str(task.get("id") or task.get("stage_id") or "stage")
    existing = next((item for item in evidence if item.get("task_id") == task_id), None)
    attempt = dict(result, task_fingerprint=stage_task_fingerprint(task), ts=_utc(now).isoformat())
    if existing:
        previous = {
            key: existing.get(key) for key in ("status", "reason", "skill_observations", "attribution", "evidence_refs")
        }
        if existing.get("status") == "passed" and previous == {key: attempt.get(key) for key in previous}:
            return existing
        existing.setdefault("attempts", []).append(attempt)
        if existing.get("status") != "passed":
            existing.update(attempt)
        result = existing
    else:
        record = dict(result, task_id=task_id, stage_id=task.get("stage_id", ""), task_fingerprint=attempt["task_fingerprint"],
                      ts=attempt["ts"], attempts=[attempt])
        evidence.append(record)
        result = record
    events = state.setdefault("events", [])
    if result["status"] == "passed":
        if not any(event.get("kind") == "stage_completed" and event.get("task_id") == task_id for event in events if isinstance(event, dict)):
            events.append({"kind": "stage_completed", "task_id": task_id, "stage_id": task.get("stage_id", ""), "ts": _utc(now).isoformat()})
    return result


def migrate_legacy_tasks(state):
    """Deterministically remove unfinished map repairs from the user queue."""
    if not isinstance(state, dict):
        return {"migrated": [], "kept": []}
    tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
    flags = state.get("done_flags") if isinstance(state.get("done_flags"), list) else []
    events = state.setdefault("events", [])
    existing = {str(item.get("task_id")) for item in events if isinstance(item, dict) and item.get("kind") == "task_migrated_out"}
    kept, kept_flags, migrated = [], [], []
    for index, task in enumerate(tasks):
        task = task if isinstance(task, dict) else {}
        task_id = str(task.get("id") or "legacy-task-{}".format(index))
        done = bool(task.get("status") == "done" or task.get("done") or (index < len(flags) and flags[index]))
        if str(task.get("source") or "").strip() == "map_patch" and not done:
            migrated.append(task_id)
            if task_id not in existing:
                events.append({"kind": "task_migrated_out", "task_id": task_id,
                               "reason": "地图修复转为内部规划动作"})
            repairs = state.setdefault("internal_map_repairs", [])
            if not any(isinstance(item, dict) and str(item.get("task_id")) == task_id for item in repairs):
                repairs.append({"task_id": task_id, "task": dict(task)})
            continue
        kept.append(task); kept_flags.append(done)
    state["tasks"], state["done_flags"] = kept, kept_flags
    state["events"] = events[-300:]
    return {"migrated": migrated, "kept": [str(item.get("id") or "") for item in kept]}


def criterion_records(criteria):
    """Create deterministic criterion ids for an outcome contract."""
    import hashlib
    rows = []
    for value in criteria or []:
        text = str(value or "").strip()
        if text:
            rows.append({"id": "criterion-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:10], "text": text})
    return rows


def outcome_eligibility(state, contract, required_stage_ids=()):
    """Return outcome gates without mutating the SkillMap."""
    contract = contract if isinstance(contract, dict) else {}
    criteria = criterion_records(contract.get("success_criteria") or [])
    skills = _skills(state)
    model = (state.get("user_model") or {}) if isinstance(state, dict) else {}
    pack = match_pack(contract, state) if isinstance(state, dict) else None
    if pack and model.get("pack_id") and model.get("pack_version"):
        overrides = model.get("coverage_overrides", {})
        gaps = [gap for gap in coverage_gaps(pack, contract)
                if not _coverage_override_valid(gap, overrides, skills)]
        if gaps:
            return {"eligible": False, "criteria": criteria, "required_skill_ids": [],
                    "missing_skill_ids": [], "missing_stage_ids": list(required_stage_ids),
                    "coverage_gaps": gaps, "reason": "能力地图未覆盖当前成功标准"}
    missing_skills = []
    required_skill_ids = [str(item).strip() for item in (contract.get("required_skill_ids") or (state.get("_required_outcome_skills") if isinstance(state, dict) else []) or []) if str(item).strip()]
    for skill_id in required_skill_ids:
        skill = skills.get(skill_id) or {}
        if not skill.get("contract_met"):
            missing_skills.append(skill_id)
        for parent in skill.get("prerequisites", []) or []:
            if _edge_kind(skill, parent) != "soft" and not _parent_met(skills, parent):
                missing_skills.append(parent)
    if not required_skill_ids:
        pack = resolve_pack(state) if isinstance(state, dict) else None
        for sink_id in covered_skill_ids(pack, contract, (state.get("user_model", {}) or {}).get("coverage_overrides", {})):
            if sink_id not in required_skill_ids:
                required_skill_ids.append(sink_id)
        for skill_id, skill in skills.items():
            if skill.get("required_for_outcome") and skill_id not in required_skill_ids:
                required_skill_ids.append(skill_id)
        for skill_id in required_skill_ids:
            if not (skills.get(skill_id) or {}).get("contract_met"):
                missing_skills.append(skill_id)
            skill = skills.get(skill_id) or {}
            for parent in skill.get("prerequisites", []) or []:
                if _edge_kind(skill, parent) != "soft" and not _parent_met(skills, parent):
                    missing_skills.append(parent)
    missing_stages = []
    integration = (state.get("user_model") or {}).get("integration_evidence", [])
    passed_stages = set()
    current_tasks = state.get("tasks") if isinstance(state, dict) and isinstance(state.get("tasks"), list) else []
    for item in integration:
        if item.get("status") != "passed": continue
        stage_task = next((task for task in current_tasks if isinstance(task, dict) and
                           (task.get("id") == item.get("task_id") or task.get("stage_id") == item.get("stage_id"))), None)
        if stage_task and item.get("task_fingerprint") != stage_task_fingerprint(stage_task):
            continue
        passed_stages.add(item.get("stage_id"))
    missing_stages = [stage_id for stage_id in required_stage_ids if stage_id not in passed_stages]
    eligible = bool(criteria) and not missing_skills and not missing_stages
    return {"eligible": eligible, "criteria": criteria, "required_skill_ids": required_skill_ids,
            "missing_skill_ids": list(dict.fromkeys(missing_skills)), "missing_stage_ids": missing_stages}


def outcome_task(contract, state=None, required_skill_ids=(), required_stage_ids=()):
    """Build a persistent outcome task with criterion-level evidence slots."""
    contract = contract if isinstance(contract, dict) else {}
    criteria = criterion_records(contract.get("success_criteria") or [])
    required_skill_ids = [str(x).strip() for x in required_skill_ids if str(x).strip()]
    gates = outcome_eligibility({**(state or {}), "_required_outcome_skills": required_skill_ids}, contract, required_stage_ids)
    return {"task_kind": "outcome", "type": "outcome", "evidence_target": "criterion",
            "title": str(contract.get("outcome") or "最终成果验收"),
            "description": "直接提交最终成果，并为每条成功标准提供独立证据。",
            "criterion_ids": [item["id"] for item in criteria],
            "criteria": criteria, "required_skill_ids": gates.get("required_skill_ids", required_skill_ids),
            "contract_fingerprint": hashlib.sha256(json.dumps({"outcome": str(contract.get("outcome") or "").strip(), "success_criteria": [str(x).strip() for x in contract.get("success_criteria") or []]}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16],
            "required_stage_ids": list(required_stage_ids), "eligibility": gates,
            "status": "pending", "locked": not gates["eligible"],
            "evidence": [], "criterion_evidence": {}}


def outcome_failure_trace(task, failed_criterion_ids, state=None):
    """Return the smallest actionable recovery chain without mutating mastery."""
    task = task if isinstance(task, dict) else {}
    failed = [str(item).strip() for item in failed_criterion_ids or [] if str(item).strip()]
    trace = []
    for criterion_id in failed:
        row = next((item for item in task.get("criteria") or [] if isinstance(item, dict) and item.get("id") == criterion_id), {})
        trace.append({"criterion_id": criterion_id, "criterion": row.get("text", ""),
                      "next_action": "补充该成功标准对应的最小独立证据",
                      "task_kind": "diagnostic", "evidence_target": "criterion"})
    return trace


def evaluate_outcome(task, outcome, criterion_judge=None):
    task = task if isinstance(task, dict) else {}
    outcome = outcome if isinstance(outcome, dict) else {}
    criteria = [item for item in task.get("criteria") or [] if isinstance(item, dict) and item.get("id")]
    evidence = outcome.get("criterion_evidence") if isinstance(outcome.get("criterion_evidence"), dict) else {}
    def evidence_state(criterion, ref):
        if not isinstance(ref, dict) or ref.get("verified") is not True:
            return "needs_review"
        kind = ref.get("kind")
        if kind == "attachment":
            reference, content = ref.get("ref"), ref.get("content")
        elif kind == "direct_text":
            reference, content = "direct_text", ref.get("text")
        else:
            return "needs_review"
        if not isinstance(reference, str) or not reference.strip() or not isinstance(content, str) or not content.strip():
            return "failed"
        reference = reference.strip()
        if reference.casefold() in {"null", "none", "undefined"} or not content.strip():
            return "failed"
        if not criterion_judge:
            return "needs_review"
        try:
            verdict = criterion_judge(criterion, reference, str(content or ""))
        except Exception:
            return "needs_review"
        if not isinstance(verdict, dict):
            return "needs_review"
        if verdict.get("criterion_id") != criterion["id"] or not isinstance(verdict.get("pass"), bool):
            return "needs_review"
        uncertainty_value = verdict.get("uncertainty")
        if isinstance(uncertainty_value, bool) or not isinstance(uncertainty_value, (int, float)):
            return "needs_review"
        uncertainty = float(uncertainty_value)
        if not 0 <= uncertainty <= 1:
            return "needs_review"
        if uncertainty >= 0.25 or verdict.get("status") == "needs_review":
            return "needs_review"
        if verdict["pass"] is True:
            return "passed"
        return "failed"

    rows = []
    needs_review = []
    for criterion in criteria:
        value = evidence.get(criterion["id"])
        refs = value if isinstance(value, list) else ([value] if value is not None else [])
        states = [evidence_state(criterion, ref) for ref in refs]
        passed = any(state == "passed" for state in states)
        if not passed and any(state == "needs_review" for state in states): needs_review.append(criterion["id"])
        rows.append({"criterion_id": criterion["id"], "passed": passed, "evidence_refs": refs, "text": criterion.get("text", "")})
    failed = [row["criterion_id"] for row in rows if not row["passed"] and row["criterion_id"] not in needs_review]
    status = "passed" if rows and not failed and not needs_review else ("needs_review" if rows and not failed else "failed")
    return {"status": status, "criterion_results": rows, "failed_criterion_ids": failed,
            "needs_review_criterion_ids": needs_review,
            "next_actions": (["补充能对应成功标准的独立证据"] if failed else []) + (["人工复核成功标准对应的证据"] if needs_review else []),
            "failure_trace": outcome_failure_trace(task, failed + needs_review),
            "evidence_target": "criterion"}


def _pack_is_stable(pack):
    # Published packs predate explicit release metadata and are stable by
    # default. A future draft/prerelease must opt out explicitly.
    return str((pack or {}).get("release_status") or "stable").strip().casefold() == "stable"


def match_pack(contract, state=None):
    contract = contract if isinstance(contract, dict) else {}
    text = " ".join([
        str(contract.get("outcome") or ""),
        str(contract.get("baseline") or ""),
        " ".join(str(item) for item in (contract.get("success_criteria") or [])),
    ]).casefold()
    matching_ids = {str(pack.get("id") or "") for pack in load_packs()
                    if any(str(token).casefold() in text for token in pack.get("match") or [])}
    model = (state or {}).get("user_model") if isinstance(state, dict) else {}
    model = model if isinstance(model, dict) else {}
    bound_id = str(model.get("pack_id") or "").strip()
    bound_version = str(model.get("pack_version") or "").strip()
    if bound_id in matching_ids and bound_version:
        return resolve_pack(state, pack_id=bound_id)
    candidates = [pack for pack in load_packs() if str(pack.get("id") or "") in matching_ids and _pack_is_stable(pack)]
    return max(candidates, key=lambda pack: _version_key(pack.get("version")), default=None)


def is_learning_goal(goal, contract=None):
    contract = dict(contract or {})
    outcome = " ".join(part for part in (str(contract.get("outcome") or ""), str(goal or "")) if str(part).strip())
    contract["outcome"] = outcome or str(goal or "")
    return match_pack(contract) is not None

_CET4_WORDS = [
    ("abandon","放弃"),("ability","能力"),("absence","缺席"),("academic","学术的"),("access","使用权"),
    ("accompany","陪伴"),("accomplish","完成"),("accurate","准确的"),("adapt","适应"),("adequate","足够的"),
    ("advocate","提倡"),("allocate","分配"),("alternative","替代方案"),("analyze","分析"),("anticipate","预期"),
    ("apparent","明显的"),("approach","方法"),("appropriate","合适的"),("assess","评估"),("assume","假设"),
    ("available","可获得的"),("benefit","益处"),("challenge","挑战"),("circumstance","情况"),("consequence","后果"),
    ("consume","消耗"),("contribute","贡献"),("decline","下降"),("demonstrate","证明"),("essential","必不可少的")]

def _diagnostic_materials(skill_id):
    if skill_id in ("english.vocabulary", "cet4.vocab.high_freq"):
        meanings = [meaning for _, meaning in _CET4_WORDS]
        return ([{"type":"question","prompt":word,"options":[meaning, meanings[(i+7)%30], meanings[(i+13)%30], meanings[(i+19)%30]],"answer":meaning}
                 for i,(word,meaning) in enumerate(_CET4_WORDS)], {"type":"choice","multiple":False})
    if skill_id == "english.reading":
        return ([{"type":"passage","title":"Digital Study Habits","content":"Many students use digital tools to organize learning. The tools are most useful when learners set a clear purpose, remove distractions and review their progress. Technology itself does not guarantee better results; deliberate practice and timely feedback remain essential."},
                 {"type":"question","prompt":"What makes digital tools most useful?","options":["Clear purpose and review","More screen time","Using many apps","Avoiding feedback"],"answer":"Clear purpose and review"},
                 {"type":"question","prompt":"What remains essential?","options":["Deliberate practice and feedback","Expensive devices","Longer breaks","Social media"],"answer":"Deliberate practice and feedback"}], {"type":"choice","multiple":False})
    if skill_id == "english.listening":
        return ([{"type":"audio_script","title":"Short dialogue","content":"Woman: Have you finished the report? Man: Not yet. I will send it before three this afternoon."},
                 {"type":"question","prompt":"When will the man send the report?","options":["Before 3 p.m.","Tomorrow morning","At noon","Next week"],"answer":"Before 3 p.m."}], {"type":"choice","multiple":False})
    if skill_id == "english.writing":
        return ([{"type":"prompt","title":"Writing prompt","content":"Write 120–180 words on how students can use technology effectively without becoming distracted. Give at least two practical suggestions."}], {"type":"text"})
    return ([], {"type":"text"})

def ensure_task_materials(task):
    if task.get("materials"): return task
    text = " ".join(str(task.get(key, "") or "") for key in ("title", "description", "skill_id")).casefold()
    skill_id = task.get("skill_id", "")
    if skill_id in ("english.vocabulary", "cet4.vocab.high_freq") or any(word in text for word in ("词汇识别", "词义匹配", "vocab.recognition", "高频词汇")): skill_id = skill_id if skill_id == "cet4.vocab.high_freq" else "english.vocabulary"
    elif "阅读" in text and "诊断" in text: skill_id = "english.reading"
    elif "听力" in text or "听写" in text: skill_id = "english.listening"
    elif "写作" in text and "诊断" in text: skill_id = "english.writing"
    materials, interaction = _diagnostic_materials(skill_id)
    if materials:
        task["materials"], task["interaction"] = materials, task.get("interaction") or interaction
    return task


def fallback_task_templates(goal):
    """Concrete offline/top-up tasks for learning goals."""
    goal = str(goal or "").strip()
    pack = match_pack({"outcome": goal, "success_criteria": [goal]})
    if pack:
        state = {"user_model": {}}
        skill_map = SkillMap.load(state, {"outcome": goal, "success_criteria": [goal], "baseline": ""})
        tasks = []
        for node in pack.get("nodes") or []:
            if len(tasks) >= 3:
                break
            skill_id = str(node.get("id") or "")
            if not skill_map.unlock(skill_id):
                continue
            tasks.append(ensure_task_materials(_task_from_skill(skill_id, _skills(state)[skill_id], source="fallback")))
        if tasks:
            return tasks
    folded = goal.casefold()
    learning_words = ("学习", "考试", "四级", "六级", "英语", "词汇", "语法", "数学", "编程",
                      "python", "java", "cet", "ielts", "toefl")
    if not any(word in folded for word in learning_words):
        return []
    if any(word in folded for word in ("英语", "四级", "六级", "词汇", "cet", "ielts", "toefl")):
        return [_node_task_contract(task) for task in [
            {"title": "闭卷默写 10 个目标词汇", "description": "不查资料写出英文、中文释义和一个例句。",
             "type": "recall", "learning_task_type": "recall", "skill_id": "english.vocabulary",
             "estimated_minutes": 15, "expected_output": "10 个词汇、释义和例句",
             "acceptance": "至少 8 个词汇拼写和释义正确",
             "materials": [{"type":"prompt","title":"本轮目标词汇","content":"abandon, ability, absence, academic, access, accompany, accomplish, accurate, adapt, adequate"}],
             "interaction": {"type":"text"}},
            {"title": "完成一篇限时阅读并整理错因", "description": "限时完成一篇阅读，记录答案、用时和每道错题原因。",
             "type": "practice", "learning_task_type": "practice", "skill_id": "english.reading",
             "estimated_minutes": 25, "expected_output": "阅读答案、用时、正确率和错因",
             "acceptance": "完成整篇阅读并为每道错题写出具体原因",
             "materials": _diagnostic_materials("english.reading")[0], "interaction": _diagnostic_materials("english.reading")[1]},
            {"title": "听写一段英语材料并复述", "description": "听写 3 至 5 分钟材料，核对后用自己的话写出要点。",
             "type": "practice", "learning_task_type": "recall", "skill_id": "english.listening",
             "estimated_minutes": 25, "expected_output": "听写文本、修正记录和三条复述要点",
             "acceptance": "完成听写核对，并准确复述至少三条信息",
             "materials": _diagnostic_materials("english.listening")[0], "interaction": {"type":"text"}},
        ]]
    return [_node_task_contract(task) for task in [
        {"title": "闭卷写出 5 个核心知识点", "description": "不查资料写出定义、用途和一个例子。",
         "type": "recall", "learning_task_type": "recall", "skill_id": "learning.core",
         "estimated_minutes": 15, "expected_output": "5 个知识点及对应例子",
         "acceptance": "至少 4 个知识点表述正确且包含例子"},
        {"title": "完成 10 道针对性练习并整理错因", "description": "完成练习，记录答案、正确率和每道错题原因。",
         "type": "practice", "learning_task_type": "practice", "skill_id": "learning.practice",
         "estimated_minutes": 30, "expected_output": "10 道答案、正确率和错因",
         "acceptance": "完成全部练习并为每道错题写出具体原因"},
        {"title": "用自己的话讲解一个薄弱知识点", "description": "不照抄资料，写出解释并设计一个新例子。",
         "type": "explain", "learning_task_type": "explain", "skill_id": "learning.explain",
         "estimated_minutes": 20, "expected_output": "一段讲解和一个原创例子",
         "acceptance": "讲解包含原理、适用条件和可验证例子"},
    ]]


def is_generic_planning_task(goal, task):
    if not fallback_task_templates(goal):
        return False
    text = " ".join(str(task.get(key, "") or "") for key in ("title", "text", "description", "expected_output"))
    return any(marker in text for marker in ("最小可交付成果", "完成定义", "定义和边界"))


def task_consistency_issues(task):
    title = str(task.get("title") or task.get("text") or "")
    description = str(task.get("description") or "")
    expected = str(task.get("expected_output") or "")
    issues = []
    requires_materials = any(marker in " ".join((title, description, expected)) for marker in
                             ("选择题", "选出", "阅读", "听力", "短文", "材料只播放"))
    if requires_materials and not task.get("materials"):
        issues.append("missing_materials")
    if any(marker in title for marker in ("闭卷", "不看资料", "不查资料")) and any(
            marker in description for marker in ("允许先看", "可以查看答案", "可查阅答案", "允许查看")):
        issues.append("closed_book_conflict")
    title_counts = {}
    for number, unit in re.findall(r"(\d+)\s*(个|道|篇|组|套|分钟|词)", title):
        title_counts.setdefault(unit, number)
    for unit, target in title_counts.items():
        for value in (description, expected):
            counts = {}
            for number, count_unit in re.findall(r"(\d+)\s*(个|道|篇|组|套|分钟|词)", value):
                counts.setdefault(count_unit, number)
            if unit in counts and counts[unit] != target:
                issues.append("quantity_mismatch")
                break
    return issues


def task_semantic_key(task):
    text = " ".join(str(task.get(key, "") or "") for key in ("title", "text", "description", "skill_id")).casefold()
    mode = str(task.get("learning_task_type") or task.get("type") or "").casefold()
    if any(marker in text for marker in ("词汇", "单词", "高频词", "vocab")):
        return "vocabulary:" + ("recall" if mode in ("recall", "diagnostic", "practice") else mode)
    if any(marker in text for marker in ("阅读", "reading")):
        return "reading:" + mode
    if any(marker in text for marker in ("听写", "听力", "listening")):
        return "listening:" + mode
    return ""


def _default_diagnostic_dimensions(goal):
    goal = str(goal or "").casefold()
    if any(word in goal for word in ("英语", "四级", "六级", "cet", "ielts", "toefl")):
        return [
            {"skill_id": "english.vocabulary", "title": "词汇识别：词义匹配",
         "description": "从30个四级高频词中选出正确中文释义。",
         "estimated_minutes": 15, "expected_output": "30个选择题答案",
         "acceptance": "正确率不低于70%（至少21/30）",
         "materials": _diagnostic_materials("english.vocabulary")[0], "interaction": {"type":"choice","min_score":0.7}},
            {"skill_id": "english.reading", "title": "阅读诊断：限时完成1篇阅读",
         "description": "按考试时间要求完成1篇阅读，记录每题答案、总用时和正确数。",
         "estimated_minutes": 20, "expected_output": "答案、总用时、正确数和错题位置",
         "acceptance": "完成整篇阅读并记录可核验的用时与正确数",
         "materials": _diagnostic_materials("english.reading")[0], "interaction": _diagnostic_materials("english.reading")[1]},
            {"skill_id": "english.listening", "title": "听力诊断：完成1组短对话",
         "description": "材料只播放考试允许的次数，记录每题答案、正确数和未听懂的位置。",
         "estimated_minutes": 15, "expected_output": "答案、正确数和听力盲点",
         "acceptance": "完成整组听力并记录正确数及至少一个具体盲点",
         "materials": _diagnostic_materials("english.listening")[0], "interaction": _diagnostic_materials("english.listening")[1]},
            {"skill_id": "english.writing", "title": "写作诊断：限时完成1篇短文",
         "description": "不使用翻译或生成工具，按考试要求限时完成一篇短文。",
         "estimated_minutes": 30, "expected_output": "完整短文、字数和实际用时",
         "acceptance": "短文达到目标考试最低字数，并记录用时和自查问题",
         "materials": _diagnostic_materials("english.writing")[0], "interaction": _diagnostic_materials("english.writing")[1]},
        ]
    if "stm32" in goal or "单片机" in goal:
        return [
            {"skill_id": "stm32.project_setup", "title": "STM32工程诊断：创建并编译工程",
             "description": "创建一个可构建的STM32工程，完成芯片、时钟和工具链配置，并记录编译结果。",
             "estimated_minutes": 25, "expected_output": "可打开的工程、编译日志和配置说明",
             "acceptance": "工程无错误编译通过，能说明芯片型号、时钟配置和烧录方式"},
            {"skill_id": "stm32.gpio", "title": "STM32 GPIO诊断：控制LED闪烁",
             "description": "配置一个GPIO输出引脚，让板载或外接LED按固定周期闪烁，并记录引脚与电平逻辑。",
             "estimated_minutes": 30, "expected_output": "可运行固件、接线或引脚配置和演示记录",
             "acceptance": "LED按目标周期稳定闪烁，代码可编译且能解释GPIO初始化和电平逻辑"},
            {"skill_id": "stm32.timer_pwm", "title": "STM32定时器诊断：输出PWM",
             "description": "使用定时器输出指定频率和占空比的PWM信号，记录计算过程并用示波器或逻辑分析仪核验。",
             "estimated_minutes": 35, "expected_output": "定时器配置、参数计算和测量结果",
             "acceptance": "实测频率和占空比与目标相符，并能解释预分频与重载值"},
            {"skill_id": "stm32.serial", "title": "STM32串口诊断：收发并验证数据",
             "description": "配置USART与电脑通信，发送一条状态信息并接收一条命令，记录波特率和验证结果。",
             "estimated_minutes": 35, "expected_output": "串口工程、通信日志和异常排查记录",
             "acceptance": "收发数据稳定可复现，能说明波特率、引脚复用和常见通信故障"},
        ]
    label = str(goal or "当前目标").strip()
    return [
        {"skill_id": "ability.fundamentals", "title": "基础诊断：解释核心概念",
         "description": "不查资料解释当前目标的5个核心概念，并标记不确定项。",
         "estimated_minutes": 15, "expected_output": "5个概念解释和不确定项",
         "acceptance": "解释覆盖5个概念，且明确标记不会或不确定的部分"},
        {"skill_id": "ability.execution", "title": "操作诊断：完成一个基础任务",
         "description": "独立完成一个与“{}”直接相关的基础操作，并记录步骤。".format(label),
         "estimated_minutes": 25, "expected_output": "可检查的操作结果和步骤记录",
         "acceptance": "结果可复现，步骤记录足以定位卡点"},
        {"skill_id": "ability.application", "title": "应用诊断：解决一个真实问题",
         "description": "在新场景中应用“{}”的核心能力，解释选择和结果。".format(label),
         "estimated_minutes": 30, "expected_output": "问题解答、关键选择和验证结果",
         "acceptance": "解答与目标直接相关，包含推理过程和可核验结果"},
    ]


def normalize_diagnostic_dimensions(raw, goal=""):
    rows = raw.get("dimensions", []) if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        return []
    clean = []
    for index, item in enumerate(rows[:8]):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        description = str(item.get("description") or "").strip()
        expected = str(item.get("expected_output") or "").strip()
        acceptance = str(item.get("acceptance") or "").strip()
        if len(title) < 2 or len(description) < 6 or not expected or not acceptance:
            continue
        if "missing_materials" in task_consistency_issues(item):
            continue
        skill_id = re.sub(r"[^a-z0-9._-]+", ".", str(item.get("skill_id") or "").casefold()).strip(".")
        if not skill_id:
            skill_id = "ability.dimension_{}".format(index + 1)
        try:
            minutes = max(5, min(60, int(item.get("estimated_minutes", 20) or 20)))
        except (TypeError, ValueError):
            minutes = 20
        materials = item.get("materials") if isinstance(item.get("materials"), list) else []
        interaction = item.get("interaction") if isinstance(item.get("interaction"), dict) else {}
        clean.append({"skill_id": skill_id, "title": title, "description": description,
                      "estimated_minutes": minutes, "expected_output": expected, "acceptance": acceptance,
                      "materials": materials, "interaction": interaction})
    unique = []
    seen = set()
    for item in clean:
        key = item["title"].casefold()
        if item["skill_id"] not in seen and key not in seen:
            unique.append(item); seen.update((item["skill_id"], key))
    return unique if 3 <= len(unique) <= 6 else []


def set_diagnostic_dimensions(state, dimensions, signature="", source="ai"):
    clean = normalize_diagnostic_dimensions(dimensions)
    if not clean:
        clean = _default_diagnostic_dimensions("")
        source = "fallback"
    model = state.setdefault("user_model", {})
    model["ability_dimensions"] = clean
    model["ability_dimensions_signature"] = signature
    model["ability_dimensions_source"] = source
    return clean


def diagnostic_dimensions(goal, state=None):
    stored = ((state or {}).get("user_model", {}) or {}).get("ability_dimensions", [])
    return normalize_diagnostic_dimensions(stored, goal) or _default_diagnostic_dimensions(goal)


def ability_profile(state, goal):
    scores = (state.get("user_model", {}) or {}).get("ability_diagnostics", {}) or {}
    dimensions = []
    for item in diagnostic_dimensions(goal, state):
        result = scores.get(item["skill_id"], {})
        dimensions.append({"skill_id": item["skill_id"], "title": item["title"].split("：", 1)[0],
                           "score": result.get("score"), "assessed": bool(result.get("assessed")),
                           "updated_at": result.get("updated_at", "")})
    assessed = sum(1 for item in dimensions if item["assessed"])
    return {"dimensions": dimensions, "assessed": assessed, "total": len(dimensions),
            "complete": bool(dimensions) and assessed == len(dimensions)}


def plan_learning_tasks(state, goal, contract=None, limit=3, now=None):
    """Return today's learning tasks from the skill map, or a map-patch task."""
    contract = contract if isinstance(contract, dict) else {"outcome": goal, "success_criteria": [goal], "baseline": ""}
    skill_map = SkillMap.load(state, contract)
    if not skill_map.ok:
        # Do not leak the internal map-repair action into the user queue.
        return []
    limit = max(1, int(limit or 1))
    tasks = []
    seen = set()
    for _ in range(limit):
        draft = skill_map.next_task(now=now)
        skill_id = str((draft or {}).get("skill_id") or "")
        if not draft or not skill_id or skill_id in seen:
            break
        seen.add(skill_id)
        tasks.append(ensure_task_materials(draft))
        skill = _skills(state).get(skill_id) or {}
        skill["band"] = skill.get("band") or "learning"
        if skill.get("contract_met"):
            break
        skill["planning_hold"] = True
    for skill in _skills(state).values():
        skill.pop("planning_hold", None)
    if tasks:
        return tasks
    return initial_diagnostic_tasks(state, goal, limit)


def initial_diagnostic_tasks(state, goal, limit=3):
    stored = ((state or {}).get("user_model", {}) or {}).get("ability_dimensions", [])
    if not stored:
        pack = match_pack({"outcome": goal, "success_criteria": [goal]})
        if pack:
            skill_map = SkillMap.load(state, {"outcome": goal, "success_criteria": [goal], "baseline": ""})
            tasks = []
            for node in pack.get("nodes") or []:
                skill_id = str(node.get("id") or "")
                if not skill_map.unlock(skill_id):
                    continue
                skill = _skills(state).get(skill_id) or {}
                if skill.get("band") == "skipped" or skill.get("contract_met"):
                    continue
                tasks.append(ensure_task_materials(_task_from_skill(skill_id, skill, source="ability_diagnostic")))
                if len(tasks) >= max(1, int(limit or 1)):
                    break
            return tasks
    profile = ability_profile(state, goal)
    missing = {item["skill_id"] for item in profile["dimensions"] if not item["assessed"]}
    tasks = []
    for item in diagnostic_dimensions(goal, state):
        if item["skill_id"] not in missing: continue
        materials, interaction = _diagnostic_materials(item["skill_id"])
        tasks.append(_node_task_contract(dict(
            item, materials=item.get("materials") or materials,
            interaction=item.get("interaction") or interaction, type="diagnostic",
            learning_task_type="diagnostic", difficulty=2, verification_mode="strict",
            source="ability_diagnostic", locked=True)))
    return [ensure_task_materials(task) for task in tasks[:max(1, int(limit or 1))]]


def _utc(now=None):
    if isinstance(now, datetime):
        return now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(now, timezone.utc) if now is not None else datetime.now(timezone.utc)


def _skills(state):
    return state.setdefault("user_model", {}).setdefault("skills", {})


def _scheduler(state):
    model = state.setdefault("user_model", {})
    raw = model.get("fsrs_scheduler")
    if raw:
        try:
            return Scheduler.from_json(raw)
        except (TypeError, ValueError):
            pass
    scheduler = Scheduler(desired_retention=float(model.get("desired_retention", 0.9) or 0.9))
    model["fsrs_scheduler"] = scheduler.to_json()
    return scheduler


def _path_exists(skills, start, target, seen=None):
    if start == target:
        return True
    seen = (seen or set()) | {start}
    return any(parent not in seen and _path_exists(skills, parent, target, seen)
               for parent in (skills.get(start, {}) or {}).get("prerequisites", []))


def _skill_meta(skill):
    return skill.get("prerequisite_meta") if isinstance(skill.get("prerequisite_meta"), dict) else {}


def _edge_kind(skill, parent):
    meta = _skill_meta(skill).get(parent) or {}
    kind = str(meta.get("kind") or "hard").strip() or "hard"
    return kind if kind in ("hard", "soft", "legacy_unspecified") else "hard"


def _parent_met(skills, parent_id):
    parent = skills.get(parent_id) or {}
    if parent.get("band") == "skipped" or parent.get("contract_met"):
        return True
    return ((parent.get("fsrs_state") in (None, State.Review.name))
            and float(parent.get("mastery", 0) or 0) >= 0.7)


def _contract_satisfied(skill, payload):
    demonstration = str(skill.get("demonstration") or "")
    passed = bool(payload.get("task_passed"))
    evidence = payload.get("evidence") or []
    has_evidence = bool(evidence) if not isinstance(evidence, str) else bool(str(evidence).strip())
    if demonstration in ("practice", "explain", "deliverable"):
        return passed and has_evidence
    if demonstration == "recall":
        return passed and str(payload.get("recall_rating") or "").lower() not in ("again", "forget", "忘记")
    return passed


def _node_task_contract(task):
    """Attach the Slice 1 node contract and legacy skill mirror."""
    task = dict(task or {})
    primary_skill_id = str(task.get("primary_skill_id") or task.get("skill_id") or "").strip()
    supporting = []
    for item in task.get("supporting_skill_ids") or []:
        item = str(item or "").strip()
        if item and item != primary_skill_id and item not in supporting:
            supporting.append(item)
    evidence = task.get("mastery_evidence") if isinstance(task.get("mastery_evidence"), dict) else {}
    task.update({
        "task_kind": "node",
        "primary_skill_id": primary_skill_id,
        "skill_id": primary_skill_id,
        "supporting_skill_ids": supporting,
        "evidence_target": "mastery",
        "core_behavior": str(task.get("core_behavior") or evidence.get("behavior") or "").strip(),
        "estimated_verification_minutes": int(task.get("estimated_verification_minutes") or task.get("estimated_minutes") or 20),
        "contract_revision": int(task.get("contract_revision") or 1),
        "mastery_evidence": dict(evidence),
    })
    return task


def _supporting_skills_ready(state, task, now=None):
    skills = _skills(state)
    now_dt = _utc(now)
    primary = str(task.get("primary_skill_id") or task.get("skill_id") or "").strip()
    for supporting_id in task.get("supporting_skill_ids") or []:
        supporting_id = str(supporting_id or "").strip()
        if not supporting_id or supporting_id == primary:
            return False
        skill = skills.get(supporting_id) or {}
        if not skill.get("contract_met") and skill.get("band") != "skipped":
            return False
        try:
            due = bool(skill.get("review_due_at")) and datetime.fromisoformat(skill["review_due_at"]).astimezone(timezone.utc) <= now_dt
        except (TypeError, ValueError):
            due = False
        if due:
            try:
                overdue_days = (now_dt - datetime.fromisoformat(skill["review_due_at"]).astimezone(timezone.utc)).total_seconds() / 86400
            except (TypeError, ValueError):
                overdue_days = 0
            if overdue_days >= 3:
                return False
    return True


def _task_from_skill(skill_id, skill, source="graph_scheduler"):
    evidence = skill.get("mastery_evidence") if isinstance(skill.get("mastery_evidence"), dict) else {}
    demonstration = str(skill.get("demonstration") or "recall")
    reviews = int(skill.get("reviews", 0) or 0)
    task_type = demonstration if demonstration in ("recall", "practice", "explain", "deliverable", "diagnostic") else (
        "diagnostic" if reviews == 0 else "practice")
    labels = {"diagnostic": "诊断", "recall": "闭卷回忆", "practice": "应用练习",
              "explain": "讲解", "deliverable": "交付", "review": "到期复习"}
    name = skill.get("title") or skill_id
    acceptance = str(evidence.get("threshold") or "答案能够暴露真实掌握情况，并包含必要的解释或示例")
    expected = str(evidence.get("behavior") or "一份独立完成、可检查的答案")
    description = str(skill.get("description") or evidence.get("behavior") or "完成可检查的掌握出示。")
    return {
        "title": "{}：{}".format(labels.get(task_type, "学习"), name),
        "description": description,
        "type": "learn", "learning_task_type": task_type, "task_kind": "node",
        "skill_id": skill_id, "primary_skill_id": skill_id, "supporting_skill_ids": [],
        "evidence_target": "mastery",
        "prerequisites": list(skill.get("prerequisites", []) or []),
        "estimated_minutes": 15 if task_type == "diagnostic" else 20,
        "difficulty": max(1, min(5, round(float(skill.get("difficulty", 5) or 5) / 2))),
        "expected_output": expected, "acceptance": acceptance,
        "verification_mode": "strict", "source": source, "locked": True,
        "demonstration": demonstration,
        "mastery_evidence": evidence,
    }


def _bind_pack(state, pack):
    skills = _skills(state)
    model = state.setdefault("user_model", {})
    previous_pack_id = str(model.get("pack_id") or "")
    previous_pack_version = str(model.get("pack_version") or "")
    current_pack_id = str(pack.get("id") or "")
    current_pack_version = str(pack.get("version") or "")
    # A goal can switch packs. Do not let nodes from the previous pack leak
    # into the new frontier; custom non-pack nodes remain valid.
    if (previous_pack_id, previous_pack_version) != (current_pack_id, current_pack_version):
        for skill_id in list(skills):
            skill = skills.get(skill_id) or {}
            if (str(skill.get("pack_id") or ""), str(skill.get("pack_version") or "")) == (previous_pack_id, previous_pack_version):
                del skills[skill_id]
    model["pack_id"] = current_pack_id
    model["pack_version"] = current_pack_version
    incoming = {}
    for edge in pack.get("edges") or []:
        child = str(edge.get("to") or "").strip()
        parent = str(edge.get("from") or "").strip()
        if not child or not parent:
            continue
        incoming.setdefault(child, []).append(edge)
    for node in pack.get("nodes") or []:
        skill_id = str(node.get("id") or "").strip()
        if not skill_id:
            continue
        skill = skills.setdefault(skill_id, {"mastery": 0.0, "reviews": 0, "prerequisites": []})
        skill["title"] = str(node.get("title") or skill_id)
        skill["description"] = str(node.get("description") or "")
        skill["demonstration"] = str(node.get("demonstration") or "recall")
        skill["mastery_evidence"] = node.get("mastery_evidence") if isinstance(node.get("mastery_evidence"), dict) else {}
        skill["core_behavior"] = str(node.get("core_behavior") or skill["mastery_evidence"].get("behavior") or "").strip()
        skill["estimated_verification_minutes"] = int(node.get("estimated_verification_minutes") or 20)
        skill["contract_revision"] = int(node.get("contract_revision") or 1)
        skill["pack_id"] = pack.get("id", "")
        skill["pack_version"] = pack.get("version", "")
        meta = skill.setdefault("prerequisite_meta", {})
        parents = []
        for edge in incoming.get(skill_id, []):
            parent = str(edge.get("from") or "").strip()
            kind = str(edge.get("kind") or "hard")
            if kind not in ("hard", "soft"):
                kind = "legacy_unspecified"
            # Preserve user-confirmed edge adjustments across reloads.
            previous = meta.get(parent) if isinstance(meta.get(parent), dict) else {}
            meta[parent] = {"kind": str(previous.get("kind") or kind),
                            "rationale": str(previous.get("rationale") or edge.get("rationale") or "")}
            parents.append(parent)
            skills.setdefault(parent, {"mastery": 0.0, "reviews": 0, "prerequisites": []})
        skill["prerequisites"] = list(dict.fromkeys(parents))
        _refresh_band(skill)
    model["pack_sinks"] = list(pack.get("sinks") or [])
    return skills


def _refresh_band(skill, now=None):
    due = False
    try:
        due = bool(skill.get("review_due_at")) and datetime.fromisoformat(skill["review_due_at"]).astimezone(timezone.utc) <= _utc(now)
    except (TypeError, ValueError):
        due = False
    if skill.get("contract_met") and due:
        skill["band"] = "due"
    elif skill.get("contract_met") or skill.get("band") == "skipped":
        if skill.get("band") != "skipped":
            skill["band"] = "skipped" if skill.get("band") == "skipped" else "learning"
            if skill.get("contract_met"):
                skill["band"] = "learning"
    elif int(skill.get("reviews", 0) or 0) > 0:
        skill["band"] = "learning"
    else:
        skill["band"] = skill.get("band") or "unlearned"
    return skill["band"]


def _coverage_ok(pack, skills):
    if not pack:
        return False
    sinks = [str(item) for item in pack.get("sinks") or [] if str(item).strip()]
    if not sinks:
        return bool(pack.get("nodes"))
    return all(sink in skills for sink in sinks)


def coverage_gaps(pack, contract):
    """Success criteria that no pack cover label can explain."""
    covers = (pack or {}).get("covers") if isinstance(pack, dict) else None
    if not covers:
        return []
    return [str(criterion).strip() for criterion in (contract or {}).get("success_criteria") or []
            if str(criterion).strip() and not _criterion_covered(str(criterion).strip(), covers)]

def _criterion_covered(text, covers):
    labels = [str(label).strip() for label in covers if str(label).strip() and str(label).strip() in text]
    labels = [label for label in labels if not any(label != other and label in other for other in labels)]
    return text in covers or len(labels) >= 2

def _coverage_override_valid(criterion, overrides, skills):
    ids = overrides.get(criterion, []) if isinstance(overrides, dict) else []
    return bool(ids) and all(str(skill_id).strip() in skills for skill_id in ids)

def covered_skill_ids(pack, contract, overrides=None):
    covers = (pack or {}).get("covers") if isinstance(pack, dict) else {}
    ids = []
    for criterion in (contract or {}).get("success_criteria") or []:
        text = str(criterion or "").strip()
        keys = [text] if text in covers else ([label for label in covers if str(label).strip() in text] if _criterion_covered(text, covers) else [])
        keys += [text] if text in (overrides or {}) else []
        for key in keys:
            for skill_id in (overrides or {}).get(key, covers.get(key, [])):
                skill_id = str(skill_id).strip()
                if skill_id and skill_id not in ids:
                    ids.append(skill_id)
    return ids


class SkillMap:
    """Small interface over the per-goal skill DAG."""

    def __init__(self, state, contract=None, pack=None, ok=True, error=""):
        self.state = state
        self.contract = contract if isinstance(contract, dict) else {}
        self.pack = pack
        self.ok = bool(ok)
        self.error = error
        self.gaps = []
        self.pack_id = str((pack or {}).get("id") or (state.get("user_model") or {}).get("pack_id") or "")
        self.pack_version = str((pack or {}).get("version") or (state.get("user_model") or {}).get("pack_version") or "")

    @classmethod
    def load(cls, state, contract):
        state = state if isinstance(state, dict) else {}
        contract = contract if isinstance(contract, dict) else {}
        pack = match_pack(contract, state)
        if not pack:
            return cls(state, contract, pack=None, ok=False, error="uncovered")
        _bind_pack(state, pack)
        if str(contract.get("baseline") or "").strip():
            loaded = cls(state, contract, pack=pack, ok=True)
            loaded.apply_baseline(contract.get("baseline"))
        gaps = coverage_gaps(pack, contract)
        overrides = (state.get("user_model", {}) or {}).get("coverage_overrides", {})
        gaps = [gap for gap in gaps if not _coverage_override_valid(gap, overrides, _skills(state))]
        ok = _coverage_ok(pack, _skills(state)) and not gaps
        loaded = cls(state, contract, pack=pack, ok=ok, error="" if ok else "uncovered")
        loaded.gaps = gaps
        state.setdefault("user_model", {})["coverage_gaps"] = list(gaps)
        return loaded

    def needs_patch(self):
        return not self.ok

    def focus(self, now=None, capacity=None):
        return learning_focus(self.state, now, pack_order=True)

    def unlock(self, skill_id):
        skills = _skills(self.state)
        skill = skills.get(skill_id)
        return bool(skill) and _ready(skills, skill)

    def next_task(self, now=None, skill_id=None):
        if not self.ok:
            # Coverage repair is an internal AI planning action, never a user task.
            return None
        if skill_id:
            skill = _skills(self.state).get(skill_id)
            return _task_from_skill(skill_id, skill or {}, source="pack") if skill else None
        review = due_review_task(self.state, now)
        if review:
            return review
        focus = self.focus(now=now)
        if not focus:
            return None
        skill = _skills(self.state)[focus["skill_id"]]
        return _task_from_skill(focus["skill_id"], skill, source="pack")

    def apply_baseline(self, baseline):
        text = str(baseline or "")
        if not text.strip():
            return self
        skills = _skills(self.state)
        skippable = []
        if self.pack:
            skippable = list(self.pack.get("skippable") or [])
        folded = text.casefold()
        for item in skippable:
            skill_id = str((item or {}).get("id") or "").strip()
            tags = [(str(tag) or "").strip() for tag in (item or {}).get("tags") or [] if str(tag).strip()]
            if not skill_id or skill_id not in skills or not tags:
                continue
            skill = skills[skill_id]
            if skill.get("baseline_override"):
                continue
            if all((tag.casefold() in folded or tag in text) for tag in tags):
                skill["band"] = "skipped"
                skill["skip_reason"] = "baseline"
        if skippable:
            return self
        for skill_id, skill in skills.items():
            haystack = " ".join([skill_id, str(skill.get("title") or ""), str(skill.get("description") or "")])
            if "听力" in text and "听力" in haystack:
                skill["band"] = "skipped"
                skill["skip_reason"] = "baseline"
            elif "python" in text.casefold() and skill_id.startswith("python.syntax") and "已经" in text:
                skill["band"] = "skipped"
                skill["skip_reason"] = "baseline"
        return self

    def unskip(self, skill_id):
        skill = _skills(self.state).get(str(skill_id or "").strip())
        if not skill:
            return self
        if skill.get("band") == "skipped" or skill.get("skip_reason") == "baseline":
            skill["band"] = "unlearned"
            skill.pop("skip_reason", None)
            skill["baseline_override"] = True
            _refresh_band(skill)
        return self

    def apply_outcome(self, skill_id, payload):
        payload = payload if isinstance(payload, dict) else {}
        skills = _skills(self.state)
        skill = skills.get(skill_id) or skills.setdefault(skill_id, {"mastery": 0.0, "reviews": 0, "prerequisites": []})
        met = _contract_satisfied(skill, payload)
        skill["contract_met"] = bool(met)
        if met:
            skill["mastery"] = max(float(skill.get("mastery", 0) or 0), 1.0)
            skill["band"] = "learning"
        else:
            skill["contract_met"] = False
            if skill.get("skip_reason") == "baseline":
                skill.pop("skip_reason", None)
                skill["baseline_override"] = True
                skill["band"] = "learning" if int(skill.get("reviews", 0) or 0) else "unlearned"
        _refresh_band(skill)
        return self

    def apply_feedback(self, decision):
        decision = decision if isinstance(decision, dict) else {}
        tasks = self.state.setdefault("tasks", [])
        skill_id = str(decision.get("skill_id") or "")
        skills = _skills(self.state)
        skill = skills.get(skill_id) or {}
        if decision.get("kind") == "wrong_direction":
            if not decision.get("confirmed"):
                return self
            child_id = str(decision.get("to") or skill_id)
            parent_id = str(decision.get("from") or "")
            child = skills.get(child_id) or {}
            if not parent_id:
                hard = [parent for parent in child.get("prerequisites", []) or [] if _edge_kind(child, parent) == "hard"]
                parent_id = hard[0] if hard else ""
            if parent_id and parent_id in (child.get("prerequisite_meta") or {}):
                child["prerequisite_meta"][parent_id]["kind"] = "soft"
                child["prerequisite_meta"][parent_id]["rationale"] = (
                    child["prerequisite_meta"][parent_id].get("rationale") or "") + "（用户确认方向调整，降为软先修）"
            return self
        if decision.get("kind") == "too_easy" and skill_id:
            order = ["recall", "practice", "explain", "deliverable"]
            current = str(skill.get("demonstration") or "recall")
            if current in order and order.index(current) < len(order) - 1:
                skill["demonstration"] = order[order.index(current) + 1]
            return self
        if decision.get("kind") not in ("too_hard", "stuck"):
            return self
        # Address the first unmet blocking prerequisite, including blockers
        # of an already queued prerequisite task.
        candidates = list(skill.get("prerequisites", []) or [])
        for parent in list(candidates):
            parent_skill = skills.get(parent) or {}
            for grandparent in parent_skill.get("prerequisites", []) or []:
                if _edge_kind(parent_skill, grandparent) != "soft" and not _parent_met(skills, grandparent):
                    candidates.append(grandparent)
                    break
        for parent in candidates:
            parent_skill = skills.get(parent) or {}
            if _parent_met(skills, parent) or any(str(task.get("skill_id") or "") == parent for task in tasks):
                continue
            draft = _task_from_skill(parent, parent_skill, source="adaptive")
            draft["id"] = "{}_prereq".format(decision.get("task_id") or skill_id)
            draft["status"] = "pending"
            draft["depends_on"] = [decision.get("task_id")] if decision.get("task_id") else []
            tasks.append(draft)
            break
        return self

    def view(self, now=None):
        graph = knowledge_graph(self.state, now)
        graph["coverage"] = self.ok
        graph["pack_id"] = self.pack_id
        graph["pack_version"] = self.pack_version
        graph["gaps"] = list(self.gaps) if self.gaps else ([] if self.ok else ["uncovered"])
        return graph


def task_in_map(skill_map, task):
    skill_id = str((task or {}).get("skill_id") or "")
    if not skill_id:
        return False
    if skill_map.pack:
        return any(str(node.get("id")) == skill_id for node in skill_map.pack.get("nodes") or [])
    return skill_id in _skills(skill_map.state)


def requires_recall_rating(task, state=None):
    skill_id = str((task or {}).get("skill_id") or "")
    if not skill_id:
        return False
    skill = (_skills(state) if state is not None else {}).get(skill_id) or {}
    demonstration = str(skill.get("demonstration") or task.get("demonstration") or "")
    if demonstration:
        return demonstration == "recall"
    return True


def sync_task_graph(state, task):
    """Upsert a task's component and keep the prerequisite graph acyclic."""
    skill_id = str(task.get("skill_id") or "").strip()
    if not skill_id:
        return None
    skills = _skills(state)
    skill = skills.setdefault(skill_id, {"mastery": 0.0, "reviews": 0, "prerequisites": []})
    if task.get("title"): skill["title"] = str(task["title"]).strip()
    if task.get("description"): skill["description"] = str(task["description"]).strip()
    incoming = task.get("prerequisites") or []
    if skill.get("pack_id") or (not incoming and skill.get("prerequisites")):
        return skill
    prerequisites = []
    for parent in dict.fromkeys(incoming):
        parent = str(parent).strip()
        if not parent or parent == skill_id:
            continue
        skills.setdefault(parent, {"mastery": 0.0, "reviews": 0, "prerequisites": []})
        if not _path_exists(skills, parent, skill_id):
            prerequisites.append(parent)
    skill["prerequisites"] = prerequisites
    return skill


def _proposed_graph_has_cycle(nodes):
    graph = {}
    for node in nodes:
        skill_id = str(node.get("id") or "").strip()
        graph[skill_id] = [str(parent).strip() for parent in (node.get("prerequisites") or []) if str(parent).strip()]
    visiting, seen = set(), set()

    def dfs(node):
        if node in visiting:
            return True
        if node in seen:
            return False
        visiting.add(node)
        if any(dfs(parent) for parent in graph.get(node, [])):
            return True
        visiting.remove(node)
        seen.add(node)
        return False

    return any(dfs(node) for node in graph)


def propose_nodes(state, proposal):
    """Accept extra nodes only when they match the bound pack version and carry contracts."""
    proposal = proposal if isinstance(proposal, dict) else {}
    model = state.setdefault("user_model", {})
    pack_id = str(model.get("pack_id") or "")
    pack_version = str(model.get("pack_version") or "")
    if str(proposal.get("pack_id") or "") != pack_id or str(proposal.get("pack_version") or "") != pack_version:
        return {"error": "pack_version", "nodes": [], "edges": []}
    nodes = [node for node in (proposal.get("nodes") or []) if isinstance(node, dict)]
    pack_ids = set()
    pack = next((item for item in load_packs() if item.get("id") == pack_id and str(item.get("version")) == pack_version), None)
    if pack:
        pack_ids = {str(node.get("id")) for node in pack.get("nodes") or []}
    extras = []
    seen_ids = set()
    for node in nodes:
        skill_id = str(node.get("id") or "").strip()
        if not skill_id or skill_id in pack_ids:
            continue
        if skill_id in seen_ids:
            return {"error": "duplicate_id", "nodes": [], "edges": []}
        seen_ids.add(skill_id)
        evidence = node.get("mastery_evidence") if isinstance(node.get("mastery_evidence"), dict) else {}
        if any(not str(evidence.get(field) or "").strip() for field in ("behavior", "threshold", "counterexample")):
            return {"error": "node_contract", "nodes": [], "edges": []}
        if not str(node.get("core_behavior") or evidence.get("behavior") or "").strip():
            return {"error": "node_contract", "nodes": [], "edges": []}
        extras.append(node)
    if _proposed_graph_has_cycle(extras + [{"id": skill_id, "prerequisites": skill.get("prerequisites", [])}
                                           for skill_id, skill in _skills(state).items()]):
        return {"error": "cycle", "nodes": [], "edges": []}
    skills = _skills(state)
    for node in extras:
        skill_id = str(node["id"]).strip()
        skill = skills.setdefault(skill_id, {"mastery": 0.0, "reviews": 0, "prerequisites": []})
        skill["title"] = str(node.get("title") or skill_id)
        skill["description"] = str(node.get("description") or "")
        skill["demonstration"] = str(node.get("demonstration") or "explain")
        skill["mastery_evidence"] = node.get("mastery_evidence") if isinstance(node.get("mastery_evidence"), dict) else {}
        skill["pack_id"] = pack_id
        skill["pack_version"] = pack_version
        skill["proposed"] = True
        meta = skill.setdefault("prerequisite_meta", {})
        parents = []
        incoming = node.get("prerequisite_meta") if isinstance(node.get("prerequisite_meta"), dict) else {}
        for parent in node.get("prerequisites") or []:
            parent = str(parent).strip()
            if not parent or parent == skill_id:
                continue
            info = incoming.get(parent) if isinstance(incoming.get(parent), dict) else {}
            kind = str(info.get("kind") or "soft")
            if kind not in ("hard", "soft"):
                kind = "soft"
            meta[parent] = {"kind": kind, "rationale": str(info.get("rationale") or "提案补充")}
            parents.append(parent)
            skills.setdefault(parent, {"mastery": 0.0, "reviews": 0, "prerequisites": []})
        skill["prerequisites"] = list(dict.fromkeys(parents))
        _refresh_band(skill)
    return knowledge_graph(state)


def merge_knowledge_graph(state, raw):
    """Merge an AI-produced graph through the same DAG validation boundary."""
    nodes = raw.get("nodes", []) if isinstance(raw, dict) else []
    clean = [node for node in nodes[:200] if isinstance(node, dict) and str(node.get("id") or "").strip()]
    if _proposed_graph_has_cycle(clean):
        return {"nodes": [], "edges": [], "focus": {}, "ready": [], "blocked": [], "error": "cycle"}
    if (state.get("user_model") or {}).get("pack_id"):
        extras = {"pack_id": (state.get("user_model") or {}).get("pack_id", ""),
                  "pack_version": (state.get("user_model") or {}).get("pack_version", ""),
                  "nodes": clean}
        proposed = propose_nodes(state, extras)
        if proposed.get("error") in ("pack_version", "node_contract", "cycle"):
            return proposed
        return knowledge_graph(state)
    skills = _skills(state)
    for node in clean:
        skill_id = str(node["id"]).strip()
        skill = skills.setdefault(skill_id, {"mastery": 0.0, "reviews": 0, "prerequisites": []})
        if node.get("title"): skill["title"] = str(node["title"]).strip()
        if node.get("description"): skill["description"] = str(node["description"]).strip()
        meta = skill.setdefault("prerequisite_meta", {})
        for parent in node.get("prerequisites") or []:
            parent = str(parent).strip()
            if parent and parent not in meta:
                meta[parent] = {"kind": "legacy_unspecified", "rationale": ""}
    for node in clean:
        sync_task_graph(state, {"skill_id": node["id"], "title": node.get("title", ""),
                                "description": node.get("description", ""),
                                "prerequisites": node.get("prerequisites", [])})
    return knowledge_graph(state)


def task_is_unlocked(state, task):
    task = task if isinstance(task, dict) else {}
    primary = str(task.get("primary_skill_id") or task.get("skill_id") or "").strip()
    # Stage/outcome/legacy tasks have their own gates; Slice 1 only gates nodes.
    if not primary or str(task.get("task_kind") or "node").strip() != "node":
        return True
    skill = sync_task_graph(state, task)
    if skill is None or not _ready(_skills(state), skill):
        return False
    return _supporting_skills_ready(state, task)


def _rating(state, task, passed):
    if not passed:
        return Rating.Again
    explicit = {"again": Rating.Again, "hard": Rating.Hard, "good": Rating.Good, "easy": Rating.Easy}
    if task.get("recall_rating") in explicit:
        return explicit[task["recall_rating"]]
    latest = next((x for x in reversed(state.get("feedback_history", []))
                   if x.get("task_id") == task.get("id")), {})
    if latest.get("kind") == "too_easy":
        return Rating.Easy
    estimate = max(1, int(task.get("estimated_minutes", 30) or 30))
    if int(task.get("attempts", 0) or 0) >= 2 or task_actual_minutes(task) > estimate * 1.25:
        return Rating.Hard
    return Rating.Good


def record_learning_outcome(state, task, passed, now=None):
    """Review only a node task's primary skill through the FSRS scheduler.

    Raw legacy callers with one ``skill_id`` remain compatible. An explicit
    non-node kind is never allowed to settle mastery, and supporting skills are
    deliberately ignored.
    """
    task = task if isinstance(task, dict) else {}
    declared_kind = str(task.get("task_kind") or "").strip()
    primary_skill_id = str(task.get("primary_skill_id") or task.get("skill_id") or "").strip()
    if not primary_skill_id or (declared_kind and declared_kind != "node"):
        return None
    settlement_task = dict(task, skill_id=primary_skill_id, primary_skill_id=primary_skill_id, task_kind="node")
    skill = sync_task_graph(state, settlement_task)
    task = _node_task_contract(dict(settlement_task,
                                    core_behavior=skill.get("core_behavior"),
                                    estimated_verification_minutes=skill.get("estimated_verification_minutes"),
                                    contract_revision=skill.get("contract_revision"),
                                    mastery_evidence=skill.get("mastery_evidence")))
    if skill is None:
        return None
    scheduler = _scheduler(state)
    try:
        card = Card.from_json(skill["fsrs_card"]) if skill.get("fsrs_card") else Card()
    except (TypeError, ValueError):
        card = Card()
    reviewed_at = _utc(now)
    rating = _rating(state, task, passed)
    card, log = scheduler.review_card(card, rating, reviewed_at)
    retrievability = scheduler.get_card_retrievability(card, reviewed_at)
    recalled = passed and rating != Rating.Again
    demonstration = str(skill.get("demonstration") or "")
    if demonstration in ("practice", "explain", "deliverable"):
        met = _contract_satisfied(skill, {"task_passed": passed, "evidence": settlement_task.get("evidence"),
                                         "recall_rating": settlement_task.get("recall_rating")})
        skill["contract_met"] = met
        mastery_value = 1.0 if met else 0.0
    else:
        mastery_value = round(retrievability if recalled else 0.0, 4)
    skill.update({
        "mastery": mastery_value,
        "reviews": int(skill.get("reviews", 0) or 0) + 1,
        "last_result": "recalled" if recalled else "forgotten",
        "last_reviewed_at": reviewed_at.isoformat(),
        "review_due_at": card.due.isoformat(),
        "fsrs_card": card.to_json(),
        "fsrs_state": card.state.name,
        "stability": card.stability,
        "difficulty": card.difficulty,
        "retrievability": round(retrievability, 4),
        "last_rating": rating.name,
    })
    model = state.setdefault("user_model", {})
    if task.get("learning_task_type") == "diagnostic":
        score = {Rating.Again: 0.2, Rating.Hard: 0.45, Rating.Good: 0.7, Rating.Easy: 0.9}[rating]
        model.setdefault("ability_diagnostics", {})[task["skill_id"]] = {
            "assessed": True, "score": score if passed else 0.0,
            "rating": rating.name, "passed": bool(passed), "updated_at": reviewed_at.isoformat(),
        }
    model.setdefault("fsrs_review_logs", []).append(log.to_json())
    model["fsrs_review_logs"] = model["fsrs_review_logs"][-5000:]
    task["review_due_at"] = skill["review_due_at"]
    return skill


def _ready(skills, skill):
    for parent in skill.get("prerequisites", []) or []:
        if _edge_kind(skill, parent) == "soft":
            continue
        if not _parent_met(skills, parent):
            return False
    return True


def learning_focus(state, now=None, pack_order=False):
    skills = (state.get("user_model", {}) or {}).get("skills", {}) or {}
    now_dt = _utc(now)
    pack_index = {}
    if pack_order:
        pack_id = (state.get("user_model") or {}).get("pack_id")
        pack = next((item for item in load_packs() if item.get("id") == pack_id), None)
        pack_index = {str(node.get("id")): index for index, node in enumerate((pack or {}).get("nodes") or [])}
    rows = []
    for skill_id, skill in skills.items():
        if not isinstance(skill, dict) or not _ready(skills, skill):
            continue
        if skill.get("band") == "skipped" or skill.get("planning_hold"):
            continue
        try:
            due = bool(skill.get("review_due_at")) and datetime.fromisoformat(skill["review_due_at"]).astimezone(timezone.utc) <= now_dt
        except (TypeError, ValueError):
            due = False
        if skill.get("contract_met") and not due:
            continue
        rows.append((not due, pack_index.get(skill_id, 10 ** 6), float(skill.get("mastery", 0) or 0), skill_id, skill))
    if not rows:
        return {}
    is_not_due, _order, mastery, skill_id, skill = min(rows)
    return {"skill_id": skill_id, "mastery": mastery, "review_due_at": skill.get("review_due_at", ""),
            "reason": "review_due" if not is_not_due else "weakest_ready", "band": skill.get("band", "unlearned")}


def due_review_task(state, now=None):
    focus = learning_focus(state, now)
    if focus.get("reason") != "review_due":
        return None
    skill = _skills(state)[focus["skill_id"]]
    return _node_task_contract({
        "title": "到期复习：{}".format(focus["skill_id"]),
        "description": "不查看资料，先回忆核心概念，再完成一个应用示例。",
        "type": "review", "learning_task_type": "review", "skill_id": focus["skill_id"],
        "prerequisites": list(skill.get("prerequisites", []) or []),
        "estimated_minutes": 20, "difficulty": max(1, min(5, round(float(skill.get("difficulty", 5) or 5) / 2))),
        "expected_output": "一份闭卷回忆答案和一个应用示例",
        "acceptance": "答案覆盖核心概念，示例可验证且未照抄资料",
        "verification_mode": "strict", "source": "fsrs", "locked": True,
    })


def next_learning_task(state, now=None, budget_minutes=None, stage_proposals=None):
    """Create one deterministic task for the current graph frontier."""
    review = due_review_task(state, now)
    if review:
        return review
    if stage_proposals is not None:
        pool = stage_candidate_pool(state, stage_proposals, now, budget_minutes if budget_minutes is not None else 30)
        if pool:
            return pool[0]
    if (state.get("user_model") or {}).get("pack_id"):
        return SkillMap(state, ok=True).next_task(now=now)
    focus = learning_focus(state, now)
    if not focus:
        return None
    skill = _skills(state)[focus["skill_id"]]
    if skill.get("mastery_evidence"):
        return _task_from_skill(focus["skill_id"], skill)
    reviews = int(skill.get("reviews", 0) or 0)
    fsrs_state = skill.get("fsrs_state", "New")
    task_type = "diagnostic" if reviews == 0 else ("recall" if fsrs_state == State.Learning.name else "practice")
    labels = {"diagnostic": "诊断", "recall": "闭卷回忆", "practice": "应用练习"}
    name = skill.get("title") or focus["skill_id"]
    return _node_task_contract({
        "title": "{}：{}".format(labels[task_type], name),
        "description": ("不查看资料，回答核心问题并标出不会的部分。" if task_type != "practice"
                        else "完成一个新场景中的应用题，并解释关键步骤。"),
        "type": "learn", "learning_task_type": task_type, "skill_id": focus["skill_id"],
        "prerequisites": list(skill.get("prerequisites", []) or []),
        "estimated_minutes": 15 if task_type == "diagnostic" else 20,
        "difficulty": max(1, min(5, round(float(skill.get("difficulty", 5) or 5) / 2))),
        "expected_output": "一份独立完成、可检查的答案",
        "acceptance": "答案能够暴露真实掌握情况，并包含必要的解释或示例",
        "verification_mode": "strict", "source": "graph_scheduler", "locked": True,
    })


def knowledge_graph(state, now=None):
    """Return a compact graph projection for UI and generation context."""
    skills = (state.get("user_model", {}) or {}).get("skills", {}) or {}
    focus = learning_focus(state, now)
    nodes = []
    edges = []
    for skill_id, skill in skills.items():
        if not isinstance(skill, dict):
            continue
        ready = _ready(skills, skill)
        nodes.append({"id": skill_id, "title": skill.get("title", skill_id),
                      "description": skill.get("description", ""),
                      "mastery": float(skill.get("mastery", 0) or 0),
                      "state": skill.get("fsrs_state", "New"), "ready": ready,
                      "band": skill.get("band", "unlearned"),
                      "demonstration": skill.get("demonstration", ""),
                      "mastery_evidence": skill.get("mastery_evidence") or {},
                      "contract_met": bool(skill.get("contract_met")),
                      "skip_reason": skill.get("skip_reason", ""),
                      "due_at": skill.get("review_due_at", ""), "difficulty": skill.get("difficulty")})
        edges.extend({"from": parent, "to": skill_id, "kind": _edge_kind(skill, parent),
                      "rationale": (_skill_meta(skill).get(parent) or {}).get("rationale", "")}
                     for parent in skill.get("prerequisites", []) or [])
    model = state.get("user_model") or {}
    return {"nodes": nodes, "edges": edges, "focus": focus,
            "ready": [node["id"] for node in nodes if node["ready"]],
            "blocked": [node["id"] for node in nodes if not node["ready"]],
            "pack_id": model.get("pack_id", ""), "pack_version": model.get("pack_version", ""),
            "coverage": bool(nodes) and not list(model.get("coverage_gaps") or []),
            "gaps": list(model.get("coverage_gaps") or [])}
