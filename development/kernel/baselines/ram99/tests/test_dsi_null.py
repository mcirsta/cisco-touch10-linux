#!/usr/bin/env python3
"""NULL clock packets must complete without an unsolicited peripheral response."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parents[1]
REL = 'drivers/gpu/drm/omapdrm/dss/dsi.c'


def transfer(text, prefix=''):
    match = re.search(r'static ssize_t _omap_dsi_host_transfer\([^;]*?\)\n\{', text)
    assert match
    end = text.index('\n}\n', match.start()) + 3
    return text[match.start():end].replace('_omap_dsi_host_transfer(', prefix + '_omap_dsi_host_transfer(')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=HERE / 'source' / REL)
    args = parser.parse_args()
    current = args.source.read_text()
    old = (HERE / 'baselines/ram78/source' / REL).read_text()
    out = HERE / 'tests/out/dsi-null'
    out.mkdir(parents=True, exist_ok=True)
    header = HERE / 'work/linux-6.18.48/include/video/mipi_display.h'
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
#include <sys/types.h>
typedef uint8_t u8;
#define MIPI_DSI_MSG_REQ_ACK 1
#define MIPI_DSI_MSG_USE_LPM 2
struct omap_dss_device { int unused; };
struct dsi_data { struct omap_dss_device output; };
struct mipi_dsi_msg {
    u8 channel, type; unsigned int flags;
    size_t tx_len; const void *tx_buf;
};
static int common_calls, long_calls, sync_calls, common_ret, long_ret, sync_ret;
static int last_vc;
static bool hs;
static void dsi_vc_enable_hs(struct omap_dss_device *d, int vc, bool value)
{ (void)d; last_vc = vc; hs = value; }
static int dsi_vc_write_common(struct omap_dss_device *d, int vc, const struct mipi_dsi_msg *m)
{ (void)d; (void)m; last_vc = vc; common_calls++; return common_ret; }
static int dsi_vc_send_long(struct dsi_data *d, int vc, const struct mipi_dsi_msg *m)
{ (void)d; assert(m->type == 0x09 && m->channel == 0); last_vc = vc; long_calls++; return long_ret; }
static int dsi_sync_vc(struct dsi_data *d, int vc)
{ (void)d; last_vc = vc; sync_calls++; return sync_ret; }
static int dsi_vc_generic_read(struct omap_dss_device *d, int vc, const struct mipi_dsi_msg *m)
{ (void)d; (void)vc; (void)m; return 0; }
static int dsi_vc_dcs_read(struct omap_dss_device *d, int vc, const struct mipi_dsi_msg *m)
{ (void)d; (void)vc; (void)m; return 0; }
static void dsi_enable_te(struct dsi_data *d, bool enable)
{ (void)d; (void)enable; }
static void reset(void)
{ common_calls = long_calls = sync_calls = common_ret = long_ret = sync_ret = 0; }
'''
    code += '#include "' + str(header) + '"\n'
    code += transfer(old, 'old') + '\n' + transfer(current)
    code += r'''
int main(void)
{
    struct dsi_data dsi = {0};
    struct mipi_dsi_msg msg = {.type = MIPI_DSI_NULL_PACKET};
    reset(); common_ret = -ETIMEDOUT;
    assert(old_omap_dsi_host_transfer(&dsi, 1, &msg) == -ETIMEDOUT);
    assert(common_calls == 1 && !long_calls && !sync_calls);
    reset(); common_ret = -ETIMEDOUT;
    assert(!_omap_dsi_host_transfer(&dsi, 1, &msg));
    assert(!common_calls && long_calls == 1 && sync_calls == 1 && hs && last_vc == 1);
    reset(); long_ret = -EIO;
    assert(_omap_dsi_host_transfer(&dsi, 1, &msg) == -EIO);
    assert(long_calls == 1 && !sync_calls && !common_calls);
    reset(); sync_ret = -ETIMEDOUT;
    assert(_omap_dsi_host_transfer(&dsi, 1, &msg) == -ETIMEDOUT);
    assert(long_calls == 1 && sync_calls == 1 && !common_calls);
    reset(); msg.flags = MIPI_DSI_MSG_USE_LPM;
    assert(!_omap_dsi_host_transfer(&dsi, 1, &msg) && !hs);
    reset(); msg.flags = MIPI_DSI_MSG_REQ_ACK; common_ret = -ETIMEDOUT;
    assert(_omap_dsi_host_transfer(&dsi, 1, &msg) == -ETIMEDOUT);
    assert(common_calls == 1 && !long_calls && !sync_calls);
    reset(); msg.type = MIPI_DSI_GENERIC_SHORT_WRITE_0_PARAM; msg.flags = 0;
    assert(!_omap_dsi_host_transfer(&dsi, 1, &msg));
    assert(common_calls == 1 && !long_calls && !sync_calls);
    puts("PASS: NULL avoids unsolicited BTA, honors speed/ACK flags, and propagates send/sync failures; generic writes unchanged");
    return 0;
}
'''
    test = out / 'null-transfer-test.c'
    test.write_text(code)
    executable = out / 'null-transfer-test'
    subprocess.run(['clang', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-g',
                    '-O1', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(test), '-o', str(executable)], check=True)
    result = subprocess.run([str(executable)], check=True, capture_output=True,
                            text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    report = {'passed': True, 'cases': 7, 'source': str(args.source),
              'sanitizers': ['address', 'undefined'],
              'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'output': result.stdout.strip()}
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(result.stdout, end='')


if __name__ == '__main__':
    main()
