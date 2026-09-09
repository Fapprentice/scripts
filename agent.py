"""Bounded Task Verge agent runtime.

The model may propose one typed action per step; this module owns validation,
step limits, retries, pauses and the audit trail.  Side effects stay in the
host application's tool callbacks.
"""
import copy
import threading
import time
import uuid
from dataclasses import dataclass, field

STATUSES = {"planning", "awaiting_confirmation", "executing", "observing",
            "verifying", "paused", "completed", "failed", "blocked"}
SAFE_ACTIONS = {
    "observe", "open_app", "focus_window", "read_file", "list_files",
    "run_check", "upload_evidence", "set_task_status", "request_confirmation",
    "complete_task", "pause", "finish",
}
CONFIRM_ACTIONS = {"write_file", "delete_file", "run_command", "permanent_allow", "request_confirmation"}


@dataclass
class Action:
    name: str
    args: dict = field(default_factory=dict)
    reason: str = ""
    requires_confirmation: bool = False

    def as_dict(self):
        return {"name": self.name, "args": self.args, "reason": self.reason,
                "requires_confirmation": self.requires_confirmation}


@dataclass
class AgentRun:
    run_id: str
    goal_id: str
    task_id: str
    status: str = "planning"
    step: int = 0
    max_steps: int = 20
    retry: int = 0
    max_retries: int = 2
    current_action: dict = field(default_factory=dict)
    observations: list = field(default_factory=list)
    artifacts: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    history: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    revision: int = 0

    def snapshot(self):
        return copy.deepcopy(self.__dict__)


class AgentError(Exception):
    pass


