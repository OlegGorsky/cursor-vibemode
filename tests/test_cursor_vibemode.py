from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from cursor_vibemode.api import endpoint_for_model, endpoint_payload
from cursor_vibemode.cursor_db import (
    apply_setup,
    backup_database,
    read_openai_key,
    read_status,
    remove_openai_key,
    set_openai_enabled,
)
from cursor_vibemode.keys import resolve_api_key, save_local_key
from cursor_vibemode.models import cursor_model_id
from cursor_vibemode.operations import is_cloudflare_browser_block, parse_model_list, setup_cursor
from cursor_vibemode.paths import APP_USER_KEY, MARKER_KEY, OPENAI_KEY_STORAGE
from cursor_vibemode.surfaces import detect_surfaces
from cursor_vibemode.url_safety import host_warnings, is_private_host


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
            alias = cursor_model_id("gpt-5.5")
            self.assertTrue(status.has_key)
            self.assertTrue(status.use_openai_key)
            self.assertEqual(status.base_url, "https://api.vibemod.pro/v1")
            self.assertEqual(status.composer_model, "gpt-5.4")
            self.assertIn("gpt-5.5", status.registered_models)
            self.assertEqual(read_openai_key(db), "sk-test-123456")

            conn = sqlite3.connect(db)
            try:
                app_user = json.loads(
                    conn.execute(
                        "SELECT value FROM ItemTable WHERE key=?", (APP_USER_KEY,)
                    ).fetchone()[0]
                )
            finally:
                conn.close()
            catalog = {
                item["name"]: item
                for item in app_user["availableDefaultModels2"]
                if isinstance(item, dict) and item.get("name")
            }
            self.assertEqual(catalog[alias]["serverModelName"], "gpt-5.5")
            self.assertEqual(catalog[alias]["clientDisplayName"], "GPT-5.5 [Vibemode]")

    def test_setup_updates_unknown_model_config_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.vscdb"
            make_db(
                db,
                {
                    "aiSettings": {
                        "modelConfig": {
                            "composer": {},
                            "future-agent-window": {},
                        }
                    }
                },
            )

            apply_setup(
                db,
                api_key="sk-test",
                base_url="https://example.com/v1",
                model_id="gpt-5.4",
                model_ids=["gpt-5.4"],
                backup=False,
            )

            conn = sqlite3.connect(db)
            try:
                app_user = json.loads(
                    conn.execute(
                        "SELECT value FROM ItemTable WHERE key=?", (APP_USER_KEY,)
                    ).fetchone()[0]
                )
            finally:
                conn.close()

            future_mode = app_user["aiSettings"]["modelConfig"]["future-agent-window"]
            self.assertEqual(future_mode["modelName"], cursor_model_id("gpt-5.4"))
            self.assertEqual(
                future_mode["selectedModels"][0]["modelId"],
                cursor_model_id("gpt-5.4"),
            )

    def test_setup_uses_cursor_alias_for_native_model_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.vscdb"
            native_gpt = {
                "name": "gpt-5.5",
                "serverModelName": "gpt-5.5",
                "clientDisplayName": "GPT-5.5",
                "vendor": {"id": 2, "displayName": "OpenAI"},
            }
            old_custom = {
                "name": "deepseek-v4-pro",
                "serverModelName": "deepseek-v4-pro",
                "isUserAdded": True,
            }
            make_db(
                db,
                {
                    "aiSettings": {
                        "modelConfig": {"composer": {}},
                        "userAddedModels": ["gpt-5.5", "deepseek-v4-pro"],
                        "modelOverrideEnabled": ["gpt-5.5", "deepseek-v4-pro"],
                    },
                    "availableDefaultModels2": [native_gpt, old_custom],
                },
            )

            apply_setup(
                db,
                api_key="sk-test",
                base_url="https://api.vibemod.pro/v1",
                model_id="gpt-5.5",
                model_ids=["gpt-5.5", "deepseek-v4-pro"],
                backup=False,
            )

            conn = sqlite3.connect(db)
            try:
                app_user = json.loads(
                    conn.execute(
                        "SELECT value FROM ItemTable WHERE key=?", (APP_USER_KEY,)
                    ).fetchone()[0]
                )
            finally:
                conn.close()

            gpt_alias = cursor_model_id("gpt-5.5")
            deepseek_alias = cursor_model_id("deepseek-v4-pro")
            catalog = {
                item["name"]: item
                for item in app_user["availableDefaultModels2"]
                if isinstance(item, dict) and item.get("name")
            }
            self.assertIn("gpt-5.5", catalog)
            self.assertEqual(catalog["gpt-5.5"]["clientDisplayName"], "GPT-5.5")
            self.assertEqual(catalog[gpt_alias]["serverModelName"], "gpt-5.5")
            self.assertTrue(catalog[gpt_alias]["isUserAdded"])
            self.assertNotIn("deepseek-v4-pro", catalog)
            self.assertIn(deepseek_alias, catalog)
            self.assertEqual(app_user["composerModel"], gpt_alias)
            self.assertEqual(
                app_user["aiSettings"]["modelConfig"]["composer"]["selectedModels"][0][
                    "modelId"
                ],
                gpt_alias,
            )
            self.assertNotIn("gpt-5.5", app_user["aiSettings"]["userAddedModels"])
            self.assertNotIn("deepseek-v4-pro", app_user["aiSettings"]["userAddedModels"])
            self.assertIn(gpt_alias, app_user["aiSettings"]["userAddedModels"])
            self.assertIn(deepseek_alias, app_user["aiSettings"]["userAddedModels"])

    def test_detects_editor_and_agent_window_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.vscdb"
            make_db(db, {})
            conn = sqlite3.connect(db)
            try:
                conn.execute(
                    "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
                    ("glass.localAgentProjects.v1", "{}"),
                )
                conn.commit()
            finally:
                conn.close()

            report = detect_surfaces(db)

            self.assertTrue(report.has_editor)
            self.assertTrue(report.has_agents)
            self.assertEqual(report.display, "редактор и агентное окно")

    def test_auto_model_list_prefers_api_models(self) -> None:
        models = parse_model_list(None, ["gpt-5.4", "deepseek-v4-pro", "gpt-5.4"])

        self.assertEqual(models, ["gpt-5.4", "deepseek-v4-pro"])
        self.assertEqual(parse_model_list("vibemode-gpt-5.5"), ["gpt-5.5"])
        self.assertEqual(parse_model_list("gpt-5.5,vibemode-gpt-5.5"), ["gpt-5.5"])

    def test_cloudflare_catalog_block_falls_back_during_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.vscdb"
            make_db(db, {})
            args = Namespace(
                replace_key=False,
                key="sk-test",
                non_interactive=True,
                base_url="https://api.vibemod.pro/v1",
                models=None,
                model="gpt-5.4",
                no_backup=True,
                no_save_key=True,
                skip_api_check=False,
                deep_api_check=False,
            )
            error = RuntimeError(
                'HTTP 403 | {"error_code":1010,"error_name":"browser_signature_banned"}'
            )

            with mock.patch("cursor_vibemode.operations.check_models", side_effect=error):
                output = StringIO()
                with redirect_stdout(output):
                    result = setup_cursor(args, db_path=db, title="setup")

            status = read_status(db)
            self.assertEqual(result, 0)
            self.assertTrue(status.has_key)
            self.assertIn("deepseek-v4-pro", status.registered_models)
            self.assertIn("Cloudflare заблокировал", output.getvalue())

    def test_cloudflare_browser_block_detector(self) -> None:
        self.assertTrue(is_cloudflare_browser_block("Error 1010: Access denied"))
        self.assertTrue(is_cloudflare_browser_block("browser_signature_banned"))
        self.assertFalse(is_cloudflare_browser_block("HTTP 401 unauthorized"))

    def test_setup_reuses_saved_key_when_user_presses_enter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.vscdb"
            make_db(db, {})
            env = {"CURSOR_VIBEMODE_HOME": tmp}
            args = Namespace(
                replace_key=False,
                key=None,
                non_interactive=False,
                base_url="https://api.vibemod.pro/v1",
                models="gpt-5.4",
                model="gpt-5.4",
                no_backup=True,
                no_save_key=True,
                skip_api_check=True,
                deep_api_check=False,
            )

            with mock.patch.dict(os.environ, env, clear=True):
                save_local_key("sk-reused")
                with mock.patch("cursor_vibemode.keys.read_secret", return_value=""):
                    output = StringIO()
                    with redirect_stdout(output):
                        result = setup_cursor(args, db_path=db, title="setup")

            self.assertEqual(result, 0)
            self.assertEqual(read_openai_key(db), "sk-reused")
            self.assertIn("Настройка завершена", output.getvalue())

    def test_endpoint_routing_uses_responses_for_gpt_only(self) -> None:
        self.assertEqual(endpoint_for_model("gpt-5.4"), "responses")
        self.assertEqual(endpoint_for_model("GPT-5.4-mini"), "responses")
        self.assertEqual(endpoint_for_model("deepseek-v4-pro"), "chat/completions")
        self.assertEqual(endpoint_for_model("kimi-k2.6"), "chat/completions")

        responses_payload = endpoint_payload("gpt-5.4", "responses")
        chat_payload = endpoint_payload("deepseek-v4-pro", "chat/completions")
        self.assertIn("input", responses_payload)
        self.assertIn("messages", chat_payload)

    def test_private_url_warnings(self) -> None:
        self.assertTrue(is_private_host("127.0.0.1"))
        self.assertTrue(is_private_host("192.168.1.2"))
        self.assertTrue(is_private_host("localhost"))
        self.assertFalse(is_private_host("api.vibemod.pro"))

        warnings = host_warnings("http://127.0.0.1:8000/v1")
        self.assertGreaterEqual(len(warnings), 2)

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

    def test_backup_cleanup_keeps_only_recent_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.vscdb"
            make_db(db, {})
            for index in range(5):
                old = db.with_name(f"state.vscdb.bak-2020010{index + 1}-000000")
                old.write_text("old", encoding="utf-8")

            backup_database(db)

            backups = sorted(db.parent.glob("state.vscdb.bak-*"))
            self.assertLessEqual(len(backups), 3)
            self.assertFalse((db.parent / "state.vscdb.bak-20200101-000000").exists())

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
            self.assertEqual(result.source, "Ключ Vibemode уже сохранен")


if __name__ == "__main__":
    unittest.main()
