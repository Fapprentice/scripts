"""Persistent companion growth for the global Dafeiyu fish.

SQLite companion tables are the source of truth. JSON documents may carry a
compatibility snapshot written in the same database, but growth is never read
back from that snapshot.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Callable

ENERGY_MIN, ENERGY_MAX = 0, 100
BOND_MIN, BOND_MAX = 0, 100
HP_MIN, HP_MAX = 0, 100
HUNGER_MIN, HUNGER_MAX = 0, 100
DEFAULT_ENERGY = 70
DEFAULT_BOND = 20
DEFAULT_HP = 100
DEFAULT_HUNGER = 70
REST_POINT = 50
SETTLE_FLOOR = 20
ENERGY_IDLE_STEP_SECONDS = 2 * 3600
ENERGY_IDLE_STEP = 2
ENERGY_CARE_STEP_SECONDS = 3 * 3600
ENERGY_CARE_STEP = 1
CARE_GAP_SECONDS = 18 * 3600
SLEEPY_ENERGY = 28
HUNGRY_THRESHOLD = 18
HUNGER_STEP_SECONDS = 3 * 3600
HUNGER_STEP = 4
STARVE_HP_STEP_SECONDS = 3 * 3600
STARVE_HP_STEP = 2
XP_BASE = 40
XP_STEP = 12
SPEND_COST = 10

POKE_LIMIT, FEED_LIMIT, TALK_LIMIT, REST_LIMIT = 8, 3, 6, 3
POKE_BOND_TIMES, TALK_BOND_TIMES = 3, 4
POKE_COOLDOWN, FEED_COOLDOWN, TALK_COOLDOWN = 20, 600, 30

TREATS = {
    "小鱼干": {"energy": 8, "bond": 2, "hunger": 18, "hp": 6, "xp": 4, "emote": "🐟"},
    "蛋糕": {"energy": 5, "bond": 1, "hunger": 12, "hp": 4, "xp": 3, "emote": "🍰"},
    "棒棒糖": {"energy": 4, "bond": 1, "hunger": 10, "hp": 3, "xp": 2, "emote": "🍭"},
}

PLAY = {
    "poke": {"kind": "poke", "emote": "💢", "ms": 1200},
    "feed": {"kind": "feed", "ms": 1800},
    "spend": {"kind": "spend", "emote": "🐟", "ms": 1800},
    "talk": {"kind": "talk", "emote": "💬", "ms": 2200},
    "celebrate": {"kind": "happy", "emote": "✨", "ms": 2500},
    "accepted": {"kind": "happy", "emote": "✨", "ms": 2500},
    "failed": {"kind": "cheer", "emote": "💪", "ms": 2000},
    "skipped": {"kind": "cheer", "emote": "💪", "ms": 2000},
    "partial": {"kind": "cheer", "emote": "💪", "ms": 2000},
}

USER_KINDS = {"poke", "feed", "talk", "celebrate", "spend"}
WORK_KINDS = {
    "focus_start", "focus_pause", "rest_start", "rest_end",
    "accepted", "failed", "skipped", "partial",
}

QUIT_REASON_MARKERS = ("收尾仪式", "quit_continue", "continue_15", "继续15", "继续 15")
QUIT_SOURCES = {"quit", "quit_continue", "continue_15"}


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(value)))


def bond_band(bond: int) -> str:
    if bond < 20:
        return "刚认识"
    if bond < 50:
        return "慢慢熟"
    if bond < 80:
        return "搭档"
    return "很熟"


def xp_to_next(level: int) -> int:
    return XP_BASE + max(0, int(level) - 1) * XP_STEP


def stage_for(level: int) -> str:
    if level >= 15:
        return "传说肥鱼"
    if level >= 10:
        return "大肥鱼"
    if level >= 5:
        return "肥鱼"
    return "鱼苗"


def _meta(row: dict) -> dict:
    payload = dict(row.get("payload") or {}) if isinstance(row.get("payload"), dict) else {}
    payload.setdefault("xp", 0)
    payload.setdefault("level", 1)
    payload.setdefault("stage", stage_for(int(payload.get("level") or 1)))
    payload.setdefault("hunger", DEFAULT_HUNGER)
    payload.setdefault("hp", DEFAULT_HP)
    payload.setdefault("fainted", False)
    return payload


def _parse_ts(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 1e12:
            number /= 1000.0
        return number
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        try:
            return float(text)
        except (TypeError, ValueError):
            return None


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat()


def _task_title(task: dict | None) -> str:
    if not isinstance(task, dict):
        return "当前任务"
    return str(task.get("text") or task.get("title") or "当前任务")


class CompanionService:
    """Day caps, cooldowns, settle, and explainable growth events."""

    def __init__(self, store, *, clock: Callable[[], float] | None = None):
        self.store = store
        self._clock = clock or (lambda: datetime.now().timestamp())
        self.last_apply: dict[str, Any] | None = None
        self._pending: tuple[str, dict, dict] | None = None
        self.store.ensure_companion()

    def _now(self) -> float:
        return float(self._clock())

    def _today(self, now: float | None = None) -> str:
        return datetime.fromtimestamp(self._now() if now is None else now).date().isoformat()

    def snapshot(self, state: dict | None = None) -> dict:
        state = state if isinstance(state, dict) else {}
        return self.store.mutate_companion(lambda row, txn: self._snapshot_with_row(row, txn, state))

    def apply(self, kind: str, payload: dict | None = None, state: dict | None = None, *, commit: bool = True) -> dict:
        state = state if isinstance(state, dict) else {}
        payload = payload if isinstance(payload, dict) else {}
        kind = str(kind or "").strip()
        if kind not in USER_KINDS and kind not in WORK_KINDS:
            result = {"ok": False, "applied": False, "message": "unknown kind", "reason": "未知的陪伴动作"}
            self.last_apply = result
            return result
        if not commit:
            self._pending = (kind, payload, state)
            result = {"ok": True, "applied": False, "deferred": True, "reason": "等待与任务状态同一次写盘"}
            self.last_apply = result
            return result
        result = self.store.mutate_companion(lambda row, txn: self._apply_with_row(row, txn, kind, payload, state))
        self.last_apply = result
        return result

    def pending_mutator(self):
        pending = self._pending
        if not pending:
            return None
        kind, payload, state = pending
        def mutator(row, txn):
            result = self._apply_with_row(row, txn, kind, payload, state)
            self.last_apply = result
            return result
        return mutator

    def clear_pending(self):
        self._pending = None

    def on_acceptance(self, state: dict, idx: int, result: dict | None, *, commit: bool = True) -> dict | None:
        result = result if isinstance(result, dict) else {}
        status = str(result.get("status") or "")
        if status == "needs_review":
            self.last_apply = None
            return None
        tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
        task = tasks[idx] if 0 <= idx < len(tasks) and isinstance(tasks[idx], dict) else {}
        task_id = str(task.get("id") or idx)
        acceptance_id = str(result.get("id") or task_id)
        payload = {
            "task_id": task_id,
            "goal_id": task.get("goal_id") or state.get("active_goal_id") or "",
            "acceptance_id": acceptance_id,
        }
        if status == "passed":
            return self.apply("accepted", payload, state, commit=commit)
        if status == "failed":
            return self.apply("failed", payload, state, commit=commit)
        return None

    def on_status(self, state: dict, idx: int, previous: str, status: str, *, commit: bool = True) -> dict | None:
        if status == previous:
            return None
        tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
        task = tasks[idx] if 0 <= idx < len(tasks) and isinstance(tasks[idx], dict) else {}
        payload = {
            "task_id": str(task.get("id") or idx),
            "goal_id": task.get("goal_id") or state.get("active_goal_id") or "",
        }
        if status == "doing":
            return self.apply("focus_start", payload, state, commit=commit)
        if status == "paused":
            return self.apply("focus_pause", payload, state, commit=commit)
        if status in ("skipped", "partial"):
            return self.apply(status, payload, state, commit=commit)
        return None

    def on_break_start(self, state: dict, item: dict, source: str = "user", *, commit: bool = True) -> dict | None:
        payload = dict(item or {})
        payload["source"] = payload.get("source") or source
        return self.apply("rest_start", payload, state, commit=commit)

    def on_break_end(self, state: dict, item: dict, *, commit: bool = True) -> dict | None:
        return self.apply("rest_end", dict(item or {}), state, commit=commit)

    def events(self, limit: int = 100) -> list:
        return self.store.list_companion_events(limit=limit)

    def _snapshot_with_row(self, row: dict, txn, state: dict) -> dict:
        row = self._load_settled(row, txn, state)
        return self._snapshot_from(row, state, txn)

    def _apply_with_row(self, row: dict, txn, kind: str, payload: dict, state: dict) -> dict:
        row = self._load_settled(row, txn, state)
        if kind == "poke":
            return self._apply_poke(row, txn, state)
        if kind == "feed":
            return self._apply_feed(row, txn, payload, state)
        if kind == "talk":
            return self._apply_talk(row, txn, state)
        if kind == "spend":
            return self._apply_spend(row, txn, payload, state)
        if kind == "celebrate":
            return self._apply_celebrate(row, txn, payload, state)
        if kind == "focus_start":
            return self._apply_focus_start(row, txn, payload, state)
        if kind == "focus_pause":
            return self._apply_focus_pause(row, txn, payload, state)
        if kind == "rest_start":
            return self._apply_rest_start(row, txn, payload, state)
        if kind == "rest_end":
            return self._apply_rest_end(row, txn, payload, state)
        if kind == "accepted":
            return self._apply_accepted(row, txn, payload, state)
        if kind == "failed":
            return self._apply_failed(row, txn, payload, state)
        if kind in ("skipped", "partial"):
            return self._apply_status(row, txn, kind, payload, state)
        return {"ok": False, "applied": False, "message": "unknown kind", "reason": "未知的陪伴动作"}

    def _load_settled(self, row: dict, txn, state: dict) -> dict:
        now = self._now()
        changed = self._rollover_day(row, now)
        changed = self._settle(row, state, now) or changed
        if changed:
            txn.write_companion(row)
        return row

    def _rollover_day(self, row: dict, now: float) -> bool:
        today = self._today(now)
        if row.get("day") == today:
            return False
        row["day"] = today
        row["poke_used"] = 0
        row["feed_used"] = 0
        row["talk_used"] = 0
        return True

    def _settle(self, row: dict, state: dict, now: float) -> bool:
        last = _parse_ts(row.get("last_settle_at")) or now
        if self._doing(state) or self._break_active(state, now):
            if now - last >= 60:
                row["last_settle_at"] = _iso(now)
                return True
            return False
        energy = int(row.get("energy") or 0)
        original = energy
        original_last = last
        while energy > REST_POINT and now - last >= ENERGY_IDLE_STEP_SECONDS:
            energy = max(REST_POINT, energy - ENERGY_IDLE_STEP)
            last += ENERGY_IDLE_STEP_SECONDS
        feed_at = _parse_ts(row.get("last_feed_at")) or 0.0
        rest_at = _parse_ts(row.get("last_rest_start_at")) or 0.0
        if now - feed_at >= CARE_GAP_SECONDS and now - rest_at >= CARE_GAP_SECONDS:
            while energy > SETTLE_FLOOR and now - last >= ENERGY_CARE_STEP_SECONDS:
                energy -= ENERGY_CARE_STEP
                last += ENERGY_CARE_STEP_SECONDS
        payload = _meta(row)
        hunger = int(payload.get("hunger") or DEFAULT_HUNGER)
        hp = int(payload.get("hp") or DEFAULT_HP)
        original_hunger, original_hp = hunger, hp
        care_gap = now - feed_at >= CARE_GAP_SECONDS and now - rest_at >= CARE_GAP_SECONDS
        if care_gap:
            cursor = original_last
            while hunger > 0 and now - cursor >= HUNGER_STEP_SECONDS:
                hunger = max(HUNGER_MIN, hunger - HUNGER_STEP)
                cursor += HUNGER_STEP_SECONDS
            if hunger <= HUNGRY_THRESHOLD:
                cursor = original_last
                while hp > HP_MIN and now - cursor >= STARVE_HP_STEP_SECONDS:
                    hp = max(HP_MIN, hp - STARVE_HP_STEP)
                    cursor += STARVE_HP_STEP_SECONDS
        payload["hunger"] = clamp(hunger, HUNGER_MIN, HUNGER_MAX)
        payload["hp"] = clamp(hp, HP_MIN, HP_MAX)
        payload["fainted"] = payload["hp"] <= 0
        row["payload"] = payload
        if energy == original and last == original_last and hunger == original_hunger and hp == original_hp:
            return False
        row["energy"] = clamp(energy, ENERGY_MIN, ENERGY_MAX)
        row["last_settle_at"] = _iso(last)
        return True

    def _apply_poke(self, row: dict, txn, state: dict) -> dict:
        now = self._now()
        cooling = self._cooldown_reason(row.get("last_poke_at"), POKE_COOLDOWN, now, "等一下再戳。我又不会跑。")
        if cooling:
            return self._denied(row, txn, state, "poke", cooling, play="poke")
        used = int(row.get("poke_used") or 0)
        if used >= POKE_LIMIT:
            return self._finish(
                row, txn, state, kind="poke", applied=False, reason="今天戳够了。动画还能看，养成到此为止。",
                play="poke", write_event=True,
            )
        used += 1
        row["poke_used"] = used
        row["last_poke_at"] = _iso(now)
        delta_bond = 1 if used <= POKE_BOND_TIMES else 0
        if delta_bond:
            reason = "戳了一下，默契 +1"
        else:
            reason = "戳了一下，今天默契已经够意思了"
        return self._grow(row, txn, state, kind="poke", delta_energy=0, delta_bond=delta_bond, delta_xp=1 if delta_bond else 0, reason=reason, play="poke")

    def _apply_feed(self, row: dict, txn, payload: dict, state: dict) -> dict:
        treat = str(payload.get("treat") or "").strip()
        spec = TREATS.get(treat)
        if not spec:
            result = {"ok": False, "applied": False, "message": "unknown treat", "reason": "未知零食"}
            return result
        now = self._now()
        cooling = self._cooldown_reason(row.get("last_feed_at"), FEED_COOLDOWN, now, "还在嚼。过几分钟再喂。")
        if cooling:
            return self._denied(row, txn, state, "feed", cooling, play="feed", treat=treat, emote=spec["emote"])
        used = int(row.get("feed_used") or 0)
        if used >= FEED_LIMIT:
            return self._finish(
                row, txn, state, kind="feed", applied=False, reason="零食今日额度用完了。不是没库存，是今天喂够了。",
                play="feed", treat=treat, emote=spec["emote"], write_event=True,
            )
        row["feed_used"] = used + 1
        row["last_feed_at"] = _iso(now)
        reason = "喂了{}，精力 +{}，默契 +{}".format(treat, spec["energy"], spec["bond"])
        return self._grow(
            row, txn, state, kind="feed", delta_energy=spec["energy"], delta_bond=spec["bond"],
            delta_hunger=spec["hunger"], delta_hp=spec["hp"], delta_xp=spec["xp"],
            reason=reason, play="feed", treat=treat, emote=spec["emote"],
        )

    def _apply_talk(self, row: dict, txn, state: dict) -> dict:
        now = self._now()
        cooling = self._cooldown_reason(row.get("last_talk_at"), TALK_COOLDOWN, now, "让我想想下句毒舌……")
        if cooling:
            return self._denied(row, txn, state, "talk", cooling, play="talk")
        used = int(row.get("talk_used") or 0)
        if used >= TALK_LIMIT:
            return self._finish(
                row, txn, state, kind="talk", applied=False, reason="今天话够多了。去干活，我看着。",
                play="talk", write_event=True,
            )
        used += 1
        row["talk_used"] = used
        row["last_talk_at"] = _iso(now)
        delta_bond = 1 if used <= TALK_BOND_TIMES else 0
        reason = "说了句话，默契 +1" if delta_bond else "说了句话，今天默契已经够意思了"
        return self._grow(row, txn, state, kind="talk", delta_energy=0, delta_bond=delta_bond, delta_xp=1 if delta_bond else 0, reason=reason, play="talk")

    def _apply_spend(self, row: dict, txn, payload: dict, state: dict) -> dict:
        motivation = state.get("motivation") if isinstance(state.get("motivation"), dict) else {}
        points = int(motivation.get("points") or 0)
        if points < SPEND_COST:
            return self._denied(row, txn, state, "spend", "积分不够 10 点，先把一件事做对。")
        motivation["points"] = points - SPEND_COST
        state["motivation"] = motivation
        history = list(motivation.get("history") or [])
        history.append({"ts": _iso(self._now()), "outcome": "spend", "points": -SPEND_COST, "reason": "用积分加餐"})
        motivation["history"] = history[-40:]
        return self._grow(
            row, txn, state, kind="spend", delta_energy=10, delta_bond=1, delta_hunger=20, delta_hp=8, delta_xp=5,
            reason="花 10 积分加餐，精力 +10", play="feed", treat="小鱼干", emote="🐟", source="user",
        )

    def _apply_celebrate(self, row: dict, txn, payload: dict, state: dict) -> dict:
        acceptance_id = str(payload.get("acceptance_id") or row.get("payload", {}).get("last_accepted_id") or "")
        if not acceptance_id:
            return self._denied(row, txn, state, "celebrate", "过了再庆祝。没有证据的开心，我不认。", play="celebrate")
        key = "celebrate:" + acceptance_id
        if txn.find_companion_event(key):
            return self._denied(row, txn, state, "celebrate", "过了就过了，别让我再核一次。", play="celebrate")
        return self._grow(
            row, txn, state, kind="celebrate", delta_energy=0, delta_bond=0,
            reason="庆祝通过，养成已在验收时入账", play="celebrate",
            dedupe_key=key, extra={"acceptance_id": acceptance_id},
        )

    def _apply_focus_start(self, row: dict, txn, payload: dict, state: dict) -> dict:
        task_id = str(payload.get("task_id") or "")
        day = row.get("day") or self._today()
        key = "focus:{}:{}".format(task_id, day)
        if txn.find_companion_event(key):
            return self._denied(row, txn, state, "focus_start", "今天这份专注已经记过默契了")
        return self._grow(
            row, txn, state, kind="focus_start", delta_energy=0, delta_bond=3, delta_xp=6,
            reason="开始专注当前任务，默契 +3",
            dedupe_key=key, task_id=task_id, goal_id=payload.get("goal_id"),
            source="task",
        )

    def _apply_focus_pause(self, row: dict, txn, payload: dict, state: dict) -> dict:
        return self._grow(
            row, txn, state, kind="focus_pause", delta_energy=0, delta_bond=0,
            reason="暂停专注，养成不变",
            task_id=payload.get("task_id"), goal_id=payload.get("goal_id"),
            source="task",
        )

    def _apply_rest_start(self, row: dict, txn, payload: dict, state: dict) -> dict:
        if not self._is_growth_rest(payload):
            return self._denied(row, txn, state, "rest_start", "这次休息不记养成")
        ts = str(payload.get("ts") or _iso(self._now()))
        key = "rest_start:" + ts
        if txn.find_companion_event(key):
            return self._denied(row, txn, state, "rest_start", "这段休息已经记过了")
        row["last_rest_start_at"] = ts if _parse_ts(ts) else _iso(self._now())
        return self._grow(
            row, txn, state, kind="rest_start", delta_energy=6, delta_bond=0, delta_hunger=4, delta_hp=2,
            reason="用户休息开始，精力 +6",
            dedupe_key=key, source=str(payload.get("source") or "user"),
            extra={"break_ts": ts},
        )

    def _apply_rest_end(self, row: dict, txn, payload: dict, state: dict) -> dict:
        ts = str(payload.get("ts") or "")
        if not ts:
            return self._denied(row, txn, state, "rest_end", "没有对应的休息")
        start_key = "rest_start:" + ts
        if not txn.find_companion_event(start_key):
            return self._denied(row, txn, state, "rest_end", "这段休息开始时未记养成")
        end_key = "rest_end:" + ts
        if txn.find_companion_event(end_key):
            return self._denied(row, txn, state, "rest_end", "这段休息结束已经记过了")
        start = _parse_ts(ts) or self._now()
        end = _parse_ts(payload.get("until")) or self._now()
        minutes = max(0.0, (end - start) / 60.0)
        delta_energy = 4 if minutes >= 4 else 0
        delta_bond = 1 if minutes >= 5 else 0
        if minutes >= 5:
            reason = "休息结束满 5 分钟，精力 +4，默契 +1"
        elif minutes >= 4:
            reason = "休息结束满 4 分钟，精力 +4"
        else:
            reason = "休息结束不到 4 分钟，开始那笔精力还在，结束不再加"
        return self._grow(
            row, txn, state, kind="rest_end", delta_energy=delta_energy, delta_bond=delta_bond,
            delta_hp=2 if minutes >= 4 else 0, delta_xp=2 if minutes >= 5 else 0,
            reason=reason, dedupe_key=end_key, source=str(payload.get("source") or "user"),
            extra={"break_ts": ts, "minutes": round(minutes, 3)},
        )

    def _apply_accepted(self, row: dict, txn, payload: dict, state: dict) -> dict:
        acceptance_id = str(payload.get("acceptance_id") or payload.get("task_id") or "")
        key = "accepted:" + acceptance_id
        if txn.find_companion_event(key):
            return self._denied(row, txn, state, "accepted", "这次通过已经记过养成")
        extra = dict(row.get("payload") or {})
        extra["last_accepted_id"] = acceptance_id
        extra["last_accepted_at"] = _iso(self._now())
        row["payload"] = extra
        return self._grow(
            row, txn, state, kind="accepted", delta_energy=6, delta_bond=8, delta_xp=18, delta_hp=4,
            reason="验收通过，精力 +6，默契 +8",
            play="accepted", dedupe_key=key,
            task_id=payload.get("task_id"), goal_id=payload.get("goal_id"),
            source="acceptance", extra={"acceptance_id": acceptance_id},
        )

    def _apply_failed(self, row: dict, txn, payload: dict, state: dict) -> dict:
        acceptance_id = str(payload.get("acceptance_id") or payload.get("task_id") or "")
        key = "failed:" + acceptance_id
        if txn.find_companion_event(key):
            return self._denied(row, txn, state, "failed", "这次失败已经记过养成")
        return self._grow(
            row, txn, state, kind="failed", delta_energy=0, delta_bond=0, delta_hp=-4, delta_hunger=-6,
            reason="验收没过，默契不扣，掉一点血和饱食",
            play="failed", dedupe_key=key,
            task_id=payload.get("task_id"), goal_id=payload.get("goal_id"),
            source="acceptance", extra={"acceptance_id": acceptance_id},
        )

    def _apply_status(self, row: dict, txn, kind: str, payload: dict, state: dict) -> dict:
        task_id = str(payload.get("task_id") or "")
        day = row.get("day") or self._today()
        key = "status:{}:{}:{}".format(task_id, kind, day)
        if txn.find_companion_event(key):
            return self._denied(row, txn, state, kind, "这个状态今天已经记过养成")
        if kind == "skipped":
            reason = "任务跳过，默契不扣，掉一点血和饱食"
            hp, hunger = -3, -4
        else:
            reason = "任务部分完成，默契不扣，掉一点血和饱食"
            hp, hunger = -2, -3
        return self._grow(
            row, txn, state, kind=kind, delta_energy=0, delta_bond=0, delta_hp=hp, delta_hunger=hunger, reason=reason, play=kind,
            dedupe_key=key, task_id=task_id, goal_id=payload.get("goal_id"), source="task",
        )

    def _grow(
        self, row: dict, txn, state: dict, *, kind: str, delta_energy: int, delta_bond: int,
        reason: str, play: str | None = None, treat: str | None = None, emote: str | None = None,
        dedupe_key: str | None = None, task_id: Any = None, goal_id: Any = None,
        source: str = "user", extra: dict | None = None, applied: bool = True,
        delta_xp: int = 0, delta_hp: int = 0, delta_hunger: int = 0,
    ) -> dict:
        if dedupe_key and txn.find_companion_event(dedupe_key):
            return self._denied(row, txn, state, kind, reason or "已经记过了", play=play, treat=treat, emote=emote)
        before_energy = clamp(int(row.get("energy") or 0), ENERGY_MIN, ENERGY_MAX)
        before_bond = clamp(int(row.get("bond") or 0), BOND_MIN, BOND_MAX)
        after_energy = clamp(before_energy + int(delta_energy or 0), ENERGY_MIN, ENERGY_MAX)
        after_bond = clamp(before_bond + int(delta_bond or 0), BOND_MIN, BOND_MAX)
        actual_energy = after_energy - before_energy
        actual_bond = after_bond - before_bond
        row["energy"] = after_energy
        row["bond"] = after_bond
        extra = dict(extra or {})
        extra.update(self._apply_progression(row, delta_xp=delta_xp, delta_hp=delta_hp, delta_hunger=delta_hunger))
        if extra.get("leveled"):
            reason = reason + "，升级到 Lv{}（{}）".format(extra.get("level"), extra.get("stage"))
            play = play or "accepted"
        if extra.get("evolved"):
            reason = reason + "，进化成{}".format(extra.get("stage"))
        if extra.get("fainted") and int(delta_hp or 0) < 0:
            reason = reason + "，暂时趴下了，喂食或休息能爬起来"
        if actual_energy != int(delta_energy or 0) or actual_bond != int(delta_bond or 0):
            reason = self._actual_reason(reason, actual_energy, actual_bond)
        event = self._event(
            kind, reason, actual_energy, actual_bond, treat=treat, dedupe_key=dedupe_key,
            task_id=task_id, goal_id=goal_id, source=source, extra=extra,
        )
        txn.write_companion(row, event)
        return self._result(row, txn, state, True, True, actual_energy, actual_bond, reason, play=play, treat=treat, emote=emote)

    def _apply_progression(self, row: dict, *, delta_xp=0, delta_hp=0, delta_hunger=0) -> dict:
        payload = _meta(row)
        before_level = int(payload.get("level") or 1)
        before_stage = stage_for(before_level)
        xp = max(0, int(payload.get("xp") or 0) + int(delta_xp or 0))
        level = before_level
        while xp >= xp_to_next(level):
            xp -= xp_to_next(level)
            level += 1
        hunger = clamp(int(payload.get("hunger") or DEFAULT_HUNGER) + int(delta_hunger or 0), HUNGER_MIN, HUNGER_MAX)
        hp = clamp(int(payload.get("hp") or DEFAULT_HP) + int(delta_hp or 0), HP_MIN, HP_MAX)
        if hunger >= 40 and hp < HP_MAX and int(delta_hunger or 0) > 0:
            hp = clamp(hp + 1, HP_MIN, HP_MAX)
        if hp > 0:
            payload["fainted"] = False
        else:
            payload["fainted"] = True
        payload["xp"] = xp
        payload["level"] = level
        payload["stage"] = stage_for(level)
        payload["hunger"] = hunger
        payload["hp"] = hp
        row["payload"] = payload
        return {
            "xp": xp,
            "level": level,
            "stage": payload["stage"],
            "hunger": hunger,
            "hp": hp,
            "fainted": payload["fainted"],
            "delta_xp": int(delta_xp or 0),
            "delta_hp": int(delta_hp or 0),
            "delta_hunger": int(delta_hunger or 0),
            "leveled": level > before_level,
            "evolved": payload["stage"] != before_stage,
        }

    @staticmethod
    def _actual_reason(reason: str, energy: int, bond: int) -> str:
        parts = []
        if energy:
            parts.append("精力 {:+d}".format(energy))
        if bond:
            parts.append("默契 {:+d}".format(bond))
        if not parts:
            return reason.split("，")[0] + "，已到上限，实际不再增加"
        prefix = reason.split("，")[0]
        return "{}，{}".format(prefix, "，".join(parts))

    def _finish(
        self, row: dict, txn, state: dict, *, kind: str, applied: bool, reason: str,
        play: str | None = None, treat: str | None = None, emote: str | None = None,
        write_event: bool = False,
    ) -> dict:
        event = None
        if write_event:
            event = self._event(kind, reason, 0, 0, treat=treat, source="user")
        txn.write_companion(row, event)
        return self._result(row, txn, state, True, applied, 0, 0, reason, play=play, treat=treat, emote=emote)

    def _denied(
        self, row: dict, txn, state: dict, kind: str, reason: str, *, play: str | None = None,
        treat: str | None = None, emote: str | None = None,
    ) -> dict:
        return self._result(row, txn, state, True, False, 0, 0, reason, play=play, treat=treat, emote=emote)

    def _result(
        self, row: dict, txn, state: dict, ok: bool, applied: bool, delta_energy: int, delta_bond: int,
        reason: str, *, play: str | None = None, treat: str | None = None, emote: str | None = None,
    ) -> dict:
        hint = self._play_hint(play, treat=treat, emote=emote) if play else None
        return {
            "ok": ok,
            "applied": applied,
            "delta_energy": int(delta_energy or 0),
            "delta_bond": int(delta_bond or 0),
            "reason": reason,
            "snapshot": self._snapshot_from(row, state, txn),
            "play_hint": hint,
        }

    def _event(
        self, kind: str, reason: str, delta_energy: int, delta_bond: int, *, treat=None,
        dedupe_key=None, task_id=None, goal_id=None, source="user", extra=None,
    ) -> dict:
        now = self._now()
        payload = dict(extra or {})
        return {
            "id": uuid.uuid4().hex,
            "ts": _iso(now),
            "kind": kind,
            "treat": treat,
            "delta_energy": int(delta_energy or 0),
            "delta_bond": int(delta_bond or 0),
            "reason": reason,
            "task_id": str(task_id) if task_id else None,
            "goal_id": str(goal_id) if goal_id else None,
            "dedupe_key": dedupe_key,
            "source": source,
            "payload": payload,
        }

    def _play_hint(self, kind: str | None, treat: str | None = None, emote: str | None = None) -> dict | None:
        if not kind:
            return None
        base = dict(PLAY.get(kind) or {"kind": kind, "ms": 1600})
        if treat:
            base["treat"] = treat
            base["emote"] = emote or TREATS.get(treat, {}).get("emote") or base.get("emote")
        elif emote:
            base["emote"] = emote
        return base

    def _cooldown_reason(self, last_at, seconds: int, now: float, message: str) -> str | None:
        last = _parse_ts(last_at)
        if last is None:
            return None
        if now - last < seconds:
            return message
        return None

    def _snapshot_from(self, row: dict, state: dict, txn=None) -> dict:
        now = self._now()
        energy = clamp(row.get("energy") or 0, ENERGY_MIN, ENERGY_MAX)
        bond = clamp(row.get("bond") or 0, BOND_MIN, BOND_MAX)
        payload = _meta(row)
        mood, mood_label, line = self._mood(row, state, energy, now, txn)
        last = txn.last_event() if txn is not None else self.store.last_companion_event()
        last_event = None
        if last:
            last_event = {
                "kind": last.get("kind"),
                "reason": last.get("reason"),
                "delta_energy": last.get("delta_energy"),
                "delta_bond": last.get("delta_bond"),
                "ts": last.get("ts"),
            }
        today = row.get("day") or self._today(now)
        rest_used = 0
        for item in state.get("breaks") or []:
            if isinstance(item, dict) and str(item.get("date") or "")[:10] == today:
                rest_used += 1
        poke_used = int(row.get("poke_used") or 0)
        feed_used = int(row.get("feed_used") or 0)
        talk_used = int(row.get("talk_used") or 0)
        accepted_id = (row.get("payload") or {}).get("last_accepted_id")
        finder = txn.find_companion_event if txn is not None else self.store.find_companion_event
        can_celebrate = bool(accepted_id) and not finder("celebrate:" + str(accepted_id))
        return {
            "id": row.get("id") or "dafeiyu",
            "name": row.get("name") or "大肥鱼",
            "energy": energy,
            "bond": bond,
            "energy_max": ENERGY_MAX,
            "bond_max": BOND_MAX,
            "hp": int(payload.get("hp") or DEFAULT_HP),
            "hp_max": HP_MAX,
            "hunger": int(payload.get("hunger") or DEFAULT_HUNGER),
            "hunger_max": HUNGER_MAX,
            "xp": int(payload.get("xp") or 0),
            "xp_to_next": xp_to_next(int(payload.get("level") or 1)),
            "level": int(payload.get("level") or 1),
            "stage": payload.get("stage") or stage_for(int(payload.get("level") or 1)),
            "fainted": bool(payload.get("fainted")),
            "spend_cost": SPEND_COST,
            "points": int((state.get("motivation") or {}).get("points") or 0) if isinstance(state.get("motivation"), dict) else 0,
            "mood": mood,
            "mood_label": mood_label,
            "bond_band": bond_band(bond),
            "line": line,
            "today": {
                "date": today,
                "poke_used": poke_used, "poke_limit": POKE_LIMIT,
                "feed_used": feed_used, "feed_limit": FEED_LIMIT,
                "talk_used": talk_used, "talk_limit": TALK_LIMIT,
                "rest_used": rest_used, "rest_limit": REST_LIMIT,
            },
            "cooldowns": {
                "poke_until": self._until(row.get("last_poke_at"), POKE_COOLDOWN, now),
                "feed_until": self._until(row.get("last_feed_at"), FEED_COOLDOWN, now),
                "talk_until": self._until(row.get("last_talk_at"), TALK_COOLDOWN, now),
            },
            "last_event": last_event,
            "can_celebrate": can_celebrate,
            "last_accepted_id": accepted_id,
        }

    def _until(self, last_at, seconds: int, now: float) -> str | None:
        last = _parse_ts(last_at)
        if last is None:
            return None
        until = last + seconds
        if until <= now:
            return None
        return _iso(until)

    def _mood(self, row: dict, state: dict, energy: int, now: float, txn=None) -> tuple[str, str, str]:
        doing = self._doing(state)
        if doing:
            title = _task_title(doing)
            return "focus", "专注中", "正在做：{}。提交可检查结果后我会高兴——标准不会因此变松。".format(title)
        if self._break_active(state, now):
            return "rest", "休息中", "休息不是逃。缓完从最小可执行步骤接着做。"
        payload = _meta(row)
        if payload.get("fainted") or int(payload.get("hp") or DEFAULT_HP) <= 0:
            return "fainted", "趴下了", "血条空了，不是死透。喂食、休息或花积分加餐就能爬起来。"
        if int(payload.get("hunger") or DEFAULT_HUNGER) <= HUNGRY_THRESHOLD:
            return "hungry", "饿了", "肚子空了会掉血。喂一口或休息一下，别拖成趴下。"
        if energy < SLEEPY_ENERGY:
            return "sleepy", "困了", "有点困，不是生气。休息或吃点东西就好。"
        kinds = self._recent_work_kinds(now, txn)
        if "accepted" in kinds or "celebrate" in kinds:
            return "happy", "开心", "这下对上了。默契涨了，成功标准没降。"
        if any(kind in kinds for kind in ("failed", "skipped", "partial")):
            return "cheer", "打气", "没过也别散。养成没扣，先补一个可验证的小动作。"
        nxt = self._next_task(state)
        if nxt:
            return "idle", "待命", "待开始：{}。开始专注我会记一笔默契。".format(_task_title(nxt))
        if not self._has_goal(state):
            return "idle", "待机", "去设置页补全最终成果和成功标准，我才能跟着验收。"
        return "idle", "待机", "还没有进行中的任务时，我会在这里等你开始。"

    def _recent_work_kinds(self, now: float, txn=None) -> set[str]:
        cutoff = now - 2 * 3600
        kinds: set[str] = set()
        events = txn.list_companion_events(limit=40) if txn is not None else self.store.list_companion_events(limit=40)
        for event in events:
            kind = event.get("kind")
            if kind not in ("accepted", "celebrate", "failed", "skipped", "partial"):
                continue
            ts = _parse_ts(event.get("ts")) or 0.0
            if ts < cutoff:
                continue
            kinds.add("accepted" if kind == "celebrate" else kind)
        return kinds

    def _doing(self, state: dict) -> dict | None:
        flags = state.get("done_flags") if isinstance(state.get("done_flags"), list) else []
        for index, task in enumerate(state.get("tasks") or []):
            if not isinstance(task, dict):
                continue
            done = False
            if index < len(flags):
                done = bool(flags[index])
            if done or task.get("status") == "done" or task.get("done"):
                continue
            if task.get("status") == "doing":
                return task
        return None

    def _next_task(self, state: dict) -> dict | None:
        flags = state.get("done_flags") if isinstance(state.get("done_flags"), list) else []
        for index, task in enumerate(state.get("tasks") or []):
            if not isinstance(task, dict):
                continue
            done = False
            if index < len(flags):
                done = bool(flags[index])
            if done or task.get("status") in ("done", "skipped") or task.get("done"):
                continue
            return task
        return None

    def _break_active(self, state: dict, now: float) -> bool:
        if state.get("break_active"):
            return True
        for item in state.get("breaks") or []:
            if not isinstance(item, dict):
                continue
            until = _parse_ts(item.get("until"))
            if until is not None and until > now:
                return True
        return False

    def _has_goal(self, state: dict) -> bool:
        readiness = state.get("goal_readiness")
        if isinstance(readiness, dict) and "ready" in readiness:
            return bool(readiness.get("ready"))
        goal = state.get("goal")
        if isinstance(goal, dict):
            goal = goal.get("title") or goal.get("goal") or goal.get("name") or ""
        return bool(str(goal or "").strip())

    @staticmethod
    def _is_growth_rest(item: dict) -> bool:
        source = str(item.get("source") or "").strip().lower()
        reason = str(item.get("reason") or "")
        if source in QUIT_SOURCES:
            return False
        if any(marker in reason for marker in QUIT_REASON_MARKERS):
            return False
        return True
