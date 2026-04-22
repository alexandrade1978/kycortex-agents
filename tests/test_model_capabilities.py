"""Unit tests for the model capabilities registry and resolution logic."""

from __future__ import annotations

import pytest

from kycortex_agents.providers.model_capabilities import (
    MODEL_REGISTRY,
    ModelCapabilities,
    get_capabilities,
)


# ---------------------------------------------------------------------------
# ModelCapabilities dataclass
# ---------------------------------------------------------------------------


class TestModelCapabilitiesDefaults:
    def test_openai_default_uses_max_completion_tokens(self):
        caps = ModelCapabilities.openai_default()
        assert caps.provider == "openai"
        assert caps.max_tokens_param == "max_completion_tokens"
        assert caps.supports_temperature is True

    def test_anthropic_default_uses_max_tokens(self):
        caps = ModelCapabilities.anthropic_default()
        assert caps.provider == "anthropic"
        assert caps.max_tokens_param == "max_tokens"
        assert caps.temperature_range == (0.0, 1.0)

    def test_ollama_default_uses_max_tokens(self):
        caps = ModelCapabilities.ollama_default()
        assert caps.provider == "ollama"
        assert caps.max_tokens_param == "max_tokens"
        assert caps.supports_temperature is True

    def test_for_provider_dispatches_to_known_provider(self):
        caps = ModelCapabilities.for_provider("openai")
        assert caps == ModelCapabilities.openai_default()

    def test_for_provider_normalizes_case_and_whitespace(self):
        caps = ModelCapabilities.for_provider("  OpenAI  ")
        assert caps == ModelCapabilities.openai_default()

    def test_for_provider_returns_generic_for_unknown_provider(self):
        caps = ModelCapabilities.for_provider("some-custom-provider")
        assert caps.provider == "some-custom-provider"
        assert caps.max_tokens_param == "max_tokens"
        assert caps.supports_temperature is True


class TestModelCapabilitiesFrozen:
    def test_frozen_dataclass_prevents_mutation(self):
        caps = ModelCapabilities.openai_default()
        with pytest.raises(AttributeError):
            caps.supports_temperature = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Registry structure
# ---------------------------------------------------------------------------


class TestRegistryStructure:
    def test_registry_is_not_empty(self):
        assert len(MODEL_REGISTRY) > 0

    def test_all_registry_keys_have_provider_prefix(self):
        for key in MODEL_REGISTRY:
            assert ":" in key, f"Registry key missing provider prefix: {key}"

    def test_all_registry_values_are_model_capabilities(self):
        for key, value in MODEL_REGISTRY.items():
            assert isinstance(value, ModelCapabilities), f"Bad value for {key}"

    def test_known_openai_models_present(self):
        expected = ["openai:gpt-4o-mini", "openai:gpt-4o", "openai:gpt-5-mini"]
        for key in expected:
            assert key in MODEL_REGISTRY, f"Missing registry entry: {key}"

    def test_gpt5_family_does_not_support_temperature(self):
        for key, caps in MODEL_REGISTRY.items():
            if key.startswith("openai:gpt-5"):
                assert caps.supports_temperature is False, f"{key} should not support temperature"

    def test_o_series_does_not_support_temperature(self):
        o_series = [k for k in MODEL_REGISTRY if k.startswith("openai:o")]
        assert len(o_series) > 0
        for key in o_series:
            assert MODEL_REGISTRY[key].supports_temperature is False


# ---------------------------------------------------------------------------
# get_capabilities — exact match
# ---------------------------------------------------------------------------


class TestGetCapabilitiesExactMatch:
    def test_exact_match_gpt4o_mini(self):
        caps = get_capabilities("openai", "gpt-4o-mini")
        assert caps.provider == "openai"
        assert caps.max_tokens_param == "max_completion_tokens"
        assert caps.supports_temperature is True

    def test_exact_match_gpt5_mini(self):
        caps = get_capabilities("openai", "gpt-5-mini")
        assert caps.supports_temperature is False
        assert caps.max_tokens_param == "max_completion_tokens"

    def test_exact_match_o1_mini(self):
        caps = get_capabilities("openai", "o1-mini")
        assert caps.supports_temperature is False
        assert caps.supports_system_role is False

    def test_exact_match_o3(self):
        caps = get_capabilities("openai", "o3")
        assert caps.supports_temperature is False
        assert caps.supports_system_role is True


# ---------------------------------------------------------------------------
# get_capabilities — glob / pattern match
# ---------------------------------------------------------------------------


