"""FSRS scheduling and the per-goal skill map."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from fsrs import Card, Rating, Scheduler, State
from utils import task_actual_minutes

PACKS_DIR = Path(__file__).resolve().parent / "packs"
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


def match_pack(contract):
    contract = contract if isinstance(contract, dict) else {}
    text = " ".join([
        str(contract.get("outcome") or ""),
        str(contract.get("baseline") or ""),
        " ".join(str(item) for item in (contract.get("success_criteria") or [])),
    ]).casefold()
    for pack in load_packs():
        if any(str(token).casefold() in text for token in pack.get("match") or []):
            return pack
    return None


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
        return [skill_map.next_task(now=now)]
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
        "type": "learn", "learning_task_type": task_type, "skill_id": skill_id,
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
    if skill.get("band") == "skipped" and not skill.get("contract_met"):
        return skill["band"]
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
    gaps = []
    for criterion in (contract or {}).get("success_criteria") or []:
        text = str(criterion or "").strip()
        if not text:
            continue
        if not any(str(label) and str(label) in text for label in covers):
            gaps.append(text)
    return gaps


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
        pack = match_pack(contract)
        if not pack:
            return cls(state, contract, pack=None, ok=False, error="uncovered")
        _bind_pack(state, pack)
        if str(contract.get("baseline") or "").strip():
            loaded = cls(state, contract, pack=pack, ok=True)
            loaded.apply_baseline(contract.get("baseline"))
        gaps = coverage_gaps(pack, contract)
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
            return {
                "title": "补全技能地图",
                "description": "先补齐能推出最终成果的技能节点和先修，再生成今日学习任务。",
                "type": "plan", "learning_task_type": "map_patch", "skill_id": "",
                "prerequisites": [], "estimated_minutes": 15, "difficulty": 1,
                "expected_output": "一张覆盖最终成果的技能地图",
                "acceptance": "汇点能推出成功标准，且每条先修都有类型和理由",
                "verification_mode": "strict", "source": "map_patch", "locked": True,
            }
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
        elif str(skill.get("demonstration") or "") in ("practice", "explain", "deliverable"):
            skill["contract_met"] = False
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
        if not str(evidence.get("threshold") or "").strip():
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
    demonstration = str(skill.get("demonstration") or "")
    if demonstration in ("practice", "explain", "deliverable"):
        met = _contract_satisfied(skill, {"task_passed": passed, "evidence": task.get("evidence"),
                                         "recall_rating": task.get("recall_rating")})
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
    if (state.get("user_model") or {}).get("pack_id"):
        return SkillMap(state, ok=True).next_task(now=now)
    review = due_review_task(state, now)
    if review:
        return review
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
