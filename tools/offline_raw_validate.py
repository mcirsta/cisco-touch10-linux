#!/usr/bin/env python3
"""Validate image signatures, ext superblocks, zeroed ranges and text leads."""
import collections
import hashlib
import json
import mmap
from pathlib import Path
import re
import struct
import sys
import zlib


def main():
    out = Path(sys.argv[1])
    r = json.loads((out/'scan.json').read_text())
    result = dict(regions=[], ext_superblocks=[], validated_images=[], plaintext_leads={})
    with open(r['source'], 'rb') as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
            # Account for all bytes, including the large trailing unpartitioned region.
            regions=[];end=0
            for p in r['partitions']:
                if p['start'] > end: regions.append((end,p['start'],'gap'))
                regions.append((p['start'],p['start']+p['size'],f'p{p["number"]}-{p["name"]}'));end=p['start']+p['size']
            if end<len(m):regions.append((end,len(m),'trailing-gap'))
            for a,b,name in regions:
                nonzero=0;first=None;last=None
                for pos in range(a,b,1024*1024):
                    chunk=m[pos:min(pos+1024*1024,b)]
                    nz=len(chunk)-chunk.count(0);nonzero+=nz
                    if nz:
                        if first is None:first=pos+len(chunk)-len(chunk.lstrip(b'\0'))
                        last=pos+len(chunk.rstrip(b'\0'))-1
                result['regions'].append(dict(name=name,start=a,size=b-a,nonzero_bytes=nonzero,first_nonzero=first,last_nonzero=last))
            # Search all raw bytes for plausible primary or backup superblocks.
            at=0
            while True:
                magic=m.find(b'\x53\xef',at)
                if magic<0:break
                at=magic+2;s=magic-56
                if s<0 or s+1024>len(m):continue
                h=m[s:s+1024]
                ni,nb=struct.unpack_from('<II',h,0);lb=struct.unpack_from('<I',h,24)[0]
                if lb>6 or not(16<=ni<=100000000 and 1024<=nb<=100000000):continue
                bs=1024<<lb;isize=struct.unpack_from('<H',h,88)[0]
                bpg,ipg=struct.unpack_from('<I',h,32)[0],struct.unpack_from('<I',h,40)[0]
                if isize not in (128,256,512) or bpg==0 or bpg>bs*8 or ipg==0 or ipg>bs*8 or h[72:76]!=b'\x00\x00\x00\x00':continue
                result['ext_superblocks'].append(dict(offset=s,blocks=nb,inodes=ni,block_size=bs,inode_size=isize,block_group=struct.unpack_from('<H',h,90)[0],last_mounted=h[136:200].split(b'\0')[0].decode(errors='replace')))
            for hit in r['signature_hits']:
                kind=hit['kind'];start=hit['offset'];pos=start;dimensions=None
                if kind=='png':
                    pos+=8
                    try:
                        while pos+12<=len(m) and pos-start<64*1024*1024:
                            n=struct.unpack_from('>I',m,pos)[0];tag=m[pos+4:pos+8]
                            if n>64*1024*1024 or pos+n+12>len(m):raise ValueError()
                            content=m[pos+8:pos+8+n]
                            if zlib.crc32(tag+content)!=struct.unpack_from('>I',m,pos+8+n)[0]:raise ValueError()
                            if tag==b'IHDR':dimensions=list(struct.unpack_from('>II',content))
                            pos+=12+n
                            if tag==b'IEND':break
                        else:continue
                    except (ValueError,struct.error):continue
                elif kind=='jpeg':
                    pos+=2;complete=False
                    try:
                        while pos<len(m) and pos-start<64*1024*1024:
                            if m[pos]!=255:raise ValueError()
                            while m[pos]==255:pos+=1
                            marker=m[pos];pos+=1
                            if marker==217:complete=True;break
                            if marker in (0,216) or 208<=marker<=215:raise ValueError()
                            n=struct.unpack_from('>H',m,pos)[0]
                            if n<2 or pos+n>len(m):raise ValueError()
                            if marker in (192,193,194,195,197,198,199,201,202,203,205,206,207):
                                height,width=struct.unpack_from('>HH',m,pos+3);dimensions=[width,height]
                            pos+=n
                            if marker==218:
                                while True:
                                    pos=m.find(b'\xff',pos)
                                    if pos<0:raise ValueError()
                                    nextbyte=m[pos+1]
                                    if nextbyte==0 or 208<=nextbyte<=215:pos+=2
                                    else:break
                        if not complete or dimensions is None:continue
                    except (ValueError,IndexError,struct.error):continue
                else:continue
                data=m[start:pos];path=out/'carved'/f'raw-emmc-{start:010x}.{kind}'
                path.write_bytes(data)
                result['validated_images'].append(dict(hit,path=str(path),dimensions=dimensions,size=len(data),sha256=hashlib.sha256(data).hexdigest()))
    # Targeted plaintext leads from free runs and saved journals. Binary hits are leads, not attribution.
    patterns={
        'email':re.compile(rb'[A-Za-z0-9._%+-]{1,80}@[A-Za-z0-9.-]{1,100}\.[A-Za-z]{2,12}'),
        'ipv4':re.compile(rb'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])'),
        'timestamped_log':re.compile(rb'(?:19|20)\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^\x00\n]{0,150}'),
        'pairing_value':re.compile(rb'PAIRING_SERVER=[ -~]{0,120}'),
        'hostname_value':re.compile(rb'HOSTNAME=[ -~]{0,120}'),
        'private_key_header':re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')}
    for fi in r['filesystems']:
        files=[Path(x['path']) for x in fi['free_runs']]
        jp=out/fi['name']/'journal.bin'
        if jp.exists():files.append(jp)
        summary={}
        for kind,pat in patterns.items():
            found=collections.defaultdict(list)
            for path in files:
                b=path.read_bytes()
                for match in pat.finditer(b):
                    s=match.group().decode(errors='replace')
                    if kind=='ipv4' and any(int(x)>255 for x in s.split('.')):continue
                    if len(found[s])<3:found[s].append(dict(file=str(path),offset=match.start()))
            summary[kind]=dict(found)
        result['plaintext_leads'][fi['name']]=summary
    (out/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Ext superblocks:',len(result['ext_superblocks']),'validated PNG/JPEG:',len(result['validated_images']))
    for region in result['regions']:
        print(region['name'],'size',region['size'],'nonzero bytes',region['nonzero_bytes'])
    for fs,lead in result['plaintext_leads'].items():
        print(fs,{kind:list(found)[:12] for kind,found in lead.items()})


if __name__=='__main__':main()
