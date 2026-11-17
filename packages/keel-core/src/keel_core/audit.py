"""``keel audit``: map a spec to the OWASP Top 10 for LLM Applications.

We use the 2025 edition IDs (LLM01 Prompt Injection to LLM10 Unbounded Consumption) because
those are the ones we can cite precisely. The agentic items (``AGT01`` to ``AGT04``) are Keel's
own short checklist for tools; they are not OWASP identifiers.

The audit is a pure function of the spec. It reads settings, not datasets or running systems, so
a ``covered`` item means "the spec turns the control on", not "the control was proven to work".
Proof comes from the eval gate. Status meanings:

- ``covered``: the settings that address this risk are on.
- ``partial``: some settings are on, or the risk needs work outside the spec.
- ``open``: nothing in the spec addresses this risk.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from keel_core.spec.models import KeelSpec

AuditStatus = Literal["covered", "partial", "open"]

_STATUSES: tuple[AuditStatus, ...] = ("covered", "partial", "open")


@dataclass(frozen=True, slots=True)
class AuditItem:
    id: str
    title: str
    status: AuditStatus
    evidence: tuple[str, ...]
    """Which spec settings led to the status, as short sentences."""
    advice: str
    """What to change or do next. Empty when there is nothing to add."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "evidence": list(self.evidence),
            "advice": self.advice,
        }


@dataclass(frozen=True, slots=True)
class AuditReport:
    app: str
    version: str
    llm_items: tuple[AuditItem, ...]
    agentic_items: tuple[AuditItem, ...]

    @property
    def items(self) -> tuple[AuditItem, ...]:
        return self.llm_items + self.agentic_items

    @property
    def open_items(self) -> tuple[AuditItem, ...]:
        return tuple(i for i in self.items if i.status == "open")

    def counts(self) -> dict[str, int]:
        return {s: sum(1 for i in self.items if i.status == s) for s in _STATUSES}

    def to_dict(self) -> dict[str, Any]:
        return {
            "app": self.app,
            "version": self.version,
            "standard": "OWASP Top 10 for LLM Applications 2025",
            "counts": self.counts(),
            "llm": [i.to_dict() for i in self.llm_items],
            "agentic": [i.to_dict() for i in self.agentic_items],
        }

    def to_text(self) -> str:
        lines = [f"Keel audit: {self.app} {self.version}", ""]
        for heading, items in (
            ("OWASP Top 10 for LLM Applications 2025", self.llm_items),
            ("Agentic checks for tools (Keel checklist)", self.agentic_items),
        ):
            lines.append(heading)
            for item in items:
                lines.append(f"  {item.status.upper():<8} {item.id}  {item.title}")
                lines.extend(f"           - {e}" for e in item.evidence)
                if item.advice:
                    lines.append(f"           > {item.advice}")
            lines.append("")
        c = self.counts()
        lines.append(f"{c['covered']} covered, {c['partial']} partial, {c['open']} open")
        return "\n".join(lines)


def audit_spec(spec: KeelSpec) -> AuditReport:
    """Score ``spec`` against the checklist. Deterministic and free of side effects."""
    return AuditReport(
        app=spec.app.name,
        version=spec.app.version,
        llm_items=tuple(check(spec) for check in _LLM_CHECKS),
        agentic_items=tuple(check(spec) for check in _AGENTIC_CHECKS),
    )


# ---------------------------------------------------------------- helpers


def _item(
    id_: str, title: str, status: AuditStatus, evidence: list[str], advice: str = ""
) -> AuditItem:
    return AuditItem(id_, title, status, tuple(evidence), advice)


def _has_attack(spec: KeelSpec) -> bool:
    return bool(spec.evals.attack)


def _has_quality(spec: KeelSpec) -> bool:
    return bool(spec.evals.quality)


def _flag(on: bool, yes: str, no: str) -> str:
    return yes if on else no


# ---------------------------------------------------------------- OWASP LLM Top 10 (2025)


