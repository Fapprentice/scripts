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

    assert store.schema_version() == 3
    assert store.migration_history() == [
        {"from_version": 0, "to_version": 1, "name": "initial_schema"},
        {"from_version": 1, "to_version": 2, "name": "companion_growth"},
        {"from_version": 2, "to_version": 3, "name": "skill_prerequisite_kind"},
    ]


def test_upgrade_creates_pre_migration_backup_before_recording_upgrade(tmp_path):
    store = SqliteStore(tmp_path, auto_backup=False)
    with sqlite3.connect(tmp_path / "taskverge.db") as database:
        database.execute("PRAGMA user_version=0")
        database.execute("DELETE FROM schema_migrations")

    upgraded = SqliteStore(tmp_path, auto_backup=False)

    assert upgraded.schema_version() == 3
    assert upgraded.migration_history() == [
        {"from_version": 0, "to_version": 1, "name": "initial_schema"},
        {"from_version": 1, "to_version": 2, "name": "companion_growth"},
        {"from_version": 2, "to_version": 3, "name": "skill_prerequisite_kind"},
    ]
    assert len(list((tmp_path / "backups" / "pre-migration").glob("*.db"))) == 1


def test_health_report_exposes_schema_and_attachment_integrity(tmp_path):
    store = SqliteStore(tmp_path, auto_backup=False)
    source = tmp_path / "proof.txt"
    source.write_text("healthy", encoding="utf-8")
    stored = store.add_attachment(source)
    os.remove(stored)

    report = store.health_report()

    assert report["ok"] is False
    assert report["schema_version"] == 3
    assert report["target_schema_version"] == 3
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


def test_v1_upgrade_creates_pre_migration_backup_and_default_companion(tmp_path):
    store = SqliteStore(tmp_path, auto_backup=False)
    store.save(
        str(tmp_path / "task-config.json"),
        {
            "goal": "英语四级",
            "goals": [{"id": "g1", "title": "英语四级", "success_criteria": ["成绩>=425"]}],
            "tasks_by_goal": {"g1": [{"id": "t1", "title": "词汇诊断", "acceptance": "正确率>=70%"}]},
        },
        backup=False,
    )
    with sqlite3.connect(tmp_path / "taskverge.db") as database:
        database.execute("PRAGMA user_version=1")
        database.execute("DELETE FROM schema_migrations WHERE to_version>=2")
        database.execute("DROP TABLE IF EXISTS companion_events")
        database.execute("DROP TABLE IF EXISTS companions")
        database.commit()
        tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "companions" not in tables
        task_count = database.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        goal_count = database.execute("SELECT COUNT(*) FROM goals").fetchone()[0]

    upgraded = SqliteStore(tmp_path, auto_backup=False)
    companion = upgraded.load_companion()
    state = upgraded.load(str(tmp_path / "task-config.json"))

    assert upgraded.schema_version() == 3
    assert any(item["name"] == "companion_growth" for item in upgraded.migration_history())
    assert companion["id"] == "dafeiyu"
    assert companion["name"] == "大肥鱼"
    assert companion["energy"] == 70 and companion["bond"] == 20
    assert companion["poke_used"] == 0 and companion["feed_used"] == 0 and companion["talk_used"] == 0
    assert state["goal"] == "英语四级"
    assert state["goals"][0]["id"] == "g1"
    assert state["tasks_by_goal"]["g1"][0]["id"] == "t1"
    with sqlite3.connect(tmp_path / "taskverge.db") as database:
        assert database.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == task_count == 1
        assert database.execute("SELECT COUNT(*) FROM goals").fetchone()[0] == goal_count == 1
        assert database.execute("SELECT COUNT(*) FROM companions").fetchone()[0] == 1
        assert database.execute("SELECT COUNT(*) FROM companion_events").fetchone()[0] == 0
    assert len(list((tmp_path / "backups" / "pre-migration").glob("*.db"))) >= 1


def test_skill_prerequisites_project_kind_and_rationale(tmp_path):
    store = SqliteStore(tmp_path, auto_backup=False)
    store.save(str(tmp_path / "task-config.json"), {
        "goal": "英语四级",
        "goals": [{"id": "g1", "title": "英语四级"}],
        "user_models_by_goal": {"g1": {"skills": {
            "cet4.vocab.high_freq": {"prerequisites": []},
            "cet4.vocab.collocation": {
                "prerequisites": ["cet4.vocab.high_freq"],
                "prerequisite_meta": {"cet4.vocab.high_freq": {"kind": "hard", "rationale": "没有词义就无法判断搭配"}},
            },
        }}},
    }, backup=False)
    with sqlite3.connect(tmp_path / "taskverge.db") as database:
        row = database.execute(
            "SELECT kind, rationale FROM skill_prerequisites").fetchone()
    assert row[0] == "hard"
    assert "词义" in row[1]


