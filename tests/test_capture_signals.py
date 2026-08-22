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
            # P heading-style pain
            - #P colonless dashed pain
            - Pain: dashed label pain
            Pain: bare label pain
            - Action Item: label with suffix
            - Question: readable question
            """
        )
        (self.root / "conversations" / "demo" / "2026-07-25-syntax-test.md").write_text(note, encoding="utf-8")
        self.originals = (
            skate_lib.SKATE_ROOT, skate_lib.CONVERSATIONS, skate_lib.SESSIONS,
            skate_app.CONVERSATIONS, skate_app.SESSIONS,
        )
        skate_lib.SKATE_ROOT = self.root
        skate_lib.CONVERSATIONS = skate_app.CONVERSATIONS = self.root / "conversations"
        skate_lib.SESSIONS = skate_app.SESSIONS = self.root / "sessions"

    def tearDown(self):
        (skate_lib.SKATE_ROOT, skate_lib.CONVERSATIONS, skate_lib.SESSIONS,
         skate_app.CONVERSATIONS, skate_app.SESSIONS) = self.originals
        self.temp.cleanup()

    def test_all_four_pain_forms_are_detected(self):
        entries = skate_lib.load_all_entries()
        self.assertEqual(len(entries), 1)
        markers = skate_lib.capture_markers(entries[0])
        self.assertEqual(len(markers["pain"]), 6)
        self.assertIn("bare label pain", markers["pain"])
        self.assertIn("heading-style pain", markers["pain"])

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

    def test_dashless_markers_render_as_separate_colored_lines(self):
        from fastapi.testclient import TestClient

        client = TestClient(skate_app.app)
        response = client.get("/entry/demo/2026-07-25-syntax-test.md")
        self.assertEqual(response.status_code, 200)
        # Both hash pains (dashed and bare) must appear as decorated lines,
        # not merged into one paragraph.
        self.assertGreaterEqual(response.text.count("capture-line-p"), 4)
        self.assertNotIn("<h1>P heading-style pain</h1>", response.text)

    def test_compression_cleans_llm_bullets_before_adding_plain_markers(self):
        fallback = skate_app._local_note_compression("Test", "", "raw note")
        normalized = skate_app._normalize_compression(
            {
                "gist": "A gist",
                "consulting_context": "A context",
                "pain_points": ["- #P: Repeated entry"],
                "observations": ["* Observation: Staff reconcile records"],
                "actions": ["#A Assign an owner"],
            },
            fallback,
        )
        self.assertEqual(normalized["pain_points"], ["Repeated entry"])
        self.assertEqual(normalized["observations"], ["Staff reconcile records"])
        self.assertEqual(normalized["actions"], ["Assign an owner"])
        markdown = skate_app._compression_markdown(normalized)
        self.assertIn("#P: Repeated entry", markdown)
        self.assertNotIn("- #P:", markdown)

    def test_grind_prewarms_a_deterministic_calm_signal_layout(self):
        template = (ROOT / "ui" / "templates" / "graph.html").read_text(encoding="utf-8")
        self.assertIn("signalsByParent", template)
        self.assertIn("function stableFraction", template)
        self.assertIn("const clusterThemes", template)
        self.assertNotIn("Math.random()", template)
        self.assertIn("Math.max(dx * dx + dy * dy, 144)", template)
        self.assertNotIn("Math.max(90, Math.min(width - 90", template)
        self.assertIn("Soft guards keep stray nodes reachable", template)
        self.assertIn("nodes.forEach((node) => { node.vx = 0; node.vy = 0; node.vz = 0; });", template)
        self.assertIn("physicsStep(0.12)", template)

    def test_grind_2d_has_lightweight_exploration_controls(self):
        template = (ROOT / "ui" / "templates" / "graph.html").read_text(encoding="utf-8")
        self.assertIn('id="grindWorkspace"', template)
        self.assertIn('id="graphNodeSearch"', template)
        self.assertIn("function curvedRail", template)
        self.assertIn('class="node-halo"', template)
        self.assertIn('class="selected-neighbors"', template)
        self.assertIn('classList.toggle("mode-2d"', template)
        self.assertIn("#f9fbfd", template)
        self.assertIn("background:transparent", template)


if __name__ == "__main__":
    unittest.main()
