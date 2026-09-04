"""Optional LLM advisor; rules remain the source of truth and default fallback."""

import hashlib
import json
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx

from backend.domain.enums import ActionType, FailureCategory, ReasonCode

from .cache import SQLiteResponseCache
from .contracts import LLMClassification, LLMDecision


class LLMProvider(Protocol):
    def complete(self, prompt: str, timeout_seconds: float) -> str: ...


class AnthropicProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def complete(self, prompt: str, timeout_seconds: float) -> str:
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={"model": self.model, "max_tokens": 512, "temperature": 0, "messages": [{"role": "user", "content": prompt}]},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        content = response.json().get("content", [])
        return str(content[0].get("text", "")) if content else ""


@dataclass(slots=True)
class AdvisorStats:
    requests: int = 0
    schema_failures: int = 0
    ineligible_actions: int = 0
    fallbacks: int = 0
    cache_hits: int = 0
    latency_ms: list[float] = field(default_factory=list)

    def json(self) -> dict[str, object]:
        return {
            "requests": self.requests,
            "schema_failures": self.schema_failures,
            "ineligible_actions": self.ineligible_actions,
            "fallbacks": self.fallbacks,
            "cache_hits": self.cache_hits,
            "mean_latency_ms": sum(self.latency_ms) / len(self.latency_ms) if self.latency_ms else 0.0,
        }


@dataclass(frozen=True, slots=True)
class AdvisorResult:
    decision: LLMDecision
    source: str
    raw_response: dict[str, object] | None
    latency_ms: int
    cache_key: str
    fallback_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    classification: LLMClassification
    source: str
    fallback_reason: str | None = None


class LLMAdvisor:
    def __init__(
        self,
        provider: LLMProvider | Callable[[str, float], str] | None = None,
        *,
        model: str = "claude-3-5-haiku-latest",
        prompt_version: str = "v1",
        timeout_seconds: float = 8.0,
        cache: SQLiteResponseCache | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.prompt_version = prompt_version
        self.timeout_seconds = timeout_seconds
        self.cache = cache or SQLiteResponseCache(":memory:")
        self.stats = AdvisorStats()

    @classmethod
    def from_environment(cls) -> "LLMAdvisor":
        key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        model = os.getenv("LLM_MODEL", "claude-3-5-haiku-latest")
        cache_path = os.getenv("LLM_CACHE_PATH", ":memory:")
        provider = AnthropicProvider(key, model) if key else None
        return cls(provider, model=model, cache=SQLiteResponseCache(cache_path))

    def decide(
        self,
        input_snapshot: dict[str, object],
        eligible_actions: Iterable[ActionType],
        fallback: ActionType,
    ) -> AdvisorResult:
        eligible = tuple(eligible_actions)
        canonical = json.dumps(
            {"input": input_snapshot, "eligible_actions": [item.value for item in eligible]},
            sort_keys=True,
            separators=(",", ":"),
        )
        cache_key = hashlib.sha256(f"{self.model}{self.prompt_version}{canonical}".encode()).hexdigest()
        fallback_decision = LLMDecision(
            action=fallback,
            delay_minutes=0,
            confidence=0,
            reason_codes=[ReasonCode.RULE_FALLBACK, ReasonCode.LLM_UNAVAILABLE],
            rationale="Deterministic rule fallback",
        )
        if self.provider is None:
            self.stats.fallbacks += 1
            return AdvisorResult(fallback_decision, "RULE", None, 0, cache_key, "LLM_UNAVAILABLE")
        response_text = self.cache.get(cache_key)
        if response_text is not None:
            self.stats.cache_hits += 1
        prompt = self._prompt(input_snapshot, eligible)
        attempts = 0
        while attempts < 2:
            attempts += 1
            self.stats.requests += 1
            started = time.perf_counter()
            try:
                if response_text is None:
                    if callable(self.provider):
                        response_text = self.provider(prompt, self.timeout_seconds)
                    else:
                        response_text = self.provider.complete(prompt, self.timeout_seconds)
                    self.cache.put(cache_key, response_text)
                parsed = LLMDecision.model_validate_json(response_text)
                if parsed.action not in eligible:
                    self.stats.ineligible_actions += 1
                    return AdvisorResult(fallback_decision.model_copy(update={"reason_codes": [ReasonCode.LLM_INELIGIBLE_ACTION]}), "RULE", {"raw": response_text}, int((time.perf_counter() - started) * 1000), cache_key, "LLM_INELIGIBLE_ACTION")
                latency = int((time.perf_counter() - started) * 1000)
                self.stats.latency_ms.append(latency)
                return AdvisorResult(parsed, "LLM", {"cache_key": cache_key, "parsed": parsed.model_dump(mode="json")}, latency, cache_key)
            except Exception as exc:  # noqa: BLE001 - provider and schema failures share fallback behavior
                self.stats.schema_failures += 1
                response_text = None
                prompt = f"{prompt}\nReturn only valid JSON matching the schema. Validation error: {exc}"
        self.stats.fallbacks += 1
        return AdvisorResult(fallback_decision.model_copy(update={"reason_codes": [ReasonCode.LLM_SCHEMA_INVALID]}), "RULE", None, 0, cache_key, "LLM_SCHEMA_INVALID")

    def classify(self, input_snapshot: dict[str, object]) -> ClassificationResult:
        """Use the advisor only for an UNKNOWN deterministic taxonomy result."""
        fallback = LLMClassification(category=FailureCategory.UNKNOWN, rationale="Deterministic UNKNOWN fallback")
        if self.provider is None:
            self.stats.fallbacks += 1
            return ClassificationResult(fallback, "RULE", "LLM_UNAVAILABLE")
        prompt = (
            "Classify this payment failure. Return JSON with category, confidence, rationale. "
            f"Allowed categories: {[item.value for item in FailureCategory]}. Input: "
            f"{json.dumps(input_snapshot, sort_keys=True)}"
        )
        for _ in range(2):
            self.stats.requests += 1
            try:
                if callable(self.provider):
                    response = self.provider(prompt, self.timeout_seconds)
                else:
                    response = self.provider.complete(prompt, self.timeout_seconds)
                parsed = LLMClassification.model_validate_json(response)
                return ClassificationResult(parsed, "LLM")
            except Exception:  # noqa: BLE001 - classification failure must safely fall back
                self.stats.schema_failures += 1
                prompt += " Return only valid JSON matching the schema."
        self.stats.fallbacks += 1
        return ClassificationResult(fallback, "RULE", "LLM_SCHEMA_INVALID")

    @staticmethod
    def _prompt(input_snapshot: dict[str, object], eligible: tuple[ActionType, ...]) -> str:
        template = Path("agent/prompts/v1.txt").read_text(encoding="utf-8")
        return template.format(
            input_snapshot=json.dumps(input_snapshot, sort_keys=True),
            eligible_actions=json.dumps([item.value for item in eligible]),
        )


__all__ = ["AdvisorResult", "AnthropicProvider", "ClassificationResult", "LLMAdvisor"]