def test_companion_survives_projection_and_is_json_snapshot_only(tmp_path):
    store = SqliteStore(tmp_path, auto_backup=False)
    store.write_companion({"energy": 76, "bond": 23, "day": "2026-04-08"}, {
        "id": "evt1", "ts": "2026-04-08T10:00:00", "kind": "poke",
        "delta_energy": 0, "delta_bond": 1, "reason": "戳了一下，默契 +1",
        "dedupe_key": "poke-test",
    })
    store.save(str(tmp_path / "task-config.json"), {"goal": "仍在", "goals": [{"id": "g1", "title": "仍在"}]}, backup=False)

    companion = store.load_companion()
    events = store.list_companion_events()
    snapshot = store.load(str(tmp_path / "companion.json"), {})
    assert companion["energy"] == 76 and companion["bond"] == 23
    assert events[0]["kind"] == "poke"
    assert snapshot["companion"]["energy"] == 76
    store.write_companion({"energy": 80, "bond": 24, "day": "2026-04-08"})
    assert store.load_companion()["energy"] == 80
    snapshot_after = store.load(str(tmp_path / "companion.json"), {})
    assert snapshot_after["companion"]["energy"] == 80
    assert snapshot_after["companion"]["bond"] == 24


def test_companion_survives_restore_backup_and_complete_import(tmp_path):
    store = SqliteStore(tmp_path, auto_backup=False)
    state_path = tmp_path / "task-config.json"
    store.save(str(state_path), {"goal": "可恢复陪伴", "goals": [{"id": "g1", "title": "可恢复陪伴"}]}, backup=False)
    store.write_companion({"energy": 76, "bond": 23, "day": "2026-04-08", "poke_used": 2}, {
        "id": "evt-poke", "ts": "2026-04-08T10:00:00", "kind": "poke",
        "delta_energy": 0, "delta_bond": 1, "reason": "戳了一下，默契 +1",
        "dedupe_key": "poke-restore",
    })
    backup = store.create_backup("manual")
    package = store.export_complete(tmp_path / "exports" / "with-companion.tvbackup")

    store.write_companion({"energy": 11, "bond": 5, "day": "2026-04-09"})
    store.save(str(state_path), {"goal": "错误修改"}, backup=False)
    assert store.load_companion()["energy"] == 11

    store.restore_backup(backup)
    restored = store.load_companion()
    assert restored["energy"] == 76
    assert restored["bond"] == 23
    assert restored["poke_used"] == 2
    events = store.list_companion_events()
    assert [item["id"] for item in events] == ["evt-poke"]
    assert events[0]["delta_bond"] == 1
    assert store.load(str(state_path))["goal"] == "可恢复陪伴"

    store.write_companion({"energy": 3, "bond": 1, "day": "2026-04-10"})
    store.save(str(state_path), {"goal": "导入前损坏"}, backup=False)
    store.import_complete(package)
    imported = store.load_companion()
    assert imported["energy"] == 76
    assert imported["bond"] == 23
    imported_events = store.list_companion_events()
    assert [item["kind"] for item in imported_events] == ["poke"]
    assert store.find_companion_event("poke-restore")["id"] == "evt-poke"
    assert store.load(str(state_path))["goal"] == "可恢复陪伴"


def test_complete_import_carries_companion_to_a_different_data_directory(tmp_path):
    source = SqliteStore(tmp_path / "source", auto_backup=False)
    source.write_companion({"energy": 88, "bond": 41, "day": "2026-04-08"}, {
        "id": "evt-feed", "ts": "2026-04-08T11:00:00", "kind": "feed", "treat": "小鱼干",
        "delta_energy": 8, "delta_bond": 2, "reason": "喂了小鱼干，精力 +8，默契 +2",
        "dedupe_key": "feed-portable",
    })
    source.save(str(tmp_path / "source" / "task-config.json"), {"goal": "便携陪伴"}, backup=False)
    package = source.export_complete(tmp_path / "portable-companion.tvbackup")

    target = SqliteStore(tmp_path / "target", auto_backup=False)
    assert target.load_companion()["energy"] == 70
    target.import_complete(package)
    companion = target.load_companion()
    assert companion["energy"] == 88
    assert companion["bond"] == 41
    events = target.list_companion_events()
    assert len(events) == 1
    assert events[0]["kind"] == "feed"
    assert events[0]["treat"] == "小鱼干"
    assert target.load(str(tmp_path / "target" / "task-config.json"))["goal"] == "便携陪伴"


def test_companion_event_dedupe_key_is_unique(tmp_path):
    store = SqliteStore(tmp_path, auto_backup=False)
    event = {
        "id": "evt-once", "ts": "2026-04-08T10:00:00", "kind": "accepted",
        "delta_energy": 6, "delta_bond": 8, "reason": "验收通过，精力 +6，默契 +8",
        "dedupe_key": "accepted:run-1",
    }
    store.write_companion({"energy": 76, "bond": 28, "day": "2026-04-08"}, event)
    with pytest.raises(sqlite3.IntegrityError):
        store.write_companion({"energy": 82, "bond": 36, "day": "2026-04-08"}, {
            **event, "id": "evt-twice",
        })
    companion = store.load_companion()
    assert companion["energy"] == 76
    assert companion["bond"] == 28
    assert len(store.list_companion_events()) == 1
