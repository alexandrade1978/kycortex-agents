"""Model-adaptive prompt policy resolution for agent task contexts."""

from __future__ import annotations

from dataclasses import dataclass

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.providers.model_capabilities import ModelCapabilities

PROMPT_POLICY_MODES: frozenset[str] = frozenset({"compact", "balanced", "rich"})


@dataclass(frozen=True)
class AdaptivePromptPolicy:
    """Resolved policy used by agents to decide prompt compression behavior."""

    mode: str
    compression_enabled: bool
    source: str
    provider: str
    model: str
    max_tokens: int
    timeout_seconds: float

    def to_context_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "compression_enabled": self.compression_enabled,
            "source": self.source,
            "provider": self.provider,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "timeout_seconds": self.timeout_seconds,
        }


def resolve_adaptive_prompt_policy(
    config: KYCortexConfig,
    *,
    provider_name: str,
    model_name: str,
    capabilities: ModelCapabilities,
    max_tokens: int | None = None,
    timeout_seconds: float | None = None,
) -> AdaptivePromptPolicy:
    """Resolve prompt mode using config, model capabilities, and runtime budget."""

    resolved_max_tokens = max_tokens if isinstance(max_tokens, int) and max_tokens > 0 else config.max_tokens
    resolved_timeout_seconds = (
        timeout_seconds
        if isinstance(timeout_seconds, (int, float)) and timeout_seconds > 0
        else config.provider_timeout_seconds_for(provider_name)
    )

    normalized_provider = provider_name.strip().lower()
    normalized_model = model_name.strip()
    override_key = f"{normalized_provider}:{normalized_model}".lower()

    if config.adaptive_prompt_policy_enabled:
        override_mode = config.adaptive_prompt_mode_overrides.get(override_key)
        if override_mode in PROMPT_POLICY_MODES:
            mode = override_mode
            source = "model_override"
        else:
            mode = _select_mode_from_budget_and_capability(
                default_mode=config.adaptive_prompt_default_mode,
                compact_threshold_tokens=config.adaptive_prompt_compact_threshold_tokens,
                max_tokens=resolved_max_tokens,
                capabilities=capabilities,
            )
            source = "adaptive_heuristic"
    else:
        mode = "compact" if resolved_max_tokens <= config.adaptive_prompt_compact_threshold_tokens else "balanced"
        source = "legacy_budget_gate"

    return AdaptivePromptPolicy(
        mode=mode,
        compression_enabled=mode == "compact",
        source=source,
        provider=normalized_provider,
        model=normalized_model,
        max_tokens=resolved_max_tokens,
        timeout_seconds=float(resolved_timeout_seconds),
    )


def _select_mode_from_budget_and_capability(
    *,
    default_mode: str,
    compact_threshold_tokens: int,
    max_tokens: int,
    capabilities: ModelCapabilities,
) -> str:
    normalized_default_mode = default_mode if default_mode in PROMPT_POLICY_MODES else "balanced"

    if max_tokens <= compact_threshold_tokens:
        return "compact"
    if capabilities.is_reasoning_model:
        return "rich"
    if isinstance(capabilities.context_window, int) and capabilities.context_window >= 200_000:
        return "rich"
    if max_tokens >= 6000:
        return "rich"
    return normalized_default_mode
