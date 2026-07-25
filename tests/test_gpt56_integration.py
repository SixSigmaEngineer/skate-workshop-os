import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ui"))

import app  # noqa: E402


class GPT56IntegrationTests(unittest.TestCase):
    def _settings(self, **overrides):
        settings = {
            "provider": "openai",
            "model": "gpt-5.6",
            "api_keys": {"openai": "test-key"},
            "openai_base_url": "https://api.openai.com/v1",
            "temperature": 0.7,
            "max_tokens": 1920,
            "reasoning_effort": "medium",
        }
        settings.update(overrides)
        return settings

    def test_gpt56_uses_responses_api_with_explicit_reasoning(self):
        with patch.object(app, "_post_json", return_value={"output_text": '{"ok":true}'}) as post:
            result = app._call_llm(self._settings(reasoning_effort="high"), "Return JSON.")

        self.assertEqual(result, '{"ok":true}')
        url, _headers, payload = post.call_args.args
        self.assertEqual(url, "https://api.openai.com/v1/responses")
        self.assertEqual(payload["model"], "gpt-5.6")
        self.assertEqual(payload["reasoning"], {"effort": "high"})
        self.assertEqual(payload["text"], {"format": {"type": "json_object"}})
        self.assertNotIn("temperature", payload)

    def test_spotter_routing_applies_model_and_reasoning(self):
        settings = self._settings(
            spotter_model="gpt-5.6-terra",
            spotter_reasoning_effort="low",
        )

        spotter = app._feature_settings(settings, "spotter")

        self.assertEqual(spotter["model"], "gpt-5.6-terra")
        self.assertEqual(spotter["reasoning_effort"], "low")

    def test_grind_inherits_general_model_and_reasoning(self):
        settings = self._settings(
            model="gpt-5.6-luna",
            reasoning_effort="xhigh",
            grind_model="another-model",
            grind_reasoning_effort="none",
        )

        grind = app._grind_settings(settings)

        self.assertEqual(grind["provider"], "openai")
        self.assertEqual(grind["model"], "gpt-5.6-luna")
        self.assertEqual(grind["reasoning_effort"], "xhigh")

    def test_grind_insights_calls_selected_general_route(self):
        settings = self._settings(model="gpt-5.6-terra", reasoning_effort="high")
        response = (
            '{"pains":[{"title":"Repeated handoff","summary":"People repeat context."}],'
            '"hmw_prompts":[{"prompt":"How might we carry context forward?","source_title":"Handoff"}],'
            '"solutions":[{"title":"Continuity brief","summary":"Test a concise shared brief."}]}'
        )
        with (
            patch.object(app, "_load_settings", return_value=settings),
            patch.object(app, "_call_llm", return_value=response) as call,
        ):
            result = app._grind_insights([], {"nodes": [], "links": [], "stats": {}})

        routed_settings = call.call_args.args[0]
        self.assertEqual(routed_settings["model"], "gpt-5.6-terra")
        self.assertEqual(routed_settings["reasoning_effort"], "high")
        self.assertEqual(result["mode"], "ai")
        self.assertEqual(result["model"], "gpt-5.6-terra")
        self.assertEqual(len(result["pains"]), 1)
        self.assertEqual(len(result["hmw_prompts"]), 1)
        self.assertEqual(len(result["solutions"]), 1)

    def test_non_gpt56_model_is_rejected(self):
        settings = self._settings(model="gpt-4.1")

        with self.assertRaisesRegex(ValueError, "GPT-5.6"):
            app._call_llm(settings, "Return JSON.")


if __name__ == "__main__":
    unittest.main()
