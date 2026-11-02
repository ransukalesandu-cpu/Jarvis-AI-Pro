"""Structural contract tests for agent and protected action boundaries."""
from __future__ import annotations

import unittest

from core.action_loader import ActionRegistry
from core.agent_protocol import ActionGateway, ReasoningAgent
from core.brain_engine import BrainEngine


class AgentProtocolTests(unittest.TestCase):
    def test_brain_engine_implements_reasoning_agent_contract(self):
        self.assertIsInstance(BrainEngine(), ReasoningAgent)

    def test_action_registry_implements_dispatch_gateway_contract(self):
        registry = ActionRegistry({}, lambda _message: None)
        self.assertIsInstance(registry, ActionGateway)

    def test_agent_contract_does_not_expose_action_execution(self):
        self.assertFalse(hasattr(BrainEngine(), "run"))
        self.assertFalse(hasattr(BrainEngine(), "dispatch"))


if __name__ == "__main__":
    unittest.main()
