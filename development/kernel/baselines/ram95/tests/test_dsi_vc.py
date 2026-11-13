#!/usr/bin/env python3
"""Reproduce and fix completion checks against the wrong DSI channel."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parents[1]
REL = 'drivers/gpu/drm/omapdrm/dss/dsi.c'


def callbacks(text, prefix=''):
    result = []
    for kind in ('vp', 'l4'):
        name = 'dsi_packet_sent_handler_' + kind
        start = text.index('static void ' + name + '(')
        end = text.index('\n}\n', start) + 3
        result.append(text[start:end].replace(name + '(', prefix + name + '('))
    return '\n'.join(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=HERE / 'source' / REL)
    args = parser.parse_args()
    source = args.source.read_text()
    baseline = (HERE / 'baselines/ram74/source' / REL).read_text()
    out = HERE / 'tests/out/dsi-vc'
    out.mkdir(parents=True, exist_ok=True)
    code = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
typedef uint32_t u32;
typedef uint8_t u8;
struct completion { int count; };
struct dsi_data { int update_vc; bool te_enabled; u32 regs[8]; };
struct dsi_packet_sent_handler_data {
    struct dsi_data *dsi;
    int vc;
    struct completion *completion;
};
#define DSI_VC_CTRL(vc) ((vc) * 2)
#define DSI_VC_TE(vc) ((vc) * 2 + 1)
#define REG_GET(dsi, reg, hi, lo) (((dsi)->regs[reg] >> (lo)) & 1)
static void complete(struct completion *c) { c->count++; }
'''
    code += callbacks(baseline, 'old_') + '\n' + callbacks(source)
    code += r'''
int main(void)
{
    void (*handlers[2][2])(void *, u32) = {
        {old_dsi_packet_sent_handler_l4, old_dsi_packet_sent_handler_vp},
        {dsi_packet_sent_handler_l4, dsi_packet_sent_handler_vp}
    };
    int failures[2] = {0, 0};
    for (int family = 0; family < 2; family++)
        for (int mode = 0; mode < 3; mode++)
            for (int vc = 0; vc < 4; vc++)
                for (int busy = 0; busy < 2; busy++) {
                    struct dsi_data dsi = {.update_vc = (vc + 1) % 4,
                                           .te_enabled = mode == 2};
                    struct completion done = {0};
                    struct dsi_packet_sent_handler_data data = {
                        .dsi = &dsi, .vc = vc, .completion = &done};
                    int bit = mode == 0 ? 5 : mode == 1 ? 31 : 30;
                    int reg = mode == 0 ? DSI_VC_CTRL(vc) : DSI_VC_TE(vc);
                    int other = mode == 0 ? DSI_VC_CTRL(dsi.update_vc) :
                                            DSI_VC_TE(dsi.update_vc);
                    dsi.regs[reg] = (u32)busy << bit;
                    dsi.regs[other] = (u32)!busy << bit;
                    handlers[family][mode != 0](&data, 0);
                    if (done.count != !busy) failures[family]++;
                }
    printf("baseline_failures=%d candidate_failures=%d cases=24\n",
           failures[0], failures[1]);
    return 0;
}
'''
    test = out / 'vc-completion-test.c'
    test.write_text(code)
    executable = out / 'vc-completion-test'
    subprocess.run(['clang', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-parameter', '-g', '-O1',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(test), '-o', str(executable)], check=True)
    result = subprocess.run([str(executable)], check=True, capture_output=True,
                            text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    match = re.fullmatch(r'baseline_failures=(\d+) candidate_failures=(\d+) cases=(\d+)\n', result.stdout)
    assert match and tuple(map(int, match.groups())) == (24, 0, 24), result.stdout
    report = {'passed': True, 'baseline_failures': 24, 'candidate_failures': 0,
              'cases': 24, 'sanitizers': ['address', 'undefined'],
              'source': str(args.source),
              'source_sha256': hashlib.sha256(source.encode()).hexdigest()}
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: baseline wrong-channel bug reproduced in all 24 cases; candidate passes')


if __name__ == '__main__':
    main()
