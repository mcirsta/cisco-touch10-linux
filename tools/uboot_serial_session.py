#!/usr/bin/env python3
"""Hold the Touch 10 service UART open and log it during one boot test.

Type a line on stdin to send it followed by CR. ':quit' closes the session.
No bytes are sent to the panel until a line is explicitly entered.
"""

from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import select
import sys
import termios


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_D3081QEX-if00-port0")
    parser.add_argument("--log", required=True)
    args = parser.parse_args()

    fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    previous = termios.tcgetattr(fd)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        attrs = termios.tcgetattr(fd)
        attrs[0] = attrs[1] = attrs[3] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[4] = attrs[5] = termios.B115200
        attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        path = Path(args.log)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab", buffering=0) as log:
            print(f"SERIAL_READY {args.port} log={path}", flush=True)
            while True:
                ready, _, _ = select.select([fd, sys.stdin], [], [], 0.5)
                if fd in ready:
                    data = os.read(fd, 65536)
                    if data:
                        log.write(data)
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()
                if sys.stdin in ready:
                    line = sys.stdin.readline()
                    if not line or line.rstrip("\r\n") == ":quit":
                        break
                    command = line.rstrip("\r\n").encode("utf-8")
                    os.write(fd, command + b"\r")
                    print(f"\nHOST_SENT {command.decode('utf-8', 'replace')}\n", flush=True)
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, previous)
        os.close(fd)


if __name__ == "__main__":
    main()
