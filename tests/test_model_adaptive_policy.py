from kycortex_agents.config import KYCortexConfig
from kycortex_agents.orchestration.model_adaptive_policy import resolve_adaptive_prompt_policy
from kycortex_agents.providers.model_capabilities import get_capabilities


def test_resolve_adaptive_prompt_policy_uses_legacy_gate_when_disabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        adaptive_prompt_policy_enabled=False,
        adaptive_prompt_compact_threshold_tokens=1200,
    )

    policy = resolve_adaptive_prompt_policy(
        config,
        provider_name="openai",
        model_name="gpt-4o",
        capabilities=get_capabilities("openai", "gpt-4o"),
        max_tokens=900,
    )

    assert policy.mode == "compact"
    assert policy.compression_enabled is True
    assert policy.source == "legacy_budget_gate"


def test_resolve_adaptive_prompt_policy_uses_override_mode_when_enabled(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        adaptive_prompt_policy_enabled=True,
        adaptive_prompt_mode_overrides={"openai:gpt-5": "rich"},
    )

    policy = resolve_adaptive_prompt_policy(
        config,
        provider_name="openai",
        model_name="gpt-5",
        capabilities=get_capabilities("openai", "gpt-5"),
        max_tokens=900,
    )

    assert policy.mode == "rich"
    assert policy.compression_enabled is False
    assert policy.source == "model_override"


def test_resolve_adaptive_prompt_policy_escalates_reasoning_models_to_rich(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        adaptive_prompt_policy_enabled=True,
        adaptive_prompt_default_mode="balanced",
    )

    policy = resolve_adaptive_prompt_policy(
        config,
        provider_name="openai",
        model_name="gpt-5",
        capabilities=get_capabilities("openai", "gpt-5"),
        max_tokens=4096,
    )

    assert policy.mode == "rich"
    assert policy.source == "adaptive_heuristic"


def test_resolve_adaptive_prompt_policy_compacts_when_budget_is_tight(tmp_path):
    config = KYCortexConfig(
        output_dir=str(tmp_path / "output"),
        adaptive_prompt_policy_enabled=True,
        adaptive_prompt_compact_threshold_tokens=1200,
    )

    policy = resolve_adaptive_prompt_policy(
        config,
        provider_name="openai",
        model_name="gpt-4o",
        capabilities=get_capabilities("openai", "gpt-4o"),
        max_tokens=1100,
    )

    assert policy.mode == "compact"
    assert policy.compression_enabled is True
