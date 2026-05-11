# Environment Parity - 1e68a8b

Status: preflight parity captured; canary traffic admitted through the 10-workflows checkpoint

## Candidate and Runtime

- candidate tag: `v1.0.13b2`
- candidate commit: `1e68a8bc8e6371b6b425e1ac9ce04e3677141628`
- parity capture time: `2026-05-11T11:02:46Z`
- execution host class: maintainer-operated pre-production runtime

## Provider Parity

- enabled providers for admitted evidence: `anthropic`, `openai`, `ollama`
- provider models used across smoke01-smoke04:
  - anthropic: `claude-haiku-4-5-20251001`
  - openai: `gpt-4o-mini`
  - ollama: `qwen2.5-coder:7b`
- the first four smoke batches completed with all provider/scenario cells accepted, including the replacement `anthropic=baseline` smoke04 cell.

## Persistence and Validation Parity

- persisted workflow state evidence is available under:
  - `output/canary_1e68a8b_smoke01/`
  - `output/canary_1e68a8b_smoke02/`
  - `output/canary_1e68a8b_smoke03/`
  - `output/canary_1e68a8b_smoke04/`
- every admitted run retained repository-owned artifacts plus persisted validation metadata proving syntax, public-contract, and import checks passed.

## Sandbox and Release Settings Parity

- release candidate identity is fixed to published `v1.0.13b2`
- admission runs use the repository-standard workflow generation and validation contracts
- no environment override is recorded at bundle-open time

## Gate Interpretation

Parity evidence remains sufficient to keep the replacement beta canary window open.
The 10-workflows checkpoint is recorded; the next operational step is the `25-workflows` checkpoint.