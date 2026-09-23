"""Recorder/tray regressions using synthetic audio and disposable vaults only."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ui")]
os.environ.setdefault("SKATE_ROOT", str(ROOT / "demo-vault"))
os.environ["SKATE_EMBED_BACKEND"] = "off"

import app
import numpy as np
import skate_lib
from fastapi.testclient import TestClient


class RecorderTrayTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.state = {"state": "idle"}
        self.patch(app, "RECORDER", self.state)
        self.patch(app, "APP_SHOW_REQUESTED", threading.Event())
        self.patch(app, "_load_settings", Mock(return_value={**app.DEFAULT_SETTINGS, "provider": "none", "transcription_model": "tiny"}))
        for module in (app, skate_lib):
            for name, value in (("SKATE_ROOT", self.root), ("CONVERSATIONS", self.root / "conversations"), ("SESSIONS", self.root / "sessions")):
                self.patch(module, name, value)
        self.client = TestClient(app.app)

    def patch(self, target, name, value):
        handle = patch.object(target, name, value)
        handle.start()
        self.addCleanup(handle.stop)

    def captured_audio(self):
        self.state.update(
            state="recording", started_at=100, stop_event=threading.Event(),
            threads=[], errors=[], loopback=[np.array([0, 1000, -1000, 32000], dtype=np.int16)],
            mic=[np.array([0, 500, -500, 32000], dtype=np.int16)],
            session="planning", session_label="Planning", include_mic=True,
        )

    def test_native_capture_uses_output_id_and_downmixes_all_channels(self):
        stop = threading.Event()
        reader = Mock()
        def record(**kwargs):
            stop.set()
            return np.array([[0.0, 0.8], [0.2, 0.6]], dtype=np.float32)
        reader.record.side_effect = record
        source = Mock(isloopback=True)
        source.recorder.return_value.__enter__ = Mock(return_value=reader)
        source.recorder.return_value.__exit__ = Mock(return_value=False)
        sc = SimpleNamespace(default_speaker=lambda: SimpleNamespace(id="output-id", name="Duplicate name"), get_microphone=Mock(return_value=source))
        chunks, errors = [], []
        with patch.dict(sys.modules, {"soundcard": sc}):
            app._recorder_capture("loopback", stop, chunks, errors)
        self.assertEqual(errors, [])
        sc.get_microphone.assert_called_once_with(id="output-id", include_loopback=True)
        source.recorder.assert_called_once_with(samplerate=16000)
        np.testing.assert_allclose(chunks[0], [13106, 13106], atol=1)

    def test_microphone_mode_does_not_start_system_capture(self):
        with patch.object(app, "_recorder_available", return_value=(True, "")), patch.object(app.threading, "Thread") as thread:
            response = self.client.post("/api/recorder/start", json={"source": "microphone", "include_mic": False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(thread.call_count, 1)
        self.assertEqual(thread.call_args.kwargs["args"][0], "mic")
        self.assertEqual(self.state["source"], "microphone")
        self.assertTrue(self.state["include_mic"])

    def test_invalid_audio_source_is_rejected(self):
        with patch.object(app, "_recorder_available", return_value=(True, "")):
            response = self.client.post("/api/recorder/start", json={"source": "unknown"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.state["state"], "idle")

    def test_microphone_note_has_accurate_source(self):
        body = app._recorder_note_body("Workshop", "hello", True, "base", source="microphone")
        self.assertIn("Recorded from microphone", body)
        self.assertNotIn("system audio", body)

    def test_live_relay_streams_the_same_mixed_pcm_and_disconnects(self):
        self.captured_audio()
        self.state["loopback"].clear()
        self.state["mic"].clear()
        class Socket:
            def __init__(inner):
                inner.packets = []
            async def accept(inner):
                pass
            async def receive(inner):
                if inner.packets:
                    return {"type": "websocket.disconnect"}
                self.state["loopback"].append(np.array([1000, 32000], dtype=np.int16))
                self.state["mic"].append(np.array([500, 32000], dtype=np.int16))
                return {"type": "websocket.receive"}
            async def send_bytes(inner, data):
                inner.packets.append(data)
            async def close(inner):
                pass
        socket = Socket()
        asyncio.run(app.recorder_audio(socket))
        np.testing.assert_array_equal(np.frombuffer(socket.packets[0], dtype="<i2"), [1500, 32767])
        self.assertEqual(self.state["state"], "recording")

    def test_recording_history_can_be_reopened_without_recorder_state(self):
        transcripts = self.root / "transcripts"
        transcripts.mkdir()
        self.patch(app, "TRANSCRIPTS_DIR", transcripts)
        (transcripts / "spotter-live-example.md").write_text("We agreed to test on Friday.", encoding="utf-8")
        history = self.client.get("/api/spotter-live/transcripts").json()
        self.assertEqual(history["files"], ["spotter-live-example.md"])
        saved = self.client.get("/api/spotter-live/transcripts", params={"file": history["files"][0]}).json()
        self.assertIn("Friday", saved["text"])
        response = self.client.get("/api/spotter-live/transcripts", params={"file": "../../settings.json"})
        self.assertEqual(response.status_code, 404)

    def test_tooltip_covers_recording_and_non_recording_states(self):
        self.assertEqual(app._tray_recorder_tooltip(), "SKATE — Not recording")
        self.state.update(state="recording", started_at=100)
        with patch.object(app.time, "time", return_value=11005):
            self.assertEqual(app._tray_recorder_tooltip(), "SKATE — Recording 03:01:45")
            self.state["errors"] = ["Microphone disconnected"]
            self.assertIn("Check audio", app._tray_recorder_tooltip())
        for state, phrase in (("stopping", "Preparing transcript"), ("transcribing", "Transcribing 37%"), ("saved", "Audio & transcript saved"), ("error", "Recording failed")):
            self.state.update(state=state, progress=37)
            title = app._tray_recorder_tooltip()
            self.assertIn("Not recording", title)
            self.assertIn(phrase, title)
            self.assertLess(len(title), 128)  # Windows notification-area limit.
            self.assertFalse(app._tray_can_stop_recording())

    def test_icon_tracks_state_and_does_not_recreate_it_for_timer_ticks(self):
        idle, recording = object(), object()
        icon = SimpleNamespace(icon=idle, title="", update_menu=Mock())
        app._sync_tray_recording(icon, idle, recording)
        self.assertIs(icon.icon, idle)
        icon.update_menu.assert_not_called()
        self.state.update(state="recording", started_at=100)
        with patch.object(app.time, "time", return_value=110):
            app._sync_tray_recording(icon, idle, recording)
            self.assertIs(icon.icon, recording)
            self.assertEqual(icon.title, "SKATE — Recording 00:00:10")
            app._sync_tray_recording(icon, idle, recording)
            icon.update_menu.assert_called_once()
        for state in ("stopping", "transcribing", "saved", "error", "idle"):
            self.state["state"] = state
            app._sync_tray_recording(icon, idle, recording)
            self.assertIs(icon.icon, idle)
            self.assertIn("Not recording", icon.title)
        self.assertEqual(icon.update_menu.call_count, 2)

    def test_bundled_idle_skateboard_and_record_circle_are_distinct(self):
        idle, recording = app._tray_idle_image(), app._tray_record_image()
        self.assertEqual(idle.size, (64, 64))
        self.assertEqual(recording.size, idle.size)
        self.assertNotEqual(idle.tobytes(), recording.tobytes())
        self.assertIsNotNone(idle.getbbox())

    def test_tray_stop_is_nonblocking_and_page_stop_cannot_duplicate_it(self):
        self.captured_audio()
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()

        def finalize(*args):
            entered.set()
            release.wait(5)
            finished.set()

        with patch.object(app, "_recorder_finalize", side_effect=finalize) as worker:
            try:
                app._tray_stop_recording(None, None)
                self.assertTrue(entered.wait(2))
                self.assertFalse(finished.is_set())
                self.assertTrue(self.state["stop_event"].is_set())
                self.assertEqual(self.state["state"], "stopping")
                self.assertFalse(app._tray_can_stop_recording())
                response = asyncio.run(app.recorder_stop())
                self.assertEqual(response.status_code, 409)
                app._tray_stop_recording(None, None)  # A stale second click is harmless.
                worker.assert_called_once_with(True, "planning", "Planning", "tiny")
            finally:
                release.set()
                self.assertTrue(finished.wait(2))

    def test_simultaneous_stop_requests_start_only_one_job(self):
        self.captured_audio()
        entered = threading.Event()
        with patch.object(app, "_recorder_finalize", side_effect=lambda *args: entered.set()) as worker:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: app._recorder_request_stop(), range(16)))
            self.assertEqual(results.count(True), 1)
            self.assertTrue(entered.wait(2))
            worker.assert_called_once()

    def test_tray_menu_wires_stop_to_the_shared_operation(self):
        with patch.dict(os.environ, {"PYSTRAY_BACKEND": "dummy"}):
            import pystray
        icon = Mock(visible=False)

        def run_tray():
            items = {item.text: item for item in icon.menu.items}
            self.assertIn("Open SKATE", items)
            stop = items["Stop recording & save"]
            self.assertFalse(stop.enabled)
            self.state["state"] = "recording"
            self.assertTrue(stop.enabled)
            stop(icon)
            items["Exit SKATE"](icon)

        def make_icon(name, image, title, menu):
            icon.menu = menu
            self.assertEqual(title, "SKATE — Not recording")
            icon.run.side_effect = run_tray
            return icon

        with patch.object(pystray, "Icon", side_effect=make_icon), patch.object(app.threading, "Thread"), patch.object(app.time, "sleep"), patch.object(app, "_recorder_request_stop") as stop:
            app._launch_with_tray("127.0.0.1", 8877, False, False)
            stop.assert_called_once_with()
            icon.stop.assert_called_once()

    def test_wav_exists_before_transcription_and_saved_note_links_to_it(self):
        self.captured_audio()

        def transcribe(path, filename, content_type, model, progress):
            self.assertIsInstance(path, Path)
            self.assertTrue(path.is_file())
            self.assertEqual(content_type, "audio/wav")
            with wave.open(str(path), "rb") as wav:
                self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 16000))
                self.assertEqual(np.frombuffer(wav.readframes(4), dtype=np.int16).tolist(), [0, 1500, -1500, 32767])
            progress(42, "Transcribing section 1")
            status = self.client.get("/api/recorder/status").json()
            self.assertEqual(status["state"], "transcribing")
            self.assertEqual(status["progress"], 42)
            self.assertEqual(self.client.get(status["audio_url"]).status_code, 200)
            return "Staff agreed to review the intake process."

        with patch.object(app, "_faster_whisper_transcribe", side_effect=transcribe):
            app._recorder_finalize(True, "planning", "Planning", "tiny")
        self.assertEqual(self.state["state"], "saved", self.state.get("error"))
        status = self.client.get("/api/recorder/status").json()
        note = (app.CONVERSATIONS / status["note"]).read_text(encoding="utf-8")
        audio = app.CONVERSATIONS / status["audio"]
        self.assertIn("Staff agreed to review", note)
        self.assertIn(f"[Download recording (WAV)](attachments/{audio.name})", note)
        self.assertIn("session: planning", note)
        download = self.client.get(status["audio_url"])
        self.assertEqual(download.content, audio.read_bytes())
        self.assertIn("attachment;", download.headers["content-disposition"])
        self.assertEqual(len(list(app.CONVERSATIONS.rglob("*.wav"))), 1)
        self.assertEqual(len(list(app.CONVERSATIONS.rglob("*.md"))), 1)
        self.assertEqual(self.state["loopback"], [])
        self.assertEqual(self.state["mic"], [])

    def test_transcription_failure_keeps_one_downloadable_wav(self):
        self.captured_audio()
        with patch.object(app, "_faster_whisper_transcribe", side_effect=RuntimeError("Model unavailable")):
            app._recorder_finalize(True, "planning", "Planning", "tiny")
        status = self.client.get("/api/recorder/status").json()
        self.assertEqual(status["state"], "error")
        self.assertIn("audio is saved", status["error"])
        self.assertEqual(self.client.get(status["audio_url"]).status_code, 200)
        self.assertEqual(len(list(app.CONVERSATIONS.rglob("*.wav"))), 1)
        self.assertFalse(list(app.CONVERSATIONS.rglob("*.md")))

    def test_repeated_recordings_in_same_second_do_not_overwrite_audio(self):
        self.captured_audio()
        with patch.object(app.time, "strftime", return_value="20260912-213000"), patch.object(app, "_faster_whisper_transcribe", return_value="Workshop notes"):
            app._recorder_finalize(True, "planning", "Planning", "tiny")
            first = app.CONVERSATIONS / self.state["audio"]
            original = first.read_bytes()
            self.captured_audio()
            self.state["loopback"] = [np.array([30, 40, 50], dtype=np.int16)]
            app._recorder_finalize(True, "planning", "Planning", "tiny")
            second = app.CONVERSATIONS / self.state["audio"]
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), original)
        self.assertNotEqual(second.read_bytes(), original)
        self.assertEqual(len(list(app.CONVERSATIONS.rglob("*.md"))), 2)

    def test_no_audio_or_failed_disk_write_never_claims_a_saved_recording(self):
        for empty in (True, False):
            with self.subTest(empty=empty):
                self.state.clear()
                self.captured_audio()
                if empty:
                    self.state.update(loopback=[], mic=[])
                with patch.object(app, "_recorder_save_audio", side_effect=OSError("Disk full")), patch.object(app, "_faster_whisper_transcribe") as transcribe:
                    app._recorder_finalize(True, "planning", "Planning", "tiny")
                self.assertEqual(self.state["state"], "error")
                self.assertNotIn("audio", self.state)
                transcribe.assert_not_called()

    def test_new_recording_clears_previous_download_and_starts_red_status(self):
        self.state.update(state="saved", audio="old.wav", audio_url="/entry/old.wav")
        with patch.object(app, "_recorder_available", return_value=(True, "")), patch.object(app, "_recorder_capture"):
            response = self.client.post("/api/recorder/start", json={"session": "planning", "include_mic": False})
        self.assertEqual(response.status_code, 200)
        status = self.client.get("/api/recorder/status").json()
        self.assertEqual(status["state"], "recording")
        self.assertNotIn("audio_url", status)
        self.assertTrue(app._tray_can_stop_recording())
        for thread in self.state["threads"]:
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
