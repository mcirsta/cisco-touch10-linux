#!/usr/bin/env python3
"""Small shared artifact checks for the Perrier kernel workflow."""
import hashlib
from pathlib import Path
import stat
import struct

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'source'
WORK = HERE / 'work/linux-6.18.48'
IMAGE = ROOT / 'development/perrier-ramenv/display-dispc'
BASELINE = ROOT / 'development/perrier-ramenv/mainline-ram'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fdt_nodes(blob):
    header = struct.unpack_from('>10I', blob)
    assert header[0] == 0xd00dfeed and header[1] == len(blob)
    pos, strings = header[2], header[3]
    nodes, stack = {}, []
    while True:
        token = struct.unpack_from('>I', blob, pos)[0]
        pos += 4
        if token == 1:
            end = blob.index(0, pos)
            name = blob[pos:end].decode()
            pos = (end + 4) & ~3
            path = ('/' + '/'.join(stack[1:] + [name])).rstrip('/') or '/'
            stack.append(name)
            nodes[path] = {}
        elif token == 2:
            stack.pop()
        elif token == 3:
            length, nameoff = struct.unpack_from('>II', blob, pos)
            pos += 8
            end = blob.index(0, strings + nameoff)
            name = blob[strings + nameoff:end].decode()
            path = '/' + '/'.join(stack[1:]) if len(stack) > 1 else '/'
            nodes[path][name] = blob[pos:pos + length]
            pos = (pos + length + 3) & ~3
        elif token == 4:
            pass
        elif token == 9:
            return nodes
        else:
            raise ValueError('Bad FDT token ' + str(token))


def audit_board(reference, candidate):
    old, new = fdt_nodes(Path(reference).read_bytes()), fdt_nodes(Path(candidate).read_bytes())
    removed = {'/chosen/framebuffer@7ec78000'}
    assert set(old) - set(new) == removed and not set(new) - set(old)
    assert old[next(iter(removed))]['status'] == b'disabled\0'
    handles = {struct.unpack('>I', p['phandle'])[0]: struct.unpack('>I', new[n]['phandle'])[0]
               for n, p in old.items() if n in new and 'phandle' in p}
    renumbered = []
    for node, after in new.items():
        before = old[node]
        assert after.keys() == before.keys(), node
        for name, value in after.items():
            previous = before[name]
            if previous == value:
                continue
            assert len(previous) == len(value) and len(value) % 4 == 0, (node, name)
            a = struct.unpack('>' + 'I' * (len(value) // 4), previous)
            b = struct.unpack('>' + 'I' * (len(value) // 4), value)
            assert all(x == y or handles.get(x) == y for x, y in zip(a, b)), (node, name)
            renumbered.append([node, name])
    return {'active_hardware_properties_identical_to_ram64': True,
            'removed_disabled_nodes': sorted(removed), 'phandle_renumbering': renumbered}


def cpio_entry(name, mode, data=b'', major=0, minor=0):
    filename = name.encode() + b'\0'
    fields = [1, mode, 0, 0, 1, 0, len(data), 0, 0, major, minor, len(filename), 0]
    header = b'070701' + b''.join(f'{n:08x}'.encode() for n in fields) + filename
    return header + bytes((-len(header)) % 4) + data + bytes((-len(data)) % 4)


def audit_archive(path, entries):
    data = Path(path).read_bytes()
    pos, seen, packed = 0, set(), set()
    while True:
        assert data[pos:pos + 6] == b'070701'
        f = [int(data[pos + 6 + i * 8:pos + 14 + i * 8], 16) for i in range(13)]
        mode, size, namesize = f[1], f[6], f[11]
        name = data[pos + 110:pos + 110 + namesize - 1].decode()
        start = (pos + 110 + namesize + 3) & ~3
        payload = data[start:start + size]
        assert len(payload) == size
        pos = (start + size + 3) & ~3
        assert name not in seen, name
        seen.add(name)
        if name == 'TRAILER!!!':
            break
        if stat.S_ISREG(mode):
            assert hashlib.sha256(payload).hexdigest() == entries[name]['sha256'], name
            packed.add(name)
        elif stat.S_ISLNK(mode):
            assert payload.decode() == entries[name]['symlink'], name
            packed.add(name)
        elif stat.S_ISCHR(mode):
            assert (name, f[9], f[10]) in {('dev/console', 5, 1), ('dev/null', 1, 3)}
        else:
            assert stat.S_ISDIR(mode), name
    assert packed == set(entries) and pos == len(data)
