#!/usr/bin/env python3
"""Keep only one device from a classic Linux usbmon pcap capture."""

import argparse
import struct
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--bus", type=int, required=True)
    parser.add_argument("--device", type=int, required=True)
    args = parser.parse_args()
    if args.source.resolve() == args.destination.resolve():
        parser.error("source and destination must differ")

    with args.source.open("rb") as source, args.destination.open("wb") as destination:
        header = source.read(24)
        if len(header) != 24 or header[:4] != b"\xd4\xc3\xb2\xa1" or struct.unpack_from("<I", header, 20)[0] != 220:
            raise ValueError("expected little-endian classic usbmon mmap pcap")
        destination.write(header)
        kept = 0
        total = 0
        while record := source.read(16):
            if len(record) != 16:
                raise ValueError("truncated pcap record header")
            captured_length = struct.unpack_from("<I", record, 8)[0]
            if captured_length > 16 * 1024 * 1024:
                raise ValueError("implausible pcap record length")
            packet = source.read(captured_length)
            if len(packet) != captured_length or len(packet) < 14:
                raise ValueError("truncated usbmon packet")
            total += 1
            if packet[11] == args.device and struct.unpack_from("<H", packet, 12)[0] == args.bus:
                destination.write(record)
                destination.write(packet)
                kept += 1
    if not kept:
        args.destination.unlink()
        raise ValueError("no packets matched target bus/device")
    print(f"kept {kept}/{total} packets for bus {args.bus} device {args.device}")


if __name__ == "__main__":
    main()
