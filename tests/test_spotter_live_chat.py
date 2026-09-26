"""Live transcript chat must return readable answers, not capture schemas."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ui"))
import app
from fastapi.testclient import TestClient


SCHEMA = json.dumps({"properties": {"say": {"type": "string"}}, "required": ["say"]})


class LiveChatTests(unittest.TestCase):
    def test_recording_can_be_reopened_before_first_caption_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (patch.object(app, "TRANSCRIPTS_DIR", Path(tmp)),
                  patch.object(app, "RECORDER", {"state": "recording", "live_file": "spotter-live-active.md", "session": "alpha"})):
                client = TestClient(app.app)
                self.assertEqual(client.get("/api/spotter-live/transcripts?file=spotter-live-active.md").json(),
                                 {"ok": True, "file": "spotter-live-active.md", "text": ""})
                self.assertEqual(client.get("/api/recorder/status").json()["session"], "alpha")
                self.assertEqual(client.get("/api/spotter-live/transcripts?file=missing.md").status_code, 404)

    def settings(self, provider="openai"):
        return {**app.DEFAULT_SETTINGS, "provider": provider,
                "api_keys": {provider: "test-key"}, "spotter_persona": "Custom coaching persona"}

    def test_plain_chat_disables_json_mode_without_changing_structured_workflows(self):
        for provider in ("openai", "openrouter", "lmstudio"):
            with self.subTest(provider=provider):
                response = {"output_text": "Discuss independent review.",
                            "choices": [{"message": {"content": "Discuss independent review."}}]}
                settings = self.settings(provider)
                settings["lmstudio_model"] = "local-model"
                with patch.object(app, "_post_json", return_value=response) as post:
                    app._call_llm(settings, "Answer in prose.", json_output=False)
                    payload = post.call_args.args[2]
                    self.assertNotIn("response_format", payload)
                    self.assertNotIn("text", payload)
                    app._call_llm(settings, "Return JSON.")
                    payload = post.call_args.args[2]
                    if provider == "openai":
                        self.assertEqual(payload["text"]["format"]["type"], "json_object")
                    else:
                        self.assertEqual(payload["response_format"]["type"], "json_object")

    def test_answer_unwraps_say_and_rejects_schemas_and_broken_json(self):
        self.assertEqual(app._spotter_live_clean_answer('{"say":"Review the handoff.","summary":"Other text"}'), "Review the handoff.")
        for answer in (SCHEMA, "```json\n" + SCHEMA + "\n```", '{"type":"object"}',
                       '{"say":', '[{"answer":"nested"}]', '{}'):
            with self.subTest(answer=answer):
                self.assertEqual(app._spotter_live_clean_answer(answer), "")

    def test_saved_transcript_question_retries_schema_then_returns_prose(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "meeting.md"
            transcript.write_text("The team needs independent review of each deployment.", encoding="utf-8")
            with (patch.object(app, "_load_settings", return_value=self.settings()),
                  patch.object(app, "_safe_transcript_path", return_value=transcript),
                  patch.object(app, "_call_llm", side_effect=[SCHEMA, "Add an independent review checkpoint."]) as call):
                result = TestClient(app.app).post("/api/spotter-live/ask", json={"file": "meeting.md", "question": "What should I add?"}).json()
            self.assertEqual(result, {"ok": True, "answer": "Add an independent review checkpoint."})
            self.assertEqual(call.call_count, 2)
            for request in call.call_args_list:
                self.assertFalse(request.kwargs["json_output"])
                self.assertIn("independent review", request.args[1])
            self.assertNotIn("Custom coaching persona", call.call_args.args[1])

    def test_repeated_schema_returns_error_instead_of_displayable_answer(self):
        with (patch.object(app, "_load_settings", return_value=self.settings()),
              patch.object(app, "_call_llm", return_value=SCHEMA) as call):
            result = TestClient(app.app).post("/api/spotter-live/ask", json={"question": "What next?"}).json()
        self.assertFalse(result["ok"])
        self.assertNotIn("answer", result)
        self.assertEqual(call.call_count, 2)
