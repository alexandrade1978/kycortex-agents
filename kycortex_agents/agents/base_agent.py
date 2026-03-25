from abc import ABC, abstractmethod
import random
import re
from time import perf_counter, sleep
from typing import Any, Optional

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, ProviderTransientError
from kycortex_agents.providers.base import BaseLLMProvider
from kycortex_agents.providers.factory import create_provider
from kycortex_agents.types import AgentInput, AgentOutput, ArtifactRecord, ArtifactType


class BaseAgent(ABC):
    """Base class for public agent extensions.

    Subclasses typically implement `run()` or `run_with_input()` and may override
    lifecycle hooks to add validation, output shaping, or error handling.
    """

    """Context keys that must be present before execution starts."""
    required_context_keys: tuple[str, ...] = ()
    output_artifact_type: ArtifactType = ArtifactType.TEXT
    output_artifact_name: str = "output"

    def __init__(self, name: str, role: str, config: KYCortexConfig):
        self.name = name
        self.role = role
        self.config = config
        self._provider: Optional[BaseLLMProvider] = None
        self._last_provider_call_metadata: Optional[dict[str, Any]] = None
        self._provider_call_count = 0
        self._provider_transient_failure_streak = 0
        self._provider_circuit_open_until = 0.0

    def _get_provider(self) -> BaseLLMProvider:
        if self._provider is None:
            self._provider = create_provider(self.config)
        return self._provider

    def chat(self, system_prompt: str, user_message: str) -> str:
        provider = self._get_provider()
        started_at = perf_counter()
        current_time = started_at
        if self._is_provider_circuit_open(current_time):
            remaining_seconds = round(max(self._provider_circuit_open_until - current_time, 0.0), 6)
            message = f"{self.name}: provider circuit breaker is open for {remaining_seconds:g} more seconds"
            self._last_provider_call_metadata = {
                "provider": self.config.llm_provider,
                "model": self.config.llm_model,
                "success": False,
                "duration_ms": round((perf_counter() - started_at) * 1000, 3),
                "error_type": "AgentExecutionError",
                "error_message": message.removeprefix(f"{self.name}: "),
                "retryable": False,
                "attempts_used": 0,
                "max_attempts": self.config.provider_max_attempts,
                "attempt_history": [],
                **self._provider_elapsed_budget_metadata(started_at, current_time),
                **self._provider_circuit_metadata(current_time),
            }
            raise AgentExecutionError(message)
        max_attempts = self.config.provider_max_attempts
        attempt_history: list[dict[str, Any]] = []
        for attempt in range(1, max_attempts + 1):
            current_time = perf_counter()
            if self._is_provider_elapsed_budget_exhausted(started_at, current_time):
                message = (
                    f"{self.name}: provider elapsed budget exhausted after "
                    f"{current_time - started_at:g} seconds"
                )
                self._last_provider_call_metadata = {
                    "provider": self.config.llm_provider,
                    "model": self.config.llm_model,
                    "success": False,
                    "duration_ms": round((current_time - started_at) * 1000, 3),
                    "error_type": "AgentExecutionError",
                    "error_message": message.removeprefix(f"{self.name}: "),
                    "retryable": False,
                    "attempts_used": len(attempt_history),
                    "max_attempts": max_attempts,
                    "attempt_history": list(attempt_history),
                    **self._provider_call_budget_metadata(),
                    **self._provider_elapsed_budget_metadata(started_at, current_time),
                    **self._provider_circuit_metadata(current_time),
                }
                raise AgentExecutionError(message)
            if self._is_provider_call_budget_exhausted():
                message = (
                    f"{self.name}: provider call budget exhausted after "
                    f"{self._provider_call_count} calls"
                )
                self._last_provider_call_metadata = {
                    "provider": self.config.llm_provider,
                    "model": self.config.llm_model,
                    "success": False,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 3),
                    "error_type": "AgentExecutionError",
                    "error_message": message.removeprefix(f"{self.name}: "),
                    "retryable": False,
                    "attempts_used": len(attempt_history),
                    "max_attempts": max_attempts,
                    "attempt_history": list(attempt_history),
                    **self._provider_call_budget_metadata(),
                    **self._provider_elapsed_budget_metadata(started_at, current_time),
                    **self._provider_circuit_metadata(current_time),
                }
                raise AgentExecutionError(message)
            try:
                self._provider_call_count += 1
                response = provider.generate(system_prompt, user_message)
                self._reset_provider_circuit_breaker()
                attempt_history.append(
                    {
                        "attempt": attempt,
                        "success": True,
                        "retryable": False,
                        "backoff_seconds": 0.0,
                    }
                )
                break
            except ProviderTransientError as exc:
                uncapped_backoff_seconds = self.config.provider_retry_backoff_seconds * (2 ** (attempt - 1))
                max_backoff_seconds = self.config.provider_retry_max_backoff_seconds
                base_backoff_seconds = uncapped_backoff_seconds
                if max_backoff_seconds is not None:
                    base_backoff_seconds = min(base_backoff_seconds, max_backoff_seconds)
                jitter_seconds = 0.0
                if base_backoff_seconds > 0 and self.config.provider_retry_jitter_ratio > 0:
                    jitter_seconds = random.uniform(
                        0.0,
                        base_backoff_seconds * self.config.provider_retry_jitter_ratio,
                    )
                total_backoff_seconds = base_backoff_seconds + jitter_seconds
                attempt_history.append(
                    {
                        "attempt": attempt,
                        "success": False,
                        "retryable": True,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "uncapped_backoff_seconds": round(uncapped_backoff_seconds, 6),
                        "base_backoff_seconds": round(base_backoff_seconds, 6),
                        "jitter_seconds": round(jitter_seconds, 6),
                        "backoff_seconds": round(total_backoff_seconds, 6),
                    }
                )
                self._last_provider_call_metadata = {
                    "provider": self.config.llm_provider,
                    "model": self.config.llm_model,
                    "success": False,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 3),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "retryable": True,
                    "attempts_used": attempt,
                    "max_attempts": max_attempts,
                    "attempt_history": list(attempt_history),
                    **self._provider_call_budget_metadata(),
                    **self._provider_elapsed_budget_metadata(started_at, perf_counter()),
                }
                if attempt >= max_attempts:
                    self._record_provider_transient_failure(perf_counter())
                    self._last_provider_call_metadata.update(self._provider_circuit_metadata(perf_counter()))
                    raise AgentExecutionError(f"{self.name}: {exc}") from exc
                remaining_elapsed_budget = self._provider_elapsed_budget_remaining_seconds(
                    started_at,
                    perf_counter(),
                )
                if remaining_elapsed_budget is not None and total_backoff_seconds >= remaining_elapsed_budget:
                    current_time = perf_counter()
                    message = (
                        f"{self.name}: provider elapsed budget exhausted after "
                        f"{current_time - started_at:g} seconds"
                    )
                    self._last_provider_call_metadata = {
                        "provider": self.config.llm_provider,
                        "model": self.config.llm_model,
                        "success": False,
                        "duration_ms": round((current_time - started_at) * 1000, 3),
                        "error_type": "AgentExecutionError",
                        "error_message": message.removeprefix(f"{self.name}: "),
                        "retryable": False,
                        "attempts_used": attempt,
                        "max_attempts": max_attempts,
                        "attempt_history": list(attempt_history),
                        **self._provider_call_budget_metadata(),
                        **self._provider_elapsed_budget_metadata(started_at, current_time),
                        **self._provider_circuit_metadata(current_time),
                    }
                    raise AgentExecutionError(message) from exc
                if total_backoff_seconds > 0:
                    sleep(total_backoff_seconds)
            except Exception as exc:
                self._reset_provider_circuit_breaker()
                attempt_history.append(
                    {
                        "attempt": attempt,
                        "success": False,
                        "retryable": False,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "backoff_seconds": 0.0,
                    }
                )
                self._last_provider_call_metadata = {
                    "provider": self.config.llm_provider,
                    "model": self.config.llm_model,
                    "success": False,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 3),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "retryable": False,
                    "attempts_used": attempt,
                    "max_attempts": max_attempts,
                    "attempt_history": list(attempt_history),
                    **self._provider_call_budget_metadata(),
                    **self._provider_elapsed_budget_metadata(started_at, perf_counter()),
                    **self._provider_circuit_metadata(perf_counter()),
                }
                if isinstance(exc, AgentExecutionError):
                    raise AgentExecutionError(f"{self.name}: {exc}") from exc
                raise AgentExecutionError(f"{self.name} failed to call the model provider") from exc
        self._last_provider_call_metadata = {
            "provider": self.config.llm_provider,
            "model": self.config.llm_model,
            "success": True,
            "duration_ms": round((perf_counter() - started_at) * 1000, 3),
            "error_type": None,
            "attempts_used": attempt,
            "max_attempts": max_attempts,
            "attempt_history": list(attempt_history),
            **self._provider_call_budget_metadata(),
            **self._provider_elapsed_budget_metadata(started_at, perf_counter()),
            **self._provider_circuit_metadata(perf_counter()),
        }
        provider_metadata = provider.get_last_call_metadata()
        if provider_metadata is not None:
            self._last_provider_call_metadata.update(provider_metadata)
        return response

    def _is_provider_circuit_open(self, current_time: float) -> bool:
        if self.config.provider_circuit_breaker_threshold <= 0:
            return False
        return current_time < self._provider_circuit_open_until

    def _is_provider_call_budget_exhausted(self) -> bool:
        if self.config.provider_max_calls_per_agent <= 0:
            return False
        return self._provider_call_count >= self.config.provider_max_calls_per_agent

    def _is_provider_elapsed_budget_exhausted(self, started_at: float, current_time: float) -> bool:
        if self.config.provider_max_elapsed_seconds_per_call <= 0:
            return False
        return (current_time - started_at) >= self.config.provider_max_elapsed_seconds_per_call

    def _provider_elapsed_budget_remaining_seconds(
        self,
        started_at: float,
        current_time: float,
    ) -> Optional[float]:
        if self.config.provider_max_elapsed_seconds_per_call <= 0:
            return None
        return max(
            self.config.provider_max_elapsed_seconds_per_call - (current_time - started_at),
            0.0,
        )

    def _record_provider_transient_failure(self, current_time: float) -> None:
        if self.config.provider_circuit_breaker_threshold <= 0:
            self._provider_transient_failure_streak = 0
            self._provider_circuit_open_until = 0.0
            return
        self._provider_transient_failure_streak += 1
        if self._provider_transient_failure_streak >= self.config.provider_circuit_breaker_threshold:
            self._provider_circuit_open_until = (
                current_time + self.config.provider_circuit_breaker_cooldown_seconds
            )

    def _reset_provider_circuit_breaker(self) -> None:
        self._provider_transient_failure_streak = 0
        self._provider_circuit_open_until = 0.0

    def _provider_circuit_metadata(self, current_time: float) -> dict[str, Any]:
        remaining_seconds = 0.0
        if self._is_provider_circuit_open(current_time):
            remaining_seconds = max(self._provider_circuit_open_until - current_time, 0.0)
        return {
            "circuit_breaker_open": self._is_provider_circuit_open(current_time),
            "circuit_breaker_failure_streak": self._provider_transient_failure_streak,
            "circuit_breaker_threshold": self.config.provider_circuit_breaker_threshold,
            "circuit_breaker_cooldown_seconds": round(
                self.config.provider_circuit_breaker_cooldown_seconds,
                6,
            ),
            "circuit_breaker_remaining_seconds": round(remaining_seconds, 6),
        }

    def _provider_call_budget_metadata(self) -> dict[str, Any]:
        remaining_calls: Optional[int] = None
        if self.config.provider_max_calls_per_agent > 0:
            remaining_calls = max(
                self.config.provider_max_calls_per_agent - self._provider_call_count,
                0,
            )
        return {
            "provider_call_count": self._provider_call_count,
            "provider_max_calls_per_agent": self.config.provider_max_calls_per_agent,
            "provider_remaining_calls": remaining_calls,
        }

    def _provider_elapsed_budget_metadata(
        self,
        started_at: float,
        current_time: float,
    ) -> dict[str, Any]:
        elapsed_seconds = max(current_time - started_at, 0.0)
        return {
            "provider_elapsed_seconds": round(elapsed_seconds, 6),
            "provider_max_elapsed_seconds_per_call": round(
                self.config.provider_max_elapsed_seconds_per_call,
                6,
            ),
            "provider_remaining_elapsed_seconds": (
                None
                if self.config.provider_max_elapsed_seconds_per_call <= 0
                else round(
                    self._provider_elapsed_budget_remaining_seconds(started_at, current_time) or 0.0,
                    6,
                )
            ),
        }

    def run_with_input(self, agent_input: AgentInput) -> str | AgentOutput:
        return self.run(agent_input.task_description, agent_input.context)

    def execute(self, agent_input: AgentInput) -> AgentOutput:
        self.validate_input(agent_input)
        self.before_execute(agent_input)
        try:
            result = self.run_with_input(agent_input)
            output = self._normalize_output(result, agent_input)
            return self.after_execute(agent_input, output)
        except Exception as exc:
            self.on_execution_error(agent_input, exc)
            raise AssertionError("on_execution_error must raise an exception") from exc

    def validate_input(self, agent_input: AgentInput) -> None:
        """Validate the public AgentInput contract before agent execution."""
        if not agent_input.task_id.strip():
            raise AgentExecutionError(f"{self.name}: task_id must not be empty")
        if not agent_input.task_title.strip():
            raise AgentExecutionError(f"{self.name}: task_title must not be empty")
        if not agent_input.task_description.strip():
            raise AgentExecutionError(f"{self.name}: task_description must not be empty")
        if not agent_input.project_name.strip():
            raise AgentExecutionError(f"{self.name}: project_name must not be empty")
        if not isinstance(agent_input.context, dict):
            raise AgentExecutionError(f"{self.name}: context must be a dictionary")
        for key in self.required_context_keys:
            value = agent_input.context.get(key)
            if value is None:
                raise AgentExecutionError(f"{self.name}: required context key '{key}' is missing")
            if isinstance(value, str) and not value.strip():
                raise AgentExecutionError(f"{self.name}: required context key '{key}' must not be empty")

    def before_execute(self, agent_input: AgentInput) -> None:
        """Hook invoked after input validation and before the agent runs."""
        return None

    def after_execute(self, agent_input: AgentInput, output: AgentOutput) -> AgentOutput:
        """Hook invoked after normalization to finalize the public AgentOutput."""
        output = self._normalize_output_for_artifact_type(output)
        self.validate_output(output)
        output.metadata.setdefault("agent_name", self.name)
        output.metadata.setdefault("agent_role", self.role)
        output.metadata.setdefault("task_id", agent_input.task_id)
        output.metadata.setdefault("project_name", agent_input.project_name)
        if self._last_provider_call_metadata is not None:
            output.metadata.setdefault("provider_call", dict(self._last_provider_call_metadata))
        if not output.artifacts:
            output.artifacts.append(self._build_default_artifact(agent_input, output))
        return output

    def _normalize_output_for_artifact_type(self, output: AgentOutput) -> AgentOutput:
        if self.output_artifact_type not in {ArtifactType.CODE, ArtifactType.TEST}:
            return output
        normalized_raw_content = self._extract_code_content(output.raw_content)
        if normalized_raw_content == output.raw_content:
            return output
        output.raw_content = normalized_raw_content
        output.summary = self._summarize_output(normalized_raw_content)
        return output

    def _extract_code_content(self, raw_content: str) -> str:
        code_blocks = re.findall(r"```(?:[A-Za-z0-9_+-]+)?\n(.*?)```", raw_content, flags=re.DOTALL)
        if not code_blocks:
            return self._extract_code_like_lines(raw_content)
        normalized_blocks = [block.strip() for block in code_blocks if block.strip()]
        if not normalized_blocks:
            return self._extract_code_like_lines(raw_content)
        return "\n\n".join(normalized_blocks)

    def _extract_code_like_lines(self, raw_content: str) -> str:
        lines = raw_content.strip().splitlines()
        start_index: Optional[int] = None
        code_start_pattern = re.compile(
            r"^(from\s+\S+\s+import\s+.+|import\s+\S+|class\s+\w+|def\s+\w+|async\s+def\s+\w+|@\w+|if\s+__name__\s*==\s*['\"]__main__['\"]\s*:|[A-Za-z_][A-Za-z0-9_]*\s*=)"
        )
        for index, line in enumerate(lines):
            stripped = line.strip()
            if code_start_pattern.match(stripped):
                start_index = index
                break
        if start_index is None:
            return raw_content
        candidate = "\n".join(lines[start_index:]).strip()
        return candidate or raw_content

    def validate_output(self, output: AgentOutput) -> None:
        """Validate the public AgentOutput contract before state is persisted."""
        if not output.raw_content.strip():
            raise AgentExecutionError(f"{self.name}: agent output raw_content must not be empty")
        if not output.summary.strip():
            raise AgentExecutionError(f"{self.name}: agent output summary must not be empty")
        if not isinstance(output.artifacts, list):
            raise AgentExecutionError(f"{self.name}: agent output artifacts must be a list")
        if not isinstance(output.decisions, list):
            raise AgentExecutionError(f"{self.name}: agent output decisions must be a list")
        if not isinstance(output.metadata, dict):
            raise AgentExecutionError(f"{self.name}: agent output metadata must be a dictionary")

    def on_execution_error(self, agent_input: AgentInput, exc: Exception) -> None:
        """Hook invoked for execution failures before the final public error is raised."""
        if isinstance(exc, AgentExecutionError):
            raise exc
        raise AgentExecutionError(f"{self.name} failed during agent execution") from exc

    def _normalize_output(self, result: Any, agent_input: AgentInput) -> AgentOutput:
        if isinstance(result, AgentOutput):
            if not result.summary.strip():
                result.summary = self._summarize_output(result.raw_content)
            return result
        if not isinstance(result, str):
            raise AgentExecutionError(f"{self.name}: agent output must be a string or AgentOutput")
        if not result.strip():
            raise AgentExecutionError(f"{self.name}: agent output must not be empty")
        return AgentOutput(
            summary=self._summarize_output(result),
            raw_content=result,
            metadata={
                "agent_name": self.name,
                "agent_role": self.role,
                "task_id": agent_input.task_id,
            },
        )

    def _summarize_output(self, raw_content: str) -> str:
        first_line = raw_content.strip().splitlines()[0].strip()
        return first_line[:120]

    def _build_default_artifact(self, agent_input: AgentInput, output: AgentOutput) -> ArtifactRecord:
        return ArtifactRecord(
            name=f"{agent_input.task_id}_{self.output_artifact_name}",
            artifact_type=self.output_artifact_type,
            content=output.raw_content,
            metadata={
                "agent_name": self.name,
                "task_id": agent_input.task_id,
                "project_name": agent_input.project_name,
            },
        )

    def require_context_value(self, agent_input: AgentInput, key: str) -> Any:
        value = agent_input.context.get(key)
        if value is None:
            raise AgentExecutionError(f"{self.name}: required context key '{key}' is missing")
        if isinstance(value, str) and not value.strip():
            raise AgentExecutionError(f"{self.name}: required context key '{key}' must not be empty")
        return value

    def get_last_provider_call_metadata(self) -> Optional[dict[str, Any]]:
        if self._last_provider_call_metadata is None:
            return None
        return dict(self._last_provider_call_metadata)

    @abstractmethod
    def run(self, task_description: str, context: dict) -> str | AgentOutput:
        pass

    def __repr__(self):
        return f"<Agent name={self.name} role={self.role}>"
