__all__ = [
    "AgentExecutionError",
    "ConfigValidationError",
    "KYCortexError",
    "ProviderConfigurationError",
    "ProviderTransientError",
    "StatePersistenceError",
    "WorkflowDefinitionError",
]


class KYCortexError(Exception):
    """Base exception for KYCortex runtime errors."""


class AgentExecutionError(KYCortexError):
    """Raised when an agent cannot produce a valid response."""


class ProviderConfigurationError(KYCortexError):
    """Raised when the configured LLM provider is not supported."""


class ProviderTransientError(AgentExecutionError):
    """Raised when a provider call fails transiently and may succeed on retry."""


class ConfigValidationError(KYCortexError):
    """Raised when runtime configuration is invalid."""


class StatePersistenceError(KYCortexError):
    """Raised when project state cannot be saved or loaded safely."""


class WorkflowDefinitionError(KYCortexError):
    """Raised when the workflow graph is invalid or cannot be scheduled."""
