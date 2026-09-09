import importlib.util
import os
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

from state_store import SqliteStore


def load_task_panel(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    name = "task_panel_persistence_{}".format(os.getpid())
    path = Path(__file__).parents[1] / "task-panel.pyw"
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(path)))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_archived_evidence_survives_cleanup_and_reload(monkeypatch, tmp_path):
    panel = load_task_panel(monkeypatch, tmp_path)
    kept_source = tmp_path / "kept.txt"
    orphan_source = tmp_path / "orphan.txt"
    kept_source.write_text("archived evidence", encoding="utf-8")
    orphan_source.write_text("unreferenced", encoding="utf-8")
    kept = panel.STORE.add_attachment(kept_source)
    orphan = panel.STORE.add_attachment(orphan_source)

    state = {"archives": [{"tasks": [{"evidence": [kept]}]}]}
    panel.sc(state)
    reloaded = panel.lc()

    assert os.path.isfile(kept)
    assert not os.path.isfile(orphan)
    assert reloaded["archives"][0]["tasks"][0]["evidence"] == [kept]


def test_shared_multi_goal_evidence_survives_archive_save_and_complete_import(monkeypatch, tmp_path):
    panel = load_task_panel(monkeypatch, tmp_path)
    source = tmp_path / "shared.txt"
    source.write_text("shared archived evidence", encoding="utf-8")
    kept = panel.STORE.add_attachment(source)
    state = {
        "goals": [{"id": "g1", "title": "one"}, {"id": "g2", "title": "two"}],
        "active_goal": 0,
        "tasks_by_goal": {"g1": [{"evidence": [kept]}], "g2": [{"evidence": [kept]}]},
        "archives": [{"goal_id": "g1", "tasks": [{"evidence": [kept]}]}],
    }
    panel.sc(state)
    package = panel.STORE.export_complete(tmp_path / "shared.tvbackup")

    target = SqliteStore(tmp_path / "target", auto_backup=False)
    target.import_complete(package)
    imported = target.load(str(tmp_path / "target" / "task-config.json"))
    refs = [
        imported["tasks_by_goal"]["g1"][0]["evidence"][0],
        imported["tasks_by_goal"]["g2"][0]["evidence"][0],
        imported["archives"][0]["tasks"][0]["evidence"][0],
    ]

    assert refs[0] == refs[1] == refs[2]
    assert refs[0].startswith(str(target.attachments_dir))
    assert os.path.isfile(refs[0])
