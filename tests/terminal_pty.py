"""Drive the real thin TUI against an isolated Host supplied by the JS test."""
from __future__ import annotations

import fcntl
import os
import select
import shutil
import signal
import struct
import subprocess
import sys
import termios
import time


def main() -> None:
    entry, root = sys.argv[1:]
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 60, 0, 0))
    process = subprocess.Popen([shutil.which("node") or "node", entry, "--install-root", root,
        "--workspace", "ts_001", "--session-id", "session_1"], stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    captured = bytearray()

    def expect(text: bytes) -> None:
        deadline = time.monotonic() + 8
        start = len(captured)
        while text not in captured[start:]:
            if time.monotonic() > deadline:
                raise AssertionError(f"PTY did not display {text!r}; output={bytes(captured[-2500:])!r}")
            if select.select([master], [], [], 0.1)[0]:
                captured.extend(os.read(master, 65536))

    try:
        expect(b"fake-model")
        os.write(master, b"PTY fixture request\r")
        expect(b"Message accepted by Host.")
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 90, 0, 0))
        process.send_signal(signal.SIGWINCH)
        os.write(master, b"\x0b")
        expect(b"Commands")
        os.write(master, b"\x1b")
        # Separate Escape from the following key; adjacent bytes encode Alt+D.
        time.sleep(0.1)
        os.write(master, b"\x04")
        expect(b"Detached from Host.")
        assert process.wait(timeout=3) == 0
        print("PTY attach, input, receipt, resize, detach passed")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        os.close(master)


if __name__ == "__main__":
    main()
