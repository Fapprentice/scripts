#!/usr/bin/env python3
"""Task Verge logging — RotatingFileHandler + sanitization.  Stdlib only.

Replaces the raw file-append logging in _bl() and _lg() with Python's
logging framework, providing:

  - Size-based log rotation (5 MB × 3 files each for boot + watchdog)
  - Automatic sanitization of sensitive paths in log messages
  - Timestamped, level-aware output

Activate via env: TASKVERGE_LOG_ROTATE=1 (default: on)

To opt out and return to raw file logging: TASKVERGE_LOG_ROTATE=0
"""

import logging
import logging.handlers
import os
import re

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------
FEATURE_LOG_ROTATE = os.environ.get("TASKVERGE_LOG_ROTATE", "1") == "1"

# ---------------------------------------------------------------------------
# Loggers
# ---------------------------------------------------------------------------
_boot_logger = None
_watchdog_logger = None
_initialized = False

# ---------------------------------------------------------------------------
# Sanitization — prevent credential / personal-path leakage into logs
# ---------------------------------------------------------------------------

# Patterns to scrub: Windows user profile paths, potential API key fragments
_USERNAME = os.environ.get("USERNAME", "user")
_PATH_SCRUB = re.compile(
    r"C:\\Users\\[^\\]+",
    re.IGNORECASE,
)
_KEY_SCRUB = re.compile(
    r"(?:sk-[a-zA-Z0-9]{4,}|DEEPSEEK=)[^\s,\]]{10,}",
    re.IGNORECASE,
)


def sanitize(msg):
    """Remove sensitive information from a log message.

    - Replaces C:\\Users\\<username> with C:\\Users\\***
    - Masks potential API key fragments
    """
    if not isinstance(msg, str):
        try:
            msg = str(msg)
        except Exception:
            return "<unprintable>"
    # Redact user profile paths (use lambda to avoid backslash-escaping issues)
    msg = _PATH_SCRUB.sub(lambda m: "C:\\Users\\***", msg)
    # Redact API key patterns
    msg = _KEY_SCRUB.sub(lambda m: "<redacted>", msg)
    # Truncate extremely long messages
    if len(msg) > 4000:
        msg = msg[:4000] + "...<truncated>"
    return msg


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup_logging(log_dir, verbose=False):
    """Initialize log rotation handlers. Call once at startup.

    Args:
        log_dir: Directory to write log files into.
        verbose: If True, set level to DEBUG; otherwise INFO.
    """
    global _boot_logger, _watchdog_logger, _initialized
    if _initialized:
        return
    _initialized = True

    if not FEATURE_LOG_ROTATE:
        return

    level = logging.DEBUG if verbose else logging.INFO
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # --- boot log ---
    _boot_logger = logging.getLogger("boot")
    _boot_logger.setLevel(level)
    _boot_logger.propagate = False
    bh = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "boot.log"),
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    bh.setFormatter(fmt)
    _boot_logger.addHandler(bh)

    # --- watchdog log ---
    _watchdog_logger = logging.getLogger("watchdog")
    _watchdog_logger.setLevel(level)
    _watchdog_logger.propagate = False
    wh = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "watchdog.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    wh.setFormatter(fmt)
    _watchdog_logger.addHandler(wh)


# ---------------------------------------------------------------------------
# Public logging API — drop-in replacements for _bl() / _lg()
# ---------------------------------------------------------------------------

def boot(msg, level="info"):
    """Log to boot.log (replaces _bl())."""
    if not FEATURE_LOG_ROTATE or _boot_logger is None:
        # Fallback: raw file append
        return _raw_write("boot.log", msg)
    msg_safe = sanitize(msg)
    getattr(_boot_logger, level)(msg_safe)


def watchdog(msg, level="info"):
    """Log to watchdog.log (replaces _lg() in App class)."""
    if not FEATURE_LOG_ROTATE or _watchdog_logger is None:
        return _raw_write("watchdog.log", msg)
    msg_safe = sanitize(msg)
    getattr(_watchdog_logger, level)(msg_safe)


def error(msg):
    """Log an error to both boot and watchdog logs."""
    boot(msg, "error")
    watchdog(msg, "error")


def warning(msg):
    """Log a warning to both boot and watchdog logs."""
    boot(msg, "warning")
    watchdog(msg, "warning")


# ---------------------------------------------------------------------------
# Fallback raw writers (for when feature is disabled)
# ---------------------------------------------------------------------------

def _raw_write(filename, msg):
    """Minimal fallback — append a line directly to the log file."""
    try:
        # Match the desktop app's per-user data directory before handlers exist.
        from datetime import datetime as _dt
        base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "TaskVerge")
        if not base:
            base = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, filename)
        with open(path, "a", encoding="utf-8") as f:
            f.write("{} {}\n".format(_dt.now().isoformat(), str(msg)))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        setup_logging(tmp)
        boot("Boot log started — pid={}".format(os.getpid()))
        watchdog("Watchdog START")
        boot("Normal message")
        boot("C:\\Users\\{}\\AppData\\Secret\\key.txt accessed".format(_USERNAME))
        watchdog("File saved at C:\\Users\\{}\\Documents\\report.pdf".format(_USERNAME))
        warning("A warning event occurred")
        error("An error event with DEEPSEEK=sk-test-api-key-12345 in the message")

        # Close handlers before reading/cleanup
        for logger in [_boot_logger, _watchdog_logger]:
            if logger:
                for h in list(logger.handlers):
                    h.close()
                    logger.removeHandler(h)

        for name in ["boot.log", "watchdog.log"]:
            path = os.path.join(tmp, name)
            if os.path.exists(path):
                print("=== {} ({:d} bytes) ===".format(name, os.path.getsize(path)))
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        print("  " + line.rstrip())

        # Verify sanitization
        print("\n=== Sanitization check ===")
        raw = "C:\\Users\\JohnDoe\\Documents DEEPSEEK=sk-abcdefghijklmno"
        print("Raw:      " + raw)
        print("Sanitized: " + sanitize(raw))