def _llm01(spec: KeelSpec) -> AuditItem:
    title = "Prompt Injection"
    guard = "prompt_injection" in spec.guardrails.input
    attack = _has_attack(spec)
    evidence = [
        _flag(guard, "guardrails.input has prompt_injection", "no prompt_injection input check"),
        _flag(attack, f"{len(spec.evals.attack)} attack suite(s) in the gate", "no attack suite"),
    ]
    if guard and attack:
        return _item("LLM01", title, "covered", evidence)
    if guard:
        return _item(
            "LLM01", title, "partial", evidence, "Add an attack suite with injection cases."
        )
    if attack:
        return _item(
            "LLM01", title, "partial", evidence, "Add prompt_injection to guardrails.input."
        )
    return _item(
        "LLM01",
        title,
        "open",
        evidence,
        "Add prompt_injection to guardrails.input and an attack suite.",
    )


def _llm02(spec: KeelSpec) -> AuditItem:
    title = "Sensitive Information Disclosure"
    pii_out = "pii" in spec.guardrails.output
    pii_in = "pii" in spec.guardrails.input
    deny = spec.access.default == "deny"
    no_log = not spec.observability.log_prompts
    evidence = [
        f"PII check on input: {'yes' if pii_in else 'no'}, on output: {'yes' if pii_out else 'no'}",
        _flag(deny, "access.default is deny", "access.default is allow"),
        _flag(no_log, "prompts are not logged", "observability.log_prompts is true"),
    ]
    if pii_out and deny and no_log:
        return _item("LLM02", title, "covered", evidence)
    if pii_in or pii_out or deny:
        advice = "Turn on the pii output check, keep access.default deny and keep prompts unlogged."
        return _item("LLM02", title, "partial", evidence, advice)
    return _item(
        "LLM02",
        title,
        "open",
        evidence,
        "Add pii checks, set access.default to deny and stop logging prompts.",
    )


def _llm03(spec: KeelSpec) -> AuditItem:
    title = "Supply Chain"
    gate = _has_quality(spec) or _has_attack(spec)
    evidence = [
        "the spec is hashed and a promoted release pins that hash",
        f"{len(spec.tools)} tool(s) declared; local mode records tool code in tools.lock",
        f"{len(spec.model.fallbacks)} fallback model(s) declared",
    ]
    advice = (
        "Dependency and model provenance (SBOM, signed models) is outside the spec. "
        "Pin dependencies with a lock file and scan them in CI."
    )
    return _item("LLM03", title, "partial" if gate else "open", evidence, advice)


def _llm04(spec: KeelSpec) -> AuditItem:
    title = "Data and Model Poisoning"
    if spec.rag is None:
        return _item("LLM04", title, "covered", ["no rag layer: the app ingests no documents"])
    attack = _has_attack(spec)
    evidence = [
        f"{len(spec.rag.sources)} rag source(s); ingestion marks suspicious text untrusted",
        _flag(attack, "attack suites can plant instructions in documents", "no attack suite"),
    ]
    if attack:
        return _item(
            "LLM04",
            title,
            "partial",
            evidence,
            "Keep sources under change control and add a planted-instruction attack case.",
        )
    return _item(
        "LLM04",
        title,
        "open",
        evidence,
        "Add an attack suite that plants an instruction in a source document.",
    )


def _llm05(spec: KeelSpec) -> AuditItem:
    title = "Improper Output Handling"
    out = spec.guardrails.output
    strong = {"schema", "toxicity"} & set(out)
    evidence = [f"guardrails.output: {', '.join(out) if out else 'none'}"]
    if strong:
        return _item("LLM05", title, "covered", evidence)
    if out:
        return _item(
            "LLM05",
            title,
            "partial",
            evidence,
            "Add a schema or toxicity output check, and escape model output in your front end.",
        )
    return _item(
        "LLM05",
        title,
        "open",
        evidence,
        "Add output guardrails. Treat model output as untrusted input in downstream code.",
    )


