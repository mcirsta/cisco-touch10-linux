#!/usr/bin/env python3
"""Reproducible, board-gated first Perrier RAM kernel build."""
import difflib
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / "development/sources/linux-6.18.48"
OUT = HERE / "build"

def call(args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)

def patch_file(relative, old, new):
    path = SRC / relative
    before = path.read_text()
    if new in before:
        return
    assert before.count(old) == 1, relative
    after = before.replace(old, new)
    patches = HERE / "patches"
    patches.mkdir(exist_ok=True)
    with (patches / (path.name + ".patch")).open("a") as stream:
        stream.write("".join(difflib.unified_diff(
            before.splitlines(True), after.splitlines(True),
            fromfile="a/"+relative, tofile="b/"+relative)))
    path.write_text(after)

def patch_perrier_bridge():
    """Keep the stock TC358765 display sequence isolated to Perrier."""
    relative = "drivers/gpu/drm/bridge/tc358775.c"
    path = SRC / relative
    before = path.read_text()
    if "static bool tc_is_perrier" in before:
        return
    after = before
    replacements = [
        (
            '#include <linux/bitfield.h>\n',
            '#include <linux/bitfield.h>\n#include <linux/delay.h>\n#include <linux/of.h>\n',
        ),
        (
            '''static inline struct tc_data *bridge_to_tc(struct drm_bridge *b)
''',
            '''static bool tc_is_perrier(const struct tc_data *tc)
{
	return tc->type == TC358765 &&
		of_machine_is_compatible("cisco,perrier-ram");
}

static inline struct tc_data *bridge_to_tc(struct drm_bridge *b)
''',
        ),
        (
            '''	gpiod_set_value(tc->reset_gpio, 0);
	usleep_range(10, 20);
}

static void tc_bridge_atomic_post_disable''',
            '''	if (tc_is_perrier(tc)) {
		/* The stock driver asserts GPIO102 for 20 ms, then waits 100 ms. */
		gpiod_set_value(tc->reset_gpio, 1);
		msleep(20);
		gpiod_set_value(tc->reset_gpio, 0);
		msleep(100);
	} else {
		gpiod_set_value(tc->reset_gpio, 0);
		usleep_range(10, 20);
	}
}

static void tc_bridge_atomic_post_disable''',
        ),
        (
            '''	d2l_write(tc->i2c, SYSRST, SYS_RST_REG | SYS_RST_DSIRX | SYS_RST_BM |
		  SYS_RST_LCD | SYS_RST_I2CM);
	usleep_range(30000, 40000);
''',
            '''	/* Perrier's stock driver uses the physical reset and does not reset
	 * the full bridge register block here.
	 */
	if (!tc_is_perrier(tc)) {
		d2l_write(tc->i2c, SYSRST, SYS_RST_REG | SYS_RST_DSIRX |
			  SYS_RST_BM | SYS_RST_LCD | SYS_RST_I2CM);
		usleep_range(30000, 40000);
	}
''',
        ),
        (
            '''	d2l_write(tc->i2c, PPI_STARTPPI, PPI_START_FUNCTION);
	d2l_write(tc->i2c, DSI_STARTDSI, DSI_RX_START);

	/* Video event mode''',
            '''	d2l_write(tc->i2c, PPI_STARTPPI, PPI_START_FUNCTION);
	d2l_write(tc->i2c, DSI_STARTDSI, DSI_RX_START);

	if (tc_is_perrier(tc)) {
		/* CE9.9.0 TC358765: reset LVDS PHY, then IS=1 and ND=6.
		 * Keep the other bits returned by the chip, including PRBS off.
		 */
		d2l_write(tc->i2c, LVPHY0, LV_PHY0_RST(1));
		usleep_range(2000, 3000);
		d2l_read(tc->i2c, LVPHY0, &val);
		val &= ~(LV_PHY0_RST(1) | LV_PHY0_IS(3) | LV_PHY0_ND(31));
		val |= LV_PHY0_IS(1) | LV_PHY0_ND(6);
		d2l_write(tc->i2c, LVPHY0, val);
	}

	/* Video event mode''',
        ),
        (
            '''	/* Video event mode vs pulse mode bit, does not exist for tc358775 */
	if (tc->type == TC358765)
		val = EVTMODE;
	else
		val = 0;

	if (tc->bpc == 8)
		val |= TC358775_VPCTRL_OPXLFMT(1);
	else /* bpc = 6; */
		val |= TC358775_VPCTRL_MSF(1);

	dsiclk = mode->crtc_clock * 3 * tc->bpc / tc->num_dsi_lanes / 1000;
	clkdiv = dsiclk / (tc->lvds_link == DUAL_LINK ? DIVIDE_BY_6 : DIVIDE_BY_3);
	byteclk = dsiclk / 4;
	t1 = hactive * (tc->bpc * 3 / 8) / tc->num_dsi_lanes;
	t2 = ((100000 / clkdiv)) * (hactive + hback_porch + hsync_len + hfront_porch) / 1000;
	t3 = ((t2 * byteclk) / 100) - (hactive * (tc->bpc * 3 / 8) /
		tc->num_dsi_lanes);

	vsdelay = (clkdiv * (t1 + t3) / byteclk) - hback_porch - hsync_len - hactive;

	val |= TC358775_VPCTRL_VSDELAY(vsdelay);
	d2l_write(tc->i2c, VPCTRL, val);
''',
            '''	if (tc_is_perrier(tc)) {
		/* Stock readback: 0x00f02110. Preserve unrelated chip bits. */
		d2l_read(tc->i2c, VPCTRL, &val);
		val &= ~(TC358775_VPCTRL_VSDELAY__MASK | BIT(8) |
			 BIT(5) | BIT(4) | BIT(0));
		val |= TC358775_VPCTRL_VSDELAY(15) | BIT(8) | BIT(4);
	} else {
		/* Video event mode vs pulse mode bit, does not exist for tc358775 */
		if (tc->type == TC358765)
			val = EVTMODE;
		else
			val = 0;

		if (tc->bpc == 8)
			val |= TC358775_VPCTRL_OPXLFMT(1);
		else /* bpc = 6; */
			val |= TC358775_VPCTRL_MSF(1);

		dsiclk = mode->crtc_clock * 3 * tc->bpc / tc->num_dsi_lanes / 1000;
		clkdiv = dsiclk / (tc->lvds_link == DUAL_LINK ? DIVIDE_BY_6 : DIVIDE_BY_3);
		byteclk = dsiclk / 4;
		t1 = hactive * (tc->bpc * 3 / 8) / tc->num_dsi_lanes;
		t2 = ((100000 / clkdiv)) * (hactive + hback_porch + hsync_len + hfront_porch) / 1000;
		t3 = ((t2 * byteclk) / 100) - (hactive * (tc->bpc * 3 / 8) /
			tc->num_dsi_lanes);

		vsdelay = (clkdiv * (t1 + t3) / byteclk) - hback_porch - hsync_len - hactive;
		val |= TC358775_VPCTRL_VSDELAY(vsdelay);
	}
	d2l_write(tc->i2c, VPCTRL, val);
''',
        ),
        (
            '''	d2l_write(tc->i2c, VFUEN, VFUEN_EN);
	d2l_write(tc->i2c, SYSRST, SYS_RST_LCD);
	d2l_write(tc->i2c, LVPHY0, LV_PHY0_PRBS_ON(4) | LV_PHY0_ND(6));
''',
            '''	if (!tc_is_perrier(tc)) {
		d2l_write(tc->i2c, VFUEN, VFUEN_EN);
		d2l_write(tc->i2c, SYSRST, SYS_RST_LCD);
		d2l_write(tc->i2c, LVPHY0,
			  LV_PHY0_PRBS_ON(4) | LV_PHY0_ND(6));
	}
''',
        ),
        (
            '''	d2l_write(tc->i2c, VFUEN, VFUEN_EN);

	val = LVCFG_LVEN_BIT;
	if (tc->lvds_link == DUAL_LINK) {
		val |= TC358775_LVCFG_LVDLINK(1);
		val |= TC358775_LVCFG_PCLKDIV(DIVIDE_BY_6);
	} else {
		val |= TC358775_LVCFG_PCLKDIV(DIVIDE_BY_3);
	}
	d2l_write(tc->i2c, LVCFG, val);
''',
            '''	if (tc_is_perrier(tc)) {
		/* TC358765 uses PCLKDIV in bits 9:8, unlike TC358775. */
		d2l_read(tc->i2c, LVCFG, &val);
		val &= ~(GENMASK(9, 8) | GENMASK(11, 10) | BIT(1));
		val |= LVCFG_LVEN_BIT;
		d2l_write(tc->i2c, LVCFG, val);
		d2l_write(tc->i2c, SYSRST, SYS_RST_LCD);
		d2l_write(tc->i2c, VFUEN, VFUEN_EN);
	} else {
		d2l_write(tc->i2c, VFUEN, VFUEN_EN);
		val = LVCFG_LVEN_BIT;
		if (tc->lvds_link == DUAL_LINK) {
			val |= TC358775_LVCFG_LVDLINK(1);
			val |= TC358775_LVCFG_PCLKDIV(DIVIDE_BY_6);
		} else {
			val |= TC358775_LVCFG_PCLKDIV(DIVIDE_BY_3);
		}
		d2l_write(tc->i2c, LVCFG, val);
	}
''',
        ),
    ]
    for old, new in replacements:
        assert after.count(old) == 1, (relative, old[:80])
        after = after.replace(old, new)
    (HERE / "patches/tc358775-perrier-display.patch").write_text("".join(
        difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                             fromfile="a/" + relative, tofile="b/" + relative)))
    path.write_text(after)

