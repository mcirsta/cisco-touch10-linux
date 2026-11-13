#!/usr/bin/env python3
"""Offline, read-only ext filesystem and whole-image remnant inventory.

Uses only the Python standard library. Opens evidence with rb/ACCESS_READ;
all output goes under a new output directory. Does not mount or replay journals.
This is a bounded forensic inventory, not a general ext4 recovery implementation.
"""
import argparse
import collections
import hashlib
import json
import math
import mmap
from pathlib import Path
import re
import struct
import zlib


def u16(b, o): return struct.unpack_from('<H', b, o)[0]
def u32(b, o): return struct.unpack_from('<I', b, o)[0]


class Ext:
    def __init__(self, data, start, size, name, out):
        self.m, self.start, self.size, self.name, self.out = data, start, size, name, out
        s = self.read(1024, 1024)
        if s[56:58] != b'\x53\xef':
            raise ValueError('not ext')
        self.bs = 1024 << u32(s, 24)
        self.nblocks, self.ninodes = u32(s, 4), u32(s, 0)
        self.first, self.bpg, self.ipg = u32(s, 20), u32(s, 32), u32(s, 40)
        self.isize = u16(s, 88) or 128
        self.descsize = max(32, u16(s, 254)) if u32(s, 96) & 0x80 else 32
        if u32(s, 96) & (0x10 | 0x80 | 0x8000):
            raise ValueError('unsupported meta_bg/64bit/inline_data filesystem')
        self.groups = []
        base = (self.first + 1) * self.bs
        for g in range(math.ceil((self.nblocks - self.first) / self.bpg)):
            d = self.read(base + g * self.descsize, self.descsize)
            self.groups.append(dict(block_bitmap=u32(d, 0), inode_bitmap=u32(d, 4),
                                    inode_table=u32(d, 8), flags=u16(d, 18)))
        self.bb = [self.block(g['block_bitmap']) for g in self.groups]
        self.ib = [self.block(g['inode_bitmap']) for g in self.groups]
        self.inodes = {}
        for i in range(1, self.ninodes + 1):
            g, n = divmod(i - 1, self.ipg)
            b = self.read(self.groups[g]['inode_table'] * self.bs + n * self.isize, self.isize)
            if any(b):
                self.inodes[i] = b
        self.paths = {2: '/'}
        self.owners = {}
        self.slack = []
        self.dirents = []
        self.extent_errors = []

    def read(self, o, n):
        if o < 0 or o + n > self.size:
            raise ValueError('outside filesystem')
        return self.m[self.start + o:self.start + o + n]

    def block(self, n):
        if not 0 <= n < self.nblocks:
            raise ValueError('invalid block')
        return self.read(n * self.bs, self.bs)

    def allocated_inode(self, i):
        g, n = divmod(i - 1, self.ipg)
        return not (self.groups[g]['flags'] & 1) and bool(self.ib[g][n // 8] & (1 << (n % 8)))

    def allocated_block(self, i):
        if i < self.first: return True
        g, n = divmod(i - self.first, self.bpg)
        return not (self.groups[g]['flags'] & 2) and bool(self.bb[g][n // 8] & (1 << (n % 8)))

    def inode_info(self, i):
        b = self.inodes[i]
        return dict(inode=i, allocated=self.allocated_inode(i), mode=oct(u16(b, 0)),
                    type=hex(u16(b, 0) & 0xf000), size=u32(b, 4) + ((u32(b, 108) << 32) if u16(b, 0) & 0xf000 == 0x8000 else 0),
                    links=u16(b, 26), ctime=u32(b, 12), mtime=u32(b, 16),
                    dtime=u32(b, 20), flags=hex(u32(b, 32)))

    def mappings(self, i):
        b = self.inodes[i]
        if i == 7:
            return []  # resize inode uses reserved-GDT references, not ordinary file data
        if (u16(b, 0) & 0xf000) == 0xa000 and u32(b, 28) == 0:
            return []  # inline symlink, not block pointers
        result = []
        seen = set()
        def extent(node):
            if u16(node, 0) != 0xf30a: raise ValueError('bad extent magic')
            entries, maximum, depth = u16(node, 2), u16(node, 4), u16(node, 6)
            if entries > maximum or 12 + entries * 12 > len(node) or depth > 5:
                raise ValueError('bad extent header')
            for n in range(entries):
                o = 12 + 12 * n
                logical = u32(node, o)
                if depth:
                    p = u32(node, o + 4) + (u16(node, o + 8) << 32)
                    if p in seen: raise ValueError('extent cycle')
                    seen.add(p); extent(self.block(p))
                else:
                    length = u16(node, o + 4)
                    unwritten = length > 32768
                    if unwritten: length -= 32768
                    p = u32(node, o + 8) + (u16(node, o + 6) << 32)
                    if p + length > self.nblocks: raise ValueError('extent outside filesystem')
                    if not unwritten:
                        result.extend((logical + x, p + x) for x in range(length))
        def indirect(p, depth, logical):
            if not p: return
            if p in seen: raise ValueError('indirect cycle')
            seen.add(p)
            for n, child in enumerate(struct.unpack('<' + 'I' * (self.bs // 4), self.block(p))):
                l = logical + n * (self.bs // 4) ** (depth - 1)
                if child:
                    if depth == 1:
                        if child >= self.nblocks: raise ValueError('bad indirect block')
                        result.append((l, child))
                    else: indirect(child, depth - 1, l)
        try:
            if u32(b, 32) & 0x80000:
                extent(b[40:100])
            else:
                ptr = struct.unpack_from('<15I', b, 40)
                result.extend((l, p) for l, p in enumerate(ptr[:12]) if 0 < p < self.nblocks)
                logical = 12
                for depth, p in enumerate(ptr[12:], 1):
                    indirect(p, depth, logical); logical += (self.bs // 4) ** depth
        except (ValueError, struct.error) as e:
            self.extent_errors.append(dict(inode=i, error=str(e)))
        return sorted(result)

    def directory(self, i, mappings):
        for logical, p in mappings:
            b = self.block(p); pos = 0
            while pos + 8 <= len(b):
                ino, length, nl, ft = struct.unpack_from('<IHBB', b, pos)
                if length < 8 or length % 4 or pos + length > self.bs: break
                if nl <= length - 8 and ino <= self.ninodes:
                    name = b[pos + 8:pos + 8 + nl]
                    if ino and name and b'\0' not in name and b'/' not in name:
                        self.dirents.append(dict(parent=i, inode=ino, name=name.decode(errors='replace'), block=p, offset=pos))
                    ideal = (8 + nl + 3) & ~3
                    # Deleted directory entries can survive inside an expanded rec_len.
                    for at in range(pos + ideal, pos + length - 7, 4):
                        old, rec, n, typ = struct.unpack_from('<IHBB', b, at)
                        if not (0 < old <= self.ninodes and 0 < n <= 255 and typ <= 7 and rec >= 8 + n and rec % 4 == 0 and at + rec <= pos + length): continue
                        val = b[at + 8:at + 8 + n]
                        if any(c < 32 or c == 127 for c in val) or b'\0' in val or b'/' in val: continue
                        self.slack.append(dict(parent=i, inode=old, name=val.decode(errors='replace'), block=p,
                                               offset=at, inode_currently_allocated=self.allocated_inode(old)))
                pos += length

    def run(self):
        for i, b in self.inodes.items():
            if self.allocated_inode(i):
                maps = self.mappings(i)
                for _, p in maps: self.owners.setdefault(p, []).append(i)
                if (u16(b, 0) & 0xf000) == 0x4000: self.directory(i, maps)
        for _ in range(20):
            changed = False
            for d in self.dirents:
                if d['parent'] in self.paths and d['name'] not in ('.', '..') and d['inode'] not in self.paths:
                    self.paths[d['inode']] = self.paths[d['parent']].rstrip('/') + '/' + d['name']; changed = True
            if not changed: break
        for d in self.slack: d['parent_path'] = self.paths.get(d['parent'])
        free_inodes = [self.inode_info(i) for i in self.inodes if i > 10 and not self.allocated_inode(i)]
        nonzero = []; free = 0; allocated = 0
        for p in range(self.first, self.nblocks):
            if self.allocated_block(p): allocated += 1
            else:
                free += 1
                b = self.block(p)
                if b.count(0) != len(b): nonzero.append(p)
        dest = self.out / self.name; dest.mkdir()
        # Preserve contiguous free block runs separately with original offsets.
        runs = []
        for p in nonzero:
            if runs and p == runs[-1][1]: runs[-1][1] = p + 1
            else: runs.append([p, p + 1])
        free_manifest = []
        for a, b in runs:
            path = dest / f'free-{a}-{b}.bin'
            path.write_bytes(self.read(a * self.bs, (b - a) * self.bs))
            free_manifest.append(dict(start_block=a, end_block=b, offset_in_filesystem=a*self.bs, path=str(path), size=path.stat().st_size))
        journals = []
        if 8 in self.inodes:
            jpath = dest / 'journal.bin'
            jmaps = self.mappings(8)
            if jmaps:
                jdata = b''.join(self.block(p) for _, p in jmaps);jpath.write_bytes(jdata)
                # Inventory every descriptor, including stale transactions outside current journal start.
                for off in range(0, len(jdata), self.bs):
                    if jdata[off:off+8] != b'\xc0\x3b\x39\x98\x00\x00\x00\x01': continue
                    seq = struct.unpack_from('>I', jdata, off+8)[0]
                    at = off + 12; data_block = off // self.bs + 1
                    while at + 8 <= off + self.bs:
                        target, flags = struct.unpack_from('>II', jdata, at);at += 8
                        if not flags & 2: at += 16
                        if flags & ~15 or target >= self.nblocks: break
                        if not flags & 4:
                            data_off = (data_block % len(jmaps)) * self.bs
                            payload = jdata[data_off:data_off+self.bs]
                            journals.append(dict(sequence=seq, target_block=target, journal_data_block=data_block % len(jmaps),
                                                 payload_sha256=hashlib.sha256(payload).hexdigest()))
                            data_block += 1
                        if flags & 8: break
        info = dict(name=self.name, source_offset=self.start, block_size=self.bs, blocks=self.nblocks,
                    inode_count=self.ninodes, inode_size=self.isize, allocated_blocks=allocated,
                    free_blocks=free, nonzero_free_blocks=len(nonzero), free_runs=free_manifest,
                    allocated_paths={str(i):p for i,p in self.paths.items()},
                    allocated_inodes=[dict(self.inode_info(i), path=self.paths.get(i)) for i in self.inodes if self.allocated_inode(i)],
                    nonzero_unallocated_inodes=free_inodes, directory_slack_entries=self.slack,
                    journal_descriptors=journals, extent_errors=self.extent_errors,
                    bitmap_free_blocks=sum(1 for p in range(self.first, self.nblocks) if not self.allocated_block(p)))
        (dest/'filesystem.json').write_text(json.dumps(info,indent=2)+'\n')
        print(self.name, 'free blocks',free,'nonzero free',len(nonzero),'stale inodes',len(free_inodes),'directory slack',len(self.slack),'journal tags',len(journals),flush=True)
        return info


SIGNATURES = {
    'gzip': b'\x1f\x8b\x08', 'sqlite': b'SQLite format 3\x00',
    'png': b'\x89PNG\r\n\x1a\n', 'zip': b'PK\x03\x04',
    'jpeg': b'\xff\xd8\xff', 'pdf': b'%PDF-',
    'squashfs': b'hsqs', 'cpio': b'070701', 'tar': b'ustar',
}
PATTERN = re.compile(b'|'.join(re.escape(x) for x in SIGNATURES.values()))
NAMES = {v:k for k,v in SIGNATURES.items()}


def scan_signatures(data, start, end, label, out, filesystems=()):
    hits = []; counts = collections.Counter(); carved = out/'carved';carved.mkdir(exist_ok=True)
    for match in PATTERN.finditer(data, start, end):
        off = match.start();kind = NAMES[match.group()];counts[kind] += 1
        hit = dict(kind=kind, offset=off, source=label)
        for fs in filesystems:
            if fs.start <= off < fs.start + fs.nblocks * fs.bs:
                p = (off-fs.start)//fs.bs
                owners = fs.owners.get(p, [])
                hit.update(filesystem=fs.name, block=p, allocated=fs.allocated_block(p), owners=owners,
                           owner_paths=[fs.paths.get(i, '<metadata or unnamed>') for i in owners])
                break
        if kind == 'gzip':
            # Require a complete stream with a valid gzip CRC/length; output is bounded.
            z = zlib.decompressobj(31); pos = off; parts=[];total=0
            try:
                while pos < end and pos-off < 128*1024*1024 and total <= 256*1024*1024:
                    chunk = data[pos:min(pos+1024*1024,end)]
                    value = z.decompress(chunk, 256*1024*1024-total+1)
                    parts.append(value);total += len(value);pos += len(chunk)
                    if z.eof: break
                    if z.unconsumed_tail: break
                hit.update(valid_gzip=z.eof, output_bytes=total)
                if z.eof:
                    payload=b''.join(parts);consumed=pos-off-len(z.unused_data)
                    hit.update(compressed_bytes=consumed, sha256=hashlib.sha256(payload).hexdigest())
                    if len(payload) >= 512:
                        path=carved/f'{label}-{off:010x}.gzip-output';path.write_bytes(payload);hit['output_path']=str(path)
            except zlib.error as e: hit['error']=str(e)
        elif kind == 'sqlite' and off + 100 <= end:
            page=struct.unpack_from('>H',data,off+16)[0];page=65536 if page==1 else page
            pages=struct.unpack_from('>I',data,off+28)[0]
            hit.update(page_size=page,page_count=pages)
            if page>=512 and page<=65536 and page&(page-1)==0 and 0<pages and pages*page<=128*1024*1024 and off+pages*page<=end:
                path=carved/f'{label}-{off:010x}.sqlite';path.write_bytes(data[off:off+pages*page]);hit['output_path']=str(path)
        hits.append(hit)
    print(label,'signature counts',dict(counts),flush=True)
    return hits


def main():
    a=argparse.ArgumentParser();a.add_argument('--image',type=Path,required=True);a.add_argument('--output',type=Path,required=True)
    a.add_argument('--decoded-config',type=Path,required=True);a.add_argument('--decoded-user',type=Path,required=True);args=a.parse_args()
    args.output.mkdir(mode=0o700,parents=True,exist_ok=False)
    report=dict(source=str(args.image.resolve()),source_size=args.image.stat().st_size,method='Read-only mmap; no mounting, journal replay or device access.',partitions=[],filesystems=[],signature_hits=[])
    handles=[]
    with args.image.open('rb') as f:
        report['source_sha256']=hashlib.file_digest(f,'sha256').hexdigest()
        with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
            h=data[512:1024];lba,count,size=struct.unpack_from('<QII',h,72)
            fslist=[]
            for i in range(count):
                e=data[lba*512+i*size:lba*512+(i+1)*size]
                if e[:16]==bytes(16):continue
                first,last=struct.unpack_from('<QQ',e,32);start=first*512;length=(last-first+1)*512
                name=e[56:128].decode('utf-16-le').strip('\0')
                report['partitions'].append(dict(number=i+1,name=name,start=start,size=length))
                if data[start+1080:start+1082]==b'\x53\xef':
                    fs=Ext(data,start,length,f'p{i+1}-{name}',args.output);fslist.append(fs);report['filesystems'].append(fs.run())
            report['signature_hits'].extend(scan_signatures(data,0,len(data),'raw-emmc',args.output,fslist))
    for name,path in [('decoded-config',args.decoded_config),('decoded-user',args.decoded_user)]:
        with path.open('rb') as f:
            with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
                fs=Ext(data,0,len(data),name,args.output);report['filesystems'].append(fs.run())
                report['signature_hits'].extend(scan_signatures(data,0,len(data),name,args.output,[fs]))
    (args.output/'scan.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Report:',args.output/'scan.json',flush=True)


if __name__=='__main__':main()
