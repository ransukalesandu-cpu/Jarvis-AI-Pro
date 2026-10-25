import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.ai_error_repair import analyze_error, build_repair_prompt, redact_secrets


class AIErrorRepairTests(unittest.TestCase):
    def test_redacts_common_api_key_fields(self):
        text = 'api_key=sk-abcdefghijk123 password:supersecret Authorization: Bearer abcdefghijk'
        result = redact_secrets(text)
        self.assertNotIn('supersecret', result)
        self.assertNotIn('abcdefghijk', result)
        self.assertIn('[REDACTED]', result)

    def test_prompt_bounds_and_marks_source_untrusted(self):
        prompt = build_repair_prompt('Traceback ' + ('x' * 20000), 'print("hello")')
        self.assertIn('untrusted', prompt)
        self.assertIn('proposed diff', prompt)
        self.assertLess(len(prompt), 30000)

    def test_groq_is_preferred_and_suggestion_is_never_auto_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'api_keys.json'
            config.write_text(json.dumps({'groq_api_key': 'test-key'}), encoding='utf-8')
            router = Mock()
            router.query.return_value = {
                'text': 'Root cause: typo. Proposed diff: ...',
                'provider': 'groq',
                'model': 'test-model',
                'mode': 'cloud',
                'latency_ms': 12,
            }
            factory = Mock(return_value=router)
            result = analyze_error(
                'NameError: missing_name',
                config_path=config,
                router_factory=factory,
            )
            factory.assert_called_once()
            self.assertEqual(factory.call_args.kwargs['preferred_provider'], 'groq')
            self.assertFalse(factory.call_args.kwargs['online_check'])
            router.query.assert_called_once()
            self.assertEqual(result['provider'], 'groq')
            self.assertFalse(result['applied'])
            self.assertTrue(result['requires_review'])

    def test_empty_error_rejected(self):
        with self.assertRaises(ValueError):
            analyze_error('  ')


if __name__ == '__main__':
    unittest.main()
