from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from cursor_vibemode.adapter_process import adapter_command_env


class AdapterProcessTests(unittest.TestCase):
    def test_windows_adapter_starts_python_module_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CURSOR_VIBEMODE_HOME": tmp}
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("cursor_vibemode.adapter_process.is_windows", return_value=True):
                    command, process_env = adapter_command_env()

        self.assertIn("-m", command)
        self.assertIn("cursor_vibemode", command)
        self.assertIn("adapter", command)
        self.assertIn("serve", command)
        self.assertIsNotNone(process_env)
        python_path = process_env["PYTHONPATH"].replace("\\", "/")
        self.assertTrue(python_path.endswith("runtime/src"))


if __name__ == "__main__":
    unittest.main()
