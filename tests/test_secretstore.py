"""Tests for secretstore.py — DPAPI encryption."""
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

_KEY_DIR = tempfile.TemporaryDirectory()
_OLD_KEY_DIR = os.environ.get("TASKVERGE_DATA_DIR")
os.environ["TASKVERGE_DATA_DIR"] = _KEY_DIR.name
import secretstore


class TestSecretStore:
    def test_encrypt_decrypt_roundtrip(self):
        original = "test-deepseek-key-1234567890"
        assert secretstore.save_key(original) is True
        loaded = secretstore.load_key()
        assert loaded == original

    def test_empty_key_removes_file(self):
        secretstore.save_key("")
        assert secretstore.load_key() is None

    def test_key_file_path(self):
        path = secretstore._key_file_path()
        assert path.endswith("task-verge.key")

    @classmethod
    def teardown_class(cls):
        # Cleanup test key file
        try:
            os.remove(secretstore._key_file_path())
        except OSError:
            pass
        _KEY_DIR.cleanup()
        if _OLD_KEY_DIR is None: os.environ.pop("TASKVERGE_DATA_DIR",None)
        else: os.environ["TASKVERGE_DATA_DIR"]=_OLD_KEY_DIR
