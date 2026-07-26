import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui"))
os.environ.setdefault("SKATE_ROOT", str(ROOT))
os.environ["SKATE_EMBED_BACKEND"] = "off"

from mcp_server import service  # noqa: E402
import skate_lib  # noqa: E402


class TempVaultCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "conversations").mkdir()
        (self.root / "sessions").mkdir()
        self.originals = {
            "root": skate_lib.SKATE_ROOT,
            "conversations": skate_lib.CONVERSATIONS,
            "sessions": skate_lib.SESSIONS,
        }
        skate_lib.SKATE_ROOT = self.root
        skate_lib.CONVERSATIONS = self.root / "conversations"
        skate_lib.SESSIONS = self.root / "sessions"

    def tearDown(self):
        skate_lib.SKATE_ROOT = self.originals["root"]
        skate_lib.CONVERSATIONS = self.originals["conversations"]
        skate_lib.SESSIONS = self.originals["sessions"]
        self.temp.cleanup()


class MCPWriteToolTests(TempVaultCase):
    def test_create_session_then_add_note(self):
        created = service.create_session("Pilot Retro Workshop", summary="Retro focus")
        self.assertTrue(created["created"])
        self.assertEqual(created["session"], "pilot-retro-workshop")

        again = service.create_session("Pilot Retro Workshop")
        self.assertFalse(again["created"])
        self.assertTrue(again["existed"])

        note = service.add_note(
            title="Volunteers wait for badge approvals",
            body="- #P: Badge approvals take two weeks.\n- #Q: Who owns the queue?",
            session="pilot-retro-workshop",
            entry_type="pain",
            tags="badging, onboarding",
        )
        self.assertTrue(note["created"])
        note_path = skate_lib.CONVERSATIONS / note["memory_id"]
        self.assertTrue(note_path.exists())
        text = note_path.read_text(encoding="utf-8")
        self.assertIn("added by MCP agent via SKATE MCP", text)
        self.assertIn("type: pain", text)

    def test_add_note_creates_missing_session_readme(self):
        note = service.add_note(
            title="First signal",
            body="- #O: Something observed.",
            session="Brand New Session",
        )
        self.assertTrue(note["created"])
        self.assertTrue((skate_lib.SESSIONS / "brand-new-session" / "README.md").exists())

    def test_add_note_validates_input(self):
        self.assertIn("error", service.add_note("", "body", "s"))
        self.assertIn("error", service.add_note("title", "", "s"))
        self.assertIn("error", service.add_note("title", "body", ""))
        self.assertIn("error", service.add_note("t", "b", "s", entry_type="malware"))

    def test_add_note_never_escapes_the_vault(self):
        note = service.add_note(
            title="../../evil",
            body="- #O: attempt",
            session="../../../outside",
        )
        self.assertTrue(note["created"])
        target = (skate_lib.CONVERSATIONS / note["memory_id"]).resolve()
        self.assertTrue(str(target).startswith(str(skate_lib.CONVERSATIONS.resolve())))

    def test_action_note_appears_in_lineup(self):
        service.add_note(
            title="Publish pilot charter",
            body="- #A: Publish the charter.",
            session="pilot-retro-workshop",
            entry_type="action",
            owner="Program Director",
            due_date="2026-08-01",
        )
        lineup = service.get_lineup()
        self.assertEqual(lineup["open_count"], 1)
        self.assertEqual(lineup["actions"][0]["title"], "Publish pilot charter")
        self.assertEqual(lineup["actions"][0]["owner"], "Program Director")
        self.assertEqual(lineup["actions"][0]["due_date"], "2026-08-01")

        scoped = service.get_lineup(session="pilot-retro-workshop", include_landed=False)
        self.assertEqual(len(scoped["actions"]), 1)
        empty = service.get_lineup(session="another-session")
        self.assertEqual(len(empty["actions"]), 0)


class MCPLineupDemoVaultTests(unittest.TestCase):
    """get_lineup against the committed Harborlight demo vault."""

    def test_demo_vault_lineup_contains_both_action_plans(self):
        lineup = service.get_lineup()
        titles = {row["title"] for row in lineup["actions"]}
        self.assertIn("Action plan - launch the two-week warm-handoff pilot", titles)
        self.assertIn("Action plan - launch the volunteer readiness sprint", titles)


if __name__ == "__main__":
    unittest.main()
