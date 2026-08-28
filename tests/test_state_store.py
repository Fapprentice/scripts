import json
import os
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from state_store import JsonStore, SqliteStore, StorageCorruptionError, open_store


def test_json_store_round_trip(tmp_path):
    path = tmp_path / "state.json"
    store = JsonStore(str(tmp_path / "errors.log"))
    store.save(str(path), {"ok": True})
    assert store.load(str(path)) == {"ok": True}
    assert store.load(str(tmp_path / "missing.json"), {"fallback": 1}) == {"fallback": 1}


def test_json_store_keeps_previous_file_on_bad_json(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{bad", encoding="utf-8")
    assert JsonStore().load(str(path), {"fallback": 1}) == {"fallback": 1}


def test_sqlite_store_migrates_legacy_json_once_and_preserves_source(tmp_path):
    legacy = tmp_path / "task-config.json"
    legacy.write_text(json.dumps({"goal": "英语四级", "state_revision": 7}), encoding="utf-8")
    store = SqliteStore(tmp_path)

    assert store.load(str(legacy))["goal"] == "英语四级"
    assert legacy.exists()
    assert (tmp_path / "legacy-json" / "task-config.json").exists()

    legacy.write_text(json.dumps({"goal": "不应再次导入"}), encoding="utf-8")
    assert store.load(str(legacy))["goal"] == "英语四级"


def test_sqlite_store_rejects_corrupt_legacy_json_without_creating_empty_state(tmp_path):
    legacy = tmp_path / "task-config.json"
    legacy.write_text("{bad", encoding="utf-8")
    store = SqliteStore(tmp_path)

    with pytest.raises(StorageCorruptionError):
        store.load(str(legacy), {"fallback": 1})
    assert store.load(str(tmp_path / "missing.json"), {"fallback": 1}) == {"fallback": 1}


def test_sqlite_store_round_trip_and_integrity(tmp_path):
    store = SqliteStore(tmp_path)
    path = tmp_path / "task-config.json"
    store.save(str(path), {"goal": "Python", "events": [{"kind": "saved"}]})

    assert store.load(str(path))["goal"] == "Python"
    assert store.check_integrity() == {"ok": True, "database": "ok", "attachments": []}


def test_sqlite_store_backup_restore_and_complete_export(tmp_path):
    store = SqliteStore(tmp_path)
    state_path = tmp_path / "task-config.json"
    store.save(str(state_path), {"goal": "原目标"})
    attachment = tmp_path / "source.txt"
    attachment.write_text("evidence", encoding="utf-8")
    stored = store.add_attachment(attachment, original_name="证据.txt")
    backup = store.create_backup("manual")

    store.save(str(state_path), {"goal": "错误修改"})
    pre_restore = store.restore_backup(backup)
    assert store.load(str(state_path))["goal"] == "原目标"
    assert os.path.isfile(pre_restore)
    assert os.path.basename(os.path.dirname(pre_restore)) == "pre-restore"
    store.restore_backup(pre_restore)
    assert store.load(str(state_path))["goal"] == "错误修改"

    export = store.export_complete(tmp_path / "exports" / "complete.tvbackup")
    with zipfile.ZipFile(export) as archive:
        names = set(archive.namelist())
        assert "taskverge.db" in names
        assert "manifest.json" in names
        assert any(name.startswith("attachments/") for name in names)
    assert os.path.isfile(stored)


def test_sqlite_store_deduplicates_and_trashes_attachments(tmp_path):
    store = SqliteStore(tmp_path)
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("same", encoding="utf-8")
    second.write_text("same", encoding="utf-8")

    path1 = store.add_attachment(first, original_name="a.txt")
    path2 = store.add_attachment(second, original_name="b.txt")
    assert path1 == path2
    assert store.check_integrity()["attachments"] == []

    trashed = store.trash_attachment(path1)
    assert os.path.exists(trashed)
    assert not os.path.exists(path1)
    restored = store.add_attachment(first)
    assert restored == path1
    assert store.check_integrity()["ok"] is True
    store.trash_attachment(restored)
    assert store.purge_trash(days=0) == 1


def test_sqlite_store_migrates_legacy_upload_paths_in_documents(tmp_path):
    uploads = tmp_path / "uploads" / "goal" / "task"
    uploads.mkdir(parents=True)
    old_file = uploads / "proof.txt"
    old_file.write_text("proof", encoding="utf-8")
    store = SqliteStore(tmp_path)
    state_path = tmp_path / "task-config.json"
    store.save(str(state_path), {"tasks": [{"evidence": [str(old_file)]}]}, backup=False)

    result = store.migrate_legacy_attachments(tmp_path / "uploads")
    migrated = store.load(str(state_path))["tasks"][0]["evidence"][0]

    assert result == {str(old_file): migrated}
    assert migrated.startswith(str(tmp_path / "attachments"))
    assert os.path.isfile(migrated)
    assert old_file.exists()


def test_sqlite_store_projects_core_state_in_same_save(tmp_path):
    store = SqliteStore(tmp_path)
    state = {
        "goals": [{"id": "g1", "title": "英语四级", "success_criteria": ["成绩>=425"], "constraints": ["每天60分钟"]}],
        "tasks_by_goal": {"g1": [{"id": "t1", "title": "词汇诊断", "acceptance": "正确率>=70%"}]},
        "events": [
            {"id": "e1", "kind": "task_created", "ts": "2026-08-24T10:00:00"},
            {"id": "e1", "kind": "task_updated", "ts": "2026-08-24T10:01:00"},
        ],
        "motivation": {"history": [{"id": "m1", "points": 2}]},
    }
    store.save(str(tmp_path / "task-config.json"), state, backup=False)

    status = store.status()
    assert status["ok"] is True
    assert status["counts"] == {"goals": 1, "tasks": 1, "events": 2, "motivation_ledger": 1}


def test_complete_export_can_restore_database_and_attachments(tmp_path):
    store = SqliteStore(tmp_path)
    state_path = tmp_path / "task-config.json"
    source = tmp_path / "proof.txt"
    source.write_text("original proof", encoding="utf-8")
    stored = store.add_attachment(source)
    store.save(str(state_path), {"goal": "可恢复"}, backup=False)
    package = store.export_complete(tmp_path / "complete.tvbackup")

    store.save(str(state_path), {"goal": "损坏后状态"}, backup=False)
    os.remove(stored)
    store.import_complete(package)

    assert store.load(str(state_path))["goal"] == "可恢复"
    assert store.check_integrity()["ok"] is True


def test_complete_export_is_portable_to_a_different_data_directory(tmp_path):
    source_store = SqliteStore(tmp_path / "source", auto_backup=False)
    proof = tmp_path / "proof.txt"; proof.write_text("portable", encoding="utf-8")
    old_path = source_store.add_attachment(proof)
    source_store.save(str(tmp_path / "source" / "task-config.json"), {"tasks": [{"evidence": [old_path]}]}, backup=False)
    package = source_store.export_complete(tmp_path / "portable.tvbackup")

    target_store = SqliteStore(tmp_path / "target", auto_backup=False)
    target_store.import_complete(package)
    new_path = target_store.load(str(tmp_path / "target" / "task-config.json"))["tasks"][0]["evidence"][0]

    assert new_path.startswith(str(tmp_path / "target" / "attachments"))
    assert os.path.isfile(new_path)


def test_backup_maintenance_creates_rolling_periods(tmp_path):
    store = SqliteStore(tmp_path, auto_backup=False)
    store.save(str(tmp_path / "task-config.json"), {"goal": "备份"}, backup=False)

    created = store.maintain_backups(datetime(2026, 8, 24, 10, 0, 0))

    assert set(created) == {"daily", "weekly", "monthly"}
    assert all(os.path.isfile(path) for path in created.values())


def test_corrupt_database_is_preserved_and_can_recover_from_valid_backup(tmp_path):
    store = SqliteStore(tmp_path, auto_backup=False)
    state_path = tmp_path / "task-config.json"
    store.save(str(state_path), {"goal": "安全副本"}, backup=False)
    backup = store.create_backup("manual")
    (tmp_path / "taskverge.db").write_bytes(b"not a database")

    with pytest.raises(StorageCorruptionError):
        SqliteStore(tmp_path, auto_backup=False)
    assert SqliteStore.find_valid_backups(tmp_path)[0] == backup

    corrupt_copy = SqliteStore.recover_from_backup(tmp_path, backup)
    recovered = SqliteStore(tmp_path, auto_backup=False)
    assert recovered.load(str(state_path))["goal"] == "安全副本"
    assert os.path.isfile(corrupt_copy)


def test_open_store_requires_confirmation_before_recovery(tmp_path):
    store = SqliteStore(tmp_path, auto_backup=False)
    store.save(str(tmp_path / "task-config.json"), {"goal": "确认恢复"}, backup=False)
    store.create_backup("manual")
    (tmp_path / "taskverge.db").write_bytes(b"broken")

    with pytest.raises(StorageCorruptionError):
        open_store(tmp_path, confirm_recovery=lambda _: False, auto_backup=False)
    recovered = open_store(tmp_path, confirm_recovery=lambda _: True, auto_backup=False)
    assert recovered.load(str(tmp_path / "task-config.json"))["goal"] == "确认恢复"


def test_failed_projection_rolls_back_the_whole_state_save(tmp_path):
    store = SqliteStore(tmp_path, auto_backup=False)
    path = tmp_path / "task-config.json"
    store.save(str(path), {"goal": "原状态", "goals": [{"id": "g1", "title": "原目标"}]}, backup=False)

    with pytest.raises(sqlite3.IntegrityError):
        store.save(str(path), {"goal": "不完整状态", "goals": [{"id": "g1"}, {"id": "g1"}]}, backup=False)

    assert store.load(str(path))["goal"] == "原状态"
    assert store.status()["counts"]["goals"] == 1

def test_schema_metadata_records_bootstrap_version_and_migration_history(tmp_path):
    store = SqliteStore(tmp_path, auto_backup=False)

    assert store.schema_version() == 1
    assert store.migration_history() == [{
        "from_version": 0, "to_version": 1, "name": "initial_schema",
    }]


def test_upgrade_creates_pre_migration_backup_before_recording_upgrade(tmp_path):
    store = SqliteStore(tmp_path, auto_backup=False)
    with sqlite3.connect(tmp_path / "taskverge.db") as database:
        database.execute("PRAGMA user_version=0")
        database.execute("DELETE FROM schema_migrations")

    upgraded = SqliteStore(tmp_path, auto_backup=False)

    assert upgraded.schema_version() == 1
    assert upgraded.migration_history() == [{
        "from_version": 0, "to_version": 1, "name": "initial_schema",
    }]
    assert len(list((tmp_path / "backups" / "pre-migration").glob("*.db"))) == 1


def test_health_report_exposes_schema_and_attachment_integrity(tmp_path):
    store = SqliteStore(tmp_path, auto_backup=False)
    source = tmp_path / "proof.txt"
    source.write_text("healthy", encoding="utf-8")
    stored = store.add_attachment(source)
    os.remove(stored)

    report = store.health_report()

    assert report["ok"] is False
    assert report["schema_version"] == 1
    assert report["target_schema_version"] == 1
    assert report["attachments"] == [{"sha256": store._hash(source), "problem": "missing"}]


def test_restore_keeps_original_database_when_replace_fails(tmp_path, monkeypatch):
    store = SqliteStore(tmp_path, auto_backup=False)
    state_path = tmp_path / "task-config.json"
    store.save(str(state_path), {"goal": "当前数据"}, backup=False)
    backup = store.create_backup("manual")
    store.save(str(state_path), {"goal": "未恢复前"}, backup=False)

    def fail_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        store.restore_backup(backup)
    assert store.load(str(state_path))["goal"] == "未恢复前"
    assert list((tmp_path / "backups" / "pre-restore").glob("*.db"))


def test_corrupt_backup_does_not_overwrite_current_database(tmp_path):
    store = SqliteStore(tmp_path, auto_backup=False)
    state_path = tmp_path / "task-config.json"
    store.save(str(state_path), {"goal": "当前完好"}, backup=False)
    backup = Path(store.create_backup("manual"))
    backup.write_bytes(b"not sqlite")
    with pytest.raises(StorageCorruptionError):
        store.restore_backup(backup)
    assert store.load(str(state_path))["goal"] == "当前完好"


def test_health_report_returns_failure_details_for_unreadable_database(tmp_path):
    store = SqliteStore(tmp_path, auto_backup=False)
    (tmp_path / "taskverge.db").write_bytes(b"not sqlite")

    report = store.health_report()

    assert report["ok"] is False
    assert report["database"] == "corrupt"
    assert "database cannot be read" in report["issues"][0]