class TestGetCapabilitiesGlobMatch:
    def test_glob_matches_dated_gpt4o_mini_variant(self):
        caps = get_capabilities("openai", "gpt-4o-mini-2025-06-18")
        assert caps.supports_temperature is True
        assert caps.max_tokens_param == "max_completion_tokens"

    def test_glob_matches_future_gpt5_variant(self):
        caps = get_capabilities("openai", "gpt-5-pro")
        assert caps.supports_temperature is False

    def test_glob_matches_anthropic_sonnet(self):
        caps = get_capabilities("anthropic", "claude-3-5-sonnet-20241022")
        assert caps.provider == "anthropic"
        assert caps.max_tokens_param == "max_tokens"
        assert caps.supports_temperature is True

    def test_glob_matches_anthropic_opus(self):
        caps = get_capabilities("anthropic", "claude-opus-4-20250514")
        assert caps.provider == "anthropic"
        assert caps.supports_temperature is True

    def test_glob_matches_o1_dated_variant(self):
        caps = get_capabilities("openai", "o1-2025-01-01")
        assert caps.supports_temperature is False


# ---------------------------------------------------------------------------
# get_capabilities — provider default fallback
# ---------------------------------------------------------------------------


class TestGetCapabilitiesProviderDefault:
    def test_unknown_openai_model_gets_openai_defaults(self):
        caps = get_capabilities("openai", "some-future-model-v99")
        assert caps.provider == "openai"
        assert caps.max_tokens_param == "max_completion_tokens"
        assert caps.supports_temperature is True

    def test_unknown_anthropic_model_gets_anthropic_defaults(self):
        caps = get_capabilities("anthropic", "claude-unknown-v42")
        assert caps.provider == "anthropic"
        assert caps.max_tokens_param == "max_tokens"

    def test_unknown_ollama_model_gets_ollama_defaults(self):
        caps = get_capabilities("ollama", "llama3:latest")
        assert caps.provider == "ollama"
        assert caps.max_tokens_param == "max_tokens"
        assert caps.supports_temperature is True

    def test_completely_unknown_provider_gets_generic_defaults(self):
        caps = get_capabilities("my-provider", "my-model")
        assert caps.provider == "my-provider"
        assert caps.max_tokens_param == "max_tokens"
        assert caps.supports_temperature is True


# ---------------------------------------------------------------------------
# get_capabilities — normalization
# ---------------------------------------------------------------------------


class TestGetCapabilitiesNormalization:
    def test_provider_name_is_case_insensitive(self):
        caps = get_capabilities("OpenAI", "gpt-4o-mini")
        assert caps == get_capabilities("openai", "gpt-4o-mini")

    def test_provider_name_strips_whitespace(self):
        caps = get_capabilities("  openai  ", "gpt-4o-mini")
        assert caps.provider == "openai"


# ---------------------------------------------------------------------------
# Ollama model registry entries
# ---------------------------------------------------------------------------


class TestOllamaModelCapabilities:
    def test_qwen25_coder_7b_exact_match(self):
        caps = get_capabilities("ollama", "qwen2.5-coder:7b")
        assert caps.provider == "ollama"
        assert caps.max_tokens_param == "num_predict"
        assert caps.supports_temperature is True
        assert caps.is_reasoning_model is False

    def test_qwen25_coder_14b_exact_match(self):
        caps = get_capabilities("ollama", "qwen2.5-coder:14b")
        assert caps.provider == "ollama"
        assert caps.max_tokens_param == "num_predict"
        assert caps.is_reasoning_model is False

    def test_qwen25_glob_matches_unknown_qwen25_variant(self):
        caps = get_capabilities("ollama", "qwen2.5:72b")
        assert caps.provider == "ollama"
        assert caps.max_tokens_param == "num_predict"
        assert caps.is_reasoning_model is False

    def test_qwen35_9b_exact_match_is_reasoning_model(self):
        caps = get_capabilities("ollama", "qwen3.5:9b")
        assert caps.provider == "ollama"
        assert caps.max_tokens_param == "num_predict"
        assert caps.is_reasoning_model is True

    def test_qwen3_glob_matches_unknown_qwen3_variant(self):
        caps = get_capabilities("ollama", "qwen3:32b")
        assert caps.provider == "ollama"
        assert caps.is_reasoning_model is True

    def test_unknown_ollama_model_not_marked_as_reasoning(self):
        caps = get_capabilities("ollama", "llama3.1:8b")
        assert caps.is_reasoning_model is False
