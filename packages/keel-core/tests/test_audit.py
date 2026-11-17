from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from keel_core import KeelSpec, load_spec
from keel_core.audit import AuditReport, audit_spec


def _spec(base: dict[str, Any], **changes: Any) -> KeelSpec:
    data = {**base, "profile": "standard", **changes}
    return KeelSpec.model_validate(data)


def _status(report: AuditReport, item_id: str) -> str:
    return next(i.status for i in report.items if i.id == item_id)


def _bare(minimal: dict[str, Any]) -> AuditReport:
    return audit_spec(
        _spec(
            minimal,
            access={"default": "allow"},
            guardrails={"input": [], "output": []},
        )
    )


def test_report_has_ten_llm_items_and_four_agentic(minimal: dict[str, Any]) -> None:
    report = audit_spec(_spec(minimal))

    assert [i.id for i in report.llm_items] == [f"LLM{n:02d}" for n in range(1, 11)]
    assert [i.id for i in report.agentic_items] == ["AGT01", "AGT02", "AGT03", "AGT04"]
    assert report.app == "demo"
    assert sum(report.counts().values()) == 14


def test_audit_is_deterministic(example_spec: Path) -> None:
    spec = load_spec(example_spec)

    assert audit_spec(spec) == audit_spec(spec)


def test_bare_spec_is_open_where_nothing_is_configured(minimal: dict[str, Any]) -> None:
    report = _bare(minimal)

    for item_id in ("LLM01", "LLM02", "LLM03", "LLM05", "LLM07", "LLM09", "LLM10"):
        assert _status(report, item_id) == "open", item_id
    assert {i.id for i in report.open_items} >= {"LLM01", "LLM10"}
    assert all(i.advice for i in report.open_items)


def test_no_rag_and_no_tools_cover_the_rag_and_agency_risks(minimal: dict[str, Any]) -> None:
    report = _bare(minimal)

    for item_id in ("LLM04", "LLM06", "LLM08", "AGT01", "AGT02", "AGT03"):
        assert _status(report, item_id) == "covered", item_id


def test_prompt_injection_partial_and_covered(minimal: dict[str, Any]) -> None:
    guard_only = audit_spec(_spec(minimal, guardrails={"input": ["prompt_injection"]}))
    attack_only = audit_spec(
        _spec(
            minimal,
            guardrails={"input": [], "output": []},
            evals={"attack": [{"name": "a", "dataset": "a.jsonl"}]},
        )
    )
    both = audit_spec(
        _spec(
            minimal,
            guardrails={"input": ["prompt_injection"]},
            evals={"attack": [{"name": "a", "dataset": "a.jsonl"}]},
        )
    )

    assert _status(guard_only, "LLM01") == "partial"
    assert "attack suite" in next(i for i in guard_only.items if i.id == "LLM01").advice
    assert _status(attack_only, "LLM01") == "partial"
    assert _status(both, "LLM01") == "covered"
    assert _status(both, "LLM07") == "covered"
    assert _status(guard_only, "LLM07") == "partial"
    assert _status(attack_only, "LLM07") == "partial"


def test_sensitive_information(minimal: dict[str, Any]) -> None:
    covered = audit_spec(_spec(minimal, guardrails={"input": ["pii"], "output": ["pii"]}))
    logging = audit_spec(
        _spec(
            minimal,
            guardrails={"input": ["pii"], "output": ["pii"]},
            observability={"log_prompts": True},
        )
    )

    assert _status(covered, "LLM02") == "covered"
    assert _status(logging, "LLM02") == "partial"


def test_supply_chain_needs_a_gate_to_be_partial(minimal: dict[str, Any]) -> None:
    gated = audit_spec(
        _spec(minimal, evals={"quality": [{"name": "q", "dataset": "q", "min_score": 0.5}]})
    )

    assert _status(gated, "LLM03") == "partial"
    assert _status(_bare(minimal), "LLM03") == "open"


def test_poisoning_with_rag(minimal: dict[str, Any]) -> None:
    rag = {"sources": [{"name": "docs", "uri": "file://docs"}]}
    without = audit_spec(_spec(minimal, rag=rag))
    with_attack = audit_spec(
        _spec(minimal, rag=rag, evals={"attack": [{"name": "a", "dataset": "a.jsonl"}]})
    )

    assert _status(without, "LLM04") == "open"
    assert _status(with_attack, "LLM04") == "partial"


def test_output_handling(minimal: dict[str, Any]) -> None:
    strong = audit_spec(_spec(minimal, guardrails={"output": ["schema"]}))
    weak = audit_spec(_spec(minimal, guardrails={"output": ["pii"]}))

    assert _status(strong, "LLM05") == "covered"
    assert _status(weak, "LLM05") == "partial"
    assert _status(_bare(minimal), "LLM05") == "open"


def _tool_spec(minimal: dict[str, Any], **kw: Any) -> KeelSpec:
    data: dict[str, Any] = {
        "tools": [
            {"name": "lookup", "mcp_server": "mcp://x/lookup"},
            {"name": "refund", "mcp_server": "mcp://x/refund", "requires_approval": True},
        ],
        "access": {
            "default": "deny",
            "roles": [
                {"name": "agent", "tools": ["lookup", "refund"]},
                {"name": "viewer", "tools": []},
            ],
        },
        "evals": {"attack": [{"name": "a", "dataset": "a.jsonl"}]},
    }
    data.update(kw)
    return _spec(minimal, **data)


