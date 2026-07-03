from __future__ import annotations

import os
import pty
import select
import sys
import time
import unittest


def run_read_secret(input_bytes: bytes) -> tuple[bool, str]:
    command = [
        sys.executable,
        "-c",
        (
            "from cursor_vibemode.keys import read_secret; "
            "value = read_secret('Prompt: '); "
            "print('VALUE=' + repr(value), flush=True)"
        ),
    ]
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp(command[0], command)

    output = b""
    sent = False
    exited = False
    deadline = time.time() + 3
    while time.time() < deadline:
        readable, _, _ = select.select([fd], [], [], 0.02)
        if readable:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                done, _ = os.waitpid(pid, os.WNOHANG)
                if done:
                    exited = True
                break
            output += chunk
            if b"Prompt: " in output and not sent:
                os.write(fd, input_bytes)
                sent = True
        try:
            done, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            exited = True
            break
        if done:
            exited = True
            break

    if not exited:
        done, _ = os.waitpid(pid, os.WNOHANG)
        exited = bool(done)
    if not exited:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
        os.waitpid(pid, 0)
    os.close(fd)
    return exited, output.decode("utf-8", errors="replace")


@unittest.skipIf(sys.platform == "win32", "PTY test is Unix-only")
class TerminalInputTests(unittest.TestCase):
    def test_read_secret_accepts_single_enter(self) -> None:
        exited, output = run_read_secret(b"\r")

        self.assertTrue(exited, output)
        self.assertIn("VALUE=''", output)

    def test_read_secret_accepts_key_with_single_enter(self) -> None:
        exited, output = run_read_secret(b"sk-test\r")

        self.assertTrue(exited, output)
        self.assertIn("VALUE='sk-test'", output)


if __name__ == "__main__":
    unittest.main()
