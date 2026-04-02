from __future__ import annotations

import os
from collections.abc import Iterable
from time import perf_counter
from typing import Any, Optional

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ProviderTransientError
from kycortex_agents.providers._error_classifier import is_transient_provider_exception
from kycortex_agents.providers.base import BaseLLMProvider


class AnthropicProvider(BaseLLMProvider):
    """Anthropic-backed provider implementation for Claude message models."""

    def __init__(self, config: KYCortexConfig, client: Optional[Any] = None):
        self.config = config
        self._client = client
        self._last_call_metadata: Optional[dict[str, Any]] = None

    def _base_url(self) -> Optional[str]:
        base_url = self.config.base_url or os.environ.get("ANTHROPIC_BASE_URL")
        if not isinstance(base_url, str) or not base_url.strip():
            return None
        normalized_base_url = base_url.strip().rstrip("/")
        if normalized_base_url.endswith("/v1"):
            normalized_base_url = normalized_base_url[:-3]
        return normalized_base_url or None

    def _get_client(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic  # type: ignore[import-not-found]

            client_kwargs: dict[str, Any] = {"api_key": self.config.api_key}
            base_url = self._base_url()
            if base_url is not None:
                client_kwargs["base_url"] = base_url
            self._client = Anthropic(**client_kwargs)
        return self._client

    def _health_check_timeout(self) -> float:
        return min(self.config.timeout_seconds, 5.0)

    def _listed_model_ids(self, payload: Any) -> set[str]:
        data = getattr(payload, "data", payload)
        if isinstance(data, dict):
            entries: Iterable[Any] = data.get("data", [])
        elif isinstance(data, Iterable) and not isinstance(data, (str, bytes)):
            entries = data
        else:
            entries = ()

        model_ids: set[str] = set()
        for entry in entries:
            if isinstance(entry, str) and entry:
                model_ids.add(entry)
                continue
            entry_id = getattr(entry, "id", None)
            if isinstance(entry_id, str) and entry_id:
                model_ids.add(entry_id)
                continue
            if isinstance(entry, dict):
                dict_id = entry.get("id") or entry.get("name")
                if isinstance(dict_id, str) and dict_id:
                    model_ids.add(dict_id)
        return model_ids

    def health_check(self) -> dict[str, Any]:
        client = self._get_client()
        models_api = getattr(client, "models", None)
        list_models = getattr(models_api, "list", None)
        if not callable(list_models):
            return super().health_check()

        timeout_seconds = self._health_check_timeout()
        started_at = perf_counter()
        try:
            models_payload = list_models(timeout=timeout_seconds)
        except Exception as exc:
            self._last_call_metadata = None
            if is_transient_provider_exception(exc):
                raise ProviderTransientError("Anthropic provider health check failed") from exc
            raise AgentExecutionError("Anthropic provider health check was rejected") from exc

        completed_at = perf_counter()
        model_ids = self._listed_model_ids(models_payload)
        if self.config.llm_model not in model_ids:
            return {
                "provider": self.config.llm_provider,
                "model": self.config.llm_model,
                "status": "failing",
                "active_check": True,
                "retryable": False,
                "backend_reachable": True,
                "model_ready": False,
                "error_type": "AgentExecutionError",
                "error_message": (
                    f"Anthropic provider health check did not confirm configured model '{self.config.llm_model}'"
                ),
                "timeout_seconds": round(timeout_seconds, 6),
                "latency_ms": round((completed_at - started_at) * 1000, 3),
            }
        return {
            "provider": self.config.llm_provider,
            "model": self.config.llm_model,
            "status": "healthy",
            "active_check": True,
            "backend_reachable": True,
            "model_ready": True,
            "timeout_seconds": round(timeout_seconds, 6),
            "latency_ms": round((completed_at - started_at) * 1000, 3),
        }

    def _extract_content(self, response: Any) -> str:
        try:
            content_blocks = response.content
        except AttributeError as exc:
            raise AgentExecutionError("Anthropic provider returned an invalid response payload") from exc

        for block in content_blocks:
            text = getattr(block, "text", None)
            if getattr(block, "type", None) == "text" and text:
                return text

        raise AgentExecutionError("Anthropic provider returned an empty response")

    def generate(self, system_prompt: str, user_message: str) -> str:
        client = self._get_client()
        try:
            response = client.messages.create(
                model=self.config.llm_model,
                system=system_prompt,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                timeout=self.config.timeout_seconds,
                messages=[{"role": "user", "content": user_message}],
            )
        except Exception as exc:
            self._last_call_metadata = None
            if is_transient_provider_exception(exc):
                raise ProviderTransientError("Anthropic provider failed to call the model API") from exc
            raise AgentExecutionError("Anthropic provider rejected the model API request") from exc
        self._last_call_metadata = self._extract_metadata(response)
        return self._extract_content(response)

    def _extract_metadata(self, response: Any) -> Optional[dict[str, Any]]:
        usage = getattr(response, "usage", None)
        metadata: dict[str, Any] = {
            "requested_max_tokens": self.config.max_tokens,
            "stop_reason": getattr(response, "stop_reason", None),
            "stop_type": getattr(response, "stop_type", None),
        }
        if usage is None:
            return metadata
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        cache_creation_input_tokens = getattr(usage, "cache_creation_input_tokens", None)
        cache_read_input_tokens = getattr(usage, "cache_read_input_tokens", None)
        total_tokens = None
        if input_tokens is not None or output_tokens is not None:
            total_tokens = (input_tokens or 0) + (output_tokens or 0)
        metadata["usage"] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cache_creation_input_tokens": cache_creation_input_tokens,
            "cache_read_input_tokens": cache_read_input_tokens,
        }
        return metadata

    def get_last_call_metadata(self) -> Optional[dict[str, Any]]:
        if self._last_call_metadata is None:
            return None
        return dict(self._last_call_metadata)