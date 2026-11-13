#!/usr/bin/env python3
"""Board-gated audit for a temporary native OMAP DRM LCD pattern image."""
import hashlib
import json
from pathlib import Path
import runpy
import struct

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
fdt_nodes = runpy.run_path(str(ROOT / 'development/perrier-simpledrm/audit.py'))['fdt_nodes']

def cell(node, key):
    return struct.unpack('>I', node[key])[0]

def main():
    cfg = (HERE / 'build/.config').read_text()
    for name in ('DRM_OMAP', 'OMAP2_DSS_DSI', 'DRM_TOSHIBA_TC358775',
                 'DRM_PANEL_LVDS', 'BACKLIGHT_CLASS_DEVICE', 'MMC_OMAP_HS',
                 'DEVMEM', 'I2C_OMAP', 'USB_EHCI_HCD_OMAP', 'DEBUG_FS'):
        assert f'CONFIG_{name}=y\n' in cfg, name
    assert 'CONFIG_GPIO_OMAP=y\n' in cfg
    assert 'CONFIG_OMAP2_DSS_DEBUGFS=y\n' in cfg
    for name in ('DRM_SIMPLEDRM', 'DRM_FBDEV_EMULATION',
                 'PINCTRL_SINGLE', 'WATCHDOG', 'SMP', 'CPU_IDLE', 'CPU_FREQ'):
        assert f'CONFIG_{name}=y\n' not in cfg, name
    assert 'CONFIG_LOCALVERSION="-perrier-ram35"' in cfg
    nodes = fdt_nodes((HERE / 'build/omap4-perrier-ram.dtb').read_bytes())
    assert nodes['/ocp']['status'] == b'disabled\0'
    assert nodes['/chosen/framebuffer@7ec78000']['status'] == b'disabled\0'
    for path in ('/target-module@58000000',
                 '/target-module@58000000/dss@0',
                 '/target-module@58000000/dss@0/target-module@1000/dispc@0',
                 '/target-module@58000000/dss@0/target-module@4000/encoder@0',
                 '/target-module@48060000/i2c@0/bridge@f', '/panel'):
        assert path in nodes and nodes[path].get('status', b'okay\0') == b'okay\0', path
    bridge = nodes['/target-module@48060000/i2c@0/bridge@f']
    assert bridge['compatible'] == b'toshiba,tc358765\0'
    assert cell(bridge, 'reg') == 15
    gpio = nodes['/target-module@48059000/gpio@0']
    assert gpio['compatible'] == b'ti,omap4-gpio\0'
    assert nodes['/target-module@48059000'].get('ti,no-reset-on-init') == b''
    assert bridge['reset-gpios'] == gpio['phandle'] + struct.pack('>II',6,1)
    assert 'stby-gpios' not in bridge
    assert nodes['/panel']['data-mapping'] == b'vesa-24\0'
    mode = nodes['/panel/panel-timing']
    for name, value in {'clock-frequency':71074000, 'hactive':1280,
                        'hfront-porch':78, 'hback-porch':79, 'hsync-len':3,
                        'vactive':800, 'vfront-porch':12, 'vback-porch':10,
                        'vsync-len':1}.items():
        assert cell(mode,name) == value, name
    dsi_ep = nodes['/target-module@58000000/dss@0/target-module@4000/encoder@0/port/endpoint']
    assert dsi_ep['lanes'] == struct.pack('>10I', *range(10))
    bridge_ep = nodes['/target-module@48060000/i2c@0/bridge@f/ports/port@0/endpoint']
    assert bridge_ep['data-lanes'] == struct.pack('>4I',1,2,3,4)
    assert dsi_ep['remote-endpoint'] == bridge_ep['phandle']
    for name in ('regulator-bridge-vddio', 'regulator-bridge-vdd'):
        regulator = nodes['/'+name]
        assert regulator['compatible'] == b'regulator-fixed\0'
        assert 'regulator-always-on' in regulator
        assert not any('gpio' in p for p in regulator)
    bridge_source = (ROOT/'development/sources/linux-6.18.48/drivers/gpu/drm/bridge/tc358775.c').read_text()
    assert 'devm_regulator_get(dev, "vddio")' in bridge_source
    assert 'if (!tc->dsi) {' in bridge_source
    assert 'ret = tc_attach_host(tc);' in bridge_source
    assert 'DSI host attach occurs from bridge .attach.' in bridge_source
    assert 'goto err_bridge_remove;' not in bridge_source
    assert 'static bool tc_is_perrier' in bridge_source
    assert 'of_machine_is_compatible("cisco,perrier-ram")' in bridge_source
    assert 'LV_PHY0_IS(1) | LV_PHY0_ND(6)' in bridge_source
    assert 'TC358775_VPCTRL_VSDELAY(15) | BIT(8) | BIT(4)' in bridge_source
    assert 'val &= ~(GENMASK(9, 8) | GENMASK(11, 10) | BIT(1));' in bridge_source
    assert 'msleep(20);' in bridge_source and 'msleep(100);' in bridge_source
    assert 'dsi->mode_flags = MIPI_DSI_MODE_VIDEO | MIPI_DSI_MODE_LPM;' in bridge_source
    assert 'if (!tc_is_perrier(tc))\n\t\tdsi->mode_flags |= MIPI_DSI_MODE_VIDEO_BURST;' in bridge_source
    assert 'tc_bridge_program(bridge, state);' in bridge_source
    assert 'Perrier was reset during probe, before the DSI PHY starts.' in bridge_source
    assert 'Perrier bridge ID after early reset:' in bridge_source
    assert 'Perrier bridge not ready; skip programming' in bridge_source
    pll_source = (ROOT/'development/sources/linux-6.18.48/drivers/gpu/drm/omapdrm/dss/pll.c').read_text()
    assert 'n_start = max(n_start, 38);' in pll_source
    assert 'm != m_stop + m_inc' in pll_source
    dsi_source = (ROOT/'development/sources/linux-6.18.48/drivers/gpu/drm/omapdrm/dss/dsi.c').read_text()
    assert 'bool stock_timing = of_machine_is_compatible("cisco,perrier-ram")' in dsi_source
    assert 'DIV_ROUND_CLOSEST_ULL((u64)panel_htot * byteclk' in dsi_source
    assert 'abs_diff(line_a, line_b) > dispc_pck / 1000' in dsi_source
    assert 'DIV_ROUND_UP_ULL((u64)req_vm->hback_porch * byteclk' in dsi_source
    assert 'The working Perrier stock path leaves VP_HSYNC_POL clear.' in dsi_source
    assert 'DSS_IO_PAD_MODE_RESET : DSS_IO_PAD_MODE_BYPASS;' in dsi_source
    assert 'Stock Perrier video mode leaves VC0 on L4.' in dsi_source
    assert 'dsi->vc[VC_VIDEO].source = DSI_VC_SOURCE_VP;' in dsi_source
    assert 'static void dsi_bridge_pre_enable(struct drm_bridge *bridge)' in dsi_source
    assert '.pre_enable = dsi_bridge_pre_enable,' in dsi_source
    dispc_source = (ROOT/'development/sources/linux-6.18.48/drivers/gpu/drm/omapdrm/dss/dispc.c').read_text()
    assert 'bool perrier_dsi = channel == OMAP_DSS_CHANNEL_LCD' in dispc_source
    assert 'onoff = !perrier_dsi;' in dispc_source
    assert 'supports_sync_align && !perrier_dsi' in dispc_source
    block = (ROOT/'development/sources/linux-6.18.48/drivers/mmc/core/block.c').read_text()
    assert 'if (of_machine_is_compatible("cisco,perrier-ram"))\n\t\tmd->read_only = 1;' in block
    init = (HERE/'init.c').read_text()
    assert 'PERRIER_INIT_ENTER ram35' in init
    assert 'probe_native_display_state();' in init
    assert 'show_kms_pattern();' in init
    assert '                probe_dispc(mem);' not in init
    assert '                probe_touch_one_ack();' not in init
    assert 'reboot(RB_AUTOBOOT)' in init
    pattern = (HERE/'kms_pattern.c').read_text()
    assert '#define WIDTH 1280u' in pattern and '#define HEIGHT 800u' in pattern
    assert 'conn.connector_type != DRM_MODE_CONNECTOR_LVDS' in pattern
    assert 'DRM_IOCTL_MODE_SETCRTC' in pattern
    assert 'PERRIER_PATTERN_SETCRTC_OK' in pattern
    assert '.bpp = 32, .depth = 32' in pattern
    assert '0xff006020' in pattern and '0xffffffff' in pattern
    assert 'DRM_IOCTL_MODE_GETCRTC' in pattern
    assert 'snapshot_bridge("start");' in pattern
    assert 'snapshot_dss_file("dsi1_regs");' in pattern
    assert 'snapshot_dss_file("clk");' in pattern
    assert 'snapshot_dss_file("dss");' in pattern
    assert 'snapshot_bridge("start");' in pattern
    assert 'snapshot_bridge("end");' in pattern
    assert '{0x0454, "HTIM1"}' in pattern
    assert '{0x0498, "LV_MX2427"}' in pattern
    assert 'snapshot_backlight("before_modeset");' in pattern
    assert 'snapshot_backlight("after_modeset");' in pattern
    backlight = (HERE/'stock-analysis/backlight_state.c').read_text()
    assert 'open("/dev/mem", O_RDONLY | O_SYNC)' in backlight
    assert 'mmap(NULL, 4096, PROT_READ, MAP_SHARED, fd, base)' in backlight
    assert 'O_WRONLY' not in backlight and 'PROT_WRITE' not in backlight
    assert 'sleep(45)' in pattern
    assert '/dev/mmc' not in pattern and '/dev/mem' not in pattern
    files = {'zImage':HERE/'build/arch/arm/boot/zImage',
             'board.dtb':HERE/'build/omap4-perrier-ram.dtb',
             'kexec':ROOT/'development/perrier/kexec-legacy-fdt'}
    artifacts = {name:{'size':p.stat().st_size,
                       'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
                 for name,p in files.items()}
    image_end = next(int(line.split()[0],16) for line in
                     (HERE/'build/System.map').read_text().splitlines()
                     if line.endswith(' _end'))
    assert image_end - 0xc0000000 < 0x02000000
    report = {'passed':True, 'kernel':'6.18.48-perrier-ram35',
              'purpose':'reset the bridge before DSI startup, then program it before video during a bounded RAM-only KMS scanout',
              'limitations':['bridge and panel physical supplies are inherited; logical regulators have no control GPIO',
                             'only stock GPIO102 reset is controlled; GPIO4 bank is not reset on init',
                             'no backlight driver or panel rail sequencing'],
              'artifacts':artifacts}
    (HERE/'reviewed-trial.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__ == '__main__': main()
