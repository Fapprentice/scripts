"""FSRS scheduling and the per-goal prerequisite knowledge graph."""

import json
import re
from datetime import datetime, timezone

from fsrs import Card, Rating, Scheduler, State
from utils import task_actual_minutes

_CET4_WORDS = [
    ("abandon","放弃"),("ability","能力"),("absence","缺席"),("academic","学术的"),("access","使用权"),
    ("accompany","陪伴"),("accomplish","完成"),("accurate","准确的"),("adapt","适应"),("adequate","足够的"),
    ("advocate","提倡"),("allocate","分配"),("alternative","替代方案"),("analyze","分析"),("anticipate","预期"),
    ("apparent","明显的"),("approach","方法"),("appropriate","合适的"),("assess","评估"),("assume","假设"),
    ("available","可获得的"),("benefit","益处"),("challenge","挑战"),("circumstance","情况"),("consequence","后果"),
    ("consume","消耗"),("contribute","贡献"),("decline","下降"),("demonstrate","证明"),("essential","必不可少的")]

def _diagnostic_materials(skill_id):
    if skill_id == "english.vocabulary":
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
    if any(word in text for word in ("词汇识别", "词义匹配", "vocab.recognition")): skill_id = "english.vocabulary"
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
    folded = goal.casefold()
    learning_words = ("学习", "考试", "四级", "六级", "英语", "词汇", "语法", "数学", "编程",
                      "python", "java", "cet", "ielts", "toefl")
    if not any(word in folded for word in learning_words):
        return []
    if any(word in folded for word in ("英语", "四级", "六级", "词汇", "cet", "ielts", "toefl")):
        return [
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
        ]
    return [
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
    ]


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


def initial_diagnostic_tasks(state, goal, limit=3):
    profile = ability_profile(state, goal)
    missing = {item["skill_id"] for item in profile["dimensions"] if not item["assessed"]}
    tasks = []
    for item in diagnostic_dimensions(goal, state):
        if item["skill_id"] not in missing: continue
        materials, interaction = _diagnostic_materials(item["skill_id"])
        tasks.append(dict(item, materials=item.get("materials") or materials,
                          interaction=item.get("interaction") or interaction, type="diagnostic",
                          learning_task_type="diagnostic", difficulty=2, verification_mode="strict",
                          source="ability_diagnostic", locked=True))
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
    if not incoming and skill.get("prerequisites"):
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


def merge_knowledge_graph(state, raw):
    """Merge an AI-produced graph through the same DAG validation boundary."""
    nodes = raw.get("nodes", []) if isinstance(raw, dict) else []
    clean = [node for node in nodes[:200] if isinstance(node, dict) and str(node.get("id") or "").strip()]
    skills = _skills(state)
    for node in clean:
        skill_id = str(node["id"]).strip()
        skill = skills.setdefault(skill_id, {"mastery": 0.0, "reviews": 0, "prerequisites": []})
        if node.get("title"): skill["title"] = str(node["title"]).strip()
        if node.get("description"): skill["description"] = str(node["description"]).strip()
    for node in clean:
        sync_task_graph(state, {"skill_id": node["id"], "title": node.get("title", ""),
                                "description": node.get("description", ""),
                                "prerequisites": node.get("prerequisites", [])})
    return knowledge_graph(state)


def task_is_unlocked(state, task):
    skill = sync_task_graph(state, task)
    return skill is None or _ready(_skills(state), skill)


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
    """Review one knowledge component through the official FSRS scheduler."""
    skill = sync_task_graph(state, task)
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
    skill.update({
        "mastery": round(retrievability if recalled else 0.0, 4),
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
    return all((skills.get(parent, {}) or {}).get("fsrs_state") in (None, State.Review.name)
               and float((skills.get(parent, {}) or {}).get("mastery", 0) or 0) >= 0.7
               for parent in skill.get("prerequisites", []) or [])


def learning_focus(state, now=None):
    skills = (state.get("user_model", {}) or {}).get("skills", {}) or {}
    now_dt = _utc(now)
    rows = []
    for skill_id, skill in skills.items():
        if not isinstance(skill, dict) or not _ready(skills, skill):
            continue
        try:
            due = bool(skill.get("review_due_at")) and datetime.fromisoformat(skill["review_due_at"]).astimezone(timezone.utc) <= now_dt
        except (TypeError, ValueError):
            due = False
        rows.append((not due, float(skill.get("mastery", 0) or 0), skill_id, skill))
    if not rows:
        return {}
    is_not_due, mastery, skill_id, skill = min(rows)
    return {"skill_id": skill_id, "mastery": mastery, "review_due_at": skill.get("review_due_at", ""),
            "reason": "review_due" if not is_not_due else "weakest_ready"}


def due_review_task(state, now=None):
    focus = learning_focus(state, now)
    if focus.get("reason") != "review_due":
        return None
    skill = _skills(state)[focus["skill_id"]]
    return {
        "title": "到期复习：{}".format(focus["skill_id"]),
        "description": "不查看资料，先回忆核心概念，再完成一个应用示例。",
        "type": "review", "learning_task_type": "review", "skill_id": focus["skill_id"],
        "prerequisites": list(skill.get("prerequisites", []) or []),
        "estimated_minutes": 20, "difficulty": max(1, min(5, round(float(skill.get("difficulty", 5) or 5) / 2))),
        "expected_output": "一份闭卷回忆答案和一个应用示例",
        "acceptance": "答案覆盖核心概念，示例可验证且未照抄资料",
        "verification_mode": "strict", "source": "fsrs", "locked": True,
    }


def next_learning_task(state, now=None):
    """Create one deterministic task for the current graph frontier."""
    review = due_review_task(state, now)
    if review:
        return review
    focus = learning_focus(state, now)
    if not focus:
        return None
    skill = _skills(state)[focus["skill_id"]]
    reviews = int(skill.get("reviews", 0) or 0)
    fsrs_state = skill.get("fsrs_state", "New")
    task_type = "diagnostic" if reviews == 0 else ("recall" if fsrs_state == State.Learning.name else "practice")
    labels = {"diagnostic": "诊断", "recall": "闭卷回忆", "practice": "应用练习"}
    name = skill.get("title") or focus["skill_id"]
    return {
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
    }


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
                      "due_at": skill.get("review_due_at", ""), "difficulty": skill.get("difficulty")})
        edges.extend({"from": parent, "to": skill_id} for parent in skill.get("prerequisites", []) or [])
    return {"nodes": nodes, "edges": edges, "focus": focus,
            "ready": [node["id"] for node in nodes if node["ready"]],
            "blocked": [node["id"] for node in nodes if not node["ready"]]}
