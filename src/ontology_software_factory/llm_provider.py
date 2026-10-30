"""Provider-neutral LLM boundary with an OpenAI Responses API implementation.

The core is deliberately dependency-light: tests can inject a small fake client, and
production code can install the `llm` extra to use the official OpenAI Python SDK.
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from dataclasses import asdict, dataclass
from typing import Any, Callable, Protocol

LOGGER = logging.getLogger(__name__)


class LLMProviderError(RuntimeError):
    """A bounded, sanitized error from the model-provider boundary."""

    def __init__(self, message: str, *, retryable: bool = False, attempts: int = 1):
        super().__init__(message)
        self.retryable = retryable
        self.attempts = attempts


@dataclass(frozen=True)
class LLMRequest:
    instructions: str
    input: str
    model: str | None = None
    timeout_seconds: float | None = None
    max_output_tokens: int = 1600
    metadata: dict[str, str] | None = None


@dataclass(frozen=True)
class LLMResponse:
    provider: str
    model: str
    response_id: str | None
    output_text: str
    latency_ms: int
    usage: dict[str, int]
    attempt_count: int = 1

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class LLMProvider(Protocol):
    def generate(self, request: LLMRequest) -> LLMResponse: ...


class OpenAIResponsesProvider:
    """Real LLM provider backed by `client.responses.create`.

    API keys are read from `OPENAI_API_KEY` by the official SDK and never included in
    logs. The adapter sets SDK retries to zero, then applies one explicit bounded policy
    so retry count and latency are visible to the caller.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 45.0,
        max_retries: int = 2,
        client: Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        random_fn: Callable[[], float] = random.random,
        usage_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-6.1-sol")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, min(max_retries, 5))
        self._sleeper = sleeper
        self._random = random_fn
        self._usage_sink = usage_sink
        if client is not None:
            self.client = client
        else:
            key = api_key or os.getenv("OPENAI_API_KEY")
            if not key:
                raise LLMProviderError(
                    "OPENAI_API_KEY is not set; configure it in the process environment.",
                    retryable=False,
                )
            try:
                from openai import OpenAI  # type: ignore[import-not-found]
            except ImportError as exc:
                raise LLMProviderError(
                    "OpenAI SDK is not installed. Run: pip install -e '.[llm]'"
                ) from exc
            self.client = OpenAI(api_key=key, timeout=timeout_seconds, max_retries=0)

    def generate(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self.model
        timeout = request.timeout_seconds or self.timeout_seconds
        started = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                response = self.client.responses.create(
                    model=model,
                    instructions=request.instructions,
                    input=request.input,
                    max_output_tokens=request.max_output_tokens,
                    timeout=timeout,
                    metadata=request.metadata or {},
                    store=False,
                )
                latency_ms = int((time.perf_counter() - started) * 1000)
                usage_obj = getattr(response, "usage", None)
                usage = {
                    "input_tokens": int(getattr(usage_obj, "input_tokens", 0) or 0),
                    "output_tokens": int(getattr(usage_obj, "output_tokens", 0) or 0),
                    "total_tokens": int(getattr(usage_obj, "total_tokens", 0) or 0),
                }
                result = LLMResponse(
                    provider="openai-responses",
                    model=str(getattr(response, "model", model) or model),
                    response_id=getattr(response, "id", None),
                    output_text=str(getattr(response, "output_text", "") or ""),
                    latency_ms=latency_ms,
                    usage=usage,
                    attempt_count=attempt,
                )
                self._emit_usage(request, result)
                LOGGER.info(
                    "llm.request.completed provider=%s model=%s response_id=%s latency_ms=%d "
                    "attempt=%d input_tokens=%d output_tokens=%d",
                    result.provider, result.model, result.response_id, latency_ms, attempt,
                    usage["input_tokens"], usage["output_tokens"],
                )
                return result
            except Exception as exc:  # SDK error types vary across compatible transports
                last_error = exc
                retryable = self._is_retryable(exc)
                LOGGER.warning(
                    "llm.request.failed provider=openai-responses model=%s attempt=%d "
                    "retryable=%s error_type=%s",
                    model, attempt, retryable, type(exc).__name__,
                )
                if not retryable or attempt > self.max_retries:
                    raise LLMProviderError(
                        f"LLM request failed ({type(exc).__name__}); details were omitted from logs.",
                        retryable=retryable,
                        attempts=attempt,
                    ) from exc
                # Exponential backoff with jitter; bounded by retry count.
                delay = min(8.0, 0.5 * (2 ** (attempt - 1))) * (0.75 + self._random() * 0.5)
                self._sleeper(delay)
        raise LLMProviderError("LLM request failed.", retryable=True) from last_error

    def generate_structured(
        self,
        request: LLMRequest,
        *,
        schema_name: str,
        schema: dict[str, Any],
    ) -> tuple[dict[str, Any], LLMResponse]:
        """Call Responses API with strict JSON Schema, then validate locally as defense in depth."""
        model = request.model or self.model
        timeout = request.timeout_seconds or self.timeout_seconds
        started = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                response = self.client.responses.create(
                    model=model,
                    instructions=request.instructions,
                    input=request.input,
                    max_output_tokens=request.max_output_tokens,
                    timeout=timeout,
                    metadata=request.metadata or {},
                    store=False,
                    text={"format": {"type": "json_schema", "name": schema_name,
                                     "schema": schema, "strict": True}},
                )
                raw = str(getattr(response, "output_text", "") or "")
                parsed = json.loads(raw)
                try:
                    from jsonschema import validate
                    validate(instance=parsed, schema=schema)
                except ImportError:
                    # This project declares jsonschema as a base dependency; the fallback
                    # keeps the adapter importable in constrained standalone tests.
                    if not isinstance(parsed, dict):
                        raise ValueError("Structured response must be a JSON object")
                meta = LLMResponse(
                    provider="openai-responses", model=str(getattr(response, "model", model) or model),
                    response_id=getattr(response, "id", None), output_text=raw,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    usage=self._usage(getattr(response, "usage", None)), attempt_count=attempt,
                )
                self._emit_usage(request, meta)
                LOGGER.info(
                    "llm.structured.completed model=%s response_id=%s latency_ms=%d attempt=%d",
                    meta.model, meta.response_id, meta.latency_ms, attempt,
                )
                return parsed, meta
            except Exception as exc:
                last_error = exc
                retryable = self._is_retryable(exc)
                # JSON/schema errors are deterministic and should not be blindly retried.
                if isinstance(exc, (json.JSONDecodeError, ValueError)) or type(exc).__module__.startswith("jsonschema"):
                    retryable = False
                LOGGER.warning(
                    "llm.structured.failed model=%s attempt=%d retryable=%s error_type=%s",
                    model, attempt, retryable, type(exc).__name__,
                )
                if not retryable or attempt > self.max_retries:
                    raise LLMProviderError(
                        f"Structured LLM request failed ({type(exc).__name__}); details omitted.",
                        retryable=retryable, attempts=attempt,
                    ) from exc
                self._sleeper(min(8.0, 0.5 * (2 ** (attempt - 1))) * (0.75 + self._random() * 0.5))
        raise LLMProviderError("Structured LLM request failed.", retryable=True) from last_error

    def _emit_usage(self, request: LLMRequest, response: LLMResponse) -> None:
        """Send a sanitized usage event to an optional caller-owned ledger sink."""
        if self._usage_sink is None:
            return
        metadata = request.metadata or {}
        event = {
            "occurredAt": datetime.now(timezone.utc).isoformat(),
            "provider": response.provider,
            "model": response.model,
            "responseId": response.response_id,
            "latencyMs": response.latency_ms,
            "attemptCount": response.attempt_count,
            "inputTokens": response.usage.get("input_tokens", 0),
            "outputTokens": response.usage.get("output_tokens", 0),
            "runId": metadata.get("run_id"),
            "stageId": metadata.get("stage_id"),
        }
        try:
            self._usage_sink(event)
        except Exception as exc:  # Telemetry must not turn a successful model response into a failed task.
            LOGGER.warning("llm.usage_sink.failed error_type=%s", type(exc).__name__)

    @staticmethod
    def _usage(usage_obj: Any | None) -> dict[str, int]:
        return {
            "input_tokens": int(getattr(usage_obj, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage_obj, "output_tokens", 0) or 0),
            "total_tokens": int(getattr(usage_obj, "total_tokens", 0) or 0),
        }

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        if status is not None:
            return int(status) in {408, 409, 429} or int(status) >= 500
        name = type(exc).__name__.lower()
        return any(part in name for part in ("timeout", "connection", "temporarilyunavailable", "ratelimit"))


class FakeLLMProvider:
    """Deterministic local provider for unit tests and UI demos; never calls a network."""

    def __init__(self, output_text: str = "Local fake provider response") -> None:
        self.output_text = output_text
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse("fake", request.model or "fake-model", "fake-response-1",
                           self.output_text, 0, {"input_tokens": 0, "output_tokens": 0,
                                                 "total_tokens": 0}, 1)
