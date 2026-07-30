import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ui"))

import app as skate_app  # noqa: E402
import skate_lib  # noqa: E402


class SessionConnectionReviewTests(unittest.TestCase):
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

    def _note(self, filename, title, body, session="alpha", themes=None, tags=None):
        path = self.conversations / "notes" / filename
        skate_app._write_entry(
            path,
            title,
            "2026-07-30",
            "note",
            session,
            session.title(),
            "active",
            tags or [],
            themes or [],
            [],
            "active",
            "manual note",
            body,
        )
        return skate_lib.load_entry(path)

    def _ai_settings(self):
        settings = json.loads(json.dumps(skate_app.DEFAULT_SETTINGS))
        settings["provider"] = "openai"
        settings["api_keys"]["openai"] = "sk-test"
        return settings

    def test_sessions_page_offers_review_button(self):
        self._note("a.md", "Intake pain", "#P: Intake is repeated")
        response = self.client.get("/sessions")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Review Connections", response.text)
        self.assertIn('data-session="alpha"', response.text)

    def test_local_review_audits_missing_themes_without_inventing_links(self):
        self._note("a.md", "Data issue", "#P: Data quality is poor")
        settings = self._ai_settings()
        settings["provider"] = "none"
        with patch.object(skate_app, "_load_settings", return_value=settings):
            response = self.client.post("/api/sessions/alpha/review-connections")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["review"]["mode"], "local")
        self.assertEqual(data["review"]["relationships"], [])
        self.assertIn("Data Quality", data["review"]["metadata"][0]["themes"])

    def test_ai_review_normalizes_real_note_targets(self):
        first = self._note("a.md", "Repeated intake", "#P: Families repeat intake")
        second = self._note("b.md", "Four forms", "#O: Four forms collect the same data")
        result = {
            "metadata": [
                {
                    "file_id": first.file_id,
                    "entry_type": "pain",
                    "themes": ["Process Waste"],
                    "tags": ["duplicate intake"],
                    "reason": "The note describes repeated work.",
                }
            ],
            "relationships": [
                {
                    "source": second.file_id,
                    "target": first.file_id,
                    "type": "causes",
                    "note": "The duplicate forms cause families to repeat intake.",
                },
                {
                    "source": second.file_id,
                    "target": "notes/missing.md",
                    "type": "supports",
                    "note": "Invalid target must be removed.",
                },
            ],
        }
        with (
            patch.object(skate_app, "_load_settings", return_value=self._ai_settings()),
            patch.object(skate_app, "_call_llm", return_value=json.dumps(result)),
        ):
            response = self.client.post("/api/sessions/alpha/review-connections")
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["review"]["metadata"]), 1)
        self.assertEqual(len(data["review"]["relationships"]), 1)
        self.assertEqual(data["review"]["relationships"][0]["type"], "causes")

    def test_apply_updates_only_approved_session_notes_and_preserves_body(self):
        first = self._note("a.md", "Repeated intake", "#P: Families repeat intake")
        second = self._note("b.md", "Four forms", "#O: Four forms collect the same data")
        payload = {
            "metadata": [
                {
                    "file_id": first.file_id,
                    "entry_type": "pain",
                    "themes": ["Process Waste"],
                    "tags": ["duplicate-intake"],
                    "reason": "Missing metadata.",
                }
            ],
            "relationships": [
                {
                    "source": second.file_id,
                    "target": first.file_id,
                    "type": "causes",
                    "note": "Four forms cause repeated intake.",
                }
            ],
        }
        response = self.client.post("/api/sessions/alpha/apply-connections", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["metadata_applied"], 1)
        self.assertEqual(response.json()["relationships_applied"], 1)
        updated_first = skate_lib.load_entry(first.path)
        updated_second = skate_lib.load_entry(second.path)
        self.assertEqual(updated_first.entry_type, "pain")
        self.assertIn("Process Waste", updated_first.themes)
        self.assertIn("#P: Families repeat intake", updated_first.body)
        self.assertEqual(updated_second.relationships[0]["target"], first.file_id)

    def test_apply_rejects_relationship_to_another_session(self):
        first = self._note("a.md", "Alpha note", "#P: Alpha pain")
        outside = self._note("outside.md", "Beta note", "#O: Beta evidence", session="beta")
        response = self.client.post(
            "/api/sessions/alpha/apply-connections",
            json={
                "metadata": [],
                "relationships": [
                    {
                        "source": first.file_id,
                        "target": outside.file_id,
                        "type": "supports",
                        "note": "Must not cross the requested scope.",
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["relationships_applied"], 0)
        self.assertEqual(skate_lib.load_entry(first.path).relationships, [])


if __name__ == "__main__":
    unittest.main()
