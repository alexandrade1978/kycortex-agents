"""Model capabilities registry for provider-agnostic API parameter adaptation.

Each supported model (or model family) declares which API parameters it accepts,
allowing providers to build correct request payloads without hard-coded per-model
branches or runtime trial-and-error retries.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModelCapabilities:
    """Declares API-level parameter capabilities for a model or model family."""

    provider: str
    max_tokens_param: str = "max_tokens"
    supports_temperature: bool = True
    temperature_range: Optional[tuple[float, float]] = None
    supports_system_role: bool = True
    context_window: Optional[int] = None
    output_format_hints: tuple[str, ...] = ()

    @classmethod
    def openai_default(cls) -> ModelCapabilities:
        """Sensible defaults for unknown OpenAI models."""
        return cls(provider="openai", max_tokens_param="max_completion_tokens")

    @classmethod
    def anthropic_default(cls) -> ModelCapabilities:
        """Sensible defaults for unknown Anthropic models."""
        return cls(
            provider="anthropic",
            max_tokens_param="max_tokens",
            temperature_range=(0.0, 1.0),
        )

    @classmethod
    def ollama_default(cls) -> ModelCapabilities:
        """Sensible defaults for unknown Ollama models."""
        return cls(provider="ollama", max_tokens_param="max_tokens")

    @classmethod
    def for_provider(cls, provider: str) -> ModelCapabilities:
        """Return provider-level defaults for the given provider name."""
        defaults = {
            "openai": cls.openai_default,
            "anthropic": cls.anthropic_default,
            "ollama": cls.ollama_default,
        }
        factory = defaults.get(provider.lower().strip())
        if factory is not None:
            return factory()
        return cls(provider=provider.lower().strip())


# ---------------------------------------------------------------------------
# Registry keyed by "provider:model" or "provider:glob_pattern".
# Exact model names take priority over glob patterns during lookup.
# ---------------------------------------------------------------------------

MODEL_REGISTRY: dict[str, ModelCapabilities] = {
    # --- OpenAI: gpt-4o family ---
    "openai:gpt-4o-mini": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=True,
        context_window=128_000,
    ),
    "openai:gpt-4o": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=True,
        context_window=128_000,
    ),
    # --- OpenAI: gpt-4.1 family ---
    "openai:gpt-4.1-mini": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=True,
        context_window=1_047_576,
    ),
    "openai:gpt-4.1": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=True,
        context_window=1_047_576,
    ),
    "openai:gpt-4.1-nano": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=True,
        context_window=1_047_576,
    ),
    # --- OpenAI: gpt-5 family (temperature not supported) ---
    "openai:gpt-5-mini": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=False,
        context_window=1_047_576,
    ),
    "openai:gpt-5": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=False,
        context_window=1_047_576,
    ),
    "openai:gpt-5-nano": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=False,
        context_window=1_047_576,
    ),
    # --- OpenAI: o-series reasoning models (temperature not supported) ---
    "openai:o1-mini": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=False,
        supports_system_role=False,
        context_window=128_000,
    ),
    "openai:o1": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=False,
        supports_system_role=False,
        context_window=128_000,
    ),
    "openai:o3-mini": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=False,
        supports_system_role=True,
        context_window=200_000,
    ),
    "openai:o3": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=False,
        supports_system_role=True,
        context_window=200_000,
    ),
    "openai:o4-mini": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=False,
        supports_system_role=True,
        context_window=200_000,
    ),
    # --- OpenAI: glob fallbacks for future dated variants ---
    "openai:gpt-4o-mini-*": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=True,
        context_window=128_000,
    ),
    "openai:gpt-4o-*": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=True,
        context_window=128_000,
    ),
    "openai:gpt-4.1-mini-*": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=True,
        context_window=1_047_576,
    ),
    "openai:gpt-4.1-*": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=True,
        context_window=1_047_576,
    ),
    "openai:gpt-5*": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=False,
        context_window=1_047_576,
    ),
    "openai:o1*": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=False,
        supports_system_role=False,
        context_window=128_000,
    ),
    "openai:o3*": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=False,
        supports_system_role=True,
        context_window=200_000,
    ),
    "openai:o4*": ModelCapabilities(
        provider="openai",
        max_tokens_param="max_completion_tokens",
        supports_temperature=False,
        supports_system_role=True,
        context_window=200_000,
    ),
    # --- Anthropic: Claude model families ---
    "anthropic:claude-3-5-sonnet-*": ModelCapabilities(
        provider="anthropic",
        max_tokens_param="max_tokens",
        supports_temperature=True,
        temperature_range=(0.0, 1.0),
        context_window=200_000,
    ),
    "anthropic:claude-3-5-haiku-*": ModelCapabilities(
        provider="anthropic",
        max_tokens_param="max_tokens",
        supports_temperature=True,
        temperature_range=(0.0, 1.0),
        context_window=200_000,
    ),
    "anthropic:claude-sonnet-4-*": ModelCapabilities(
        provider="anthropic",
        max_tokens_param="max_tokens",
        supports_temperature=True,
        temperature_range=(0.0, 1.0),
        context_window=200_000,
    ),
    "anthropic:claude-opus-4-*": ModelCapabilities(
        provider="anthropic",
        max_tokens_param="max_tokens",
        supports_temperature=True,
        temperature_range=(0.0, 1.0),
        context_window=200_000,
    ),
    "anthropic:claude-4-*": ModelCapabilities(
        provider="anthropic",
        max_tokens_param="max_tokens",
        supports_temperature=True,
        temperature_range=(0.0, 1.0),
        context_window=200_000,
    ),
}


def get_capabilities(provider: str, model: str) -> ModelCapabilities:
    """Resolve model capabilities via exact match, glob pattern, or provider defaults.

    Lookup order:
    1. Exact ``"provider:model"`` key in the registry.
    2. First glob pattern in the registry that matches.
    3. Built-in provider-level defaults (never fails).
    """
    normalized_provider = provider.lower().strip()
    lookup_key = f"{normalized_provider}:{model}"

    # 1. Exact match
    exact = MODEL_REGISTRY.get(lookup_key)
    if exact is not None:
        return exact

    # 2. Glob / pattern match
    for pattern, capabilities in MODEL_REGISTRY.items():
        if "*" in pattern and fnmatch.fnmatch(lookup_key, pattern):
            return capabilities

    # 3. Provider-level defaults
    return ModelCapabilities.for_provider(normalized_provider)
