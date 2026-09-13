"""Bounded cleanup scheduling, honest progress, and cancellation without API calls."""
import asyncio
import copy
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "ui")]
os.environ.setdefault("SKATE_ROOT", str(ROOT / "demo-vault"))
os.environ["SKATE_EMBED_BACKEND"] = "off"
import app
from fastapi.testclient import TestClient


def settings(provider="openai"):
    value = copy.deepcopy(app.DEFAULT_SETTINGS)
    value.update(provider=provider, reasoning_effort="medium", lmstudio_model="test-local")
    value["api_keys"]["openai"] = "test-not-a-real-key"
    return value


PARTS = [f"#A: Staff will review section {i}." for i in range(9)]


class CleanupPerformanceTests(unittest.TestCase):
    def test_parallel_sections_are_bounded_and_merged_in_source_order(self):
        active = peak = 0
        lock = threading.Lock()
        events = []
        observed_efforts = []
        def model(config, prompt):
            nonlocal active, peak
            index = int(re.findall(r"section (\d+)", prompt)[-1])
            with lock:
                active += 1
                peak = max(peak, active)
                observed_efforts.append(config["reasoning_effort"])
            time.sleep(0.07 if index % 3 else 0.12)
            with lock:
                active -= 1
            return json.dumps({"gist": f"Section {index}", "actions": [f"Staff will review section {index}."]})
        async def run():
            return await app._reviewed_summary({"title": "Planning", "body": "\n".join(PARTS)}, "compression", events.append)
        with patch.object(app, "_load_settings", return_value=settings()), patch.object(app.note_quality, "chunks", return_value=PARTS), patch.object(app, "_call_llm", side_effect=model):
            result = asyncio.run(run())
        self.assertEqual(peak, 3)
        self.assertEqual(result["compression"]["actions"], [part[4:] for part in PARTS])
        self.assertEqual(result["compression"]["gist"], "\n\n".join(f"Section {i}" for i in range(9)))
        self.assertEqual(events[0]["completed"], 0)
        self.assertEqual(events[-1]["completed"], 9)
        self.assertEqual(events[-1]["active"], 0)
        self.assertEqual([event["completed"] for event in events], sorted(event["completed"] for event in events))
        self.assertTrue(all(effort == "medium" for effort in observed_efforts))

    def test_local_model_is_not_sent_parallel_requests(self):
        active = peak = 0
        def model(*args):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            time.sleep(0.01)
            active -= 1
            return '{"gist":"Workshop"}'
        with patch.object(app, "_load_settings", return_value=settings("lmstudio")), patch.object(app.note_quality, "chunks", return_value=PARTS), patch.object(app, "_call_llm", side_effect=model):
            asyncio.run(app._reviewed_summary({"body": "\n".join(PARTS)}, "compression"))
        self.assertEqual(peak, 1)

    def test_access_and_rate_errors_stop_queued_requests_and_preserve_every_section(self):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status), patch.object(app, "_load_settings", return_value=settings()), patch.object(app.note_quality, "chunks", return_value=PARTS), patch.object(app, "_call_llm", side_effect=app.ModelHTTPError(status, "Private provider error detail")) as model:
                result = asyncio.run(app._reviewed_summary({"body": "\n".join(PARTS)}, "compression"))
            self.assertLessEqual(model.call_count, 3)
            self.assertEqual(result["compression"]["mode"], "local")
            self.assertEqual(result["review"]["local_fallback_chunks"], 9)
            self.assertIn("section 8", result["markdown"])
            self.assertTrue(result["review"]["provider_issue"])
            self.assertNotIn("Private provider error detail", json.dumps(result))

    def test_repeated_timeouts_do_not_wait_once_for_every_section(self):
        with patch.object(app, "_load_settings", return_value=settings()), patch.object(app.note_quality, "chunks", return_value=PARTS), patch.object(app, "_call_llm", side_effect=TimeoutError) as model:
            result = asyncio.run(app._reviewed_summary({"body": "\n".join(PARTS)}, "compression"))
        self.assertLessEqual(model.call_count, 4)  # One can start while another timeout is delivered.
        self.assertIn("section 8", result["markdown"])
        self.assertIn("timeouts", result["message"])

    def test_a_malformed_section_does_not_discard_later_sections(self):
        def model(config, prompt):
            if "section 1." in prompt:
                return "not json"
            return '{"gist":"Reviewed"}'
        with patch.object(app, "_load_settings", return_value=settings()), patch.object(app.note_quality, "chunks", return_value=PARTS), patch.object(app, "_call_llm", side_effect=model):
            result = asyncio.run(app._reviewed_summary({"body": "\n".join(PARTS)}, "compression"))
        self.assertEqual(result["compression"]["mode"], "mixed")
        self.assertEqual(result["review"]["local_fallback_chunks"], 1)
        self.assertIn("section 8", result["markdown"])

    def test_stop_prevents_unsent_sections_and_holds_slots_until_real_calls_finish(self):
        started = threading.Event()
        release = threading.Event()
        cancelled = threading.Event()
        calls = []
        lock = threading.Lock()
        slots = threading.BoundedSemaphore(3)
        def model(*args):
            with lock:
                calls.append(1)
                if len(calls) == 3:
                    started.set()
            release.wait(timeout=3)
            return '{"gist":"Reviewed"}'
        async def run():
            task = asyncio.create_task(app._reviewed_summary({"body": "\n".join(PARTS)}, "compression", cancelled=cancelled))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(cancelled.is_set())
                self.assertFalse(slots.acquire(blocking=False))
                self.assertEqual(len(calls), 3)
            finally:
                release.set()
        with patch.object(app, "_load_settings", return_value=settings()), patch.object(app.note_quality, "chunks", return_value=PARTS), patch.object(app, "_call_llm", side_effect=model), patch.object(app, "CLEANUP_CLOUD_SLOTS", slots):
            asyncio.run(run())
        self.assertEqual(len(calls), 3)
        self.assertTrue(slots.acquire(blocking=False))
        slots.release()

    def test_stream_sends_progress_then_result_and_validates_inputs(self):
        with patch.object(app, "_load_settings", return_value=settings("none")), patch.object(app, "_call_llm") as model:
            client = TestClient(app.app)
            response = client.post("/api/cleanup/stream", json={"kind": "compression", "body": "#A: Staff will review intake."})
            events = [json.loads(line) for line in response.text.splitlines()]
            self.assertEqual(events[0]["type"], "progress")
            self.assertEqual(events[-1]["type"], "result")
            self.assertTrue(events[-1]["data"]["ok"])
            self.assertEqual(response.headers["cache-control"], "no-store")
            for payload in ([], {}, {"kind": "bogus"}):
                self.assertEqual(client.post("/api/cleanup/stream", json=payload).status_code, 400)
            empty = client.post("/api/cleanup/stream", json={"kind": "compression", "body": ""})
            self.assertFalse(json.loads(empty.text)["data"]["ok"])
            model.assert_not_called()

    def test_stream_reports_unexpected_failure_without_source_or_key_details(self):
        async def fail(*args):
            raise RuntimeError("Private source data")
        with patch.object(app, "_reviewed_summary", side_effect=fail):
            response = TestClient(app.app).post("/api/cleanup/stream", json={"kind": "compression", "body": "text"})
        self.assertEqual(json.loads(response.text)["type"], "error")
        self.assertNotIn("Private source data", response.text)

    def test_http_status_is_retained_and_quota_errors_are_not_retried_as_format_errors(self):
        error = HTTPError("https://example.test/responses", 429, "Too many requests", {}, BytesIO(b'{"error":"quota"}'))
        with patch.object(app, "urlopen", side_effect=error):
            with self.assertRaises(app.ModelHTTPError) as caught:
                app._post_json("https://example.test/responses", {}, {})
        self.assertEqual(caught.exception.status_code, 429)
        for provider in ("openai", "openrouter"):
            config = settings(provider)
            config["api_keys"]["openrouter"] = "fake-key"
            with patch.object(app, "_post_json", side_effect=app.ModelHTTPError(429, "quota")) as post:
                with self.assertRaises(app.ModelHTTPError):
                    app._call_llm(config, "test prompt")
                self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
