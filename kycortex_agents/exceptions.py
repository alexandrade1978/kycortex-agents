class KYCortexError(Exception):
    """Base exception for KYCortex runtime errors."""


class AgentExecutionError(KYCortexError):
    """Raised when an agent cannot produce a valid response."""


class ProviderConfigurationError(KYCortexError):
    """Raised when the configured LLM provider is not supported."""


class ConfigValidationError(KYCortexError):
    """Raised when runtime configuration is invalid."""


class StatePersistenceError(KYCortexError):
    """Raised when project state cannot be saved or loaded safely."""
