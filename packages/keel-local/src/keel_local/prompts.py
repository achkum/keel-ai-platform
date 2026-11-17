"""System prompt registry backed by files, with content-hash versions."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path

from keel_core.errors import KeelError

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("API key (sk-...)", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
)


def check_no_secrets(text: str) -> None:
    """Fail the build if a prompt looks like it contains a credential.

    Prompts are versioned, traced and shared, so a secret in one leaks widely.
    """
    for label, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            raise KeelError(f"prompt contains what looks like a secret: {label}")


class FilePromptRegistry:
    """Reads templates from ``base_dir`` and fills ``{name}`` placeholders.

    Only plain ``{name}`` placeholders for the given variables are replaced, with a regex,
    never ``str.format``, so a template cannot reach attributes or call anything.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base = Path(base_dir).resolve()

    def render(self, template: str, variables: Mapping[str, str]) -> tuple[str, str]:
        path = (self._base / template).resolve()
        if not path.is_relative_to(self._base):
            raise KeelError(f"prompt template '{template}' is outside the spec directory")
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise KeelError(f"prompt template not found: {template}") from None
        except (OSError, UnicodeDecodeError) as exc:
            raise KeelError(f"cannot read prompt template {template}: {exc}") from exc
        text = _PLACEHOLDER.sub(lambda m: variables.get(m.group(1), m.group(0)), raw)
        payload = raw + "\0" + json.dumps(sorted(variables.items()), ensure_ascii=False)
        version = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return text, version
