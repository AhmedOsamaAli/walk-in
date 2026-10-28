"""JSON in and out of the disk caches, fast and off the event loop's way.

Qloo's answers are large (a survey reads 27-66 MB of them), so they are parsed with orjson, about three times as fast
as the json module on them, to the same values: json reads whatever orjson refuses (NaN, overflowing exponents, lone
surrogates) and every text with a run of 19 digits or more, since orjson would read an integer past 64 bits as a float
where json keeps it whole (the check costs a tenth of the parse). Cache files are written whole or not at all (a
temporary file, then a rename), since readers in other threads may open them at any moment. Callers run read and write
in a worker thread.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import orjson

# Every digit becomes '0', so a run of 19 digits is a run of 19 zeros: bytes.translate and bytes.find are fast C loops.
_DIGITS_AS_ZEROS = bytes(48 if 48 <= value <= 57 else value for value in range(256))
_LONG_DIGIT_RUN = b"0" * 19


def loads(data: bytes | str) -> Any:
    """The JSON value in `data`, exactly as json.loads would give it."""
    try:
        raw = data.encode("utf-8") if isinstance(data, str) else data
    except UnicodeEncodeError:  # lone surrogates, which only json reads
        return json.loads(data)
    if raw.translate(_DIGITS_AS_ZEROS).find(_LONG_DIGIT_RUN) < 0:
        try:
            return orjson.loads(raw)
        except orjson.JSONDecodeError:
            pass
    return json.loads(data)


def read(path: Path) -> tuple[Any, float] | None:
    """A cached answer and when it was written (seconds since the epoch); None when there is none or it is damaged."""
    try:
        with open(path, "rb") as file:
            data = file.read()
            written = os.fstat(file.fileno()).st_mtime
        return loads(data), written
    except (OSError, ValueError):
        return None


def write(path: Path, data: bytes) -> None:
    """Writes `data` to `path` whole: readers see the old file or the new one, never part of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex[:12]}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
