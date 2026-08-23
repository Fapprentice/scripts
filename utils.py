#!/usr/bin/env python3
"""Task Verge utility functions — pure helpers, zero side effects.

Extracted from task-panel.pyw (Phase 4 module split).
All functions are pure or have only local I/O — no global state.
"""

import json
import os
import random
import re
import subprocess
import time
from datetime import datetime, date

# ---------------------------------------------------------------------------
# subprocess helper (Windows CREATE_NO_WINDOW)
# ---------------------------------------------------------------------------
_CNW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0

def _run(cmd, **kw):
    if _CNW and "creationflags" not in kw:
        kw["creationflags"] = _CNW
    # Windows utilities may emit output in the active console code page while
    # the process inherits an UTF-8 locale.  Replacement keeps discovery and
    # diagnostics usable instead of leaking reader-thread decode warnings.
    kw.setdefault("errors", "replace")
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ---------------------------------------------------------------------------
# Text extraction / normalisation
# ---------------------------------------------------------------------------

def task_text(t):
    if t is None: return ""
    if isinstance(t, dict): return str(t.get("text") or t.get("name") or t.get("title") or t.get("description") or "").strip()
    s = str(t).strip()
    return "" if s.lower() in ("none", "null", "nil", "undefined", "n/a", "无", "暂无", "不需要") else s


def value_text(v):
    if v is None: return ""
    if isinstance(v, (dict, list)): return ""
    s = str(v).strip()
    return "" if s.lower() in ("none", "null", "nil", "undefined", "n/a", "无", "暂无", "不需要") else s


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def new_id(prefix="task"):
    return "{}_{}_{}".format(prefix, int(time.time() * 1000), random.randint(1000, 9999))


# ---------------------------------------------------------------------------
# List / task helpers
# ---------------------------------------------------------------------------

def as_list(v):
    if isinstance(v, list): return [task_text(x) for x in v if task_text(x)]
    if task_text(v): return [task_text(v)]
    return []


def task_done(t, flag=False):
    if isinstance(t, dict):
        return bool(t.get("done")) or t.get("status") == "done" or bool(flag)
    return bool(flag)


def app_confidence(v):
    try: return max(0, min(1, float(v or 0)))
    except Exception: return 0


def _nat(v):
    try: return max(0, int(v or 0))
    except (TypeError, ValueError): return 0


# ---------------------------------------------------------------------------
# Task normalisation
# ---------------------------------------------------------------------------

def normalize_task(t, goal_id="", idx=0, done=False):
    if isinstance(t, dict):
        title = task_text(t)
        status = "done" if task_done(t, done) else (t.get("status") or "pending")
        try: minutes = int(t.get("estimated_minutes") or t.get("minutes") or 30)
        except Exception: minutes = 30
        try: difficulty = int(t.get("difficulty") or 2)
        except Exception: difficulty = 2
        return {
            "id": task_text(t.get("id")) or new_id("task"),
            "goal_id": task_text(t.get("goal_id")) or str(goal_id),
            "title": title, "text": title,
            "description": task_text(t.get("description")),
            "type": task_text(t.get("type")) or "practice",
            "role": task_text(t.get("role")) or "secondary",
            "status": status if status in ("pending", "doing", "paused", "partial", "done", "skipped", "deferred") else "pending",
            "estimated_minutes": max(5, min(180, minutes)),
            "required_apps": as_list(t.get("required_apps")),
            "allowed_apps": as_list(t.get("allowed_apps")),
            "blocked_apps": as_list(t.get("blocked_apps")),
            "expected_output": task_text(t.get("expected_output")),
            "acceptance": task_text(t.get("acceptance")),
            "evidence_mode": task_text(t.get("evidence_mode")) or ("none" if task_text(t.get("type")) == "behavior" else "optional"),
            "verification_mode": task_text(t.get("verification_mode")) or ("strict" if task_text(t.get("type")) == "challenge" else "light"),
            "milestone": task_text(t.get("milestone")),
            "depends_on": as_list(t.get("depends_on")),
            "evidence": as_list(t.get("evidence")),
            "app_reason": task_text(t.get("app_reason")),
            "app_confidence": app_confidence(t.get("app_confidence", 0)),
            "acceptance_result": t.get("acceptance_result") if isinstance(t.get("acceptance_result"), dict) else {},
            "difficulty": max(1, min(5, difficulty)),
            "source": task_text(t.get("source")) or "manual",
            "locked": bool(t.get("locked", False)),
            "created_at": task_text(t.get("created_at")) or datetime.now().isoformat(),
            "started_at": task_text(t.get("started_at")),
            "completed_at": task_text(t.get("completed_at")),
            "attempts": _nat(t.get("attempts")),
            "actual_minutes": _nat(t.get("actual_minutes")),
            "ended_at": task_text(t.get("ended_at")),
            "continuation_note": task_text(t.get("continuation_note")),
            "next_action": task_text(t.get("next_action")),
            "adjustment_reason": task_text(t.get("adjustment_reason")),
            "skill_id": task_text(t.get("skill_id") or t.get("knowledge_component")),
            "prerequisites": as_list(t.get("prerequisites")),
            "learning_task_type": task_text(t.get("learning_task_type")),
            "review_due_at": task_text(t.get("review_due_at")),
            "recall_rating": task_text(t.get("recall_rating")).lower(),
        }
    title = task_text(t)
    return {
        "id": new_id("task"), "goal_id": str(goal_id), "title": title, "text": title,
        "description": "", "type": "practice", "role": "secondary",
        "status": "done" if done else "pending", "estimated_minutes": 30,
        "required_apps": [], "allowed_apps": [], "blocked_apps": [],
        "expected_output": "", "acceptance": "", "evidence_mode": "optional", "verification_mode": "light", "milestone": "", "depends_on": [],
        "evidence": "", "app_reason": "", "app_confidence": 0,
        "acceptance_result": {}, "difficulty": 2, "source": "legacy", "locked": False,
        "created_at": datetime.now().isoformat(), "started_at": "", "completed_at": "",
        "attempts": 0, "actual_minutes": 0, "ended_at": "", "continuation_note": "", "next_action": "", "adjustment_reason": "",
        "skill_id": "", "prerequisites": [], "learning_task_type": "", "review_due_at": "",
        "recall_rating": "",
    }


