"""Tests for apprules.py — deterministic app recognition."""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import apprules


class TestPreclassifyApps:
    def test_known_apps_hit(self):
        classified, remaining = apprules.preclassify_apps([
            {"exe": "Obsidian.exe"}, {"exe": "Code.exe"},
            {"exe": "Chrome.exe"}, {"exe": "WeChat.exe"},
            {"exe": "UnknownApp.exe"},
        ])
        total_classified = sum(len(v) for v in classified.values())
        assert total_classified == 4
        assert len(remaining) == 1
        assert remaining[0]["exe"] == "UnknownApp.exe"

    def test_empty_input(self):
        classified, remaining = apprules.preclassify_apps([])
        assert classified == {}
        assert remaining == []

class TestSmartFilterTasks:
    def test_python_task(self):
        result = apprules.smart_filter_tasks([
            {"index": 0, "title": "完成 Python 基础练习题"},
        ])
        assert 0 in result
        assert "开发" in result[0]

    def test_writing_task(self):
        result = apprules.smart_filter_tasks([
            {"index": 1, "title": "写周报和会议记录"},
        ])
        assert 1 in result
        cats = result[1]
        assert any("文档写作" in c or "笔记" in c for c in cats)

    def test_unknown_task(self):
        result = apprules.smart_filter_tasks([
            {"index": 0, "title": "随便做点事"},
        ])
        assert 0 not in result


class TestFallbackApps:
    def test_ide_category(self):
        apps = apprules.fallback_apps_for_categories(
            ["开发/IDE", "学习办公/笔记与知识管理"],
            [{"exe": "Code.exe"}, {"exe": "Obsidian.exe"}, {"exe": "Pycharm64.exe"}],
        )
        assert "Code.exe" in apps
        assert "Obsidian.exe" in apps

    def test_empty_categories(self):
        apps = apprules.fallback_apps_for_categories(
            [], [{"exe": "Code.exe"}],
        )
        assert apps == []
