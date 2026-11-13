#!/usr/bin/env python3
"""Replay real touch captures through functions extracted from the ported core."""
from pathlib import Path
import os
import re
import subprocess

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'perrier-touch'
core = (HERE / 'cyttsp4_core.c').read_text()
header = (HERE / 'cyttsp4_core.h').read_text()


def function(name):
    return re.search(r'(?m)^static (?:inline )?(?:void|int|size_t) ' + name +
                     r'\([\s\S]*?^}\n', core)[0]


def declaration(kind, name):
    return re.search(r'(?m)^' + kind + ' ' + name + r' \{[\s\S]*?^}[^;]*;', header)[0]


prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint16_t u16;
#include "../perrier-touch/cyttsp4_protocol.h"
#define CY_NUM_TCH_FIELDS 7
#define CY_NUM_EXT_TCH_FIELDS 3
#define CY_BYTE_OFS_MASK 0x1f
#define CY_BOFS_SHIFT 5
#define GET_NUM_TOUCHES(x) ((x) & 0x1f)
#define IS_BAD_PKT(x) ((x) & 0x20)
#define IS_LARGE_AREA(x) ((x) & 0x20)
#define GFP_KERNEL 0
#define __packed __attribute__((packed))
#define kzalloc(n, f) calloc(1, n)
#define kfree(p) free(p)
#define dev_vdbg(...) ((void)0)
#define dev_dbg(...) ((void)0)
#define dev_err(...) ((void)0)
#define cyttsp4_pr_buf(...) ((void)0)
#define CY_REG_BASE 0
'''
types = '\n'.join(declaration('struct', n) for n in (
    'cyttsp4_tch_rec_params', 'cyttsp4_opcfg', 'cyttsp4_touch',
    'cyttsp4_tch_abs_params', 'cyttsp4_sysinfo_ofs'))
enum = declaration('enum', 'cyttsp4_tch_abs')
stubs = r'''
struct device { int unused; };
struct input_dev { struct device dev; };
struct cyttsp4_sysinfo {
    struct cyttsp4_sysinfo_ofs si_ofs;
    struct { struct cyttsp4_opcfg *opcfg; } si_ptrs;
    u8 *xy_mode, *xy_data;
};
struct cyttsp4_mt_data { struct cyttsp4_sysinfo *si; struct input_dev *input; };
struct cyttsp4 { struct cyttsp4_sysinfo sysinfo; struct cyttsp4_mt_data md; struct device *dev; };
static u8 wire[256];
static size_t wire_length = 256;
static unsigned int reads, releases, active;
static struct cyttsp4_touch decoded[10];
static int cyttsp4_adap_read(struct cyttsp4 *cd, int addr, int len, void *data)
{
    assert(addr >= 0 && len > 0 && (size_t)(addr + len) <= wire_length);
    reads++;
    memcpy(data, wire + addr, len);
    return 0;
}
static void cyttsp4_lift_all(struct cyttsp4_mt_data *md) { releases++; active = 0; }
'''
helpers = '\n'.join(function(n) for n in ('merge_bytes', 'cyttsp4_bits_2_bytes',
    'cyttsp4_si_get_opcfg_data', 'cyttsp4_get_touch_axis', 'cyttsp4_get_touch'))
capture = r'''
static void cyttsp4_get_mt_touches(struct cyttsp4_mt_data *md, int count)
{
    assert(count >= 0 && count <= 10);
    active = 0;
    for (int i = 0; i < count; i++) {
        struct cyttsp4_touch t;
        cyttsp4_get_touch(md, &t, md->si->xy_data + i * md->si->si_ofs.tch_rec_size);
        if (t.abs[CY_TCH_E] != 3) decoded[active++] = t;
    }
}
'''
main = r'''
int main(int argc, char **argv)
{
    assert(argc == 3);
    FILE *f = fopen(argv[1], "rb");
    assert(f && fread(wire, 1, 256, f) == 256);
    fclose(f);
    u8 original[256]; memcpy(original, wire, 256);
    struct cy4_layout reference;
    assert(!cy4_parse_sysinfo(wire, 256, &reference));
    struct input_dev input = {0};
    struct cyttsp4 cd = {0};
    cd.sysinfo.si_ofs.opcfg_ofs = cy4_be16(wire + 10);
    cd.sysinfo.si_ofs.ddata_ofs = cy4_be16(wire + 12);
    cd.sysinfo.si_ofs.max_x = reference.max_x;
    cd.sysinfo.si_ofs.max_y = reference.max_y;
    assert(!cyttsp4_si_get_opcfg_data(&cd));
    assert(cd.sysinfo.si_ofs.max_tchs == 10 && cd.sysinfo.si_ofs.tch_rec_size == 7);
    cd.sysinfo.xy_mode = calloc(1, cd.sysinfo.si_ofs.mode_size);
    cd.sysinfo.xy_data = calloc(1, cd.sysinfo.si_ofs.data_size);
    cd.md.si = &cd.sysinfo; cd.md.input = &input;
    FILE *frames = fopen(argv[2], "rb"); assert(frames);
    unsigned int samples = 0, coordinates = 0;
    wire_length = 64;
    while (fread(wire, 1, 64, frames) == 64) {
        struct cy4_contact expected[10];
        int count = cy4_parse_report(&reference, wire, 64, expected);
        assert(count >= 0);
        memcpy(cd.sysinfo.xy_mode, wire, cd.sysinfo.si_ofs.mode_size);
        assert(!cyttsp4_xy_worker(&cd));
        assert(active == (unsigned int)count);
        for (int i = 0; i < count; i++) {
            assert(decoded[i].abs[CY_TCH_X] == expected[i].x);
            assert(decoded[i].abs[CY_TCH_Y] == expected[i].y);
            assert(decoded[i].abs[CY_TCH_T] == expected[i].id);
            assert(decoded[i].abs[CY_TCH_P] == expected[i].pressure);
            assert(decoded[i].abs[CY_TCH_W] == expected[i].width);
            coordinates++;
        }
        samples++;
    }
    fclose(frames);
    /* Oversize counts must be rejected before any read into the 70-byte buffer. */
    unsigned int before = reads;
    cd.sysinfo.xy_mode[9] = 219; cd.sysinfo.xy_mode[11] = 31;
    assert(cyttsp4_xy_worker(&cd) == -EPROTO && reads == before && !active);
    /* Ten contacts cross the former bridge's 64-byte limit. */
    memset(wire, 0, 256); wire_length = 82; wire[9] = 72; wire[11] = 10;
    for (unsigned int i = 0; i < 10; i++) {
        u8 *p = wire + 12 + i * 7;
        p[1] = 100 + i; p[3] = 200; p[4] = 20; p[5] = 0x20 | i; p[6] = 3;
    }
    memcpy(cd.sysinfo.xy_mode, wire, 12);
    assert(!cyttsp4_xy_worker(&cd) && active == 10);
    assert(decoded[9].abs[CY_TCH_X] == 109 && decoded[9].abs[CY_TCH_T] == 9);
    /* Exhaust every one-byte descriptor corruption through the ported parser. */
    wire_length = 256;
    for (unsigned int byte = 66; byte < 89; byte++) {
        for (unsigned int value = 0; value < 256; value++) {
            memcpy(wire, original, 256); wire[byte] = value;
            if (!cyttsp4_si_get_opcfg_data(&cd)) {
                u8 record[7] = {0}; struct cyttsp4_touch t;
                cyttsp4_get_touch(&cd.md, &t, record);
            }
        }
    }
    printf("PASS upstream-core captured_frames=%u matching_contacts=%u; ten contacts, pre-read count bound, 5888 descriptor mutations\n", samples, coordinates);
    free(cd.sysinfo.si_ptrs.opcfg); free(cd.sysinfo.xy_mode); free(cd.sysinfo.xy_data);
    return 0;
}
'''
test = HERE / 'test-core.c'
test.write_text(prefix + enum + '\n' + types + '\n' + stubs + helpers + capture +
                function('cyttsp4_xy_worker') + main)
binary = HERE / 'test-core'
subprocess.run(['clang', '-std=c11', '-g', '-O1', '-Wall', '-Wextra',
    '-Wno-unused-parameter', '-Wno-unused-variable', '-Wno-unused-but-set-variable',
    '-Wno-unused-but-set-global', '-Werror',
    '-fsanitize=address,undefined', '-fno-omit-frame-pointer', test, '-o', binary], check=True)
result = subprocess.run([binary, OLD / 'fixtures/sysinfo.bin', OLD / 'fixtures/reports.bin'],
    capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
(HERE / 'test-core.log').write_text(result.stdout + result.stderr)
result.check_returncode()
print(result.stdout, end='')