def normalize_tasks(tasks, goal_id="", flags=None):
    flags = flags or []
    out = []
    for i, t in enumerate(tasks or []):
        if not task_text(t): continue
        out.append(normalize_task(t, goal_id, i, flags[i] if i < len(flags) else False))
    return out


def task_items(tasks, flags=None):
    flags = flags or []
    out = []
    for i, t in enumerate(tasks):
        nt = normalize_task(t, "", i, flags[i] if i < len(flags) else False)
        nt["done"] = task_done(nt, flags[i] if i < len(flags) else False)
        nt["text"] = nt.get("title") or "--"
        nt["next_action"] = ("提交交付物并进行验收" if nt["status"] == "doing" else "开始：" + nt["text"]) if not nt["done"] and nt["status"] not in ("skipped", "deferred") else ""
        out.append(nt)
    return out


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def today():
    return date.today().isoformat()


def min_of(hhmm):
    try:
        h, m = [int(x) for x in str(hhmm).split(":", 1)]
        return max(0, min(24 * 60, h * 60 + m))
    except Exception:
        return 9 * 60


def hhmm(m):
    m = max(0, min(24 * 60 - 1, int(m)))
    return "{:02d}:{:02d}".format(m // 60, m % 60)


# ---------------------------------------------------------------------------
# Shell / JSON helpers
# ---------------------------------------------------------------------------

def shq(s):
    return "'" + str(s).replace("'", "'\"'\"'") + "'"


def pt():
    t = _env_read("PCSTATS_TOKEN")
    return t if t else "pcstats2026"


def ej(t):
    """Extract JSON from text (direct parse, markdown-unwrap, regex)."""
    for s in [t, t.rstrip("`").removeprefix("```json").removeprefix("```").lstrip()]:
        if s:
            try: return json.loads(s)
            except json.JSONDecodeError: pass
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if m:
        try: return json.loads(m.group())
        except json.JSONDecodeError: pass
    raise ValueError("bad json: " + t[:200])


# ---------------------------------------------------------------------------
# .env reader (used by pt() and aiprovider)
# ---------------------------------------------------------------------------

def _env_read(name):
    """Read a value from .env files (search order: ~/.hermes/.env, ~/AppData/Local/hermes/.env, <cwd>/.env)."""
    for p in [
        os.path.expanduser("~/.hermes/.env"),
        os.path.expanduser("~/AppData/Local/hermes/.env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
    ]:
        try:
            with open(p, encoding="utf-8") as f:
                for ln in f:
                    if name.upper() in ln.upper():
                        v = ln.split("=", 1)[1].strip().strip("'\"")
                        if v: return v
        except Exception: pass
    return ""


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== utils.py self-test ===")
    assert task_text("hello") == "hello"
    assert task_text({"text": "world"}) == "world"
    assert task_text("none") == ""
    assert value_text("x") == "x"
    assert value_text({"x": 1}) == ""
    assert len(new_id()) > 10
    assert as_list("a") == ["a"]
    assert as_list(["a", "b"]) == ["a", "b"]
    assert min_of("09:30") == 570
    assert hhmm(570) == "09:30"
    assert shq("test") == "'test'"
    assert today() == date.today().isoformat()
    nt = normalize_task({"text": "Hello", "estimated_minutes": 60})
    assert nt["title"] == "Hello"
    assert nt["estimated_minutes"] == 60
    items = task_items([{"text": "A", "done": True}, {"text": "B"}], [True, False])
    assert len(items) == 2
    assert items[0]["done"] is True
    assert items[1]["done"] is False
    assert task_items([{"text": "A", "status": "pending"}], [True])[0]["done"] is True
    print("All tests passed!")