def cpio_entry(name, mode, data=b"", major=0, minor=0):
    filename = name.encode() + b"\0"
    fields = [1, mode, 0, 0, 1, 0, len(data), 0, 0, major, minor, len(filename), 0]
    header = b"070701" + b"".join(f"{n:08x}".encode() for n in fields) + filename
    return header + bytes((-len(header)) % 4) + data + bytes((-len(data)) % 4)

def main():
    OUT.mkdir(exist_ok=True)
    patch_file("drivers/clk/ti/clk-44xx.c", "\tti_clk_add_aliases();\n",
        "\tti_clk_add_aliases();\n\n\t/* Perrier RAM trial: retain stock USB/audio PLL configuration. */\n"
        "\tif (of_machine_is_compatible(\"cisco,perrier-ram\"))\n\t\treturn 0;\n")
    patch_file("arch/arm/mach-omap2/io.c", "void __init omap4430_init_late(void)\n{\n",
        "void __init omap4430_init_late(void)\n{\n"
        "\t/* No PMIC, voltage or low-power policy changes in the RAM trial. */\n"
        "\tif (of_machine_is_compatible(\"cisco,perrier-ram\"))\n\t\treturn;\n")
    patch_file("drivers/mmc/core/block.c", "#include <linux/rpmb.h>\n",
        "#include <linux/rpmb.h>\n#include <linux/of.h>\n")
    patch_file("drivers/mmc/core/block.c", "\tmd->read_only = mmc_blk_readonly(card);\n",
        "\tmd->read_only = mmc_blk_readonly(card);\n"
        "\t/* Perrier RAM trial: all eMMC areas reject write opens. */\n"
        "\tif (of_machine_is_compatible(\"cisco,perrier-ram\"))\n"
        "\t\tmd->read_only = 1;\n")
    patch_file("drivers/gpu/drm/bridge/tc358775.c",
        'devm_regulator_get(dev, "vddio-supply")',
        'devm_regulator_get(dev, "vddio")')
    patch_file("drivers/gpu/drm/bridge/tc358775.c",
        'devm_regulator_get(dev, "vdd-supply")',
        'devm_regulator_get(dev, "vdd")')
    patch_file("drivers/gpu/drm/bridge/tc358775.c",
        'static int tc_bridge_attach(struct drm_bridge *bridge,\n',
        'static int tc_attach_host(struct tc_data *tc);\n\n'
        'static int tc_bridge_attach(struct drm_bridge *bridge,\n')
    patch_file("drivers/gpu/drm/bridge/tc358775.c",
        '\tstruct tc_data *tc = bridge_to_tc(bridge);\n\n'
        '\t/* Attach the panel-bridge to the dsi bridge */\n',
        '\tstruct tc_data *tc = bridge_to_tc(bridge);\n'
        '\tint ret;\n\n'
        '\t/* Break the I2C bridge / DSI host probe-order cycle. */\n'
        '\tif (!tc->dsi) {\n'
        '\t\tret = tc_attach_host(tc);\n'
        '\t\tif (ret)\n'
        '\t\t\treturn ret;\n'
        '\t}\n\n'
        '\t/* Attach the panel-bridge to the dsi bridge */\n')
    patch_file("drivers/gpu/drm/bridge/tc358775.c",
        '\tret = tc_attach_host(tc);\n'
        '\tif (ret)\n'
        '\t\tgoto err_bridge_remove;\n\n'
        '\treturn 0;\n\n'
        'err_bridge_remove:\n'
        '\tdrm_bridge_remove(&tc->bridge);\n'
        '\treturn ret;\n',
        '\t/* DSI host attach occurs from bridge .attach. */\n'
        '\treturn 0;\n')
    patch_perrier_bridge()
    patch_file("drivers/gpu/drm/bridge/tc358775.c",
        '\tdsi->mode_flags = MIPI_DSI_MODE_VIDEO | MIPI_DSI_MODE_VIDEO_BURST |\n'
        '\t\t\t  MIPI_DSI_MODE_LPM;\n',
        '\t/* Stock Perrier uses a 1080-byte-clock line at 53.3 MHz. The\n'
        '\t * generic burst mode picked 1173 cycles at 57.9 MHz instead.\n'
        '\t */\n'
        '\tdsi->mode_flags = MIPI_DSI_MODE_VIDEO | MIPI_DSI_MODE_LPM;\n'
        '\tif (!tc_is_perrier(tc))\n'
        '\t\tdsi->mode_flags |= MIPI_DSI_MODE_VIDEO_BURST;\n')
    patch_file("drivers/gpu/drm/omapdrm/dss/pll.c",
        '#include <linux/kernel.h>\n',
        '#include <linux/kernel.h>\n#include <linux/of.h>\n')
    patch_file("drivers/gpu/drm/omapdrm/dss/pll.c",
        '\tn_start = max(DIV_ROUND_UP(clkin, fint_hw_max), 1ul);\n'
        '\tn_stop = min((unsigned)(clkin / fint_hw_min), hw->n_max);\n',
        '\tn_start = max(DIV_ROUND_UP(clkin, fint_hw_max), 1ul);\n'
        '\tn_stop = min((unsigned)(clkin / fint_hw_min), hw->n_max);\n'
        '\t/* The proven Perrier DSI1 clock uses N=38, M=422. */\n'
        '\tif (of_machine_is_compatible("cisco,perrier-ram") &&\n'
        '\t    !strcmp(pll->name, "dsi0"))\n'
        '\t\tn_start = max(n_start, 38);\n')
    patch_file("drivers/gpu/drm/omapdrm/dss/pll.c",
        '\t\tfor (m = m_start; m != m_stop; m += m_inc) {\n',
        '\t\t/* m_stop is inclusive: a narrow non-burst range can contain\n'
        '\t\t * exactly one valid multiplier.\n'
        '\t\t */\n'
        '\t\tfor (m = m_start; m != m_stop + m_inc; m += m_inc) {\n')
    patch_file("drivers/gpu/drm/omapdrm/dss/dsi.c",
        '\tu64 dsi_tput, dispc_tput;\n',
        '\tu64 dsi_tput, dispc_tput, line_a, line_b;\n'
        '\tbool stock_timing = of_machine_is_compatible("cisco,perrier-ram") &&\n'
        '\t\tcfg->trans_mode == OMAP_DSS_DSI_EVENT_MODE;\n')
    patch_file("drivers/gpu/drm/omapdrm/dss/dsi.c",
        '\tdsi_htot = div64_u64((u64)panel_htot * byteclk, req_pck_nom);\n',
        '\tif (stock_timing)\n'
        '\t\tdsi_htot = DIV_ROUND_CLOSEST_ULL((u64)panel_htot * byteclk,\n'
        '\t\t\t\t\t  req_pck_nom);\n'
        '\telse\n'
        '\t\tdsi_htot = div64_u64((u64)panel_htot * byteclk, req_pck_nom);\n')
    patch_file("drivers/gpu/drm/omapdrm/dss/dsi.c",
        '\tdispc_htot = div64_u64((u64)dsi_htot * dispc_pck, byteclk);\n\n'
        '\t/* verify that the DSI and DISPC TLs are the same */\n'
        '\tif ((u64)dsi_htot * dispc_pck != (u64)dispc_htot * byteclk)\n'
        '\t\treturn false;\n',
        '\tif (stock_timing)\n'
        '\t\tdispc_htot = DIV_ROUND_CLOSEST_ULL((u64)dsi_htot * dispc_pck,\n'
        '\t\t\t\t\t    byteclk);\n'
        '\telse\n'
        '\t\tdispc_htot = div64_u64((u64)dsi_htot * dispc_pck, byteclk);\n\n'
        '\t/* The stock PLL integer divides differ by 720 Hz-cycles per\n'
        '\t * 1440-pixel line. That is under 0.001 pixel per line.\n'
        '\t */\n'
        '\tline_a = (u64)dsi_htot * dispc_pck;\n'
        '\tline_b = (u64)dispc_htot * byteclk;\n'
        '\tif (line_a != line_b &&\n'
        '\t    (!stock_timing || abs_diff(line_a, line_b) > dispc_pck / 1000))\n'
        '\t\treturn false;\n')
    patch_file("drivers/gpu/drm/omapdrm/dss/dsi.c",
        '\thbp = div64_u64((u64)req_vm->hback_porch * byteclk, req_pck_nom);\n',
        '\tif (stock_timing)\n'
        '\t\thbp = DIV_ROUND_UP_ULL((u64)req_vm->hback_porch * byteclk,\n'
        '\t\t\t\t       req_pck_nom);\n'
        '\telse\n'
        '\t\thbp = div64_u64((u64)req_vm->hback_porch * byteclk, req_pck_nom);\n')
    patch_file("drivers/gpu/drm/omapdrm/dss/dsi.c",
        '\tdispc_vm = &ctx->vm;\n'
        '\t*dispc_vm = *req_vm;\n'
        '\tdispc_vm->pixelclock = dispc_pck;\n',
        '\tdispc_vm = &ctx->vm;\n'
        '\t*dispc_vm = *req_vm;\n'
        '\tdispc_vm->pixelclock = dispc_pck;\n'
        '\t/* The stock DISPC uses the panel\'s original H timings. */\n'
        '\tif (stock_timing)\n'
        '\t\treturn true;\n')
    patch_file("drivers/gpu/drm/omapdrm/dss/dsi.c",
        '\tr = FLD_MOD(r, 1, 10, 10);\t\t/* VP_HSYNC_POL */\n',
        '\t/* The working Perrier stock path leaves VP_HSYNC_POL clear. */\n'
        '\tr = FLD_MOD(r, !of_machine_is_compatible("cisco,perrier-ram"),\n'
        '\t\t\t10, 10);\t\t/* VP_HSYNC_POL */\n')
    patch_file("drivers/gpu/drm/omapdrm/dss/dsi.c",
        '\tdsi->mgr_config.io_pad_mode = DSS_IO_PAD_MODE_BYPASS;\n',
        '\t/* Perrier uses the DSI path with GP_OUT0/1 low in stock. */\n'
        '\tdsi->mgr_config.io_pad_mode =\n'
        '\t\tof_machine_is_compatible("cisco,perrier-ram") ?\n'
        '\t\tDSS_IO_PAD_MODE_RESET : DSS_IO_PAD_MODE_BYPASS;\n')
    patch_file("drivers/gpu/drm/omapdrm/dss/dsi.c",
        '\tREG_FLD_MOD(dsi, DSI_VC_CTRL(VC_VIDEO), 1, 1, 1); /* SOURCE_VP */\n'
        '\tdsi->vc[VC_VIDEO].source = DSI_VC_SOURCE_VP;\n',
        '\t/* Stock Perrier video mode leaves VC0 on L4. The mainline VP\n'
        '\t * setting leaves its transmit FIFO full on this board.\n'
        '\t */\n'
        '\tif (!of_machine_is_compatible("cisco,perrier-ram")) {\n'
        '\t\tREG_FLD_MOD(dsi, DSI_VC_CTRL(VC_VIDEO), 1, 1, 1); /* SOURCE_VP */\n'
        '\t\tdsi->vc[VC_VIDEO].source = DSI_VC_SOURCE_VP;\n'
        '\t}\n')
    patch_file("drivers/gpu/drm/omapdrm/dss/dispc.c",
        '\tbool onoff, rf, ipc, vs, hs, de;\n',
        '\tbool onoff, rf, ipc, vs, hs, de;\n'
        '\tbool perrier_dsi = channel == OMAP_DSS_CHANNEL_LCD &&\n'
        '\t\tof_machine_is_compatible("cisco,perrier-ram");\n')
    patch_file("drivers/gpu/drm/omapdrm/dss/dispc.c",
        '\tonoff = true; /* always use the \'rf\' setting */\n',
        '\t/* The stock Perrier DSI route has POL_FREQ=0. */\n'
        '\tonoff = !perrier_dsi;\n')
    patch_file("drivers/gpu/drm/omapdrm/dss/dispc.c",
        '\tif (dispc->feat->supports_sync_align)\n'
        '\t\tl |= (1 << 18);\n',
        '\tif (dispc->feat->supports_sync_align && !perrier_dsi)\n'
        '\t\tl |= (1 << 18);\n')
    call([ROOT / "development/toolchain/arm-cc", "-O2", "-static", "-o", HERE / "init", HERE / "init.c"])
    call([ROOT / "development/toolchain/arm-cc", "-O2", "-static", "-D__user=",
          "-I", SRC / "include/uapi", "-o", HERE / "kms-probe", HERE / "kms_probe.c"])
    call([ROOT / "development/toolchain/arm-cc", "-O2", "-static", "-D__user=",
          "-idirafter", SRC / "include/uapi", "-o", HERE / "kms-pattern", HERE / "kms_pattern.c"])
    call([ROOT / "development/toolchain/arm-cc", "-Os", "-static", "-o",
          HERE / "backlight-state", HERE / "stock-analysis/backlight_state.c"])
    archive = b""
    for name in ["dev", "proc", "sys", "mnt", "mnt/base", "extra", "gui", "apps"]:
        archive += cpio_entry(name, 0o040755)
    archive += cpio_entry("dev/console", 0o020600, major=5, minor=1)
    archive += cpio_entry("dev/mem", 0o020600, major=1, minor=1)
    archive += cpio_entry("init", 0o100755, (HERE / "init").read_bytes())
    archive += cpio_entry("kms-probe", 0o100755, (HERE / "kms-probe").read_bytes())
    archive += cpio_entry("kms-pattern", 0o100755, (HERE / "kms-pattern").read_bytes())
    archive += cpio_entry("backlight-state", 0o100755,
                          (HERE / "backlight-state").read_bytes())
    archive += cpio_entry("TRAILER!!!", 0)
    (HERE / "initramfs.cpio").write_bytes(archive)
    fragment = (HERE / "minimal.config").read_text()
    fragment += f'\nCONFIG_INITRAMFS_SOURCE="{HERE / "initramfs.cpio"}"\n'
    (HERE / "resolved.config").write_text(fragment)
    env = dict(os.environ, KCONFIG_ALLCONFIG=str(HERE / "resolved.config"),
               KBUILD_BUILD_USER="touch10", KBUILD_BUILD_HOST="perrier-dev",
               KBUILD_BUILD_TIMESTAMP="2026-11-08 00:00:00 UTC")
    base = ["make", "-C", SRC, f"O={OUT}", "ARCH=arm", "LLVM=1"]
    call(base + ["allnoconfig"], env=env)
    call(base + [f"-j{os.cpu_count()}", "zImage"], env=env)
    dts = HERE / "omap4-perrier-ram.dts"
    with (OUT / "perrier.preprocessed.dts").open("wb") as stream:
        call(["clang", "-E", "-P", "-x", "assembler-with-cpp", "-nostdinc", "-undef", "-D__DTS__",
              "-I", SRC / "arch/arm/boot/dts/ti/omap", "-I", SRC / "scripts/dtc/include-prefixes", dts], stdout=stream)
    call([OUT / "scripts/dtc/dtc", "-i", SRC / "arch/arm/boot/dts/ti/omap", "-I", "dts", "-O", "dtb", "-o", OUT / "omap4-perrier-ram.dtb", OUT / "perrier.preprocessed.dts"])
    call([OUT / "scripts/dtc/dtc", "-I", "dtb", "-O", "dts", "-o", OUT / "compiled.dts", OUT / "omap4-perrier-ram.dtb"])
    files = [OUT / "arch/arm/boot/zImage", OUT / "vmlinux", OUT / "System.map", OUT / ".config",
             OUT / "omap4-perrier-ram.dtb", HERE / "initramfs.cpio", HERE / "init", HERE / "kms-probe", HERE / "kms-pattern", HERE / "backlight-state"]
    record = {"kernel": "6.18.48-perrier-ram33", "source_sha256": "5ebdadb10a4b5708fc6b1c457764a110bc49f8150cc3502c59b921ead8c6fc8c",
              "source_signature_key": "647F28654894E3BD457199BE38DBBDC86092693E", "files": {}}
    for path in files:
        record["files"][str(path.relative_to(ROOT))] = {"size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (HERE / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))

if __name__ == "__main__":
    main()
