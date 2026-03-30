from __future__ import annotations

import json
import socket
from time import perf_counter
from typing import Any, Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ProviderTransientError
from kycortex_agents.providers._error_classifier import is_retryable_http_status
from kycortex_agents.providers.base import BaseLLMProvider


class OllamaProvider(BaseLLMProvider):
    """Ollama-backed provider implementation for local or remote open-source models."""

    def __init__(
        self,
        config: KYCortexConfig,
        request_opener: Optional[Callable[..., Any]] = None,
    ):
        self.config = config
        self._request_opener = request_opener or urlopen
        self._last_call_metadata: Optional[dict[str, Any]] = None

    def _endpoint(self) -> str:
        base_url = (self.config.base_url or "").rstrip("/")
        return f"{base_url}/api/generate"

    def _health_endpoint(self) -> str:
        base_url = (self.config.base_url or "").rstrip("/")
        return f"{base_url}/api/tags"

    def _health_check_timeout(self) -> float:
        return min(self.config.timeout_seconds, 5.0)

    def _read_health_payload(self) -> dict[str, Any]:
        timeout_seconds = self._health_check_timeout()
        request = Request(self._health_endpoint(), method="GET")
        try:
            with self._request_opener(request, timeout=timeout_seconds) as response:
                raw_payload = response.read().decode("utf-8")
        except HTTPError as exc:
            self._last_call_metadata = None
            error_type = ProviderTransientError if is_retryable_http_status(exc.code) else AgentExecutionError
            raise error_type(
                f"Ollama health check failed at {self.config.base_url} with HTTP {exc.code}"
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            self._last_call_metadata = None
            raise ProviderTransientError(
                f"Ollama server is not responding at {self.config.base_url} (health check timed out after {timeout_seconds:g} seconds)"
            ) from exc
        except (URLError, OSError) as exc:
            self._last_call_metadata = None
            raise ProviderTransientError(
                f"Ollama server is not responding at {self.config.base_url}"
            ) from exc
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            self._last_call_metadata = None
            raise AgentExecutionError(
                f"Ollama health check returned an invalid JSON response at {self.config.base_url}"
            ) from exc
        if not isinstance(payload, dict):
            self._last_call_metadata = None
            raise AgentExecutionError(
                f"Ollama health check returned an invalid payload shape at {self.config.base_url}"
            )
        return payload

    def _ensure_server_reachable(self) -> None:
        self._read_health_payload()

    def _model_is_available(self, available_model_name: str) -> bool:
        configured_model = self.config.llm_model
        return available_model_name == configured_model or available_model_name.startswith(f"{configured_model}:")

    def health_check(self) -> dict[str, Any]:
        started_at = perf_counter()
        payload = self._read_health_payload()
        completed_at = perf_counter()
        model_entries = payload.get("models", [])
        model_names: list[str] = []
        for entry in model_entries:
            if not isinstance(entry, dict):
                continue
            model_name = entry.get("name")
            if isinstance(model_name, str):
                model_names.append(model_name)
        model_ready = any(self._model_is_available(model_name) for model_name in model_names)
        if not model_ready:
            return {
                "provider": self.config.llm_provider,
                "model": self.config.llm_model,
                "status": "failing",
                "active_check": True,
                "retryable": False,
                "backend_reachable": True,
                "model_ready": False,
                "base_url": self.config.base_url,
                "error_type": "AgentExecutionError",
                "error_message": (
                    f"Ollama health check did not confirm configured model '{self.config.llm_model}'"
                ),
                "timeout_seconds": round(self._health_check_timeout(), 6),
                "latency_ms": round((completed_at - started_at) * 1000, 3),
            }
        return {
            "provider": self.config.llm_provider,
            "model": self.config.llm_model,
            "status": "healthy",
            "active_check": True,
            "backend_reachable": True,
            "model_ready": True,
            "base_url": self.config.base_url,
            "timeout_seconds": round(self._health_check_timeout(), 6),
            "latency_ms": round((completed_at - started_at) * 1000, 3),
        }

    def _build_payload(self, system_prompt: str, user_message: str) -> dict[str, Any]:
        options: dict[str, Any] = {
            "temperature": self.config.temperature,
        }
        if self.config.ollama_num_ctx is not None:
            options["num_ctx"] = self.config.ollama_num_ctx
        return {
            "model": self.config.llm_model,
            "system": system_prompt,
            "prompt": user_message,
            "stream": False,
            "options": options,
        }

    def _extract_content(self, payload: dict[str, Any]) -> str:
        content = payload.get("response")
        if not content:
            raise AgentExecutionError("Ollama provider returned an empty response")
        return content

    def generate(self, system_prompt: str, user_message: str) -> str:
        self._ensure_server_reachable()
        body = json.dumps(self._build_payload(system_prompt, user_message)).encode("utf-8")
        request = Request(
            self._endpoint(),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._request_opener(request, timeout=self.config.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            self._last_call_metadata = None
            error_type = ProviderTransientError if is_retryable_http_status(exc.code) else AgentExecutionError
            raise error_type(
                f"Ollama API request failed with HTTP {exc.code} while calling model '{self.config.llm_model}'"
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            self._last_call_metadata = None
            raise ProviderTransientError(
                f"Ollama request to model '{self.config.llm_model}' timed out after {self.config.timeout_seconds:g} seconds"
            ) from exc
        except (URLError, OSError) as exc:
            self._last_call_metadata = None
            raise ProviderTransientError(
                f"Ollama server is not responding at {self.config.base_url}"
            ) from exc
        except json.JSONDecodeError as exc:
            self._last_call_metadata = None
            raise AgentExecutionError(
                f"Ollama API returned an invalid JSON response for model '{self.config.llm_model}'"
            ) from exc
        self._last_call_metadata = self._extract_metadata(payload)
        return self._extract_content(payload)

    def _extract_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        prompt_eval_count = payload.get("prompt_eval_count")
        eval_count = payload.get("eval_count")
        total_tokens = None
        if prompt_eval_count is not None or eval_count is not None:
            total_tokens = (prompt_eval_count or 0) + (eval_count or 0)
        total_duration_ns = payload.get("total_duration")
        load_duration_ns = payload.get("load_duration")
        return {
            "requested_max_tokens": self.config.max_tokens,
            "done_reason": payload.get("done_reason"),
            "usage": {
                "input_tokens": prompt_eval_count,
                "output_tokens": eval_count,
                "total_tokens": total_tokens,
            },
            "timing": {
                "total_duration_ms": round(total_duration_ns / 1_000_000, 3) if isinstance(total_duration_ns, (int, float)) else None,
                "load_duration_ms": round(load_duration_ns / 1_000_000, 3) if isinstance(load_duration_ns, (int, float)) else None,
            },
        }

    def get_last_call_metadata(self) -> Optional[dict[str, Any]]:
        if self._last_call_metadata is None:
            return None
        return dict(self._last_call_metadata)