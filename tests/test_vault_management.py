"""Deletion, credential removal, and local relevance checks in disposable vaults."""
import ast
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "ui")]
os.environ.setdefault("SKATE_ROOT", str(ROOT / "demo-vault"))
os.environ["SKATE_EMBED_BACKEND"] = "off"

import app
import frontmatter
import note_quality
import skate_lib
import vault_trash
from fastapi.testclient import TestClient


# Fictional dialogue exercises the reported sports-tangent pattern.
SPORTS_CHAT = """My favorite hockey team is the Comets.
But I follow another team too.
They are my primary team.
I bought season tickets for years.
After moving I became a season ticket holder for the Falcons.
The Falcons became my Pacific team.
I also follow the Wolves because a friend likes their hockey games.
So the Wolves are my central team.
That is a long answer about my favorite hockey team.
"""


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for module in (app, skate_lib):
            for name, value in (("SKATE_ROOT", self.root), ("CONVERSATIONS", self.root / "conversations"), ("SESSIONS", self.root / "sessions")):
                p = patch.object(module, name, value)
                p.start()
                self.addCleanup(p.stop)
        for name, value in (("SETTINGS_PATH", self.root / "settings.json"), ("RECORDER", {"state": "idle"})):
            p = patch.object(app, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(skate_lib, "GRIND_CACHE_DIR", self.root / ".cache/grind")
        p.start()
        self.addCleanup(p.stop)
        self.client = TestClient(app.app)
        self.settings = copy.deepcopy(app.DEFAULT_SETTINGS)
        self.settings["provider"] = "none"
        app._save_settings(self.settings)

    def note(self, name, session="alpha", body="#O: Staff review intake."):
        path = self.root / "conversations" / "shared" / name
        app._write_note(path, frontmatter.Post(body, title=name, session=session, date="2026-09-12", type="note"))
        return path

    def session(self, key="alpha"):
        path = self.root / "sessions" / key / "README.md"
        app._write_note(path, frontmatter.Post("Session focus", title=key.title(), session=key, status="active"))
        return path

    def remove_note(self, path):
        return self.client.post("/api/trash/note/" + path.relative_to(app.CONVERSATIONS).as_posix(), json={"confirmed": True})

    def test_note_removal_and_restore_preserve_bytes_attachments_and_other_notes(self):
        path = self.note("one.md")
        original = path.read_bytes()
        other = self.note("two.md")
        attachment = path.parent / "attachments" / "original.txt"
        attachment.parent.mkdir()
        attachment.write_text("Original recording transcript", encoding="utf-8")
        response = self.remove_note(path)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(path.exists())
        self.assertTrue(other.exists())
        self.assertTrue(attachment.exists())
        self.assertEqual([e.title for e in skate_lib.load_all_entries()], ["two.md"])
        self.assertIn("one.md", self.client.get("/trash").text)
        restored = self.client.post("/api/trash/restore/" + response.json()["id"])
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(vault_trash.items(self.root), [])

    def test_session_removal_uses_membership_and_restores_empty_session(self):
        metadata = self.session()
        a = self.note("alpha.md")
        b = self.note("beta.md", "beta")
        response = self.client.post("/api/trash/session/alpha", json={"confirmed": True, "expected_count": 1})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(metadata.exists())
        self.assertFalse(a.exists())
        self.assertTrue(b.exists())
        self.assertNotIn("alpha", [row["key"] for row in skate_lib.session_stats(skate_lib.load_all_entries())])
        self.client.post("/api/trash/restore/" + response.json()["id"])
        self.assertTrue(metadata.exists())
        self.assertTrue(a.exists())
        empty = self.session("empty")
        removed = self.client.post("/api/trash/session/empty", json={"confirmed": True, "expected_count": 0})
        self.assertEqual(removed.status_code, 200)
        self.assertFalse(empty.exists())
        self.client.post("/api/trash/restore/" + removed.json()["id"])
        self.assertTrue(empty.exists())

    def test_unassigned_includes_blank_and_explicit_unassigned_notes(self):
        blank = self.note("blank.md", "")
        explicit = self.note("explicit.md", "unassigned")
        self.assertEqual(len(skate_lib.filter_entries(skate_lib.load_all_entries(), session="unassigned")), 2)
        response = self.client.post("/api/trash/session/unassigned", json={"confirmed": True, "expected_count": 2})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(blank.exists())
        self.assertFalse(explicit.exists())

    def test_confirmation_and_new_note_count_are_required(self):
        path = self.note("one.md")
        for payload in ({}, {"confirmed": "true"}, {"confirmed": True, "expected_count": 0}):
            response = self.client.post("/api/trash/session/alpha", json=payload)
            self.assertIn(response.status_code, (400, 409))
            self.assertTrue(path.exists())
        self.assertEqual(self.client.post("/api/trash/note/shared/one.md", json={}).status_code, 400)
        self.assertTrue(path.exists())

    def test_session_recording_blocks_removal_until_saved(self):
        path = self.note("one.md")
        for state in ("recording", "stopping", "transcribing"):
            with patch.object(app, "RECORDER", {"state": state, "session": "alpha"}):
                response = self.client.post("/api/trash/session/alpha", json={"confirmed": True, "expected_count": 1})
                self.assertEqual(response.status_code, 409)
                self.assertTrue(path.exists())

    def test_restore_conflict_never_overwrites_or_partially_restores(self):
        first, second = self.note("first.md"), self.note("second.md")
        removed = self.client.post("/api/trash/session/alpha", json={"confirmed": True, "expected_count": 2}).json()
        second.write_text("Replacement note", encoding="utf-8")
        response = self.client.post("/api/trash/restore/" + removed["id"])
        self.assertEqual(response.status_code, 409)
        self.assertFalse(first.exists())
        self.assertEqual(second.read_text(encoding="utf-8"), "Replacement note")
        self.assertEqual(len(vault_trash.items(self.root)), 1)

    def test_filesystem_failures_roll_back_completed_moves(self):
        first, second = self.note("first.md"), self.note("second.md")
        rename = Path.rename
        def fail_second(path, target):
            if path == second:
                raise PermissionError("Simulated locked note")
            return rename(path, target)
        with patch.object(Path, "rename", fail_second):
            with self.assertRaises(PermissionError):
                vault_trash.move(self.root, [first, second], title="Alpha", kind="session", session="alpha")
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())
        self.assertEqual(vault_trash.items(self.root), [])

    def test_paths_cannot_reach_keys_or_other_directories(self):
        keyfile = self.root / "settings.json"
        before = keyfile.read_bytes()
        for file_id in ("../settings.json", "..%2Fsettings.json", "../outside.md", "shared/attachments/file.txt"):
            response = self.client.post("/api/trash/note/" + file_id, json={"confirmed": True})
            self.assertNotEqual(response.status_code, 200)
        for relative in ("../outside.md", "conversations/../../outside.md", "sessions/C:/outside.md", "settings.json"):
            with self.assertRaises(vault_trash.TrashError):
                vault_trash._original(self.root, relative)
        self.assertEqual(keyfile.read_bytes(), before)

    def test_cached_grind_does_not_return_deleted_note_evidence(self):
        path = self.note("one.md")
        skate_lib.save_grind_snapshot("alpha", {"pains": [{"title": "Old evidence"}]}, skate_lib.load_all_entries())
        self.assertIsNotNone(skate_lib.load_grind_snapshot("alpha"))
        self.remove_note(path)
        self.assertIsNone(skate_lib.load_grind_snapshot("alpha"))

    def test_deleted_demo_files_are_not_reseeded_on_restart(self):
        path = self.note("one.md")
        seed = self.root / "app" / "vault-seed" / "conversations" / "shared" / "one.md"
        seed.parent.mkdir(parents=True)
        shutil.copy2(path, seed)
        removed = self.remove_note(path).json()
        # Load only the seed functions, without starting the desktop launcher.
        tree = ast.parse((ROOT / "portable_launcher.py").read_text(encoding="utf-8"))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {"_seed_vault", "_copy_if_missing"}]
        namespace = {"Path": Path, "json": json, "shutil": shutil, "EXE_DIR": self.root / "app"}
        exec(compile(ast.Module(body=functions, type_ignores=[]), "seed-functions", "exec"), namespace)
        namespace["_seed_vault"](self.root)
        self.assertFalse(path.exists())
        self.client.post("/api/trash/restore/" + removed["id"])
        namespace["_seed_vault"](self.root)
        self.assertTrue(path.exists())

    def test_empty_explicit_vault_does_not_switch_to_other_notes(self):
        with patch.dict(os.environ, {"SKATE_ROOT": str(self.root)}):
            self.assertEqual(skate_lib._resolve_skate_root(), self.root)

    def test_saved_keys_can_be_removed_individually_without_exposure(self):
        for provider in self.settings["api_keys"]:
            with self.subTest(provider=provider):
                self.settings["api_keys"] = {key: "test-private-" + key for key in self.settings["api_keys"]}
                app._save_settings(self.settings)
                html = self.client.get("/settings").text
                self.assertNotIn("test-private-", html)
                self.assertIn(f'name="clear_{provider}_api_key"', html)
                self.client.post("/settings", data={"provider": "none", f"clear_{provider}_api_key": "on", f"{provider}_api_key": "autofilled-value"})
                saved = app._load_settings()["api_keys"]
                self.assertEqual(saved[provider], "")
                for other in saved:
                    if other != provider:
                        self.assertEqual(saved[other], "test-private-" + other)
                self.assertFalse(app._public_settings(app._load_settings())["api_key_present"][provider])

    def test_blank_key_keeps_existing_and_removal_disconnects_ai(self):
        self.settings.update(provider="openai")
        self.settings["api_keys"]["openai"] = "test-private-key"
        app._save_settings(self.settings)
        self.client.post("/settings", data={"provider": "openai", "openai_api_key": ""})
        self.assertTrue(app._llm_available(app._load_settings()))
        self.client.post("/settings", data={"provider": "openai", "clear_openai_api_key": "on"})
        self.assertFalse(app._llm_available(app._load_settings()))


