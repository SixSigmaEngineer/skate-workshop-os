"""Regression coverage for the September 2026 workshop fixes (no cloud calls)."""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "ui")]
os.environ.setdefault("SKATE_ROOT", str(ROOT))
os.environ["SKATE_EMBED_BACKEND"] = "off"

import app
import audio_uploads
import note_quality
import skate_lib
import ui_themes
from fastapi.testclient import TestClient


CHAT = "My dog has a pain problem. We should take my dog to the vet. Good morning everyone."
WORK = "Staff copy client data manually into three systems. #A: Maria will review the intake fields on Friday."


def no_ai():
    settings = copy.deepcopy(app.DEFAULT_SETTINGS)
    settings.update(provider="none", ui_theme="default", recording_upload_limit_mb=2048)
    return settings


class QualityTests(unittest.TestCase):
    def test_social_chat_does_not_create_signals_locally(self):
        data = app._local_transcript_summary("Intake workshop", CHAT)
        for key in note_quality.SIGNAL_KEYS.values():
            self.assertEqual(data[key], [], key)
        self.assertNotIn("dog", data["summary"])

    def test_mixed_capture_keeps_work_and_explains_exclusions(self):
        reviewed = note_quality.screen(CHAT + "\n" + WORK)
        self.assertNotIn("my dog", reviewed["text"].lower())
        self.assertIn("client data", reviewed["text"])
        self.assertEqual(reviewed["excluded_count"], 3)
        self.assertEqual(reviewed["source_units"], 5)

    def test_real_user_needs_are_not_a_pet_or_family_blacklist(self):
        for text, focus in [
            ("My dog cannot enter the client service area, which limits accessibility.", ""),
            ("My wife misses the training because her shift ends late.", ""),
            ("My dog needs a wheelchair fitting.", "Dog mobility workshop"),
        ]:
            self.assertEqual(note_quality.screen(text, focus)["excluded_count"], 0)

    def test_unknown_domain_context_is_preserved_without_fabricated_signals(self):
        text = "The quasar has an unusual spectrum."
        extracted = note_quality.local_signals(text)
        self.assertEqual(extracted["context"], [text])
        self.assertEqual(extracted["pain_points"], [])

    def test_focus_stopwords_do_not_admit_chatter(self):
        self.assertEqual(note_quality.screen(CHAT, "The workshop for our team")["kept_units"], 0)

    def test_quotation_does_not_keep_neighboring_pet_chat(self):
        text = 'My dog has a problem. Staff said "Do not approve 15 requests."'
        reviewed = note_quality.screen(text, "The intake workshop")
        self.assertNotIn("dog", reviewed["text"])
        self.assertIn('"Do not approve 15 requests."', reviewed["text"])

    def test_whole_long_note_reaches_late_actions_and_decisions(self):
        transcript = (CHAT + "\n") * 1500 + "\n#A: Maria will check the intake fields Friday.\nDecision: We agreed to pause the rollout."
        with patch.object(app, "_load_settings", return_value=no_ai()), patch.object(app, "_call_llm") as call:
            data = TestClient(app.app).post("/api/compress-note", json={"title": "Intake", "body": transcript}).json()
        call.assert_not_called()
        self.assertIn("Maria will check", data["markdown"])
        self.assertIn("pause the rollout", data["markdown"])
        self.assertNotIn("dog", data["markdown"])
        self.assertGreater(data["review"]["source_units"], 4500)
        self.assertEqual(data["review"]["excluded_count"], 4500)

    def test_ai_chunks_cover_the_tail_and_merge_all_actions(self):
        text = "\n".join(f"#A: Staff will review intake record {i}." for i in range(900))
        prompts = []
        def model(settings, prompt):
            prompts.append(prompt)
            return json.dumps({"gist": "Intake review", "actions": [f"Staff will review section {len(prompts)}."]})
        settings = no_ai()
        settings.update(provider="lmstudio")
        with patch.object(app, "_load_settings", return_value=settings), patch.object(app, "_call_llm", side_effect=model):
            data = TestClient(app.app).post("/api/compress-note", json={"title": "Intake", "body": text}).json()
        self.assertGreater(len(prompts), 1)
        self.assertIn("record 899", "\n".join(prompts))
        self.assertEqual(len(data["compression"]["actions"]), len(prompts))
        self.assertEqual(data["review"]["chunks_processed"], len(prompts))
        self.assertTrue(all("WORKSHOP RELEVANCE" in prompt for prompt in prompts))

    def test_provider_failure_keeps_locally_extracted_evidence(self):
        settings = no_ai()
        settings.update(provider="lmstudio")
        with patch.object(app, "_load_settings", return_value=settings), patch.object(app, "_call_llm", side_effect=TimeoutError):
            data = TestClient(app.app).post("/api/summarize-transcript", json={"title": "Intake", "transcript": "#A: Maria will review the client form."}).json()
        self.assertTrue(data["ok"])
        self.assertIn("Maria", data["markdown"])
        self.assertEqual(data["review"]["local_fallback_chunks"], 1)

    def test_dense_ai_section_does_not_silently_clip_actions_or_decisions(self):
        actions = [f"Staff will review intake record {i}." for i in range(20)]
        decisions = [f"The team agreed to pause rollout {i}." for i in range(20)]
        settings = no_ai()
        settings.update(provider="lmstudio")
        for endpoint, source_key, result_key in [
            ("/api/compress-note", "body", "compression"),
            ("/api/summarize-transcript", "transcript", "summary"),
        ]:
            with self.subTest(endpoint=endpoint), patch.object(app, "_load_settings", return_value=settings), patch.object(app, "_call_llm", return_value=json.dumps({"actions": actions, "decisions": decisions})):
                data = TestClient(app.app).post(endpoint, json={"title": "Intake", source_key: "\n".join(actions + decisions)}).json()
            self.assertEqual(data[result_key]["actions"], actions)
            self.assertEqual(data[result_key]["decisions"], decisions)

    def test_quotes_numbers_negation_and_owner_are_preserved(self):
        text = '#O: Dr. Patel said, "We cannot approve 15 requests; the owner is unknown."'
        data = app._local_note_compression("Intake", "", text)
        self.assertEqual(data["observations"], [text[4:]])

    def test_compression_retains_all_explicit_signal_types(self):
        text = "#S: Test the intake form.\n#R: Review the workflow.\nDecision: Hold the rollout."
        result = app._local_note_compression("Intake", "", text)
        rendered = app._compression_markdown(result)
        self.assertIn("#S: Test the intake form.", rendered)
        self.assertIn("#R: Review the workflow.", rendered)
        self.assertIn("Hold the rollout.", rendered)

    def test_cleaned_markers_render_and_actions_can_be_promoted(self):
        entry = skate_lib.Entry(path=skate_lib.CONVERSATIONS / "demo/test.md", title="Intake", date="2026-09-12")
        entry.body = app._compression_markdown(app._local_note_compression("Intake", "", "#A: Maria will check the intake form.\n#P: Manual entry delays intake."))
        html = app._render_note_html(entry)
        self.assertIn('class="capture-line capture-line-a"', html)
        self.assertIn('class="capture-line capture-line-p"', html)
        self.assertEqual([item["text"] for item in app._embedded_actions(entry)], ["Maria will check the intake form."])

    def test_unpunctuated_input_is_bounded_without_loss(self):
        text = "unique-word " * 3000
        parts = note_quality.chunks(text, 1000)
        self.assertTrue(all(len(part) <= 1000 for part in parts))
        self.assertEqual(" ".join(parts).split(), text.split())

    def test_spotter_does_not_prepare_social_chat_for_the_vault(self):
        with patch.object(app, "_load_settings", return_value=no_ai()):
            data = TestClient(app.app).post("/api/spotter", json={"mode": "pain", "session_label": "Intake", "text": CHAT}).json()
        self.assertEqual(data["create_url"], "")
        self.assertEqual(data["markdown"], "")

    def test_live_local_response_filters_the_recorded_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "room.md"
            source.write_text(CHAT + "\n#A: Maria will review the client form.", encoding="utf-8")
            with patch.object(app, "TRANSCRIPTS_DIR", Path(directory)), patch.object(app, "_load_settings", return_value=no_ai()):
                data = TestClient(app.app).post("/api/spotter-live/ask", json={"file": "room.md", "question": "What action items were captured?"}).json()
        self.assertTrue(data["ok"])
        self.assertIn("Maria", data["answer"])
        self.assertNotIn("dog", data["answer"])

    def test_grind_does_not_score_a_personal_complaint_as_business_pain(self):
        entry = skate_lib.Entry(path=ROOT / "conversations/test.md", title="Workshop transcript", date="2026-09-12")
        entry.body = CHAT
        self.assertEqual(skate_lib._pain_score(entry), 0)


