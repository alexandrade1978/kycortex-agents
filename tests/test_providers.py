from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ProviderConfigurationError
from kycortex_agents.providers.anthropic_provider import AnthropicProvider
from kycortex_agents.providers.factory import create_provider
from kycortex_agents.providers.ollama_provider import OllamaProvider
from kycortex_agents.providers.openai_provider import OpenAIProvider


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


def build_client(response=None, error=None):
    def create(**kwargs):
        if error is not None:
            raise error
        return response

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def build_anthropic_client(response=None, error=None):
    def create(**kwargs):
        if error is not None:
            raise error
        return response

    return SimpleNamespace(messages=SimpleNamespace(create=create))


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

    with pytest.raises(AgentExecutionError, match="failed to call the model API"):
        provider.generate("system", "message")


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


def test_anthropic_provider_wraps_api_error(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="anthropic")
    provider = AnthropicProvider(config, client=build_anthropic_client(error=RuntimeError("down")))

    with pytest.raises(AgentExecutionError, match="failed to call the model API"):
        provider.generate("system", "message")


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

    with pytest.raises(AgentExecutionError, match=r"HTTP 500"):
        provider.generate("system", "message")


def test_ollama_provider_rejects_invalid_json_response(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama", llm_model="llama3")
    provider = OllamaProvider(
        config,
        request_opener=build_ollama_opener(payload=['{"models": []}', 'not-json']),
    )

    with pytest.raises(AgentExecutionError, match=r"invalid JSON response"):
        provider.generate("system", "message")