import os
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class KYCortexConfig:
    """Global configuration for KYCortex agent system."""
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"
    api_key: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 4096
    project_name: str = "kycortex-project"
    output_dir: str = "./output"
    log_level: str = "INFO"

    def __post_init__(self):
        if self.api_key is None:
            self.api_key = os.environ.get("OPENAI_API_KEY", "")
        os.makedirs(self.output_dir, exist_ok=True)

DEFAULT_CONFIG = KYCortexConfig()
