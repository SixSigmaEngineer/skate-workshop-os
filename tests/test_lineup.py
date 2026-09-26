import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ui"))

import app as skate_app  # noqa: E402
import skate_lib  # noqa: E402


class LineupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.conversations = self.root / "conversations"
        self.sessions = self.root / "sessions"
        self.conversations.mkdir()
        self.sessions.mkdir()
        self.originals = {
            "app_conversations": skate_app.CONVERSATIONS,
            "app_sessions": skate_app.SESSIONS,
            "lib_root": skate_lib.SKATE_ROOT,
            "lib_conversations": skate_lib.CONVERSATIONS,
            "lib_sessions": skate_lib.SESSIONS,
        }
        skate_app.CONVERSATIONS = self.conversations
        skate_app.SESSIONS = self.sessions
        skate_lib.SKATE_ROOT = self.root
        skate_lib.CONVERSATIONS = self.conversations
        skate_lib.SESSIONS = self.sessions
        self.client = TestClient(skate_app.app)

    def tearDown(self):
        skate_app.CONVERSATIONS = self.originals["app_conversations"]
        skate_app.SESSIONS = self.originals["app_sessions"]
        skate_lib.SKATE_ROOT = self.originals["lib_root"]
        skate_lib.CONVERSATIONS = self.originals["lib_conversations"]
        skate_lib.SESSIONS = self.originals["lib_sessions"]
        self.temp.cleanup()

    def test_flexible_action_can_be_added_and_landed(self):
        response = self.client.post(
            "/lineup/new",
            data={"title": "Send the readout", "lineup_kind": "action", "cadence": "once"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        entry = skate_lib.load_all_entries()[0]
        self.assertEqual(entry.entry_type, "action")
        self.assertEqual(entry.lineup_status, "open")
        self.assertEqual(entry.session, "")

        response = self.client.post(
            f"/lineup/toggle/{entry.file_id}",
            data={"return_to": "/lineup"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(skate_lib.load_all_entries()[0].lineup_status, "landed")

    def test_long_action_titles_save_from_both_forms_without_losing_text(self):
        title = "Follow up with the workshop owners and confirm the process improvement details " * 5
        for route in ("/lineup/new", "/new"):
            with self.subTest(route=route):
                response = self.client.post(route, data={"title": title, "entry_type": "action"}, follow_redirects=False)
                self.assertEqual(response.status_code, 303)
        entries = skate_lib.load_all_entries()
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(entry.title == title.strip() for entry in entries))
        self.assertTrue(all(len(entry.path.name) < 120 for entry in entries))

    def test_failed_action_save_keeps_form_values_and_explains_recovery(self):
        with patch.object(skate_app, "_write_entry", side_effect=PermissionError("locked")):
            response = self.client.post("/lineup/new", data={"title": "Confirm owners", "owner": "Brian", "details": "Retain this context"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("could not save", response.text)
        for value in ("Confirm owners", "Brian", "Retain this context"):
            self.assertIn(value, response.text)

    def test_standard_work_advances_to_its_next_cycle(self):
        today = date.today()
        self.client.post(
            "/lineup/new",
            data={
                "title": "Enter client hours",
                "lineup_kind": "standard_work",
                "cadence": "weekly",
                "due_date": today.isoformat(),
            },
        )
        entry = skate_lib.load_all_entries()[0]
        self.client.post(f"/lineup/toggle/{entry.file_id}", data={"return_to": "/lineup"})
        completed = skate_lib.load_all_entries()[0]
        self.assertEqual(completed.last_completed, today.isoformat())
        self.assertEqual(completed.due_date, (today + timedelta(days=7)).isoformat())
        self.assertEqual(completed.lineup_status, "open")

    def test_action_marker_can_be_promoted_with_source_link(self):
        source = self.conversations / "notes" / "session-note.md"
        skate_app._write_entry(
            source, "Session note", "2026-07-25", "note", "alpha", "Alpha", "active",
            [], [], [], "active", "manual note", "# Session note\n\n- #A: Confirm pilot owners\n",
        )
        source_entry = skate_lib.load_entry(source)
        action = skate_app._embedded_actions(source_entry)[0]
        response = self.client.post(
            f"/lineup/promote/{source_entry.file_id}",
            data={"fingerprint": action["fingerprint"]},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        tracked = [entry for entry in skate_lib.load_all_entries() if entry.entry_type == "action"]
        self.assertEqual(len(tracked), 1)
        self.assertEqual(tracked[0].session, "alpha")
        self.assertEqual(tracked[0].captured_from, action["captured_from"])
        self.assertEqual(tracked[0].relationships[0]["target"], source_entry.file_id)


if __name__ == "__main__":
    unittest.main()
