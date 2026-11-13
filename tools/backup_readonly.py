#!/usr/bin/env python3
"""Read a Touch 10's eMMC and EEPROM over an already authorized root SSH login.

All remote commands are reads. Output is private and local. Requires a verified
SSH host key and working key/agent authentication; does not try passwords or
enable services. A live raw dump is not a certified offline filesystem snapshot.
"""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from datetime import datetime, timezone


class Reader:
    def __init__(self, host):
        self.prefix = ['ssh', '-T', '-o', 'BatchMode=yes', '-o',
                       'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
                       'root@' + str(ipaddress.ip_address(host))]

    def command(self, *args):
        return self.prefix + [shlex.join(args)]

    def text(self, *args):
        return subprocess.check_output(self.command(*args), text=True).strip()

    def digest(self, source):
        digest = self.text('sha256sum', source).split()[0]
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Invalid remote SHA-256 result')
        return digest


def copy_stream(reader, source, destination, expected_bytes, stderr_file):
    """Keep incomplete output on any failure; never silently accept truncation."""
    digest = hashlib.sha256()
    total = 0
    with destination.open('xb') as output, stderr_file.open('ab') as errors:
        proc = subprocess.Popen(reader.command('cat', source), stdout=subprocess.PIPE,
                                stderr=errors)
        try:
            while data := proc.stdout.read(1024 * 1024):
                output.write(data)
                digest.update(data)
                total += len(data)
                if total > expected_bytes:
                    raise ValueError(f'{source}: source larger than expected')
            if proc.wait() != 0:
                raise RuntimeError(f'{source}: SSH read failed; partial file retained')
            output.flush()
            os.fsync(output.fileno())
        finally:
            proc.stdout.close()
            if proc.poll() is None:
                proc.terminate()
                proc.wait()
    if total != expected_bytes:
        raise ValueError(f'{source}: expected {expected_bytes} bytes, received {total}')
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, help='Touch 10 IP address')
    parser.add_argument('--output', required=True, type=Path, help='New local directory')
    parser.add_argument('--expected-mac', default='24:16:9d:b6:77:bb')
    args = parser.parse_args()
    os.umask(0o077)
    reader = Reader(args.host)
    if reader.text('id', '-u') != '0':
        raise RuntimeError('An authorized root SSH session is required')
    if reader.text('cat', '/sys/class/net/eth0/address').lower() != args.expected_mac.lower():
        raise RuntimeError('MAC address mismatch: refusing to back up the wrong device')
    args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
    manifest = {'started_utc': datetime.now(timezone.utc).isoformat(),
                'host': args.host, 'mac': args.expected_mac, 'complete': False,
                'consistency': 'live reads; not an offline filesystem snapshot',
                'sources': []}
    manifest_path = args.output / 'manifest.json'

    def save_manifest():
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')

    save_manifest()
    try:
        metadata = {
            'uname.txt': ('uname', '-a'),
            'cmdline.txt': ('cat', '/proc/cmdline'),
            'partitions.txt': ('cat', '/proc/partitions'),
            'mounts.txt': ('cat', '/proc/mounts'),
            'cpuinfo.txt': ('cat', '/proc/cpuinfo'),
            'mmc-cid.txt': ('cat', '/sys/class/block/mmcblk0/device/cid'),
            'mmc-csd.txt': ('cat', '/sys/class/block/mmcblk0/device/csd'),
        }
        for name, command in metadata.items():
            (args.output / name).write_text(reader.text(*command) + '\n')
        sources = []
        # Preserve board identity/key and boot areas first, then the large user area.
        sources.append(('/sys/class/i2c-adapter/i2c-4/4-0054/eeprom', 'board-eeprom.bin', 256))
        for name in ['mmcblk0boot0', 'mmcblk0boot1', 'mmcblk0']:
            sectors = int(reader.text('cat', '/sys/class/block/' + name + '/size'))
            if sectors <= 0:
                raise ValueError('Invalid size for ' + name)
            sources.append(('/dev/' + name, name + '.img', sectors * 512))
        for source, name, size in sources:
            record = {'source': source, 'file': name, 'expected_bytes': size,
                      'verified': False}
            manifest['sources'].append(record)
            save_manifest()
            print(f'Reading {name}: {size:,} bytes', flush=True)
            record['sha256_before'] = reader.digest(source)
            temporary = args.output / (name + '.partial')
            record['sha256_received'] = copy_stream(
                reader, source, temporary, size, args.output / 'ssh-stderr.log')
            record['sha256_after'] = reader.digest(source)
            record['verified'] = len({record[k] for k in
                ['sha256_before', 'sha256_received', 'sha256_after']}) == 1
            if not record['verified']:
                raise RuntimeError(source + ': source changed or transfer mismatched; '
                                   'unverified partial file retained')
            temporary.rename(args.output / name)
            save_manifest()
        manifest['complete'] = True
    except BaseException as exc:
        manifest['error'] = str(exc)
        raise
    finally:
        manifest['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save_manifest()
    print('All four sources transferred and matched remote SHA-256 before and after.')
    print('Live filesystem consistency still requires separate assessment.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