def _llm06(spec: KeelSpec) -> AuditItem:
    title = "Excessive Agency"
    if not spec.tools:
        return _item("LLM06", title, "covered", ["the app declares no tools"])
    deny = spec.access.default == "deny"
    attack = _has_attack(spec)
    role_names = {r.name for r in spec.access.roles}
    broad = [
        t.name
        for t in spec.tools
        if not t.requires_approval
        and role_names
        and all(t.name in r.tools for r in spec.access.roles)
    ]
    needing_approval = sum(t.requires_approval for t in spec.tools)
    evidence = [
        _flag(deny, "access.default is deny", "access.default is allow"),
        f"{needing_approval} of {len(spec.tools)} tool(s) need approval",
        _flag(attack, "attack suites check tool misuse", "no attack suite"),
    ]
    if broad:
        evidence.append(f"granted to every role without approval: {', '.join(broad)}")
    if not deny:
        return _item(
            "LLM06",
            title,
            "open",
            evidence,
            "Set access.default to deny and grant each tool to the roles that need it.",
        )
    if attack and not broad:
        return _item("LLM06", title, "covered", evidence)
    return _item(
        "LLM06",
        title,
        "partial",
        evidence,
        "Add an attack suite with no_tool cases, and require approval or narrow roles for tools.",
    )


def _llm07(spec: KeelSpec) -> AuditItem:
    title = "System Prompt Leakage"
    guard = "prompt_injection" in spec.guardrails.input
    attack = _has_attack(spec)
    evidence = [
        _flag(guard, "prompt_injection input check is on", "no prompt_injection input check"),
        _flag(attack, "attack suites can include no_leak cases", "no attack suite"),
        "the audit cannot read datasets: check that a no_leak case exists",
    ]
    if guard and attack:
        return _item(
            "LLM07",
            title,
            "covered",
            evidence,
            "Keep secrets out of the prompt. Add a no_leak case for the prompt text.",
        )
    if guard or attack:
        return _item(
            "LLM07",
            title,
            "partial",
            evidence,
            "Add prompt_injection input checks and a no_leak attack case. Keep secrets out.",
        )
    return _item(
        "LLM07",
        title,
        "open",
        evidence,
        "Add an attack suite with no_leak cases. Keep secrets out of prompts.",
    )


def _llm08(spec: KeelSpec) -> AuditItem:
    title = "Vector and Embedding Weaknesses"
    if spec.rag is None:
        return _item("LLM08", title, "covered", ["no rag layer: no vector store to attack"])
    deny = spec.access.default == "deny"
    scoped = any(r.sources for r in spec.access.roles)
    cites = spec.rag.require_citations
    evidence = [
        _flag(deny, "access.default is deny", "access.default is allow"),
        _flag(scoped, "roles limit which sources they may read", "no role limits sources"),
        _flag(cites, "citations are required", "citations are not required"),
    ]
    if not deny:
        return _item(
            "LLM08",
            title,
            "open",
            evidence,
            "Set access.default to deny and list the sources each role may read.",
        )
    if scoped and cites:
        return _item("LLM08", title, "covered", evidence)
    return _item(
        "LLM08",
        title,
        "partial",
        evidence,
        "Give each role an explicit sources list and set rag.require_citations to true.",
    )


def _llm09(spec: KeelSpec) -> AuditItem:
    title = "Misinformation"
    quality = _has_quality(spec)
    cites = spec.rag is not None and spec.rag.require_citations
    evidence = [
        _flag(
            quality, f"{len(spec.evals.quality)} quality suite(s) in the gate", "no quality suite"
        ),
        _flag(
            cites,
            "answers must cite retrieved sources",
            "no required citations (no rag layer, or require_citations is false)",
        ),
    ]
    if quality and cites:
        return _item("LLM09", title, "covered", evidence)
    if quality:
        return _item(
            "LLM09", title, "partial", evidence, "Ground answers with rag and require citations."
        )
    if cites:
        return _item("LLM09", title, "partial", evidence, "Add a quality suite.")
    return _item(
        "LLM09", title, "open", evidence, "Add a quality suite and ground answers in cited sources."
    )


