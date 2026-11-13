#!/usr/bin/env python3
"""Receive one temporary root shell from the owner's Touch 10 direct link."""

import argparse
import os
import select
import socket
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-ip", default="10.77.10.1")
    parser.add_argument("--target-ip", default="10.77.10.10")
    parser.add_argument("--port", type=int, default=8876)
    parser.add_argument("--seconds", type=int, default=900)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error("--seconds must be 1..3600")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((args.host_ip, args.port))
        listener.listen(1)
        deadline = time.monotonic() + args.seconds
        print(f"root-shell listener ready at {args.host_ip}:{args.port}", flush=True)
        while time.monotonic() < deadline:
            listener.settimeout(min(5, deadline - time.monotonic()))
            try:
                client, peer = listener.accept()
            except TimeoutError:
                continue
            if peer[0] != args.target_ip:
                client.close()
                continue
            with client:
                print(f"connected from {peer[0]}; checking UID", flush=True)
                client.sendall(b"id\nprintf 'T10_SHELL_READY\\n'\n")
                client.setblocking(False)
                while True:
                    ready, _, _ = select.select([client, sys.stdin], [], [], 1)
                    if client in ready:
                        try:
                            data = client.recv(65536)
                        except BlockingIOError:
                            continue
                        if not data:
                            print("\nremote shell closed", flush=True)
                            return
                        os.write(sys.stdout.fileno(), data)
                    if sys.stdin in ready:
                        data = os.read(sys.stdin.fileno(), 4096)
                        if not data:
                            return
                        client.sendall(data)
    raise TimeoutError("Touch 10 root shell did not connect before the deadline")


if __name__ == "__main__":
    main()
