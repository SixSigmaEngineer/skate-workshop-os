"""The GRIND must read the whole note, not just its opening paragraph.

Before this was fixed, _pain_score() scored `title + summary + tags`, where
`summary` is the "## Summary" section or - failing that - the FIRST non-heading
paragraph. A facilitator typing fast in the room routinely describes the real
problem three paragraphs down without stopping to mark it, and those notes were
invisible to the GRIND entirely.

Explicitly marked signals (``#P:``) must still rank first: this widens what the
GRIND can see, it does not change what it prioritises.
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
from skate_lib import Entry, MARKED_PAIN_SCORE, _pain_score, design_insights  # noqa: E402


def make_entry(title, body, tags=()):
    entry = Entry(
        path=skate_lib.CONVERSATIONS / "demo" / "note.md",
        title=title,
        date="2026-08-21",
    )
    entry.body = body
    entry.tags = list(tags)
    entry.session = "demo"
    entry.entry_type = "note"
    return entry


BURIED_PAIN = """# Intake review

We met with the intake team for ninety minutes.

The team walked through the current process end to end.

Duplicate entry across four disconnected forms is creating serious delay,
and staff describe the reconciliation calls as the most manual part of
their week. This is the real bottleneck.
"""


class PainScoreScopeTests(unittest.TestCase):
    def test_keywords_below_the_first_paragraph_are_scored(self):
        entry = make_entry("Intake review", BURIED_PAIN)
        # The opening paragraph deliberately contains no keyword at all.
        self.assertNotIn("delay", entry.summary.lower())
        self.assertGreater(
            _pain_score(entry), 0,
            "pain keywords in later paragraphs were ignored",
        )

    def test_title_matches_outrank_body_matches(self):
        in_title = make_entry("The bottleneck in intake", "Routine notes.\n")
        in_body = make_entry("Intake review", "Notes.\n\nThere is a bottleneck.\n")
        self.assertGreater(_pain_score(in_title), _pain_score(in_body))

    def test_repetition_does_not_inflate_a_score(self):
        once = make_entry("Review", "Notes.\n\nThis is a bottleneck.\n")
        many = make_entry("Review", "Notes.\n\n" + "This is a bottleneck. " * 40)
        self.assertEqual(_pain_score(once), _pain_score(many))

    def test_inferred_scores_never_reach_the_marked_score(self):
        loaded = make_entry(
            "pain problem friction bottleneck delay confusing manual waste risk",
            "hard difficult stuck unclear missing fails failure slow confusion\n",
            tags=["pain", "problem", "risk"],
        )
        self.assertLess(_pain_score(loaded), MARKED_PAIN_SCORE)

    def test_a_note_with_no_pain_language_still_scores_zero(self):
        calm = make_entry("Attendees", "Notes.\n\nSix people joined the session.\n")
        self.assertEqual(_pain_score(calm), 0)


class GrindOrderingTests(unittest.TestCase):
    def test_marked_pains_rank_above_inferred_ones(self):
        marked = make_entry("Session A", "# A\n\n- #P: Referral status disappears\n")
        inferred = make_entry(
            "Session B",
            "# B\n\nOpening.\n\nA serious bottleneck and constant delay.\n",
        )
        insights = design_insights([marked, inferred])
        self.assertTrue(insights["pains"], "no pains produced")
        self.assertEqual(
            insights["pains"][0]["score"], MARKED_PAIN_SCORE,
            "an inferred pain displaced an explicitly marked one",
        )

    def test_unmarked_note_still_reaches_the_grind(self):
        inferred = make_entry(
            "Intake review", BURIED_PAIN,
        )
        insights = design_insights([inferred])
        titles = " ".join(p["title"] for p in insights["pains"])
        self.assertIn("Intake review", titles)


if __name__ == "__main__":
    unittest.main()
