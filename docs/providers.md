# Provider Guide

This guide explains how the built-in provider layer works, how providers are selected, and what runtime differences matter when configuring OpenAI, Anthropic, or Ollama.

## Provider Architecture

The provider layer isolates model-specific backend calls from agent and orchestrator logic.

- `BaseLLMProvider` defines the shared contract used by the runtime.
- `create_provider(config)` selects the built-in provider implementation for the configured backend.
- `OpenAIProvider`, `AnthropicProvider`, and `OllamaProvider` adapt backend-specific APIs into the same runtime interface.

Agents call providers through this shared abstraction, which keeps orchestration logic independent from any one vendor SDK.

## Common Contract

All built-in providers implement the same public entrypoints:

- `generate(system_prompt, user_message)`: execute a model call and return the generated text response.
- `get_last_call_metadata()`: return provider-specific usage and timing metadata captured from the most recent successful call when available.
- `health_check()`: return a lightweight provider health snapshot without generating model output.

Provider implementations surface two operational failure classes:

- `ProviderTransientError` for retryable backend conditions such as rate limits, timeouts, temporary network failures, and transient service unavailability
- `AgentExecutionError` for deterministic invalid requests, invalid payloads, unsupported backend behavior, or explicit unhealthy states that should fail fast

The agent runtime consumes those two classes to apply retries, fallback routing, circuit breaking, persistence, and workflow failure policy consistently across providers.

## Provider Selection

Provider selection is driven by `KYCortexConfig.llm_provider`.

Supported values are:

- `openai`
- `anthropic`
- `ollama`

`create_provider()` validates runtime configuration first and then resolves the configured provider through the built-in provider map.

`probe_provider_health()` is the matching public helper when callers need a structured provider-readiness snapshot before generation. Providers that do not implement an active probe return a passive `ready` snapshot, while built-in providers can report active reachability results, explicit model-readiness outcomes, and unhealthy snapshots. The runtime also reuses cached unhealthy health snapshots during a configured cooldown window so repeated calls do not keep probing the same failing backend again immediately.

## Runtime Resilience Controls

The provider layer is consumed by `BaseAgent`, which applies the production-facing resilience controls configured through `KYCortexConfig`.

- Per-provider request deadlines through `provider_timeout_seconds`
- Retry policy with capped backoff and jitter through `provider_max_attempts`, `provider_retry_backoff_seconds`, `provider_retry_max_backoff_seconds`, and `provider_retry_jitter_ratio`
- Per-agent and per-provider call budgets through `provider_max_calls_per_agent` and `provider_max_calls_per_provider`
- Aggregate elapsed-time limits through `provider_max_elapsed_seconds_per_call`
- Provider fallback routing through `provider_fallback_order` and `provider_fallback_models`
- Multi-model provider routing through `llm_model_candidates` (primary provider) and ordered `provider_fallback_models` values (fallback providers)
- Circuit breaking through `provider_circuit_breaker_threshold` and `provider_circuit_breaker_cooldown_seconds`
- Health-probe cooldown caching through `provider_health_check_cooldown_seconds`
- Cooperative cancellation through `provider_cancellation_check_interval_seconds`

In practice, this means provider selection is not just a direct SDK call. The runtime can preflight provider health, skip providers whose circuit is open, reroute around exhausted quotas, and fall back to secondary providers before or after a failed generation attempt.

When multi-model routing is configured, the runtime evaluates ordered provider/model pairs. The primary provider is attempted as `llm_model` followed by `llm_model_candidates`, and each fallback provider is attempted in `provider_fallback_order` using the ordered model list declared in `provider_fallback_models`.

## OpenAI Configuration

Use the OpenAI provider when `llm_provider="openai"`.

- Environment variable fallback: `OPENAI_API_KEY`
- Required runtime fields: valid API key, model name
- API style: OpenAI chat completions
- Metadata captured: requested token budget, prompt/completion/total token counts, and `finish_reason` when the backend returns usage information
- Health probe behavior: validates backend reachability and confirms the configured model is present in the provider model list before generation begins

Example:

```python
from kycortex_agents import KYCortexConfig
from kycortex_agents.providers import create_provider

config = KYCortexConfig(
    llm_provider="openai",
    llm_model="gpt-4o-mini",
    api_key="your-openai-key",
)

provider = create_provider(config)
```

## Anthropic Configuration

Use the Anthropic provider when `llm_provider="anthropic"`.

- Environment variable fallback: `ANTHROPIC_API_KEY`
- Required runtime fields: valid API key, model name
- API style: Anthropic messages API
- Metadata captured: requested token budget, input/output/total/cache token counts, plus `stop_reason` and `stop_type` when the backend returns them
- Health probe behavior: validates backend reachability and confirms the configured model is present in the provider model list before generation begins

Example:

```python
from kycortex_agents import KYCortexConfig
from kycortex_agents.providers import create_provider

config = KYCortexConfig(
    llm_provider="anthropic",
    llm_model="claude-haiku-4-5-20251001",
    api_key="your-anthropic-key",
)

provider = create_provider(config)
```

## Ollama Configuration

Use the Ollama provider when `llm_provider="ollama"`.

