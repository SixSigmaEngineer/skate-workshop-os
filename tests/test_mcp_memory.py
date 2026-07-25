import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui"))
os.environ.setdefault("SKATE_ROOT", str(ROOT))
os.environ["SKATE_EMBED_BACKEND"] = "off"

from mcp_server import service  # noqa: E402
import skate_lib  # noqa: E402


class MCPMemoryServiceTests(unittest.TestCase):
    def test_lists_only_active_sessions(self):
        result = service.list_active_sessions()

        self.assertGreaterEqual(result["count"], 2)
        self.assertTrue(all(row["status"] == "active" for row in result["sessions"]))
        self.assertIn(
            "harborlight-service-access-2026",
            {row["session"] for row in result["sessions"]},
        )

    def test_search_returns_bounded_evidence_and_reduction_metrics(self):
        result = service.search_memory("families repeat their story", top_k=3)

        self.assertEqual(result["retrieval_mode"], "lexical")
        self.assertLessEqual(result["returned_memory_count"], 3)
        self.assertGreater(result["estimated_context_reduction_percent"], 0)
        self.assertIn("repeat", result["results"][0]["title"].lower())

    def test_path_traversal_is_rejected(self):
        result = service.get_memory_object("../../settings.json")

        self.assertIn("error", result)

    def test_session_context_is_governed_and_bounded(self):
        result = service.get_session_context(
            "harborlight-service-access-2026",
            query="consent handoff",
            top_k=4,
        )

        self.assertEqual(result["session"], "harborlight-service-access-2026")
        self.assertLessEqual(len(result["evidence"]), 4)
        self.assertTrue(
            all(item["session"] == "harborlight-service-access-2026" for item in result["evidence"])
        )

    def test_trace_evidence_returns_typed_links(self):
        memory_id = (
            "harborlight-service-access-2026/"
            "2026-07-15-hl-stated-problem-repeat-story.md"
        )
        result = service.trace_evidence(memory_id)

        self.assertEqual(result["root"]["memory_id"], memory_id)
        self.assertGreater(result["link_count"], 0)
        self.assertTrue(all(link["type"] for link in result["links"]))

    def test_saved_grind_snapshot_is_retrievable(self):
        entries = skate_lib.filter_entries(
            skate_lib.load_all_entries(),
            session="harborlight-service-access-2026",
        )
        insights = {"mode": "ai", "model": "gpt-5.6", "pains": [{"title": "Test pain"}]}
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(skate_lib, "GRIND_CACHE_DIR", Path(temp)):
                skate_lib.save_grind_snapshot(
                    "harborlight-service-access-2026",
                    insights,
                    entries,
                )
                result = service.get_grind_outputs("harborlight-service-access-2026")

        self.assertEqual(result["source"], "saved_grind_run")
        self.assertEqual(result["insights"]["model"], "gpt-5.6")


if __name__ == "__main__":
    unittest.main()
