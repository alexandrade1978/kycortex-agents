import sys
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ProviderConfigurationError, ProviderTransientError
from kycortex_agents.providers.anthropic_provider import AnthropicProvider
from kycortex_agents.providers.base import BaseLLMProvider
from kycortex_agents.providers.factory import create_provider, probe_provider_health
from kycortex_agents.providers.ollama_provider import OllamaProvider
from kycortex_agents.providers.openai_provider import OpenAIProvider
from kycortex_agents.providers._error_classifier import (
    extract_http_status_code,
    is_retryable_http_status,
    is_transient_provider_exception,
)
from kycortex_agents.providers import factory as provider_factory


class FakeAPIError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def build_response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def build_response_with_usage(content, prompt_tokens=10, completion_tokens=5, total_tokens=15):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        ),
    )


def build_client(
    response=None,
    error=None,
    captured_kwargs=None,
    health_response=None,
    health_error=None,
    health_captured_kwargs=None,
):
    def create(**kwargs):
        if captured_kwargs is not None:
            captured_kwargs.append(kwargs)
        if error is not None:
            raise error
        return response

    def list_models(**kwargs):
        if health_captured_kwargs is not None:
            health_captured_kwargs.append(kwargs)
        if health_error is not None:
            raise health_error
        return health_response if health_response is not None else []

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        models=SimpleNamespace(list=list_models),
    )


def build_anthropic_client(
    response=None,
    error=None,
    captured_kwargs=None,
    health_response=None,
    health_error=None,
    health_captured_kwargs=None,
):
    def create(**kwargs):
        if captured_kwargs is not None:
            captured_kwargs.append(kwargs)
        if error is not None:
            raise error
        return response

    def list_models(**kwargs):
        if health_captured_kwargs is not None:
            health_captured_kwargs.append(kwargs)
        if health_error is not None:
            raise health_error
        return health_response if health_response is not None else []

    return SimpleNamespace(
        messages=SimpleNamespace(create=create),
        models=SimpleNamespace(list=list_models),
    )


class FakeHTTPResponse:
    def __init__(self, payload: str):
        self._payload = payload

    def read(self):
        return self._payload.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def build_ollama_opener(payload=None, error=None):
    calls = 0

    def open_request(request, timeout=None):
        nonlocal calls
        current_payload = payload[min(calls, len(payload) - 1)] if isinstance(payload, list) else payload
        current_error = error[min(calls, len(error) - 1)] if isinstance(error, list) else error
        calls += 1
        if current_error is not None:
            raise current_error
        return FakeHTTPResponse(current_payload)

    return open_request


def build_http_error(url: str, code: int, reason: str) -> HTTPError:
    return HTTPError(url=url, code=code, msg=reason, hdrs=None, fp=None)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (SimpleNamespace(status_code=429), 429),
        (SimpleNamespace(code=503), 503),
        (SimpleNamespace(response=SimpleNamespace(status_code=502)), 502),
        (SimpleNamespace(status_code="429", response=SimpleNamespace(status_code="502")), None),
    ],
)
def test_extract_http_status_code_supports_multiple_exception_shapes(exc, expected):
    assert extract_http_status_code(exc) == expected


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (408, True),
        (429, True),
        (500, True),
        (599, True),
        (404, False),
    ],
)
def test_is_retryable_http_status_matches_retry_policy(status_code, expected):
    assert is_retryable_http_status(status_code) is expected


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (SimpleNamespace(), True),
        (SimpleNamespace(status_code=503), True),
        (SimpleNamespace(response=SimpleNamespace(status_code=429)), True),
        (SimpleNamespace(code=400), False),
    ],
)
def test_is_transient_provider_exception_distinguishes_deterministic_statuses(exc, expected):
    assert is_transient_provider_exception(exc) is expected


def test_create_provider_returns_openai_provider(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="openai", api_key="token")

    provider = create_provider(config)

    assert isinstance(provider, OpenAIProvider)


def test_create_provider_returns_anthropic_provider(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="anthropic", api_key="token")

    provider = create_provider(config)

    assert isinstance(provider, AnthropicProvider)


