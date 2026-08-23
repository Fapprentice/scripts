import json

from state_store import JsonStore


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
