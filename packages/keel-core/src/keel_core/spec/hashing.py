"""Stable fingerprint of a spec, used in cache keys, audit entries and release records."""

from __future__ import annotations

import hashlib
import json

from keel_core.spec.models import KeelSpec


def spec_hash(spec: KeelSpec) -> str:
    """Return the sha256 hex digest of the spec's canonical JSON.

    Keys are sorted and separators are compact, so the hash only changes when the
    meaning of the spec changes, not when the YAML is reformatted.
    """
    canonical = json.dumps(
        spec.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