def test_create_provider_returns_ollama_provider(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama")

    provider = create_provider(config)

    assert isinstance(provider, OllamaProvider)


def test_create_provider_rejects_unknown_provider(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="unknown")

    with pytest.raises(ProviderConfigurationError, match="Unsupported LLM provider"):
        create_provider(config)


def test_create_provider_requires_runtime_credentials(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="openai", api_key="")

    with pytest.raises(ProviderConfigurationError, match="Missing API key"):
        create_provider(config)


def test_create_provider_wraps_runtime_validation_error_cause(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="anthropic", api_key="")

    with pytest.raises(ProviderConfigurationError, match="Missing API key") as exc_info:
        create_provider(config)

    assert exc_info.value.__cause__ is not None
    assert exc_info.value.__cause__.__class__.__name__ == "ConfigValidationError"


def test_create_provider_preserves_original_provider_name_in_error(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="  Unknown  ")

    with pytest.raises(ProviderConfigurationError, match="Unsupported LLM provider: unknown"):
        create_provider(config)


def test_create_provider_surfaces_provider_instantiation_failures(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="openai", api_key="token")

    class ExplodingProvider:
        def __init__(self, runtime_config):
            raise RuntimeError(f"boom for {runtime_config.llm_provider}")

    monkeypatch.setattr("kycortex_agents.providers.factory.OpenAIProvider", ExplodingProvider)

    with pytest.raises(RuntimeError, match="boom for openai"):
        create_provider(config)


def test_create_provider_accepts_ollama_default_base_url(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama")

    provider = create_provider(config)

    assert isinstance(provider, OllamaProvider)
    assert provider.config.base_url == "http://localhost:11434"


def test_probe_provider_health_returns_default_snapshot_for_providers_without_active_check(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="openai", api_key="token")

    class MinimalProvider(BaseLLMProvider):
        def generate(self, system_prompt: str, user_message: str) -> str:
            return "ok"

    monkeypatch.setattr("kycortex_agents.providers.factory.create_provider", lambda runtime_config: MinimalProvider())

    snapshot = probe_provider_health(config)

    assert snapshot["provider"] == "openai"
    assert snapshot["model"] == "gpt-4o"
    assert snapshot["status"] == "ready"
    assert snapshot["active_check"] is False
    assert snapshot["retryable"] is False
    assert snapshot["latency_ms"] >= 0


def test_probe_provider_health_wraps_transient_provider_failures(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama", llm_model="llama3")

    def create_failing_provider(runtime_config: KYCortexConfig):
        return OllamaProvider(runtime_config, request_opener=build_ollama_opener(error=OSError("down")))

    monkeypatch.setattr("kycortex_agents.providers.factory.create_provider", create_failing_provider)

    snapshot = probe_provider_health(config)

    assert snapshot["provider"] == "ollama"
    assert snapshot["model"] == "llama3"
    assert snapshot["status"] == "degraded"
    assert snapshot["active_check"] is True
    assert snapshot["retryable"] is True
    assert snapshot["error_type"] == "ProviderTransientError"
    assert "not responding" in snapshot["error_message"]
    assert snapshot["latency_ms"] >= 0


def test_probe_provider_health_wraps_deterministic_provider_failures(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama", llm_model="llama3")

    def create_failing_provider(runtime_config: KYCortexConfig):
        return OllamaProvider(
            runtime_config,
            request_opener=build_ollama_opener(
                error=build_http_error("http://localhost:11434/api/tags", 404, "Not Found")
            ),
        )

    monkeypatch.setattr("kycortex_agents.providers.factory.create_provider", create_failing_provider)

    snapshot = probe_provider_health(config)

    assert snapshot["provider"] == "ollama"
    assert snapshot["model"] == "llama3"
    assert snapshot["status"] == "failing"
    assert snapshot["active_check"] is True
    assert snapshot["retryable"] is False
    assert snapshot["error_type"] == "AgentExecutionError"
    assert "HTTP 404" in snapshot["error_message"]
    assert snapshot["latency_ms"] >= 0


def test_probe_provider_health_caches_unhealthy_snapshot_during_cooldown(tmp_path, monkeypatch):
    provider_factory._HEALTH_PROBE_CACHE.clear()
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        llm_provider="openai",
        api_key="token",
        provider_health_check_cooldown_seconds=30.0,
    )
    provider_calls: list[str] = []

    class UnhealthyProvider(BaseLLMProvider):
        def generate(self, system_prompt: str, user_message: str) -> str:
            return "ok"

        def health_check(self) -> dict[str, object]:
            provider_calls.append("health")
            raise ProviderTransientError("temporary outage")

    monkeypatch.setattr(
        "kycortex_agents.providers.factory.create_provider",
        lambda runtime_config: UnhealthyProvider(),
    )

    first_snapshot = probe_provider_health(config)
    second_snapshot = probe_provider_health(config)

    assert provider_calls == ["health"]
    assert first_snapshot["status"] == "degraded"
    assert first_snapshot["cooldown_cached"] is False
    assert first_snapshot["cooldown_remaining_seconds"] == 0.0
    assert second_snapshot["status"] == "degraded"
    assert second_snapshot["cooldown_cached"] is True
    assert second_snapshot["cooldown_remaining_seconds"] > 0


def test_probe_provider_health_does_not_cache_ready_snapshot(tmp_path, monkeypatch):
    provider_factory._HEALTH_PROBE_CACHE.clear()
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        llm_provider="openai",
        api_key="token",
        provider_health_check_cooldown_seconds=30.0,
    )
    provider_calls: list[str] = []

    class HealthyProvider(BaseLLMProvider):
        def generate(self, system_prompt: str, user_message: str) -> str:
            return "ok"

        def health_check(self) -> dict[str, object]:
            provider_calls.append("health")
            return {
                "provider": "openai",
                "model": "gpt-4o",
                "status": "healthy",
                "active_check": True,
                "retryable": False,
            }

    monkeypatch.setattr(
        "kycortex_agents.providers.factory.create_provider",
        lambda runtime_config: HealthyProvider(),
    )

    first_snapshot = probe_provider_health(config)
    second_snapshot = probe_provider_health(config)

    assert provider_calls == ["health", "health"]
    assert first_snapshot["cooldown_cached"] is False
    assert second_snapshot["cooldown_cached"] is False


def test_openai_provider_returns_content(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    provider = OpenAIProvider(config, client=build_client(response=build_response("ok")))

    result = provider.generate("system", "message")

    assert result == "ok"


def test_openai_provider_captures_usage_metadata(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    provider = OpenAIProvider(config, client=build_client(response=build_response_with_usage("ok")))

    provider.generate("system", "message")

    assert provider.get_last_call_metadata() == {
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    }


def test_openai_provider_wraps_api_error(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    provider = OpenAIProvider(config, client=build_client(error=RuntimeError("down")))

    with pytest.raises(ProviderTransientError, match="failed to call the model API"):
        provider.generate("system", "message")


def test_openai_provider_passes_configured_timeout_to_sdk(tmp_path):
    captured_kwargs: list[dict[str, object]] = []
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=17.0)
    provider = OpenAIProvider(
        config,
        client=build_client(response=build_response("ok"), captured_kwargs=captured_kwargs),
    )

    provider.generate("system", "message")

    assert captured_kwargs[0]["timeout"] == 17.0


def test_openai_provider_health_check_returns_structured_success_snapshot(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=14.0)
    provider = OpenAIProvider(
        config,
        client=build_client(health_response=[SimpleNamespace(id="gpt-4o")]),
    )

    snapshot = provider.health_check()

    assert snapshot["provider"] == "openai"
    assert snapshot["model"] == "gpt-4o"
    assert snapshot["status"] == "healthy"
    assert snapshot["active_check"] is True
    assert snapshot["timeout_seconds"] == 5.0
    assert snapshot["latency_ms"] >= 0


def test_openai_provider_health_check_passes_capped_timeout_to_sdk(tmp_path):
    captured_kwargs: list[dict[str, object]] = []
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), timeout_seconds=17.0)
    provider = OpenAIProvider(
        config,
        client=build_client(health_captured_kwargs=captured_kwargs),
    )

    provider.health_check()

    assert captured_kwargs[0]["timeout"] == 5.0


def test_openai_provider_health_check_treats_client_4xx_errors_as_deterministic(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    provider = OpenAIProvider(
        config,
        client=build_client(health_error=FakeAPIError("bad request", 400)),
    )

    with pytest.raises(AgentExecutionError, match="health check was rejected") as exc_info:
        provider.health_check()

    assert exc_info.type is AgentExecutionError


def test_openai_provider_health_check_treats_rate_limits_as_transient(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    provider = OpenAIProvider(
        config,
        client=build_client(health_error=FakeAPIError("rate limited", 429)),
    )

    with pytest.raises(ProviderTransientError, match="health check failed") as exc_info:
        provider.health_check()

    assert exc_info.type is ProviderTransientError


def test_openai_provider_treats_client_4xx_errors_as_deterministic(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    provider = OpenAIProvider(config, client=build_client(error=FakeAPIError("bad request", 400)))

    with pytest.raises(AgentExecutionError, match="rejected the model API request") as exc_info:
        provider.generate("system", "message")

    assert exc_info.type is AgentExecutionError


def test_openai_provider_treats_rate_limits_as_transient(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    provider = OpenAIProvider(config, client=build_client(error=FakeAPIError("rate limited", 429)))

    with pytest.raises(ProviderTransientError, match="failed to call the model API") as exc_info:
        provider.generate("system", "message")

    assert exc_info.type is ProviderTransientError


def test_openai_provider_builds_client_from_installed_sdk(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), api_key="token")

    class FakeOpenAI:
        def __init__(self, api_key):
            self.api_key = api_key

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    provider = OpenAIProvider(config)
    client = provider._get_client()

    assert isinstance(client, FakeOpenAI)
    assert client.api_key == "token"


def test_openai_provider_rejects_invalid_and_empty_payloads(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    invalid_provider = OpenAIProvider(config, client=build_client(response=SimpleNamespace(choices=[])))

    with pytest.raises(AgentExecutionError, match="invalid response payload"):
        invalid_provider.generate("system", "message")

    empty_provider = OpenAIProvider(config, client=build_client(response=build_response("")))

    with pytest.raises(AgentExecutionError, match="empty response"):
        empty_provider.generate("system", "message")


def test_openai_provider_metadata_is_none_before_calls(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))

    assert OpenAIProvider(config, client=build_client(response=build_response("ok"))).get_last_call_metadata() is None


def test_anthropic_provider_returns_content(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="anthropic")
    response = SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")])
    provider = AnthropicProvider(config, client=build_anthropic_client(response=response))

    result = provider.generate("system", "message")

    assert result == "ok"


def test_anthropic_provider_captures_usage_metadata(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="anthropic")
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ok")],
        usage=SimpleNamespace(
            input_tokens=12,
            output_tokens=8,
            cache_creation_input_tokens=3,
            cache_read_input_tokens=2,
        ),
    )
    provider = AnthropicProvider(config, client=build_anthropic_client(response=response))

    provider.generate("system", "message")

    assert provider.get_last_call_metadata() == {
        "usage": {
            "input_tokens": 12,
            "output_tokens": 8,
            "total_tokens": 20,
            "cache_creation_input_tokens": 3,
            "cache_read_input_tokens": 2,
        }
    }


def test_anthropic_provider_preserves_none_total_tokens_when_usage_counts_are_missing(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="anthropic")
    provider = AnthropicProvider(config, client=build_anthropic_client(response=SimpleNamespace()))

    metadata = provider._extract_metadata(
        SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=None,
                output_tokens=None,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            )
        )
    )

    assert metadata is not None
    assert metadata["usage"]["input_tokens"] is None
    assert metadata["usage"]["output_tokens"] is None
    assert metadata["usage"]["total_tokens"] is None


def test_anthropic_provider_wraps_api_error(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="anthropic")
    provider = AnthropicProvider(config, client=build_anthropic_client(error=RuntimeError("down")))

    with pytest.raises(ProviderTransientError, match="failed to call the model API"):
        provider.generate("system", "message")


def test_anthropic_provider_passes_configured_timeout_to_sdk(tmp_path):
    captured_kwargs: list[dict[str, object]] = []
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="anthropic", timeout_seconds=19.0)
    response = SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")])
    provider = AnthropicProvider(
        config,
        client=build_anthropic_client(response=response, captured_kwargs=captured_kwargs),
    )

    provider.generate("system", "message")

    assert captured_kwargs[0]["timeout"] == 19.0


def test_anthropic_provider_health_check_returns_structured_success_snapshot(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="anthropic", timeout_seconds=14.0)
    provider = AnthropicProvider(
        config,
        client=build_anthropic_client(health_response=[SimpleNamespace(id="claude-3-5-sonnet")]),
    )

    snapshot = provider.health_check()

    assert snapshot["provider"] == "anthropic"
    assert snapshot["model"] == "gpt-4o"
    assert snapshot["status"] == "healthy"
    assert snapshot["active_check"] is True
    assert snapshot["timeout_seconds"] == 5.0
    assert snapshot["latency_ms"] >= 0


def test_anthropic_provider_health_check_passes_capped_timeout_to_sdk(tmp_path):
    captured_kwargs: list[dict[str, object]] = []
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="anthropic", timeout_seconds=19.0)
    provider = AnthropicProvider(
        config,
        client=build_anthropic_client(health_captured_kwargs=captured_kwargs),
    )

    provider.health_check()

    assert captured_kwargs[0]["timeout"] == 5.0


