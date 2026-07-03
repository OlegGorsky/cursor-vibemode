from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cursor_vibemode.cursor_db import (
    apply_setup,
    read_openai_key,
    read_status,
    remove_openai_key,
    set_openai_enabled,
)
from cursor_vibemode.keys import resolve_api_key, save_local_key
from cursor_vibemode.paths import APP_USER_KEY, MARKER_KEY, OPENAI_KEY_STORAGE


def make_db(path: Path, app_user: dict | None = None) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
        if app_user is not None:
            conn.execute(
                "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
                (APP_USER_KEY, json.dumps(app_user)),
            )
        conn.commit()
    finally:
        conn.close()


class CursorVibemodeTests(unittest.TestCase):
    def test_setup_writes_key_base_url_and_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.vscdb"
            make_db(db, {"aiSettings": {"modelConfig": {"composer": {}}}})

            apply_setup(
                db,
                api_key="sk-test-123456",
                base_url="https://api.vibemod.pro/v1/",
                model_id="gpt-5.4",
                model_ids=["gpt-5.4", "gpt-5.5"],
                backup=False,
            )

            status = read_status(db)
            self.assertTrue(status.has_key)
            self.assertTrue(status.use_openai_key)
            self.assertEqual(status.base_url, "https://api.vibemod.pro/v1")
            self.assertEqual(status.composer_model, "gpt-5.4")
            self.assertIn("gpt-5.5", status.registered_models)
            self.assertEqual(read_openai_key(db), "sk-test-123456")

    def test_setup_creates_missing_application_user_and_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.vscdb"
            make_db(db)

            apply_setup(
                db,
                api_key="sk-test",
                base_url="https://example.com/v1",
                model_id="custom-model",
                model_ids=["custom-model"],
                backup=False,
            )

            conn = sqlite3.connect(db)
            try:
                app_user = json.loads(
                    conn.execute(
                        "SELECT value FROM ItemTable WHERE key=?", (APP_USER_KEY,)
                    ).fetchone()[0]
                )
                marker = json.loads(
                    conn.execute(
                        "SELECT value FROM ItemTable WHERE key=?", (MARKER_KEY,)
                    ).fetchone()[0]
                )
                key_value = conn.execute(
                    "SELECT value FROM ItemTable WHERE key=?", (OPENAI_KEY_STORAGE,)
                ).fetchone()[0]
            finally:
                conn.close()

            self.assertEqual(app_user["openAIBaseUrl"], "https://example.com/v1")
            self.assertTrue(app_user["useOpenAIKey"])
            self.assertEqual(key_value, "sk-test")
            self.assertEqual(marker[OPENAI_KEY_STORAGE], 0)

    def test_enable_disable_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.vscdb"
            make_db(db, {})
            apply_setup(
                db,
                api_key="sk-test",
                base_url="https://example.com/v1",
                model_id="gpt-5.4",
                model_ids=["gpt-5.4"],
                backup=False,
            )

            set_openai_enabled(db, False, backup=False)
            self.assertFalse(read_status(db).use_openai_key)

            set_openai_enabled(db, True, backup=False)
            self.assertTrue(read_status(db).use_openai_key)

            remove_openai_key(db, backup=False)
            status = read_status(db)
            self.assertFalse(status.use_openai_key)
            self.assertFalse(status.has_key)

    def test_resolve_api_key_prompts_in_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CURSOR_VIBEMODE_HOME": tmp}
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("cursor_vibemode.keys.read_secret", return_value="sk-from-prompt"):
                    result = resolve_api_key(
                        explicit_key=None,
                        replace_key=False,
                        non_interactive=False,
                    )

            self.assertEqual(result.value, "sk-from-prompt")
            self.assertEqual(result.source, "prompt")

    def test_resolve_api_key_ignores_codex_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CURSOR_VIBEMODE_HOME": tmp, "CODEX_KEY": "sk-codex"}
            with mock.patch.dict(os.environ, env, clear=True):
                with self.assertRaises(RuntimeError):
                    resolve_api_key(
                        explicit_key=None,
                        replace_key=False,
                        non_interactive=True,
                    )

    def test_resolve_api_key_can_reuse_local_cursor_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CURSOR_VIBEMODE_HOME": tmp}
            with mock.patch.dict(os.environ, env, clear=True):
                save_local_key("sk-local")
                with mock.patch("cursor_vibemode.keys.read_secret", return_value=""):
                    result = resolve_api_key(
                        explicit_key=None,
                        replace_key=False,
                        non_interactive=False,
                    )

            self.assertEqual(result.value, "sk-local")
            self.assertEqual(result.source, "Saved cursor-vibemode key found")


if __name__ == "__main__":
    unittest.main()
