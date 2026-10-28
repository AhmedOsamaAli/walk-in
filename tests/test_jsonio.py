"""JSON in and out of the disk caches (app.jsonio): orjson reads to exactly what json reads, json reads what orjson
refuses, and a cache file is written whole or not at all."""
from __future__ import annotations

import json
import math

import pytest

from app import jsonio

SAMPLES = [
    '{"name": "Café — Zamalek", "rating": 4.5, "count": 1200, "tags": [], "ok": true, "none": null}',
    '{"big": 1e16, "small": 1.5e-07, "neg": -0.0, "int": 9007199254740993, "nested": {"a": [1, [2, [3]]]}}',
    '{"same": 1, "same": 2}',  # a repeated key: the last one wins, as in json
    '[1, 2.50, "\\u2009→ ü", "\\"quoted\\"", "tab\\tnew\\nline"]',
    '\ufeff{"bom": true}',  # read as json reads text, or refused the same way
]
REFUSED_BY_ORJSON = [
    '{"value": NaN, "more": Infinity}',
    '{"far": 1e400, "near": -1e400}',
    '{"lone": "\\ud800"}',
]
# orjson would read these integers as floats; a run of 19 digits sends the text to json.
TOO_LONG_FOR_ORJSON = [
    '{"huge": 123456789012345678901234567890}',
    '{"over": 18446744073709551616, "under": -9223372036854775809}',
    '[0.12345678901234567890123, "id 13727494369054243302"]',
]


@pytest.mark.parametrize("text", SAMPLES + REFUSED_BY_ORJSON + TOO_LONG_FOR_ORJSON)
def test_values_are_what_json_reads(text):
    try:
        expected = json.loads(text)
    except ValueError:
        with pytest.raises(ValueError):
            jsonio.loads(text)
        return
    for data in (text, text.encode("utf-8", "surrogatepass")):
        got = jsonio.loads(data)
        assert json.dumps(got, sort_keys=True) == json.dumps(expected, sort_keys=True)
        assert [type(value) for value in walk(got)] == [type(value) for value in walk(expected)]
        if isinstance(expected, dict) and isinstance(expected.get("value"), float):
            assert math.isnan(got["value"])


def walk(value):
    """Every value inside a JSON value, depth first."""
    yield value
    children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
    for child in children:
        yield from walk(child)


def test_a_text_with_lone_surrogates_is_read_by_json():
    text = json.dumps({"broken": "\ud800 half"}, ensure_ascii=False)  # what json.dumps writes for broken data
    assert jsonio.loads(text) == json.loads(text)


def test_a_cache_file_is_written_whole_and_read_with_its_time(tmp_path):
    path = tmp_path / "deeper" / "answer.json"
    jsonio.write(path, b'{"v": 1}')
    data, written = jsonio.read(path)
    assert data == {"v": 1} and written == path.stat().st_mtime
    jsonio.write(path, b'{"v": 2}')
    assert jsonio.read(path)[0] == {"v": 2} and sorted(p.name for p in path.parent.iterdir()) == ["answer.json"]
    assert jsonio.read(tmp_path / "missing.json") is None
    (tmp_path / "damaged.json").write_bytes(b'{"v": ')
    assert jsonio.read(tmp_path / "damaged.json") is None


def test_a_failed_write_leaves_the_old_file_and_no_scraps(tmp_path, monkeypatch):
    path = tmp_path / "answer.json"
    jsonio.write(path, b'{"v": 1}')

    def broken(*args):
        raise OSError("disk full")

    monkeypatch.setattr(jsonio.os, "replace", broken)
    with pytest.raises(OSError):
        jsonio.write(path, b'{"v": 2}')
    assert jsonio.read(path)[0] == {"v": 1} and [p.name for p in tmp_path.iterdir()] == ["answer.json"]
