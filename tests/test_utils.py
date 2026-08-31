"""Tests for utils.py — pure utility functions."""
import os
import sys
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import utils


def test_task_time_uses_fractional_seconds_as_single_source():
    task = utils.normalize_task({"title": "x", "actual_seconds": 7.75, "actual_minutes": 99})
    assert task["actual_seconds"] == 7.75
    assert "actual_minutes" not in task
    assert utils.task_actual_minutes(task) == 7.75 / 60


def test_task_execution_materials_survive_normalization():
    task = utils.normalize_task({"title": "词义匹配", "materials": [{"prompt": "abandon", "options": ["放弃", "获得"]}],
                                 "interaction": {"type": "choice"}, "response": {"0": "放弃"}})
    assert task["materials"][0]["options"] == ["放弃", "获得"]
    assert task["interaction"]["type"] == "choice"
    assert task["response"] == {"0": "放弃"}


def test_task_traceability_survives_normalization():
    task = utils.normalize_task({"title": "可追溯任务", "criterion_ids": ["criterion-1"],
                                 "answer_key": [{"id": "key-1", "material_ids": ["material-1"], "answer": "A"}]})
    assert task["criterion_ids"] == ["criterion-1"]
    assert task["answer_key"][0]["material_ids"] == ["material-1"]


class TestTaskText:
    def test_normal_string(self):
        assert utils.task_text("hello") == "hello"

    def test_dict_extraction(self):
        assert utils.task_text({"text": "world"}) == "world"

    def test_sentinel_filtering(self):
        for v in ("none", "null", "nil", "undefined", "n/a", "无", "暂无", "不需要"):
            assert utils.task_text(v) == ""

    def test_none_returns_empty(self):
        assert utils.task_text(None) == ""

    def test_focus_session_fields_survive_normalization(self):
        task = utils.normalize_task({"title": "阅读", "status": "partial", "type": "behavior", "continuation_note": "读到第 5 页", "actual_seconds": 423})
        assert task["status"] == "partial"
        assert task["verification_mode"] == "light"
        assert task["continuation_note"] == "读到第 5 页"
        assert task["actual_seconds"] == 423


class TestValueText:
    def test_normal_string(self):
        assert utils.value_text("x") == "x"

    def test_dict_returns_empty(self):
        assert utils.value_text({"x": 1}) == ""

    def test_list_returns_empty(self):
        assert utils.value_text([1, 2]) == ""


class TestNewId:
    def test_generates_valid_id(self):
        id_ = utils.new_id()
        assert len(id_) > 10
        assert id_.startswith("task_")

    def test_custom_prefix(self):
        id_ = utils.new_id("gen")
        assert id_.startswith("gen_")


class TestAsList:
    def test_string_wrapped(self):
        assert utils.as_list("a") == ["a"]

    def test_list_preserved(self):
        assert utils.as_list(["a", "b"]) == ["a", "b"]

    def test_none_returns_empty(self):
        assert utils.as_list(None) == []


class TestTaskDone:
    def test_dict_done_key(self):
        assert utils.task_done({"done": True}) is True

    def test_dict_status_done(self):
        assert utils.task_done({"status": "done"}) is True

    def test_dict_not_done(self):
        assert utils.task_done({"status": "pending"}) is False

    def test_flag_override(self):
        assert utils.task_done("something", True) is True
        assert utils.task_done("something", False) is False


class TestAppConfidence:
    def test_clamped_range(self):
        assert utils.app_confidence(0.5) == 0.5
        assert utils.app_confidence(2.0) == 1.0
        assert utils.app_confidence(-0.5) == 0.0

    def test_none_returns_zero(self):
        assert utils.app_confidence(None) == 0


class TestTimeHelpers:
    def test_min_of_parsing(self):
        assert utils.min_of("09:30") == 570

    def test_hhmm_formatting(self):
        assert utils.hhmm(570) == "09:30"

    def test_roundtrip(self):
        for hhmm_val in ("00:00", "09:00", "14:30", "23:59"):
            assert utils.hhmm(utils.min_of(hhmm_val)) == hhmm_val

    def test_today_format(self):
        assert utils.today() == date.today().isoformat()


class TestShq:
    def test_simple(self):
        assert "'test'" in utils.shq("test")


class TestEj:
    def test_direct_json(self):
        result = utils.ej('{"a": 1}')
        assert result == {"a": 1}

    def test_markdown_wrapped(self):
        result = utils.ej('```json\n{"b": 2}\n```')
        assert result == {"b": 2}

    def test_invalid_raises(self):
        try:
            utils.ej("not json at all")
            assert False, "Should have raised"
        except ValueError:
            pass


class TestNormalizeTask:
    def test_basic_normalization(self):
        nt = utils.normalize_task({"text": "Hello"})
        assert nt["title"] == "Hello"
        assert nt["text"] == "Hello"
        assert nt["status"] == "pending"
        assert nt["estimated_minutes"] == 30

    def test_custom_minutes(self):
        nt = utils.normalize_task({"text": "Task", "estimated_minutes": 60})
        assert nt["estimated_minutes"] == 60

    def test_clamps_out_of_range(self):
        nt = utils.normalize_task({"text": "X", "estimated_minutes": 500})
        assert nt["estimated_minutes"] == 180

    def test_legacy_string_input(self):
        nt = utils.normalize_task("simple task")
        assert nt["title"] == "simple task"
        assert nt["source"] == "legacy"

    def test_learning_fields_survive_normalization(self):
        nt = utils.normalize_task({"text": "Recall loops", "skill_id": "python.loops",
                                   "prerequisites": ["python.basics"], "learning_task_type": "recall",
                                   "recall_rating": "Hard", "hint_ladder": ["方向", "步骤"],
                                   "teach_back_prompt": "解释方法", "independent_check": "独立复现",
                                   "transfer_prompt": "换题练习"})
        assert nt["skill_id"] == "python.loops"
        assert nt["prerequisites"] == ["python.basics"]
        assert nt["learning_task_type"] == "recall"
        assert nt["recall_rating"] == "hard"
        assert nt["hint_ladder"] == ["方向", "步骤"]
        assert nt["teach_back_prompt"] == "解释方法"
        assert nt["independent_check"] == "独立复现"
        assert nt["transfer_prompt"] == "换题练习"


class TestNormalizeTasks:
    def test_batch_normalization(self):
        result = utils.normalize_tasks(
            [{"text": "A", "done": True}, {"text": "B"}],
            goal_id="0", flags=[True, False]
        )
        assert len(result) == 2
        assert result[0]["status"] == "done"
        assert result[1]["status"] == "pending"

    def test_filters_empty(self):
        result = utils.normalize_tasks([{"text": ""}, {"text": "A"}])
        assert len(result) == 1


class TestTaskItems:
    def test_inline_done_fields(self):
        items = utils.task_items(
            [{"text": "A", "done": True}, {"text": "B"}],
            [True, False]
        )
        assert items[0]["done"] is True
        assert items[1]["done"] is False
        assert items[0]["text"] == "A"
        assert items[1]["text"] == "B"
