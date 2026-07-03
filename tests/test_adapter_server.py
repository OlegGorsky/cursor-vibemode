from __future__ import annotations

import unittest

from cursor_vibemode.adapter_http import (
    rewrite_messages_event,
    upstream_error_message,
    upstream_headers,
)


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


if __name__ == "__main__":
    unittest.main()
