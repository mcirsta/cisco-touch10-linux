#!/usr/bin/env python3
"""Resolve DT bus addresses and phandles for the Perrier layout migration."""
from pathlib import Path
import struct

from common import fdt_nodes


def cells(value):
    assert len(value) % 4 == 0
    return list(struct.unpack('>' + 'I' * (len(value) // 4), value))


def parent(path):
    return path.rsplit('/', 1)[0] or '/'


def strings(value):
    return value.rstrip(b'\0').decode().split('\0')


class Tree:
    def __init__(self, filename):
        self.nodes = fdt_nodes(Path(filename).read_bytes())
        self.handles = {cells(p['phandle'])[0]: n for n, p in self.nodes.items()
                        if 'phandle' in p}
        self.symbols = {n: v.rstrip(b'\0').decode()
                        for n, v in self.nodes.get('/__symbols__', {}).items()}

    def count(self, path, name, default):
        value = self.nodes[path].get(name)
        return cells(value)[0] if value is not None else default

    def available(self, path):
        while True:
            if self.nodes[path].get('status', b'okay\0') not in (b'okay\0', b'ok\0'):
                return False
            if path == '/':
                return True
            path = parent(path)

    def translate(self, bus, address, length):
        while bus != '/':
            props = self.nodes[bus]
            if 'ranges' not in props:
                raise ValueError('No MMIO translation at ' + bus)
            data = cells(props['ranges'])
            upper = parent(bus)
            ac = self.count(bus, '#address-cells', 2)
            pac = self.count(upper, '#address-cells', 2)
            sc = self.count(bus, '#size-cells', 1)
            assert ac == pac == sc == 1, (bus, ac, pac, sc)
            if data:
                # Match the starting address, as of_translate_address() does.
                match = [(a, b) for a, b, size in zip(data[::3], data[1::3], data[2::3])
                         if a <= address < a + size]
                if len(match) != 1:
                    raise ValueError(f'No unique range for {bus}: {address:#x}+{length:#x}')
                a, b = match[0]
                address = address - a + b
            bus = upper
        return address

    def resources(self, path):
        props, bus = self.nodes[path], parent(path)
        if 'reg' not in props:
            return []
        ac = self.count(bus, '#address-cells', 2)
        sc = self.count(bus, '#size-cells', 1)
        if ac != 1 or sc != 1:
            return []
        data = cells(props['reg'])
        assert len(data) % 2 == 0, path
        return [(self.translate(bus, a, size), size) for a, size in zip(data[::2], data[1::2])]

    def refs(self, data, cell_property=None, remap=None):
        values, out = cells(data), []
        remap = remap or {}
        while values:
            node = self.handles[values.pop(0)]
            count = self.count(node, cell_property, 0) if cell_property else 0
            assert len(values) >= count
            out.append((remap.get(node, node), tuple(values[:count])))
            del values[:count]
        return out
