class KYCortexError(Exception):
    """Base exception for KYCortex runtime errors."""


class AgentExecutionError(KYCortexError):
    """Raised when an agent cannot produce a valid response."""
