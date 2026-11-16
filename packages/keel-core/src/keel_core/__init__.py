"""Keel core: the spec, its validation and the layer interfaces."""

from importlib.metadata import PackageNotFoundError, version

from keel_core.errors import KeelError, SpecError, SpecIssue
from keel_core.spec import KeelSpec, diff_specs, load_spec, parse_spec

try:
    __version__ = version("keel-core")
except PackageNotFoundError:  # pragma: no cover - only when run from a source tree
    __version__ = "0.0.0"

__all__ = [
    "KeelError",
    "KeelSpec",
    "SpecError",
    "SpecIssue",
    "__version__",
    "diff_specs",
    "load_spec",
    "parse_spec",
]
