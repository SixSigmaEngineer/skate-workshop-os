"""AI synthesis must send the right parts of a note, not just the first ones.

Regression tests for the GRIND payload. History of the defect, in order:
the payload once sent only `summary` (a note's first paragraph - 8% of a
realistic note); then the whole body but truncated tail-first, which kept a
long meeting's opening and threw away its decisions; now an excerpt selected
by relevance - marked lines first, then the first and last chunks, then
chunks scored on the same pain vocabulary the local GRIND uses - with
"[...]" marking elided text.
"""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui"))
os.environ.setdefault("SKATE_ROOT", str(ROOT))
os.environ["SKATE_EMBED_BACKEND"] = "off"

import skate_lib  # noqa: E402
from skate_lib import Entry  # noqa: E402
import app as skate_app  # noqa: E402


def make_entry(title, body):
    entry = Entry(
        path=skate_lib.CONVERSATIONS / "demo" / "note.md",
        title=title,
        date="2026-08-22",
    )
    entry.body = body
    entry.tags = []
    entry.themes = []
    entry.session = "demo"
    entry.entry_type = "note"
    return entry


FILLER = (
    "The group discussed scheduling and reviewed the agenda in general "
    "terms without reaching any conclusions. " * 6
)


def long_meeting(paragraphs_before=130, paragraphs_mid=60, paragraphs_late=30):
    parts = ["# Vendor workshop\n\nWe convened the full team for the review."]
    parts += [FILLER] * paragraphs_before
    parts += [
        "Staff described the reconciliation calls as a serious bottleneck "
        "causing delay and manual rework every week."
    ]
    parts += [FILLER] * paragraphs_mid
    parts += ["- #A: Maria to inventory the duplicated fields across the forms."]
    parts += [FILLER] * paragraphs_late
    parts += [
        "Decision: we will pilot the consent-aware handoff for two weeks "
        "before any platform purchase."
    ]
    return "\n\n".join(parts)


class SelectBodyExcerptTests(unittest.TestCase):
    def test_short_body_passes_through_untouched(self):
        body = "# T\n\nOne paragraph only.\n\n- #P: a pain"
        excerpt, truncated = skate_app._select_body_excerpt(body, 2000)
        self.assertEqual(excerpt, body)
        self.assertFalse(truncated)
        self.assertNotIn(skate_app.BODY_GAP_MARK, excerpt)

    def test_never_exceeds_the_limit(self):
        for limit in (400, 2200, 9000):
            excerpt, truncated = skate_app._select_body_excerpt(long_meeting(), limit)
            self.assertLessEqual(len(excerpt), limit)
            self.assertTrue(truncated)

    def test_keeps_the_end_of_a_long_meeting(self):
        """Tail-first truncation threw away decisions; selection must not."""
        excerpt, _ = skate_app._select_body_excerpt(long_meeting(), 9000)
        self.assertIn("Decision: we will pilot", excerpt)

    def test_keeps_buried_pain_and_markers_over_filler(self):
        excerpt, _ = skate_app._select_body_excerpt(long_meeting(), 9000)
        self.assertIn("reconciliation calls", excerpt)
        self.assertIn("#A: Maria", excerpt)

    def test_marks_gaps_where_text_was_skipped(self):
        excerpt, _ = skate_app._select_body_excerpt(long_meeting(), 9000)
        self.assertIn(skate_app.BODY_GAP_MARK, excerpt)

    def test_reaches_into_a_transcript_with_no_blank_lines(self):
        wall = "speaker: routine remark about logistics\n" * 900
        wall += "speaker: this manual reconciliation is the real bottleneck\n"
        wall += "speaker: closing remark\n" * 200
        excerpt, truncated = skate_app._select_body_excerpt(wall, 9000)
        self.assertTrue(truncated)
        self.assertIn("real bottleneck", excerpt)


class EntryPayloadTests(unittest.TestCase):
    def test_payload_body_respects_allocated_limits(self):
        entries = [make_entry(f"N{i}", "word " * 5000) for i in range(13)]
        limits = skate_app._allocate_body_budget(
            [len(e.body.strip()) for e in entries]
        )
        for pay, limit in zip(skate_app._entry_payload(entries), limits):
            self.assertLessEqual(len(pay["body"]), limit)

    def test_single_long_note_keeps_its_decision(self):
        pay = skate_app._entry_payload([make_entry("W", long_meeting())])[0]
        self.assertTrue(pay["body_truncated"])
        self.assertIn("Decision: we will pilot", pay["body"])

    def test_summary_is_not_sent(self):
        pay = skate_app._entry_payload([make_entry("T", "# T\n\nBody text.")])[0]
        self.assertNotIn("summary", pay)


if __name__ == "__main__":
    unittest.main()
