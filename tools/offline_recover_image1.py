#!/usr/bin/env python3
"""Recover the deleted image1 config/user files using saved journal extents.

Only reads the existing raw backup and EEPROM backup. Tests the saved current
key against a filesystem header; does not claim to recover erased former keys.
"""
import ctypes
import ctypes.util
import hashlib
import json
import mmap
from pathlib import Path
import sys
from offline_deleted_scan import Ext


def main():
    out = Path(sys.argv[1])
    scan = json.loads((out/'scan.json').read_text())
    detail = json.loads((out/'journal-and-directories.json').read_text())
    fi = next(f for f in scan['filesystems'] if f['name']=='p14-system-b')
    dest = out/'recovered-image1'
    dest.mkdir(mode=0o700, exist_ok=True)
    lib = ctypes.CDLL(ctypes.util.find_library('crypto'))
    class AESKEY(ctypes.Structure):
        _fields_ = [('rd_key', ctypes.c_uint32*60), ('rounds', ctypes.c_int)]
    lib.AES_set_decrypt_key.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(AESKEY)]
    lib.AES_cbc_encrypt.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(AESKEY), ctypes.c_void_p, ctypes.c_int]
    saved_key = Path('backups/touch10-2026-11-07/board-eeprom.bin').read_bytes()[101:117].ljust(32, b'\0')
    key = AESKEY()
    lib.AES_set_decrypt_key(saved_key, 256, ctypes.byref(key))
    results = []
    with open(scan['source'], 'rb') as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as raw:
            fs = Ext(raw, fi['source_offset'], fi['blocks']*fi['block_size'], fi['name'], out)
            for ino, name in [(37,'user'), (38,'config')]:
                versions = [v for v in detail['journal_inode_versions'] if v['filesystem']==fi['name'] and v['inode']==ino and v['size']==4194304 and v.get('extents')]
                v = max(versions, key=lambda x:x['sequence'])
                data = bytearray(v['size'])
                reused = []
                for run in v['extents']:
                    for n in range(run['blocks']):
                        logical, physical = run['logical']+n, run['physical']+n
                        data[logical*fs.bs:(logical+1)*fs.bs] = fs.block(physical)
                        if fs.allocated_block(physical): reused.append(physical)
                p = dest/f'{name}.encrypted'
                p.write_bytes(data)
                result = dict(name=name, original_inode=ino, journal_sequence=v['sequence'], size=len(data), sha256=hashlib.sha256(data).hexdigest(), encrypted_file=str(p), currently_reallocated_blocks=reused, extents=v['extents'])
                # Header starts in sector 2. IV does not affect the magic at byte 56.
                header = ctypes.create_string_buffer(512)
                iv = ctypes.create_string_buffer((2).to_bytes(8,'little')+bytes(8))
                lib.AES_cbc_encrypt(bytes(data[1024:1536]),header,512,ctypes.byref(key),iv,0)
                valid = header.raw[56:58]==b'\x53\xef'
                result['current_saved_key_decodes_ext_header'] = valid
                if valid:
                    decoded = bytearray()
                    for sector in range(len(data)//512):
                        value = ctypes.create_string_buffer(512)
                        iv = ctypes.create_string_buffer(sector.to_bytes(8,'little')+bytes(8))
                        lib.AES_cbc_encrypt(bytes(data[sector*512:(sector+1)*512]),value,512,ctypes.byref(key),iv,0)
                        decoded.extend(value.raw)
                    p = dest/f'{name}.ext4'
                    p.write_bytes(decoded)
                    result['decoded_file'] = str(p)
                results.append(result)
                print(name, 'reallocated blocks:',len(reused),'current key decodes header:',valid)
    (out/'image1-config-recovery.json').write_text(json.dumps(results,indent=2)+'\n')


if __name__=='__main__':main()
