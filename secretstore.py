#!/usr/bin/env python3
"""Windows DPAPI secret store — zero external deps, stdlib + ctypes only.

Encrypts the DeepSeek API key (or other small secrets) using Windows
Data Protection API (CryptProtectData / CryptUnprotectData).

The encrypted blob is per-user + per-machine — copying the .key file
to another machine or user account renders it unreadable.

  save_key(key)  → writes encrypted blob to task-verge.key
  load_key()     → returns decrypted key string, or None

Activate via env: TASKVERGE_DPAPI=1 (default: on)
"""

import ctypes
import os
from ctypes import wintypes

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------
FEATURE_DPAPI = os.environ.get("TASKVERGE_DPAPI", "1") == "1"

# ---------------------------------------------------------------------------
# DPAPI constants
# ---------------------------------------------------------------------------
CRYPTPROTECT_UI_FORBIDDEN = 0x1

# ---------------------------------------------------------------------------
# Windows API bindings
# ---------------------------------------------------------------------------
class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


_crypt32 = ctypes.windll.crypt32
_crypt32.CryptProtectData.restype = wintypes.BOOL
_crypt32.CryptProtectData.argtypes = [
    ctypes.POINTER(_DATA_BLOB),  # pDataIn
    wintypes.LPCWSTR,            # szDataDescr
    ctypes.POINTER(_DATA_BLOB),  # pOptionalEntropy
    ctypes.c_void_p,             # pvReserved
    ctypes.c_void_p,             # pPromptStruct
    wintypes.DWORD,              # dwFlags
    ctypes.POINTER(_DATA_BLOB),  # pDataOut
]

_crypt32.CryptUnprotectData.restype = wintypes.BOOL
_crypt32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(_DATA_BLOB),  # pDataIn
    ctypes.POINTER(wintypes.LPWSTR),  # ppszDataDescr
    ctypes.POINTER(_DATA_BLOB),  # pOptionalEntropy
    ctypes.c_void_p,             # pvReserved
    ctypes.c_void_p,             # pPromptStruct
    wintypes.DWORD,              # dwFlags
    ctypes.POINTER(_DATA_BLOB),  # pDataOut
]

_kernel32 = ctypes.windll.kernel32
_kernel32.LocalFree.restype = wintypes.HLOCAL
_kernel32.LocalFree.argtypes = [wintypes.HLOCAL]


def _free_blob(blob):
    if blob.pbData:
        _kernel32.LocalFree(blob.pbData)
    blob.pbData = None
    blob.cbData = 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def protect(plaintext_bytes):
    """Encrypt bytes using DPAPI. Returns ciphertext bytes or None."""
    if not FEATURE_DPAPI:
        return plaintext_bytes

    in_blob = _DATA_BLOB()
    out_blob = _DATA_BLOB()

    buf = ctypes.create_string_buffer(plaintext_bytes, len(plaintext_bytes))
    in_blob.cbData = len(plaintext_bytes)
    in_blob.pbData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))

    try:
        ok = _crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            "Task Verge API Key",
            None, None, None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            return None
        result = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return result
    except Exception:
        return None
    finally:
        _free_blob(out_blob)


def unprotect(ciphertext_bytes):
    """Decrypt bytes using DPAPI. Returns plaintext bytes or None."""
    if not FEATURE_DPAPI:
        return ciphertext_bytes

    in_blob = _DATA_BLOB()
    out_blob = _DATA_BLOB()

    buf = ctypes.create_string_buffer(ciphertext_bytes, len(ciphertext_bytes))
    in_blob.cbData = len(ciphertext_bytes)
    in_blob.pbData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))

    try:
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None, None, None, None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            return None
        result = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return result
    except Exception:
        return None
    finally:
        _free_blob(out_blob)


# ---------------------------------------------------------------------------
# Key file I/O
# ---------------------------------------------------------------------------

def _key_file_path():
    """Returns the encrypted key path in the per-user data directory."""
    base = os.environ.get("TASKVERGE_DATA_DIR") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "TaskVerge")
    if not base: base = os.getcwd()
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "task-verge.key")


def save_key(key_str):
    """Encrypt and persist the API key. Returns True on success."""
    if not key_str or not key_str.strip():
        # Unset the key — remove the encrypted file
        try:
            os.remove(_key_file_path())
        except OSError:
            pass
        return True

    encrypted = protect(key_str.strip().encode("utf-8"))
    if encrypted is None:
        return False

    try:
        with open(_key_file_path(), "wb") as f:
            f.write(encrypted)
        return True
    except Exception:
        return False


def load_key():
    """Load and decrypt the API key. Returns str or None."""
    if not FEATURE_DPAPI:
        return None

    path = _key_file_path()
    if not os.path.exists(path):
        return None

    try:
        with open(path, "rb") as f:
            ciphertext = f.read()
    except Exception:
        return None

    if not ciphertext:
        return None

    plaintext = unprotect(ciphertext)
    if plaintext is None:
        return None

    try:
        return plaintext.decode("utf-8").strip()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Self-test (run with: python secretstore.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    test_key = "test-deepseek-key-1234567890"
    print(f"Original:  {test_key}")
    print(f"DPAPI on:  {FEATURE_DPAPI}")

    ok = save_key(test_key)
    print(f"Save OK:   {ok}")

    loaded = load_key()
    print(f"Load OK:   {loaded is not None}")
    print(f"Match:     {test_key == loaded}")

    # Show the ciphertext is binary
    if os.path.exists(_key_file_path()):
        size = os.path.getsize(_key_file_path())
        print(f"Key file:  {_key_file_path()} ({size} bytes)")
        with open(_key_file_path(), "rb") as f:
            preview = f.read()[:32]
        print(f"Preview:   {preview.hex()[:60]}...")

    # Cleanup
    try:
        os.remove(_key_file_path())
        print("Cleaned up.")
    except OSError:
        pass
