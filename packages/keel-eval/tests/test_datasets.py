from __future__ import annotations

from pathlib import Path

import pytest

from keel_eval import GateError
from keel_eval import datasets as ds


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "d.jsonl"
    path.write_text(text, encoding="utf-8")
    return path


def test_quality_valid_with_blank_lines_and_roles(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '{"question": "a", "role": "hr", "roles": ["employee"], "must_include": ["x"]}\n\n'
        '{"question": "b", "expected_sources": ["handbook"]}\n',
    )
    cases = ds.load_quality(path)
    assert [c.question for c in cases] == ["a", "b"]
    assert cases[0].roles == frozenset({"hr", "employee"})
    assert cases[0].must_include == ("x",)
    assert cases[1].roles is None
    assert cases[1].expected_sources == ("handbook",)


def test_attack_valid(tmp_path: Path) -> None:
    path = _write(
        tmp_path, '{"input": "hi", "expect": "no_tool", "tool": "refund", "forbidden": ["z"]}\n'
    )
    (case,) = ds.load_attack(path)
    assert (case.expect, case.tool, case.forbidden) == ("no_tool", "refund", ("z",))


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ('{"question": "a"}\n{bad json}\n', "d.jsonl:2: invalid JSON"),
        ("[1, 2]\n", "d.jsonl:1: each line must be a JSON object"),
        ('{"question": ""}\n', "d.jsonl:1: 'question' must be a non-empty string"),
        ('{"question": "a", "extra": 1}\n', "unknown keys"),
        ('{"question": "a", "must_include": "x"}\n', "'must_include' must be a list of strings"),
        ('{"question": "a", "role": 3}\n', "'role' must be a non-empty string"),
        ("\n\n", "has no cases"),
    ],
)
def test_quality_malformed(tmp_path: Path, text: str, needle: str) -> None:
    with pytest.raises(GateError, match=needle):
        ds.load_quality(_write(tmp_path, text))


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ('{"input": "a", "expect": "nope"}\n', "d.jsonl:1: 'expect' must be one of"),
        ('{"input": "a"}\n', "'expect' must be one of"),
        ('{"input": "a", "expect": "refuse", "tool": 3}\n', "'tool' must be a string"),
        ('{"expect": "refuse"}\n', "'input' must be a non-empty string"),
    ],
)
def test_attack_malformed(tmp_path: Path, text: str, needle: str) -> None:
    with pytest.raises(GateError, match=needle):
        ds.load_attack(_write(tmp_path, text))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(GateError, match="cannot read dataset"):
        ds.load_quality(tmp_path / "nope.jsonl")


def test_not_utf8(tmp_path: Path) -> None:
    path = tmp_path / "d.jsonl"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(GateError, match="cannot read dataset"):
        ds.load_quality(path)


def test_size_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ds, "MAX_DATASET_BYTES", 10)
    with pytest.raises(GateError, match="larger than"):
        ds.load_quality(_write(tmp_path, '{"question": "long enough to exceed"}\n'))


def test_resolve_in_accepts_inside_and_rejects_traversal(tmp_path: Path) -> None:
    assert ds.resolve_in(tmp_path, "evals/q.jsonl") == (tmp_path / "evals" / "q.jsonl").resolve()
    for bad in ("../outside.jsonl", "evals/../../outside.jsonl", str(tmp_path.parent / "x")):
        with pytest.raises(GateError, match="outside the spec directory"):
            ds.resolve_in(tmp_path, bad)
