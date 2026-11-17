"""Python tools (``python://module:function``) with a description lock.

The lock guards against tool poisoning: if a tool's description or schema changes, the model
would read different instructions than the ones a human reviewed. A changed tool is left out
until someone reviews it and deletes its entry from ``tools.lock``.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import inspect
import json
import sys
import warnings
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from keel_core.errors import KeelError
from keel_core.ports import Principal, ToolPort
from keel_core.spec.models import Tool

DEFAULT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
}


class PythonTool:
    """Wraps ``fn(arguments, principal) -> str``, sync or async."""

    def __init__(
        self,
        name: str,
        fn: Callable[[Mapping[str, Any], Principal], Any],
        *,
        description: str | None = None,
        input_schema: Mapping[str, Any] | None = None,
    ) -> None:
        self.name = name
        self._fn = fn
        doc = inspect.getdoc(fn)
        self.description = description or (doc.split("\n\n")[0] if doc else f"Tool {name}")
        self.input_schema: Mapping[str, Any] = input_schema or DEFAULT_SCHEMA

    async def call(self, arguments: Mapping[str, Any], *, principal: Principal) -> str:
        if inspect.iscoroutinefunction(self._fn):
            result = await self._fn(arguments, principal)
        else:
            result = await asyncio.to_thread(self._fn, arguments, principal)
        return str(result)


def load_python_function(
    target: str, base_dir: Path
) -> Callable[[Mapping[str, Any], Principal], Any]:
    """Resolve ``module:function``. The spec dir is appended to ``sys.path`` for app modules."""
    module_name, sep, func_name = target.partition(":")
    if not sep or not module_name or not func_name:
        raise KeelError(f"tool target '{target}' must look like python://module:function")
    base = str(base_dir.resolve())
    if base not in sys.path:
        sys.path.append(base)  # appended, so it can never shadow the standard library
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise KeelError(f"cannot import tool module '{module_name}': {exc}") from exc
    fn = getattr(module, func_name, None)
    if not callable(fn):
        raise KeelError(f"tool function '{func_name}' not found in module '{module_name}'")
    return fn  # type: ignore[no-any-return]


def tool_fingerprint(tool: ToolPort) -> str:
    schema = json.dumps(dict(tool.input_schema), sort_keys=True, separators=(",", ":"))
    payload = "\0".join((tool.name, tool.description, schema))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_lock(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise KeelError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise KeelError(f"{path} must hold a JSON object")
    return {str(k): str(v) for k, v in data.items()}


def load_tools(tools: Sequence[Tool], *, base_dir: Path, lock_path: Path) -> dict[str, ToolPort]:
    """Build the tools reachable in local mode, applying the description lock.

    ``mcp://`` tools are not reachable here and are left out with a warning (fail closed).
    """
    lock = _read_lock(lock_path)
    updated = dict(lock)
    out: dict[str, ToolPort] = {}
    for spec_tool in tools:
        uri = spec_tool.mcp_server
        if uri.startswith("mcp://"):
            warnings.warn(
                f"tool '{spec_tool.name}' uses {uri}, which is not reachable in local mode; "
                "it is unavailable",
                stacklevel=2,
            )
            continue
        if not uri.startswith("python://"):
            raise KeelError(f"tool '{spec_tool.name}': unsupported uri '{uri}' in local mode")
        fn = load_python_function(uri.removeprefix("python://"), base_dir)
        tool = PythonTool(spec_tool.name, fn)
        fingerprint = tool_fingerprint(tool)
        known = lock.get(tool.name)
        if known is None:
            updated[tool.name] = fingerprint
        elif known != fingerprint:
            warnings.warn(
                f"tool '{tool.name}': tool description changed; review and delete "
                f"tools.lock entry ({lock_path})",
                stacklevel=2,
            )
            continue
        out[tool.name] = tool
    if updated != lock:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out