def test_excessive_agency_covered_when_scoped_and_tested(minimal: dict[str, Any]) -> None:
    report = audit_spec(_tool_spec(minimal))

    assert _status(report, "LLM06") == "covered"
    assert _status(report, "AGT01") == "covered"
    # lookup runs without approval, and the spec cannot say it is read-only.
    assert _status(report, "AGT02") == "partial"
    assert _status(report, "AGT03") == "covered"


def test_excessive_agency_partial_when_tool_is_broad_and_unapproved(
    minimal: dict[str, Any],
) -> None:
    spec = _tool_spec(
        minimal,
        access={
            "default": "deny",
            "roles": [
                {"name": "a", "tools": ["lookup", "refund"]},
                {"name": "b", "tools": ["lookup"]},
            ],
        },
    )
    report = audit_spec(spec)
    item = next(i for i in report.items if i.id == "LLM06")

    assert item.status == "partial"
    assert any("lookup" in e for e in item.evidence)
    assert _status(report, "AGT02") == "partial"


def test_excessive_agency_partial_without_attack_suite(minimal: dict[str, Any]) -> None:
    report = audit_spec(_tool_spec(minimal, evals={}))

    assert _status(report, "LLM06") == "partial"


def test_excessive_agency_open_with_default_allow(minimal: dict[str, Any]) -> None:
    report = audit_spec(_tool_spec(minimal, access={"default": "allow"}))

    assert _status(report, "LLM06") == "open"
    assert _status(report, "AGT01") == "open"


def test_tools_granted_to_nobody_and_unapproved_tools(minimal: dict[str, Any]) -> None:
    spec = _tool_spec(
        minimal,
        tools=[
            {"name": "lookup", "mcp_server": "mcp://x/lookup"},
            {"name": "unused", "mcp_server": "mcp://x/unused"},
        ],
        access={"default": "deny", "roles": [{"name": "a", "tools": ["lookup"]}]},
    )
    report = audit_spec(spec)
    agt01 = next(i for i in report.items if i.id == "AGT01")

    assert agt01.status == "partial"
    assert any("unused" in e for e in agt01.evidence)
    assert _status(report, "AGT02") == "partial"
    agt03 = next(i for i in report.items if i.id == "AGT03")
    assert any("no rag" in e for e in agt03.evidence)


def test_provenance_mentions_rag_when_present(minimal: dict[str, Any]) -> None:
    spec = _tool_spec(minimal, rag={"sources": [{"name": "docs", "uri": "file://docs"}]})
    agt03 = next(i for i in audit_spec(spec).items if i.id == "AGT03")

    assert any("suspicious" in e for e in agt03.evidence)


def test_vector_weaknesses(minimal: dict[str, Any]) -> None:
    rag = {"sources": [{"name": "docs", "uri": "file://docs"}]}
    scoped = audit_spec(
        _spec(
            minimal,
            rag=rag,
            access={"default": "deny", "roles": [{"name": "r", "sources": ["docs"]}]},
        )
    )
    unscoped = audit_spec(_spec(minimal, rag=rag, access={"default": "deny"}))
    allow = audit_spec(_spec(minimal, rag=rag, access={"default": "allow"}))
    no_cites = audit_spec(
        _spec(
            minimal,
            rag={**rag, "require_citations": False},
            access={"default": "deny", "roles": [{"name": "r", "sources": ["docs"]}]},
        )
    )

    assert _status(scoped, "LLM08") == "covered"
    assert _status(unscoped, "LLM08") == "partial"
    assert _status(allow, "LLM08") == "open"
    assert _status(no_cites, "LLM08") == "partial"


def test_misinformation(minimal: dict[str, Any]) -> None:
    rag = {"sources": [{"name": "docs", "uri": "file://docs"}]}
    quality = {"quality": [{"name": "q", "dataset": "q.jsonl", "min_score": 0.5}]}

    assert _status(audit_spec(_spec(minimal, rag=rag, evals=quality)), "LLM09") == "covered"
    assert _status(audit_spec(_spec(minimal, evals=quality)), "LLM09") == "partial"
    assert _status(audit_spec(_spec(minimal, rag=rag)), "LLM09") == "partial"
    assert _status(_bare(minimal), "LLM09") == "open"


def test_unbounded_consumption(minimal: dict[str, Any]) -> None:
    both = audit_spec(
        _spec(minimal, cache_router={"budget_usd_per_day": 5, "rate_limit_per_minute": 10})
    )
    budget = audit_spec(_spec(minimal, cache_router={"budget_usd_per_day": 5}))
    rate = audit_spec(_spec(minimal, cache_router={"rate_limit_per_minute": 10}))

    assert _status(both, "LLM10") == "covered"
    assert _status(budget, "LLM10") == "partial"
    assert _status(rate, "LLM10") == "partial"
    assert _status(_bare(minimal), "LLM10") == "open"


def test_observability_exporter_none_is_partial(minimal: dict[str, Any]) -> None:
    off = audit_spec(_spec(minimal, observability={"exporter": "none"}))
    on = audit_spec(_spec(minimal, observability={"exporter": "console"}))

    assert _status(off, "AGT04") == "partial"
    assert _status(on, "AGT04") == "covered"


def test_example_spec_has_no_open_items(example_spec: Path) -> None:
    report = audit_spec(load_spec(example_spec))

    assert report.open_items == ()


def test_serialisation(example_spec: Path) -> None:
    report = audit_spec(load_spec(example_spec))

    data = json.loads(json.dumps(report.to_dict()))
    text = report.to_text()

    assert data["standard"].startswith("OWASP Top 10 for LLM Applications 2025")
    assert len(data["llm"]) == 10
    assert data["counts"] == report.counts()
    assert "LLM01" in text
    assert "covered" in text.lower()
    assert text.endswith("open")
