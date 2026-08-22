"""Notes must survive repeated saves without growing blank lines.

Regression test for the Windows save bug: an HTML textarea submits CRLF, and
Path.write_text() with the default newline=None then translates each LF to the
platform separator. On Windows that turns \r\n into \r\r\n, which reads back as
two line breaks - so every save doubled the blank lines in the note.
"""

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

import app as skate_app  # noqa: E402


def browser_submit(text: str) -> str:
    """What a browser sends: textarea values are normalised to CRLF."""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")


BODY = (
    "# Handoff note\n"
    "\n"
    "We met the intake team for ninety minutes.\n"
    "\n"
    "- #O: Families repeat their story at every handoff\n"
    "- #P: Each handoff resets context instead of carrying it forward\n"
)


class NoteLineEndingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "note.md"

    def tearDown(self):
        self.temp.cleanup()

    def _save(self, body: str) -> None:
        skate_app._write_entry(
            self.path, "Handoff note", "2026-08-21", "note",
            "demo", "Demo session", "active",
            [], [], [], "active", "manual note", body,
        )

    def _load_body(self) -> str:
        import frontmatter
        return frontmatter.load(self.path, encoding="utf-8").content

    def test_normalize_newlines_collapses_crlf_and_cr(self):
        self.assertEqual(skate_app._normalize_newlines("a\r\nb\rc\nd"), "a\nb\nc\nd")

    def test_repeated_saves_do_not_add_blank_lines(self):
        """The original bug: blank lines doubled on every round trip."""
        self._save(BODY)
        first = self._load_body()
        baseline = first.count("\n\n")

        current = first
        for _ in range(6):
            current = self._load_body()
            self._save(browser_submit(current))

        final = self._load_body()
        self.assertEqual(
            final.count("\n\n"), baseline,
            "blank lines changed across saves - the CRLF round trip has regressed",
        )
        self.assertEqual(final, first, "note content drifted across repeated saves")

    def test_no_carriage_returns_are_written_to_disk(self):
        """The vault is git-tracked and shared, so LF everywhere."""
        self._save(browser_submit(BODY))
        raw = self.path.read_bytes()
        self.assertNotIn(b"\r", raw, "note was written with CR bytes")

    def test_intentional_blank_lines_are_preserved(self):
        """Normalising must not flatten paragraphs the facilitator wanted."""
        spaced = "# T\n\npara one\n\npara two\n\n\npara three after two blanks\n"
        self._save(browser_submit(spaced))
        body = self._load_body()
        self.assertIn("para one\n\npara two", body)
        self.assertIn("para two\n\n\npara three", body)


if __name__ == "__main__":
    unittest.main()
