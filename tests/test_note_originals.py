import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "ui")]
import app
import note_quality
import note_sources
import skate_lib
from mcp_server import service
from fastapi.testclient import TestClient


class NoteOriginalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for module in (app, skate_lib):
            for key, value in (("SKATE_ROOT", self.root), ("CONVERSATIONS", self.root / "conversations"), ("SESSIONS", self.root / "sessions")):
                p = patch.object(module, key, value)
                p.start()
                self.addCleanup(p.stop)
        self.client = TestClient(app.app)

    def archive(self, text, name="original-note-test.txt", session="note-originals"):
        result = self.client.post(f"/api/attachments?session={session}&filename={name}", content=text.encode("utf-8"))
        self.assertTrue(result.json()["ok"])
        source_id = session + "/" + result.json()["path"]
        return source_id, f"[Original notes / transcript](/entry/{source_id})"

    def save(self, body, session="alpha", status="active"):
        path = app.CONVERSATIONS / "notes/test.md"
        app._write_entry(path, "Intake workshop", "2026-09-24", "note", session, session, "active",
                         [], [], [], status, "manual note", body)
        return "notes/test.md"

    def test_full_original_and_cleaned_text_are_separate_and_pageable_through_mcp(self):
        raw = "dirty notes →\r\n" + "Do not lose this unedited line.\n" * 950 + "LAST COMMITMENT"
        source_id, link = self.archive(raw)
        clean = "## Cleaned Notes\n\nThe team reviewed intake.\n\n#A: Maria will review the client form."
        memory_id = self.save(clean + "\n\n" + link)
        memory = service.get_memory_object(memory_id)
        self.assertIn(clean, memory["body"])
        self.assertNotIn("LAST COMMITMENT", memory["body"])
        self.assertEqual(memory["signals"]["action"], ["Maria will review the client form."])
        self.assertEqual(memory["original_sources"][0]["source_id"], source_id)
        chunks, offset = [], 0
        while offset is not None:
            page = service.get_memory_original(memory_id, source_id, offset, 12000)
            chunks.append(page["text"])
            offset = page["next_offset"]
        self.assertEqual("".join(chunks), raw)
        self.assertGreater(len(chunks), 1)
        self.assertIn("Original notes &amp; transcripts", self.client.get("/entry/" + memory_id).text)

    def test_repeated_cleanup_preserves_both_sources_after_session_changes(self):
        first, link1 = self.archive("First dirty draft")
        second, link2 = self.archive("Second working version", "original-note-second.txt")
        memory_id = self.save("#O: Staff review intake.\n" + link1 + "\n" + link2, session="beta")
        self.assertEqual(len(service.get_memory_object(memory_id)["original_sources"]), 2)
        self.assertEqual(service.get_memory_original(memory_id, first)["text"], "First dirty draft")
        self.assertEqual(service.get_memory_original(memory_id, second)["text"], "Second working version")

    def test_legacy_original_link_is_readable(self):
        source_id, _ = self.archive("Legacy source", session="alpha")
        memory_id = self.save("[Original note text](attachments/original-note-test.txt)")
        self.assertEqual(service.get_memory_original(memory_id, source_id)["text"], "Legacy source")

    def test_unlinked_sources_and_inactive_notes_are_not_exposed_by_mcp(self):
        source_id, link = self.archive("Private original")
        memory_id = self.save("No source link")
        self.assertIn("error", service.get_memory_original(memory_id, source_id))
        self.save(link, status="inactive")
        self.assertIn("error", service.get_memory_original(memory_id, source_id))
        self.save(link)
        session_file = app.SESSIONS / "alpha/README.md"
        app._write_note(session_file, app.frontmatter.Post("", title="Alpha", session="alpha", status="inactive"))
        self.assertIn("error", service.get_memory_original(memory_id, source_id))

    def test_original_endpoint_rejects_unrelated_files_and_traversal(self):
        for source_id in ("../settings.json", "alpha/attachments/other.txt", "alpha/attachments/../../settings.json", "alpha\\attachments\\original-note-test.txt"):
            self.assertEqual(self.client.get("/api/note-originals", params={"source_id": source_id}).status_code, 404)

    def test_cleaned_note_body_can_be_read_past_the_first_page(self):
        body = "#O: Staff review intake.\n" * 1000 + "TAIL"
        memory_id = self.save(body)
        first = service.get_memory_object(memory_id)
        second = service.get_memory_object(memory_id, offset=first["next_offset"])
        rest = service.get_memory_object(memory_id, offset=second["next_offset"]) if second["next_offset"] is not None else {"body": ""}
        self.assertEqual(first["body"] + second["body"] + rest["body"], body)

    def test_summary_prose_and_hashtag_signals_are_both_retained(self):
        narrative = "Staff review intake manually, which delays approvals. Maria agreed to review the form before Friday."
        fallback = app._local_note_compression("Intake", "", "#A: Maria will review the client form.")
        normalized = app._normalize_compression({"meeting_summary": narrative}, fallback)
        rendered = app._compression_markdown(normalized)
        self.assertIn(narrative, rendered)
        self.assertIn("#A: Maria will review the client form.", rendered)
        self.assertNotIn("- Action Item:", rendered)
        for prompt in (app._compression_prompt("Intake", "", "source"), app._transcript_summary_prompt("Intake", "source")):
            self.assertIn(note_quality.SUMMARY_PROSE_RULES, prompt)

    def test_repeated_cleanup_does_not_turn_archive_links_into_observations(self):
        source = "**Meeting summary**\n\nStaff review the client form.\n\n**Signals**\n\n#O: Staff review the client form.\n\n[Original notes / transcript](/entry/note-originals/attachments/original-note-test.txt)"
        result = app._local_note_compression("Intake", "", source)
        self.assertEqual(result["observations"], ["Staff review the client form."])
        self.assertNotIn("original-note", app._compression_markdown(result))
