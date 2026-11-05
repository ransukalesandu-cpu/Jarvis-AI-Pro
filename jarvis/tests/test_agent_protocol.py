"""Structural contract tests for agent and protected action boundaries."""
from __future__ import annotations

import inspect
import unittest

from jarvis.core.action_loader import ActionRegistry
from jarvis.core.agent_protocol import ActionGateway, ReasoningAgent
from jarvis.core.brain_engine import BrainEngine


class AgentProtocolTests(unittest.TestCase):
    def test_brain_engine_implements_reasoning_agent_contract(self):
        self.assertIsInstance(BrainEngine(), ReasoningAgent)

    def test_reasoning_agent_signature_matches_supported_brain_keywords(self):
        parameters = inspect.signature(BrainEngine.respond).parameters
        self.assertNotIn("kwargs", parameters)
        self.assertEqual(
            set(parameters),
            {
                "self", "user_text", "base_system_prompt", "conversation_history",
                "project", "memory_enabled", "assistant_names", "assistant_name",
            },
        )

    def test_action_registry_implements_dispatch_gateway_contract(self):
        registry = ActionRegistry({}, lambda _message: None)
        self.assertIsInstance(registry, ActionGateway)

    def test_agent_contract_does_not_expose_action_execution(self):
        self.assertFalse(hasattr(BrainEngine(), "run"))
        self.assertFalse(hasattr(BrainEngine(), "dispatch"))


if __name__ == "__main__":
    unittest.main()