class RelevanceTests(unittest.TestCase):
    def test_sports_conversation_and_neighboring_team_statements_are_excluded(self):
        reviewed = note_quality.screen(SPORTS_CHAT, "Onsite planning workshop")
        self.assertEqual(reviewed["kept_units"], 0)
        self.assertEqual(reviewed["excluded_count"], 9)
        self.assertIn("Comets", reviewed["excluded"][0]["text"])

    def test_sports_names_are_not_blacklisted_and_real_work_is_preserved(self):
        for text, focus in [
            ("Hurricanes delayed customer onboarding by two days.", ""),
            ("The hockey team needs a better ticket billing process.", ""),
            ("My favorite hockey team is the Hurricanes.", "Hockey fan experience"),
            ("Our team is overloaded and cannot finish the assigned work.", ""),
            ('#A: Maria will review the client queue on Friday. Do not approve 15 requests.', ""),
        ]:
            with self.subTest(text=text):
                reviewed = note_quality.screen(text, focus)
                self.assertEqual(reviewed["excluded_count"], 0)
                self.assertIn(text, reviewed["text"])

    def test_sports_context_stops_at_work_evidence(self):
        reviewed = note_quality.screen("I like hockey.\nThe team has an onboarding backlog.\nOur team is called Atlas.")
        self.assertIn("Our team is called Atlas.", reviewed["text"])
        self.assertIn("onboarding backlog", reviewed["text"])

    def test_uncertain_prose_is_retained_but_not_promoted_into_gist_or_signals(self):
        source = "Our team is called Atlas.\nThe quasar has an unusual spectrum.\nOkay, yeah."
        data = app._local_note_compression("Workshop", "", source)
        self.assertEqual(data["observations"], [])
        self.assertEqual(len(data["key_points"]), 2)
        self.assertNotIn("Atlas", data["gist"])
        self.assertIn("Additional context to review", app._compression_markdown(data))

    def test_long_no_ai_cleanup_keeps_late_actions_and_reports_sports_exclusions(self):
        source = SPORTS_CHAT + "\n" + "\n".join(f"Staff need to review intake record {i}." for i in range(700)) + "\nDecision: Pause rollout.\n#A: Maria will audit the dashboard Friday."
        settings = copy.deepcopy(app.DEFAULT_SETTINGS)
        settings["provider"] = "none"
        with patch.object(app, "_load_settings", return_value=settings), patch.object(app, "_call_llm") as model:
            for endpoint, field in (("/api/compress-note", "body"), ("/api/summarize-transcript", "transcript")):
                data = TestClient(app.app).post(endpoint, json={"title": "Intake", field: source}).json()
                self.assertTrue(data["ok"])
                self.assertNotIn("comets", data["markdown"].lower())
                self.assertIn("record 699", data["markdown"])
                self.assertIn("Maria will audit", data["markdown"])
                self.assertIn("Pause rollout", data["markdown"])
                self.assertEqual(data["review"]["excluded_count"], 9)
                self.assertEqual(data["review"]["chunks_processed"], 1)
            model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
