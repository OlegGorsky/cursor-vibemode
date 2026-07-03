from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from cursor_vibemode.cursor_db import apply_setup
from cursor_vibemode.models import cursor_model_id
from cursor_vibemode.paths import APP_USER_KEY


def make_db(path: Path, app_user: dict) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)"
        )
        conn.execute(
            "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
            (APP_USER_KEY, json.dumps(app_user)),
        )
        conn.commit()
    finally:
        conn.close()


def add_composer_data(path: Path, composer_data: dict) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE cursorDiskKV (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)"
        )
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            ("composerData:test", json.dumps(composer_data)),
        )
        conn.commit()
    finally:
        conn.close()


class CursorDbMigrationTests(unittest.TestCase):
    def test_setup_cleans_stale_aliases_from_app_user_and_composers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.vscdb"
            stale_alias = cursor_model_id("gpt-5.4")
            make_db(db, stale_app_user(stale_alias))
            add_composer_data(db, stale_composer_data(stale_alias))

            apply_setup(
                db,
                api_key="sk-test",
                base_url="https://api.vibemod.pro/v1",
                model_id="gpt-5.4",
                model_ids=["gpt-5.4", "gpt-5.5"],
                backup=False,
            )

            app_user_raw, composer_raw = read_raw_payloads(db)
            self.assertNotIn("vibemode-", app_user_raw)
            self.assertNotIn("vibemode-", composer_raw)
            composer = json.loads(composer_raw)
            self.assertEqual(composer["modelConfig"]["modelName"], "gpt-5.4")
            self.assertEqual(
                composer["modelConfig"]["selectedModels"][0]["modelId"],
                "gpt-5.4",
            )


def stale_app_user(stale_alias: str) -> dict:
    return {
        "composerModel": stale_alias,
        "aiSettings": {
            "modelConfig": {"composer": stale_model_config(stale_alias)},
            "userAddedModels": [stale_alias],
            "modelOverrideEnabled": [stale_alias],
            "modelLastUsedAt": {stale_alias: 100},
        },
        "availableDefaultModels2": [
            {"name": stale_alias, "serverModelName": "gpt-5.4", "isUserAdded": True}
        ],
    }


def stale_composer_data(stale_alias: str) -> dict:
    return {"modelConfig": stale_model_config(stale_alias)}


def stale_model_config(stale_alias: str) -> dict:
    return {
        "modelName": stale_alias,
        "selectedModels": [{"modelId": stale_alias, "parameters": []}],
    }


def read_raw_payloads(path: Path) -> tuple[str, str]:
    conn = sqlite3.connect(path)
    try:
        app_user_raw = conn.execute(
            "SELECT value FROM ItemTable WHERE key=?", (APP_USER_KEY,)
        ).fetchone()[0]
        composer_raw = conn.execute(
            "SELECT value FROM cursorDiskKV WHERE key='composerData:test'"
        ).fetchone()[0]
        return app_user_raw, composer_raw
    finally:
        conn.close()


if __name__ == "__main__":
    unittest.main()
