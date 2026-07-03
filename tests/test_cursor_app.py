from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cursor_vibemode.cursor_app import (
    LOCAL_MODE_DISABLED,
    LOCAL_MODE_ENABLED,
    inspect_cursor_app,
    patch_cursor_app,
)


def make_app(root: Path, *, local_mode: str | None = LOCAL_MODE_DISABLED) -> None:
    workbench = root / "out" / "vs" / "workbench"
    workbench.mkdir(parents=True)
    (root / "out").mkdir(exist_ok=True)
    marker = local_mode or "no local mode flag here"
    (workbench / "workbench.desktop.main.js").write_text(f"desktop {marker}", encoding="utf-8")
    (workbench / "workbench.glass.main.js").write_text(f"glass {marker}", encoding="utf-8")
    (root / "out" / "main.js").write_text(f"main {marker}", encoding="utf-8")
    (root / "product.json").write_text(
        json.dumps(
            {
                "checksums": {
                    "vs/workbench/workbench.desktop.main.js": "old",
                    "main.js": "old",
                }
            }
        ),
        encoding="utf-8",
    )


def checksum(path: Path) -> str:
    return base64.b64encode(hashlib.sha256(path.read_bytes()).digest()).decode("ascii").rstrip("=")


class CursorAppPatchTests(unittest.TestCase):
    def test_patch_enables_local_mode_and_updates_product_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_app(root)

            before = inspect_cursor_app(str(root))
            report = patch_cursor_app(str(root))
            after = inspect_cursor_app(str(root))

            self.assertEqual(before.state, "disabled")
            self.assertEqual(after.state, "enabled")
            self.assertFalse(report.already_enabled)
            self.assertIn("out/vs/workbench/workbench.desktop.main.js", report.changed_files)

            desktop = root / "out" / "vs" / "workbench" / "workbench.desktop.main.js"
            self.assertIn(LOCAL_MODE_ENABLED, desktop.read_text(encoding="utf-8"))
            self.assertNotIn(LOCAL_MODE_DISABLED, desktop.read_text(encoding="utf-8"))

            product = json.loads((root / "product.json").read_text(encoding="utf-8"))
            self.assertEqual(product["checksums"]["vs/workbench/workbench.desktop.main.js"], checksum(desktop))
            self.assertEqual(product["checksums"]["main.js"], checksum(root / "out" / "main.js"))
            self.assertTrue((root / "product.json.cursor-vibemode.bak").is_file())

    def test_patch_is_idempotent_when_local_mode_is_already_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_app(root, local_mode=LOCAL_MODE_ENABLED)

            report = patch_cursor_app(str(root))

            self.assertTrue(report.already_enabled)
            self.assertEqual(report.changed_files, ())

    def test_old_bundle_without_local_mode_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_app(root, local_mode=None)

            report = patch_cursor_app(str(root))

            self.assertTrue(report.not_required)
            self.assertEqual(report.changed_files, ())

    @unittest.skipIf(__import__("sys").platform != "linux", "shadow copy fallback is Linux-only")
    def test_readonly_app_creates_shadow_copy_and_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source_root = base / "source" / "cursor"
            app_root = source_root / "resources" / "app"
            source_root.mkdir(parents=True)
            (source_root / "cursor").write_text("#!/bin/sh\n", encoding="utf-8")
            (source_root / "bin").mkdir()
            (source_root / "bin" / "cursor").write_text("#!/bin/sh\n", encoding="utf-8")
            make_app(app_root)
            for rel in (
                "product.json",
                "out/main.js",
                "out/vs/workbench/workbench.desktop.main.js",
                "out/vs/workbench/workbench.glass.main.js",
            ):
                (app_root / rel).chmod(0o444)

            home = base / "home"
            env = {"HOME": str(home), "XDG_DATA_HOME": str(base / "xdg")}
            with mock.patch.dict("os.environ", env, clear=False):
                report = patch_cursor_app(str(app_root))

            self.assertIsNotNone(report.launcher)
            self.assertTrue(report.launcher and report.launcher.is_file())
            self.assertTrue(str(report.launcher).startswith(str(home)))
            self.assertIn("/bin/cursor", report.launcher.read_text(encoding="utf-8"))
            self.assertNotEqual(report.app_root, app_root)
            self.assertIn(LOCAL_MODE_DISABLED, (app_root / "out" / "main.js").read_text(encoding="utf-8"))
            self.assertIn(LOCAL_MODE_ENABLED, (report.app_root / "out" / "main.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
