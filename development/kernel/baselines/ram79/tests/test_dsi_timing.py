#!/usr/bin/env python3
"""Exercise the actual DSI arithmetic with captured timing and divider limits."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parents[1]
NAME = 'drivers/gpu/drm/omapdrm/dss/dsi.c'
OUT = HERE / 'tests/out/dsi-timing'


def function(text, name):
    start = text.index('static bool ' + name + '(')
    end = text.index('\n}\n', start) + 3
    return text[start:end]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    current = (HERE / 'source' / NAME).read_text()
    before = (HERE / 'baselines/ram74/source' / NAME).read_text()
    helper = function(current, 'dsi_vm_calc_line_totals')
    new = function(current, 'dsi_vm_calc_blanking')
    old = function(before, 'dsi_vm_calc_blanking').replace(
        'dsi_vm_calc_blanking(', 'old_blanking(')
    prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>
typedef uint64_t u64;
#define HSDIV_DISPC 0
#define OMAP_DSS_DSI_EVENT_MODE 0
#define OMAP_DSS_DSI_PULSE_MODE 1
#define OMAP_DSS_DSI_BURST_MODE 2
#define DIV_ROUND_UP(n, d) (((n) + (d) - 1) / (d))
#define DIV_ROUND_UP_ULL(n, d) DIV_ROUND_UP(n, d)
#define DIV_ROUND_CLOSEST_ULL(n, d) (((n) + (d) / 2) / (d))
#define max(a, b) ((a) > (b) ? (a) : (b))
#define abs_diff(a, b) ((a) > (b) ? (a) - (b) : (b) - (a))
static u64 div64_u64(u64 n, u64 d) { return n / d; }
static unsigned long gcd(unsigned long a, unsigned long b)
{ while (b) { unsigned long c = a % b; a = b; b = c; } return a; }
static bool of_machine_is_compatible(const char *s) { (void)s; return true; }
static int mipi_dsi_pixel_format_to_bpp(int format) { return format; }
struct videomode {
    unsigned long pixelclock;
    int hactive, hfront_porch, hback_porch, hsync_len;
    int vactive, vfront_porch, vback_porch, vsync_len;
};
struct omap_dss_dsi_config {
    int pixel_format, trans_mode;
    const struct videomode *vm;
};
struct dsi_data { int num_lanes_used, line_buffer_size; };
struct omap_dss_dsi_videomode_timings {
    unsigned long hsclk;
    int ndl, bitspp, hss, hsa, hse, hbp, hact, hfp;
    int vsa, vbp, vact, vfp, trans_mode;
    int blanking_mode, hsa_blanking_mode, hfp_blanking_mode;
    int hbp_blanking_mode, window_sync;
};
struct dsi_clk_calc_ctx {
    struct dsi_data *dsi;
    const struct omap_dss_dsi_config *config;
    unsigned long req_pck_min, req_pck_nom, req_pck_max;
    struct { unsigned long clkdco; unsigned int mX[1]; } dsi_cinfo;
    struct { unsigned int lck_div, pck_div; unsigned long pck; } dispc_cinfo;
    struct videomode vm;
    struct omap_dss_dsi_videomode_timings dsi_vm;
};
'''
    tests = r'''
int main(void)
{
    int dt = -1, pt = -1;
    assert(dsi_vm_calc_line_totals(12, 53305246, 71073000, 71074000,
                                  71075000, 1440, &dt, &pt));
    assert(dt == 1080 && pt == 1440);
    assert((u64)dt * 71073662 != (u64)pt * 53305246);
    assert((u64)dt * 16 == (u64)pt * 12);
    assert(!dsi_vm_calc_line_totals(0, 53305246, 1, 2, 3, 1440, &dt, &pt));
    assert(!dsi_vm_calc_line_totals(12, 0, 1, 2, 3, 1440, &dt, &pt));
    assert(!dsi_vm_calc_line_totals(12, 1, 1, 0, 3, 1440, &dt, &pt));
    assert(!dsi_vm_calc_line_totals(12, 1, 3, 2, 1, 1440, &dt, &pt));
    assert(!dsi_vm_calc_line_totals(12, 1, 1, 2, 3, 0, &dt, &pt));
    /* An integral line outside the panel's frequency interval is rejected. */
    assert(!dsi_vm_calc_line_totals(17, 50000000, 99999000, 100000000,
                                   100001000, 1000, &dt, &pt));
    /* Extreme 32-bit inputs must not overflow or truncate into valid totals. */
    assert(!dsi_vm_calc_line_totals(1, UINT32_MAX, 1, 1, 1,
                                   INT_MAX, &dt, &pt));
    assert(!dsi_vm_calc_line_totals(UINT32_MAX, UINT32_MAX, 1, 1, 1,
                                   INT_MAX, &dt, &pt));
    struct videomode vm = { .pixelclock = 71074000, .hactive = 1280,
        .hfront_porch = 78, .hback_porch = 79, .hsync_len = 3,
        .vactive = 800, .vfront_porch = 12, .vback_porch = 10, .vsync_len = 1 };
    struct dsi_data dsi = { .num_lanes_used = 5, .line_buffer_size = 8192 };
    struct omap_dss_dsi_config cfg = { .pixel_format = 24,
        .trans_mode = OMAP_DSS_DSI_EVENT_MODE, .vm = &vm };
    struct dsi_clk_calc_ctx a = { .dsi = &dsi, .config = &cfg,
        .req_pck_min = 71073000, .req_pck_nom = 71074000,
        .req_pck_max = 71075000,
        .dsi_cinfo = { .clkdco = 852883944, .mX = { 6 } },
        .dispc_cinfo = { .lck_div = 1, .pck_div = 2, .pck = 71073662 } };
    struct dsi_clk_calc_ctx b = a;
    assert(old_blanking(&a) && dsi_vm_calc_blanking(&b));
    assert(!memcmp(&a.vm, &b.vm, sizeof(a.vm)));
    a.dsi_vm.hbp = 59; a.dsi_vm.hfp = 58;
    assert(!memcmp(&a.dsi_vm, &b.dsi_vm, sizeof(a.dsi_vm)));
    assert(b.dsi_vm.hbp == 59 && b.dsi_vm.hfp == 58);
    /* Vary real divider ranges, nominal rate and line length. Check the
     * accepted result against rational clock/line constraints, not Hz equality.
     */
    unsigned int accepted = 0, rejected = 0;
    for (unsigned int hs = 1; hs <= 32; hs++)
        for (unsigned int lck = 1; lck <= 255; lck += 17)
            for (unsigned int pck = 1; pck <= 255; pck += 17) {
                unsigned int div = hs * lck * pck;
                unsigned int panel = 1280 + (hs + lck + pck) % 381;
                unsigned long nominal = 1000000000UL / div;
                if (!nominal) continue;
                unsigned long low = nominal > 1000 ? nominal - 1000 : 1;
                if (!dsi_vm_calc_line_totals(div, 62500000, low, nominal,
                        nominal + 1000, panel, &dt, &pt)) {
                    rejected++;
                    continue;
                }
                accepted++;
                assert(dt > 0 && pt > 0);
                assert((u64)dt * 16 == (u64)pt * div);
                assert((u64)dt * low <= (u64)panel * 62500000);
                assert((u64)dt * (nominal + 1000) >= (u64)panel * 62500000);
                unsigned int step = div / gcd(div, 16);
                assert(dt % step == 0);
                /* No adjacent integral line is closer to the nominal period. */
                u64 error = abs_diff((u64)dt * nominal, (u64)panel * 62500000);
                if ((unsigned int)dt > step)
                    assert(error <= abs_diff(((u64)dt - step) * nominal,
                                              (u64)panel * 62500000));
                assert(error <= abs_diff(((u64)dt + step) * nominal,
                                          (u64)panel * 62500000));
            }
    assert(accepted && rejected);
    printf("PASS: captured line clocks unchanged; mainline HBP=59/HFP=58; %u divider cases accepted, %u rejected\n",
           accepted, rejected);
    return 0;
}
'''
    source = OUT / 'dsi-timing-test.c'
    source.write_text(prefix + helper + '\n' + old + '\n' + new + '\n' + tests)
    executable = OUT / 'dsi-timing-test'
    subprocess.run(['clang', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-g', '-O1', '-fsanitize=address,undefined',
                    '-fno-omit-frame-pointer', str(source), '-o', str(executable)], check=True)
    result = subprocess.run([str(executable)], capture_output=True, text=True,
                            env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    if result.returncode:
        print(result.stderr, end='')
    result.check_returncode()
    print(result.stdout, end='')
    report = {'passed': True, 'sanitizers': ['address', 'undefined'],
              'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'captured_line_totals_unchanged': True, 'dsi_hbp': 59, 'dsi_hfp': 58,
              'dispc_timing_unchanged': True, 'output': result.stdout.strip()}
    (OUT / 'result.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
