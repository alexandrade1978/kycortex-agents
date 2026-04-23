"""Tests for architect module standalone functions."""

from kycortex_agents.agents.architect import _low_budget_architecture_section, _architecture_request_block, ArchitectAgent
from kycortex_agents.config import KYCortexConfig


class TestArchitectFunctions:
    """Test standalone functions in architect module."""

    def test_low_budget_architecture_section_valid_tokens(self):
        """Test low budget section with valid token count."""
        result = _low_budget_architecture_section(500)
        assert isinstance(result, str)
        assert "budget" in result.lower()
        assert "compact" in result.lower()

    def test_low_budget_architecture_section_max_tokens(self):
        """Test low budget section with max allowed tokens."""
        result = _low_budget_architecture_section(1200)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_low_budget_architecture_section_zero_tokens(self):
        """Test low budget section with zero tokens returns empty string."""
        result = _low_budget_architecture_section(0)
        assert result == ""

    def test_low_budget_architecture_section_negative_tokens(self):
        """Test low budget section with negative tokens returns empty string."""
        result = _low_budget_architecture_section(-100)
        assert result == ""

    def test_low_budget_architecture_section_over_max_tokens(self):
        """Test low budget section with tokens over 1200 returns empty string."""
        result = _low_budget_architecture_section(1300)
        assert result == ""

    def test_low_budget_architecture_section_non_integer_tokens(self):
        """Test low budget section with non-integer tokens returns empty string."""
        result = _low_budget_architecture_section("500")
        assert result == ""
        
        result = _low_budget_architecture_section(None)
        assert result == ""
        
        result = _low_budget_architecture_section(50.5)
        assert result == ""

    def test_low_budget_architecture_section_respects_adaptive_non_compact_mode(self):
        """Test low budget section is suppressed when adaptive mode is not compact."""
        result = _low_budget_architecture_section(500, prompt_mode="rich")
        assert result == ""

    def test_architecture_request_block_empty_context(self):
        """Test request block with empty context."""
        result = _architecture_request_block({})
        assert isinstance(result, str)
        assert "architecture" in result.lower() or "design" in result.lower()

    def test_architecture_request_block_budget_compaction_mode(self):
        """Test request block in budget compaction mode."""
        context = {"decomposition_mode": "budget_compaction_planner"}
        result = _architecture_request_block(context)
        assert isinstance(result, str)
        assert "compact" in result.lower() or "budget" in result.lower()

    def test_architecture_request_block_regular_mode(self):
        """Test request block in regular (non-budget) mode."""
        context = {"decomposition_mode": "regular"}
        result = _architecture_request_block(context)
        assert isinstance(result, str)
        # Regular mode should include more detailed guidance
        assert len(result) > 100

    def test_architecture_request_block_non_dict_context(self):
        """Test request block with non-dict context."""
        # Non-dict context should be treated as empty dict
        result = _architecture_request_block("not a dict")
        assert isinstance(result, str)
        assert len(result) > 0
        
        result = _architecture_request_block(None)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_architecture_request_block_other_modes(self):
        """Test request block with other decomposition modes."""
        context = {"decomposition_mode": "other_mode"}
        result = _architecture_request_block(context)
        # Should use regular mode for unknown decomposition modes
        assert isinstance(result, str)
        assert len(result) > 100


class TestArchitectAgentCoverage:
    """Test ArchitectAgent methods to improve coverage."""

    def test_architect_run_with_task_public_contract_anchor(self, monkeypatch, tmp_path):
        """Test ArchitectAgent.run() with non-empty task_public_contract_anchor."""
        # Create a minimal config
        config = KYCortexConfig(
            output_dir=str(tmp_path / "output"),
            api_key="test-key"
        )
        
        agent = ArchitectAgent(config)
        
        # Mock the chat method to avoid actual API call
        call_args = []
        def mock_chat(system_prompt, user_msg):
            call_args.append((system_prompt, user_msg))
            return "Mock architecture response"
        
        monkeypatch.setattr(agent, "chat", mock_chat)
        
        # Call run() with task_public_contract_anchor containing actual content
        context = {
            "goal": "Build a module",
            "task_public_contract_anchor": "def process() -> str: ...",
            "provider_max_tokens": 500
        }
        
        result = agent.run("Design a system", context)
        
        # Verify the result
        assert result == "Mock architecture response"
        # Verify that chat was called
        assert len(call_args) == 1
        system_prompt, user_msg = call_args[0]
        # Verify that the contract anchor is included in the message
        assert "task_public_contract_anchor" not in user_msg  # The label shouldn't appear
        assert "def process() -> str" in user_msg

    def test_architect_run_with_empty_contract_anchor(self, monkeypatch, tmp_path):
        """Test ArchitectAgent.run() with empty task_public_contract_anchor."""
        config = KYCortexConfig(
            output_dir=str(tmp_path / "output"),
            api_key="test-key"
        )
        
        agent = ArchitectAgent(config)
        
        call_args = []
        def mock_chat(system_prompt, user_msg):
            call_args.append((system_prompt, user_msg))
            return "Mock response"
        
        monkeypatch.setattr(agent, "chat", mock_chat)
        
        # Call with empty contract anchor
        context = {
            "goal": "Build a module",
            "task_public_contract_anchor": "",  # Empty
            "provider_max_tokens": 500
        }
        
        result = agent.run("Design a system", context)
        
        assert result == "Mock response"
        # Verify contract section is not in the message
        _, user_msg = call_args[0]
        # When anchor is empty, "Task-level public contract" should not appear
        assert "Task-level public contract" not in user_msg