- No API key required by default
- Default base URL: `http://localhost:11434`
- Required runtime fields: model name plus a valid base URL when the default is overridden
- Optional runtime field: `ollama_num_ctx` to request an explicit `num_ctx` value for larger-context local workflows
- Optional runtime field: `ollama_think` to explicitly control Ollama thinking mode (`true` or `false`)
- Repository-local empirical baseline: `qwen2.5-coder:7b` with `ollama_num_ctx=16384`
- API style: HTTP POST to the Ollama `/api/generate` endpoint
- Runtime token budget behavior: `max_tokens` is forwarded as Ollama `options.num_predict`
- Reasoning-model default: when `ollama_think` is unset, runtime requests disable implicit thinking (`think=false`) for reasoning-capable Qwen3-family models to keep bounded completion behavior under workflow timeouts
- Metadata captured: requested token budget, prompt/output token counts, `done_reason`, and timing information derived from Ollama duration fields
- Health probe behavior: queries `/api/tags`, validates the local endpoint is reachable, and confirms the configured model name is installed before generation begins

Example:

```python
from kycortex_agents import KYCortexConfig
from kycortex_agents.providers import create_provider

config = KYCortexConfig(
    llm_provider="ollama",
    llm_model="qwen2.5-coder:7b",
    base_url="http://localhost:11434",
    ollama_num_ctx=16384,
)

provider = create_provider(config)
```

The framework does not need Python-side GPU packages for Ollama usage because inference stays behind the Ollama HTTP API.
In practice, local usage only needs a reachable Ollama endpoint and the expected model installed on that Ollama instance.
If Ollama is running on another host or port, point `base_url` to that endpoint instead of the default.

## Runtime Validation Rules

`KYCortexConfig.validate_runtime()` enforces provider-specific requirements before instantiation:

- unsupported `llm_provider` values fail fast
- OpenAI and Anthropic require credentials through `api_key` or the matching environment variable
- Ollama requires a usable `base_url`

These checks are intentionally centralized in configuration so provider instantiation errors remain predictable.

## Metadata and Observability

The built-in providers expose different metadata shapes, but they all flow back through the same runtime path into task state and snapshots.

- OpenAI: requested token budget, usage token counts, and `finish_reason`
- Anthropic: requested token budget, usage token counts, cache token details, `stop_reason`, and `stop_type`
- Ollama: requested token budget, usage token counts, `done_reason`, and duration metrics converted to milliseconds

Health probes also flow through a shared shape:

- `status`: `ready`, `healthy`, `degraded`, or `failing`
- `active_check`: whether the provider performed a real probe instead of returning passive readiness
- `backend_reachable`: whether the health probe reached the backend successfully
- `model_ready`: whether the configured model is confirmed ready on that backend
- `retryable`: whether a failed probe indicates a transient condition
- `latency_ms`: elapsed probe latency for readiness checks

When a provider is reachable but the configured model is unavailable, the built-in providers report `status="failing"`, `backend_reachable=True`, and `model_ready=False`. This is treated as a deterministic failure so the runtime can fail fast or move to a fallback provider without burning transient retry budget.

Cached unhealthy health snapshots additionally expose:

- `cooldown_cached`: whether the snapshot came from the unhealthy-probe cache instead of a fresh provider call
- `cooldown_remaining_seconds`: how much unhealthy-probe cooldown remains before a fresh probe is attempted again

The agent runtime also emits higher-level provider execution metadata such as:

- `provider_health` across the whole execution plan, including `healthy`, `degraded`, `failing`, and `open_circuit` states
- `provider_budget` summaries derived from per-call budget metadata
- active-provider and fallback history
- provider timeout resolution by backend
- circuit-breaker state and remaining cooldown

This metadata is later persisted into task state and the internal runtime telemetry read model so retries, repair routing, and audits can reconstruct provider behavior. `ProjectState.internal_runtime_telemetry()` is now the dedicated operator-facing read path for exact provider/model, latency, usage, repair-budget, and provider-health telemetry. Public `workflow_telemetry`, per-task `resource_telemetry`, and provider-matrix `workflow_telemetry` payloads are removed from the current local public contract.

The current empirical maintenance baseline treats cloud-provider full-workflow runs as the primary comparison surface. OpenAI and Anthropic are currently tracked through that matrix, while Ollama validation still depends on a reachable local `/api/tags` endpoint and the configured model being installed on the local machine.

## Error Handling

The provider layer normalizes backend problems into runtime-safe failures, but not into a single exception type:

- invalid response payloads become `AgentExecutionError`
- empty backend responses become `AgentExecutionError`
- deterministic client-side request rejections such as 4xx validation failures become `AgentExecutionError`
- retryable backend failures such as 429s, transient 5xx responses, timeouts, and transport errors become `ProviderTransientError`
- deterministic model-readiness failures reported by health checks remain `AgentExecutionError`

This distinction is what allows the runtime to retry only retryable failures, open circuits only on transient failure streaks, and fail fast on deterministic invalid requests.

## Extension Path

Custom providers should implement `BaseLLMProvider`, return metadata through `get_last_call_metadata()` when they want observability data to flow through the rest of the runtime, and override `health_check()` when they can perform an active readiness probe.

For compatibility with legacy injected providers, the runtime also tolerates providers that omit `health_check()`. In that case the preflight path records a passive `ready` snapshot with `active_check=False` and continues to generation.

Custom provider implementations should also preserve the retryability split used by the built-in providers:

- raise `ProviderTransientError` for retryable outages
- raise `AgentExecutionError` for deterministic invalid states

If a project needs a non-built-in backend, the cleanest extension path is:

1. implement a provider that satisfies `BaseLLMProvider`
2. instantiate it in custom runtime setup
3. inject it into custom agents or a provider-aware customization layer

The built-in `create_provider()` and `probe_provider_health()` helpers remain the canonical public entrypoints for the supported OpenAI, Anthropic, and Ollama integrations.