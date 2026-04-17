from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace as dataclass_replace
from time import perf_counter
from typing import Any, Optional

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ProviderTransientError
from kycortex_agents.providers._error_classifier import is_transient_provider_exception
from kycortex_agents.providers.base import BaseLLMProvider
from kycortex_agents.providers.model_capabilities import get_capabilities


def _is_unsupported_temperature_error(exc: BaseException) -> bool:
    """Return True when the OpenAI API rejects the temperature parameter."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body if "param" in body else body.get("error", {})
        if isinstance(err, dict):
            return err.get("param") == "temperature" and err.get("code") == "unsupported_value"
    msg = str(exc).lower()
    return "temperature" in msg and "unsupported" in msg


class OpenAIProvider(BaseLLMProvider):
    """OpenAI-backed provider implementation for chat completion models."""

    def __init__(self, config: KYCortexConfig, client: Optional[Any] = None):
        self.config = config
        self._client = client
        self._last_call_metadata: Optional[dict[str, Any]] = None
        self._capabilities = get_capabilities(config.llm_provider, config.llm_model)

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.config.api_key)
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
        timeout_seconds = self._health_check_timeout()
        started_at = perf_counter()
        try:
            client = self._get_client()
            models_api = getattr(client, "models", None)
            list_models = getattr(models_api, "list", None)
            if not callable(list_models):
                return super().health_check()
            models_payload = list_models(timeout=timeout_seconds)
        except Exception as exc:
            self._last_call_metadata = None
            if is_transient_provider_exception(exc):
                raise ProviderTransientError("OpenAI provider health check failed") from exc
            raise AgentExecutionError("OpenAI provider health check was rejected") from exc

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
                    f"OpenAI provider health check did not confirm configured model '{self.config.llm_model}'"
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

    def _build_messages(self, system_prompt: str, user_message: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

    def _extract_content(self, response: Any) -> str:
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, KeyError, TypeError) as exc:
            raise AgentExecutionError("OpenAI provider returned an invalid response payload") from exc
        if not content:
            raise AgentExecutionError("OpenAI provider returned an empty response")
        return content

    _REASONING_TOKEN_MULTIPLIER = 4

    def _effective_max_tokens(self) -> int:
        if self._capabilities.is_reasoning_model:
            return self.config.max_tokens * self._REASONING_TOKEN_MULTIPLIER
        return self.config.max_tokens

    def _build_create_kwargs(self, system_prompt: str, user_message: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.config.llm_model,
            self._capabilities.max_tokens_param: self._effective_max_tokens(),
            "timeout": self.config.timeout_seconds,
            "messages": self._build_messages(system_prompt, user_message),
        }
        if self._capabilities.supports_temperature:
            kwargs["temperature"] = self.config.temperature
        return kwargs

    def generate(self, system_prompt: str, user_message: str) -> str:
        try:
            client = self._get_client()
            kwargs = self._build_create_kwargs(system_prompt, user_message)
            response = client.chat.completions.create(**kwargs)
        except Exception as exc:
            if (
                self._capabilities.supports_temperature
                and _is_unsupported_temperature_error(exc)
            ):
                self._capabilities = dataclass_replace(self._capabilities, supports_temperature=False)
                return self.generate(system_prompt, user_message)
            self._last_call_metadata = None
            if is_transient_provider_exception(exc):
                raise ProviderTransientError("OpenAI provider failed to call the model API") from exc
            raise AgentExecutionError("OpenAI provider rejected the model API request") from exc
        self._last_call_metadata = self._extract_metadata(response)
        return self._extract_content(response)

    def _extract_metadata(self, response: Any) -> Optional[dict[str, Any]]:
        usage = getattr(response, "usage", None)
        metadata: dict[str, Any] = {
            "requested_max_tokens": self._effective_max_tokens(),
            "finish_reason": None,
        }
        try:
            metadata["finish_reason"] = getattr(response.choices[0], "finish_reason", None)
        except (AttributeError, IndexError, KeyError, TypeError):
            metadata["finish_reason"] = None
        if usage is None:
            return metadata
        metadata["usage"] = {
            "input_tokens": getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
        return metadata

    def get_last_call_metadata(self) -> Optional[dict[str, Any]]:
        if self._last_call_metadata is None:
            return None
        return dict(self._last_call_metadata)