def test_anthropic_provider_health_check_treats_client_4xx_errors_as_deterministic(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="anthropic")
    provider = AnthropicProvider(
        config,
        client=build_anthropic_client(health_error=FakeAPIError("bad request", 400)),
    )

    with pytest.raises(AgentExecutionError, match="health check was rejected") as exc_info:
        provider.health_check()

    assert exc_info.type is AgentExecutionError


def test_anthropic_provider_health_check_treats_server_5xx_errors_as_transient(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="anthropic")
    provider = AnthropicProvider(
        config,
        client=build_anthropic_client(health_error=FakeAPIError("upstream down", 503)),
    )

    with pytest.raises(ProviderTransientError, match="health check failed") as exc_info:
        provider.health_check()

    assert exc_info.type is ProviderTransientError


def test_ollama_provider_uses_configured_timeouts_for_health_check_and_generation(tmp_path):
    captured_timeouts: list[float] = []

    def open_request(request, timeout=None):
        captured_timeouts.append(timeout)
        if request.full_url.endswith("/api/tags"):
            return FakeHTTPResponse('{"models": []}')
        return FakeHTTPResponse('{"response": "ok"}')

    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        llm_provider="ollama",
        llm_model="llama3",
        timeout_seconds=14.0,
    )
    provider = OllamaProvider(config, request_opener=open_request)

    provider.generate("system", "message")

    assert captured_timeouts == [5.0, 14.0]


