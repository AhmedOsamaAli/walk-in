"""Reuses AI answers when the evidence behind them is unchanged.

Free AI tiers allow a few dozen requests a day per model. A survey whose Qloo evidence is identical to an earlier
one would get an equivalent answer, so the earlier answer is replayed instead of spending the quota again. Keys
include the prompt version, so changing a prompt starts fresh. Answers stay on the server, like the Qloo cache.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("blankspace")


def fingerprint(*parts: Any) -> str:
    text = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class AnswerCache:
    def __init__(self, directory: Path | None, enabled: bool = True) -> None:
        self._dir = directory
        self.enabled = bool(enabled and directory)

    def _path(self, kind: str, key: str) -> Path:
        return self._dir / kind / f"{key}.json"

    def get(self, kind: str, key: str) -> dict | None:
        if not self.enabled:
            return None
        try:
            return json.loads(self._path(kind, key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, kind: str, key: str, value: dict) -> None:
        if not self.enabled:
            return
        path = self._path(kind, key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps({**value, "saved_at": time.time()}, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
        except OSError:
            log.warning("Could not save a %s answer", kind, exc_info=True)
