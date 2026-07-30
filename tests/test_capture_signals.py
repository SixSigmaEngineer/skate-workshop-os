import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui"))
os.environ.setdefault("SKATE_ROOT", str(ROOT))
os.environ["SKATE_EMBED_BACKEND"] = "off"

import skate_lib  # noqa: E402
import app as skate_app  # noqa: E402


class CaptureSignalSyntaxTests(unittest.TestCase):
    """Both signal syntaxes count: compact #P: markers and readable labels."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "conversations" / "demo").mkdir(parents=True)
        (self.root / "sessions").mkdir()
        note = textwrap.dedent(
            """\
            ---
            title: Syntax test
            date: "2026-07-25"
            type: note
            session: demo
            status: active
            ---
            # Syntax test

            - #P: dashed hash pain
            #P: bare hash pain
            - Pain: dashed label pain
            Pain: bare label pain
            - Action Item: label with suffix
            - Question: readable question
            """
        )
        (self.root / "conversations" / "demo" / "2026-07-25-syntax-test.md").write_text(note, encoding="utf-8")
        self.originals = (skate_lib.SKATE_ROOT, skate_lib.CONVERSATIONS, skate_lib.SESSIONS)
        skate_lib.SKATE_ROOT = self.root
        skate_lib.CONVERSATIONS = self.root / "conversations"
        skate_lib.SESSIONS = self.root / "sessions"

    def tearDown(self):
        skate_lib.SKATE_ROOT, skate_lib.CONVERSATIONS, skate_lib.SESSIONS = self.originals
        self.temp.cleanup()

    def test_all_four_pain_forms_are_detected(self):
        entries = skate_lib.load_all_entries()
        self.assertEqual(len(entries), 1)
        markers = skate_lib.capture_markers(entries[0])
        self.assertEqual(len(markers["pain"]), 4)
        self.assertIn("bare label pain", markers["pain"])

    def test_label_variants_map_to_their_types(self):
        entries = skate_lib.load_all_entries()
        markers = skate_lib.capture_markers(entries[0])
        self.assertEqual(markers["action"], ["label with suffix"])
        self.assertEqual(markers["question"], ["readable question"])

    def test_rendered_bullets_are_decorated_for_both_syntaxes(self):
        html = "<ul><li>#P: hash form</li><li>Pain: label form</li><li>Recommendation: rec</li></ul>"
        out = skate_app._decorate_capture_markers(html)
        self.assertEqual(out.count("capture-marker-p"), 2)
        self.assertIn('capture-marker-r" title="Recommendation">Recommendation:</span>', out)


if __name__ == "__main__":
    unittest.main()
