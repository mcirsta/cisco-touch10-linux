#!/usr/bin/env python3
"""Capture a 115200 8N1 service console, optionally sending explicit commands.

Uses the Python standard library. Does not toggle DTR/RTS or send a break.
Commands are sent exactly as supplied, so review them before use.
"""
import argparse
import fcntl
import os
from pathlib import Path
import select
import re
import sys
import termios
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='/dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_D3081QEX-if00-port0')
    parser.add_argument('--seconds', type=float, default=4)
    parser.add_argument('--command', action='append', default=[])
    parser.add_argument('--line-ending', choices=['cr', 'lf', 'crlf'], default='cr')
    parser.add_argument('--interrupt', action='store_true', help='Send one Ctrl-C before commands')
    parser.add_argument('--support-commands', action='store_true',
                        help='Refresh and require a support prompt before every command')
    parser.add_argument('--log', required=True)
    args = parser.parse_args()
    fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    previous = termios.tcgetattr(fd)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        attrs = termios.tcgetattr(fd)
        attrs[0] = 0
        attrs[1] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[3] = 0
        attrs[4] = attrs[5] = termios.B115200
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        path = Path(args.log)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('ab') as log:
            def capture(seconds):
                received = bytearray()
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    ready, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
                    if ready:
                        data = os.read(fd, 65536)
                        if data:
                            received.extend(data)
                            log.write(data)
                            log.flush()
                            sys.stdout.buffer.write(data)
                            sys.stdout.buffer.flush()
                return bytes(received)
            capture(args.seconds)
            if args.interrupt:
                os.write(fd, b'\x03')
                capture(args.seconds)
            for command in args.command:
                if args.support_commands:
                    os.write(fd, b'\r')
                    prompt = capture(args.seconds)
                    if not re.search(rb'(?:^|[\r\n])\$ $', prompt):
                        raise RuntimeError('Support prompt missing; no further command sent')
                ending = {'cr': b'\r', 'lf': b'\n', 'crlf': b'\r\n'}[args.line_ending]
                os.write(fd, command.encode() + ending)
                capture(args.seconds)
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, previous)
        os.close(fd)


if __name__ == '__main__':
    main()
