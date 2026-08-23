"""Tests for acceptance.py — AI acceptance rules-first engine."""
import os
import sys
import unittest

# Set feature flag before importing

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import acceptance


class TestAcceptanceRules(unittest.TestCase):
    """Test each deterministic rule in isolation."""

    def setUp(self):
        self.task = {
            "id": "task_001",
            "goal_id": "0",
            "title": "完成列表练习题",
            "evidence": [],
            "expected_output": "一个Python文件 list_exercises.py",
            "acceptance": "代码可运行且输出正确结果",
        }
        self.empty_details = {"text": "", "files": []}

    # ---- R1: has_evidence ----

    def test_r1_fails_with_empty_evidence(self):
        """Task with no evidence should fail R1."""
        result = acceptance._r1_has_evidence(self.task)
        self.assertFalse(result.pass_)
        self.assertIn("未提交", result.detail)

    def test_r1_passes_with_list_evidence(self):
        """Task with evidence list should pass R1."""
        self.task["evidence"] = ["path/to/file.py"]
        result = acceptance._r1_has_evidence(self.task)
        self.assertTrue(result.pass_)

    def test_r1_passes_with_string_evidence(self):
        """Task with string evidence should pass R1."""
        self.task["evidence"] = "completed the exercise"
        result = acceptance._r1_has_evidence(self.task)
        self.assertTrue(result.pass_)

    # ---- R2: files_exist ----

    def test_r2_passes_with_no_files(self):
        """No file references means R2 passes."""
        result = acceptance._r2_files_exist(self.task, self.empty_details)
        self.assertTrue(result.pass_)

    def test_r2_passes_with_existing_files(self):
        """All referenced files exist — should pass."""
        details = {"files": [{"path": __file__, "exists": True}]}
        result = acceptance._r2_files_exist(self.task, details)
        self.assertTrue(result.pass_)

    def test_r2_fails_with_missing_files(self):
        """Missing files should fail R2."""
        details = {"files": [{"path": "/nonexistent/file.py", "exists": False}]}
        result = acceptance._r2_files_exist(self.task, details)
        self.assertFalse(result.pass_)
        self.assertIn("文件不存在", result.detail)

    # ---- R3: py_compile ----

    def test_r3_passes_no_py_files(self):
        """No .py files means R3 passes."""
        result = acceptance._r3_py_compile(self.task, self.empty_details)
        self.assertTrue(result.pass_)

    def test_r3_passes_valid_py_file(self):
        """A valid .py file passes py_compile."""
        import tempfile, subprocess
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("print('hello')\n")
            fp = f.name
        try:
            r = subprocess.run(
                [sys.executable, "-m", "py_compile", fp],
                capture_output=True, text=True, timeout=5,
            )
            details = {"files": [{
                "path": fp, "exists": True,
                "python_check": {"ok": r.returncode == 0, "output": r.stderr or r.stdout or ""},
            }]}
            result = acceptance._r3_py_compile(self.task, details)
            self.assertTrue(result.pass_, f"Expected pass but got: {result.detail}")
        finally:
            os.unlink(fp)

    def test_r3_fails_invalid_py_file(self):
        """A .py file with syntax errors fails py_compile."""
        import tempfile, subprocess
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("this is not valid python {{{{{\n")
            fp = f.name
        try:
            r = subprocess.run(
                [sys.executable, "-m", "py_compile", fp],
                capture_output=True, text=True, timeout=5,
            )
            details = {"files": [{
                "path": fp, "exists": True,
                "python_check": {"ok": r.returncode == 0, "output": r.stderr or r.stdout or ""},
            }]}
            result = acceptance._r3_py_compile(self.task, details)
            self.assertFalse(result.pass_, "Expected fail but got pass")
        finally:
            os.unlink(fp)

    # ---- R5: output keywords ----

    def test_r5_passes_no_expected_output(self):
        """No expected output defined — R5 passes."""
        self.task["expected_output"] = ""
        result = acceptance._r5_output_keywords(self.task, self.empty_details)
        self.assertTrue(result.pass_)

    def test_r5_passes_keyword_match(self):
        """Evidence containing keywords from expected output passes."""
        self.task["expected_output"] = "一个Python文件 list_exercises.py"
        details = {"text": "我创建了 list_exercises.py 文件", "files": []}
        result = acceptance._r5_output_keywords(self.task, details)
        self.assertTrue(result.pass_)

    # ---- Full check_evidence pipeline ----

    def test_check_evidence_no_evidence(self):
        """Full pipeline: task with no evidence fails fast."""
        verdict = acceptance.check_evidence(self.task, self.empty_details)
        self.assertFalse(verdict.pass_)
        self.assertFalse(verdict.needs_llm)
        self.assertIn("R1_evidence", verdict.checks)

    def test_behavior_task_uses_light_confirmation(self):
        task = dict(self.task, type="behavior", verification_mode="none")
        verdict = acceptance.check_evidence(task, self.empty_details)
        self.assertTrue(verdict.pass_)
        self.assertFalse(verdict.needs_llm)

    def test_check_evidence_all_pass(self):
        """Full pipeline: valid evidence passes all checks."""
        import tempfile, subprocess
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("print('hello world')\n")
            fp = f.name
        try:
            r = subprocess.run(
                [sys.executable, "-m", "py_compile", fp],
                capture_output=True, text=True, timeout=5,
            )
            self.task["evidence"] = [fp]
            details = {
                "text": "完成了列表练习题，创建了 list_exercises.py",
                "files": [{
                    "path": fp, "exists": True,
                    "content": "print('hello world')",
                    "python_check": {"ok": r.returncode == 0, "output": ""},
                    "docker_run": {"skipped": True},
                }],
            }
            verdict = acceptance.check_evidence(self.task, details)
            # Should pass all deterministic checks (R5/R6 may still flag needs_llm)
            self.assertTrue(verdict.pass_)
            for check_id in ["R1_evidence", "R2_files_exist", "R3_py_compile", "R4_docker_run"]:
                self.assertTrue(
                    verdict.checks.get(check_id, {}).get("pass", False),
                    f"{check_id} should pass but got: {verdict.checks.get(check_id)}",
                )
        finally:
            os.unlink(fp)

    # ---- Verdict to result conversion ----

    def test_verdict_to_result_pass(self):
        """Pass verdict converts cleanly."""
        verdict = acceptance.AcceptanceVerdict(True, "All good", {"R1": {"pass": True, "detail": "ok"}}, False)
        ar = acceptance.verdict_to_acceptance_result(verdict)
        self.assertTrue(ar["pass"])
        self.assertTrue(ar["rules_first"])
        self.assertEqual(ar["decision"], "accepted")
        self.assertEqual(ar["confidence"], 1.0)

    def test_verdict_to_result_fail(self):
        """Fail verdict includes missing/next_steps."""
        verdict = acceptance.AcceptanceVerdict(
            False, "R1: no evidence",
            {"R1_evidence": {"pass": False, "detail": "未提交任何交付物"}},
            False,
        )
        ar = acceptance.verdict_to_acceptance_result(verdict)
        self.assertFalse(ar["pass"])
        self.assertEqual(ar["decision"], "rejected")
        self.assertTrue(len(ar["missing"]) > 0)
        self.assertTrue(len(ar["next_steps"]) > 0)

    def test_borderline_verdict_requires_review(self):
        verdict = acceptance.AcceptanceVerdict(
            True, "Needs interpretation",
            {"R1": {"pass": True, "detail": "ok"}, "R2": {"pass": False, "detail": "unclear"}},
            True,
        )
        ar = acceptance.verdict_to_acceptance_result(verdict)
        self.assertEqual(ar["decision"], "review")
        self.assertLess(ar["confidence"], 0.75)


if __name__ == "__main__":
    unittest.main()
