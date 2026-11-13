#!/usr/bin/env python3
"""Find evidence-backed old RWFS key candidates in saved backup/remnant files.

Never contacts the device. Inputs are opened rb/ACCESS_READ. Candidate values
are not printed or stored in reports; reports contain fingerprints and offsets.
Tests original raw keys, textual encodings, and legacy string termination.
"""
import argparse
import base64
import collections
import ctypes
import ctypes.util
import hashlib
import json
import mmap
from pathlib import Path
import re
import struct


class AESKEY(ctypes.Structure):
    _fields_ = [('rd_key', ctypes.c_uint32*60), ('rounds', ctypes.c_int)]


class Search:
    def __init__(self, out, original):
        self.out, self.original = out, original
        self.lib = ctypes.CDLL(ctypes.util.find_library('crypto'))
        for mode in ['encrypt','decrypt']:
            getattr(self.lib, 'AES_set_'+mode+'_key').argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(AESKEY)]
        self.lib.AES_cbc_encrypt.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(AESKEY), ctypes.c_void_p, ctypes.c_int]
        self.targets = {}
        for name, path in [('current-config', original/'backup-config.encrypted'), ('old-config', original.parent/'deleted-remnants-2026-11-08/recovered-image1/config.encrypted'), ('old-user', original.parent/'deleted-remnants-2026-11-08/recovered-image1/user.encrypted')]:
            self.targets[name] = dict(path=str(path), header=path.read_bytes()[1024:1536])
        self.candidates = {}
        self.cipher_keys = set()
        self.matches = []
        self.sources = []
        self.markers = []
        self.transforms = collections.Counter()
        self.outbuf = ctypes.create_string_buffer(512)

    def candidate(self, value, path, offset, reason):
        if not value or len(value)>128: return
        fp = hashlib.sha256(value).hexdigest()
        if fp in self.candidates:
            entry = self.candidates[fp]
            entry['occurrences'] += 1
            if len(entry['locations'])<3:
                entry['locations'].append(dict(source=str(path),offset=offset,reason=reason))
            return
        self.candidates[fp] = dict(length=len(value),occurrences=1,locations=[dict(source=str(path),offset=offset,reason=reason)])
        variants = {value}
        # A shell variable/readline helper may terminate a legacy binary key.
        variants.update([value.split(b'\0')[0], value.split(b'\n')[0], value.split(b'\0')[0].split(b'\n')[0]])
        for v in list(variants):
            if len(v)%4 == 0:
                variants.add(b''.join(v[i:i+4][::-1] for i in range(0,len(v),4)))
        for v in variants:
            modes = [('zero-pad-AES256', v[:32].ljust(32,b'\0')), ('zero-pad-AES128',v[:16].ljust(16,b'\0'))]
            # Covers historical passphrase conversion variants as well as raw loop keys.
            modes.extend([('SHA256-AES256',hashlib.sha256(v).digest()),('MD5-AES128',hashlib.md5(v).digest())])
            for mode,key in modes:
                if key in self.cipher_keys:continue
                self.cipher_keys.add(key);self.transforms[mode] += 1
                k=AESKEY();self.lib.AES_set_decrypt_key(key,len(key)*8,ctypes.byref(k))
                for name,target in self.targets.items():
                    iv=ctypes.create_string_buffer((2).to_bytes(8,'little')+bytes(8))
                    self.lib.AES_cbc_encrypt(target['header'],self.outbuf,512,ctypes.byref(k),iv,0)
                    b=self.outbuf.raw
                    if b[56:58] != b'\x53\xef': continue
                    # Magic alone has a 1/65536 false-positive rate. Require geometry,
                    # inode size, group sizes and standard superblock fields too.
                    inodes,blocks=struct.unpack_from('<II',b,0)
                    block_log=struct.unpack_from('<I',b,24)[0]
                    bpg,ipg=struct.unpack_from('<I',b,32)[0],struct.unpack_from('<I',b,40)[0]
                    inode_size=struct.unpack_from('<H',b,88)[0]
                    if block_log>6:continue
                    bs=1024<<block_log
                    if not (16<=inodes<=1000000 and 1024<=blocks<=10000000 and blocks*bs==4194304 and inode_size in (128,256) and 0<bpg<=bs*8 and 0<ipg<=bs*8):continue
                    match=dict(target=name,candidate_sha256=fp,derived_key_sha256=hashlib.sha256(key).hexdigest(),mode=mode,source=str(path),offset=offset,reason=reason,inodes=inodes,blocks=blocks,block_size=bs)
                    self.matches.append(match)
                    print('VALIDATED MATCH',name,'from',str(path),'offset',offset,'mode',mode,flush=True)
                    if name.startswith('old-'):
                        keypath=self.out/(name+'.aes-key')
                        keypath.write_bytes(key);keypath.chmod(0o600)
                        self.decrypt(target['path'],self.out/(name+'.ext4'),k)

    def decrypt(self,path,out,key):
        data=Path(path).read_bytes();result=bytearray()
        for sector in range(len(data)//512):
            iv=ctypes.create_string_buffer(sector.to_bytes(8,'little')+bytes(8))
            self.lib.AES_cbc_encrypt(data[sector*512:(sector+1)*512],self.outbuf,512,ctypes.byref(key),iv,0)
            result.extend(self.outbuf.raw)
        out.write_bytes(result);out.chmod(0o600)

    def scan(self,path):
        if path.stat().st_size==0:return
        before=len(self.candidates);counts=collections.Counter()
        # Long zero runs consume sparse regions quickly. Their boundaries can
        # expose the 16-byte raw key before the zeros in a 32-byte loop/AES key.
        pattern=re.compile(rb'(?P<hex>[0-9a-fA-F]{16,})|(?P<zero>\x00{16,})|(?P<marker>16KEY)|(?P<base64>[A-Za-z0-9+/]{22}==)')
        with path.open('rb') as f:
            with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
                for match in pattern.finditer(data):
                    kind=match.lastgroup;start=match.start();end=match.end();counts[kind]+=1
                    if kind=='hex':
                        val=match.group()
                        # Every 16-character window, not just aligned tokens.
                        for n in range(len(val)-15):
                            self.candidate(val[n:n+16],path,start+n,'hex-16-window')
                        # Binary keys may have been logged as hex dumps.
                        for n in range(max(0,len(val)-31)):
                            try:key=bytes.fromhex(val[n:n+32].decode())
                            except ValueError:continue
                            self.candidate(key,path,start+n,'hex-decoded-16-bytes')
                        if len(val)<=128:self.candidate(val,path,start,'whole-hex-token')
                    elif kind=='zero':
                        if start>=16:self.candidate(data[start-16:start],path,start-16,'16-bytes-before-zero-buffer')
                        # C-string terminators/padding can merge into this run.
                        for shift in range(1,16):
                            if start>=16-shift:self.candidate(data[start-16+shift:start]+bytes(shift),path,start-16+shift,'key-with-zero-suffix')
                    elif kind=='marker':
                        following=data[end:end+16]
                        self.markers.append(dict(source=str(path),offset=start,following_key_sha256=hashlib.sha256(following).hexdigest(),followed_by_code_quote=following[:1] in (b'"',b"'",b'\0')))
                        self.candidate(following,path,end,'EEPROM-16KEY-record')
                    elif kind=='base64':
                        try:key=base64.b64decode(match.group(),validate=True)
                        except ValueError:continue
                        self.candidate(key,path,start,'base64-16-bytes')
                # Common hexdump/xxd formatting of an EEPROM snapshot.
                for match in re.finditer(rb'(?:[0-9a-fA-F]{2}[ \t]){15}[0-9a-fA-F]{2}',data):
                    self.candidate(bytes.fromhex(match.group().decode()),path,match.start(),'spaced-hex-dump')
                current=Path('backups/touch10-2026-11-07/board-eeprom.bin').read_bytes()[101:117]
                current_offsets=[];at=0
                while True:
                    at=data.find(current,at)
                    if at<0:break
                    if len(current_offsets)<20:current_offsets.append(at)
                    at+=len(current)
        self.sources.append(dict(path=str(path),bytes=path.stat().st_size,patterns=dict(counts),new_unique_candidates=len(self.candidates)-before,current_saved_key_offsets=current_offsets))
        print('SCANNED',str(path),'new candidates',len(self.candidates)-before,'total',len(self.candidates),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    args.output.mkdir(parents=True,mode=0o700,exist_ok=False)
    original=Path('analysis/prior-use-2026-11-08')
    s=Search(args.output,original)
    eeprom=Path('backups/touch10-2026-11-07/board-eeprom.bin')
    raw=eeprom.read_bytes()
    s.candidate(raw[101:117],eeprom,101,'known-current-key-positive-control')
    if not any(m['target']=='current-config' for m in s.matches):raise RuntimeError('positive control failed')
    for i in range(len(raw)-15):s.candidate(raw[i:i+16],eeprom,i,'every-EEPROM-16-byte-window')
    s.candidate(bytes(16),eeprom,0,'erased-zero-key-check')
    s.candidate(bytes([255])*16,eeprom,0,'erased-FF-key-check')
    base=Path('backups/touch10-2026-11-07')
    sources=[base/'mmcblk0.img',base/'mmcblk0boot0.img',base/'mmcblk0boot1.img',eeprom,
             original/'backup-config.ext4',original/'backup-user.ext4']
    rem=Path('analysis/deleted-remnants-2026-11-08')
    sources.extend(sorted((rem/'carved').glob('*.gzip-output')))
    sources.extend(sorted(rem.glob('*/journal.bin')))
    for path in sources:s.scan(path)
    report=dict(method='Offline rb/ACCESS_READ scan; no device access. Candidates tested only against local filesystem headers; no candidate values disclosed in report.',sources=s.sources,candidate_count=len(s.candidates),derived_cipher_key_count=len(s.cipher_keys),transforms=dict(s.transforms),matches=s.matches,markers=s.markers,positive_control_passed=any(m['target']=='current-config' for m in s.matches),old_filesystem_key_found=any(m['target'].startswith('old-') for m in s.matches),limitations=['Old firmware uses arbitrary random 16-byte keys. Unmarked binary keys without recognizable buffering/encoding cannot be exhaustively identified in arbitrary backup bytes.','Only the current EEPROM snapshot is available; no historical EEPROM state is provided by the eMMC backup.','Absent encrypted historical data or overwritten headers can prevent candidate validation.'])
    (args.output/'search.json').write_text(json.dumps(report,indent=2)+'\n')
    (args.output/'candidate-fingerprints.json').write_text(json.dumps(s.candidates,indent=2)+'\n')
    print('FINISHED candidates',len(s.candidates),'cipher keys',len(s.cipher_keys),'old key found',report['old_filesystem_key_found'],flush=True)


if __name__=='__main__':main()
