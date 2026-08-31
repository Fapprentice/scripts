"""Durable local persistence for Task Verge."""

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

APPLICATION_ID = 0x54564745
SCHEMA_VERSION = 3
MIGRATIONS = {1: "initial_schema", 2: "companion_growth", 3: "skill_prerequisite_kind"}
COMPANION_ID = "dafeiyu"
COMPANION_NAME = "大肥鱼"
COMPANION_DEFAULT_ENERGY = 70
COMPANION_DEFAULT_BOND = 20
COMPANION_DOCUMENT = "companion.json"


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, traceback):
        try:
            return super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


class StorageCorruptionError(RuntimeError):
    """Existing user data is unreadable and must not be overwritten."""


class JsonStore:
    """Legacy JSON adapter kept for compatibility and migration tests."""

    def __init__(self, log_path=None): self.log_path = log_path

    def load(self, path, default=None):
        try:
            with open(path, encoding="utf-8-sig") as f: return json.load(f)
        except FileNotFoundError: return {} if default is None else default
        except Exception as exc:
            if self.log_path:
                try:
                    with open(self.log_path, "a", encoding="utf-8") as f:
                        f.write("{} JSON_FAIL {}: {}\n".format(path, os.path.basename(path), exc))
                except OSError: pass
            return {} if default is None else default

    def save(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".json", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            try: os.remove(tmp)
            except OSError: pass


class SqliteStore:
    """One seam for state, migration, backups and managed attachments."""

    def __init__(self, data_dir, log_path=None, auto_backup=True):
        self.root = Path(data_dir); self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "taskverge.db"
        self.attachments_dir = self.root / "attachments"
        self.backups_dir = self.root / "backups"
        self.trash_dir = self.root / "trash"
        self.legacy_dir = self.root / "legacy-json"
        self.log_path = Path(log_path) if log_path else self.root / "watchdog.log"
        self._lock = threading.RLock(); self._auto_backup = auto_backup; self._last_backup = 0.0
        for directory in (self.attachments_dir, self.backups_dir, self.trash_dir, self.legacy_dir):
            directory.mkdir(parents=True, exist_ok=True)
        existed = self.db_path.exists()
        if existed:
            self._verify_database(self.db_path, quick=True)
            if self._stored_schema_version() < SCHEMA_VERSION:
                self.create_backup("pre-migration")
        self._initialize()
        if existed: self.maybe_backup()

    def _connect(self, path=None):
        db = sqlite3.connect(str(path or self.db_path), timeout=5, factory=_ClosingConnection)
        db.execute("PRAGMA foreign_keys=ON"); db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=5000"); db.execute("PRAGMA journal_mode=DELETE")
        return db

    @contextmanager
    def _atomic(self, immediate=False):
        # The store lock serializes companion read-modify-write. The connection
        # commits on success and rolls back on error via _ClosingConnection.
        with self._lock, self._connect() as db:
            yield db

    def _run_companion_mutator(self, db, mutator):
        self._ensure_companion_row(db)
        row = self._companion_from_row(db.execute(
            "SELECT id,name,energy,bond,day,poke_used,feed_used,talk_used,last_poke_at,last_feed_at,last_talk_at,last_settle_at,last_rest_start_at,payload,updated_at FROM companions WHERE id=?",
            (COMPANION_ID,)).fetchone())
        txn = _CompanionTxn(self, db)
        extra = mutator(row, txn)
        return extra

    def mutate_companion(self, mutator):
        with self._atomic(immediate=True) as db:
            return self._run_companion_mutator(db, mutator)

    def _initialize(self):
        schema = """
        CREATE TABLE IF NOT EXISTS documents(name TEXT PRIMARY KEY,payload TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS schema_migrations(to_version INTEGER PRIMARY KEY,from_version INTEGER NOT NULL,name TEXT NOT NULL,applied_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attachments(sha256 TEXT PRIMARY KEY,stored_path TEXT NOT NULL UNIQUE,original_name TEXT NOT NULL,size INTEGER NOT NULL,created_at TEXT NOT NULL,trashed_at TEXT);
        CREATE TABLE IF NOT EXISTS goals(id TEXT PRIMARY KEY,payload TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS success_criteria(id TEXT PRIMARY KEY,goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS constraints(id TEXT PRIMARY KEY,goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,goal_id TEXT REFERENCES goals(id) ON DELETE CASCADE,payload TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS task_criteria(id TEXT PRIMARY KEY,task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS materials(id TEXT PRIMARY KEY,task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS answer_keys(id TEXT PRIMARY KEY,material_id TEXT REFERENCES materials(id) ON DELETE CASCADE,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY,task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,attachment_sha256 TEXT REFERENCES attachments(sha256),payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS acceptance_runs(id TEXT PRIMARY KEY,task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,payload TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS focus_sessions(id TEXT PRIMARY KEY,task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY,task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS skills(id TEXT PRIMARY KEY,goal_id TEXT REFERENCES goals(id) ON DELETE CASCADE,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS skill_prerequisites(skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,prerequisite_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,kind TEXT NOT NULL DEFAULT 'legacy_unspecified',rationale TEXT NOT NULL DEFAULT '',PRIMARY KEY(skill_id,prerequisite_id));
        CREATE TABLE IF NOT EXISTS review_logs(id TEXT PRIMARY KEY,skill_id TEXT REFERENCES skills(id) ON DELETE SET NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,goal_id TEXT REFERENCES goals(id) ON DELETE SET NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS motivation_ledger(id TEXT PRIMARY KEY,goal_id TEXT REFERENCES goals(id) ON DELETE SET NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS app_usage_daily(day TEXT NOT NULL,app TEXT NOT NULL,seconds INTEGER NOT NULL,PRIMARY KEY(day,app));
        CREATE TABLE IF NOT EXISTS eval_samples(id TEXT PRIMARY KEY,payload TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS deleted_items(id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,deleted_at TEXT NOT NULL);
        """
        with self._lock, self._connect() as db:
            db.executescript(schema)
            columns = {row[1] for row in db.execute("PRAGMA table_info(schema_migrations)")}
            if "to_version" not in columns:
                db.execute("ALTER TABLE schema_migrations RENAME TO schema_migrations_legacy")
                db.execute("CREATE TABLE schema_migrations(to_version INTEGER PRIMARY KEY,from_version INTEGER NOT NULL,name TEXT NOT NULL,applied_at TEXT NOT NULL)")
                for version, applied_at in db.execute("SELECT version,applied_at FROM schema_migrations_legacy"):
                    db.execute("INSERT INTO schema_migrations VALUES (?,?,?,?)", (version, version - 1, MIGRATIONS.get(version, "legacy"), applied_at))
                db.execute("DROP TABLE schema_migrations_legacy")
            db.execute("PRAGMA application_id={}".format(APPLICATION_ID))
            current = db.execute("PRAGMA user_version").fetchone()[0]
            if current > SCHEMA_VERSION:
                raise StorageCorruptionError("database schema is newer than this application")
            if current < SCHEMA_VERSION:
                for version in range(current + 1, SCHEMA_VERSION + 1):
                    self._migration(version, db)
                    db.execute("INSERT OR REPLACE INTO schema_migrations VALUES (?,?,?,?)", (version, version - 1, MIGRATIONS[version], datetime.now().isoformat()))
                db.execute("PRAGMA user_version={}".format(SCHEMA_VERSION))
            self._ensure_companion_row(db)

    def _migration(self, version, db):
        if version == 1:
            return
        if version == 2:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS companions(id TEXT PRIMARY KEY,name TEXT NOT NULL,energy INTEGER NOT NULL,bond INTEGER NOT NULL,day TEXT NOT NULL,poke_used INTEGER NOT NULL DEFAULT 0,feed_used INTEGER NOT NULL DEFAULT 0,talk_used INTEGER NOT NULL DEFAULT 0,last_poke_at TEXT,last_feed_at TEXT,last_talk_at TEXT,last_settle_at TEXT,last_rest_start_at TEXT,payload TEXT NOT NULL DEFAULT '{}',updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS companion_events(id TEXT PRIMARY KEY,ts TEXT NOT NULL,kind TEXT NOT NULL,treat TEXT,delta_energy INTEGER NOT NULL DEFAULT 0,delta_bond INTEGER NOT NULL DEFAULT 0,reason TEXT NOT NULL,task_id TEXT,goal_id TEXT,dedupe_key TEXT,source TEXT,payload TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_companion_events_ts ON companion_events(ts);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_companion_events_dedupe ON companion_events(dedupe_key) WHERE dedupe_key IS NOT NULL;
            """)
            return
        if version == 3:
            columns = {row[1] for row in db.execute("PRAGMA table_info(skill_prerequisites)")}
            if "kind" not in columns:
                db.execute("ALTER TABLE skill_prerequisites ADD COLUMN kind TEXT NOT NULL DEFAULT 'legacy_unspecified'")
            if "rationale" not in columns:
                db.execute("ALTER TABLE skill_prerequisites ADD COLUMN rationale TEXT NOT NULL DEFAULT ''")
            return
        raise StorageCorruptionError("missing migration for schema {}".format(version))

    def _stored_schema_version(self):
        with sqlite3.connect(str(self.db_path), factory=_ClosingConnection) as db:
            return db.execute("PRAGMA user_version").fetchone()[0]

    def schema_version(self):
        """Return the database's applied schema version for diagnostics."""
        return self._stored_schema_version()

    def migration_history(self):
        """Return migration records in application order."""
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT from_version,to_version,name FROM schema_migrations ORDER BY to_version").fetchall()
        return [{"from_version": source, "to_version": target, "name": name} for source, target, name in rows]

    @classmethod
    def find_valid_backups(cls, data_dir):
        root = Path(data_dir); valid = []
        for path in sorted((root / "backups").glob("*/*.db"), key=lambda item:item.stat().st_mtime, reverse=True):
            try:
                with sqlite3.connect(str(path), factory=_ClosingConnection) as db:
                    ok = db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                    app_id = db.execute("PRAGMA application_id").fetchone()[0]
                if ok and app_id == APPLICATION_ID: valid.append(str(path))
            except sqlite3.DatabaseError: pass
        return valid

    @classmethod
    def recover_from_backup(cls, data_dir, backup_path):
        root = Path(data_dir); source = Path(backup_path).resolve(); backup_root = (root / "backups").resolve()
        if not source.is_file() or backup_root not in source.parents or str(source) not in cls.find_valid_backups(root):
            raise StorageCorruptionError("no valid recovery backup")
        database = root / "taskverge.db"
        corrupt = root / ("taskverge.corrupt-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".db")
        if database.exists(): os.replace(database, corrupt)
        try:
            shutil.copy2(source, database)
            with sqlite3.connect(str(database), factory=_ClosingConnection) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok": raise StorageCorruptionError("recovered database failed integrity check")
        except Exception:
            database.unlink(missing_ok=True)
            if corrupt.exists(): os.replace(corrupt, database)
            raise
        return str(corrupt)

    @staticmethod
    def _key(path): return os.path.basename(os.fspath(path)).lower()

    def load(self, path, default=None):
        key = self._key(path)
        with self._lock, self._connect() as db:
            row = db.execute("SELECT payload FROM documents WHERE name=?", (key,)).fetchone()
        if row:
            try: return json.loads(row[0])
            except (TypeError, json.JSONDecodeError) as exc:
                raise StorageCorruptionError("database document is corrupt: {}".format(key)) from exc
        legacy = Path(path)
        if legacy.exists(): return self._migrate_one(legacy, default)
        return {} if default is None else default

    def _migrate_one(self, legacy, default=None):
        try:
            with legacy.open(encoding="utf-8-sig") as handle: data = json.load(handle)
        except Exception as exc:
            self._log("MIGRATION_FAIL {}: {}".format(legacy.name, exc))
            raise StorageCorruptionError("legacy JSON is corrupt: {}".format(legacy)) from exc
        backup = self.legacy_dir / legacy.name
        if not backup.exists(): shutil.copy2(legacy, backup)
        self.save(str(legacy), data, backup=False)
        return data if data is not None else ({} if default is None else default)

    def save(self, path, data, backup=True, companion_mutator=None):
        now = datetime.now().isoformat()
        with self._atomic(immediate=True) as db:
            if companion_mutator:
                self._run_companion_mutator(db, companion_mutator)
            payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            db.execute("""INSERT INTO documents(name,payload,revision,updated_at) VALUES (?,?,1,?)
                ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,revision=documents.revision+1,updated_at=excluded.updated_at""",
                       (self._key(path), payload, now))
            if self._key(path) == "task-config.json" and isinstance(data, dict): self._project_state(db, data, now)
            elif self._key(path) == "fgtime.json" and isinstance(data, dict): self._project_app_usage(db, data)
        if backup: self.maybe_backup()

    @staticmethod
    def _json(value): return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _row_id(prefix, value, index):
        if isinstance(value, dict) and value.get("id"): return "{}-{}-{}".format(prefix, index, value["id"])
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return "{}-{}-{}".format(prefix, index, hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12])

    def _project_state(self, db, state, now):
        # SQLite is the source of truth; JSON documents are compatibility snapshots replaced in the same transaction as relational projections.
        for table in ("skill_prerequisites","task_criteria","answer_keys","evidence","acceptance_runs",
                      "focus_sessions","feedback","review_logs","skills","materials","tasks",
                      "success_criteria","constraints","events","motivation_ledger","goals"):
            db.execute("DELETE FROM " + table)
        goals = [g for g in state.get("goals", []) if isinstance(g, dict)]
        goal_ids = set()
        for gi, goal in enumerate(goals):
            goal_id = str(goal.get("id") or "goal_{}".format(gi)); goal_ids.add(goal_id)
            db.execute("INSERT INTO goals VALUES (?,?,?)", (goal_id, self._json(goal), now))
            for ci, criterion in enumerate(goal.get("success_criteria", []) or []):
                db.execute("INSERT INTO success_criteria VALUES (?,?,?)", (self._row_id(goal_id+"-criterion",criterion,ci),goal_id,self._json(criterion)))
            for ci, constraint in enumerate(goal.get("constraints", []) or []):
                db.execute("INSERT INTO constraints VALUES (?,?,?)", (self._row_id(goal_id+"-constraint",constraint,ci),goal_id,self._json(constraint)))
        task_groups = state.get("tasks_by_goal", {}) if isinstance(state.get("tasks_by_goal"), dict) else {}
        seen_tasks = set()
        for goal_id, tasks in task_groups.items():
            parent = str(goal_id) if str(goal_id) in goal_ids else None
            for ti, task in enumerate(tasks if isinstance(tasks, list) else []):
                if not isinstance(task, dict): continue
                task_id = str(task.get("id") or self._row_id("task",task,ti))
                if task_id in seen_tasks: continue
                seen_tasks.add(task_id)
                db.execute("INSERT INTO tasks VALUES (?,?,?,?)", (task_id,parent,self._json(task),now))
                criteria = task.get("acceptance_criteria") or ([task.get("acceptance")] if task.get("acceptance") else [])
                for ci, criterion in enumerate(criteria if isinstance(criteria, list) else [criteria]):
                    db.execute("INSERT INTO task_criteria VALUES (?,?,?)", (self._row_id(task_id+"-criterion",criterion,ci),task_id,self._json(criterion)))
                materials = task.get("materials") if isinstance(task.get("materials"), list) else []
                for mi, material in enumerate(materials):
                    material_id = self._row_id(task_id+"-material",material,mi)
                    db.execute("INSERT INTO materials VALUES (?,?,?)", (material_id,task_id,self._json(material)))
                for ei, evidence in enumerate(task.get("evidence", []) or []):
                    path = str(evidence); digest = None
                    row = db.execute("SELECT sha256 FROM attachments WHERE stored_path=?", (path,)).fetchone()
                    if row: digest = row[0]
                    db.execute("INSERT INTO evidence VALUES (?,?,?,?)", (self._row_id(task_id+"-evidence",evidence,ei),task_id,digest,self._json(evidence)))
                result = task.get("acceptance_result")
                if result:
                    db.execute("INSERT INTO acceptance_runs VALUES (?,?,?,?)", (self._row_id(task_id+"-acceptance",result,0),task_id,self._json(result),str(result.get("ts",now)) if isinstance(result,dict) else now))
        for ei, event in enumerate(state.get("events", []) or []):
            if not isinstance(event, dict): continue
            goal_id = str(event.get("goal_id")) if str(event.get("goal_id")) in goal_ids else None
            db.execute("INSERT INTO events VALUES (?,?,?,?)", (self._row_id("event",event,ei),goal_id,self._json(event),str(event.get("ts") or event.get("created_at") or now)))
        history = state.get("motivation", {}).get("history", []) if isinstance(state.get("motivation"), dict) else []
        for mi, entry in enumerate(history if isinstance(history,list) else []):
            goal_id = str(entry.get("goal_id")) if isinstance(entry,dict) and str(entry.get("goal_id")) in goal_ids else None
            db.execute("INSERT INTO motivation_ledger VALUES (?,?,?)", (self._row_id("motivation",entry,mi),goal_id,self._json(entry)))
        # Companion tables are independent of this DELETE/INSERT projection.
        # A JSON snapshot is written in the same transaction for restore/export only.
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='companions'").fetchone():
            self._snapshot_companion_document(db, now)
        models = state.get("user_models_by_goal", {}) if isinstance(state.get("user_models_by_goal"),dict) else {}
        for goal_id, model in models.items():
            if not isinstance(model,dict): continue
            raw_skills = model.get("skills") or {}
            if isinstance(raw_skills, dict):
                skill_items = [dict(value, id=key) if isinstance(value, dict) else {"id": key}
                               for key, value in raw_skills.items()]
            elif isinstance(raw_skills, list):
                skill_items = [item for item in raw_skills if isinstance(item, dict)]
            else:
                skill_items = []
            inserted = {}
            for si, skill in enumerate(skill_items):
                local_id = str(skill.get("id") or skill.get("key") or self._row_id("skill",skill,si))
                skill_id = "{}::{}".format(goal_id, local_id)
                db.execute("INSERT INTO skills VALUES (?,?,?)", (skill_id,str(goal_id) if str(goal_id) in goal_ids else None,self._json(skill)))
                inserted[local_id] = skill_id
            for local_id, skill_id in inserted.items():
                skill = next((item for item in skill_items if str(item.get("id") or item.get("key") or "") == local_id), {})
                meta = skill.get("prerequisite_meta") if isinstance(skill.get("prerequisite_meta"), dict) else {}
                for parent in skill.get("prerequisites") or []:
                    parent = str(parent).strip()
                    if not parent:
                        continue
                    parent_id = inserted.get(parent) or "{}::{}".format(goal_id, parent)
                    if not db.execute("SELECT 1 FROM skills WHERE id=?", (parent_id,)).fetchone():
                        continue
                    info = meta.get(parent) if isinstance(meta.get(parent), dict) else {}
                    kind = str(info.get("kind") or "legacy_unspecified")
                    if kind not in ("hard", "soft", "legacy_unspecified"):
                        kind = "legacy_unspecified"
                    rationale = str(info.get("rationale") or "")
                    db.execute("INSERT OR IGNORE INTO skill_prerequisites(skill_id,prerequisite_id,kind,rationale) VALUES (?,?,?,?)",
                               (skill_id, parent_id, kind, rationale))
            for ri, review in enumerate(model.get("fsrs_review_logs",[]) or []):
                if not isinstance(review,dict): continue
                raw_skill_id = str(review.get("skill_id") or review.get("skill") or "")
                skill_id = "{}::{}".format(goal_id,raw_skill_id) if raw_skill_id else None
                if skill_id and not db.execute("SELECT 1 FROM skills WHERE id=?",(skill_id,)).fetchone(): skill_id=None
                db.execute("INSERT INTO review_logs VALUES (?,?,?)", (self._row_id(str(goal_id)+"-review",review,ri),skill_id,self._json(review)))
        feedback_groups = state.get("feedback_by_goal", {}) if isinstance(state.get("feedback_by_goal"),dict) else {}
        for goal_id, entries in feedback_groups.items():
            for fi, entry in enumerate(entries if isinstance(entries,list) else []):
                task_id = str(entry.get("task_id")) if isinstance(entry,dict) else None
                if task_id not in seen_tasks: task_id=None
                db.execute("INSERT INTO feedback VALUES (?,?,?)", (self._row_id(str(goal_id)+"-feedback",entry,fi),task_id,self._json(entry)))

    def _project_app_usage(self, db, data):
        db.execute("DELETE FROM app_usage_daily")
        for key, seconds in data.items():
            if isinstance(seconds,(int,float)):
                day, app = (str(key).split("|",1)+[""])[:2] if "|" in str(key) else ("unknown",str(key))
                db.execute("INSERT INTO app_usage_daily VALUES (?,?,?)", (day,app,int(seconds)))

    def _default_companion_row(self, now=None):
        now = now or datetime.now().isoformat()
        return {
            "id": COMPANION_ID, "name": COMPANION_NAME,
            "energy": COMPANION_DEFAULT_ENERGY, "bond": COMPANION_DEFAULT_BOND,
            "day": datetime.now().date().isoformat(),
            "poke_used": 0, "feed_used": 0, "talk_used": 0,
            "last_poke_at": None, "last_feed_at": None, "last_talk_at": None,
            "last_settle_at": now, "last_rest_start_at": None,
            "payload": {}, "updated_at": now,
        }

    def _companion_from_row(self, row):
        if not row:
            return self._default_companion_row()
        payload = row[13]
        if isinstance(payload, str):
            try: payload = json.loads(payload) if payload else {}
            except (TypeError, json.JSONDecodeError): payload = {}
        if not isinstance(payload, dict): payload = {}
        return {
            "id": row[0], "name": row[1], "energy": int(row[2] or 0), "bond": int(row[3] or 0),
            "day": row[4] or datetime.now().date().isoformat(),
            "poke_used": int(row[5] or 0), "feed_used": int(row[6] or 0), "talk_used": int(row[7] or 0),
            "last_poke_at": row[8], "last_feed_at": row[9], "last_talk_at": row[10],
            "last_settle_at": row[11], "last_rest_start_at": row[12],
            "payload": payload, "updated_at": row[14],
        }

    def _ensure_companion_row(self, db, now=None):
        now = now or datetime.now().isoformat()
        existing = db.execute("SELECT 1 FROM companions WHERE id=?", (COMPANION_ID,)).fetchone()
        if existing:
            return
        row = self._default_companion_row(now)
        db.execute(
            "INSERT INTO companions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["id"], row["name"], row["energy"], row["bond"], row["day"],
             row["poke_used"], row["feed_used"], row["talk_used"],
             row["last_poke_at"], row["last_feed_at"], row["last_talk_at"],
             row["last_settle_at"], row["last_rest_start_at"], self._json(row["payload"]), row["updated_at"]),
        )
        self._snapshot_companion_document(db, now)

    def _companion_document_payload(self, db):
        row = db.execute("SELECT id,name,energy,bond,day,poke_used,feed_used,talk_used,last_poke_at,last_feed_at,last_talk_at,last_settle_at,last_rest_start_at,payload,updated_at FROM companions WHERE id=?", (COMPANION_ID,)).fetchone()
        companion = self._companion_from_row(row)
        events = []
        for item in db.execute("SELECT id,ts,kind,treat,delta_energy,delta_bond,reason,task_id,goal_id,dedupe_key,source,payload FROM companion_events ORDER BY ts DESC, created_at DESC LIMIT 200"):
            extra = item[11]
            if isinstance(extra, str):
                try: extra = json.loads(extra) if extra else {}
                except (TypeError, json.JSONDecodeError): extra = {}
            events.append({
                "id": item[0], "ts": item[1], "kind": item[2], "treat": item[3],
                "delta_energy": item[4], "delta_bond": item[5], "reason": item[6],
                "task_id": item[7], "goal_id": item[8], "dedupe_key": item[9],
                "source": item[10], "payload": extra if isinstance(extra, dict) else {},
            })
        return {"companion": companion, "events": events}

    def _snapshot_companion_document(self, db, now=None):
        now = now or datetime.now().isoformat()
        payload = self._json(self._companion_document_payload(db))
        db.execute("""INSERT INTO documents(name,payload,revision,updated_at) VALUES (?,?,1,?)
            ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,revision=documents.revision+1,updated_at=excluded.updated_at""",
                   (COMPANION_DOCUMENT, payload, now))

    def ensure_companion(self):
        with self._atomic() as db:
            self._ensure_companion_row(db)

    def load_companion(self):
        with self._atomic() as db:
            self._ensure_companion_row(db)
            row = db.execute("SELECT id,name,energy,bond,day,poke_used,feed_used,talk_used,last_poke_at,last_feed_at,last_talk_at,last_settle_at,last_rest_start_at,payload,updated_at FROM companions WHERE id=?", (COMPANION_ID,)).fetchone()
        return self._companion_from_row(row)

    def _write_companion_on(self, db, companion, event=None):
        now = datetime.now().isoformat()
        companion = dict(companion or {})
        companion["id"] = companion.get("id") or COMPANION_ID
        companion["name"] = companion.get("name") or COMPANION_NAME
        companion["updated_at"] = now
        db.execute(
            """INSERT INTO companions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name,energy=excluded.energy,bond=excluded.bond,day=excluded.day,
            poke_used=excluded.poke_used,feed_used=excluded.feed_used,talk_used=excluded.talk_used,
            last_poke_at=excluded.last_poke_at,last_feed_at=excluded.last_feed_at,last_talk_at=excluded.last_talk_at,
            last_settle_at=excluded.last_settle_at,last_rest_start_at=excluded.last_rest_start_at,
            payload=excluded.payload,updated_at=excluded.updated_at""",
            (companion["id"], companion["name"], int(companion.get("energy") or 0), int(companion.get("bond") or 0),
             companion.get("day") or datetime.now().date().isoformat(),
             int(companion.get("poke_used") or 0), int(companion.get("feed_used") or 0), int(companion.get("talk_used") or 0),
             companion.get("last_poke_at"), companion.get("last_feed_at"), companion.get("last_talk_at"),
             companion.get("last_settle_at"), companion.get("last_rest_start_at"),
             self._json(companion.get("payload") if isinstance(companion.get("payload"), dict) else {}), now),
        )
        if event:
            extra = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            db.execute(
                "INSERT INTO companion_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (event.get("id") or self._row_id("companion", event, 0), event.get("ts") or now,
                 event.get("kind") or "event", event.get("treat"),
                 int(event.get("delta_energy") or 0), int(event.get("delta_bond") or 0),
                 event.get("reason") or "", event.get("task_id"), event.get("goal_id"),
                 event.get("dedupe_key"), event.get("source") or "user", self._json(extra), now),
            )
        self._snapshot_companion_document(db, now)
        return companion

    def write_companion(self, companion, event=None):
        with self._atomic(immediate=True) as db:
            return self._write_companion_on(db, companion, event)

    def _event_from_row(self, row):
        if not row:
            return None
        extra = row[11]
        if isinstance(extra, str):
            try: extra = json.loads(extra) if extra else {}
            except (TypeError, json.JSONDecodeError): extra = {}
        return {
            "id": row[0], "ts": row[1], "kind": row[2], "treat": row[3],
            "delta_energy": row[4], "delta_bond": row[5], "reason": row[6],
            "task_id": row[7], "goal_id": row[8], "dedupe_key": row[9],
            "source": row[10], "payload": extra if isinstance(extra, dict) else {},
        }

    def find_companion_event(self, dedupe_key, db=None):
        if not dedupe_key:
            return None
        if db is None:
            with self._atomic() as conn:
                row = conn.execute("SELECT id,ts,kind,treat,delta_energy,delta_bond,reason,task_id,goal_id,dedupe_key,source,payload FROM companion_events WHERE dedupe_key=?", (dedupe_key,)).fetchone()
            return self._event_from_row(row)
        row = db.execute("SELECT id,ts,kind,treat,delta_energy,delta_bond,reason,task_id,goal_id,dedupe_key,source,payload FROM companion_events WHERE dedupe_key=?", (dedupe_key,)).fetchone()
        return self._event_from_row(row)

    def last_companion_event(self):
        with self._atomic() as db:
            row = db.execute("SELECT id,ts,kind,treat,delta_energy,delta_bond,reason,task_id,goal_id,dedupe_key,source,payload FROM companion_events ORDER BY ts DESC, created_at DESC LIMIT 1").fetchone()
        return self._event_from_row(row)

    def list_companion_events(self, limit=100):
        limit = max(1, min(int(limit or 100), 500))
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT id,ts,kind,treat,delta_energy,delta_bond,reason,task_id,goal_id,dedupe_key,source,payload FROM companion_events ORDER BY ts DESC, created_at DESC LIMIT ?", (limit,)).fetchall()
        events = []
        for row in rows:
            extra = row[11]
            if isinstance(extra, str):
                try: extra = json.loads(extra) if extra else {}
                except (TypeError, json.JSONDecodeError): extra = {}
            events.append({
                "id": row[0], "ts": row[1], "kind": row[2], "treat": row[3],
                "delta_energy": row[4], "delta_bond": row[5], "reason": row[6],
                "task_id": row[7], "goal_id": row[8], "dedupe_key": row[9],
                "source": row[10], "payload": extra if isinstance(extra, dict) else {},
            })
        return events

    def health_report(self):
        """Return a non-throwing, serializable data-health diagnostic report."""
        try:
            integrity = self.check_integrity()
            return {
                **integrity,
                "schema_version": self.schema_version(),
                "target_schema_version": SCHEMA_VERSION,
                "migrations": self.migration_history(),
                "issues": [],
            }
        except StorageCorruptionError as exc:
            return {
                "ok": False, "database": "corrupt", "attachments": [],
                "schema_version": None, "target_schema_version": SCHEMA_VERSION,
                "migrations": [], "issues": [str(exc)],
            }

    def status(self):
        integrity = self.check_integrity()
        with self._lock, self._connect() as db:
            counts = {table: db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0]
                      for table in ("goals","tasks","events","motivation_ledger")}
        return {"ok":integrity["ok"],"database":integrity["database"],"attachments":integrity["attachments"],"counts":counts}

    def list_backups(self):
        result = []
        for path in self.backups_dir.glob("*/*.db"):
            result.append({"path":str(path),"kind":path.parent.name,"created_at":datetime.fromtimestamp(path.stat().st_mtime).isoformat(),"size":path.stat().st_size})
        return sorted(result, key=lambda item:item["created_at"], reverse=True)

    def maybe_backup(self, interval=1800):
        if not self._auto_backup or not self.db_path.exists(): return None
        now = time.time()
        if now - self._last_backup < interval: return None
        result = self.create_backup("automatic"); self.maintain_backups(); self.purge_trash(); self._last_backup = now; return result

    def create_backup(self, kind="automatic", now=None):
        if kind not in {"automatic","daily","weekly","monthly","manual","pre-migration","pre-restore"}: raise ValueError("unknown backup kind")
        folder = self.backups_dir / kind; folder.mkdir(parents=True, exist_ok=True)
        target = folder / ((now or datetime.now()).strftime("%Y%m%d-%H%M%S-%f") + ".db")
        with self._lock, self._connect() as source, sqlite3.connect(str(target), factory=_ClosingConnection) as destination: source.backup(destination)
        self._verify_database(target, quick=False); self._prune_backups(); return str(target)

    def maintain_backups(self, now=None):
        now = now or datetime.now(); created = {}
        periods = {
            "daily": now.strftime("%Y%m%d"),
            "weekly": "{}-{:02d}".format(*now.isocalendar()[:2]),
            "monthly": now.strftime("%Y%m"),
        }
        for kind, period in periods.items():
            existing = sorted((self.backups_dir / kind).glob("*.db"), reverse=True)
            if kind == "weekly":
                current = any("{}-{:02d}".format(*datetime.strptime(path.stem[:8],"%Y%m%d").isocalendar()[:2]) == period for path in existing)
            else:
                current = any(path.stem.startswith(period) for path in existing)
            if not current: created[kind] = self.create_backup(kind, now)
        return created

    def _prune_backups(self):
        for kind, limit in {"automatic":48,"daily":14,"weekly":8,"monthly":12,"pre-migration":5,"pre-restore":10}.items():
            for old in sorted((self.backups_dir / kind).glob("*.db"), reverse=True)[limit:]: old.unlink(missing_ok=True)

    def restore_backup(self, backup_path, protect=True):
        source = Path(backup_path).resolve()
        if not source.is_file() or self.backups_dir.resolve() not in source.parents: raise ValueError("backup must be inside Task Verge backups")
        self._verify_database(source, quick=False)
        pre_restore = None
        if protect and self.db_path.exists():
            pre_restore = self.create_backup("pre-restore")
        fd, name = tempfile.mkstemp(suffix=".db", dir=self.root); os.close(fd); tmp = Path(name)
        replaced = False
        try:
            with sqlite3.connect(str(source), factory=_ClosingConnection) as backup, sqlite3.connect(str(tmp), factory=_ClosingConnection) as restored: backup.backup(restored)
            self._verify_database(tmp, quick=False)
            with self._lock:
                os.replace(tmp, self.db_path)
                replaced = True
            self._verify_database(self.db_path, quick=False)
            self._initialize()
            return pre_restore
        except Exception:
            if replaced and pre_restore:
                try: self.restore_backup(pre_restore, protect=False)
                except Exception: pass
            raise
        finally:
            tmp.unlink(missing_ok=True)

    def _verify_database(self, path, quick=True):
        try:
            with sqlite3.connect(str(path), factory=_ClosingConnection) as db:
                check = db.execute("PRAGMA {}".format("quick_check" if quick else "integrity_check")).fetchone()[0]
                foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall(); app_id = db.execute("PRAGMA application_id").fetchone()[0]
            if check != "ok" or foreign_keys or app_id != APPLICATION_ID: raise StorageCorruptionError("database integrity check failed")
        except sqlite3.DatabaseError as exc: raise StorageCorruptionError("database cannot be read: {}".format(path)) from exc

    def check_integrity(self):
        self._verify_database(self.db_path, quick=False); problems = []
        with self._lock, self._connect() as db: rows = db.execute("SELECT sha256,stored_path,trashed_at FROM attachments").fetchall()
        for digest, stored_path, trashed_at in rows:
            if trashed_at: continue
            path = Path(stored_path)
            if not path.is_file(): problems.append({"sha256":digest,"problem":"missing"})
            elif self._hash(path) != digest: problems.append({"sha256":digest,"problem":"hash_mismatch"})
        return {"ok":not problems,"database":"ok","attachments":problems}

    @staticmethod
    def _hash(path):
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
        return digest.hexdigest()

    def add_attachment(self, source, original_name=None):
        source = Path(source)
        if not source.is_file(): raise FileNotFoundError(source)
        digest = self._hash(source); folder = self.attachments_dir / digest[:2]; folder.mkdir(parents=True, exist_ok=True)
        target = folder / (digest + source.suffix.lower()[:16])
        if not target.exists():
            fd, name = tempfile.mkstemp(dir=folder); os.close(fd); tmp = Path(name)
            try: shutil.copy2(source, tmp); os.replace(tmp, target)
            finally: tmp.unlink(missing_ok=True)
        with self._lock, self._connect() as db:
            db.execute("""INSERT INTO attachments VALUES (?,?,?,?,?,NULL)
                ON CONFLICT(sha256) DO UPDATE SET stored_path=excluded.stored_path,
                original_name=excluded.original_name,size=excluded.size,trashed_at=NULL""",
                       (digest,str(target),original_name or source.name,target.stat().st_size,datetime.now().isoformat()))
        return str(target)

    def migrate_legacy_attachments(self, source_dir):
        source_dir = Path(source_dir)
        if not source_dir.is_dir(): return {}
        mapping = {str(path): self.add_attachment(path, path.name)
                   for path in source_dir.rglob("*") if path.is_file()}
        if not mapping: return {}

        def replace(value):
            if isinstance(value, str): return mapping.get(value, value)
            if isinstance(value, list): return [replace(item) for item in value]
            if isinstance(value, dict): return {key: replace(item) for key, item in value.items()}
            return value

        with self._lock, self._connect() as db:
            rows = db.execute("SELECT name,payload FROM documents").fetchall()
            for name, payload in rows:
                original = json.loads(payload); updated = replace(original)
                if updated != original:
                    db.execute("UPDATE documents SET payload=?,revision=revision+1,updated_at=? WHERE name=?",
                               (json.dumps(updated, ensure_ascii=False, separators=(",", ":")), datetime.now().isoformat(), name))
        return mapping

    def trash_attachment(self, stored_path):
        source = Path(stored_path).resolve()
        if self.attachments_dir.resolve() not in source.parents: raise ValueError("attachment is outside managed storage")
        target = self.trash_dir / (datetime.now().strftime("%Y%m%d-%H%M%S-%f-") + source.name); os.replace(source, target)
        with self._lock, self._connect() as db:
            db.execute("UPDATE attachments SET stored_path=?,trashed_at=? WHERE stored_path=?", (str(target),datetime.now().isoformat(),str(source)))
        return str(target)

    def purge_trash(self, days=30):
        cutoff = datetime.now() - timedelta(days=days); removed = 0
        with self._lock, self._connect() as db:
            for digest, path, timestamp in db.execute("SELECT sha256,stored_path,trashed_at FROM attachments WHERE trashed_at IS NOT NULL").fetchall():
                if datetime.fromisoformat(timestamp) <= cutoff:
                    Path(path).unlink(missing_ok=True); db.execute("DELETE FROM attachments WHERE sha256=?", (digest,)); removed += 1
        return removed

    def export_complete(self, target):
        target = Path(target); target.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(suffix=".db", dir=self.root); os.close(fd); snapshot = Path(name)
        try:
            with self._lock, self._connect() as source, sqlite3.connect(str(snapshot), factory=_ClosingConnection) as destination: source.backup(destination)
            manifest = {"format":"task-verge-backup","version":1,"created_at":datetime.now().isoformat(),"database_sha256":self._hash(snapshot)}
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(snapshot, "taskverge.db"); archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                for path in self.attachments_dir.rglob("*"):
                    if path.is_file(): archive.write(path, "attachments/" + path.relative_to(self.attachments_dir).as_posix())
        finally: snapshot.unlink(missing_ok=True)
        return str(target)

    def import_complete(self, package):
        package = Path(package)
        if not package.is_file(): raise FileNotFoundError(package)
        work = Path(tempfile.mkdtemp(prefix="taskverge-import-", dir=self.root))
        previous_attachments = self.trash_dir / ("pre-import-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        backup = None
        try:
            with zipfile.ZipFile(package) as archive:
                names = archive.namelist()
                if "taskverge.db" not in names or "manifest.json" not in names: raise StorageCorruptionError("incomplete backup package")
                for name in names:
                    path = Path(name)
                    if path.is_absolute() or ".." in path.parts: raise StorageCorruptionError("unsafe backup path")
                archive.extractall(work)
            imported_db = work / "taskverge.db"
            manifest = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("format") != "task-verge-backup" or manifest.get("database_sha256") != self._hash(imported_db):
                raise StorageCorruptionError("backup manifest check failed")
            self._verify_database(imported_db, quick=False)
            imported_attachments = work / "attachments"
            imported_attachments.mkdir(exist_ok=True)
            with sqlite3.connect(str(imported_db), factory=_ClosingConnection) as db:
                db.execute("PRAGMA foreign_keys=ON"); path_mapping = {}
                rows = db.execute("SELECT sha256,stored_path,trashed_at FROM attachments").fetchall()
                for digest, old_path, trashed_at in rows:
                    if trashed_at: continue
                    matches = list(imported_attachments.rglob(digest + "*"))
                    if len(matches) != 1 or self._hash(matches[0]) != digest:
                        raise StorageCorruptionError("backup attachment check failed: {}".format(digest))
                    new_path = str(self.attachments_dir / matches[0].relative_to(imported_attachments)); path_mapping[old_path] = new_path
                    db.execute("UPDATE attachments SET stored_path=? WHERE sha256=?", (new_path,digest))
                def replace(value):
                    if isinstance(value,str): return path_mapping.get(value,value)
                    if isinstance(value,list): return [replace(item) for item in value]
                    if isinstance(value,dict): return {key:replace(item) for key,item in value.items()}
                    return value
                documents = db.execute("SELECT name,payload FROM documents").fetchall()
                for name, payload in documents:
                    original=json.loads(payload); updated=replace(original)
                    if updated != original: db.execute("UPDATE documents SET payload=?,revision=revision+1,updated_at=? WHERE name=?",(self._json(updated),datetime.now().isoformat(),name))
                    if name=="task-config.json": self._project_state(db,updated,datetime.now().isoformat())
                    elif name=="fgtime.json": self._project_app_usage(db,updated)
            backup = self.create_backup("pre-restore")
            with self._lock:
                if self.attachments_dir.exists(): os.replace(self.attachments_dir, previous_attachments)
                os.replace(imported_attachments, self.attachments_dir)
                os.replace(imported_db, self.db_path)
            self._initialize()
            self.check_integrity()
        except Exception:
            if backup:
                try: self.restore_backup(backup, protect=False)
                except Exception: pass
            if previous_attachments.exists():
                try:
                    if self.attachments_dir.exists(): shutil.rmtree(self.attachments_dir)
                    os.replace(previous_attachments, self.attachments_dir)
                except OSError: pass
            raise
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return True

    def _log(self, message):
        try:
            with self.log_path.open("a", encoding="utf-8") as handle: handle.write("{} {}\n".format(datetime.now().isoformat(), message))
        except OSError: pass


class _CompanionTxn:
    """Companion reads/writes that stay on one open SQLite connection."""

    def __init__(self, store, db):
        self.store = store
        self.db = db

    def write(self, companion, event=None):
        return self.store._write_companion_on(self.db, companion, event)

    def write_companion(self, companion, event=None):
        return self.write(companion, event)

    def find_event(self, dedupe_key):
        return self.store.find_companion_event(dedupe_key, db=self.db)

    def find_companion_event(self, dedupe_key):
        return self.find_event(dedupe_key)

    def last_event(self):
        row = self.db.execute(
            "SELECT id,ts,kind,treat,delta_energy,delta_bond,reason,task_id,goal_id,dedupe_key,source,payload FROM companion_events ORDER BY ts DESC, created_at DESC LIMIT 1"
        ).fetchone()
        return self.store._event_from_row(row)

    def list_events(self, limit=40):
        limit = max(1, min(int(limit or 40), 500))
        rows = self.db.execute(
            "SELECT id,ts,kind,treat,delta_energy,delta_bond,reason,task_id,goal_id,dedupe_key,source,payload FROM companion_events ORDER BY ts DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self.store._event_from_row(row) for row in rows]

    def list_companion_events(self, limit=40):
        return self.list_events(limit)


def open_store(data_dir, log_path=None, confirm_recovery=None, auto_backup=True):
    try:
        return SqliteStore(data_dir, log_path, auto_backup=auto_backup)
    except StorageCorruptionError:
        backups = SqliteStore.find_valid_backups(data_dir)
        if not backups or not confirm_recovery or not confirm_recovery(backups[0]): raise
        SqliteStore.recover_from_backup(data_dir, backups[0])
        return SqliteStore(data_dir, log_path, auto_backup=auto_backup)
