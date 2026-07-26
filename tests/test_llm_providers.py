import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui"))
os.environ.setdefault("SKATE_ROOT", str(ROOT))
os.environ["SKATE_EMBED_BACKEND"] = "off"

import app as skate_app  # noqa: E402


def _settings(provider: str, **overrides) -> dict:
    settings = json.loads(json.dumps(skate_app.DEFAULT_SETTINGS))
    settings["provider"] = provider
    settings["api_keys"].update(
        {"openai": "sk-test", "anthropic": "sk-ant-test", "openrouter": "sk-or-test"}
    )
    settings.update(overrides)
    return settings


class LLMAvailabilityTests(unittest.TestCase):
    def test_none_provider_is_never_available(self):
        settings = _settings("none")
        self.assertFalse(skate_app._llm_available(settings))
        self.assertIn("turned off", skate_app._llm_unavailable_reason(settings))

    def test_lmstudio_needs_no_key(self):
        settings = _settings("lmstudio")
        settings["api_keys"] = {k: "" for k in settings["api_keys"]}
        self.assertTrue(skate_app._llm_available(settings))

    def test_cloud_providers_require_their_own_key(self):
        for provider in ("openai", "anthropic", "openrouter"):
            settings = _settings(provider)
            self.assertTrue(skate_app._llm_available(settings))
            settings["api_keys"][provider] = ""
            self.assertFalse(skate_app._llm_available(settings))

    def test_call_llm_refuses_when_off(self):
        with self.assertRaises(ValueError):
            skate_app._call_llm(_settings("none"), "prompt")


class ActiveModelTests(unittest.TestCase):
    def test_model_follows_provider(self):
        self.assertEqual(skate_app._active_model(_settings("openai")), "gpt-5.6")
        self.assertEqual(skate_app._active_model(_settings("anthropic")), "claude-sonnet-5")
        self.assertEqual(
            skate_app._active_model(_settings("openrouter", openrouter_model="meta-llama/llama-4")),
            "meta-llama/llama-4",
        )

    def test_spotter_model_override_only_applies_to_openai(self):
        settings = _settings("anthropic", spotter_model="gpt-5.6-luna")
        eff = skate_app._feature_settings(settings, "spotter")
        self.assertEqual(skate_app._active_model(eff), "claude-sonnet-5")
        settings = _settings("openai", spotter_model="gpt-5.6-luna")
        eff = skate_app._feature_settings(settings, "spotter")
        self.assertEqual(skate_app._active_model(eff), "gpt-5.6-luna")


