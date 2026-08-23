"""Tests for applog.py — log rotation and sanitization."""
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import applog


class TestSanitize:
    def test_path_scrubbing(self):
        raw = r"C:\Users\JohnDoe\Documents\file.txt"
        result = applog.sanitize(raw)
        assert "JohnDoe" not in result
        assert "C:\\Users\\***" in result

    def test_key_scrubbing(self):
        raw = "Log: DEEPSEEK=sk-test-api-key-12345 found"
        result = applog.sanitize(raw)
        assert "sk-test" not in result
        assert "<redacted>" in result

    def test_truncation(self):
        long_msg = "X" * 5000
        result = applog.sanitize(long_msg)
        assert len(result) <= 4100  # 4000 + "...<truncated>"


class TestSetupLogging:
    def test_creates_log_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            applog.setup_logging(tmp)
            applog.boot("test boot message")
            applog.watchdog("test watchdog message")

            # Close handlers before checking
            for logger in [applog._boot_logger, applog._watchdog_logger]:
                if logger:
                    for h in list(logger.handlers):
                        h.close()
                        logger.removeHandler(h)

            boot_path = os.path.join(tmp, "boot.log")
            wd_path = os.path.join(tmp, "watchdog.log")
            assert os.path.exists(boot_path)
            assert os.path.exists(wd_path)

            with open(boot_path, encoding="utf-8") as f:
                content = f.read()
                assert "test boot message" in content

            with open(wd_path, encoding="utf-8") as f:
                content = f.read()
                assert "test watchdog message" in content

    def test_disabled_feature(self):
        old = os.environ.get("TASKVERGE_LOG_ROTATE")
        os.environ["TASKVERGE_LOG_ROTATE"] = "0"
        try:
            import importlib
            importlib.reload(applog)
            assert applog.FEATURE_LOG_ROTATE is False
        finally:
            if old is not None:
                os.environ["TASKVERGE_LOG_ROTATE"] = old
            else:
                del os.environ["TASKVERGE_LOG_ROTATE"]
            importlib.reload(applog)
