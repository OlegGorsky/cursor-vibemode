from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from cursor_vibemode.adapter_http import (
    rewrite_messages_event,
    upstream_error_message,
    upstream_headers,
)
from cursor_vibemode.adapter_server import load_config
from cursor_vibemode.keys import save_local_key


class AdapterServerTests(unittest.TestCase):
    def test_messages_headers_prefer_bearer_vibemode_key(self) -> None:
        headers = {
            "authorization": "Bearer sk-good",
            "x-api-key": "wrong-key",
            "content-type": "application/json",
        }

        result = upstream_headers(headers, "/messages")

        self.assertEqual(result["x-api-key"], "sk-good")
        self.assertEqual(result["Authorization"], "Bearer sk-good")

    def test_configured_key_overrides_cursor_headers(self) -> None:
        headers = {"authorization": "Bearer wrong", "x-api-key": "wrong"}

        result = upstream_headers(headers, "/messages", "sk-configured")

        self.assertEqual(result["x-api-key"], "sk-configured")
        self.assertEqual(result["Authorization"], "Bearer sk-configured")

    def test_configured_key_wins_even_with_new_key_format(self) -> None:
        result = upstream_headers({"authorization": "Bearer cursor-token"}, "/chat", "vibe-key")

        self.assertEqual(result["Authorization"], "Bearer vibe-key")

    def test_cursor_session_token_is_not_forwarded_as_key(self) -> None:
        result = upstream_headers({"authorization": "Bearer cursor-token"}, "/chat")

        self.assertNotIn("Authorization", result)

    def test_messages_headers_fall_back_to_x_api_key(self) -> None:
        result = upstream_headers({"x-api-key": "sk_from_x"}, "/messages")

        self.assertEqual(result["x-api-key"], "sk_from_x")
        self.assertEqual(result["Authorization"], "Bearer sk_from_x")

    def test_upstream_headers_replace_python_user_agent(self) -> None:
        result = upstream_headers({"user-agent": "Python-urllib/3.13"}, "/models")

        self.assertIn("Mozilla/5.0", result["User-Agent"])

    def test_upstream_error_message_extracts_openai_error(self) -> None:
        body = b'{"error":{"message":"Invalid API key.","type":"AuthError"}}'

        self.assertEqual(upstream_error_message(body), "Invalid API key.")

    def test_rewrite_messages_event_converts_openai_error_sse(self) -> None:
        event = (
            b"event: error\n"
            b'data: {"error":{"message":"Invalid API key.","type":"AuthError"}}\n\n'
        )

        rewritten = rewrite_messages_event(event).decode("utf-8")

        self.assertIn('"type":"error"', rewritten)
        self.assertIn('"api_error"', rewritten)
        self.assertIn("Invalid API key.", rewritten)

    def test_adapter_config_falls_back_to_saved_local_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CURSOR_VIBEMODE_HOME": tmp}
            with mock.patch.dict(os.environ, env, clear=True):
                save_local_key("sk-local")
                config_path = os.path.join(tmp, "adapter.json")
                with open(config_path, "w", encoding="utf-8") as stream:
                    json.dump({"upstream_base_url": "https://api.vibemod.pro/v1"}, stream)

                config = load_config()

        self.assertEqual(config.api_key, "sk-local")


if __name__ == "__main__":
    unittest.main()
