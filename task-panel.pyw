#!/usr/bin/env python3 -W ignore::DeprecationWarning
"""Task Verge desktop application."""
import copy, csv, hashlib, json, os, re, sys, time, struct, socket, random, atexit, warnings, shutil
warnings.filterwarnings("ignore", category=DeprecationWarning)
import subprocess, threading, urllib.request, urllib.error, urllib.parse, tempfile, traceback, ctypes
import http.server, mimetypes, webbrowser
from email import policy as email_policy
from email.parser import BytesParser
from datetime import datetime, date

# ---- Utility functions (extracted to utils.py) ----
from utils import (
    _run, _CNW, task_text, value_text, new_id, as_list, task_done,
    app_confidence, normalize_task, normalize_tasks, task_items,
    today, min_of, hhmm, shq, pt, ej,
)
import adaptive
import acceptance as _ACCEPTANCE_MOD
import evaluation as _EVALUATION_MOD
import agent as _agent_mod
import applog as _APPLOG
import apprules as _APPRULES
import secretstore as _SECRETSTORE
from runtime import JobRunner, BoundedHTTPServer
from state_store import JsonStore, open_store
from task_service import TaskService
from agent_service import AgentService
from feedback_service import FeedbackService
from acceptance_service import AcceptanceService
_AUTH_EXEMPT_GET = {"/api/claim", "/api/heartbeat", "/favicon.ico", "/api/generate-status"}
_AUTH_EXEMPT_POST = set()
JOBS = JobRunner()
TASKS = None
AGENTS = None
FEEDBACK = None
ACCEPTANCE = None


# ---- initial crash log ----
_boot_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "TaskVerge")
if not _boot_dir:
    _boot_dir = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
try: os.makedirs(_boot_dir, exist_ok=True)
except OSError: pass
_BOOT = os.path.join(_boot_dir, "boot.log")
def _bl(msg):
    if _APPLOG:
        try: _APPLOG.boot(msg)
        except Exception: pass
        return
    try:
        with open(_BOOT, "a", encoding="utf-8") as f: f.write("{} {}\n".format(datetime.now().isoformat(), msg))
    except: pass
_bl("boot: pid={} exe={} frozen={}".format(os.getpid(), sys.executable, getattr(sys,'frozen',False)))
UI_THEME = 'light'

def _app_dir():
    r"""Return persistent data directory. Uses %LocalAppData%\TaskVerge
    for data files, falls back to script directory."""
    try: script_dir = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
    except NameError: return os.getcwd()
    # ---- Migrate to %LocalAppData%\TaskVerge ----
    try:
        appdata = os.environ.get("LOCALAPPDATA", "")
        if appdata:
            data_dir = os.path.join(appdata, "TaskVerge")
            os.makedirs(data_dir, exist_ok=True)
            marker=os.path.join(data_dir,".install-data-migrated")
            # One-time migration from releases that wrote state beside the EXE.
            for fname in (() if "--ci" in sys.argv else ("task-config.json", "history.json", "fgtime.json", "crash.log", "boot.log", "watchdog.log")):
                old_path = os.path.join(script_dir, fname)
                new_path = os.path.join(data_dir, fname)
                if os.path.exists(old_path) and (not os.path.exists(new_path) or (getattr(sys,"frozen",False) and not os.path.exists(marker) and os.path.getmtime(old_path)>os.path.getmtime(new_path))):
                    try:
                        if os.path.exists(new_path): shutil.copy2(new_path,new_path+".pre-package-migration")
                        shutil.copy2(old_path,new_path)
                    except OSError: pass
            if getattr(sys,"frozen",False) and not os.path.exists(marker):
                try:
                    with open(marker,"w",encoding="utf-8") as f: f.write(datetime.now().isoformat())
                except OSError: pass
            return data_dir
    except Exception: pass
    return script_dir
APP_DIR = _app_dir()
os.environ["TASKVERGE_DATA_DIR"] = APP_DIR
P = {
    "cfg": os.path.join(APP_DIR, "task-config.json"),
    "hist": os.path.join(APP_DIR, "history.json"),
    "fg": os.path.join(APP_DIR, "fgtime.json"),
    "log": os.path.join(APP_DIR, "watchdog.log"),
    "url": os.path.join(APP_DIR, "task-panel.url"),
    "pid": os.path.join(APP_DIR, "task-panel.pid"),
    "icons": os.path.join(APP_DIR, "icon-cache"),
    "uploads": os.path.join(APP_DIR, "attachments"),
    "exports": os.path.join(APP_DIR, "exports"),
    "ico": os.path.join(os.environ.get("TEMP", APP_DIR), "tpanel.ico"),
    "as": os.path.join(os.environ.get("APPDATA",""), "Microsoft","Windows",
        "Start Menu","Programs","Startup","task-panel.bat"),
    "crash": os.path.join(APP_DIR, "crash.log"),
    "stop": os.path.join(APP_DIR, "task-panel.stop"),
    "eval_samples": os.path.join(APP_DIR, "eval-samples.jsonl"),
}
# User data lives in %LOCALAPPDATA%; bundled frontend assets stay beside the
# entry script so a fresh data directory can still render the application.
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
_MAX_JSON_BYTES = 1 * 1024 * 1024
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_MAX_BACKUP_BYTES = 512 * 1024 * 1024
CFG0 = {"goal":"","goals":[],"archived_goals":[],"active_goal":0,"state_revision":0,"blocklist":[],"blocklists_by_goal":{},"task_apps":[],"manual_task_apps":[],"ai_task_apps":[],"task_app_categories":[],"tasks":[],"done_flags":[],"completion_pct":0,
    "tasks_by_goal":{},"flags_by_goal":{},"pct_by_goal":{},"apps_by_goal":{},"manual_apps_by_goal":{},"ai_apps_by_goal":{},"app_cats_by_goal":{},
    "locks_by_goal":{},"time_blocks_by_goal":{},"generation_by_goal":{},"acceptance_by_goal":{},
    "feedback_by_goal":{},"user_models_by_goal":{},"adaptive_signals_by_goal":{},
    "reviews_by_goal":{},"next_cycles_by_goal":{},"plan_locked":False,
    "schedule":{"enabled":False,"start":"09:00","end":"18:00","focus_template":"90"},"time_blocks":[],"task_generation":{},"last_acceptance":{},"coach_context":{"adjustments_today":0,"ignored_insights":[]},"coach_messages":[],
    "breaks":[],"events":[],"quit_attempts":[],"archives":[],
    "feedback_history":[],"user_model":{},"motivation":{"points":0,"streak":0,"best_streak":0,"history":[]},"adaptive_signals":[],"last_review":{},"next_cycle_context":{},
    "app_catalog":{},"app_catalog_sig":"","task_app_memory":{},
    "agent_runs":{},"workspace":"",
    "privacy":{"monitoring_consent":False,"cloud_ai_enabled":True,"upload_raw_file_enabled":True,"fine_grained_fg_enabled":True,"share_foreground_with_ai":False,"diagnostic_log_verbose":False},
    "focus_guard":{"enabled":True,"pause_until":0,"app_overrides":{},"stats":{"distractions":0,"distraction_seconds":0,"closed_windows":0,"temporary_allows":0,"permanent_allows":0,"paused":0}},
    "task_gen":{"available_minutes":120,"task_count":3,"max_task_minutes":45,"prefer_continuation":True,"force_measurable_output":True}}

LEGACY_STORE = JsonStore(P["log"])
def _confirm_storage_recovery(backup):
    if "--ci" in sys.argv: return False
    message="检测到本地数据库损坏。\n\n可恢复最近的有效备份：\n{}\n\n损坏文件会保留，不会删除。是否恢复？".format(backup)
    return ctypes.windll.user32.MessageBoxW(None,message,"Task Verge 数据恢复",0x34)==6
STORE = open_store(APP_DIR, P["log"], _confirm_storage_recovery)
_DURABLE_DOCUMENTS = {"task-config.json", "history.json", "fgtime.json"}
def jl(path, default=None):
    return (STORE if os.path.basename(path).lower() in _DURABLE_DOCUMENTS else LEGACY_STORE).load(path, default)
def js(path, data):
    return (STORE if os.path.basename(path).lower() in _DURABLE_DOCUMENTS else LEGACY_STORE).save(path, data)

# Import all legacy documents before rewriting evidence paths. The source JSON
# and uploads remain untouched as a read-only migration safety net.
for _legacy_path, _default in ((P["cfg"], CFG0), (P["hist"], []), (P["fg"], {})):
    jl(_legacy_path, copy.deepcopy(_default))
STORE.migrate_legacy_attachments(os.path.join(APP_DIR, "uploads"))

def path_under(root, path):
    try:
        base=os.path.normcase(os.path.abspath(root))
        target=os.path.normcase(os.path.abspath(path))
        return os.path.commonpath((base, target)) == base
    except (OSError, ValueError):
        return False

def sample_ai_incident(stage, model="", criterion_ids=(), user_content="", retain_content=False):
    """Store regression-candidate metadata; content retention is opt-in only."""
    try:
        ids = [str(x.get("id")) if isinstance(x, dict) else str(x) for x in criterion_ids if x]
        return _EVALUATION_MOD.record_production_sample(P["eval_samples"], {
            "model": model, "failure_stage": stage, "criterion_ids": ids,
            "user_content": user_content,
        }, retain_content=bool(retain_content))
    except (OSError, TypeError, ValueError):
        return None
_CFG_LOCK = threading.RLock()
def compact_state(c):
    c["events"]=c.get("events",[])[-300:]
    c["quit_attempts"]=c.get("quit_attempts",[])[-100:]
    c["breaks"]=c.get("breaks",[])[-100:]
    c["archives"]=c.get("archives",[])[-400:]
    return c
def cleanup_uploads(c):
    root=P.get("uploads")
    if not root or not os.path.isdir(root): return
    keep=set()
    for arr in c.get("tasks_by_goal",{}).values():
        for t in arr if isinstance(arr,list) else []:
            ev=t.get("evidence") if isinstance(t,dict) else ""
            ev_list = as_list(ev) if isinstance(ev, list) else ([ev] if value_text(ev) else [])
            for e in ev_list:
                if e and os.path.abspath(e).startswith(os.path.abspath(root)): keep.add(os.path.abspath(e).lower())
    for dirpath,_,files in os.walk(root,topdown=False):
        for name in files:
            fp=os.path.abspath(os.path.join(dirpath,name))
            if fp.lower() not in keep:
                try: STORE.trash_attachment(fp)
                except (OSError, ValueError): pass
        try:
            if dirpath!=root and not os.listdir(dirpath): os.rmdir(dirpath)
        except OSError: pass
def lc():
    with _CFG_LOCK:
        c = jl(P["cfg"], copy.deepcopy(CFG0))
        [c.setdefault(k,copy.deepcopy(v)) for k,v in CFG0.items()]; return compact_state(c)
def sc(c):
    with _CFG_LOCK:
        c["state_revision"] = int(c.get("state_revision",0) or 0) + 1
        compact_state(c); cleanup_uploads(c)
        js(P["cfg"], c)

# ---- Compatibility/state helpers retained during the module split ----
# These helpers are deliberately small: JSON remains the source of truth and
# callers decide when to persist through sc().
def norm_goals(c):
    goals = c.get("goals") if isinstance(c.get("goals"), list) else []
    clean = []
    for i, item in enumerate(goals):
        if isinstance(item, dict):
            g = dict(item)
            g["id"] = task_text(g.get("id")) or "goal_{}".format(i)
            g["title"] = task_text(g.get("title") or g.get("goal") or g.get("name"))
        else:
            g = {"id": "goal_{}".format(i), "title": task_text(item)}
        if g["title"] == "[object Object]":
            g["title"] = ""
        if g["title"]: clean.append(g)
    if not clean and task_text(c.get("goal")) not in ("", "[object Object]"):
        clean = [{"id": "goal_0", "title": task_text(c.get("goal"))}]
    c["goals"] = clean
    try: c["active_goal"] = max(0, min(int(c.get("active_goal", 0) or 0), len(clean) - 1))
    except Exception: c["active_goal"] = 0
    if clean:
        c["goal"] = clean[c["active_goal"]].get("title", "")
    return c

def gid(c):
    norm_goals(c)
    goals = c.get("goals", [])
    return goals[c.get("active_goal", 0)].get("id", "goal_0") if goals else "goal_0"

def goal_details(c):
    norm_goals(c)
    goals=c.get("goals",[]); i=c.get("active_goal",0)
    if not goals or i<0 or i>=len(goals): return {}
    g=goals[i]
    return {"outcome":task_text(g.get("outcome")),"deadline":task_text(g.get("deadline")),
            "baseline":task_text(g.get("baseline")),"success_criteria":as_list(g.get("success_criteria")),
            "constraints":as_list(g.get("constraints"))}

def record_product_event(c, name):
    """Record privacy-safe funnel counts without storing raw user content."""
    allowed = {"goal_created","goal_ready","goal_confirmed","first_task_generated","first_task_started","first_evidence_submitted","first_task_accepted"}
    if name not in allowed: return
    funnel = c.setdefault("product_funnel", {})
    funnel[name] = int(funnel.get(name, 0) or 0) + 1
    funnel["updated_at"] = datetime.now().isoformat()


def mark_first_task_started(c, task, idx):
    """Persist the first execution milestone without altering the goal contract."""
    if c.get("first_task_started_at"):
        return
    c["first_task_started_at"] = datetime.now().isoformat()
    c["first_task_id"] = task_text(task.get("id"))
    evlog(c, "first_task_started", "开始首个任务", {"idx": idx, "task_id": c["first_task_id"]})
    record_product_event(c, "first_task_started")


def ensure_goal_state(c):
    c = c if isinstance(c, dict) else copy.deepcopy(CFG0)
    for k, v in CFG0.items(): c.setdefault(k, copy.deepcopy(v))
    norm_goals(c)
    key = gid(c)
    # Restore the selected goal's snapshot.  Older data used the numeric
    # goal index as key, so accept that form during migration.
    maps = c.get("tasks_by_goal", {}) or {}
    flags_map = c.get("flags_by_goal", {}) or {}
    legacy_key = str(c.get("active_goal", 0))
    stored_key = key if key in maps or key in flags_map else legacy_key
    if stored_key in maps or stored_key in flags_map:
        c["tasks"] = copy.deepcopy(maps.get(stored_key, []))
        c["done_flags"] = list(flags_map.get(stored_key, []))
        for name, map_name, default in (
            ("task_apps", "apps_by_goal", []), ("manual_task_apps", "manual_apps_by_goal", []),
            ("ai_task_apps", "ai_apps_by_goal", []), ("task_app_categories", "app_cats_by_goal", []),
            ("time_blocks", "time_blocks_by_goal", []), ("task_generation", "generation_by_goal", {}),
            ("last_acceptance", "acceptance_by_goal", {}),
            ("feedback_history", "feedback_by_goal", []), ("user_model", "user_models_by_goal", {}),
            ("adaptive_signals", "adaptive_signals_by_goal", []),
            ("last_review", "reviews_by_goal", {}), ("next_cycle_context", "next_cycles_by_goal", {}),
        ):
            c[name] = copy.deepcopy((c.get(map_name, {}) or {}).get(stored_key, default))
        c["plan_locked"] = bool((c.get("locks_by_goal", {}) or {}).get(stored_key, False))
        c["blocklist"] = list((c.get("blocklists_by_goal", {}) or {}).get(stored_key, []))
    elif maps or flags_map:
        # A newly-created goal starts clean instead of inheriting another
        # goal's tasks and application assignments.
        c["tasks"] = []; c["done_flags"] = []; c["completion_pct"] = 0
        c["task_apps"] = []; c["manual_task_apps"] = []; c["ai_task_apps"] = []
        c["task_app_categories"] = []; c["time_blocks"] = []
        c["task_generation"] = {}; c["last_acceptance"] = {}; c["plan_locked"] = False
        c["feedback_history"] = []; c["user_model"] = {}; c["adaptive_signals"] = []
        c["last_review"] = {}; c["next_cycle_context"] = {}
        c["blocklist"] = []
    c["tasks"] = normalize_tasks(c.get("tasks", []), key, c.get("done_flags", []))
    for task in c["tasks"]: task["goal_id"] = key; adaptive.ensure_task_materials(task)
    sync_pct(c)
    c["task_gen"] = gen_settings(c)
    return c

def save_goal_state(c):
    """Synchronize active-goal metadata without causing a second revision."""
    norm_goals(c)
    for task in c.get("tasks", []):
        if isinstance(task, dict): adaptive.sync_task_graph(c, task)
    c["tasks_by_goal"][gid(c)] = copy.deepcopy(c.get("tasks", []))
    c["flags_by_goal"][gid(c)] = list(c.get("done_flags", []))
    c["pct_by_goal"][gid(c)] = c.get("completion_pct", 0)
    c["apps_by_goal"][gid(c)] = list(c.get("task_apps", []))
    c["manual_apps_by_goal"][gid(c)] = list(c.get("manual_task_apps", []))
    c["ai_apps_by_goal"][gid(c)] = list(c.get("ai_task_apps", []))
    c["app_cats_by_goal"][gid(c)] = list(c.get("task_app_categories", []))
    c["blocklists_by_goal"][gid(c)] = list(c.get("blocklist", []))
    c["locks_by_goal"][gid(c)] = bool(c.get("plan_locked", False))
    c["time_blocks_by_goal"][gid(c)] = copy.deepcopy(c.get("time_blocks", []))
    c["generation_by_goal"][gid(c)] = copy.deepcopy(c.get("task_generation", {}))
    c["acceptance_by_goal"][gid(c)] = copy.deepcopy(c.get("last_acceptance", {}))
    c["feedback_by_goal"][gid(c)] = copy.deepcopy(c.get("feedback_history", []))
    c["user_models_by_goal"][gid(c)] = copy.deepcopy(c.get("user_model", {}))
    c["adaptive_signals_by_goal"][gid(c)] = list(c.get("adaptive_signals", []))
    c["reviews_by_goal"][gid(c)] = copy.deepcopy(c.get("last_review", {}))
    c["next_cycles_by_goal"][gid(c)] = copy.deepcopy(c.get("next_cycle_context", {}))
    return c

def gen_settings(c):
    base = dict(CFG0.get("task_gen", {}))
    raw = c.get("task_gen", {}) if isinstance(c, dict) else {}
    if isinstance(raw, dict): base.update(raw)
    base["task_count"] = max(1, min(12, int(base.get("task_count", 3) or 3)))
    base["max_task_minutes"] = max(5, min(180, int(base.get("max_task_minutes", 45) or 45)))
    base["available_minutes"] = max(5, min(1440, int(base.get("available_minutes", 120) or 120)))
    return base

def effective_gen_settings(c):
    settings=gen_settings(c); model=c.get("user_model",{}) or {}
    factor=max(0.5,min(1.25,float(model.get("capacity_factor",1) or 1)))
    settings["available_minutes"]=max(30,min(600,round(settings["available_minutes"]*factor)))
    preferred=int(model.get("preferred_task_minutes",0) or 0)
    if preferred: settings["max_task_minutes"]=max(10,min(settings["max_task_minutes"],round(preferred*1.5)))
    settings["adaptive_capacity_factor"]=factor
    return settings

def merged_task_apps(c):
    out = []
    sources = ["manual_task_apps", "ai_task_apps"]
    # Legacy task_apps is a fallback only; otherwise removed apps would be
    # reintroduced from the stale compatibility list.
    if not any(c.get(k) for k in sources): sources.append("task_apps")
    for key in sources:
        for value in c.get(key, []) if isinstance(c.get(key, []), list) else []:
            value = task_text(value)
            if value and value.lower() not in {x.lower() for x in out}: out.append(value)
    return out[:40]

def focus_task_apps(c):
    """Prefer the active task's assignments; fall back to the goal desktop."""
    tasks=normalize_tasks(c.get("tasks",[]),gid(c),c.get("done_flags",[]))
    flags=c.get("done_flags",[])
    current=next((t for i,t in enumerate(tasks) if not task_done(t,flags[i] if i<len(flags) else False)),None)
    if isinstance(current,dict):
        apps=[]
        for key in ("required_apps","allowed_apps"):
            apps += as_list(current.get(key,[]))
        apps=[task_text(x) for x in apps if task_text(x)]
        if apps: return list(dict.fromkeys(apps))[:20]
    return merged_task_apps(c)

def focus_context(c):
    tasks=normalize_tasks(c.get("tasks",[]),gid(c),c.get("done_flags",[]))
    current=next((t for t in tasks if not task_done(t) and t.get("status")!="skipped"),None)
    if not current: return {"task":"","next_action":"","required_apps":[],"allowed_apps":[],"blocked_apps":[]}
    return {"task":task_text(current.get("title") or current.get("text")),
            "next_action":("提交交付物并进行验收" if current.get("status")=="doing" else "开始："+task_text(current.get("title") or current.get("text"))),
            "required_apps":as_list(current.get("required_apps")),"allowed_apps":as_list(current.get("allowed_apps")),"blocked_apps":as_list(current.get("blocked_apps"))}

def focus_profile(c):
    archives=c.get("archives",[]) or []; stats=(c.get("focus_guard",{}) or {}).get("stats",{}) or {}
    avg=round(sum(float(a.get("completion_pct",0) or 0) for a in archives)/len(archives)) if archives else 0
    top=dict(sorted(clean_fg(lf()).items(),key=lambda x:-x[1])[:3])
    best=next(iter(top),"")
    return {"avg_completion":avg,"archive_days":len(archives),"top_apps":top,"distractions":int(stats.get("distractions",0) or 0),"recovery_seconds":int(stats.get("distraction_seconds",0) or 0),"recommendation":("优先在 {} 中完成当前任务".format(best) if best else "先开始当前任务的最小交付步骤")}

def has_legacy_app_assignment(c):
    return any(isinstance(t, dict) and t.get("app") for t in c.get("tasks", []))

def evlog(c, kind, message="", extra=None):
    item = {"ts": datetime.now().isoformat(), "kind": task_text(kind), "message": task_text(message)}
    if isinstance(extra, dict): item.update(extra)
    c.setdefault("events", []).append(item)
    c["events"] = c["events"][-300:]

def break_active(c):
    now = time.time()
    return any(float(x.get("until", 0) or 0) > now for x in c.get("breaks", []) if isinstance(x, dict))

def unfinished(c):
    return [t for t in normalize_tasks(c.get("tasks", []), gid(c), c.get("done_flags", [])) if t.get("status") != "done"]

def task_payload(tasks, flags=None):
    return [{"index": i, "title": t.get("title", ""), "status": t.get("status", "pending"),
             "done": task_done(t, (flags or [])[i] if i < len(flags or []) else False),
             "criterion_ids": t.get("criterion_ids", []),
             "expected_output": t.get("expected_output", ""), "acceptance": t.get("acceptance", "")}
            for i, t in enumerate(normalize_tasks(tasks, "", flags or []))]

def insights_for(c):
    tasks = normalize_tasks(c.get("tasks", []), gid(c), c.get("done_flags", []))
    done = sum(1 for t in tasks if t.get("status") == "done")
    return {"alerts": [], "stats": {"completion_pct": round(done * 100 / len(tasks)) if tasks else 0,
            "task_done": done, "task_total": len(tasks), "top_apps": []}, "suggestions": []}

def push_coach_alerts(c):
    return []