class StreamRequest:
    def __init__(self, parts, headers=None):
        self.parts, self.headers = parts, headers or {}

    async def stream(self):
        for part in self.parts:
            if isinstance(part, Exception):
                raise part
            yield part


class UploadTests(unittest.TestCase):
    def test_stream_is_written_to_disk(self):
        path = asyncio.run(audio_uploads.receive_recording(StreamRequest([b"abc", b"def"]), 10))
        try:
            self.assertEqual(path.read_bytes(), b"abcdef")
        finally:
            path.unlink()

    def test_oversize_is_rejected_with_or_without_content_length(self):
        for request in [StreamRequest([b"123456"], {"content-length": "6"}), StreamRequest([b"123", b"456"])]:
            with self.assertRaises(audio_uploads.UploadProblem) as caught:
                asyncio.run(audio_uploads.receive_recording(request, 5))
            self.assertEqual(caught.exception.status, 413)

    def test_empty_bad_length_and_disconnect_remove_temporary_files(self):
        real_tempfile = audio_uploads.tempfile.NamedTemporaryFile
        for request in [StreamRequest([]), StreamRequest([b"abc", RuntimeError("disconnected")]), StreamRequest([], {"content-length": "bad"})]:
            with tempfile.TemporaryDirectory() as directory:
                def create(**kwargs):
                    return real_tempfile(dir=directory, **kwargs)
                with patch.object(audio_uploads.tempfile, "NamedTemporaryFile", side_effect=create):
                    with self.assertRaises((audio_uploads.UploadProblem, RuntimeError)):
                        asyncio.run(audio_uploads.receive_recording(request, 10))
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_incomplete_upload_is_not_transcribed(self):
        with self.assertRaisesRegex(audio_uploads.UploadProblem, "incomplete"):
            asyncio.run(audio_uploads.receive_recording(StreamRequest([b"abc"], {"content-length": "8"}), 10))

    def test_upload_job_uses_a_path_and_releases_it(self):
        received = []
        def transcribe(source, filename, content_type, model, **kwargs):
            self.assertIsInstance(source, Path)
            self.assertEqual(source.read_bytes(), b"fake recording")
            received.append(source)
            return {"ok": True, "transcript": "Staff reviewed intake.", "mode": "local-whisper"}
        with patch.object(app, "_perform_transcription", side_effect=transcribe), patch.object(app, "_audio_upload_limit", return_value=2 * 1024**3):
            with TestClient(app.app) as client:
                result = client.post("/api/transcription-jobs", content=b"fake recording", headers={"x-skate-filename": "meeting.mp4"}).json()
                self.assertTrue(result["ok"])
                # Join the finite test worker instead of sleeping or hitting a model.
                import threading
                for thread in threading.enumerate():
                    if thread.name == f"skate-transcription-{result['job_id'][:8]}":
                        thread.join(timeout=5)
                self.assertEqual(client.get('/api/transcription-jobs/' + result['job_id']).json()["status"], "complete")
        self.assertEqual(len(received), 1)
        self.assertFalse(received[0].exists())

    def test_job_releases_upload_after_transcription_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audio.wav"
            path.write_bytes(b"audio")
            with patch.object(app, "_perform_transcription", side_effect=RuntimeError("bad file")), patch.object(app, "TRANSCRIPTION_JOBS", {"job": {"status": "queued"}}):
                app._run_transcription_job("job", path, "audio.wav", "audio/wav", "base")
                self.assertEqual(app.TRANSCRIPTION_JOBS["job"]["status"], "error")
            self.assertFalse(path.exists())

    def test_ten_minute_decoder_sections_preserve_all_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.wav"
            with wave.open(str(source), "wb") as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
                wav.writeframes(b"\0\0" * 36000)
            totals, offsets = [], []
            for path, offset, duration in audio_uploads.audio_sections(source, root, seconds=1):
                with wave.open(str(path), "rb") as wav:
                    totals.append(wav.getnframes())
                offsets.append(offset)
            self.assertEqual(totals, [16000, 16000, 4000])
            self.assertEqual(offsets, [0, 1, 2])
            self.assertFalse((root / "section.wav").exists())


