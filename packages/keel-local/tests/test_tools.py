from __future__ import annotations

import asyncio
import json
import sys
import textwrap
import warnings
from pathlib import Path

import pytest

from keel_core.errors import KeelError
from keel_core.ports import Principal
from keel_core.spec.models import Tool
from keel_local.demo_tools import issue_refund, lookup_ticket
from keel_local.tools import PythonTool, load_tools

P = Principal("ann", frozenset({"employee"}))


def _tool(name: str, uri: str) -> Tool:
    return Tool(name=name, mcp_server=uri)


def test_demo_tools_are_deterministic() -> None:
    assert lookup_ticket({"query": "T-1"}, P) == lookup_ticket({"query": "T-1"}, P)
    assert "T-1" in lookup_ticket({"query": "T-1"}, P)
    assert "unknown" in issue_refund({}, P)
    assert "ann" in issue_refund({"query": "o9"}, P)


def test_python_tool_sync_and_async() -> None:
    def sync_fn(arguments: dict[str, str], principal: Principal) -> str:
        """Short summary.

        More detail that is not part of the description.
        """
        return f"{arguments['query']}:{principal.user_id}"

    async def async_fn(arguments: dict[str, str], principal: Principal) -> str:
        return "async"

    t = PythonTool("s", sync_fn)
    assert t.description == "Short summary."
    assert t.input_schema["properties"]["query"] == {"type": "string"}
    assert asyncio.run(t.call({"query": "q"}, principal=P)) == "q:ann"
    a = PythonTool("a", async_fn)
    assert a.description == "Tool a"
    assert asyncio.run(a.call({}, principal=P)) == "async"


def test_load_tools_writes_lock_and_reloads(tmp_path: Path) -> None:
    lock = tmp_path / ".keel" / "tools.lock"
    spec_tools = [_tool("lookup-ticket", "python://keel_local.demo_tools:lookup_ticket")]
    tools = load_tools(spec_tools, base_dir=tmp_path, lock_path=lock)
    assert set(tools) == {"lookup-ticket"}
    assert set(json.loads(lock.read_text(encoding="utf-8"))) == {"lookup-ticket"}
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert set(load_tools(spec_tools, base_dir=tmp_path, lock_path=lock)) == {"lookup-ticket"}


def test_lock_mismatch_excludes_tool(tmp_path: Path) -> None:
    lock = tmp_path / "tools.lock"
    lock.write_text(json.dumps({"lookup-ticket": "0" * 64}), encoding="utf-8")
    spec_tools = [_tool("lookup-ticket", "python://keel_local.demo_tools:lookup_ticket")]
    with pytest.warns(UserWarning, match="tool description changed; review and delete"):
        tools = load_tools(spec_tools, base_dir=tmp_path, lock_path=lock)
    assert tools == {}
    # deleting the entry accepts the current description
    lock.write_text("{}", encoding="utf-8")
    assert set(load_tools(spec_tools, base_dir=tmp_path, lock_path=lock)) == {"lookup-ticket"}


def test_description_change_in_app_module_detected(tmp_path: Path) -> None:
    mod = tmp_path / "lockmod_app.py"
    mod.write_text(
        textwrap.dedent(
            '''
            def go(arguments, principal):
                """Original description."""
                return "x"
            '''
        ),
        encoding="utf-8",
    )
    lock = tmp_path / "tools.lock"
    spec_tools = [_tool("go", "python://lockmod_app:go")]
    try:
        assert set(load_tools(spec_tools, base_dir=tmp_path, lock_path=lock)) == {"go"}
        mod.write_text(
            mod.read_text(encoding="utf-8").replace("Original", "Evil"), encoding="utf-8"
        )
        sys.modules.pop("lockmod_app")
        with pytest.warns(UserWarning, match="description changed"):
            assert load_tools(spec_tools, base_dir=tmp_path, lock_path=lock) == {}
    finally:
        sys.modules.pop("lockmod_app", None)
        if str(tmp_path.resolve()) in sys.path:
            sys.path.remove(str(tmp_path.resolve()))


def test_mcp_tool_left_out_with_warning(tmp_path: Path) -> None:
    with pytest.warns(UserWarning, match="not reachable in local mode"):
        tools = load_tools(
            [_tool("remote", "mcp://server/tool")], base_dir=tmp_path, lock_path=tmp_path / "l"
        )
    assert tools == {}
    assert not (tmp_path / "l").exists()


@pytest.mark.parametrize(
    ("uri", "message"),
    [
        ("http://x", "unsupported uri"),
        ("python://nocolon", "must look like"),
        ("python://no_such_module_xyz:f", "cannot import"),
        ("python://keel_local.demo_tools:missing", "not found"),
    ],
)
def test_bad_tool_targets(tmp_path: Path, uri: str, message: str) -> None:
    with pytest.raises(KeelError, match=message):
        load_tools([_tool("t", uri)], base_dir=tmp_path, lock_path=tmp_path / "l")


def test_corrupt_lock_file(tmp_path: Path) -> None:
    lock = tmp_path / "l"
    spec_tools = [_tool("t", "python://keel_local.demo_tools:lookup_ticket")]
    lock.write_text("{not json", encoding="utf-8")
    with pytest.raises(KeelError, match="cannot read"):
        load_tools(spec_tools, base_dir=tmp_path, lock_path=lock)
    lock.write_text("[]", encoding="utf-8")
    with pytest.raises(KeelError, match="JSON object"):
        load_tools(spec_tools, base_dir=tmp_path, lock_path=lock)
