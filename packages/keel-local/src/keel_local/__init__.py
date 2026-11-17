"""Keel local mode: in-process adapters for all eight layers.

``build_runtime`` is the composition root: it reads ``keel.yaml`` and wires one in-process
adapter per layer into a :class:`keel_core.runtime.Runtime`.
"""

from __future__ import annotations

from keel_local.runtime import STATE_DIR_NAME, build_runtime, state_dir_for

__all__ = ["STATE_DIR_NAME", "build_runtime", "state_dir_for"]
