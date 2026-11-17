from __future__ import annotations

from pathlib import Path

import pytest

SPEC_TEXT = """\
keel: keel/v0
app:
  name: tiny
  version: 0.1.0
model:
  provider: keel
  name: extractive
system_prompt:
  template: prompts/system.md
  variables:
    company: Acme
rag:
  sources:
    - name: handbook
      uri: file://docs/handbook
    - name: finance
      uri: file://docs/finance.md
tools:
  - name: lookup-ticket
    mcp_server: python://keel_local.demo_tools:lookup_ticket
access:
  default: deny
  roles:
    - name: employee
      sources: [handbook]
      tools: [lookup-ticket]
    - name: finance
      sources: [handbook, finance]
guardrails:
  input: [prompt_injection, pii]
  output: [pii]
evals:
  attack:
    - name: basic
      dataset: evals/attack.jsonl
"""


@pytest.fixture
def spec_dir(tmp_path: Path) -> Path:
    """A tiny app on disk: spec, prompt and two document sources."""
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "system.md").write_text("You work for {company}.\n", encoding="utf-8")
    (tmp_path / "docs" / "handbook").mkdir(parents=True)
    (tmp_path / "docs" / "handbook" / "travel.md").write_text(
        "Employees may book economy flights for trips.\n\n"
        "Hotels must cost less than 150 euros per night.\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "finance.md").write_text(
        "The quarterly budget for marketing is 40000 euros.\n", encoding="utf-8"
    )
    (tmp_path / "keel.yaml").write_text(SPEC_TEXT, encoding="utf-8")
    return tmp_path