def fallback_chat_action(msg, c):
    text = task_text(msg).lower()
    if any(x in text for x in ("休息", "暂停", "break")):
        return {"reply": "可以先休息 5 分钟。", "action": {"type": "break", "minutes": 5}}
    if any(x in text for x in ("重新计划", "重做", "拆小", "regenerate")):
        return {"reply": "我会按当前目标重新拆分任务。", "action": {"type": "regenerate_tasks"}}
    return {"reply": "我会继续围绕当前目标推进。", "action": {"type": "plan"}}
def lh():
    return jl(P["hist"], [])
def ah(r):
    h = lh(); h.append(r)
    js(P["hist"], h[-500:])
_FG_IGNORED={"n/a","lockapp","lockapp.exe","screensaver","screensaver.scr"}
def clean_fg(data):
    return {k:v for k,v in (data or {}).items() if str(k).strip().lower() not in _FG_IGNORED}
def lf():
    raw = jl(P["fg"], {})
    clean = clean_fg(raw)
    if clean != raw: js(P["fg"], clean)
    return clean
def sf(d):
    js(P["fg"], d)
def daily_archive(c):
    fg=dict(sorted(lf().items(),key=lambda x:-x[1])[:10])
    review=adaptive.complete_review(c,fg)
    rec={"date":today(),"goal":c.get("goal",""),"goal_id":gid(c),
         "tasks":copy.deepcopy(c.get("tasks",[])),"done_flags":list(c.get("done_flags",[])),
         "completion_pct":c.get("completion_pct",0),"fg":fg,"review":review}
    c.setdefault("archives",[])
    c["archives"]=[a for a in c["archives"] if a.get("date")!=today() or a.get("goal_id")!=gid(c)]+[rec]
    save_goal_state(c)
    return rec
def ev(n):
    for p in [os.path.join(APP_DIR,".env"),os.path.join(os.path.dirname(os.path.abspath(__file__)),".env")]:
        try:
            with open(p, encoding="utf-8") as f:
                for ln in f:
                    if n.upper() in ln.upper():
                        v = ln.split("=",1)[1].strip().strip("'\"")
                        if v: return v
        except: pass
    return ""
def dk():
    # DPAPI encrypted key takes priority; migrate legacy plaintext once.
    if _SECRETSTORE:
        try:
            k = _SECRETSTORE.load_key()
            if k and valid_deepseek_key(k):
                return k
        except Exception: pass
    k=ev("DEEPSEEK")
    if k and save_deepseek_key(k): return k
    return ""
def valid_deepseek_key(key):
    key=(key or "").strip()
    return len(key)>=20 and key.lower() not in ("invalid-key","changeme","your-key-here")
def save_deepseek_key(key):
    """Persist the DeepSeek key only in the OS-protected user store."""
    key = (key or "").strip()
    for env_path in {os.path.join(APP_DIR,".env"),os.path.join(os.path.dirname(os.path.abspath(__file__)),".env")}:
        lines=[]
        try:
            with open(env_path,encoding="utf-8") as f: lines=[ln for ln in f if not ln.upper().startswith("DEEPSEEK=")]
            if lines:
                with open(env_path,"w",encoding="utf-8") as f: f.writelines(lines)
            else: os.remove(env_path)
        except FileNotFoundError: pass
        except OSError as e:
            _bl("cannot remove plaintext API key: {}".format(e)); return False
    if not _SECRETSTORE: return not key
    try: return bool(_SECRETSTORE.save_key(key))
    except Exception as e:
        _bl("cannot save encrypted API key: {}".format(e)); return False
class AIError(Exception):
    def __init__(self, kind, msg):
        super().__init__(msg); self.kind=kind
