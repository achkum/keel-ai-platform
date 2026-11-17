"""Rule based guardrails for local mode.

These are heuristics. They catch the obvious cases and keep the pipeline honest in tests and
demos; a production deployment can swap in a model based classifier through the same port.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Sequence

from keel_core.errors import KeelError
from keel_core.ports import GuardrailPort, GuardrailResult

# ---------------------------------------------------------------- injection patterns

INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"\b(?:ignore|disregard|forget|override)\b.{0,30}\b(?:previous|prior|above|earlier|all|any|your)\b"
        r".{0,30}\b(?:instructions?|rules?|prompts?|guidelines?|policy|policies)\b",
        r"\b(?:reveal|show|print|repeat|leak|output)\b.{0,30}\b(?:system|hidden|initial)\b"
        r".{0,10}\b(?:prompt|instructions?|message)\b",
        r"\byou are now\b",
        r"\bnew instructions?\s*:",
        r"\b(?:developer|god|dan) mode\b",
        r"\bdo anything now\b",
        r"\bjailbreak",
        r"\bact as\b.{0,40}\bwithout (?:any )?(?:restrictions?|limits?|rules?|filters?)\b",
        r"\bpretend (?:that )?you (?:have no|are not bound)\b",
        r"<\s*/?\s*(?:system|assistant)\s*>",
    )
)


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).lower().split())


def looks_like_injection(text: str) -> bool:
    """True if the text contains a planted-instruction pattern. Shared with retrieval."""
    return _first_injection_match(text) is not None


def _first_injection_match(text: str) -> str | None:
    norm = _normalize(text)
    for pattern in INJECTION_PATTERNS:
        if pattern.search(norm):
            return pattern.pattern[:40]
    return None


# ---------------------------------------------------------------- PII


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        total += n
    return total % 10 == 0


def _iban_ok(raw: str) -> bool:
    iban = raw.replace(" ", "").upper()
    if not 15 <= len(iban) <= 34:
        return False
    rearranged = iban[4:] + iban[:4]
    number = "".join(str(int(c, 36)) for c in rearranged)
    return int(number) % 97 == 1


def _card_ok(raw: str) -> bool:
    digits = re.sub(r"\D", "", raw)
    return 13 <= len(digits) <= 19 and _luhn_ok(digits)


def _personnummer_ok(raw: str) -> bool:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 12:
        digits = digits[2:]
    return len(digits) == 10 and _luhn_ok(digits) and 1 <= int(digits[2:4]) <= 12


def _phone_ok(raw: str) -> bool:
    digits = re.sub(r"\D", "", raw)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw.strip()):
        return False
    return 9 <= len(digits) <= 15


_PII_RULES: tuple[tuple[str, re.Pattern[str], Callable[[str], bool]], ...] = (
    (
        "iban",
        re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b"),
        _iban_ok,
    ),
    ("credit_card", re.compile(r"(?<![\w-])\d(?:[ -]?\d){12,18}(?![\w-])"), _card_ok),
    ("us_ssn", re.compile(r"(?<![\w-])\d{3}-\d{2}-\d{4}(?![\w-])"), lambda _s: True),
    (
        "personnummer",
        re.compile(r"(?<![\w-])(?:\d{2})?\d{6}[-+]?\d{4}(?![\w-])"),
        _personnummer_ok,
    ),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"), lambda _s: True),
    ("phone", re.compile(r"(?<![\w@])\+?\(?\d[\d\s().-]{7,18}\d(?!\w)"), _phone_ok),
)


class PiiGuardrail:
    """Redacts emails, phone numbers, card numbers (Luhn), IBANs, Swedish personnummer, US SSNs.

    Never blocks: the text continues with ``[REDACTED:<kind>]`` in place of each match.
    """

    name = "pii"

    def inspect(self, text: str) -> GuardrailResult:
        counts: Counter[str] = Counter()
        for kind, pattern, valid in _PII_RULES:

            def _sub(
                match: re.Match[str], kind: str = kind, valid: Callable[[str], bool] = valid
            ) -> str:
                if not valid(match.group(0)):
                    return match.group(0)
                counts[kind] += 1
                return f"[REDACTED:{kind}]"

            text = pattern.sub(_sub, text)
        findings = tuple(f"pii:{k} x{n}" for k, n in sorted(counts.items()))
        return GuardrailResult(True, text, findings)


class PromptInjectionGuardrail:
    """Blocks text that matches known instruction-override patterns."""

    name = "prompt_injection"

    def inspect(self, text: str) -> GuardrailResult:
        hit = _first_injection_match(text)
        if hit is None:
            return GuardrailResult(True, text)
        return GuardrailResult(False, text, ("prompt_injection: instruction-override pattern",))


_TOXIC_WORDS = (
    "kill yourself",
    "fuck you",
    "piece of shit",
    "idiot",
    "moron",
    "scumbag",
    "bastard",
    "retard",
)
_TOXIC_RE = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in _TOXIC_WORDS) + r")s?\b")


class ToxicityGuardrail:
    """Blocks text with words from a small built-in list."""

    name = "toxicity"

    def inspect(self, text: str) -> GuardrailResult:
        if _TOXIC_RE.search(_normalize(text)):
            return GuardrailResult(False, text, ("toxicity: abusive language",))
        return GuardrailResult(True, text)


class TopicGuardrail:
    """Placeholder: passes everything. Topic rules are not configurable in the spec yet."""

    name = "topic"

    def inspect(self, text: str) -> GuardrailResult:
        return GuardrailResult(True, text, ("topic: not configurable yet, passed",))


class SchemaGuardrail:
    """Placeholder: passes everything. Output schemas are not configurable in the spec yet."""

    name = "schema"

    def inspect(self, text: str) -> GuardrailResult:
        return GuardrailResult(True, text, ("schema: not configurable yet, passed",))


_FACTORIES: dict[str, Callable[[], GuardrailPort]] = {
    "pii": PiiGuardrail,
    "prompt_injection": PromptInjectionGuardrail,
    "toxicity": ToxicityGuardrail,
    "topic": TopicGuardrail,
    "schema": SchemaGuardrail,
}


def guardrails_for(names: Sequence[str]) -> list[GuardrailPort]:
    """Build guardrails for spec check names, keeping the spec's order."""
    out: list[GuardrailPort] = []
    for name in names:
        factory = _FACTORIES.get(name)
        if factory is None:
            raise KeelError(f"unknown guardrail check '{name}'")
        out.append(factory())
    return out
