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

Provider failures are normalized into `AgentExecutionError`, so the rest of the runtime can apply the same retry, persistence, and logging behavior regardless of backend.

## Provider Selection

Provider selection is driven by `KYCortexConfig.llm_provider`.

Supported values are:

- `openai`
- `anthropic`
- `ollama`

`create_provider()` validates runtime configuration first and then resolves the configured provider through the built-in provider map.

## OpenAI Configuration

Use the OpenAI provider when `llm_provider="openai"`.

- Environment variable fallback: `OPENAI_API_KEY`
- Required runtime fields: valid API key, model name
- API style: OpenAI chat completions
- Metadata captured: prompt, completion, and total token counts when the backend returns usage information

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
- Metadata captured: input, output, total, and cache-related token counts when the backend returns usage information

Example:

```python
from kycortex_agents import KYCortexConfig
from kycortex_agents.providers import create_provider

config = KYCortexConfig(
    llm_provider="anthropic",
    llm_model="claude-3-5-sonnet-latest",
    api_key="your-anthropic-key",
)

provider = create_provider(config)
```

## Ollama Configuration

Use the Ollama provider when `llm_provider="ollama"`.

- No API key required by default
- Default base URL: `http://localhost:11434`
- Required runtime fields: model name plus a valid base URL when the default is overridden
- API style: HTTP POST to the Ollama `/api/generate` endpoint
- Metadata captured: prompt/output token counts plus timing information derived from Ollama duration fields

Example:

```python
from kycortex_agents import KYCortexConfig
from kycortex_agents.providers import create_provider

config = KYCortexConfig(
    llm_provider="ollama",
    llm_model="llama3",
    base_url="http://localhost:11434",
)

provider = create_provider(config)
```

## Runtime Validation Rules

`KYCortexConfig.validate_runtime()` enforces provider-specific requirements before instantiation:

- unsupported `llm_provider` values fail fast
- OpenAI and Anthropic require credentials through `api_key` or the matching environment variable
- Ollama requires a usable `base_url`

These checks are intentionally centralized in configuration so provider instantiation errors remain predictable.

## Metadata and Observability

The built-in providers expose different metadata shapes, but they all flow back through the same runtime path into task state and snapshots.

- OpenAI: usage token counts
- Anthropic: usage token counts plus cache token details when present
- Ollama: usage token counts plus duration metrics converted to milliseconds

This metadata is later attached to task outputs, execution events, and persisted project state for post-run inspection.

## Error Handling

The provider layer normalizes backend problems into runtime-safe failures:

- invalid response payloads become `AgentExecutionError`
- empty backend responses become `AgentExecutionError`
- SDK, HTTP, timeout, and decode failures become `AgentExecutionError`

This keeps retry behavior and workflow-failure policy handling consistent across vendors.

## Extension Path

Custom providers should implement `BaseLLMProvider` and return metadata through `get_last_call_metadata()` when they want observability data to flow through the rest of the runtime.

If a project needs a non-built-in backend, the cleanest extension path is:

1. implement a provider that satisfies `BaseLLMProvider`
2. instantiate it in custom runtime setup
3. inject it into custom agents or a provider-aware customization layer

The built-in `create_provider()` helper remains the canonical path for the supported OpenAI, Anthropic, and Ollama integrations.