def _llm10(spec: KeelSpec) -> AuditItem:
    title = "Unbounded Consumption"
    cr = spec.cache_router
    budget = cr.budget_usd_per_day is not None
    rate = cr.rate_limit_per_minute is not None
    evidence = [
        _flag(budget, f"budget {cr.budget_usd_per_day} USD per day", "no daily budget"),
        _flag(rate, f"rate limit {cr.rate_limit_per_minute} per minute", "no rate limit"),
        f"model timeout {spec.model.timeout_s:g}s, {spec.model.max_retries} retries",
        f"cache: {cr.cache}",
    ]
    if budget and rate:
        return _item("LLM10", title, "covered", evidence)
    if budget:
        return _item("LLM10", title, "partial", evidence, "Set cache_router.rate_limit_per_minute.")
    if rate:
        return _item("LLM10", title, "partial", evidence, "Set cache_router.budget_usd_per_day.")
    return _item(
        "LLM10",
        title,
        "open",
        evidence,
        "Set cache_router.budget_usd_per_day and rate_limit_per_minute.",
    )


_LLM_CHECKS: tuple[Callable[[KeelSpec], AuditItem], ...] = (
    _llm01,
    _llm02,
    _llm03,
    _llm04,
    _llm05,
    _llm06,
    _llm07,
    _llm08,
    _llm09,
    _llm10,
)


# ---------------------------------------------------------------- agentic checks for tools


def _agt01(spec: KeelSpec) -> AuditItem:
    title = "Tool scope follows roles"
    if not spec.tools:
        return _item("AGT01", title, "covered", ["the app declares no tools"])
    deny = spec.access.default == "deny"
    granted = {t for r in spec.access.roles for t in r.tools}
    ungranted = sorted(t.name for t in spec.tools if t.name not in granted)
    evidence = [
        _flag(deny, "access.default is deny", "access.default is allow"),
        f"tools granted to at least one role: {', '.join(sorted(granted)) or 'none'}",
    ]
    if ungranted:
        evidence.append(f"declared but granted to no role: {', '.join(ungranted)}")
    if not deny:
        return _item(
            "AGT01", title, "open", evidence, "Set access.default to deny and grant tools per role."
        )
    if ungranted:
        return _item(
            "AGT01", title, "partial", evidence, "Remove tools nobody uses or grant them to a role."
        )
    return _item("AGT01", title, "covered", evidence)


def _agt02(spec: KeelSpec) -> AuditItem:
    title = "Human approval for risky tools"
    if not spec.tools:
        return _item("AGT02", title, "covered", ["the app declares no tools"])
    approved = [t.name for t in spec.tools if t.requires_approval]
    evidence = [f"{len(approved)} of {len(spec.tools)} tool(s) need approval"]
    if len(approved) == len(spec.tools):
        return _item("AGT02", title, "covered", evidence)
    advice = "Set requires_approval on every tool that changes state or sends data out."
    return _item("AGT02", title, "partial", evidence, advice)


def _agt03(spec: KeelSpec) -> AuditItem:
    title = "Provenance: untrusted content cannot trigger tools"
    if not spec.tools:
        return _item("AGT03", title, "covered", ["the app declares no tools"])
    evidence = [
        "the runtime blocks a tool call when untrusted text is in context, unless approved",
        _flag(
            spec.rag is not None,
            "suspicious retrieved chunks are labelled untrusted",
            "no rag layer; tool output is still labelled untrusted",
        ),
    ]
    return _item("AGT03", title, "covered", evidence)


def _agt04(spec: KeelSpec) -> AuditItem:
    title = "Traceable actions"
    exporter = spec.observability.exporter
    evidence = [
        f"observability.exporter is {exporter}",
        "every request writes a trace and a tamper-evident audit entry",
    ]
    if exporter == "none":
        return _item(
            "AGT04", title, "partial", evidence, "Use the console or otlp exporter in production."
        )
    return _item("AGT04", title, "covered", evidence)


_AGENTIC_CHECKS: tuple[Callable[[KeelSpec], AuditItem], ...] = (_agt01, _agt02, _agt03, _agt04)

__all__ = ["AuditItem", "AuditReport", "AuditStatus", "audit_spec"]
