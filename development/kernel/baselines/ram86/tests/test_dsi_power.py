#!/usr/bin/env python3
"""Exercise the actual host/bridge callbacks against the DRM power-order contract."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parents[1]
DSI = HERE / 'source/drivers/gpu/drm/omapdrm/dss/dsi.c'
BRIDGE = HERE / 'source/drivers/gpu/drm/bridge/tc358775.c'


def function(text, result, name):
    start = text.index('static ' + result + ' ' + name + '(')
    end = text.index('\n}\n', start) + 3
    return text[start:end]


def main():
    dsi, bridge = DSI.read_text(), BRIDGE.read_text()
    out = HERE / 'tests/out/dsi-power'
    out.mkdir(parents=True, exist_ok=True)
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include <errno.h>
#define VC_VIDEO 0
#define MIPI_DSI_NULL_PACKET 0x09
struct device { int unused; };
struct drm_bridge { int unused; };
struct drm_atomic_state { int unused; };
struct omap_dss_device { int unused; };
struct dsi_data {
    struct drm_bridge bridge;
    struct omap_dss_device output;
    int dsi_disable_work;
    bool iface_enabled, video_enabled;
};
struct mipi_dsi_msg { uint8_t channel, type; unsigned int flags; };
struct mipi_dsi_host;
struct mipi_dsi_host_ops {
    ssize_t (*transfer)(struct mipi_dsi_host *, const struct mipi_dsi_msg *);
};
struct mipi_dsi_host { const struct mipi_dsi_host_ops *ops; };
struct mipi_dsi_device { struct device dev; struct mipi_dsi_host *host; uint8_t channel; };
struct gpio_desc { bool reset; };
struct tc_data {
    struct drm_bridge bridge;
    struct device *dev;
    struct mipi_dsi_device *dsi;
    struct gpio_desc *reset_gpio, *stby_gpio;
    void *vddio, *vdd;
};
static bool phy_on, hs_on, reset_asserted = true, locked;
static unsigned int reset_wait;
static char events[64];
static unsigned int next;
static void event(char c) { assert(next < sizeof(events) - 1); events[next++] = c; }
#define drm_bridge_to_dsi(b) ((struct dsi_data *)(b))
static struct tc_data *bridge_to_tc(struct drm_bridge *b) { return (struct tc_data *)b; }
static bool tc_is_perrier(struct tc_data *tc) { (void)tc; return true; }
static void cancel_delayed_work_sync(int *work) { (void)work; assert(!locked); }
static void dsi_bus_lock(struct dsi_data *dsi) { (void)dsi; assert(!locked); locked = true; }
static void dsi_bus_unlock(struct dsi_data *dsi) { (void)dsi; assert(locked); locked = false; }
static void dsi_enable(struct dsi_data *dsi)
{ assert(locked && !dsi->iface_enabled); dsi->iface_enabled = phy_on = true; event('P'); }
static void dsi_disable(struct dsi_data *dsi)
{ assert(locked && reset_asserted && !dsi->video_enabled); dsi->iface_enabled = phy_on = hs_on = false; event('p'); }
static void dsi_enable_video_output(struct omap_dss_device *d, int vc)
{ (void)d; assert(locked && vc == 0 && phy_on && hs_on && !reset_asserted); event('V'); }
static void dsi_disable_video_output(struct omap_dss_device *d, int vc)
{ (void)d; assert(locked && vc == 0 && phy_on && !reset_asserted); event('v'); }
static int regulator_enable(void *r) { (void)r; return 0; }
static int regulator_disable(void *r) { (void)r; return 0; }
static void usleep_range(int a, int b) { (void)a; (void)b; }
static void msleep(unsigned int ms) { if (!reset_asserted) reset_wait += ms; }
static void gpiod_set_value(struct gpio_desc *gpio, int value)
{
    if (!gpio || !gpio->reset) return;
    assert(phy_on);
    reset_asserted = value;
    reset_wait = 0;
    event(value ? 'R' : 'r');
}
#define dev_err(dev, ...) ((void)(dev))
#define dev_info(dev, ...) ((void)(dev))
static ssize_t host_transfer(struct mipi_dsi_host *host, const struct mipi_dsi_msg *msg)
{
    (void)host;
    assert(!locked && phy_on && !reset_asserted && reset_wait >= 200);
    assert(msg->channel == 0 && msg->type == MIPI_DSI_NULL_PACKET && !msg->flags);
    hs_on = true; event('H'); return 0;
}
static void tc_bridge_program(struct drm_bridge *b, struct drm_atomic_state *s)
{ (void)b; (void)s; assert(phy_on && hs_on && !reset_asserted); event('I'); }
'''
    for name in ('dsi_bridge_pre_enable', 'dsi_bridge_enable',
                 'dsi_bridge_disable', 'dsi_bridge_post_disable'):
        code += '\n' + function(dsi, 'void', name)
    code += '\n' + function(bridge, 'int', 'tc358765_start_hs_clock')
    for name in ('tc_bridge_atomic_pre_enable', 'tc_bridge_atomic_post_disable'):
        code += '\n' + function(bridge, 'void', name)
    code += r'''
int main(void)
{
    struct dsi_data dsi = {0};
    struct device dev = {0};
    struct gpio_desc reset = {.reset = true};
    const struct mipi_dsi_host_ops ops = {.transfer = host_transfer};
    struct mipi_dsi_host host = {.ops = &ops};
    struct mipi_dsi_device peripheral = {.host = &host};
    struct tc_data tc = {.dev = &dev, .dsi = &peripheral, .reset_gpio = &reset};
    struct drm_atomic_state state = {0};
    for (int i = 0; i < 2; i++) {
        assert(reset_asserted && !phy_on && !dsi.iface_enabled);
        dsi_bridge_pre_enable(&dsi.bridge);
        assert(phy_on && !hs_on && !dsi.video_enabled);
        tc_bridge_atomic_pre_enable(&tc.bridge, &state);
        dsi_bridge_enable(&dsi.bridge);
        assert(dsi.video_enabled && !reset_asserted);
        dsi_bridge_disable(&dsi.bridge);
        assert(phy_on && !dsi.video_enabled);
        tc_bridge_atomic_post_disable(&tc.bridge, &state);
        dsi_bridge_post_disable(&dsi.bridge);
        assert(!phy_on && !dsi.iface_enabled && reset_asserted);
    }
    assert(!strcmp(events, "PrHIVvRpPrHIVvRp"));
    puts("PASS: two real callback cycles follow PHY -> reset release -> HS -> I2C -> video; stop video -> reset -> PHY off");
    return 0;
}
'''
    test = out / 'power-sequence-test.c'
    test.write_text(code)
    executable = out / 'power-sequence-test'
    subprocess.run(['clang', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-parameter', '-g',
                    '-O1', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(test), '-o', str(executable)], check=True)
    result = subprocess.run([str(executable)], check=True, capture_output=True,
                            text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    report = {'passed': True, 'cycles': 2, 'sanitizers': ['address', 'undefined'],
              'source_sha256': hashlib.sha256(dsi.encode()).hexdigest(),
              'bridge_source_sha256': hashlib.sha256(bridge.encode()).hexdigest(),
              'output': result.stdout.strip()}
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(result.stdout, end='')


if __name__ == '__main__':
    main()