def deepseek_json(messages, max_tokens=1000, temperature=0.2, timeout=35, retries=1):
    k=dk()
    if not valid_deepseek_key(k): raise AIError("missing_key","未配置有效 DeepSeek Key")
    if not k: raise AIError("missing_key","未配置 DeepSeek Key")
    body=json.dumps({"model":"deepseek-chat","messages":messages,"temperature":temperature,"max_tokens":max_tokens},ensure_ascii=False).encode("utf-8")
    req=urllib.request.Request("https://api.deepseek.com/v1/chat/completions",data=body,headers={"Content-Type":"application/json","Authorization":"Bearer "+k})
    last=None
    for n in range(retries+1):
        try:
            resp=json.loads(urllib.request.urlopen(req,timeout=timeout).read())
            return ej(resp["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as e:
            kind="auth" if e.code in (401,403) else ("rate_limit" if e.code==429 else "http")
            raise AIError(kind,"DeepSeek HTTP {}: {}".format(e.code,e.reason))
        except (TimeoutError, urllib.error.URLError) as e:
            last=e
            if n<retries: time.sleep(1+n); continue
            raise AIError("network","DeepSeek 网络/超时错误: {}".format(e))
        except Exception as e:
            last=e
            if n<retries: time.sleep(1+n); continue
            raise AIError("bad_response","DeepSeek 响应解析失败: {}".format(e))
    raise AIError("unknown",str(last))

def fallback_task_templates(goal, settings=None):
    goal = task_text(goal) or "当前目标"
    learning_templates = adaptive.learning_fallback_templates(goal)
    if learning_templates:
        return learning_templates
    return [
        {"title": "明确“{}”今天的最小可交付成果".format(goal), "description": "写下完成定义和边界。", "type": "plan", "estimated_minutes": 15, "expected_output": "一段完成定义", "acceptance": "内容明确且可核验"},
        {"title": "为“{}”准备输入和工作环境".format(goal), "description": "收集资料、打开必要工具并确认路径。", "type": "prepare", "estimated_minutes": 20, "expected_output": "输入清单或工作区", "acceptance": "输入可访问且路径有效"},
        {"title": "完成“{}”的第一个可运行版本".format(goal), "description": "优先完成最小闭环，不扩展范围。", "type": "practice", "estimated_minutes": 45, "expected_output": "可运行结果", "acceptance": "结果可复现"},
        {"title": "验证“{}”并记录一个证据".format(goal), "description": "执行检查并记录输出、截图或文件。", "type": "verify", "estimated_minutes": 25, "expected_output": "验证记录", "acceptance": "证据能对应完成标准"},
    ]

def save_diagnostic_plan(c, tasks, mode="diagnostic"):
    goal_id=gid(c)
    criterion_ids=[x["id"] for x in _EVALUATION_MOD.criterion_records(goal_details(c).get("success_criteria", []))]
    completed=[t for t in normalize_tasks(c.get("tasks",[]),goal_id,c.get("done_flags",[])) if task_done(t)]
    fresh=[]
    for raw in tasks:
        task=normalize_task(raw,goal_id,len(completed)+len(fresh),False)
        if criterion_ids: task["criterion_ids"]=criterion_ids[:]
        task["id"]=new_id("task"); task["status"]="pending"; fresh.append(task)
    c["tasks"]=completed+fresh; c["done_flags"]=[True]*len(completed)+[False]*len(fresh)
    sync_pct(c); c["plan_locked"]=True
    profile=adaptive.ability_profile(c,c.get("goal",""))
    c["task_generation"]={"ts":datetime.now().isoformat(),"goal_analysis":{"intent":c.get("goal","")},
                          "milestones":[],"progress_diagnosis":{"ability_profile":profile},
                          "daily_strategy":"先完成能力诊断，再按薄弱项分配学习任务。"}
    save_goal_state(c); evlog(c,"ability_diagnostic","generated initial diagnostic plan",profile); sc(c)
    gen_status("完成","已生成 {} 个能力诊断任务".format(len(fresh)),mode=mode)
    return "OK {} diagnostic tasks".format(len(fresh))

def ensure_ability_dimensions(c):
    goal=c.get("goal","")
    signature=json.dumps({"goal":goal,"details":goal_details(c)},sort_keys=True,ensure_ascii=False)
    model=c.setdefault("user_model",{})
    stored=adaptive.normalize_diagnostic_dimensions(model.get("ability_dimensions",[]),goal)
    source=model.get("ability_dimensions_source","")
    key=dk()
    if stored and model.get("ability_dimensions_signature")==signature and not (
            source=="fallback" and c.get("privacy",{}).get("cloud_ai_enabled",True) and valid_deepseek_key(key)):
        return stored
    dimensions=[]; source="fallback"
    if c.get("privacy",{}).get("cloud_ai_enabled",True) and valid_deepseek_key(key):
        gen_status("分析能力维度","根据目标建立稳定、可测量的能力模型")
        try:
            result=deepseek_json([
                {"role":"system","content":"你是能力测量设计专家。只返回紧凑 JSON，不要 Markdown。维度必须互不重叠、覆盖目标核心能力，并能通过短任务测量。凡任务引用题目、文章、案例、数据或代码，必须在 materials 中完整提供。"},
                {"role":"user","content":json.dumps({
                    "goal":goal,"goal_details":goal_details(c),
                    "requirements":{"dimension_count":"3-6","stable":True,"measurable":True,
                        "schema":{"dimensions":[{"skill_id":"ascii.stable.id","title":"能力名：诊断动作",
                            "description":"无需帮助完成的具体诊断","estimated_minutes":20,
                            "expected_output":"可检查产出","acceptance":"包含数量或清晰判定标准",
                            "materials":[{"type":"question|passage|prompt|data|code","content":"","prompt":"","options":[],"answer":""}],
                            "interaction":{"type":"choice|text","min_score":0.7}}]}}
                },ensure_ascii=False)}
            ],1200,0.1,30,1)
            dimensions=adaptive.normalize_diagnostic_dimensions(result,goal)
            source="ai" if dimensions else "fallback"
        except Exception as exc:
            _bl("ability dimensions fallback: "+repr(exc))
    if not dimensions:
        dimensions=adaptive.diagnostic_dimensions(goal)
    dimensions=adaptive.set_diagnostic_dimensions(c,dimensions,signature,source)
    save_goal_state(c); sc(c)
    return dimensions

def build_task_prompt(c):
    settings = effective_gen_settings(c)
    criteria = _EVALUATION_MOD.criterion_records(goal_details(c).get("success_criteria", []))
    unfinished_items = [t for t in normalize_tasks(c.get("tasks", []), gid(c), c.get("done_flags", [])) if t.get("status") != "done"]
    prompt = {
        "goal": c.get("goal", ""), "goal_details": goal_details(c),
        "success_criteria_records": criteria,
        "user_model": {k:v for k,v in (c.get("user_model", {}) or {}).items()
                       if k not in ("skills", "fsrs_review_logs", "fsrs_scheduler")},
        "knowledge_graph": adaptive.knowledge_graph(c),
        "recent_feedback": c.get("feedback_history", [])[-10:],
        "learning_focus": adaptive.learning_focus(c),
        "ability_profile": adaptive.ability_profile(c, c.get("goal", "")),
        "learning_policy": {
            "sequence": ["diagnostic", "recall", "practice", "explain", "transfer"],
            "rule": "If mastery is unknown, generate a diagnostic task first. Every task that refers to questions, source text, data, code, cases or other inputs must include those inputs in materials; never ask the user to find them.",
        },
        "unfinished_tasks": task_payload(unfinished_items),
        "history": lh()[-5:], "settings": settings,
        "required_schema": {"goal_analysis": {}, "milestones": [], "progress_diagnosis": {},
                             "knowledge_graph": {"nodes": [{"id": "", "title": "", "description": "",
                                                            "prerequisites": []}]},
                             "daily_strategy": "", "tasks": [{"title": "", "description": "", "type": "practice",
                             "criterion_ids": ["Use IDs from success_criteria_records"],
                             "estimated_minutes": 30, "expected_output": "", "acceptance": "", "required_apps": [],
                             "allowed_apps": [], "depends_on": [], "skill_id": "", "prerequisites": [],
                             "learning_task_type": "recall", "materials": [{"type":"question|passage|audio_script|prompt|data|code","title":"","content":"","prompt":"","options":[],"answer":""}],
                             "interaction": {"type":"choice|text","min_score":0.7}}]},
    }
    return settings, json.dumps(prompt, ensure_ascii=False)

def validate_ai_tasks(goal, tasks, settings, criterion_ids=()):
    if not isinstance(tasks, list): return []
    valid_criteria = set(criterion_ids)
    out = []; seen = set(); semantic_seen = set()
    for raw in tasks:
        if not isinstance(raw, dict): continue
        if adaptive.is_generic_planning_task(goal, raw): continue
        if adaptive.task_consistency_issues(raw): continue
        title = task_text(raw.get("title") or raw.get("text") or raw.get("name"))
        if len(title) < 3 or title.casefold() in seen: continue
        item = normalize_task(dict(raw, title=title), "", len(out), False)
        if valid_criteria:
            item["criterion_ids"] = [x for x in item.get("criterion_ids", []) if x in valid_criteria]
            if not item["criterion_ids"]: continue
        for index, material in enumerate(item.get("materials", []), 1):
            material.setdefault("id", "{}-material-{}".format(item["id"], index))
        if not item.get("answer_key"):
            item["answer_key"] = [{"id": "{}-key-{}".format(item["id"], index),
                                   "material_ids": [material["id"]], "answer": material["answer"]}
                                  for index, material in enumerate(item.get("materials", []), 1)
                                  if material.get("answer") not in (None, "")]
        semantic_key = adaptive.task_semantic_key(item)
        if semantic_key and semantic_key in semantic_seen: continue
        item["source"] = "ai"
        item["locked"] = True
        if not item.get("expected_output"): item["expected_output"] = "可核验的完成结果"
        if not item.get("acceptance"): item["acceptance"] = "结果与当前目标直接相关且可复现"
        seen.add(title.casefold()); semantic_seen.add(semantic_key); out.append(item)
        if len(out) >= max(1, int(settings.get("task_count", 3) or 3) + 3): break
    return out

def generation_eval(c, tasks):
    details = goal_details(c); criteria = _EVALUATION_MOD.criterion_records(details.get("success_criteria", []))
    if not criteria or not details.get("outcome"):
        return {"decision":"pass", "first_failing_stage":None}
    case = {"id":"live-generation", "version":1, "goal":{"id":gid(c),
            "final_outcome":details.get("outcome"), "success_criteria":criteria,
            "constraints":details.get("constraints", [])}}
    return _EVALUATION_MOD.evaluate_generation(case, {"tasks":tasks,
            "metadata":{"model":"deepseek", "prompt_version":"task-generation-v2"}})

def fit_task_budget(tasks, settings):
    budget=max(5, int(settings.get("available_minutes", 120) or 120))
    max_each=max(5, int(settings.get("max_task_minutes", 45) or 45))
    out=[]; total=0
    for task in tasks or []:
        minutes=max(5, min(max_each, int(task.get("estimated_minutes", 30) or 30)))
        task["estimated_minutes"]=minutes
        if out and total+minutes>budget: continue
        out.append(task); total+=minutes
        if total>=budget: break
    return out or list(tasks[:1] if tasks else [])

def evidence_details(evidence, response=""):
    paths = valid_evidence_paths(evidence)
    files = []
    for path in paths:
        item = {"path": path, "exists": os.path.exists(path)}
        if item["exists"] and path.lower().endswith(".py"):
            try:
                r = _run([sys.executable, "-m", "py_compile", path], timeout=15)
                item["python_check"] = {"ok": r.returncode == 0, "stderr": (r.stderr or "")[-500:]}
            except Exception as e: item["python_check"] = {"ok": False, "error": str(e)}
        files.append(item)
    response_text=json.dumps(response,ensure_ascii=False) if isinstance(response,(dict,list)) else task_text(response)
    return {"files": files, "count": len(files), "text": response_text}

def valid_evidence_paths(evidence):
    root=os.path.abspath(P["uploads"])
    return [os.path.abspath(p) for p in as_list(evidence)
            if path_under(root,os.path.abspath(p)) and os.path.isfile(os.path.abspath(p))]

def compact_evidence_basis(details):
    return [{"files": [{"path": f.get("path", ""), "exists": bool(f.get("exists")),
                         "python_ok": f.get("python_check", {}).get("ok") if f.get("python_check") else None}
                        for f in (d.get("files", []) if isinstance(d, dict) else [])]}
            for d in (details or [])]

def norm_acceptance_result(result, passed=False, reason=""):
    return _ACCEPTANCE_MOD.explainable_result(result, passed=passed, reason=reason)

def generation_guard(c):
    # ponytail: ignore unrelated telemetry writes; only user-editable inputs can invalidate a generation.
    return json.dumps({k: c.get(k) for k in (
        "goal", "goals", "active_goal", "tasks", "done_flags", "task_gen",
        "privacy", "manual_task_apps", "blocklist")}, sort_keys=True, ensure_ascii=False, default=str)

def catalog_guard(c):
    return json.dumps({"state": generation_guard(c), "app_catalog": c.get("app_catalog"),
                       "app_catalog_sig": c.get("app_catalog_sig")}, sort_keys=True,
                      ensure_ascii=False, default=str)

def gen_tasks():
    c = ensure_goal_state(lc())
    if not c.get("privacy",{}).get("cloud_ai_enabled", True):
        gen_status("完成","云模型已关闭，使用离线兜底")
        GEN_STATUS["mode"] = "offline"
        return fallback_tasks(c, "cloud ai disabled")
    generation_revision = generation_guard(c)
    gen_status("读取目标")
    g = c.get("goal","")
    if not g: gen_status("完成","没有目标"); return "SKIP no goal"
    ensure_ability_dimensions(c)
    settings=effective_gen_settings(c)
    diagnostics=adaptive.initial_diagnostic_tasks(c,g,settings.get("task_count",3))
    if diagnostics: return save_diagnostic_plan(c,diagnostics)
    gen_status("读取 DeepSeek Key")
    k = dk()
    if not valid_deepseek_key(k): return fallback_tasks(c,"no valid DeepSeek key")
    gen_status("整理上下文","读取目标、未完成任务、历史复盘和生成偏好")
    settings, prompt = build_task_prompt(c)
    gen_status("请求 AI","生成目标分析和今日任务")
    result = deepseek_json([
        {"role":"system","content":"你是严格的个人执行计划生成器。只返回紧凑 JSON。不要输出 Markdown。任务必须直接服务当前目标，必须可验收。"},
        {"role":"user","content":prompt}],1800,0.25,35,1)
    gen_status("解析结果")
    if not isinstance(result,dict): raise AIError("bad_response","AI result must be a JSON object")
    criterion_ids = [x["id"] for x in _EVALUATION_MOD.criterion_records(goal_details(c).get("success_criteria", []))]
    tasks = validate_ai_tasks(g, result.get("tasks",[]), settings, criterion_ids)
    adaptive.merge_knowledge_graph(c,result.get("knowledge_graph",{}))
    tasks=[task for task in tasks if adaptive.task_is_unlocked(c,task)]
    if len(tasks) < settings.get("task_count",3) or generation_eval(c, tasks).get("decision") != "pass":
        sample_ai_incident("goal_to_task", "deepseek", goal_details(c).get("success_criteria", []))
        gen_status("修正结果","AI 返回任务不足或偏离目标，正在二次修正")
        repair_prompt = prompt + "\n\ninvalid_result:\n" + json.dumps(result, ensure_ascii=False) + "\nReturn a corrected JSON object with enough valid tasks."
        result = deepseek_json([{"role":"system","content":"Return compact JSON only. Fix the task list so every task directly serves the current goal."},{"role":"user","content":repair_prompt}],1600,0.2,35,1)
        if not isinstance(result,dict): raise AIError("bad_response","AI repair result must be a JSON object")
        tasks = validate_ai_tasks(g, result.get("tasks",[]), settings, criterion_ids)
        adaptive.merge_knowledge_graph(c,result.get("knowledge_graph",{}))
        tasks=[task for task in tasks if adaptive.task_is_unlocked(c,task)]
    if len(tasks) < settings.get("task_count",3):
        seen={task_text(t).lower() for t in tasks}
        semantic_seen={adaptive.task_semantic_key(t) for t in tasks if adaptive.task_semantic_key(t)}
        for x in fallback_task_templates(g, settings):
            if len(tasks) >= settings.get("task_count",3): break
            semantic_key=adaptive.task_semantic_key(x)
            if task_text(x).lower() not in seen and (not semantic_key or semantic_key not in semantic_seen):
                nt=normalize_task(x, gid(c), len(tasks), False); nt["source"]="fallback_topup"; nt["locked"]=True
                if criterion_ids: nt["criterion_ids"] = criterion_ids[:]
                tasks.append(nt); seen.add(task_text(nt).lower()); semantic_seen.add(semantic_key)
    scheduled = adaptive.next_learning_task(c)
    scheduled_key = adaptive.task_semantic_key(scheduled) if scheduled else ""
    if scheduled and not any(
            t.get("skill_id") == scheduled["skill_id"] or
            (scheduled_key and adaptive.task_semantic_key(t) == scheduled_key)
            for t in tasks):
        scheduled = normalize_task(scheduled, gid(c), 0, False)
        if criterion_ids: scheduled["criterion_ids"] = criterion_ids[:]
        tasks.insert(0, scheduled)
    if not tasks: return fallback_tasks(c,"AI returned no valid tasks")
    for task in tasks: adaptive.ensure_task_materials(task)
    tasks=fit_task_budget(tasks, settings)
    quality = generation_eval(c, tasks)
    if quality.get("decision") != "pass":
        sample_ai_incident(quality.get("first_failing_stage") or "goal_to_task", "deepseek", criterion_ids)
        return fallback_tasks(c, "AI quality gate failed")
    latest=ensure_goal_state(lc())
    if generation_guard(latest) != generation_revision:
        gen_status("澶辫触","generation state changed; please retry",mode="conflict")
        return "CONFLICT generation state changed"
    c=latest; goal_id=gid(c)
    adaptive.merge_knowledge_graph(c,result.get("knowledge_graph",{}))
    completed=[]; completed_ids=set(); completed_titles=set()
    for old in normalize_tasks(c.get("tasks",[]), goal_id, c.get("done_flags",[])):
        if task_done(old) or old.get("status")=="done":
            completed.append(old); completed_ids.add(old.get("id")); completed_titles.add(old.get("title","").casefold())
    tasks=[t for t in tasks if t.get("id") not in completed_ids and t.get("title","").casefold() not in completed_titles]
    tasks=completed+tasks
    known={t.get("title","").casefold() for t in tasks}
    for t in tasks:
        t["depends_on"]=[x for x in as_list(t.get("depends_on")) if x.casefold() in known and x.casefold()!=t.get("title","").casefold()][:4]
    for i,t in enumerate(tasks):
        t["goal_id"]=goal_id
        if i >= len(completed): t["status"]="pending"; t["id"]=new_id("task")
    c["tasks"] = tasks
    c["done_flags"] = [True]*len(completed)+[False]*len(tasks[len(completed):])
    c["completion_pct"]=round(len(completed)*100/len(c["tasks"])) if c["tasks"] else 0; c["plan_locked"]=True
    c["task_generation"]={"ts":datetime.now().isoformat(),"goal_analysis":result.get("goal_analysis",{}),"milestones":result.get("milestones",[]),"progress_diagnosis":result.get("progress_diagnosis",{}),"daily_strategy":result.get("daily_strategy","")}
    c["ai_task_apps"]=[]; c["task_app_categories"]=[]
    save_goal_state(c); evlog(c,"plan_locked","generated structured tasks",{"strategy":c["task_generation"]})
    gen_status("保存任务")
    sc(c)
    gen_status("完成","OK {} tasks".format(len(c["tasks"])))
    return "OK {} tasks".format(len(c["tasks"]))

def fallback_tasks(c, why):
    g=c.get("goal","目标") or "目标"; s=effective_gen_settings(c); goal_id=gid(c)
    criterion_ids=[x["id"] for x in _EVALUATION_MOD.criterion_records(goal_details(c).get("success_criteria", []))]
    diagnostics=adaptive.initial_diagnostic_tasks(c,g,s.get("task_count",3))
    if diagnostics: return save_diagnostic_plan(c,diagnostics,"fallback")
    existing=normalize_tasks(c.get("tasks",[]), goal_id, c.get("done_flags",[]))
    raw=existing[:]
    scheduled=adaptive.next_learning_task(c)
    scheduled_key=adaptive.task_semantic_key(scheduled) if scheduled else ""
    if scheduled and not any(
            t.get("skill_id")==scheduled["skill_id"] or
            (scheduled_key and adaptive.task_semantic_key(t)==scheduled_key)
            for t in raw):
        scheduled=normalize_task(scheduled, goal_id, 0, False)
        if criterion_ids: scheduled["criterion_ids"]=criterion_ids[:]
        raw.insert(0, scheduled)
    seen={task_text(t).casefold() for t in raw if task_text(t)}
    semantic_seen={adaptive.task_semantic_key(t) for t in raw if adaptive.task_semantic_key(t)}
    for template in fit_task_budget(fallback_task_templates(g, s), s):
        if len(raw) >= s["task_count"]: break
        if task_text(template).casefold() in seen: continue
        semantic_key=adaptive.task_semantic_key(template)
        if semantic_key and semantic_key in semantic_seen: continue
        nt=normalize_task(template, goal_id, len(raw), False)
        if criterion_ids: nt["criterion_ids"]=criterion_ids[:]
        nt["source"]="fallback"; nt["locked"]=True
        raw.append(nt); seen.add(task_text(template).casefold()); semantic_seen.add(semantic_key)
    c["tasks"]=raw
    c["done_flags"]=[task_done(t) for t in raw]
    for t in c["tasks"]: t["goal_id"]=goal_id
    sync_pct(c); c["plan_locked"]=True
    c["task_generation"]={"ts":datetime.now().isoformat(),"goal_analysis":{"intent":g,"success_criteria":goal_details(c).get("success_criteria",[])},"milestones":[],"progress_diagnosis":{},"daily_strategy":"先完成最小可交付成果，再用证据验收。"}
    save_goal_state(c); evlog(c,"fallback_gen",why); sc(c)
    gen_status("完成","本地兜底生成 {} tasks: {}".format(len(c["tasks"]), why))
    GEN_STATUS["mode"]="fallback"
    return "OK {} tasks (fallback)".format(len(c["tasks"]))

def cli_gen():
    print(gen_tasks())

def reset_task_timer(task):
    task["actual_seconds"] = 0
    task.pop("actual_minutes", None)
    task["started_at"] = ""

def evaluate_task(task_idx):
    c=ensure_goal_state(lc()); items=normalize_tasks(c.get("tasks",[]),gid(c),c.get("done_flags",[]))
    if task_idx<0 or task_idx>=len(items): raise ValueError("任务索引越界")
    task=items[task_idx]; evidence=as_list(task.get("evidence")); response=task.get("response"); cloud_enabled=bool(c.get("privacy",{}).get("cloud_ai_enabled",True))
    if task.get("skill_id") and not task.get("recall_rating"):
        raise ValueError("请先选择回忆质量：忘记、困难、正常或轻松")
    if not evidence and not response and task.get("verification_mode")!="none":
        result=norm_acceptance_result({"pass":False,"reason":"未提交交付物或证据","missing":["交付物文件或可核验证据"],"next_steps":["上传交付物后重新验收"]})
    else:
        details=evidence_details(evidence,response); verdict=_ACCEPTANCE_MOD.check_evidence(task,details)
        result=_ACCEPTANCE_MOD.verdict_to_acceptance_result(verdict)
        if result.get("needs_llm") and cloud_enabled and valid_deepseek_key(dk()):
            result.update(_ACCEPTANCE_MOD.run_llm_eval(task,details,{},lambda msgs,mt,temp,to,retries: deepseek_json(msgs,mt,temp,to,retries)))
    result=norm_acceptance_result(result)
    if result["status"] != "passed":
        sample_ai_incident("evidence_to_acceptance", "deepseek" if cloud_enabled else "deterministic",
                           task.get("criterion_ids", []))
    reset_task_timer(task)
    c["tasks"]=items; c["done_flags"]=list(c.get("done_flags",[]))
    ok, persisted = ACCEPTANCE.persist_result(c, task_idx, result)
    if not ok: raise ValueError(persisted)
    if persisted.get("status")=="passed": record_product_event(c, "first_task_accepted")
    return {"ok":True,"pass":persisted.get("status")=="passed","status":persisted.get("status"),"result":persisted}

def cli_eval():
    c = ensure_goal_state(lc())
    cloud_enabled=bool(c.get("privacy",{}).get("cloud_ai_enabled", True))
    if not cloud_enabled and not _ACCEPTANCE_MOD:
        return print("FAIL cloud ai disabled (evaluate)")
    items=normalize_tasks(c.get("tasks",[]), gid(c), c.get("done_flags",[]))
    if not items: return print("SKIP no tasks")
    no_evidence=[not as_list(t.get("evidence")) and not t.get("response") and t.get("verification_mode") != "none" for t in items]
    if all(no_evidence):
        results=[norm_acceptance_result({"pass":False,"reason":"未提交交付物或证据","missing":["交付物文件或可核验说明"],"next_steps":["上传交付物后重新点击 AI 验收"]}) for _ in items]
        ah({"date":today(),"goal":c.get("goal",""),"goal_id":gid(c),"tasks":items,"completion_pct":0,"summary":"未提交交付物或证据，AI 未放行","acceptance_results":results})
        c["tasks"]=items; c["done_flags"]=[False]*len(items); c["completion_pct"]=0
        for i,t in enumerate(c["tasks"]): t["status"]="pending"; t["acceptance_result"]=results[i]; reset_task_timer(t)
        save_goal_state(c); sc(c); return print("OK 0%")
    k = dk()
    today_s = date.today().isoformat()
    fg = lf()
    details=[evidence_details(t.get("evidence",[]) if isinstance(t.get("evidence"), list) else t.get("evidence",""),t.get("response")) for t in items]
    fg_top=dict(sorted(fg.items(),key=lambda x:-x[1])[:12])
    cloud_fg=fg_top if c.get("privacy",{}).get("share_foreground_with_ai",False) else {}

    # ---- Rules-first path (if enabled) ----
    if _ACCEPTANCE_MOD:
        results = []
        done = []
        any_needs_llm = False
        for i, t in enumerate(items):
            verdict = _ACCEPTANCE_MOD.check_evidence(t, details[i])
            ar = _ACCEPTANCE_MOD.verdict_to_acceptance_result(verdict)
            results.append(ar)
            done.append(verdict.pass_ and not verdict.needs_llm)
            if verdict.needs_llm:
                any_needs_llm = True

        # If any task needs LLM judgment, call it per-task
        if any_needs_llm and cloud_enabled and valid_deepseek_key(k):
            for i, t in enumerate(items):
                if results[i].get("needs_llm"):
                    try:
                        llm_result = _ACCEPTANCE_MOD.run_llm_eval(
                            t, details[i], cloud_fg,
                            lambda msgs, mt, temp, to, retries: deepseek_json(msgs, mt, temp, to, retries))
                        results[i]["pass"] = llm_result.get("pass", False)
                        results[i]["reason"] = llm_result.get("reason", results[i]["reason"])
                        results[i]["missing"] = llm_result.get("missing", [])
                        results[i]["next_steps"] = llm_result.get("next_steps", [])
                        results[i]["evidence_refs"] = llm_result.get("evidence_refs", [])
                        done[i] = results[i]["pass"]
                    except Exception as e:
                        results[i]["reason"] += f" (LLM 调用失败: {e})"
                        results[i]["needs_llm"] = False
                        done[i] = results[i]["pass"]

        # Apply no-evidence overrides (unchanged from original logic)
        for i, missing in enumerate(no_evidence):
            if missing and items[i].get("verification_mode") != "none":
                done[i] = False
                results[i] = {"pass": False, "reason": "未提交交付物或证据", "missing": ["交付物文件或可核验证据"],
                    "next_steps": ["上传交付物后重新验收"], "evidence_refs": [],
                    "checks": {}, "needs_llm": False, "overridden": False, "override_reason": "", "rules_first": True}

        c["tasks"] = items
        basis = {"ts": datetime.now().isoformat(), "model": "rules-first+deepseek-chat",
            "foreground_time": fg_top, "evidence": compact_evidence_basis(details), "raw_result": {}}

        graded=[norm_acceptance_result(results[i] if i < len(results) else {}) for i in range(len(items))]
        c["done_flags"] = [ar["decision"]=="accepted" for ar in graded]
        for i, t in enumerate(c["tasks"]):
            t["status"] = "done" if c["done_flags"][i] else "pending"
            adaptive.record_task_outcome(t,c["done_flags"][i])
            reset_task_timer(t)
            ar = graded[i]
            ar["basis"] = {"foreground_time": fg_top, "evidence": basis["evidence"][i] if i < len(basis["evidence"]) else {}}
            ar.setdefault("rules_first", True)
            t["acceptance_result"] = ar
            if t.get("skill_id") and t.get("recall_rating") and ar.get("decision") in ("accepted","rejected"):
                adaptive.record_learning_outcome(c,t,c["done_flags"][i])
        sync_pct(c); pct = c.get("completion_pct", 0)
        c["last_acceptance"] = basis
        ah({"date": today_s, "goal": c.get("goal", ""), "goal_id": gid(c), "tasks": items,
            "completion_pct": pct, "summary": "规则优先验收完成",
            "acceptance_results": [t.get("acceptance_result", {}) for t in c["tasks"]], "basis": basis})
        save_goal_state(c)
        sc(c)
        print("OK {}% (rules-first)".format(pct))
        return

    # ---- Original LLM-only path (fallback when rules-first is disabled) ----
    payload={"goal":c.get("goal",""),"tasks":[{"title":t.get("title",""),"description":t.get("description",""),"expected_output":t.get("expected_output",""),"acceptance":t.get("acceptance",""),"required_apps":t.get("required_apps",[]),"allowed_apps":t.get("allowed_apps",[]),"evidence":as_list(t.get("evidence","")),"evidence_details":details[i]} for i,t in enumerate(items)],
        "foreground_time":cloud_fg}
    schema='{"completion_pct":80,"done":[true,false,true],"results":[{"pass":true,"reason":"short verdict","missing":["what is missing"],"next_steps":["what user should upload or fix"],"evidence_refs":["file.py: stdout line or code fact"]}],"summary":"text"}'
    prompt=json.dumps(payload,ensure_ascii=False)+"\nReturn JSON only: "+schema
    result = deepseek_json([{"role":"system","content":"你是严格的任务验收审计员，不是任务生成器。默认怀疑，只有证据满足 expected_output 和 acceptance 才通过。根据交付物、读取到的文件内容、Docker/Python 检查结果、必要应用使用证据判断。没有证据不得通过；文件不存在不得通过；Python 文件 py_compile 或 Docker 执行失败不得通过；只用前台时间不能通过。每个 result 必须包含 pass、reason、missing、next_steps、evidence_refs。只返回 JSON。"},{"role":"user","content":prompt}],2200,0.1,35,1)
    pct = result.get("completion_pct",0)
    done = result.get("done",[])
    results = result.get("results",[])
    for i,missing in enumerate(no_evidence):
        if missing:
            if i < len(done): done[i]=False
            while len(results)<=i: results.append({})
            results[i]={"pass":False,"reason":"未提交交付物或证据","missing":["交付物文件或可核验证据"],"next_steps":["上传交付物后重新验收"],"evidence_refs":[]}
    for i,d in enumerate(details):
        bad=next((f for f in d.get("files",[]) if not f.get("exists") or f.get("python_check",{}).get("ok") is False or f.get("docker_run",{}).get("ok") is False), None)
        if bad:
            if i < len(done): done[i]=False
            while len(results)<=i: results.append({})
            results[i]={"pass":False,"reason":"交付物文件不存在、Python 静态检查失败或 Docker 执行失败","missing":["可通过检查的交付物"],"next_steps":["修复文件路径、语法错误或运行错误后重新上传"],"evidence_refs":[bad.get("path","")]}
    c["tasks"] = items
    basis={"ts":datetime.now().isoformat(),"model":"deepseek-chat","foreground_time":fg_top,"evidence":compact_evidence_basis(details),"raw_result":result}
    graded=[norm_acceptance_result(results[i] if i < len(results) else {}) for i in range(len(items))]
    c["done_flags"]=[ar["decision"]=="accepted" for ar in graded]
    for i,t in enumerate(c["tasks"]):
        t["status"]="done" if c["done_flags"][i] else "pending"
        adaptive.record_task_outcome(t,c["done_flags"][i])
        reset_task_timer(t)
        ar=graded[i]
        ar["basis"]={"foreground_time":fg_top,"evidence":basis["evidence"][i] if i < len(basis["evidence"]) else {}}
        t["acceptance_result"]=ar
        if t.get("skill_id") and t.get("recall_rating") and ar.get("decision") in ("accepted","rejected"):
            adaptive.record_learning_outcome(c,t,c["done_flags"][i])
    sync_pct(c); pct=c.get("completion_pct",0)
    c["last_acceptance"]=basis
    ah({"date":today_s,"goal":c.get("goal",""),"goal_id":gid(c),"tasks":items,"completion_pct":pct,"summary":result.get("summary",""),"acceptance_results":[t.get("acceptance_result",{}) for t in c["tasks"]],"basis":basis})
    save_goal_state(c)
    sc(c)
    print("OK {}%".format(pct))

def ensure_time_blocks(c, force=False):
    ensure_goal_state(c)
    if c.get("time_blocks") and not force: return c["time_blocks"]
    sch=c.get("schedule",{}) or {}; start=min_of(sch.get("start","09:00")); end=min_of(sch.get("end","18:00"))
    if end<=start: end=start+8*60
    # ---- Focus template: 25 (Pomodoro) / 50 / 90 (default) ----
    template = str(sch.get("focus_template", "90") or "90")
    if template == "25": focus_min, break_min = 25, 5
    elif template == "50": focus_min, break_min = 50, 10
    else: focus_min, break_min = 90, 15
    cur=start; since_break=0; out=[]
    for i,t in enumerate(normalize_tasks(c.get("tasks",[]),gid(c),c.get("done_flags",[]))):
        if t.get("status")=="done": continue
        dur=max(10,min(gen_settings(c).get("max_task_minutes",45),int(t.get("estimated_minutes",30) or 30)))
        if since_break>=focus_min and cur+break_min<end:
            out.append({"type":"break","start":hhmm(cur),"end":hhmm(cur+break_min),"status":"pending","reason":"{} 分钟后自动休息".format(focus_min)})
            cur+=break_min; since_break=0
        if cur+dur>end: break
        out.append({"type":"task","task_idx":i,"task_id":t.get("id",""),"title":t.get("title",""),"start":hhmm(cur),"end":hhmm(cur+dur),"status":t.get("status","pending"),"reason":"按预计时长和当前日程自动安排"})
        cur+=dur+5; since_break+=dur
    c["time_blocks"]=out; return out

def cli_stats():
    def r(cmd):
        try: r = _run(cmd, timeout=10); return r.stdout.strip()
        except: return ""
    s = {"ts":time.time(),"host":socket.gethostname()}
    o = r(["powershell","-NoProfile","-Command","Get-WmiObject Win32_OperatingSystem | Select TotalVisibleMemorySize,FreePhysicalMemory | Format-Table -HideTableHeaders"])
    p = o.split()
    if len(p) >= 2: t,f = int(p[0]), int(p[1]); s["mem_total_gb"]=round(t/1048576,1); s["mem_free_gb"]=round(f/1048576,1); s["mem_used_pct"]=round((t-f)/t*100,0)
    o = r(["powershell","-NoProfile","-Command","Get-WmiObject Win32_Processor | Select Name,LoadPercentage | Format-Table -HideTableHeaders"])
    for l in o.split("\n"):
        if not l.strip(): continue
        pp = l.split()
        if len(pp)>=2: s["cpu_name"]=" ".join(pp[:-1])[:60]
        if pp[-1].isdigit(): s["cpu_load_pct"]=int(pp[-1])
        break
    o = r(["nvidia-smi","--query-gpu=temperature.gpu,utilization.gpu,power.draw","--format=csv,noheader"])
    if o:
        pp=o.split(",")
        if len(pp)>=1: s["gpu_temp_c"]=int(pp[0].strip())
        if len(pp)>=2: s["gpu_util_pct"]=int(pp[1].strip().replace("%",""))
        if len(pp)>=3: s["gpu_power_w"]=float(pp[2].strip().replace("W",""))
    o = r(["powershell","-NoProfile","-Command","Get-WmiObject Win32_LogicalDisk -Filter DriveType=3 | Select DeviceID,Size,FreeSpace | Format-Table -HideTableHeaders"])
    s["disks"]={}
    for l in o.split("\n"):
        pp=l.strip().split()
        if len(pp)>=3 and pp[0].endswith(":"): sz,fr=int(pp[1]),int(pp[2]); s["disks"][pp[0]]={"total_gb":round(sz/1073741824,1),"free_gb":round(fr/1073741824,1),"used_pct":round((sz-fr)/sz*100,0)}
    o = r(["powershell","-NoProfile","-Command","Get-Counter '\\Thermal Zone Information(*)\\Temperature' -ErrorAction SilentlyContinue | Select -Expand CounterSamples | Select -Expand CookedValue"])
    temps=[float(x) for x in o.split() if x.replace(".","").replace("-","").isdigit() and float(x)>280]
    if temps: s["cpu_temp_c"]=round(min(temps)-273.15,1)
    s["agent"]="hermes-cron"; token=pt()
    try:
        resp=urllib.request.urlopen(urllib.request.Request("https://www.lianyue.fun/api/pc-stats",data=json.dumps(s).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer "+token},method="POST"),timeout=15)
        rj=json.loads(resp.read())
    except Exception as e: rj={"error":str(e)}
    ok="ok" if rj.get("ok") else "FAIL"
    print("[pc-stats] {} mem={}% cpu={}% gpu={}C".format(ok,s.get("mem_used_pct"),s.get("cpu_load_pct"),s.get("gpu_temp_c")))

def fg_title():
    if os.name!="nt": return "n/a"
    try:
        u32=ctypes.windll.user32
        hwnd=u32.GetForegroundWindow()
        if not hwnd: return "n/a"
        buf=ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(hwnd,buf,256)
        title=buf.value.strip()
        pid=ctypes.c_ulong()
        u32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        exe=""
        try:
            raw=_run(["tasklist","/fo","csv","/nh","/fi","PID eq {}".format(pid.value)],timeout=3).stdout
            rows=list(csv.reader(raw.splitlines()))
            if rows and rows[0]: exe=os.path.splitext(rows[0][0])[0]
        except Exception: pass
        return (exe+": "+title if exe and title else title or exe or "n/a")[:80]
    except Exception:
        return "n/a"

# ---- 单实例会话锁：后端 token 校验，防止多标签页并发写 ----
_SESSION = {"token": None, "ts": 0.0}
_SESSION_TTL = 8.0  # 秒，超过该时间无心跳则视为失活
import secrets as _secrets
_DESKTOP_CLAIM_SECRET = _secrets.token_urlsafe(24)
def claim_session(force=False):
    now = time.time()
    if not force and _SESSION["token"] and now - _SESSION["ts"] < _SESSION_TTL:
        return None  # 已有活跃会话
    tok = _secrets.token_hex(8)
    _SESSION["token"] = tok
    _SESSION["ts"] = now
    return tok
def heartbeat_session(tok):
    if tok and tok == _SESSION["token"]:
        _SESSION["ts"] = time.time()
        return True
    return False
def check_session(tok):
    if not _SESSION["token"]: return False
    if time.time() - _SESSION["ts"] > _SESSION_TTL:
        _SESSION["token"] = None
        return False
    return tok == _SESSION["token"]

# ---- 崩溃恢复：标记文件 + 全局异常钩子 ----
_LAST_CRASH = None  # 启动时读取的上次崩溃记录
def crash_read_last():
    try:
        with open(P["crash"], encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
def crash_mark_running():
    global _LAST_CRASH
    prev = crash_read_last()
    if prev and prev.get("reason") not in ("clean exit", "running"):
        _LAST_CRASH = prev
    if prev and prev.get("reason") == "running":
        _LAST_CRASH = prev  # 上次没正常退出
    ts = datetime.now().isoformat()
    try:
        with open(P["crash"], "w", encoding="utf-8") as f:
            json.dump({"ts": ts, "reason": "running"}, f)
    except Exception: pass
def crash_mark_clean():
    ts = datetime.now().isoformat()
    try:
        with open(P["crash"], "w", encoding="utf-8") as f:
            json.dump({"ts": ts, "reason": "clean exit"}, f)
    except Exception: pass
def crash_record(reason):
    ts = datetime.now().isoformat(); reason_s = str(reason)[:300]
    try:
        rev = lc().get("state_revision", 0)
        crash_data = {"ts": ts, "reason": reason_s, "version": "0.2.0", "revision": rev}
    except Exception:
        crash_data = {"ts": ts, "reason": reason_s, "version": "0.2.0"}
    try:
        with open(P["crash"], "w", encoding="utf-8") as f:
            json.dump(crash_data, f)
    except Exception: pass
def crash_last():
    return _LAST_CRASH
def _install_excepthook():
    def hook(typ, val, tb):
        try:
            msg = "".join(traceback.format_exception(typ, val, tb))[-500:]
            crash_record("uncaught: " + msg)
        except Exception: pass
        _bl("EXC: " + repr(val))
    sys.excepthook = hook
_install_excepthook()

class WebApp:
    def __init__(self):
        self.focus=""; self.alive=True; self._coach_tick=0
        self._fg_started=False
        self._fine_grained=lc().get("privacy",{}).get("fine_grained_fg_enabled",True)
        self._start_ts = time.time()  # for coach session duration tracking
        self._fg_data=lf(); self._fg_last_flush=time.time()
        threading.Thread(target=self._coach_tick_loop, daemon=True).start()
        if lc().get("privacy",{}).get("monitoring_consent",False): self.start_foreground_tracking()
        if not lc().get("app_catalog"): start_catalog_job()
        # Reconcile persisted tasks after launch; old assignments can be stale.
        start_infer_apps()
    def start_foreground_tracking(self):
        if self._fg_started: return
        self._fg_started=True
        # ---- Foreground tracking: prefer event-driven if available ----
        threading.Thread(target=self._fg_loop, daemon=True).start()
    def _fg_loop(self):
        while self.alive:
            self.focus=fg_title()
            if not self._fine_grained: self.focus=self.focus.split(":",1)[0]
            k=((self.focus.split(":",1)[0] if ":" in self.focus else self.focus)[:40] or "n/a")
            if k.strip().lower() not in _FG_IGNORED:
                with _CFG_LOCK:
                    self._fg_data[k]=self._fg_data.get(k,0)+2
                    if time.time()-self._fg_last_flush >= 15:
                        sf(clean_fg(self._fg_data)); self._fg_last_flush=time.time()
            if time.time()-self._coach_tick>60:
                self._coach_tick=time.time()
                try:
                    with _CFG_LOCK:
                        c=ensure_goal_state(lc())
                        decision=adaptive.passive_review(c)
                        if decision: save_goal_state(c); evlog(c,"adaptive_adjust",decision.get("reason",""),decision)
                        sc(c)
                except Exception: pass
            time.sleep(2)

    def _coach_tick_loop(self):
        """Separate coach tick loop for event-driven FG mode."""
        while self.alive:
            if time.time()-self._coach_tick>60:
                self._coach_tick=time.time()
                try:
                    with _CFG_LOCK:
                        c=ensure_goal_state(lc())
                        decision=adaptive.passive_review(c)
                        if decision: save_goal_state(c); evlog(c,"adaptive_adjust",decision.get("reason",""),decision)
                        sc(c)
                except Exception: pass
            time.sleep(2)

    def _fg_current_focus(self):
        """Get current foreground focus — from watcher or polling."""
        return self.focus
    def state(self):
        c=ensure_goal_state(lc()); flags=c.get("done_flags",[])
        public_model=copy.deepcopy(c.get("user_model",{}))
        public_model.pop("fsrs_review_logs",None); public_model.pop("fsrs_scheduler",None)
        for skill in (public_model.get("skills",{}) or {}).values():
            if isinstance(skill,dict): skill.pop("fsrs_card",None)
        return {"goal":c.get("goal",""),"goals":c.get("goals",[]),"active_goal":c.get("active_goal",0),"tasks":task_items(c.get("tasks",[]),flags),"done_flags":list(flags),
            "completion_pct":c.get("completion_pct",0),"task_apps":merged_task_apps(c),
            "manual_task_apps":c.get("manual_task_apps",[]),"ai_task_apps":c.get("ai_task_apps",[]),
            "task_app_categories":c.get("task_app_categories",[]),"app_catalog_ready":bool(c.get("app_catalog")),
            "legacy_app_assignment":has_legacy_app_assignment(c),
            "app_catalog":c.get("app_catalog",{}),
            "fg":dict(sorted(((k,v) for k,v in self._fg_data.items() if k!="n/a"),key=lambda x:-x[1])[:8]),"history":lh()[-10:],
            "focus":self._fg_current_focus(),"autostart":os.path.exists(P["as"]),
            "plan_locked":c.get("plan_locked",False),"schedule":c.get("schedule",{}),"task_gen":gen_settings(c),
            "time_blocks":ensure_time_blocks(c),
            "insights":insights_for(c),
            "coach_context":c.get("coach_context",{}),"coach_messages":c.get("coach_messages",[])[-20:],
            "task_generation":c.get("task_generation",{}),
            "goal_details":goal_details(c),
            "goal_contract":adaptive.goal_contract(goal_details(c)),
            "goal_readiness":adaptive.goal_readiness(goal_details(c)),
            "first_task":{"started_at":c.get("first_task_started_at",""),"task_id":c.get("first_task_id","")},
            "product_funnel":c.get("product_funnel",{}),
            "last_acceptance":c.get("last_acceptance",{}),
            "feedback_history":c.get("feedback_history",[])[-30:],
            "user_model":public_model, "knowledge_graph":adaptive.knowledge_graph(c),
            "motivation":c.get("motivation",{"points":0,"streak":0,"best_streak":0,"history":[]}),
            "last_review":c.get("last_review",{}),"next_cycle_context":c.get("next_cycle_context",{}),
            "adaptive_task_gen":effective_gen_settings(c),
            "deepseek_configured":valid_deepseek_key(dk()),
            "privacy":c.get("privacy",copy.deepcopy(CFG0["privacy"])),"workspace":c.get("workspace",""),
            "focus_guard":c.get("focus_guard",CFG0["focus_guard"]),
            "agent_runs":[r for r in list((c.get("agent_runs",{}) or {}).values())[-50:] if r.get("goal_id")==gid(c)],
            "focus_context":focus_context(c),
            "focus_profile":focus_profile(c),
            "break_active":break_active(c),"breaks":c.get("breaks",[])[-20:],"events":c.get("events",[])[-80:],
            "quit_attempts":c.get("quit_attempts",[])[-50:],"archives":c.get("archives",[])[-30:],
             "last_crash":crash_last(),"undo_available":bool(_UNDO)}

WEBAPP = None
GEN_STATUS={"running":False,"step":"空闲","message":"","ts":0}
GEN_TERMINAL_STEPS={"完成","失败","completed","failed"}
GEN_LOCK=threading.Lock()
GEN_START_LOCK=threading.Lock()
_UNDO=[]

def _agent_tools(c):
    """Build the small, permission-checked tool surface for one run."""
    target=next((t for t in c.get("tasks",[]) if not task_done(t)),{})
    target_id=target.get("id")
    def current():
        latest=ensure_goal_state(lc())
        task=next((t for t in latest.get("tasks",[]) if t.get("id")==target_id),None)
        return latest,task
    def observe(_args):
        latest,task=current(); task=task or {}; ctx=focus_context(latest)
        foreground=WEBAPP._fg_current_focus() if WEBAPP else ""
        status=task.get("status","pending") if task else "pending"
        next_action={}
        history=_args.get("history",[]) if isinstance(_args,dict) else []
        last=history[-1] if history else {}
        last_result=last.get("result",{}) if isinstance(last,dict) else {}
        if last.get("action",{}).get("name") == "run_check" and last_result.get("pass") and last_result.get("finished"):
            next_action={"name":"complete_task","args":{"verified":True},"reason":"确定性验收已通过"}
        elif status == "pending":
            next_action={"name":"set_task_status","args":{"status":"doing"},"reason":"开始当前任务"}
        elif status == "doing":
            candidates=focus_task_apps(latest)
            if candidates and last.get("action",{}).get("name") != "open_app" and not any(os.path.splitext(task_text(x))[0].lower() in foreground.lower() for x in candidates):
                next_action={"name":"open_app","args":{"exe":candidates[0]},"reason":"打开当前任务应用"}
            elif task.get("evidence"):
                next_action={"name":"run_check","args":{},"reason":"验证当前任务证据"}
            else:
                next_action={"name":"pause","args":{},"reason":"等待用户提交交付物"}
        return {"ok":True,"task":ctx,"foreground":foreground,
                "evidence":as_list(task.get("evidence",[])) if task else [],"status":status,
                "next_action":next_action}
    def set_status(args):
        status=task_text(args.get("status"))
        with _CFG_LOCK:
            latest,task=current()
            if not task or status not in ("pending","doing","skipped"): raise ValueError("invalid task status")
            task["status"]=status; save_goal_state(latest); sc(latest)
        return {"ok":True,"status":status}
    def open_app(args):
        exe=task_text(args.get("exe")).lower(); app=next((a for a in applications() if a.get("exe","").lower()==exe),None)
        if not app or not app.get("path") or not os.path.exists(app["path"]): raise ValueError("application unavailable")
        subprocess.Popen([app["path"]],creationflags=_CNW); return {"ok":True,"exe":app["exe"]}
    def focus_app(args):
        title=task_text(args.get("title") or args.get("window"))
        if not title or not focus_window(title): raise ValueError("window not found")
        return {"ok":True,"title":title}
    root=os.path.abspath(c.get("workspace") or os.path.expanduser("~"))
    if not os.path.isdir(root): raise ValueError("请先在设置中选择有效的 Agent 工作区")
    def safe_path(value):
        path=os.path.abspath(os.path.join(root,task_text(value)))
        if not path_under(root,path): raise ValueError("path outside workspace")
        return path
    def list_files(args):
        base=safe_path(args.get("path","."));
        if not os.path.isdir(base): raise ValueError("directory not found")
        return {"ok":True,"files":[os.path.relpath(os.path.join(base,n),root) for n in os.listdir(base)][:200]}
    def read_file(args):
        path=safe_path(args.get("path"));
        if not os.path.isfile(path): raise ValueError("file not found")
        with open(path,encoding="utf-8",errors="replace") as f: text=f.read(200000)
        return {"ok":True,"path":os.path.relpath(path,root),"content":text}
    def run_check(args):
        _,task=current()
        if not task: return {"ok":True,"finished":True}
        details=evidence_details(task.get("evidence",[]))
        if _ACCEPTANCE_MOD:
            verdict=_ACCEPTANCE_MOD.check_evidence(task,details)
            return {"ok":True,"finished":bool(verdict.pass_ and not verdict.needs_llm),"pass":bool(verdict.pass_),"reason":verdict.reason}
        return {"ok":True,"finished":False,"reason":"等待验收器"}
    def upload_evidence(args):
        path=safe_path(args.get("path"));
        if not os.path.isfile(path): raise ValueError("evidence file not found")
        with _CFG_LOCK:
            latest,task=current()
            if not task: raise ValueError("no active task")
            target=STORE.add_attachment(path, os.path.basename(path))
            ev=as_list(task.get("evidence",[]))
            if target not in ev: ev.append(target)
            task["evidence"]=ev; save_goal_state(latest); sc(latest)
        return {"ok":True,"path":target}
    def complete_task(args):
        if not args.get("verified"): raise ValueError("completion requires verified evidence")
        with _CFG_LOCK:
            latest,task=current()
            if not task or not task.get("evidence"): raise ValueError("evidence required")
            task["status"]="done"; idx=latest["tasks"].index(task); latest.setdefault("done_flags",[])[idx]=True; sync_pct(latest); save_goal_state(latest); sc(latest)
        return {"ok":True,"finished":True}
    def write_file(args):
        path=safe_path(args.get("path")); content=args.get("content","")
        if not isinstance(content,str) or len(content)>500000: raise ValueError("invalid file content")
        os.makedirs(os.path.dirname(path),exist_ok=True)
        with open(path,"w",encoding="utf-8") as f: f.write(content)
        return {"ok":True,"path":os.path.relpath(path,root)}
    def delete_file(args):
        path=safe_path(args.get("path"));
        if not os.path.isfile(path): raise ValueError("file not found")
        if os.path.basename(path).lower() in {"task-panel.pyw","task-config.json"}: raise ValueError("protected file")
        os.remove(path); return {"ok":True,"path":os.path.relpath(path,root)}
    def run_command(args):
        argv=args.get("argv")
        if not isinstance(argv,list) or not argv or any(not isinstance(x,str) for x in argv): raise ValueError("argv required")
        if argv[0].lower() not in {"python","python.exe","py"}: raise ValueError("command not allowed")
        out=subprocess.run(argv,cwd=root,capture_output=True,text=True,timeout=30,shell=False)
        return {"ok":out.returncode==0,"returncode":out.returncode,"stdout":out.stdout[-4000:],"stderr":out.stderr[-4000:]}
    def permanent_allow(_args):
        if not getattr(WEBAPP,"_focus_guard",None): raise ValueError("focus guard unavailable")
        WEBAPP._focus_guard._allow_current(-1); return {"ok":True}
    return {"observe":observe,"set_task_status":set_status,"open_app":open_app,
            "focus_window":focus_app,"list_files":list_files,"read_file":read_file,
            "run_check":run_check,"upload_evidence":upload_evidence,
            "complete_task":complete_task,"pause":lambda args:{"ok":True,"paused":True},
            "request_confirmation":lambda args:{"ok":True,"requires_confirmation":True},
            "write_file":write_file,"delete_file":delete_file,"run_command":run_command,
            "permanent_allow":permanent_allow}

def _agent_planner(run, observation):
    if observation.get("status") == "pending":
        return {"name":"set_task_status","args":{"status":"doing"},"reason":"启动当前任务"}
    return {"name":"observe","args":{},"reason":"等待新的任务证据"}

def _agent_orchestrator(c):
    if not _agent_mod: raise RuntimeError("agent runtime unavailable")
    planner=_agent_planner
    if valid_deepseek_key(dk()) and c.get("privacy",{}).get("cloud_ai_enabled",True):
        def ai_planner(run, observation):
            try:
                result=deepseek_json([
                    {"role":"system","content":"你是受控桌面任务 Agent。一次只能选择一个动作。只返回 JSON，动作必须是 observe、open_app、focus_window、read_file、list_files、run_check、upload_evidence、set_task_status、complete_task、request_confirmation、pause、write_file、delete_file、run_command、permanent_allow 之一。写文件、删除、命令和永久放行必须 requires_confirmation=true。不得直接宣称完成；完成必须由 run_check 结果证明。"},
                    {"role":"user","content":json.dumps({"run":run,"observation":observation},ensure_ascii=False)}],900,0.1,20,0)
                if isinstance(result,dict) and result.get("name"): return result
            except Exception: pass
            return _agent_planner(run,observation)
        planner=ai_planner
    def save_runs(data):
        c["agent_runs"]=copy.deepcopy(data)
        with _CFG_LOCK:
            latest=ensure_goal_state(lc()); latest["agent_runs"]=copy.deepcopy(data); sc(latest)
    return _agent_mod.AgentOrchestrator(
        load_state=lambda:lc().get("agent_runs",{}), save_state=save_runs,
        tools=_agent_tools(c), planner=planner)

def _agent_loop(c, run_id):
    """Run bounded low-risk steps in the background; confirmation pauses it."""
    try:
        orch=_agent_orchestrator(c)
        for _ in range(20):
            latest=lc().get("agent_runs",{}).get(run_id,{})
            if latest.get("status") in {"paused","awaiting_confirmation","completed","failed","blocked"}:
                break
            run=orch.step(run_id)
            if lc().get("agent_runs",{}).get(run_id,{}).get("status") == "paused": break
            if run.get("status") in {"awaiting_confirmation","paused","completed","failed","blocked"}: break
            time.sleep(0.2)
    except Exception as exc:
        _bl("agent loop: " + repr(exc))

def push_undo(c, label):
    _UNDO.append((task_text(label), copy.deepcopy(c)))
    del _UNDO[:-5]

def pop_undo(c):
    if not _UNDO: return None
    label, snap = _UNDO.pop()
    c.clear(); c.update(copy.deepcopy(snap)); save_goal_state(c); sc(c)
    return label

def gen_status(step, message="", **extra):
    GEN_STATUS.update({"running":step not in GEN_TERMINAL_STEPS,"step":step,"message":message,"ts":time.time()})
    GEN_STATUS.update(extra)

def _start_gen_job():
    job_id=new_id("gen")
    gen_status("queued","waiting for generation job",job_id=job_id,mode="ai",error="")
    def job():
        with GEN_LOCK:
            try:
                result=gen_tasks()
                if str(result).startswith("CONFLICT"): return
                gen_status("recognizing_apps","matching tasks to installed applications")
                start_infer_apps(wait=True)
                gen_status("completed","tasks and app recognition completed")
            except Exception as e:
                try:
                    fallback_tasks(ensure_goal_state(lc()),str(e)); gen_status("completed","local fallback tasks generated",mode="fallback")
                except Exception as fallback_error:
                    gen_status("failed",str(fallback_error),mode="error",error=str(fallback_error))
    return JOBS.submit(job, key="generate")
    return {"message":"generation started","job_id":job_id}

def start_gen_job():
    with GEN_START_LOCK:
        readiness = adaptive.goal_readiness(goal_details(ensure_goal_state(lc())))
        if not readiness["ready"]:
            missing="、".join(readiness.get("missing") or [])
            return {"ok":False, "code":"goal_not_ready", "message":"请先补全目标契约" + ("：还缺"+missing if missing else "。"), "readiness":readiness}
        c=ensure_goal_state(lc()); record_product_event(c, "goal_ready"); record_product_event(c, "first_task_generated"); save_goal_state(c)
        if GEN_STATUS.get("running"):
            return {"ok":True, "message":"generation already running","job_id":GEN_STATUS.get("job_id","")}
        _start_gen_job()
        return {"ok":True, "message":"generation started","job_id":GEN_STATUS.get("job_id","")}

def processes():
    try: raw=_run(["tasklist","/fo","csv","/nh"],timeout=10).stdout
    except Exception: return []
    return sorted(set(row[0] for row in csv.reader(raw.splitlines()) if row))

def icon_for(path):
    if not path or not os.path.exists(path): return ""
    os.makedirs(P["icons"],exist_ok=True)
    name=hashlib.sha1(path.lower().encode("utf-8","ignore")).hexdigest()+".png"
    out=os.path.join(P["icons"],name)
    if os.path.exists(out): return "/icons/"+name
    ps="$p={};$o={};Add-Type -AssemblyName System.Drawing;$i=[System.Drawing.Icon]::ExtractAssociatedIcon($p);if($i){{$b=$i.ToBitmap();$b.Save($o,[System.Drawing.Imaging.ImageFormat]::Png);$b.Dispose();$i.Dispose()}}".format(json.dumps(path),json.dumps(out))
    try: _run(["powershell","-NoProfile","-Command",ps],timeout=5)
    except Exception: pass
    return "/icons/"+name if os.path.exists(out) else ""

def installed_applications():
    ps = r"""
$apps = @()
$shell = New-Object -ComObject WScript.Shell
$dirs = @("$env:ProgramData\Microsoft\Windows\Start Menu\Programs","$env:APPDATA\Microsoft\Windows\Start Menu\Programs")
foreach ($d in $dirs) {
  if (Test-Path $d) {
    Get-ChildItem $d -Recurse -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {
      try {
        $s=$shell.CreateShortcut($_.FullName)
        if ($s.TargetPath -and $s.TargetPath.ToLower().EndsWith(".exe")) {
          $apps += [pscustomobject]@{ name=[IO.Path]::GetFileNameWithoutExtension($_.Name); exe=[IO.Path]::GetFileName($s.TargetPath); path=$s.TargetPath; title="已安装应用"; source="installed" }
        }
      } catch {}
    }
  }
}
$apps | ConvertTo-Json -Compress
"""
    try:
        raw=_run(["powershell","-NoProfile","-Command",ps],timeout=20,encoding="gbk",errors="replace").stdout.strip()
        data=json.loads(raw) if raw else []
        if isinstance(data,dict): data=[data]
        return [{"exe":task_text(a.get("exe","")),"name":task_text(a.get("name","")),"title":task_text(a.get("title","")),"path":task_text(a.get("path","")),"source":"installed"} for a in data if task_text(a.get("exe",""))]
    except Exception:
        return []

def applications():
    merged={}
    if os.name=="nt":
        try:
            pid_to_exe={}; pid_to_path={}
            raw=_run(["tasklist","/fo","csv","/nh"],timeout=10).stdout
            for row in csv.reader(raw.splitlines()):
                if len(row)>1 and row[1].isdigit(): pid_to_exe[int(row[1])]=row[0]
            ps_paths="Get-CimInstance Win32_Process | Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress"
            rawp=_run(["powershell","-NoProfile","-Command",ps_paths],timeout=10).stdout.strip()
            datap=json.loads(rawp) if rawp else []
            if isinstance(datap,dict): datap=[datap]
            for p in datap:
                if p.get("ProcessId") and p.get("ExecutablePath"): pid_to_path[int(p["ProcessId"])]=p["ExecutablePath"]
            user32=ctypes.windll.user32
            CB=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
            @CB
            def enum(hwnd, lp):
                if not user32.IsWindowVisible(hwnd): return True
                buf=ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd,buf,256)
                title=buf.value.strip()
                if not title: return True
                pid=ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                exe=pid_to_exe.get(pid.value,"")
                if exe and exe.lower() not in ("task-panel.pyw","python.exe","pythonw.exe"):
                    path=pid_to_path.get(pid.value,"")
                    merged[exe.lower()]={"exe":exe,"name":os.path.splitext(exe)[0],"title":title,"path":path,"source":"running"}
                return True
            user32.EnumWindows(enum,None)
        except Exception:
            pass
    for a in installed_applications():
        if a["exe"].lower() not in merged: merged[a["exe"].lower()]=a
    if merged:
        apps=sorted(merged.values(),key=lambda x:(x.get("source")!="running",x.get("name","").lower()))
        for a in apps: a["icon"]=icon_for(a.get("path",""))
        return apps
    ps = r"""
$items = @()
Get-Process | ForEach-Object {
  $path = $null; $desc = $null; $title = $_.MainWindowTitle
  try { $path = $_.Path } catch {}
  if ($path) {
    try { $desc = (Get-Item $path).VersionInfo.FileDescription } catch {}
  }
  $name = if ($desc) { $desc } else { $_.ProcessName }
  $items += [pscustomobject]@{ exe = ($_.ProcessName + ".exe"); name = $name; title = $title }
}
$items | Where-Object { $_.exe -and $_.name } | Sort-Object exe -Unique | ConvertTo-Json -Compress
"""
    try:
        raw=_run(["powershell","-NoProfile","-Command",ps],timeout=12).stdout.strip()
        data=json.loads(raw) if raw else []
        if isinstance(data,dict): data=[data]
        apps=[]
        for a in data:
            exe=task_text(a.get("exe",""))
            name=task_text(a.get("name","")).replace(".exe","")
            title=task_text(a.get("title",""))
            if exe: apps.append({"exe":exe,"name":name or exe,"title":title,"path":"","source":"running","icon":""})
        windowed=[a for a in apps if a.get("title")]
        if windowed: return windowed
        return apps
    except Exception:
        return [{"exe":p,"name":p,"title":""} for p in processes()]

def ai_json(system,prompt,max_tokens=1000):
    try: return deepseek_json([{"role":"system","content":system},{"role":"user","content":prompt}],max_tokens,0.1,35,1)
    except AIError: return {}

_USABLE_BAD={"taskmgr.exe","explorer.exe","applicationframehost.exe","python.exe","pythonw.exe"}
def usable_apps(c=None):
    return [a for a in applications() if a.get("exe") and a.get("exe","").lower() not in _USABLE_BAD]

def ensure_app_catalog(c, apps=None):
    apps=apps or usable_apps(c)
    sig=hashlib.sha1(json.dumps(sorted((a.get("exe",""),a.get("name","")) for a in apps),ensure_ascii=False).encode()).hexdigest()
    if c.get("app_catalog_sig")=="manual" and c.get("app_catalog"): return add_uncategorized(c["app_catalog"],apps)
    if c.get("app_catalog_sig")==sig and c.get("app_catalog"): return c["app_catalog"]
    # ---- Stage 1: deterministic pre-classification ----
    preclassified = {}
    remaining = apps[:240]
    if _APPRULES:
        try:
            preclassified, remaining = _APPRULES.preclassify_apps(apps[:240])
        except Exception: pass
    rows=[{"exe":a.get("exe",""),"name":a.get("name",""),"title":a.get("title","")} for a in remaining]
    prompt="Classify installed apps into broad categories and subcategories.\napps:\n{}\nReturn JSON only: {{\"categories\":[{{\"name\":\"学习办公\",\"children\":[{{\"name\":\"文档写作\",\"apps\":[\"WINWORD.EXE\"]}}]}}]}}. Use exact exe names only.".format(json.dumps(rows,ensure_ascii=False))
    catalog=ai_json("Return compact JSON only. Make useful broad categories and subcategories for deciding which apps a task needs.",prompt,3500) if rows else {"categories":[]}
    if not isinstance(catalog,dict): catalog={}
    if not isinstance(catalog.get("categories"),list): catalog={"categories":[]}
    # ---- Merge preclassified apps into the AI catalog ----
    if preclassified and catalog.get("categories") is not None:
        for label, exes in preclassified.items():
            cat_name, sub_name = label.split("/", 1) if "/" in label else (label, "通用")
            cat = next((x for x in catalog["categories"] if x.get("name") == cat_name), None)
            if not cat:
                cat = {"name": cat_name, "children": []}
                catalog["categories"].append(cat)
            child = next((x for x in cat.get("children", []) if x.get("name") == sub_name), None)
            if not child:
                child = {"name": sub_name, "apps": []}
                cat.setdefault("children", []).append(child)
            child["apps"] = sorted(set(child.get("apps", []) + exes), key=str.lower)
    valid={a.get("exe","").lower():a.get("exe","") for a in apps}
    for cat in catalog.get("categories",[]):
        if not isinstance(cat,dict): continue
        for ch in cat.get("children",[]):
            if not isinstance(ch,dict): continue
            ch["apps"]=[valid[x.lower()] for x in ch.get("apps",[]) if task_text(x).lower() in valid]
    catalog=add_uncategorized(catalog,apps)
    c["app_catalog"]=catalog; c["app_catalog_sig"]=sig
    return catalog

def add_uncategorized(catalog, apps):
    valid={a.get("exe","").lower():a.get("exe","") for a in apps if a.get("exe")}
    used=set()
    for cat in catalog.get("categories",[]):
        for ch in cat.get("children",[]):
            clean=[]
            local=set()
            for x in ch.get("apps",[]):
                key=task_text(x).lower()
                if key in valid and key not in local:
                    local.add(key); used.add(key); clean.append(valid[key])
            ch["apps"]=clean
    missing=[exe for key,exe in valid.items() if key not in used]
    if not missing: return catalog
    cats=catalog.setdefault("categories",[])
    other=next((x for x in cats if x.get("name")=="未分类"),None)
    if not other:
        other={"name":"未分类","children":[{"name":"待整理","apps":[]}]} ; cats.append(other)
    child=other.setdefault("children",[{"name":"待整理","apps":[]}])[0]
    child["apps"]=sorted(set(child.get("apps",[])+missing),key=str.lower)
    return catalog

def normalize_catalog(catalog):
    """清理用户编辑的分类：仅去重同一应用在不同小类的重复，保留用户定义的结构，不自动补未分类。"""
    out_cats=[]
    for cat in catalog.get("categories",[]):
        chs=[]
        for ch in cat.get("children",[]):
            clean=[]
            seen=set()
            for x in ch.get("apps",[]):
                key=task_text(x).lower()
                if key and key not in seen:
                    seen.add(key); clean.append(x)
            chs.append({"name":ch.get("name",""),"apps":clean})
        out_cats.append({"name":cat.get("name",""),"children":chs})
    return {"categories":out_cats}

def catalog_labels(catalog):
    out=[]
    for cat in catalog.get("categories",[]):
        for ch in cat.get("children",[]):
            out.append(cat.get("name","")+"/"+ch.get("name",""))
    return [x for x in out if x.strip("/")]

def apps_for_labels(catalog, labels):
    want={task_text(x).lower() for x in labels}; out=[]
    for cat in catalog.get("categories",[]):
        for ch in cat.get("children",[]):
            label=(cat.get("name","")+"/"+ch.get("name","")).lower()
            if label in want or ch.get("name","").lower() in want or cat.get("name","").lower() in want: out += ch.get("apps",[])
    return out

def infer_task_apps(c):
    task_objs=[x for x in normalize_tasks(c.get("tasks",[]), gid(c), c.get("done_flags",[])) if task_text(x)]
    if not task_objs: return {"ok":False,"reason":"no tasks","categories":[],"assignments":{},"all_apps":[]}
    blocked={task_text(x).lower() for x in c.get("blocklist",[])}
    apps=[a for a in usable_apps(c) if a.get("exe","").lower() not in blocked]
    tasks=[{"index":i,"title":t.get("title",""),"type":t.get("type",""),"expected_output":t.get("expected_output","")} for i,t in enumerate(task_objs)]
    cloud_enabled=bool(c.get("privacy",{}).get("cloud_ai_enabled",True))
    # Local rules cover common tasks without a cloud key. Unknown tasks still
    # fall through to the AI path below when a key is available.
    if _APPRULES and (not cloud_enabled or not valid_deepseek_key(dk())):
        rule_cats = _APPRULES.smart_filter_tasks(tasks)
        assignments = {}; all_apps = set(); categories = set()
        for idx, cats in rule_cats.items():
            candidates = _APPRULES.fallback_apps_for_categories(cats, apps, c.get("task_app_memory", {}))
            if not candidates: continue
            categories.update(cats); all_apps.update(candidates)
            assignments[idx] = {"required_apps": [], "allowed_apps": candidates[:4],
                                "reason": "本地规则匹配任务类型，可选工作应用", "confidence": 0.75}
        if assignments:
            return {"ok":True,"categories":sorted(categories),"assignments":assignments,
                    "all_apps":sorted(all_apps,key=str.lower)}
        # ponytail: keep unknown tasks usable; prefer the user's existing desktop
        # over returning an empty assignment that makes FocusGuard unusable.
        fallback=[a.get("exe") for a in apps if a.get("exe")]
        if fallback:
            return {"ok":True,"categories":[],"assignments":{
                i:{"required_apps":[],"allowed_apps":fallback[:4],"reason":"使用当前工作桌面应用","confidence":0.35}
                for i in range(len(task_objs))},"all_apps":fallback[:20]}
    if not cloud_enabled or not valid_deepseek_key(dk()): return {"ok":False,"reason":"no valid key","categories":[],"assignments":{},"all_apps":[]}
    catalog=ensure_app_catalog(c,apps); labels=catalog_labels(catalog)
    valid={a.get("exe","").lower():a.get("exe","") for a in apps if a.get("exe")}
    category_result=ai_json("Return compact JSON only. Assign existing categories to each task. Never invent categories.","categories:\n{}\ntasks:\n{}\nReturn {{\"assignments\":[{{\"task_index\":0,\"categories\":[\"category/subcategory\"]}}]}}".format(json.dumps(labels,ensure_ascii=False),json.dumps(tasks,ensure_ascii=False)),1200)
    if not isinstance(category_result,dict) or not isinstance(category_result.get("assignments"),list):
        return {"ok":False,"reason":"category response invalid","categories":[],"assignments":{},"all_apps":[]}
    task_categories={}
    wanted={x.lower():x for x in labels}
    for row in (category_result.get("assignments",[]) if isinstance(category_result.get("assignments",[]),list) else []):
        if not isinstance(row,dict): continue
        try: idx=int(row.get("task_index"))
        except Exception: continue
        if idx<0 or idx>=len(task_objs): continue
        raw_cats=row.get("categories",[]) if isinstance(row.get("categories",[]),list) else []
        cats=[wanted[x.lower()] for x in raw_cats if task_text(x).lower() in wanted]
        task_categories[idx]=cats[:4]
    mem=c.get("task_app_memory",{})
    candidate_rows=[]
    for idx in range(len(task_objs)):
        cats=task_categories.get(idx,[]); key="|".join(sorted(cats)) or "default"
        candidates=set(apps_for_labels(catalog,cats)+mem.get(key,[]))
        candidates=[valid[x.lower()] for x in candidates if x.lower() in valid]
        candidate_rows.append({"task_index":idx,"categories":cats,"candidates":sorted(set(candidates),key=str.lower)[:40]})
    assignment_result=ai_json("Return compact JSON only. Assign apps per task. Use only candidates. required_apps means necessary; allowed_apps means helpful but optional. If no app is needed, return empty arrays.","tasks:\n{}\ncandidates:\n{}\nReturn {{\"assignments\":[{{\"task_index\":0,\"required_apps\":[\"exact.exe\"],\"allowed_apps\":[\"exact.exe\"],\"reason\":\"short\",\"confidence\":0.0}}]}}".format(json.dumps(tasks,ensure_ascii=False),json.dumps(candidate_rows,ensure_ascii=False)),2200)
    if not isinstance(assignment_result,dict) or not isinstance(assignment_result.get("assignments"),list):
        return {"ok":False,"reason":"assignment response invalid","categories":[],"assignments":{},"all_apps":[]}
    assignments={}; all_ai=set()
    for row in (assignment_result.get("assignments",[]) if isinstance(assignment_result.get("assignments",[]),list) else []):
        if not isinstance(row,dict): continue
        try: idx=int(row.get("task_index"))
        except Exception: continue
        if idx<0 or idx>=len(task_objs): continue
        candidate={x.lower() for x in next((r["candidates"] for r in candidate_rows if r["task_index"]==idx),[])}
        raw_required=row.get("required_apps",[]) if isinstance(row.get("required_apps",[]),list) else []
        raw_allowed=row.get("allowed_apps",[]) if isinstance(row.get("allowed_apps",[]),list) else []
        required=[valid[x.lower()] for x in raw_required if task_text(x).lower() in candidate]
        allowed=[valid[x.lower()] for x in raw_allowed if task_text(x).lower() in candidate]
        allowed=list(dict.fromkeys(required+allowed))[:8]
        assignments[idx]={"required_apps":required[:4],"allowed_apps":allowed,"reason":task_text(row.get("reason")),"confidence":app_confidence(row.get("confidence"))}
        all_ai.update(allowed)
    c["task_app_categories"]=sorted({x for cats in task_categories.values() for x in cats})
    for key, cats in (("|".join(sorted(v)) or "default", v) for v in task_categories.values()):
        if key in mem: mem[key]=list(dict.fromkeys(mem[key]))[:20]
    c["task_app_memory"]=mem
    return {"ok":True,"categories":c["task_app_categories"],"assignments":assignments,"all_apps":sorted(all_ai,key=str.lower)}

def remember_task_apps(c):
    key="|".join(sorted(c.get("task_app_categories",[]))) or "default"
    c.setdefault("task_app_memory",{})[key]=merged_task_apps(c)

def start_infer_apps(wait=False):
    def job():
        c=ensure_goal_state(lc())
        input_guard=generation_guard(c)
        try:
            result=infer_task_apps(c)
            with _CFG_LOCK:
                c=ensure_goal_state(lc())
                if generation_guard(c)!=input_guard: return
                if not result.get("ok",False):
                    reason=result.get("reason","应用匹配未完成")
                    evlog(c,"ai_apps_skipped" if reason=="no valid key" else "ai_apps_failed", "未配置有效 Key，保留已有应用" if reason=="no valid key" else reason); sc(c); return
                c["ai_task_apps"]=result.get("all_apps",[]); c["task_apps"]=merged_task_apps(c)
                assignments=result.get("assignments",{}); c["tasks"]=normalize_tasks(c.get("tasks",[]),gid(c),c.get("done_flags",[]))
                for i,t in enumerate(c["tasks"]):
                    if t.get("status")!="done":
                        a=assignments.get(i,{}); previous_allowed=as_list(t.get("allowed_apps"))
                        t["required_apps"]=a.get("required_apps",[]); t["allowed_apps"]=list(dict.fromkeys(previous_allowed+c.get("manual_task_apps",[])+a.get("allowed_apps",[])))[:8]
                        t["app_reason"]=a.get("reason",""); t["app_confidence"]=a.get("confidence",0)
                remember_task_apps(c); save_goal_state(c); evlog(c,"ai_apps","AI 自动识别应用",{"apps":c["ai_task_apps"]}); sc(c)
        except Exception as e:
            latest=ensure_goal_state(lc())
            if gid(latest)!=gid(c) or generation_guard(latest)!=input_guard:
                return
            evlog(latest,"ai_apps_failed",str(e)); sc(latest)
    if wait: return job()
    future = JOBS.submit(job, key="infer-apps")
    if wait and future:
        future.result()
    return future

def start_catalog_job():
    def job():
        c=ensure_goal_state(lc())
        input_guard=catalog_guard(c)
        try:
            ensure_app_catalog(c)
            result=copy.deepcopy(c.get("app_catalog",{})); sig=c.get("app_catalog_sig","")
            with _CFG_LOCK:
                c=ensure_goal_state(lc())
                if catalog_guard(c)!=input_guard: return
                c["app_catalog"]=result; c["app_catalog_sig"]=sig; evlog(c,"app_catalog","AI 应用分类完成"); sc(c)
        except Exception as e:
            latest=ensure_goal_state(lc())
            if catalog_guard(latest)!=input_guard:
                return
            evlog(c,"app_catalog_failed",str(e)); sc(c)
    return JOBS.submit(job, key="catalog")

def find_app(q, apps):
    q=task_text(q).lower()
    return next((a for a in apps if q and (a.get("exe","").lower()==q or q in a.get("name","").lower() or q in a.get("exe","").lower())),None)

def request_task_app(c, action, app_name):
    apps=usable_apps(c); app=find_app(app_name,apps)
    exe=app["exe"] if app else task_text(app_name)
    if not exe or (not app and action!="remove"): return False,"找不到这个应用（不在可用应用列表中，可能被系统应用过滤）"
    manual=c.setdefault("manual_task_apps",[]); blocked=c.setdefault("blocklist",[])
    if action=="remove":
        c["manual_task_apps"]=[x for x in manual if x.lower()!=exe.lower()]
        c["ai_task_apps"]=[x for x in c.get("ai_task_apps",[]) if x.lower()!=exe.lower()]
        for t in c.get("tasks",[]):
            if isinstance(t,dict):
                t["required_apps"]=[x for x in t.get("required_apps",[]) if task_text(x).lower()!=exe.lower()]
                t["allowed_apps"]=[x for x in t.get("allowed_apps",[]) if task_text(x).lower()!=exe.lower()]
        if exe.lower() not in {x.lower() for x in blocked}: blocked.append(exe)
        c["task_apps"]=merged_task_apps(c); remember_task_apps(c); save_goal_state(c); return True,"已移除"
    c["blocklist"]=[x for x in blocked if x.lower()!=exe.lower()]
    if exe.lower() not in {x.lower() for x in manual}: manual.append(exe)
    c["task_apps"]=merged_task_apps(c); remember_task_apps(c); save_goal_state(c); return True,"已手动加入"

def sync_pct(c):
    ts=c.get("tasks",[]); fl=c.get("done_flags",[])
    while len(fl)<len(ts): fl.append(False)
    for i,t in enumerate(ts):
        if isinstance(t,dict):
            if t.get("status")=="done": fl[i]=True
            else: t["status"]="done" if fl[i] else t.get("status","pending")
    c["done_flags"]=fl[:len(ts)]
    c["completion_pct"]=round(sum(1 for i,_ in enumerate(ts) if i<len(fl) and fl[i])*100/len(ts)) if ts else 0

def set_autostart(en):
    ex=sys.executable if getattr(sys,'frozen',False) else os.path.join(os.path.dirname(sys.executable),"pythonw.exe")
    arg="" if getattr(sys,'frozen',False) else ' "{}"'.format(os.path.join(APP_DIR,"task-panel.pyw"))
    if en:
        os.makedirs(os.path.dirname(P["as"]),exist_ok=True)
        with open(P["as"],"w") as f:
            f.write('@echo off\n:run\n"{}"{}\nif exist "{}" (del /q "{}" & exit /b 0)\ntimeout /t 2 /nobreak >nul\ngoto run\n'.format(ex,arg,P["stop"],P["stop"]))
    else:
        try: os.remove(P["as"])
        except OSError: pass
def request_stop():
    try:
        with open(P["stop"],"w",encoding="utf-8") as f: f.write("stop\n")
    except Exception: pass

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass
    def send_json(self, data, code=200):
        body=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def read_json(self):
        n=int(self.headers.get("Content-Length","0") or 0)
        if n > _MAX_JSON_BYTES: raise ValueError("request body too large")
        return json.loads(self.rfile.read(n).decode() or "{}")

    # ---- Security: Host/Origin validation + strict auth ----
    def _validate_host_origin(self):
        """Reject requests with suspicious Host or Origin headers.
        Returns True if the request passes validation."""
        host = (self.headers.get("Host") or "").lower()
        # Only allow localhost / 127.0.0.1
        if host and not (host.startswith("127.0.0.1:") or host.startswith("localhost:")):
            self.send_json({"ok":False,"message":"无效主机"}, 403)
            return False
        # Reject cross-origin requests
        origin = (self.headers.get("Origin") or "").lower()
        if origin and not (origin.startswith("http://127.0.0.1:") or origin.startswith("http://localhost:")):
            self.send_json({"ok":False,"message":"无效来源"}, 403)
            return False
        return True

    def _check_auth(self, exempt_set=None):
        """If strict auth is enabled, verify X-Session token for data endpoints.
        exempt_set: set of paths that are always allowed without auth."""
        path = self.path.split("?", 1)[0]
        # Static assets must load before the browser can claim its API session.
        if not path.startswith("/api/"):
            return True
        if exempt_set and path in exempt_set:
            return True
        tok = self.headers.get("X-Session", "")
        if not check_session(tok):
            self.send_json({"ok":False,"message":"需要有效的会话令牌"}, 401)
            return False
        return True
    def do_GET(self):
        if not self._validate_host_origin(): return
        if not self._check_auth(_AUTH_EXEMPT_GET): return
        if self.path=="/api/state": return self.send_json(WEBAPP.state())
        if self.path=="/api/export":
            data=ensure_goal_state(lc()); data["history"]=lh(); data["fg"]=lf(); return self.send_json(data)
        if self.path=="/api/storage-status":
            status=STORE.status(); status.update(STORE.health_report()); status["backups"]=STORE.list_backups(); return self.send_json(status)
        if self.path=="/api/insights":
            c=ensure_goal_state(lc()); return self.send_json(insights_for(c))
        if self.path=="/api/generate-status": return self.send_json(GEN_STATUS)
        if self.path=="/api/agent-state":
            c=ensure_goal_state(lc()); runs=c.get("agent_runs",{}) or {}
            key=gid(c); return self.send_json({"ok":True,"runs":[r for r in list(runs.values())[-50:] if r.get("goal_id")==key]})
        if self.path=="/api/claim":
            supplied = self.headers.get("X-TaskVerge-Desktop", "")
            tok = claim_session(bool(supplied) and _secrets.compare_digest(supplied, _DESKTOP_CLAIM_SECRET))
            if tok is None:
                return self.send_json({"ok":False,"message":"另一个窗口正在操作"},409)
            return self.send_json({"ok":True,"token":tok})
        if self.path=="/api/heartbeat":
            return self.send_json({"ok":True})
        if self.path=="/api/processes":
            apps=applications()
            return self.send_json({"apps":apps,"usable_apps":usable_apps(),"processes":[a["exe"] for a in apps]})
        if self.path=="/favicon.ico": self.send_response(204); self.end_headers(); return
        req_path=self.path.split("?",1)[0]
        if req_path.startswith("/icons/"):
            fp=os.path.abspath(os.path.join(P["icons"],req_path.split("/",2)[2]))
            if not path_under(P["icons"], fp) or not os.path.exists(fp): self.send_error(404); return
            data=open(fp,"rb").read(); self.send_response(200); self.send_header("Content-Type","image/png"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data); return
        p="/index.html" if req_path=="/" else req_path
        fp=os.path.abspath(os.path.join(WEB_DIR,p.lstrip("/")))
        if not path_under(WEB_DIR, fp) or not os.path.exists(fp): self.send_error(404); return
        data=open(fp,"rb").read(); mime=mimetypes.guess_type(fp)[0] or "application/octet-stream"
        if mime.startswith("text/") or mime in ("application/javascript","application/json"): mime += "; charset=utf-8"
        self.send_response(200); self.send_header("Content-Type",mime); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        if not self._validate_host_origin(): return
        if not self._check_auth(_AUTH_EXEMPT_POST): return
        with _CFG_LOCK:
            return self._do_POST()

    def _do_POST(self):
        try:
            c=ensure_goal_state(lc())
            if self.path=="/api/upload-evidence":
                if not c.get("privacy",{}).get("upload_raw_file_enabled", True):
                    return self.send_json({"ok":False,"message":"文件上传已被禁用（隐私设置）"},403)
                if int(self.headers.get("Content-Length","0") or 0) > _MAX_UPLOAD_BYTES:
                    return self.send_json({"ok":False,"message":"upload too large (50 MB max)"},413)
                length=int(self.headers.get("Content-Length","0") or 0)
                envelope=("Content-Type: {}\r\nMIME-Version: 1.0\r\n\r\n".format(self.headers.get("Content-Type","")).encode()+self.rfile.read(length))
                parts=list(BytesParser(policy=email_policy.default).parsebytes(envelope).iter_parts())
                fields={p.get_param("name",header="content-disposition"):p for p in parts}
                try: i=int((fields.get("idx").get_content() if fields.get("idx") else "0") or 0)
                except (TypeError,ValueError): return self.send_json({"ok":False,"message":"任务索引必须是数字"},400)
                ts=normalize_tasks(c.get("tasks",[]), gid(c), c.get("done_flags",[]))
                if i<0 or i>=len(ts): return self.send_json({"ok":False,"message":"任务索引越界"},400)
                item=fields.get("file"); filename=item.get_filename() if item else ""
                if not filename: return self.send_json({"ok":False,"message":"没有文件"},400)
                name=re.sub(r"[^A-Za-z0-9._-]+","_",os.path.basename(filename))[:120] or "upload.bin"
                fd,tmp=tempfile.mkstemp(dir=APP_DIR)
                try:
                    with os.fdopen(fd,"wb") as f: f.write(item.get_payload(decode=True) or b"")
                    fp=STORE.add_attachment(tmp,name)
                finally:
                    try: os.remove(tmp)
                    except OSError: pass
                # evidence is a list — append new file, deduplicate by abspath
                ev = as_list(ts[i].get("evidence"))
                if fp.lower() not in [os.path.abspath(x).lower() for x in ev]:
                    ev.append(fp)
                ts[i]["evidence"]=ev; c["tasks"]=ts; save_goal_state(c); evlog(c,"task_evidence","上传交付物",{"idx":i,"file":fp}); sc(c)
                return self.send_json({"ok":True,"evidence":fp})
            if self.path=="/api/storage-import":
                if int(self.headers.get("Content-Length","0") or 0)>_MAX_BACKUP_BYTES: return self.send_json({"ok":False,"message":"备份文件过大（最大 512 MB）"},413)
                length=int(self.headers.get("Content-Length","0") or 0)
                envelope=("Content-Type: {}\r\nMIME-Version: 1.0\r\n\r\n".format(self.headers.get("Content-Type","")).encode()+self.rfile.read(length))
                parts=list(BytesParser(policy=email_policy.default).parsebytes(envelope).iter_parts())
                fields={p.get_param("name",header="content-disposition"):p for p in parts}
                if (fields.get("confirm").get_content() if fields.get("confirm") else "")!="true": return self.send_json({"ok":False,"message":"导入前必须明确确认"},400)
                item=fields.get("file"); filename=item.get_filename() if item else ""
                if not filename.lower().endswith(".tvbackup"): return self.send_json({"ok":False,"message":"请选择 .tvbackup 完整备份"},400)
                fd,tmp=tempfile.mkstemp(suffix=".tvbackup",dir=APP_DIR)
                try:
                    with os.fdopen(fd,"wb") as f: f.write(item.get_payload(decode=True) or b"")
                    STORE.import_complete(tmp)
                finally:
                    try: os.remove(tmp)
                    except OSError: pass
                return self.send_json({"ok":True,"message":"完整备份已恢复，请重启应用"})
            data=self.read_json()
            if self.path=="/api/theme":
                global UI_THEME
                UI_THEME='dark' if data.get('theme')=='dark' else 'light'
                set_native_dark_mode(UI_THEME=='dark')
                return self.send_json({"ok":True})
            if self.path=="/api/storage-backup":
                path=STORE.create_backup("manual"); return self.send_json({"ok":True,"path":path,"message":"备份已创建"})
            if self.path=="/api/storage-export":
                os.makedirs(P["exports"],exist_ok=True)
                path=os.path.join(P["exports"],"task-verge-{}.tvbackup".format(datetime.now().strftime("%Y%m%d-%H%M%S")))
                STORE.export_complete(path); return self.send_json({"ok":True,"path":path,"message":"完整备份已导出"})
            if self.path=="/api/storage-restore":
                if data.get("confirm") is not True: return self.send_json({"ok":False,"message":"恢复前必须明确确认"},400)
                allowed={item["path"] for item in STORE.list_backups()}; path=task_text(data.get("path"))
                if path not in allowed: return self.send_json({"ok":False,"message":"备份不存在或不受信任"},400)
                pre=STORE.restore_backup(path); return self.send_json({"ok":True,"path":pre,"message":"备份已恢复，请重启应用"})
            if self.path=="/api/event":
                evlog(c,task_text(data.get("kind","ui_event"))[:40] or "ui_event",task_text(data.get("message",""))[:200],data.get("extra") if isinstance(data.get("extra"),dict) else {})
                sc(c); return self.send_json({"ok":True})
            if self.path=="/api/task":
                if c.get("plan_locked") and not task_text(data.get("reason","")): return self.send_json({"ok":False,"message":"计划已锁定，修改任务需要填写原因"},400)
                try: i=int(data.get("idx",0))
                except (TypeError,ValueError): return self.send_json({"ok":False,"message":"任务索引必须是数字"},400)
                ts=normalize_tasks(c.get("tasks",[]), gid(c), c.get("done_flags",[]))
                if i<0 or i>=len(ts): return self.send_json({"ok":False,"message":"任务索引越界"},400)
                title=str(data.get("text","")).strip()
                if not title: return self.send_json({"ok":False,"message":"任务内容不能为空"},400)
                ts[i]["title"]=title; ts[i]["text"]=title
                c["tasks"]=[t for t in ts if task_text(t)]; sync_pct(c); save_goal_state(c); evlog(c,"task_edit",task_text(data.get("reason",""))); sc(c); start_infer_apps()
                return self.send_json({"ok":True})
            if self.path=="/api/task-evidence":
                try: i=int(data.get("idx",0))
                except (TypeError,ValueError): return self.send_json({"ok":False,"message":"任务索引必须是数字"},400)
                ts=normalize_tasks(c.get("tasks",[]), gid(c), c.get("done_flags",[]))
                if i<0 or i>=len(ts): return self.send_json({"ok":False,"message":"任务索引越界"},400)
                evidence=valid_evidence_paths(data.get("evidence",""))
                if len(evidence)!=len(as_list(data.get("evidence",""))): return self.send_json({"ok":False,"message":"交付物必须来自 Task Verge 上传目录"},400)
                ts[i]["evidence"]=evidence; c["tasks"]=ts
                save_goal_state(c); evlog(c,"task_evidence","更新验收证据列表",{"idx":i}); sc(c); return self.send_json({"ok":True})
            if self.path=="/api/task-response":
                try: i=int(data.get("idx",0))
                except (TypeError,ValueError): return self.send_json({"ok":False,"message":"任务索引必须是数字"},400)
                ts=normalize_tasks(c.get("tasks",[]), gid(c), c.get("done_flags",[]))
                if i<0 or i>=len(ts): return self.send_json({"ok":False,"message":"任务索引越界"},400)
                response=data.get("response","")
                if not isinstance(response,(str,dict)): return self.send_json({"ok":False,"message":"作答格式无效"},400)
                if len(json.dumps(response,ensure_ascii=False))>20000: return self.send_json({"ok":False,"message":"作答内容过长"},400)
                ts[i]["response"]=response; c["tasks"]=ts
                save_goal_state(c); evlog(c,"task_response","保存页面作答",{"idx":i}); sc(c); return self.send_json({"ok":True})
            if self.path=="/api/task-rating":
                try: i=int(data.get("idx",0))
                except (TypeError,ValueError): return self.send_json({"ok":False,"message":"任务索引必须是数字"},400)
                rating=task_text(data.get("rating","")).lower()
                if rating not in ("again","hard","good","easy"): return self.send_json({"ok":False,"message":"无效的 FSRS 评分"},400)
                ts=normalize_tasks(c.get("tasks",[]), gid(c), c.get("done_flags",[]))
                if i<0 or i>=len(ts): return self.send_json({"ok":False,"message":"任务索引越界"},400)
                if not ts[i].get("skill_id"): return self.send_json({"ok":False,"message":"只有学习任务可以评分"},400)
                ts[i]["recall_rating"]=rating; c["tasks"]=ts
                save_goal_state(c); evlog(c,"fsrs_rating",rating,{"idx":i,"skill_id":ts[i]["skill_id"]}); sc(c)
                return self.send_json({"ok":True,"rating":rating})
            if self.path=="/api/task-adjust":
                try: i=int(data.get("idx",0))
                except (TypeError,ValueError): return self.send_json({"ok":False,"message":"invalid task index"},400)
                ts=normalize_tasks(c.get("tasks",[]), gid(c), c.get("done_flags",[]))
                if i<0 or i>=len(ts): return self.send_json({"ok":False,"message":"task index out of range"},400)
                action=task_text(data.get("action"))
                if action not in ("extend","skip"): return self.send_json({"ok":False,"message":"unknown task adjustment"},400)
                push_undo(c,"task adjustment")
                if action=="extend":
                    ts[i]["estimated_minutes"]=min(180,max(5,int(ts[i].get("estimated_minutes",30) or 30)+15)); msg="task extended 15 minutes"
                else:
                    ts[i]["status"]="skipped"; msg="task skipped for today"
                c["tasks"]=ts; sync_pct(c); save_goal_state(c); evlog(c,"task_adjust",msg,{"idx":i,"action":action})
                c.setdefault("coach_context",{})["adjustments_today"]=int(c.get("coach_context",{}).get("adjustments_today",0) or 0)+1; sc(c)
                return self.send_json({"ok":True,"message":msg})
            if self.path=="/api/feedback":
                try: i=int(data.get("idx",0))
                except (TypeError,ValueError): return self.send_json({"ok":False,"message":"invalid task index"},400)
                text=value_text(data.get("text","")); kind=task_text(data.get("kind",""))
                if not text and not kind: return self.send_json({"ok":False,"message":"feedback is required"},400)
                try: decision=FEEDBACK.submit(c, i, text, kind)
                except IndexError: return self.send_json({"ok":False,"message":"task index out of range"},400)
                evlog(c,"user_feedback",decision.get("reason",""),decision); sc(c)
                return self.send_json({"ok":True,"decision":decision,"tasks":task_items(c.get("tasks",[]),c.get("done_flags",[]))})
            if self.path=="/api/agent-start":
                try: i=int(data.get("idx",0))
                except (TypeError,ValueError): return self.send_json({"ok":False,"message":"invalid task index"},400)
                ts=normalize_tasks(c.get("tasks",[]),gid(c),c.get("done_flags",[]))
                if i<0 or i>=len(ts): return self.send_json({"ok":False,"message":"task index out of range"},400)
                run=AGENTS.start(gid(c), ts[i], data.get("max_steps",20))
                return self.send_json({"ok":True,"run":run})
                return self.send_json({"ok":True,"run":run})
            if self.path=="/api/agent-step":
                orch=_agent_orchestrator(c); run=orch.step(task_text(data.get("run_id"))); return self.send_json({"ok":True,"run":run})
            if self.path=="/api/agent-confirm":
                orch=_agent_orchestrator(c); run=orch.confirm(task_text(data.get("run_id"))); return self.send_json({"ok":True,"run":run})
            if self.path=="/api/agent-resume":
                orch=_agent_orchestrator(c); run=orch.resume(task_text(data.get("run_id"))); return self.send_json({"ok":True,"run":run})
            if self.path=="/api/agent-stop":
                orch=_agent_orchestrator(c); run=orch.stop(task_text(data.get("run_id")),task_text(data.get("reason")) or "user paused"); return self.send_json({"ok":True,"run":run})
            if self.path=="/api/task-state":
                try: i=int(data.get("idx",0))
                except (TypeError,ValueError): return self.send_json({"ok":False,"message":"invalid task index"},400)
                ok, message = TASKS.set_status(c, i, task_text(data.get("status")), data.get("continuation_note"), data.get("next_action"))
                return self.send_json({"ok":ok,"message":message}, 200 if ok else 400)
                return self.send_json({"ok":True,"message":"task state updated"})
            if self.path=="/api/recovery":
                source=next((t for t in c.get("tasks",[]) if isinstance(t,dict) and t.get("status") in ("paused","partial") and not task_done(t)),None)
                if not source: return self.send_json({"ok":False,"message":"no recoverable task"},400)
                recovery=normalize_task({"title":"完成一个 10 分钟保底动作","description":"从当前任务留下的续接点开始，只推进一个最小动作。","type":"behavior","role":"recovery","estimated_minutes":10,"next_action":source.get("continuation_note") or source.get("next_action") or "写下下一步并完成它","evidence_mode":"optional","verification_mode":"none"},gid(c),len(c.get("tasks",[])),False)
                recovery["status"]="pending"; recovery["recovery_for"]=source.get("id") or source.get("title")
                c["tasks"].append(recovery); c.setdefault("done_flags",[]).append(False); save_goal_state(c); evlog(c,"recovery_task","创建今日保底任务",{"idx":len(c["tasks"])-1}); sc(c)
                return self.send_json({"ok":True,"idx":len(c["tasks"])-1,"task":recovery})
            if self.path=="/api/task-evidence-list":
                # accept a list of evidence paths directly (used by frontend to remove one)
                try: i=int(data.get("idx",0))
                except (TypeError,ValueError): return self.send_json({"ok":False,"message":"任务索引必须是数字"},400)
                ts=normalize_tasks(c.get("tasks",[]), gid(c), c.get("done_flags",[]))
                if i<0 or i>=len(ts): return self.send_json({"ok":False,"message":"任务索引越界"},400)
                evidence=valid_evidence_paths(data.get("evidence",[]))
                if len(evidence)!=len(as_list(data.get("evidence",[]))): return self.send_json({"ok":False,"message":"交付物路径无效"},400)
                ts[i]["evidence"]=evidence; c["tasks"]=ts
                save_goal_state(c); evlog(c,"task_evidence","更新验收证据列表",{"idx":i}); sc(c); return self.send_json({"ok":True})
            if self.path=="/api/tasks":
                ok, message = TASKS.replace(c, data.get("tasks"), data.get("reason", ""))
                if ok: start_infer_apps()
                return self.send_json({"ok":ok,"message":message}, 200 if ok else 400)
            if self.path=="/api/lock-plan":
                c["plan_locked"]=bool(data.get("locked",True)); evlog(c,"plan_lock" if c["plan_locked"] else "plan_unlock",task_text(data.get("reason",""))); save_goal_state(c); sc(c); return self.send_json({"ok":True})
            if self.path=="/api/break":
                reason=task_text(data.get("reason",""))
                try: mins=max(1,min(60,int(data.get("minutes",10) or 10)))
                except (TypeError,ValueError): return self.send_json({"ok":False,"message":"休息时长必须是数字"},400)
                todays=[b for b in c.get("breaks",[]) if b.get("date")==today()]
                if len(todays)>=3: return self.send_json({"ok":False,"message":"今天休息次数已用完"},400)
                c.setdefault("breaks",[]); c["breaks"].append({"date":today(),"ts":datetime.now().isoformat(),"until":time.time()+mins*60,"minutes":mins,"reason":reason}); evlog(c,"break",reason,{"minutes":mins}); sc(c); return self.send_json({"ok":True})
            if self.path=="/api/break-end":
                now=time.time(); ended=False
                for b in c.get("breaks",[]):
                    if isinstance(b,dict) and float(b.get("until",0) or 0)>now:
                        b["until"]=now; b["ended"]=True; ended=True
                evlog(c,"break_end","结束休息",{"ended":ended}); sc(c)
                return self.send_json({"ok":True,"ended":ended})
            if self.path=="/api/quit":
                reason=task_text(data.get("reason",""))
                action=task_text(data.get("action","quit"))
                if action == "continue_15":
                    # User chose to continue working for 15 more minutes
                    c.setdefault("breaks",[]); c["breaks"].append({"date":today(),"ts":datetime.now().isoformat(),"until":time.time()+15*60,"minutes":15,"reason":"收尾仪式-继续"})
                    c.setdefault("quit_attempts",[]); c["quit_attempts"].append({"date":today(),"ts":datetime.now().isoformat(),"reason":"继续15分钟","unfinished":unfinished(c)})
                    evlog(c,"quit_continue","继续 15 分钟"); sc(c); return self.send_json({"ok":True,"message":"继续 15 分钟"})
                if action == "defer":
                    # Defer unfinished tasks to tomorrow
                    reason=reason or "延期到下一个时间块"
                    for t in c.get("tasks",[]):
                        if isinstance(t, dict) and t.get("status")!="done":
                            t["status"]="deferred"
                    c.setdefault("quit_attempts",[]); c["quit_attempts"].append({"date":today(),"ts":datetime.now().isoformat(),"reason":reason,"unfinished":unfinished(c)}); evlog(c,"quit_defer",reason); save_goal_state(c); sc(c)
                    return self.send_json({"ok":True,"message":"已延期"})
                # action == "quit": traditional quit with reason
                if unfinished(c) and not reason: return self.send_json({"ok":False,"message":"任务未完成，退出需要填写原因"},400)
                c.setdefault("quit_attempts",[]); c["quit_attempts"].append({"date":today(),"ts":datetime.now().isoformat(),"reason":reason,"unfinished":unfinished(c)}); evlog(c,"quit",reason); sc(c)
                def _exit():
                    time.sleep(1.5)
                    try:
                        s32=ctypes.windll.shell32
                        from ctypes import wintypes as w
                        NI=type("NI",(ctypes.Structure,),{"_fields_":[("cb",w.DWORD),("hw",w.HWND),("id",w.UINT),("fl",w.UINT),("cbmsg",w.UINT),("hi",w.HANDLE),("tip",w.WCHAR*128),("st",w.DWORD),("stm",w.DWORD),("inf",w.WCHAR*256),("ver",w.UINT),("tit",w.WCHAR*64),("iflg",w.DWORD),("gd",ctypes.c_ubyte*16),("bal",w.HANDLE)]})
                        n=NI(ctypes.sizeof(NI),0,7,0,0,0,"")
                        s32.Shell_NotifyIconW(2,ctypes.byref(n))
                    except Exception: pass
                    request_stop()
                    try: os.remove(P["pid"])
                    except OSError: pass
                    os._exit(0)
                threading.Thread(target=_exit,daemon=True).start(); return self.send_json({"ok":True,"message":"即将退出"})
            if self.path=="/api/archive":
                rec=daily_archive(c); evlog(c,"archive","每日归档",{"review":rec.get("review",{})}); sc(c); return self.send_json({"ok":True,"archive":rec})
            if self.path=="/api/next-cycle":
                rec=daily_archive(c)
                adaptive.prepare_next_cycle(c); save_goal_state(c)
                evlog(c,"next_cycle","根据复盘开始下一轮",{"review":rec.get("review",{})}); sc(c)
                return self.send_json({"ok":True,"review":rec.get("review",{})})
            if self.path=="/api/archive-delete":
                push_undo(c,"daily archive")
                target=task_text(data.get("date","")); before=len(c.get("archives",[]))
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",target): return self.send_json({"ok":False,"message":"归档日期格式不正确"},400)
                c["archives"]=[a for a in c.get("archives",[]) if task_text(a.get("date"))!=target]
                if len(c["archives"])==before: return self.send_json({"ok":False,"message":"找不到这条归档"},404)
                evlog(c,"archive_delete","删除归档",{"date":target}); sc(c); return self.send_json({"ok":True,"message":"归档已删除"})
            if self.path=="/api/settings":
                ensure_goal_state(c); save_goal_state(c)
                if not isinstance(data.get("goals"),list): return self.send_json({"ok":False,"message":"目标列表格式不正确"},400)
                if "task_gen" in data and not isinstance(data.get("task_gen"),dict): return self.send_json({"ok":False,"message":"生成参数格式不正确"},400)
                old={task_text(g):copy.deepcopy(g) for g in c.get("goals",[]) if isinstance(g,dict) and task_text(g)}
                goals=[]
                for pos,item in enumerate(data.get("goals",[])):
                    title=task_text(item)
                    if not title: continue
                    record=old.get(title,{"id":"goal_{}".format(pos),"title":title})
                    record["title"]=title; goals.append(record)
                one=task_text(data.get("goal",""))
                if one and one not in goals: goals.insert(0,one)
                if not goals: return self.send_json({"ok":False,"message":"请至少设置一个目标"},400)
                tg=data.get("task_gen",{})
                if isinstance(tg,dict):
                    cur=gen_settings(c)
                    for k in ("available_minutes","task_count","max_task_minutes"):
                        if k in tg:
                            try: cur[k]=int(tg.get(k))
                            except Exception: pass
                    if "prefer_continuation" in tg: cur["prefer_continuation"]=bool(tg.get("prefer_continuation"))
                    if "force_measurable_output" in tg: cur["force_measurable_output"]=bool(tg.get("force_measurable_output"))
                    c["task_gen"]=gen_settings({"task_gen":cur})
                fg=data.get("focus_guard",{})
                if isinstance(fg,dict) and "enabled" in fg:
                    c.setdefault("focus_guard",copy.deepcopy(CFG0["focus_guard"]))["enabled"]=bool(fg.get("enabled"))
                privacy=data.get("privacy",{})
                if isinstance(privacy,dict):
                    current=c.setdefault("privacy",copy.deepcopy(CFG0["privacy"]))
                    for key in CFG0["privacy"]:
                        if key in privacy: current[key]=bool(privacy[key])
                    WEBAPP._fine_grained=current.get("fine_grained_fg_enabled",True)
                schedule=data.get("schedule",{})
                if isinstance(schedule,dict) and task_text(schedule.get("focus_template")) in ("25","50","90"):
                    c.setdefault("schedule",copy.deepcopy(CFG0["schedule"]))["focus_template"]=task_text(schedule["focus_template"])
                workspace=os.path.abspath(os.path.expanduser(task_text(data.get("workspace",c.get("workspace",""))))) if task_text(data.get("workspace",c.get("workspace",""))) else ""
                if workspace and not os.path.isdir(workspace): return self.send_json({"ok":False,"message":"Agent 工作区不存在"},400)
                c["workspace"]=workspace
                try: active_goal=int(data.get("active_goal",0) or 0)
                except (TypeError,ValueError): return self.send_json({"ok":False,"message":"当前目标索引必须是数字"},400)
                c["goals"]=goals; c["goal"]=""; c["active_goal"]=active_goal; norm_goals(c)
                details=data.get("goal_details",{})
                if isinstance(details,dict) and c.get("goals"):
                    g=c["goals"][c["active_goal"]]
                    for k in ("outcome","deadline","baseline"):
                        g[k]=task_text(details.get(k,""))
                    for k in ("success_criteria","constraints"):
                        g[k]=as_list(details.get(k,[]))
                ensure_goal_state(c)
                try: retention=float(data.get("desired_retention",0.9) or 0.9)
                except (TypeError,ValueError): return self.send_json({"ok":False,"message":"FSRS 目标记忆率格式不正确"},400)
                if not 0.7 <= retention <= 0.97: return self.send_json({"ok":False,"message":"FSRS 目标记忆率必须在 0.70 到 0.97 之间"},400)
                model=c.setdefault("user_model",{})
                if float(model.get("desired_retention",0.9) or 0.9) != retention: model.pop("fsrs_scheduler",None)
                model["desired_retention"]=retention
                save_goal_state(c); sc(c); set_autostart(bool(data.get("autostart"))); return self.send_json({"ok":True})
            if self.path=="/api/privacy-consent":
                c.setdefault("privacy",copy.deepcopy(CFG0["privacy"]))["monitoring_consent"]=bool(data.get("accepted"))
                sc(c)
                if c["privacy"]["monitoring_consent"]: WEBAPP.start_foreground_tracking()
                return self.send_json({"ok":True})
            if self.path=="/api/deepseek-key":
                key=task_text(data.get("key",""))
                if save_deepseek_key(key): return self.send_json({"ok":True,"message":"Key 已保存"})
                return self.send_json({"ok":False,"message":"Key 保存失败"},500)
            if self.path=="/api/active-goal":
                try: active_goal=int(data.get("active_goal",0) or 0)
                except (TypeError,ValueError): return self.send_json({"ok":False,"message":"当前目标索引必须是数字"},400)
                save_goal_state(c); c["active_goal"]=active_goal; ensure_goal_state(c); sc(c); return self.send_json({"ok":True})
            if self.path=="/api/goal-delete":
                ensure_goal_state(c); save_goal_state(c)
                goals=c.get("goals",[])
                if len(goals)<=1: return self.send_json({"ok":False,"message":"至少保留一个目标"},400)
                try: index=int(data.get("index",-1))
                except (TypeError,ValueError): return self.send_json({"ok":False,"message":"目标索引必须是数字"},400)
                if index<0 or index>=len(goals): return self.send_json({"ok":False,"message":"目标不存在"},404)
                removed=copy.deepcopy(goals[index]); removed["archived_at"]=datetime.now().isoformat()
                removed["archive_reason"]="用户删除"
                c.setdefault("archived_goals",[]).append(removed)
                old_active=int(c.get("active_goal",0) or 0)
                c["goals"]=goals[:index]+goals[index+1:]
                c["active_goal"] = old_active-1 if index<old_active else min(old_active,len(c["goals"])-1)
                c["goal"]=""; norm_goals(c); ensure_goal_state(c)
                evlog(c,"goal_archive","目标已删除并归档",{"goal_id":removed.get("id"),"goal":removed.get("title")})
                sc(c)
                return self.send_json({"ok":True,"archived_goal":removed,"active_goal":c.get("active_goal",0)})
            if self.path=="/api/focus-policy":
                p=c.setdefault("focus_guard",copy.deepcopy(CFG0["focus_guard"])); action=task_text(data.get("action"))
                if action=="pause":
                    try: minutes=max(1,min(240,int(data.get("minutes",30) or 30)))
                    except (TypeError,ValueError): return self.send_json({"ok":False,"message":"暂停时长无效"},400)
                    p["pause_until"]=time.time()+minutes*60; p.setdefault("stats",{})["paused"]=int(p.setdefault("stats",{}).get("paused",0) or 0)+1
                elif action=="clear_overrides": push_undo(c,"application exceptions"); p["app_overrides"]={}
                elif action=="enabled": p["enabled"]=bool(data.get("value",True))
                else: return self.send_json({"ok":False,"message":"未知专注策略"},400)
                evlog(c,"focus_policy","更新专注策略",{"action":action}); sc(c); return self.send_json({"ok":True})
            if self.path=="/api/catalog":
                cat=data.get("catalog",{})
                if not isinstance(cat,dict) or not isinstance(cat.get("categories",[]),list): return self.send_json({"ok":False,"message":"分类 JSON 格式不对"},400)
                c["app_catalog"]=normalize_catalog(cat); c["app_catalog_sig"]="manual"; evlog(c,"app_catalog","用户调整应用分类"); sc(c); return self.send_json({"ok":True})
            if self.path=="/api/catalog-regenerate":
                c["app_catalog_sig"]=""; c["app_catalog"]={}; evlog(c,"app_catalog","触发 AI 重新分类"); sc(c)
                start_catalog_job(); return self.send_json({"ok":True})
            if self.path=="/api/request-app":
                ok,msg=request_task_app(c,task_text(data.get("action","add")),task_text(data.get("app","")))
                evlog(c,"request_app",msg,{"app":data.get("app",""),"action":data.get("action","add"),"ok":ok})
                sc(c); return self.send_json({"ok":ok,"message":msg},200 if ok else 400)
            if self.path=="/api/open-app":
                exe=task_text(data.get("exe","")).lower()
                app=next((a for a in applications() if a.get("exe","").lower()==exe),None)
                if not app or not app.get("path") or not os.path.exists(app["path"]): return self.send_json({"ok":False,"message":"找不到应用路径"},404)
                subprocess.Popen([app["path"]],creationflags=_CNW)
                return self.send_json({"ok":True})
            if self.path=="/api/generate":
                job=start_gen_job(); return self.send_json(job, 200 if job.get("ok") else 400)
            if self.path=="/api/reinfer-apps":
                if _APPRULES and not valid_deepseek_key(dk()):
                    start_infer_apps(); return self.send_json({"ok":True,"message":"offline app matching started"})
                if not valid_deepseek_key(dk()): return self.send_json({"ok":False,"message":"未配置有效 DeepSeek Key，无法重新匹配应用"},400)
                start_infer_apps(); return self.send_json({"ok":True,"message":"已开始重新匹配应用"})
            if self.path=="/api/plan":
                blocks=ensure_time_blocks(c, True); evlog(c,"coach_plan","生成时间块",{"blocks":len(blocks)}); save_goal_state(c); sc(c); return self.send_json({"ok":True,"time_blocks":blocks})
            if self.path=="/api/chat":
                msg=value_text(data.get("message",""))
                if not msg: return self.send_json({"ok":False,"message":"请输入对话内容"},400)
                ctx={"goal":c.get("goal",""),"tasks":task_payload(c.get("tasks",[]),c.get("done_flags",[])),"time_blocks":ensure_time_blocks(c),"insights":insights_for(c)}
                # ---- Local coach rules first, LLM as fallback ----
                r = None
                if msg.strip().startswith("/"):
                    r = fallback_chat_action(msg, c)
                # If local rules didn't match, try LLM
                if r is None:
                    try:
                        r = deepseek_json([{"role":"system","content":"你是 AI 专注教练。根据 state 回复用户，并只提出一个需要用户确认的 action。action 可为 plan、reschedule_first_pending、regenerate_tasks、break 或 null。返回 JSON: {\"reply\":\"...\",\"action\":{...}}"},{"role":"user","content":json.dumps({"message":msg,"state":ctx},ensure_ascii=False)}],900,0.2,30,1)
                    except AIError:
                        r = fallback_chat_action(msg, c)
                r.setdefault("reply","我会根据当前计划协助你调整。")
                c.setdefault("coach_messages",[]).append({"ts":datetime.now().isoformat(),"role":"user","text":msg})
                c["coach_messages"].append({"ts":datetime.now().isoformat(),"role":"assistant","text":r.get("reply",""),"action":r.get("action")})
                evlog(c,"coach_chat",msg,{"action":r.get("action")}); save_goal_state(c); sc(c); return self.send_json({"ok":True,"reply":r.get("reply",""),"action":r.get("action")})
            if self.path=="/api/coach-action":
                action=data.get("action",{})
                if not isinstance(action,dict): return self.send_json({"ok":False,"message":"action 格式错误"},400)
                typ=action.get("type"); msg="已执行"
                if typ=="plan":
                    ensure_time_blocks(c, True); msg="已重新生成时间块"
                elif typ=="reschedule_first_pending":
                    blocks=ensure_time_blocks(c)
                    start=min_of(action.get("start","14:00"))
                    for b in blocks:
                        if b.get("type")=="task" and b.get("status")!="done":
                            dur=min_of(b["end"])-min_of(b["start"]); b["start"]=hhmm(start); b["end"]=hhmm(start+max(10,dur)); msg="已调整第一个未完成任务"; break
                    c["time_blocks"]=blocks
                elif typ=="regenerate_tasks":
                    start_gen_job(); msg="已开始重新生成任务"
                elif typ=="archive_today":
                    rec=daily_archive(c); msg="已归档今日复盘"
                elif typ=="break":
                    try: mins=max(1,min(60,int(action.get("minutes",5) or 5)))
                    except (TypeError,ValueError): mins=5
                    c.setdefault("breaks",[]); c["breaks"].append({"date":today(),"ts":datetime.now().isoformat(),"until":time.time()+mins*60,"minutes":mins,"reason":"教练建议休息"})
                    evlog(c,"break","教练建议休息",{"minutes":mins}); msg="已记录 {} 分钟休息".format(mins)
                elif typ=="quiet":
                    c.setdefault("coach_context",{})["quiet_until"]=time.time()+24*3600
                    msg="已静默至明日"
                elif typ=="ignore_insight":
                    insight_id = task_text(action.get("insight_id",""))
                    if insight_id:
                        cc = c.setdefault("coach_context",{})
                        ignored = set(cc.get("ignored_insights",[]))
                        ignored.add(insight_id)
                        cc["ignored_insights"] = list(ignored)[-50:]
                    msg="已忽略此项洞察"
                else:
                    return self.send_json({"ok":False,"message":"未知 action"},400)
                cc=c.setdefault("coach_context",{}); cc["adjustments_today"]=int(cc.get("adjustments_today",0))+1
                evlog(c,"coach_action",msg,{"action":action}); save_goal_state(c); sc(c); return self.send_json({"ok":True,"message":msg})
            if self.path=="/api/evaluate":
                try: cli_eval(); return self.send_json({"ok":True,"message":"AI 验收完成"})
                except AIError as e: return self.send_json({"ok":False,"message":"AI {}: {}".format(e.kind,e)},502)
            if self.path=="/api/evaluate-task":
                try: return self.send_json(evaluate_task(int(data.get("idx",-1))))
                except (TypeError,ValueError) as e: return self.send_json({"ok":False,"message":str(e)},400)
                except AIError as e: return self.send_json({"ok":False,"message":"AI {}: {}".format(e.kind,e)},502)
            if self.path=="/api/remediate-task":
                try: i=int(data.get("idx", data.get("task_idx", -1)))
                except (TypeError,ValueError): return self.send_json({"ok":False,"message":"invalid task index"},400)
                recovery=ACCEPTANCE.ensure_remediation(c, i)
                if not recovery: return self.send_json({"ok":False,"message":"无法创建补救任务"},400)
                sync_pct(c); save_goal_state(c); evlog(c,"remediation_task","创建补救任务",{"idx":i,"task_id":recovery.get("id","")}); sc(c)
                return self.send_json({"ok":True,"task":recovery})
            if self.path=="/api/manual-accept":
                try: i=int(data.get("task_idx",0))
                except (TypeError,ValueError): return self.send_json({"ok":False,"message":"invalid task index"},400)
                ok, message = ACCEPTANCE.manual_accept(c, i, data.get("reason", "manual approval"))
                return self.send_json({"ok":ok,"message":message}, 200 if ok else 400)
                return self.send_json({"ok":True,"message":"任务已手动放行"})
            if self.path=="/api/clear-fg":
                push_undo(c,"foreground statistics")
                WEBAPP._fg_data={}; WEBAPP._fg_last_flush=time.time()
                sf({}); evlog(c,"clear_fg","用户清除前台时间数据"); sc(c); return self.send_json({"ok":True,"message":"已清除前台时间数据"})
            if self.path=="/api/undo":
                label=pop_undo(c)
                if not label: return self.send_json({"ok":False,"message":"nothing to undo"},400)
                return self.send_json({"ok":True,"message":"undone: "+label})
            if self.path=="/api/dismiss-crash":
                global _LAST_CRASH
                _LAST_CRASH = None
                crash_mark_clean(); return self.send_json({"ok":True})
            if self.path=="/api/heartbeat":
                tok = self.headers.get("X-Session","")
                heartbeat_session(tok); return self.send_json({"ok":True})
            self.send_error(404)
        except Exception as e:
            self.send_json({"ok":False,"message":str(e)},500)

_MAIN_WINDOW = None

def open_desktop(url):
    if _MAIN_WINDOW is not None:
        try:
            _MAIN_WINDOW.show()
            return
        except Exception: pass
    # Reuse the existing desktop first; launching Chrome before this creates
    # duplicate Task Verge windows and invalidates the single-session token.
    if focus_window("Task Verge"): return
    for p in [os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")]:
        if os.path.exists(p):
            subprocess.Popen([p,"--app="+url,"--start-maximized"],creationflags=_CNW)
            return
    for p in [os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe")]:
        if os.path.exists(p):
            subprocess.Popen([p,"--app="+url,"--start-maximized"],creationflags=_CNW)
            return
    webbrowser.open(url)

def run_native_window(url):
    """Run the local web UI in a native WebView2 desktop window."""
    global _MAIN_WINDOW
    try:
        import webview
    except Exception as e:
        _bl("native webview unavailable: " + repr(e))
        return False
    try:
        desktop_url = url + ("&" if "?" in url else "?") + "desktop_token=" + urllib.parse.quote(_DESKTOP_CLAIM_SECRET)
        try: ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TaskVerge.Desktop")
        except Exception: pass
        icon_path=os.path.join(WEB_DIR, "taskverge.ico")
        _MAIN_WINDOW = webview.create_window("Task Verge", desktop_url, width=1160, height=760,
                                             min_size=(900, 640), maximized=True, confirm_close=False)
        def hide_to_tray():
            try: _MAIN_WINDOW.hide()
            except Exception: pass
            return False
        _MAIN_WINDOW.events.closing += hide_to_tray
        def apply_icon():
            def retry():
                for _ in range(25):
                    if set_window_icon(): return
                    time.sleep(0.12)
            threading.Thread(target=retry, daemon=True).start()
        webview.start(func=apply_icon, icon=icon_path)
        return True
    except Exception as e:
        _bl("native webview failed: " + repr(e))
        _MAIN_WINDOW = None
        return False

def focus_window(title):
    if os.name!="nt": return False
    hwnd=find_window(title)
    if not hwnd: return False
    user32=ctypes.windll.user32
    user32.ShowWindow(hwnd,9)
    user32.SetForegroundWindow(hwnd)
    return True

def set_window_icon(title="Task Verge"):
    """Apply Task Verge.ico to the native window so source-mode pythonw is not shown on the taskbar."""
    if os.name!="nt": return False
    hwnd=find_window(title)
    if not hwnd: return False
    try:
        u32=ctypes.windll.user32
        u32.LoadImageW.restype=ctypes.c_void_p
        u32.SendMessageW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_void_p]
        u32.SendMessageW.restype=ctypes.c_ssize_t
        path=ico()
        small=u32.LoadImageW(None,path,1,16,16,0x10)
        big=u32.LoadImageW(None,path,1,32,32,0x10) or small
        if not (small or big): return False
        if small: u32.SendMessageW(hwnd,0x0080,0,small)
        if big: u32.SendMessageW(hwnd,0x0080,1,big)
        return True
    except Exception as e:
        _bl("window icon: " + repr(e)); return False

def set_native_dark_mode(enabled):
    """Keep the WebView2 title bar in sync with the page theme."""
    if os.name!="nt": return False
    hwnd=find_window("Task Verge")
    if not hwnd: return False
    value=ctypes.c_int(1 if enabled else 0)
    dwm=ctypes.windll.dwmapi
    result=dwm.DwmSetWindowAttribute(hwnd,20,ctypes.byref(value),ctypes.sizeof(value))
    if result!=0:
        result=dwm.DwmSetWindowAttribute(hwnd,19,ctypes.byref(value),ctypes.sizeof(value))
    ctypes.windll.user32.SetWindowPos(hwnd,0,0,0,0,0,0x0001|0x0002|0x0004|0x0020)
    return result==0

def find_window(title):
    if os.name!="nt": return 0
    found=[]
    EnumWindowsProc=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
    user32=ctypes.windll.user32
    @EnumWindowsProc
    def enum(hwnd, lparam):
        buf=ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd,buf,256)
        if title in buf.value:
            found.append(hwnd)
            return False
        return True
    user32.EnumWindows(enum,None)
    return found[0] if found else 0

def foreground_exe(hwnd=None):
    if os.name!="nt": return ""
    try:
        u32=ctypes.windll.user32; k32=ctypes.windll.kernel32
        hwnd=hwnd or u32.GetForegroundWindow()
        if not hwnd: return ""
        pid=ctypes.c_ulong(); u32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        h=k32.OpenProcess(0x1000,False,pid.value)
        if not h: return ""
        buf=ctypes.create_unicode_buffer(520); size=ctypes.c_ulong(len(buf))
        ok=k32.QueryFullProcessImageNameW(h,0,buf,ctypes.byref(size)); k32.CloseHandle(h)
        return os.path.basename(buf.value).lower() if ok else ""
    except Exception: return ""

def set_topmost(hwnd, enabled):
    if os.name!="nt" or not hwnd: return False
    try:
        u32=ctypes.windll.user32
        u32.SetWindowPos.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint]
        u32.SetWindowPos.restype=ctypes.c_bool
        return bool(u32.SetWindowPos(ctypes.c_void_p(hwnd),ctypes.c_void_p(-1 if enabled else -2),0,0,0,0,0x0001|0x0002|0x0010))
    except Exception: return False

def web_tray(url, server):
    if os.name!="nt": return
    from ctypes import wintypes as w
    u32=ctypes.windll.user32; s32=ctypes.windll.shell32; k32=ctypes.windll.kernel32
    # Windows WPARAM/LPARAM are pointer-sized; wintypes may expose them as
    # 32-bit longs on some Python builds, which overflows tray callbacks.
    u32.DefWindowProcW.argtypes=[w.HWND,w.UINT,ctypes.c_size_t,ctypes.c_ssize_t]; u32.DefWindowProcW.restype=ctypes.c_ssize_t
    u32.AppendMenuW.argtypes=[w.HMENU,w.UINT,ctypes.c_size_t,w.LPCWSTR]
    u32.TrackPopupMenu.argtypes=[w.HMENU,w.UINT,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.HWND,ctypes.c_void_p]
    u32.TrackPopupMenu.restype=w.BOOL
    NIM_ADD,NIM_DELETE,NIM_SETVERSION=0,2,4; NIF_MESSAGE,NIF_ICON,NIF_TIP=1,2,4
    WM_TRAY,ID_TRAY,ID_OPEN,ID_QUIT=0x8000+7,7,2001,2002
    class NI(ctypes.Structure):
        _fields_=[("cb",w.DWORD),("hw",w.HWND),("id",w.UINT),("fl",w.UINT),("cbmsg",w.UINT),("hi",w.HANDLE),("tip",w.WCHAR*128),("st",w.DWORD),("stm",w.DWORD),("inf",w.WCHAR*256),("ver",w.UINT),("tit",w.WCHAR*64),("iflg",w.DWORD),("gd",ctypes.c_ubyte*16),("bal",w.HANDLE)]
    nsz=ctypes.sizeof(NI); hi=u32.LoadImageW(0,ico(),1,16,16,0x10) or u32.LoadImageW(0,ico(),1,32,32,0x10)
    WP=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,w.HWND,w.UINT,ctypes.c_size_t,ctypes.c_ssize_t)
    @WP
    def wp(hw,msg,wp,lp):
        if msg==1:
            n=NI(nsz,hw,ID_TRAY,NIF_MESSAGE|NIF_ICON|NIF_TIP,WM_TRAY,hi,"Task Verge")
            s32.Shell_NotifyIconW(NIM_ADD,ctypes.byref(n))
            n.ver=4; s32.Shell_NotifyIconW(NIM_SETVERSION,ctypes.byref(n))
            return 0
        if msg==WM_TRAY:
            ev=lp&0xFFFF
            if ev in (0x0202,0x0203,0x0400): open_desktop(url)
            if ev in (0x0204,0x0205,0x007b):
                pt=w.POINT(); u32.GetCursorPos(ctypes.byref(pt)); hm=u32.CreatePopupMenu()
                u32.AppendMenuW(hm,0,ID_OPEN,"打开 Task Verge")
                u32.AppendMenuW(hm,0,ID_QUIT,"退出")
                u32.SetForegroundWindow(hw); u32.TrackPopupMenu(hm,0x40|0x08,pt.x,pt.y,0,hw,None); u32.DestroyMenu(hm)
            return 0
        if msg==0x0111:
            cmd=wp&0xFFFF
            if cmd==ID_OPEN: open_desktop(url)
            if cmd==ID_QUIT:
                try:
                    c=ensure_goal_state(lc()); c.setdefault("quit_attempts",[]).append({"date":today(),"ts":datetime.now().isoformat(),"reason":"系统托盘退出","unfinished":unfinished(c)}); evlog(c,"quit","系统托盘退出"); sc(c)
                except Exception as e: _bl("tray exit log failed: {}".format(e))
                request_stop(); crash_mark_clean()
                try: os.remove(P["pid"])
                except OSError: pass
                u32.DestroyWindow(hw)
                threading.Thread(target=lambda:(time.sleep(0.1),os._exit(0)),daemon=True).start()
                return 0
            return 0
        if msg==2:
            n=NI(nsz,hw,ID_TRAY,NIF_MESSAGE,0,0,""); s32.Shell_NotifyIconW(NIM_DELETE,ctypes.byref(n)); u32.PostQuitMessage(0); return 0
        return u32.DefWindowProcW(hw,msg,int(wp),int(lp))
    class WC(ctypes.Structure):
        _fields_=[("cb",w.UINT),("st",w.UINT),("wp",ctypes.c_void_p),("cex",ctypes.c_int),("wex",ctypes.c_int),("hi",w.HINSTANCE),("ic",w.HICON),("cu",w.HICON),("bg",w.HBRUSH),("mn",w.LPCWSTR),("cn",w.LPCWSTR),("ism",w.HICON)]
    wc=WC(ctypes.sizeof(WC),0,ctypes.cast(wp,ctypes.c_void_p),0,0,k32.GetModuleHandleW(None),0,0,0,None,"TaskVergeTray",0)
    u32.RegisterClassExW(ctypes.byref(wc))
    hw=u32.CreateWindowExW(0,"TaskVergeTray","",0,0,0,0,0,0,0,0,None)
    if not hw: return
    m=w.MSG()
    while u32.GetMessageW(ctypes.byref(m),None,0,0)>0:
        u32.TranslateMessage(ctypes.byref(m)); u32.DispatchMessageW(ctypes.byref(m))

def run_web():
    global TASKS, AGENTS, FEEDBACK, ACCEPTANCE
    TASKS = TaskService(text=task_text, normalize=normalize_tasks, goal_id=gid, sync_pct=sync_pct,
                        save=save_goal_state, event=evlog, undo=push_undo, compact=sc, outcome=adaptive.record_outcome,
                        readiness=lambda c: adaptive.goal_readiness(goal_details(c)), first_task_started=mark_first_task_started)
    AGENTS = AgentService(lambda: _agent_orchestrator(ensure_goal_state(lc())),
                          start_loop=lambda run_id: JOBS.submit(_agent_loop, ensure_goal_state(lc()), run_id, key="agent:" + run_id))
    FEEDBACK = FeedbackService(record=adaptive.record_feedback, done=task_done, sync_pct=sync_pct,
                               save=save_goal_state, event=evlog, compact=sc)
    ACCEPTANCE = AcceptanceService(normalize=normalize_tasks, text=task_text, sync_pct=sync_pct,
                                   save=save_goal_state, event=evlog, outcome=adaptive.record_outcome,
                                   learning_outcome=adaptive.record_learning_outcome)
    global WEBAPP
    crash_mark_running()
    atexit.register(crash_mark_clean)
    # ---- Log rotation: init ----
    if _APPLOG:
        try: _APPLOG.setup_logging(APP_DIR)
        except Exception: pass
    WEBAPP = WebApp()
    # ponytail: keep the normal desktop URL stable; CI still owns its random port.
    try: port=int(os.environ.get("TASKVERGE_PORT", "64161") or 64161)
    except (TypeError, ValueError): port=64161
    try:
        s=BoundedHTTPServer(("127.0.0.1",port),Handler)
    except OSError:
        s=BoundedHTTPServer(("127.0.0.1",0),Handler)
    url="http://127.0.0.1:{}/".format(s.server_port)
    try:
        with open(P["url"],"w",encoding="utf-8") as f: f.write(url)
    except Exception: pass
    _bl("web: "+url)
    threading.Thread(target=s.serve_forever,daemon=True).start()
    threading.Thread(target=lambda:web_tray(url,s),daemon=True).start()
    if os.name=="nt":
        WEBAPP._focus_guard=FocusGuard(WEBAPP); WEBAPP._focus_guard.start()
    if run_native_window(url):
        crash_mark_clean(); WEBAPP.alive=False; s.shutdown(); return
    open_desktop(url)
    try:
        while True: time.sleep(3600)
    except KeyboardInterrupt:
        crash_mark_clean(); WEBAPP.alive=False; s.shutdown()

def pid_alive(pid):
    try:
        pid=int(pid)
        if pid<=0 or pid==os.getpid(): return False
        if os.name!="nt": os.kill(pid,0); return True
        h=ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h: return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    except Exception:
        return False
def single_instance_guard():
    old=task_text(jl(P["pid"],{}).get("pid",""))
    if old and pid_alive(old):
        if not focus_window("Task Verge"):
            try:
                with open(P["url"],encoding="utf-8") as f: open_desktop(f.read().strip())
            except Exception: pass
        _bl("main: existing pid {}, exit".format(old))
        sys.exit(2)
    js(P["pid"], {"pid":os.getpid(),"ts":datetime.now().isoformat(),"script":os.path.abspath(__file__)})
    def clean_pid():
        try:
            cur=jl(P["pid"],{})
            if int(cur.get("pid",0))==os.getpid(): os.remove(P["pid"])
        except Exception: pass
    atexit.register(clean_pid)

import tkinter as tk
DARK="#0d1117"; CARD="#161b22"; CARD2="#21262d"; FG="#c9d1d9"; MU="#8b949e"; GR="#3fb950"; RD="#f85149"; BLUE="#58a6ff"

class BannerApi:
    """JS → Python bridge for the WebView2 banner."""
    def __init__(self, guard):
        self._guard = guard
    def close_current_window(self):
        self._guard._close_current_window()
    def allow_current(self, seconds):
        self._guard._allow_current(int(seconds))
    def pause(self, seconds):
        self._guard._pause(int(seconds))

class FocusGuard:
    """Progressive focus intervention for non-work applications."""
    _SYSTEM={"explorer.exe","applicationframehost.exe","shellexperiencehost.exe","textinputhost.exe","searchhost.exe","startmenuexperiencehost.exe","lockapp.exe","taskmgr.exe"}
    _EXEMPT={"teams.exe","ms-teams.exe","zoom.exe","webex.exe","slack.exe","outlook.exe","keepass.exe","1password.exe","bitwarden.exe"}
    def __init__(self,app):
        self.app=app; self.alive=True; self.root=None; self._bad_since=0; self._last_exe=""; self._allow={}; self._session_allowed_exe=""; self._task_hwnd=0; self._offending_hwnd=0; self._top=False; self._webview=None; self._webview_window=None
    def start(self): threading.Thread(target=self._run,daemon=True).start()
    def _run(self):
        try:
            _bl("focus guard started")
            self.root=tk.Tk(); self.root.withdraw()
            self.root.after(100,self._tick); self.root.mainloop()
        except Exception as e: _bl("focus guard: " + repr(e))
    def _run_webview(self):
        return
        # Lazy import: local 'platform' package shadows stdlib, so fix sys.modules temporarily
        _sm=sys.modules; _orig_pl=_sm.get('platform')
        if _orig_pl: del _sm['platform']
        _orig_path=sys.path[:]; sys.path=[p for p in sys.path if p not in ('','.') and os.path.abspath(p)!=os.path.abspath('.')]
        try:
            import webview
            self._webview=webview
        finally:
            if _orig_pl: _sm['platform']=_orig_pl
            sys.path=_orig_path
        def _on_ready(): self._webview_ready.set()
        sw=ctypes.windll.user32.GetSystemMetrics(0)
        x=max(0,(sw-584)//2)
        self._webview_window=webview.create_window(
            "",html=self._banner_html(),width=584,height=88,
            x=x,y=16,frameless=True,easy_drag=False,
            on_top=True,transparent=True,js_api=self._api)
        try:
            webview.start(func=_on_ready, gui='edgechromium')
        except Exception as e:
            _bl("webview edgechromium: " + repr(e))
            try: webview.start(func=_on_ready)
            except Exception as e:
                _bl("webview fallback: " + repr(e)); self._webview_ready.set()
    def _policy(self):
        try: return ensure_goal_state(lc()).get("focus_guard",{}) or {}
        except Exception: return {}
    def _record(self,kind,seconds=0,**extra):
        try:
            c=ensure_goal_state(lc()); p=c.setdefault("focus_guard",{}); s=p.setdefault("stats",{})
            if kind=="distraction": s["distractions"]=int(s.get("distractions",0) or 0)+1
            if seconds: s["distraction_seconds"]=int(s.get("distraction_seconds",0) or 0)+max(0,int(seconds or 0))
            if kind not in ("distraction","distraction_seconds") and kind in s: s[kind]=int(s.get(kind,0) or 0)+1
            evlog(c,"focus_"+kind,"专注控制",extra); sc(c)
        except Exception: pass
    def _allowed(self,exe,hwnd=0):
        now=time.time(); self._allow={k:v for k,v in self._allow.items() if v>now}
        p=self._policy()
        if p.get("enabled",True) is False or float(p.get("pause_until",0) or 0)>now: return True
        override=(p.get("app_overrides",{}) or {}).get(exe)
        if override=="allow" or exe in self._SYSTEM or exe in self._EXEMPT or exe in self._allow: return True
        if os.path.splitext(exe)[0].lower()==os.path.splitext(self._session_allowed_exe)[0].lower(): return True
        try:
            c=ensure_goal_state(lc()); ctx=focus_context(c)
            blocked={os.path.splitext(task_text(x))[0].lower() for x in as_list(ctx.get("blocked_apps",[]))}
            if os.path.splitext(exe)[0].lower() in blocked: return False
            apps={os.path.splitext(task_text(x))[0].lower() for x in focus_task_apps(c)}
            if not apps: return True  # setup mode: never block before a work desktop exists
            return os.path.splitext(exe)[0].lower() in {os.path.splitext(x)[0].lower() for x in apps}
        except Exception: return False
    def _tick(self):
        if not self.alive or not getattr(self.app,"alive",True):
            try: self.root.destroy()
            except Exception: pass
            return
        if getattr(self,'_menu_open',False):
            try: self.root.after(500,self._tick)
            except Exception: pass
            return
        try:
            u32=ctypes.windll.user32; active=u32.GetForegroundWindow(); exe=foreground_exe(active)
            if self._session_allowed_exe and os.path.splitext(exe)[0].lower()!=os.path.splitext(self._session_allowed_exe)[0].lower():
                self._session_allowed_exe=""
            self._task_hwnd=find_window("Task Verge") or self._task_hwnd
            task_active=bool(self._task_hwnd and active==self._task_hwnd)
            current=next((t for t in ensure_goal_state(lc()).get("tasks",[]) if isinstance(t,dict) and not task_done(t)),{})
            focus_active=current.get("status")=="doing"
            # ponytail: monitor only during an active session; browsing outside it is not a distraction.
            allowed=not focus_active or task_active or self._allowed(exe,active)
            if allowed:
                if self._bad_since: self._record("distraction_seconds",time.time()-self._bad_since,app=self._last_exe)
                self._bad_since=0; self._last_exe=""; self._offending_hwnd=0; self._hide(); self._set_top(task_active)
            else:
                self._offending_hwnd=active
                if exe!=self._last_exe:
                    if self._bad_since: self._record("distraction_seconds",time.time()-self._bad_since,app=self._last_exe)
                    self._bad_since=time.time(); self._last_exe=exe; self._record("distraction",app=exe)
                elapsed=time.time()-self._bad_since if self._bad_since else 0
                if elapsed>=60:
                    if not getattr(self,"_logged_banner",False):
                        self._logged_banner=True; _bl("focus banner: {}".format(exe or "unknown"))
                    self._set_top(True); self._show(exe,int(elapsed))
                else: self._set_top(False); self._hide()
        except Exception as e:
            if not getattr(self,"_logged_tick_error",False):
                self._logged_tick_error=True; _bl("focus tick: " + repr(e))
        try: self.root.after(500,self._tick)
        except Exception: pass
    def _set_top(self,enabled):
        if self._top==enabled: return
        self._top=enabled; set_topmost(self._task_hwnd,enabled)
    def _hide(self):
        if self._webview_window:
            try: self._webview_window.withdraw()
            except Exception: pass
    def _show(self,exe,elapsed):
        if self._webview_window is not None and getattr(self,'_banner_theme','') != UI_THEME:
            try: self._webview_window.destroy()
            except Exception: pass
            self._webview_window=None
        if self._webview_window is None:
            self._banner_theme=UI_THEME
            dark=UI_THEME=='dark'; card='#161b22' if dark else '#ffffff'; border='#30363d' if dark else '#d0d7de'; title='#f0f6fc' if dark else '#1d1d1f'; muted='#8b949e' if dark else '#6e6e73'; secondary='#21262d' if dark else '#f2f2f7'
            w=self._webview_window=tk.Toplevel(self.root)
            w.overrideredirect(True); w.attributes('-topmost',True); w.configure(bg='#010101')
            w.attributes('-transparentcolor','#010101')
            W,H=540,78; w.geometry('{}x{}+{}+16'.format(W,H,max(0,(w.winfo_screenwidth()-W)//2)))
            c=tk.Canvas(w,width=W,height=H,bg='#010101',highlightthickness=0); c.pack()
            r=14; x0,y0,x1,y1=2,2,W-2,H-2
            # Shadow skirt (4-corner rounded rect, offset +3)
            c.create_rectangle(x0+r,y0+3,x1-r,y1+3,fill='#05070a',outline='')
            c.create_rectangle(x0,y0+r+3,x1,y1-r+3,fill='#05070a',outline='')
            c.create_oval(x0,y0+3,x0+2*r,y0+2*r+3,fill='#05070a',outline='')
            c.create_oval(x1-2*r,y0+3,x1,y0+2*r+3,fill='#05070a',outline='')
            c.create_oval(x0,y1-2*r+3,x0+2*r,y1+3,fill='#05070a',outline='')
            c.create_oval(x1-2*r,y1-2*r+3,x1,y1+3,fill='#05070a',outline='')
            # White card (4-corner rounded rect) — use create_arc for clean corners
            c.create_rectangle(x0+r,y0,x1-r,y1,fill=card,outline=border)
            c.create_rectangle(x0,y0+r,x1,y1-r,fill=card,outline=border)
            c.create_oval(x0,y0,x0+2*r,y0+2*r,fill=card,outline=border)
            c.create_oval(x1-2*r,y0,x1,y0+2*r,fill=card,outline=border)
            c.create_oval(x0,y1-2*r,x0+2*r,y1,fill=card,outline=border)
            c.create_oval(x1-2*r,y1-2*r,x1,y1,fill=card,outline=border)
            ix0,iy0,isz,ir=18,19,40,11; ix1,iy1=ix0+isz,iy0+isz
            c.create_rectangle(ix0+ir,iy0,ix1-ir,iy1,fill='#ff9500',outline='')
            c.create_oval(ix0,iy0,ix0+2*ir,iy0+2*ir,fill='#ff9500',outline='')
            c.create_oval(ix1-2*ir,iy0,ix1,iy0+2*ir,fill='#ff9500',outline='')
            c.create_oval(ix0,iy1-2*ir,ix0+2*ir,iy1,fill='#ff9500',outline='')
            c.create_oval(ix1-2*ir,iy1-2*ir,ix1,iy1,fill='#ff9500',outline='')
            c.create_text(ix0+isz//2,iy0+isz//2-1,text='!',fill='#ffffff',font=('Segoe UI',18,'bold'))
            c.create_text(76,26,text='专注提醒',anchor='w',fill=title,font=('Segoe UI',12,'bold'))
            self._banner_status=c.create_text(76,46,text='',anchor='w',fill=muted,font=('Segoe UI',9))
            self._return_btn=tk.Button(w,text='关闭当前窗口',command=self._close_current_window,
                bg='#238636',fg='#ffffff',activebackground='#2ea043',activeforeground='#ffffff',
                relief='flat',bd=0,highlightthickness=0,padx=13,pady=4,
                font=('Segoe UI',9,'bold'),cursor='hand2')
            self._allow_btn=tk.Button(w,text='允许此应用 ▾',command=self._allow_menu,
                bg=secondary,fg=title,activebackground=border,activeforeground=title,
                relief='flat',bd=0,highlightthickness=0,padx=11,pady=4,
                font=('Segoe UI',9),cursor='hand2')
            self._return_btn.configure(text='回到任务',command=self._return_to_task)
            c.create_window(382,39,window=self._return_btn)
            c.create_window(486,39,window=self._allow_btn)
            self._banner_fade_pending=True
        c=self._webview_window.winfo_children()[0]
        c.itemconfig(self._banner_status,text='{} · 已离开任务 {} 秒'.format(exe or '当前应用',int(elapsed)))
        c.itemconfig(self._banner_status,text='{} · 已离开任务 {} 秒 · 切换应用后恢复提醒'.format(exe or '当前应用',int(elapsed)))
        ctx=focus_context(ensure_goal_state(lc())); task=task_text(ctx.get("task")) or "当前任务"
        def clip(value, limit):
            value=task_text(value) or ""
            return value if len(value)<=limit else value[:max(1,limit-1)]+'…'
        c.itemconfig(self._banner_status,text='{} · {} · {} 秒'.format(clip(exe or '当前应用',12),clip(task,14),int(elapsed)))
        self._return_btn.configure(text='立即回到任务' if elapsed>=60 else '回到任务')
        blocked=any(os.path.splitext(exe or '')[0].lower()==os.path.splitext(task_text(x))[0].lower() for x in ctx.get('blocked_apps',[]))
        self._return_btn.configure(bg='#da3633' if blocked or elapsed>=60 else '#238636')
        self._webview_window.deiconify(); self._webview_window.lift()
        if not getattr(self,"_logged_banner_window",False):
            self._logged_banner_window=True; _bl("focus banner window: state={} viewable={}".format(self._webview_window.state(), self._webview_window.winfo_viewable()))
        if getattr(self,'_banner_fade_pending',False):
            self._banner_fade_pending=False; self._webview_window.attributes('-alpha',0.0); self._fade_banner(0.0)
        return
        if not self._webview_ready.is_set() or not hasattr(self,'_webview'): return
        wv=self._webview
        if self._webview_window is None:
            sw=self.root.winfo_screenwidth()
            x=max(0,(sw-584)//2)
            self._webview_window=wv.create_window(
                "",html=self._banner_html(),width=584,height=88,
                x=x,y=16,frameless=True,easy_drag=False,
                on_top=True,transparent=True,api=self._api)
            def _init():
                try: self._webview_window.evaluate_js('updateText({},{})'.format(json.dumps(exe or "当前应用"),int(elapsed)))
                except Exception: pass
            self._webview_window.events.loaded += _init
        else:
            try: self._webview_window.show()
            except Exception: pass
            try: self._webview_window.evaluate_js('updateText({},{})'.format(json.dumps(exe or "当前应用"),int(elapsed)))
            except Exception: pass
    def _banner_html(self):
        return '''<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:transparent;font-family:'Segoe UI',system-ui,sans-serif;overflow:hidden}
.banner{width:584px;height:88px;background:#fff;border-radius:18px;
box-shadow:0 12px 32px -8px rgba(0,0,0,0.18),0 2px 8px rgba(0,0,0,0.06);
display:flex;align-items:center;padding:0 20px;gap:14px}
.icon{width:40px;height:40px;border-radius:11px;background:#ff9500;
color:#fff;display:flex;align-items:center;justify-content:center;
font-size:20px;font-weight:700;flex-shrink:0}
.text{display:flex;flex-direction:column;gap:4px;flex:1;min-width:0}
.title{font-size:13px;font-weight:700;color:#1d1d1f}
.status{font-size:12px;color:#6e6e73;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.btn{border:none;border-radius:9999px;cursor:pointer;font-size:12px;font-family:inherit;white-space:nowrap}
.btn-close{background:#007aff;color:#fff;padding:8px 14px;font-weight:700}
.btn-close.confirm{background:#ff453a}
.btn-allow{background:#f2f2f7;color:#1d1d1f;padding:8px 12px}
.dropdown{position:absolute;top:100%;right:0;margin-top:4px;background:#fff;
border-radius:10px;box-shadow:0 4px 16px rgba(0,0,0,0.12);padding:4px;
min-width:160px;display:none;border:1px solid #e5e5ea;z-index:100}
.dropdown.show{display:block}
.dropdown-item{padding:8px 12px;font-size:12px;color:#1d1d1f;cursor:pointer;border-radius:6px}
.dropdown-item:hover{background:#f2f2f7}
.dropdown-sep{height:1px;background:#e5e5ea;margin:4px 0}
</style></head><body>
<div class="banner">
<div class="icon">!</div>
<div class="text"><div class="title">专注提醒</div><div class="status" id="status"></div></div>
<button class="btn btn-close" id="closeBtn">关闭当前窗口</button>
<div style="position:relative">
<button class="btn btn-allow" id="allowBtn">允许此应用 ▾</button>
<div class="dropdown" id="menu">
<div class="dropdown-item" onclick="allowApp(0)">本次允许</div>
<div class="dropdown-item" onclick="allowApp(900)">允许 15 分钟</div>
<div class="dropdown-item" onclick="allowApp(-1)">始终允许此应用</div>
<div class="dropdown-sep"></div>
<div class="dropdown-item" onclick="pauseFocus(1800)">暂停专注 30 分钟</div>
</div></div></div>
<script>
var armed=false,timer=null;
function updateText(exe,elapsed){document.getElementById('status').textContent=exe+' · 已离开任务 '+elapsed+' 秒';}
document.getElementById('closeBtn').onclick=function(){
var b=this;if(!armed){armed=true;b.textContent='确认关闭';b.classList.add('confirm');
timer=setTimeout(function(){armed=false;b.textContent='关闭当前窗口';b.classList.remove('confirm');},2000);return;}
clearTimeout(timer);pywebview.api.close_current_window();};
document.getElementById('allowBtn').onclick=function(e){e.stopPropagation();document.getElementById('menu').classList.toggle('show');};
function allowApp(s){document.getElementById('menu').classList.remove('show');pywebview.api.allow_current(s);}
function pauseFocus(s){document.getElementById('menu').classList.remove('show');pywebview.api.pause(s);}
document.addEventListener('click',function(){document.getElementById('menu').classList.remove('show');});
</script></body></html>'''
    def _close_current_window(self):
        hwnd=self._offending_hwnd
        if not hwnd or hwnd==self._task_hwnd: return
        try: ctypes.windll.user32.PostMessageW(hwnd,0x0010,0,0)
        except Exception: pass
        self._record("closed_windows",app=self._last_exe); self._hide(); self._set_top(False)
    def _return_to_task(self):
        try:
            u32=ctypes.windll.user32
            hwnd=self._task_hwnd if self._task_hwnd and u32.IsWindow(self._task_hwnd) else find_window("Task Verge")
            if hwnd:
                self._task_hwnd=hwnd
                u32.ShowWindow(hwnd,9)
                u32.SetForegroundWindow(hwnd)
        except Exception: pass
        self._hide(); self._set_top(False)
    def _allow_menu(self):
        self._menu_open=True
        dark=UI_THEME=='dark'
        menu=tk.Menu(self._webview_window,tearoff=0,
            bg='#161b22' if dark else '#ffffff',fg='#c9d1d9' if dark else '#1d1d1f',
            activebackground='#21262d' if dark else '#eaf3ff',activeforeground='#58a6ff' if dark else '#007aff',font=('Segoe UI',9),
            bd=0,relief='flat',activeborderwidth=0)
        menu.add_command(label='关闭当前窗口',command=self._close_current_window)
        menu.add_separator()
        menu.add_command(label='\u5141\u8bb8\u5f53\u524d\u5e94\u7528\u76f4\u5230\u5207\u6362',command=lambda:self._allow_current(0))
        menu.add_command(label='\u6682\u505c\u4e13\u6ce8 30 \u5206\u949f',command=lambda:self._pause(1800))
        menu.bind('<Unmap>',lambda e:setattr(self,'_menu_open',False))
        menu.update_idletasks()
        right=self._webview_window.winfo_rootx()+520
        menu.tk_popup(right-menu.winfo_reqwidth(),self._webview_window.winfo_rooty()+70)
        return
        dark=UI_THEME=='dark'; menu=tk.Menu(self._webview_window,tearoff=0,
            bg='#161b22' if dark else '#ffffff',fg='#c9d1d9' if dark else '#1d1d1f',
            activebackground='#21262d' if dark else '#eaf3ff',activeforeground='#58a6ff' if dark else '#007aff',font=('Segoe UI',9),
            bd=0,relief='flat',activeborderwidth=0)
        menu.add_command(label='本次允许',command=lambda:self._allow_current(0))
        menu.add_command(label='允许 15 分钟',command=lambda:self._allow_current(900))
        menu.add_command(label='始终允许此应用',command=lambda:self._allow_current(-1))
        menu.add_separator()
        menu.add_command(label='暂停专注 30 分钟',command=lambda:self._pause(1800))
        menu.bind('<Unmap>',lambda e:setattr(self,'_menu_open',False))
        menu.update_idletasks()
        right=self._webview_window.winfo_rootx()+520
        menu.tk_popup(right-menu.winfo_reqwidth(),self._webview_window.winfo_rooty()+70)
    def _fade_banner(self,alpha):
        if not self._webview_window or not self._webview_window.winfo_exists(): return
        alpha=min(1.0,alpha+0.2); self._webview_window.attributes('-alpha',alpha)
        if alpha<1.0: self.root.after(20,lambda:self._fade_banner(alpha))
    def _pause(self,seconds):
        self._menu_open=False
        try:
            c=ensure_goal_state(lc()); p=c.setdefault("focus_guard",{}); p["pause_until"]=time.time()+seconds; sc(c); self._record("paused")
        except Exception: pass
        self._hide(); self._set_top(False)
    def _allow_current(self,seconds=900):
        self._menu_open=False
        if seconds==0: self._session_allowed_exe=self._last_exe
        if self._last_exe and seconds>0: self._allow[self._last_exe]=time.time()+seconds
        if self._last_exe and seconds<0:
            try:
                c=ensure_goal_state(lc()); c.setdefault("focus_guard",{}).setdefault("app_overrides",{})[self._last_exe]="allow"; sc(c); self._record("permanent_allows",app=self._last_exe)
            except Exception: pass
        elif self._last_exe: self._record("temporary_allows",app=self._last_exe)
        self._hide(); self._set_top(False)

def ico():
    bundled=os.path.join(WEB_DIR,"taskverge.ico")
    if os.path.exists(bundled): return bundled
    p=P["ico"]
    if os.path.exists(p): return p
    w,h=32,32; fg=bytes((255,255,255,255)); bg=bytes((17,17,17,0))
    px=bytearray(w*h*4)
    for y in range(h):
        for x in range(w):
            i=((h-1-y)*w+x)*4; top=y<6; stem=12<=x<20 and y>=6
            px[i:i+4]=fg if (top or stem) else bg
    inf=struct.pack('<IiiHHIIiiII',40,w,h*2,1,32,0,len(px),0,0,0,0)
    ent=struct.pack('<BBBBHHII',w,h,0,0,1,32,len(inf)+len(px),22)
    with open(p,'wb') as f: f.write(struct.pack('<HHH',0,1,1)+ent+inf+px)
    return p
atexit.register(lambda: os.path.exists(P["ico"]) and os.remove(P["ico"]))

if __name__ == "__main__":
    for a in sys.argv[1:]:
        _bl("main: arg {}".format(a))
        if a=="--generate": cli_gen(); sys.exit(0)
        if a=="--evaluate": cli_eval(); sys.exit(0)
        if a=="--stats": cli_stats(); sys.exit(0)
        if a=="--ci":
            # CI mode: start HTTP server only, no tray, no desktop, no single-instance guard
            _bl("main: CI mode, starting web app only")
            crash_mark_running()
            atexit.register(crash_mark_clean)
            TASKS = TaskService(text=task_text, normalize=normalize_tasks, goal_id=gid, sync_pct=sync_pct,
                                save=save_goal_state, event=evlog, undo=push_undo, compact=sc, outcome=adaptive.record_outcome,
                        readiness=lambda c: adaptive.goal_readiness(goal_details(c)), first_task_started=mark_first_task_started)
            AGENTS = AgentService(lambda: _agent_orchestrator(ensure_goal_state(lc())),
                                  start_loop=lambda run_id: JOBS.submit(_agent_loop, ensure_goal_state(lc()), run_id, key="agent:" + run_id))
            FEEDBACK = FeedbackService(record=adaptive.record_feedback, done=task_done, sync_pct=sync_pct,
                                       save=save_goal_state, event=evlog, compact=sc)
            ACCEPTANCE = AcceptanceService(normalize=normalize_tasks, text=task_text, sync_pct=sync_pct,
                                           save=save_goal_state, event=evlog, outcome=adaptive.record_outcome,
                                           learning_outcome=adaptive.record_learning_outcome)
            WEBAPP = WebApp()
            # Port zero asks the OS for an available port; CI then publishes the
            # resolved URL for every downstream test step. A positive explicit
            # TASKVERGE_PORT remains useful for local/remote smoke tooling.
            try: ci_port = int(os.environ.get("TASKVERGE_PORT", "0") or 0)
            except (TypeError, ValueError): ci_port = 0
            s = BoundedHTTPServer(("127.0.0.1", ci_port), Handler)
            url = "http://127.0.0.1:{}/".format(s.server_port)
            try:
                with open(P["url"], "w", encoding="utf-8") as f: f.write(url)
            except Exception: pass
            _bl("ci: " + url)
            print("CI_URL=" + url)
            sys.stdout.flush()
            threading.Thread(target=s.serve_forever, daemon=True).start()
            try:
                while True: time.sleep(3600)
            except KeyboardInterrupt:
                crash_mark_clean(); WEBAPP.alive = False; s.shutdown()
            sys.exit(0)
    single_instance_guard()
    mutex_name = "Local\\TaskPanel_D_work_S_scripts"
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
    err = ctypes.windll.kernel32.GetLastError()
    if err == 183:  # ERROR_ALREADY_EXISTS
        # Check for WAIT_ABANDONED — previous holder died without releasing
        rc = ctypes.windll.kernel32.WaitForSingleObject(mutex, 0)
        if rc == 0x00000080:  # WAIT_ABANDONED
            _bl("main: abandoned mutex detected, taking ownership")
            ctypes.windll.kernel32.ReleaseMutex(mutex)
            # Re-create mutex
            ctypes.windll.kernel32.CloseHandle(mutex)
            mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
        else:
            _bl("main: mutex failed, exiting")
            if not focus_window("Task Verge"):
                try:
                    with open(P["url"], encoding="utf-8") as f: open_desktop(f.read().strip())
                except Exception: pass
            sys.exit(2)
    try: os.remove(P["stop"])
    except OSError: pass
    _bl("main: mutex ok, starting web app")
    run_web()
