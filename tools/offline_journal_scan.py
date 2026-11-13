#!/usr/bin/env python3
"""Inspect the journal copies and free blocks produced by offline_deleted_scan.py."""
import argparse
import json
import mmap
from pathlib import Path
import struct
from offline_deleted_scan import Ext, u16


def directory(b, bs, ni):
    if len(b) != bs or b[8:9] != b'.' or b[20:22] != b'..':
        return None
    pos = 0
    entries = []
    while pos + 8 <= bs:
        ino, length, n, typ = struct.unpack_from('<IHBB', b, pos)
        if not (length >= 8 and length % 4 == 0 and pos + length <= bs and n <= length - 8 and ino <= ni and typ <= 7):
            return None
        name = b[pos+8:pos+8+n]
        if ino and (not n or b'\0' in name or b'/' in name):
            return None
        if ino:
            entries.append(dict(inode=ino, name=name.decode(errors='replace')))
        pos += length
    return entries if pos == bs and len(entries) >= 2 else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('scan_directory', type=Path)
    args = p.parse_args()
    out = args.scan_directory
    report = json.loads((out/'scan.json').read_text())
    details = dict(freed_directories=[], journal_inode_versions=[], journal_directory_versions=[])
    for fi in report['filesystems']:
        decoded = fi['name'].startswith('decoded')
        source = Path('analysis/prior-use-2026-11-08/backup-'+fi['name'].removeprefix('decoded-')+'.ext4') if decoded else Path(report['source'])
        with source.open('rb') as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as raw:
                fs = Ext(raw, 0 if decoded else fi['source_offset'], fi['blocks']*fi['block_size'], fi['name'], out)
                for run in fi['free_runs']:
                    b = Path(run['path']).read_bytes()
                    for off in range(0, len(b), fs.bs):
                        entries = directory(b[off:off+fs.bs], fs.bs, fs.ninodes)
                        if entries:
                            details['freed_directories'].append(dict(filesystem=fi['name'], block=run['start_block']+off//fs.bs, entries=entries))
                jp = out/fi['name']/'journal.bin'
                if not jp.exists(): continue
                j = jp.read_bytes()
                seen = set()
                for tag in fi['journal_descriptors']:
                    payload = j[tag['journal_data_block']*fs.bs:(tag['journal_data_block']+1)*fs.bs]
                    entries = directory(payload, fs.bs, fs.ninodes)
                    if entries:
                        details['journal_directory_versions'].append(dict(filesystem=fi['name'], sequence=tag['sequence'], target_block=tag['target_block'], entries=entries))
                    for g, desc in enumerate(fs.groups):
                        at = (tag['target_block']-desc['inode_table'])*fs.bs
                        if not 0 <= at < fs.ipg*fs.isize: continue
                        for n in range(fs.bs//fs.isize):
                            i = g*fs.ipg+at//fs.isize+n+1
                            b = payload[n*fs.isize:(n+1)*fs.isize]
                            if i <= 10 or i > fs.ninodes or not any(b) or (u16(b, 0)&0xf000) not in (0x4000, 0x8000, 0xa000): continue
                            fingerprint = (i, bytes(b))
                            if fingerprint in seen: continue
                            seen.add(fingerprint)
                            old = fs.inodes.get(i)
                            fs.inodes[i] = b
                            info = fs.inode_info(i)
                            info.update(filesystem=fi['name'], sequence=tag['sequence'], target_block=tag['target_block'])
                            if info['size']:
                                runs = []
                                for logical, physical in fs.mappings(i):
                                    if runs and logical == runs[-1]['logical']+runs[-1]['blocks'] and physical == runs[-1]['physical']+runs[-1]['blocks']:
                                        runs[-1]['blocks'] += 1
                                    else:
                                        runs.append(dict(logical=logical, physical=physical, blocks=1))
                                info['extents'] = runs
                            details['journal_inode_versions'].append(info)
                            if old is None: del fs.inodes[i]
                            else: fs.inodes[i] = old
    (out/'journal-and-directories.json').write_text(json.dumps(details, indent=2)+'\n')
    print('Freed directories:', len(details['freed_directories']), 'journal inode versions:', len(details['journal_inode_versions']), 'journal directory versions:', len(details['journal_directory_versions']))
    for d in details['freed_directories']:
        print(d)
    for d in details['journal_directory_versions']:
        if any(e['name'] in ['image1', 'config.img', 'user.img'] for e in d['entries']):
            print(d)


if __name__ == '__main__':
    main()
