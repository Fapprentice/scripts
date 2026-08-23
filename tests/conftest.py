"""Shared fixtures for Task Verge tests."""
import os
import sys
import tempfile
import pytest

# Add the project root to sys.path so tests can import project modules
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture
def temp_dir():
    """A temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def sample_task():
    """A minimal normalized task dict for testing."""
    return {
        "id": "task_001",
        "goal_id": "0",
        "title": "完成列表练习题",
        "text": "完成列表练习题",
        "description": "编写 list_exercises.py",
        "type": "practice",
        "status": "pending",
        "estimated_minutes": 30,
        "required_apps": [],
        "allowed_apps": [],
        "blocked_apps": [],
        "expected_output": "一个Python文件 list_exercises.py",
        "acceptance": "代码可运行且输出正确结果",
        "milestone": "",
        "depends_on": [],
        "evidence": [],
        "app_reason": "",
        "app_confidence": 0,
        "acceptance_result": {},
        "difficulty": 2,
        "source": "manual",
        "locked": False,
        "created_at": "2026-07-11T00:00:00",
    }


@pytest.fixture
def sample_task_with_evidence(sample_task, temp_dir):
    """A task with a valid .py file as evidence."""
    py_path = os.path.join(temp_dir, "list_exercises.py")
    with open(py_path, "w", encoding="utf-8") as f:
        f.write("# A simple list exercise\n")
        f.write("fruits = ['apple', 'banana', 'cherry']\n")
        f.write("fruits.append('date')\n")
        f.write("print(f'Total fruits: {len(fruits)}')\n")
        f.write("for fruit in fruits:\n")
        f.write("    print(fruit)\n")

    sample_task["evidence"] = [py_path]
    return sample_task


@pytest.fixture
def sample_details_empty():
    """Empty evidence details."""
    return {"text": "", "files": []}


@pytest.fixture
def sample_details_with_file(temp_dir):
    """Evidence details with a valid .py file."""
    py_path = os.path.join(temp_dir, "list_exercises.py")
    with open(py_path, "w", encoding="utf-8") as f:
        f.write("print('hello world')\n")

    import subprocess
    r = subprocess.run(
        [sys.executable, "-m", "py_compile", py_path],
        capture_output=True, text=True, timeout=5,
    )

    return {
        "text": "完成了列表练习题",
        "files": [{
            "path": py_path,
            "exists": True,
            "content": open(py_path, encoding="utf-8", errors="replace").read(),
            "python_check": {"ok": r.returncode == 0, "output": (r.stderr or r.stdout or "").strip()},
            "docker_run": {"skipped": True, "output": "Docker not available"},
        }],
    }
