class KYCortexError(Exception):
    """Base exception for KYCortex runtime errors."""


class AgentExecutionError(KYCortexError):
    """Raised when an agent cannot produce a valid response."""


class ProviderConfigurationError(KYCortexError):
    """Raised when the configured LLM provider is not supported."""
