from types import SimpleNamespace

import pytest

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ProviderConfigurationError
from kycortex_agents.providers.factory import create_provider
from kycortex_agents.providers.openai_provider import OpenAIProvider


def build_response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def build_client(response=None, error=None):
    def create(**kwargs):
        if error is not None:
            raise error
        return response

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_create_provider_returns_openai_provider(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"), llm_provider="openai", api_key="token")

    provider = create_provider(config)

    assert isinstance(provider, OpenAIProvider)


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


def test_openai_provider_wraps_api_error(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    provider = OpenAIProvider(config, client=build_client(error=RuntimeError("down")))

    with pytest.raises(AgentExecutionError, match="failed to call the model API"):
        provider.generate("system", "message")