class AgentOrchestrator:
    """One bounded observe/decide/execute/verify loop."""

    def __init__(self, *, load_state, save_state, tools=None, planner=None, atomic_save=None, atomic_pause=None):
        self.load_state = load_state
        self.save_state = save_state
        self.tools = tools or {}
        self.planner = planner
        self.atomic_save = atomic_save
        self.atomic_pause = atomic_pause
        self._state_lock = threading.RLock()

    def start(self, goal_id, task, max_steps=20):
        run = AgentRun(uuid.uuid4().hex, str(goal_id or ""),
                       str(task.get("id") or task.get("title") or ""),
                       max_steps=max(1, min(50, int(max_steps or 20))))
        self._put(run)
        return run.snapshot()

    def get(self, run_id):
        with self._state_lock:
            raw = (self.load_state() or {}).get(run_id)
        if not raw:
            return None
        return AgentRun(**{k: raw[k] for k in AgentRun.__dataclass_fields__ if k in raw})

    def stop(self, run_id, reason="user paused"):
        if self.atomic_pause:
            try:
                paused = self.atomic_pause(run_id, reason)
            except Exception:
                paused = None
            if isinstance(paused, dict) and paused.get("status") == "paused":
                return (self.get(run_id) or AgentRun(**{
                    key: paused[key] for key in AgentRun.__dataclass_fields__ if key in paused
                })).snapshot()
        # A stop request is a user intent: refresh after a lost CAS and retry
        # the small state transition, without holding a planner-wide lock.
        for _ in range(3):
            run = self._required(run_id)
            run.status = "paused"
            if reason and reason not in run.errors:
                run.errors.append(reason)
            if self._put(run):
                return (self.get(run_id) or run).snapshot()
        latest = self.get(run_id) or run
        if latest.status != "paused":
            raise AgentError("stop could not be persisted; the run changed concurrently")
        return latest.snapshot()

    def resume(self, run_id):
        run = self._required(run_id)
        if run.status not in {"paused", "awaiting_confirmation"}:
            raise AgentError("run is not resumable")
        run.status = "planning"; run.updated_at = time.time()
        if not self._put(run): return (self.get(run_id) or run).snapshot()
        return self.step(run_id)

    def confirm(self, run_id):
        run = self._required(run_id)
        if run.status != "awaiting_confirmation":
            raise AgentError("run is not awaiting confirmation")
        action = Action(**run.current_action)
        self._validate(action); run.status = "executing"
        if not self._is_current(run): return (self.get(run_id) or run).snapshot()
        try:
            result=self._execute(action)
            run.history.append({"step":run.step+1,"action":action.as_dict(),"result":result,"ts":time.time()})
            run.step += 1; run.current_action={}; run.retry=0
            run.status="completed" if self._finished(run,result) else ("paused" if result.get("paused") else "planning")
            return (self.get(run_id) if not self._put(run) else run).snapshot()
        except Exception as exc:
            run.errors.append(str(exc)); run.status="failed"; self._put(run); return (self.get(run_id) or run).snapshot()

    def step(self, run_id):
        run = self._required(run_id)
        if run.status in {"completed", "failed", "blocked", "paused"}:
            return run.snapshot()
        if run.step >= run.max_steps:
            run.status = "blocked"; run.errors.append("agent step limit reached")
            self._put(run); return run.snapshot()
        try:
            run.status = "planning"
            observation = self._observe(run)
            run.observations.append(observation)
            action = self._plan(run, observation)
            self._validate(action)
            if not self._is_current(run): return (self.get(run_id) or run).snapshot()
            run.current_action = action.as_dict()
            if action.requires_confirmation or action.name in CONFIRM_ACTIONS:
                run.status = "awaiting_confirmation"
                if not self._put(run): return (self.get(run_id) or run).snapshot()
                return run.snapshot()
            run.status = "executing"
            result = self._execute(action)
            run.history.append({"step": run.step + 1, "action": action.as_dict(),
                                "result": result, "ts": time.time()})
            run.step += 1; run.retry = 0; run.status = "verifying"
            if result.get("paused"):
                run.status = "paused"
            elif result.get("requires_confirmation"):
                run.status = "awaiting_confirmation"
            elif self._finished(run, result):
                run.status = "completed"
            else:
                run.status = "planning"
            if not self._put(run): return (self.get(run_id) or run).snapshot()
            return run.snapshot()
        except Exception as exc:
            run.retry += 1; run.errors.append(str(exc))
            run.status = "planning" if run.retry <= run.max_retries else "failed"
            self._put(run); return (self.get(run_id) or run).snapshot()

    def _observe(self, run):
        fn = self.tools.get("observe")
        return fn(run.snapshot()) if fn else {}

    def _is_current(self, run):
        with self._state_lock:
            raw = (self.load_state() or {}).get(run.run_id)
        return bool(raw and raw.get("revision", 0) == run.revision and raw.get("status") not in {"paused", "completed", "failed", "blocked"})

    def _plan(self, run, observation):
        if self.planner:
            raw = self.planner(run.snapshot(), observation)
            if isinstance(raw, Action): return raw
            if isinstance(raw, dict): return Action(str(raw.get("name", "observe")), raw.get("args") or {}, str(raw.get("reason", "")), bool(raw.get("requires_confirmation")))
        # Safe deterministic fallback: observation may nominate the next tool.
        suggested = observation.get("next_action") if isinstance(observation, dict) else None
        if isinstance(suggested, dict):
            return Action(str(suggested.get("name", "observe")), suggested.get("args") or {}, str(suggested.get("reason", "")))
        return Action("observe", {}, "等待下一次状态观察")

    def _validate(self, action):
        if action.name not in SAFE_ACTIONS and action.name not in CONFIRM_ACTIONS:
            raise AgentError("unsupported agent action: " + action.name)
        if not isinstance(action.args, dict):
            raise AgentError("action args must be an object")

    def _execute(self, action):
        fn = self.tools.get(action.name)
        if not fn:
            if action.name == "observe": return {"ok": True}
            raise AgentError("tool unavailable: " + action.name)
        result = fn(action.args)
        return result if isinstance(result, dict) else {"ok": bool(result), "value": result}

    def _finished(self, run, result):
        return bool(result.get("finished")) if isinstance(result, dict) else False

    def _required(self, run_id):
        run = self.get(run_id)
        if not run: raise AgentError("agent run not found")
        return run

    def _put(self, run):
        if self.atomic_save:
            expected_revision = int(run.revision or 0)
            candidate = run.snapshot()
            candidate["revision"] = expected_revision + 1
            candidate["updated_at"] = time.time()
            if not self.atomic_save(candidate, expected_revision):
                return False
            run.revision = candidate["revision"]
            run.updated_at = candidate["updated_at"]
            return True
        with self._state_lock:
            data = self.load_state() or {}
            current = data.get(run.run_id)
            if current and current.get("revision", 0) != run.revision:
                return False
            run.revision = int(run.revision or 0) + 1
            run.updated_at = time.time()
            data[run.run_id] = run.snapshot()
            if len(data) > 100:
                keep = sorted(data.values(), key=lambda x: x.get("updated_at", 0), reverse=True)[:100]
                data.clear(); data.update({x["run_id"]: x for x in keep})
            self.save_state(data)
            return True