class ThemeAndExportTests(unittest.TestCase):
    def test_desktop_close_hides_until_exit_is_requested(self):
        import threading
        from types import SimpleNamespace
        from unittest.mock import Mock

        callbacks = []

        class ClosingEvent:
            def __iadd__(self, callback):
                callbacks.append(callback)
                return self

        window = Mock(events=SimpleNamespace(closing=ClosingEvent()))
        quitting = threading.Event()
        holder = {}

        def run_window(**kwargs):
            self.assertFalse(callbacks[0]())
            window.hide.assert_called_once_with()
            window.destroy.assert_not_called()
            self.assertFalse(quitting.is_set())
            quitting.set()
            self.assertTrue(callbacks[0]())
            self.assertEqual(window.hide.call_count, 1)

        webview = SimpleNamespace(create_window=Mock(return_value=window), start=run_window, settings={})
        with patch.dict(sys.modules, {"webview": webview}), patch.object(app.sys, "platform", "linux"):
            self.assertTrue(app._open_skate_window("http://127.0.0.1:8875", hide_on_close=True, window_holder=holder, quitting=quitting))
        self.assertIs(holder["window"], window)
        self.assertTrue(webview.settings["ALLOW_DOWNLOADS"])

    def test_palette_overrides_are_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "themes.json").write_text(json.dumps({"terra": {"accent": "#123456", "bg": "red;display:none"}}))
            themes = ui_themes.catalog(path, ROOT / "ui/static/skateboards")
            terra = next(theme for theme in themes if theme["id"] == "terra")
            self.assertEqual(terra["colors"]["accent"], "#123456")
            self.assertEqual(terra["colors"]["bg"], "#f5f6ee")

    def test_settings_persist_theme_and_bound_upload_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps(no_ai()), encoding="utf-8")
            with patch.object(app, "SETTINGS_PATH", path):
                client = TestClient(app.app)
                client.post("/settings", data={"provider": "none", "ui_theme": "luna", "recording_upload_limit_mb": "999999"})
                saved = app._load_settings()
                self.assertEqual(saved["ui_theme"], "luna")
                self.assertEqual(saved["recording_upload_limit_mb"], 4096)
                self.assertIn('data-ui-theme="luna"', client.get("/settings").text)

    def test_session_print_uses_saved_active_notes_without_ai(self):
        entry = skate_lib.Entry(path=skate_lib.CONVERSATIONS / "demo/note.md", title="Intake review", date="2026-09-12")
        entry.body, entry.session = "#O: Staff check the client record.\n![Chart](attachments/chart.png)", "demo"
        with patch.object(app, "_active_session_entries", return_value=[entry]), patch.object(app, "_call_llm") as model:
            response = TestClient(app.app).get("/session/demo/print")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Staff check the client record.", response.text)
        self.assertIn("/entry/demo/attachments/chart.png", response.text)
        model.assert_not_called()


