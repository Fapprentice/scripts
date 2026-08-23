"""JSON persistence boundary for the local application state."""

import json
import os
import tempfile


class JsonStore:
    def __init__(self, log_path=None):
        self.log_path = log_path

    def load(self, path, default=None):
        try:
            with open(path, encoding="utf-8-sig") as f:
                return json.load(f)
        except FileNotFoundError:
            return {} if default is None else default
        except Exception as exc:
            if self.log_path:
                try:
                    with open(self.log_path, "a", encoding="utf-8") as f:
                        f.write("{} JSON_FAIL {}: {}\n".format(path, os.path.basename(path), exc))
                except OSError:
                    pass
            return {} if default is None else default

    def save(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".json", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