class ProviderRoutingTests(unittest.TestCase):
    def test_anthropic_routing_and_parsing(self):
        captured = {}

        def fake_post(url, headers, payload, timeout=120):
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = payload
            return {"content": [{"type": "text", "text": '{"ok": true}'}]}

        with patch.object(skate_app, "_post_json", fake_post):
            text = skate_app._call_llm(_settings("anthropic"), "hello")
        self.assertEqual(text, '{"ok": true}')
        self.assertIn("api.anthropic.com/v1/messages", captured["url"])
        self.assertEqual(captured["headers"]["x-api-key"], "sk-ant-test")
        self.assertEqual(captured["payload"]["model"], "claude-sonnet-5")

    def test_openrouter_uses_chat_completions(self):
        captured = {}

        def fake_post(url, headers, payload, timeout=120):
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = payload
            return {"choices": [{"message": {"content": '{"ok": true}'}}]}

        with patch.object(skate_app, "_post_json", fake_post):
            text = skate_app._call_llm(
                _settings("openrouter", openrouter_model="anthropic/claude-sonnet-5"), "hello"
            )
        self.assertEqual(text, '{"ok": true}')
        self.assertIn("openrouter.ai/api/v1/chat/completions", captured["url"])
        self.assertEqual(captured["headers"]["Authorization"], "Bearer sk-or-test")
        self.assertEqual(captured["payload"]["model"], "anthropic/claude-sonnet-5")

    def test_openrouter_retries_without_json_format(self):
        calls = []

        def fake_post(url, headers, payload, timeout=120):
            calls.append(dict(payload))
            if "response_format" in payload:
                raise ValueError("API returned HTTP 400: response_format unsupported")
            return {"choices": [{"message": {"content": "plain"}}]}

        with patch.object(skate_app, "_post_json", fake_post):
            text = skate_app._call_llm(
                _settings("openrouter", openrouter_model="some/model"), "hello"
            )
        self.assertEqual(text, "plain")
        self.assertEqual(len(calls), 2)
        self.assertNotIn("response_format", calls[1])

    def test_lmstudio_targets_local_server(self):
        captured = {}

        def fake_post(url, headers, payload, timeout=120):
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = payload
            return {"choices": [{"message": {"content": "local"}}]}

        settings = _settings("lmstudio", lmstudio_model="qwen2.5-7b-instruct")
        settings["api_keys"] = {k: "" for k in settings["api_keys"]}
        with patch.object(skate_app, "_post_json", fake_post):
            text = skate_app._call_llm(settings, "hello")
        self.assertEqual(text, "local")
        self.assertIn("127.0.0.1:1234/v1/chat/completions", captured["url"])
        self.assertNotIn("Authorization", captured["headers"])

    def test_openai_path_unchanged(self):
        captured = {}

        def fake_post(url, headers, payload, timeout=120):
            captured["url"] = url
            captured["payload"] = payload
            return {"output_text": '{"ok": true}'}

        with patch.object(skate_app, "_post_json", fake_post):
            text = skate_app._call_llm(_settings("openai"), "hello")
        self.assertEqual(text, '{"ok": true}')
        self.assertIn("api.openai.com/v1/responses", captured["url"])
        self.assertEqual(captured["payload"]["model"], "gpt-5.6")


class ReasoningEffortMappingTests(unittest.TestCase):
    def _capture(self, settings):
        captured = {}

        def fake_post(url, headers, payload, timeout=120):
            captured.update(payload)
            return {
                "content": [{"type": "text", "text": "ok"}],
                "choices": [{"message": {"content": "ok"}}],
                "output_text": "ok",
            }

        with patch.object(skate_app, "_post_json", fake_post):
            skate_app._call_llm(settings, "hello")
        return captured

    def test_anthropic_effort_maps_to_thinking_budget(self):
        payload = self._capture(_settings("anthropic", reasoning_effort="high"))
        self.assertEqual(payload["thinking"], {"type": "enabled", "budget_tokens": 16384})
        self.assertGreater(payload["max_tokens"], 16384)

    def test_anthropic_effort_none_disables_thinking(self):
        payload = self._capture(_settings("anthropic", reasoning_effort="none"))
        self.assertNotIn("thinking", payload)

    def test_openrouter_effort_maps_and_caps_at_high(self):
        payload = self._capture(
            _settings("openrouter", openrouter_model="some/model", reasoning_effort="max")
        )
        self.assertEqual(payload["reasoning"], {"effort": "high"})

    def test_lmstudio_sends_no_reasoning_field(self):
        settings = _settings("lmstudio", lmstudio_model="m", reasoning_effort="high")
        payload = self._capture(settings)
        self.assertNotIn("reasoning", payload)


class SettingsValidationTests(unittest.TestCase):
    def test_defaults_include_all_providers(self):
        keys = skate_app.DEFAULT_SETTINGS["api_keys"]
        for provider in ("openai", "anthropic", "openrouter", "elevenlabs"):
            self.assertIn(provider, keys)

    def test_provider_labels_cover_all_providers(self):
        for provider in skate_app.LLM_PROVIDERS:
            self.assertIn(provider, skate_app.LLM_PROVIDER_LABELS)


if __name__ == "__main__":
    unittest.main()