class InlineSessionTests(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.TemporaryDirectory()
        self.addCleanup(self.vault.cleanup)
        root = Path(self.vault.name)
        self.sessions = root / "sessions"
        for module in (app, skate_lib):
            for name, value in (("SESSIONS", self.sessions), ("CONVERSATIONS", root / "conversations")):
                patched = patch.object(module, name, value)
                patched.start()
                self.addCleanup(patched.stop)
        self.client = TestClient(app.app)

    def test_created_session_is_active_and_accepts_recorded_notes(self):
        response = self.client.post("/api/sessions", json={"title": "September Planning"})
        self.assertEqual(response.status_code, 201)
        session = response.json()["session"]
        self.assertEqual(session, {"key": "september-planning", "label": "September Planning"})
        rows = skate_lib.session_stats([])
        self.assertEqual([(row["key"], row["status"], row["count"]) for row in rows], [(session["key"], "active", 0)])
        file_id = app._recorder_save_note(session["key"], session["label"], "#O: Staff reviewed intake.", "Planning recording")
        entry = skate_lib.find_entry_by_id(file_id)
        self.assertEqual(entry.session_key, session["key"])
        self.assertEqual(entry.session_display, session["label"])

    def test_duplicate_reuses_active_session_without_overwriting_and_rejects_inactive(self):
        self.client.post("/api/sessions", json={"title": "Planning Review"})
        path = self.sessions / "planning-review" / "README.md"
        original = path.read_text(encoding="utf-8") + "\nExisting readout notes.\n"
        path.write_text(original, encoding="utf-8")
        again = self.client.post("/api/sessions", json={"title": "planning review"})
        self.assertEqual(again.status_code, 200)
        self.assertFalse(again.json()["created"])
        self.assertEqual(again.json()["session"]["label"], "Planning Review")
        self.assertEqual(path.read_text(encoding="utf-8"), original)
        collision = self.client.post("/api/sessions", json={"title": "Planning-Review"})
        self.assertEqual(collision.status_code, 409)
        inactive = original.replace("status: active", "status: inactive")
        path.write_text(inactive, encoding="utf-8")
        self.assertEqual(self.client.post("/api/sessions", json={"title": "Planning Review"}).status_code, 409)
        self.assertEqual(path.read_text(encoding="utf-8"), inactive)

    def test_invalid_names_do_not_create_sessions(self):
        for payload in ([], {}, {"title": None}, {"title": "   "}, {"title": "x" * 121}, {"title": "!!!"}, {"title": "Unassigned"}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post("/api/sessions", json=payload).status_code, 400)
        self.assertFalse(self.sessions.exists())


if __name__ == "__main__":
    unittest.main()