def test_ollama_provider_health_check_returns_structured_success_snapshot(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        llm_provider="ollama",
        llm_model="llama3",
        timeout_seconds=14.0,
    )
    provider = OllamaProvider(
        config,
        request_opener=build_ollama_opener(payload='{"models": []}'),
    )

    snapshot = provider.health_check()

    assert snapshot["provider"] == "ollama"
    assert snapshot["model"] == "llama3"
    assert snapshot["status"] == "healthy"
    assert snapshot["active_check"] is True
    assert snapshot["base_url"] == "http://localhost:11434"
    assert snapshot["timeout_seconds"] == 5.0
    assert snapshot["latency_ms"] >= 0


def test_anthropic_provider_treats_client_4xx_errors_as_deterministic(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="anthropic")
    provider = AnthropicProvider(config, client=build_anthropic_client(error=FakeAPIError("bad request", 400)))

    with pytest.raises(AgentExecutionError, match="rejected the model API request") as exc_info:
        provider.generate("system", "message")

    assert exc_info.type is AgentExecutionError


def test_anthropic_provider_treats_server_5xx_errors_as_transient(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="anthropic")
    provider = AnthropicProvider(config, client=build_anthropic_client(error=FakeAPIError("upstream down", 503)))

    with pytest.raises(ProviderTransientError, match="failed to call the model API") as exc_info:
        provider.generate("system", "message")

    assert exc_info.type is ProviderTransientError


