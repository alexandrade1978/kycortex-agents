from types import SimpleNamespace

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
    def open_request(request, timeout=None):
        if error is not None:
            raise error
        return FakeHTTPResponse(payload)

    return open_request


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
        request_opener=build_ollama_opener(payload='{"response": "ok"}'),
    )

    result = provider.generate("system", "message")

    assert result == "ok"


def test_ollama_provider_captures_usage_metadata(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama", llm_model="llama3")
    provider = OllamaProvider(
        config,
        request_opener=build_ollama_opener(
            payload='{"response": "ok", "prompt_eval_count": 14, "eval_count": 9, "total_duration": 125000000, "load_duration": 25000000}'
        ),
    )

    provider.generate("system", "message")

    assert provider.get_last_call_metadata() == {
        "usage": {"input_tokens": 14, "output_tokens": 9, "total_tokens": 23},
        "timing": {"total_duration_ms": 125.0, "load_duration_ms": 25.0},
    }


def test_ollama_provider_wraps_api_error(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="ollama", llm_model="llama3")
    provider = OllamaProvider(
        config,
        request_opener=build_ollama_opener(error=OSError("down")),
    )

    with pytest.raises(AgentExecutionError, match="failed to call the model API"):
        provider.generate("system", "message")