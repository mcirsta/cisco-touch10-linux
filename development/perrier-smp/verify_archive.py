#!/usr/bin/env python3
"""Verify cpio and embedded bytes through a Perrier zImage, offline."""
import argparse
import json
from pathlib import Path
import zlib

RAM = Path(__file__).resolve().parents[1] / 'perrier-ramenv'

def verify_cpio(data):
    offset = count = 0
    while offset < len(data):
        assert offset % 4 == 0
        assert data[offset:offset + 6] == b'070701', offset
        fields = [int(data[offset + 6 + i * 8:offset + 14 + i * 8], 16)
                  for i in range(13)]
        size, name_size = fields[6], fields[11]
        name_start = offset + 110
        name_end = name_start + name_size
        assert 0 < name_size <= 4096 and data[name_end - 1] == 0
        name = data[name_start:name_end - 1]
        body = (name_end + 3) & ~3
        assert not any(data[name_end:body]), (name, 'name padding')
        end = body + size
        next_offset = (end + 3) & ~3
        assert next_offset <= len(data) and not any(data[end:next_offset]), (name, 'data padding')
        offset = next_offset
        count += 1
        if name == b'TRAILER!!!':
            assert offset == len(data)
            return count
    raise AssertionError('missing cpio trailer')

def verify(profile):
    root = RAM / profile
    cpio = (root / 'initramfs.cpio').read_bytes()
    entries = verify_cpio(cpio)
    build = root / 'kernel-build'
    packed = (build / 'usr/initramfs_inc_data').read_bytes()
    assert zlib.decompress(packed, 16 + zlib.MAX_WBITS) == cpio
    image = (build / 'arch/arm/boot/Image').read_bytes()
    archive_offset = image.find(packed[:64])
    assert archive_offset >= 0 and image[archive_offset:archive_offset + len(packed)] == packed
    zimage = (build / 'arch/arm/boot/zImage').read_bytes()
    start = 0
    while True:
        start = zimage.find(b'\x1f\x8b\x08', start)
        assert start >= 0, 'no zImage gzip member reproduces Image'
        try:
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
            output = decompressor.decompress(zimage[start:]) + decompressor.flush()
            if decompressor.eof and output == image:
                return {'profile': profile, 'cpio_entries': entries,
                        'cpio_bytes': len(cpio), 'compressed_bytes': len(packed),
                        'archive_offset_in_Image': archive_offset,
                        'zImage_member_offset': start, 'passed': True}
        except zlib.error:
            pass
        start += 1

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profiles', nargs='*', default=['native-keypad',
                        'native-smp-onecpu', 'native-smp-sync',
                        'native-smp-nosmp', 'native-keypad-newqt'])
    args = parser.parse_args()
    print(json.dumps([verify(name) for name in args.profiles], indent=2))

if __name__ == '__main__':
    main()