def test_anthropic_provider_builds_client_from_installed_sdk(tmp_path, monkeypatch):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="anthropic", api_key="token")

    class FakeAnthropic:
        def __init__(self, api_key):
            self.api_key = api_key

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=FakeAnthropic))

    provider = AnthropicProvider(config)
    client = provider._get_client()

    assert isinstance(client, FakeAnthropic)
    assert client.api_key == "token"


def test_anthropic_provider_rejects_invalid_and_empty_payloads(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="anthropic")
    invalid_provider = AnthropicProvider(config, client=build_anthropic_client(response=SimpleNamespace()))

    with pytest.raises(AgentExecutionError, match="invalid response payload"):
        invalid_provider.generate("system", "message")

    empty_provider = AnthropicProvider(
        config,
        client=build_anthropic_client(response=SimpleNamespace(content=[SimpleNamespace(type="tool_use", text="")]))
    )

    with pytest.raises(AgentExecutionError, match="empty response"):
        empty_provider.generate("system", "message")


def test_anthropic_provider_metadata_is_none_before_calls(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="anthropic")

    assert AnthropicProvider(config, client=build_anthropic_client(response=SimpleNamespace())).get_last_call_metadata() is None


def test_ollama_provider_returns_content(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama", llm_model="llama3")
    provider = OllamaProvider(
        config,
        request_opener=build_ollama_opener(payload=['{"models": []}', '{"response": "ok"}']),
    )

    result = provider.generate("system", "message")

    assert result == "ok"


def test_ollama_provider_captures_usage_metadata(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama", llm_model="llama3")
    provider = OllamaProvider(
        config,
        request_opener=build_ollama_opener(
            payload=['{"models": []}', '{"response": "ok", "prompt_eval_count": 14, "eval_count": 9, "total_duration": 125000000, "load_duration": 25000000}']
        ),
    )

    provider.generate("system", "message")

    assert provider.get_last_call_metadata() == {
        "usage": {"input_tokens": 14, "output_tokens": 9, "total_tokens": 23},
        "timing": {"total_duration_ms": 125.0, "load_duration_ms": 25.0},
    }


def test_ollama_provider_rejects_unreachable_server(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama", llm_model="llama3")
    provider = OllamaProvider(
        config,
        request_opener=build_ollama_opener(error=OSError("down")),
    )

    with pytest.raises(AgentExecutionError, match=r"Ollama server is not responding at http://localhost:11434"):
        provider.generate("system", "message")


def test_ollama_provider_surfaces_health_check_http_error(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama", llm_model="llama3")
    provider = OllamaProvider(
        config,
        request_opener=build_ollama_opener(error=build_http_error("http://localhost:11434/api/tags", 503, "Unavailable")),
    )

    with pytest.raises(ProviderTransientError, match=r"health check failed at http://localhost:11434 with HTTP 503") as exc_info:
        provider.generate("system", "message")

    assert exc_info.type is ProviderTransientError


def test_ollama_provider_treats_health_check_4xx_errors_as_deterministic(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama", llm_model="llama3")
    provider = OllamaProvider(
        config,
        request_opener=build_ollama_opener(error=build_http_error("http://localhost:11434/api/tags", 404, "Not Found")),
    )

    with pytest.raises(AgentExecutionError, match=r"health check failed at http://localhost:11434 with HTTP 404") as exc_info:
        provider.generate("system", "message")

    assert exc_info.type is AgentExecutionError


def test_ollama_provider_surfaces_health_check_timeout(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        llm_provider="ollama",
        llm_model="llama3",
        timeout_seconds=300.0,
    )
    provider = OllamaProvider(
        config,
        request_opener=build_ollama_opener(error=TimeoutError("timed out")),
    )

    with pytest.raises(AgentExecutionError, match=r"health check timed out after 5 seconds"):
        provider.generate("system", "message")


def test_ollama_provider_surfaces_generation_timeout_after_successful_preflight(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        llm_provider="ollama",
        llm_model="llama3",
        timeout_seconds=42.0,
    )
    provider = OllamaProvider(
        config,
        request_opener=build_ollama_opener(payload=['{"models": []}'], error=[None, TimeoutError("timed out")]),
    )

    with pytest.raises(AgentExecutionError, match=r"timed out after 42 seconds"):
        provider.generate("system", "message")


def test_ollama_provider_surfaces_http_error_with_status_code(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama", llm_model="llama3")
    provider = OllamaProvider(
        config,
        request_opener=build_ollama_opener(
            payload=['{"models": []}'],
            error=[None, build_http_error("http://localhost:11434/api/generate", 500, "Internal Server Error")],
        ),
    )

    with pytest.raises(ProviderTransientError, match=r"HTTP 500") as exc_info:
        provider.generate("system", "message")

    assert exc_info.type is ProviderTransientError


def test_ollama_provider_treats_generation_4xx_errors_as_deterministic(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama", llm_model="llama3")
    provider = OllamaProvider(
        config,
        request_opener=build_ollama_opener(
            payload=['{"models": []}'],
            error=[None, build_http_error("http://localhost:11434/api/generate", 400, "Bad Request")],
        ),
    )

    with pytest.raises(AgentExecutionError, match=r"HTTP 400") as exc_info:
        provider.generate("system", "message")

    assert exc_info.type is AgentExecutionError


def test_ollama_provider_rejects_invalid_json_response(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama", llm_model="llama3")
    provider = OllamaProvider(
        config,
        request_opener=build_ollama_opener(payload=['{"models": []}', 'not-json']),
    )

    with pytest.raises(AgentExecutionError, match=r"invalid JSON response"):
        provider.generate("system", "message")


def test_ollama_provider_rejects_empty_response_payload(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama", llm_model="llama3")
    provider = OllamaProvider(
        config,
        request_opener=build_ollama_opener(payload=['{"models": []}', '{"response": ""}']),
    )

    with pytest.raises(AgentExecutionError, match=r"empty response"):
        provider.generate("system", "message")


def test_ollama_provider_rejects_generation_connection_failure_after_preflight(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama", llm_model="llama3")
    provider = OllamaProvider(
        config,
        request_opener=build_ollama_opener(payload=['{"models": []}'], error=[None, OSError("down")]),
    )

    with pytest.raises(ProviderTransientError, match=r"Ollama server is not responding at http://localhost:11434") as exc_info:
        provider.generate("system", "message")

    assert exc_info.type is ProviderTransientError


def test_ollama_provider_metadata_is_none_before_calls(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama", llm_model="llama3")

    assert OllamaProvider(config, request_opener=build_ollama_opener(payload=['{"models": []}'])).get_last_call_metadata() is None


def test_base_provider_default_metadata_is_none():
    class MinimalProvider(BaseLLMProvider):
        def generate(self, system_prompt: str, user_message: str) -> str:
            return "ok"

    assert MinimalProvider().get_last_call_metadata() is None


def test_base_provider_default_health_check_returns_ready_snapshot():
    class MinimalProvider(BaseLLMProvider):
        def generate(self, system_prompt: str, user_message: str) -> str:
            return "ok"

    assert MinimalProvider().health_check() == {
        "provider": None,
        "model": None,
        "status": "ready",
        "active_check": False,
    }


def test_base_provider_generate_super_raises_not_implemented():
    class SuperCallingProvider(BaseLLMProvider):
        def generate(self, system_prompt: str, user_message: str) -> str:
            return super().generate(system_prompt, user_message)

    with pytest.raises(NotImplementedError):
        SuperCallingProvider().generate("system", "message")