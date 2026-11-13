#!/usr/bin/env python3
"""Try one bounded Ctrl-C interruption after observing a U-Boot banner.

No BREAK, newline, bootloader command, environment save or flash write is sent.
Input stops on a prompt, kernel handoff, or a short interruption timeout.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import select
import signal
import sys
import termios
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='/dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_D3081QEX-if00-port0')
    parser.add_argument('--seconds', type=float, default=600)
    parser.add_argument('--interrupt-seconds', type=float, default=5)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(130))
    fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    previous = termios.tcgetattr(fd)
    status = {'state': 'waiting_for_boot', 'ctrl_c_sent': 0, 'received_bytes': 0}
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        attrs = termios.tcgetattr(fd)
        attrs[0] = attrs[1] = attrs[3] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[4] = attrs[5] = termios.B115200
        attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        args.log.parent.mkdir(parents=True, exist_ok=True)
        args.result.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + args.seconds
        armed_at = None
        next_send = 0
        tail = bytearray()
        with args.log.open('ab') as log:
            print('Listening; Ctrl-C is armed only after a U-Boot banner.', flush=True)
            while time.monotonic() < deadline:
                if select.select([fd], [], [], 0.01)[0]:
                    data = os.read(fd, 65536)
                    if not data:
                        raise OSError('Serial device returned EOF')
                    log.write(data)
                    log.flush()
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
                    status['received_bytes'] += len(data)
                    tail.extend(data)
                    del tail[:-8192]
                    if armed_at is None and b'U-Boot 2013.' in tail:
                        armed_at = time.monotonic()
                        status['state'] = 'interrupting'
                    if armed_at is not None:
                        if b'Starting kernel' in tail:
                            status['state'] = 'kernel_started_no_prompt'
                            break
                        if re.search(rb'(?:^|[\r\n])(?:=>|[A-Za-z0-9_./()@ -]{1,64}[>#]) *$', tail):
                            status['state'] = 'possible_bootloader_prompt'
                            break
                now = time.monotonic()
                if armed_at is not None:
                    if now - armed_at > args.interrupt_seconds:
                        status['state'] = 'interrupt_window_ended_no_prompt'
                        break
                    if now >= next_send:
                        os.write(fd, b'\x03')
                        status['ctrl_c_sent'] += 1
                        next_send = now + 0.02
            else:
                status['state'] = 'no_boot_banner_before_timeout'
    except BaseException as exc:
        status['error'] = str(exc)
        raise
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, previous)
        os.close(fd)
        args.result.write_text(json.dumps(status, indent=2) + '\n')
        print('\nProbe result: ' + json.dumps(status), flush=True)


if __name__ == '__main__':
    main()
