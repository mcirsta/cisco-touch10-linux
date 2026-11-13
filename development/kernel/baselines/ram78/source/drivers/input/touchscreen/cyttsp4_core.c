// SPDX-License-Identifier: GPL-2.0-only
/*
 * cyttsp4_core.c
 * Cypress TrueTouch(TM) Standard Product V4 Core driver module.
 * For use with Cypress Txx4xx parts.
 * Supported parts include:
 * TMA4XX
 * TMA1036
 *
 * Copyright (C) 2012 Cypress Semiconductor
 *
 * DT/regulator/GPIO and Perrier report-profile port for Linux 6.18.
 *
 * Contact Cypress Semiconductor at www.cypress.com <ttdrivers@cypress.com>
 */

#include "cyttsp4_core.h"
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/regulator/consumer.h>
#include <linux/input/mt.h>
#include <linux/interrupt.h>
#include <linux/pm_runtime.h>
#include <linux/sched.h>
#include <linux/slab.h>

/* Timeout in ms. */
#define CY_CORE_REQUEST_EXCLUSIVE_TIMEOUT	500
#define CY_CORE_SLEEP_REQUEST_EXCLUSIVE_TIMEOUT	5000
#define CY_CORE_MODE_CHANGE_TIMEOUT		1000
#define CY_CORE_RESET_AND_WAIT_TIMEOUT		500
#define CY_CORE_SYSINFO_TIMEOUT			10000
#define CY_CORE_WAKEUP_TIMEOUT			500

#define CY_CORE_STARTUP_RETRY_COUNT		3

static const char * const cyttsp4_tch_abs_string[] = {
	[CY_TCH_X]	= "X",
	[CY_TCH_Y]	= "Y",
	[CY_TCH_P]	= "P",
	[CY_TCH_T]	= "T",
	[CY_TCH_E]	= "E",
	[CY_TCH_O]	= "O",
	[CY_TCH_W]	= "W",
	[CY_TCH_MAJ]	= "MAJ",
	[CY_TCH_MIN]	= "MIN",
	[CY_TCH_OR]	= "OR",
	[CY_TCH_NUM_ABS] = "INVALID"
};


static const u8 ldr_err_app[] = {
	0x01, 0x02, 0x00, 0x00, 0x55, 0xDD, 0x17
};

static inline size_t merge_bytes(u8 high, u8 low)
{
	return (high << 8) + low;
}

#ifdef VERBOSE_DEBUG
static void cyttsp4_pr_buf(struct device *dev, u8 *pr_buf, u8 *dptr, int size,
		const char *data_name)
{
	int i, k;
	static const char fmt[] = "%02X ";
	int max;

	if (!size)
		return;

	max = (CY_MAX_PRBUF_SIZE - 1) - sizeof(CY_PR_TRUNCATED);

	pr_buf[0] = 0;
	for (i = k = 0; i < size && k < max; i++, k += 3)
		scnprintf(pr_buf + k, CY_MAX_PRBUF_SIZE, fmt, dptr[i]);

	dev_vdbg(dev, "%s:  %s[0..%d]=%s%s\n", __func__, data_name, size - 1,
			pr_buf, size <= max ? "" : CY_PR_TRUNCATED);
}
#else
#define cyttsp4_pr_buf(...) do { } while (0)
#endif

static int cyttsp4_load_status_regs(struct cyttsp4 *cd)
{
	struct cyttsp4_sysinfo *si = &cd->sysinfo;
	struct device *dev = cd->dev;
	int rc;

	rc = cyttsp4_adap_read(cd, CY_REG_BASE, si->si_ofs.mode_size,
			si->xy_mode);
	if (rc < 0)
		dev_err(dev, "%s: fail read mode regs r=%d\n",
			__func__, rc);
	else
		cyttsp4_pr_buf(dev, cd->pr_buf, si->xy_mode,
			si->si_ofs.mode_size, "xy_mode");

	return rc;
}

static int cyttsp4_handshake(struct cyttsp4 *cd, u8 mode)
{
	u8 cmd = mode ^ CY_HST_TOGGLE;
	int rc;

	/*
	 * Mode change issued, handshaking now will cause endless mode change
	 * requests, for sync mode modechange will do same with handshake
	 */
	if (mode & CY_HST_MODE_CHANGE)
		return 0;

	rc = cyttsp4_adap_write(cd, CY_REG_BASE, sizeof(cmd), &cmd);
	if (rc < 0)
		dev_err(cd->dev, "%s: bus write fail on handshake (ret=%d)\n",
				__func__, rc);

	return rc;
}


static int cyttsp4_hw_hard_reset(struct cyttsp4 *cd)
{
	/* Perrier stock cyttsp4_hw_reset: physical high 20 / low 40 / high 20 ms. */
	cd->in_bootloader = true;
	gpiod_set_value_cansleep(cd->reset_gpio, 0);
	msleep(20);
	gpiod_set_value_cansleep(cd->reset_gpio, 1);
	msleep(40);
	gpiod_set_value_cansleep(cd->reset_gpio, 0);
	msleep(20);
	return 0;
}


/*
 * Gets number of bits for a touch filed as parameter,
 * sets maximum value for field which is used as bit mask
 * and returns number of bytes required for that field
 */
static int cyttsp4_bits_2_bytes(unsigned int nbits, size_t *max)
{
	*max = 1UL << nbits;
	return (nbits + 7) / 8;
}

static int cyttsp4_si_data_offsets(struct cyttsp4 *cd)
{
	struct cyttsp4_sysinfo *si = &cd->sysinfo;
	int rc = cyttsp4_adap_read(cd, CY_REG_BASE, sizeof(si->si_data),
			&si->si_data);
	if (rc < 0) {
		dev_err(cd->dev, "%s: fail read sysinfo data offsets r=%d\n",
			__func__, rc);
		return rc;
	}

	/* Print sysinfo data offsets */
	cyttsp4_pr_buf(cd->dev, cd->pr_buf, (u8 *)&si->si_data,
		       sizeof(si->si_data), "sysinfo_data_offsets");

	/* convert sysinfo data offset bytes into integers */

	si->si_ofs.map_sz = merge_bytes(si->si_data.map_szh,
			si->si_data.map_szl);
	si->si_ofs.cydata_ofs = merge_bytes(si->si_data.cydata_ofsh,
			si->si_data.cydata_ofsl);
	si->si_ofs.test_ofs = merge_bytes(si->si_data.test_ofsh,
			si->si_data.test_ofsl);
	si->si_ofs.pcfg_ofs = merge_bytes(si->si_data.pcfg_ofsh,
			si->si_data.pcfg_ofsl);
	si->si_ofs.opcfg_ofs = merge_bytes(si->si_data.opcfg_ofsh,
			si->si_data.opcfg_ofsl);
	si->si_ofs.ddata_ofs = merge_bytes(si->si_data.ddata_ofsh,
			si->si_data.ddata_ofsl);
	si->si_ofs.mdata_ofs = merge_bytes(si->si_data.mdata_ofsh,
			si->si_data.mdata_ofsl);
	if ((si->si_data.hst_mode & ~CY_HST_TOGGLE) != CY_HST_SYSINFO ||
	    si->si_ofs.map_sz > 256 ||
	    si->si_ofs.cydata_ofs < sizeof(si->si_data) ||
	    si->si_ofs.test_ofs < si->si_ofs.cydata_ofs + sizeof(struct cyttsp4_cydata) ||
	    si->si_ofs.pcfg_ofs < si->si_ofs.test_ofs + sizeof(struct cyttsp4_test) ||
	    si->si_ofs.opcfg_ofs < si->si_ofs.pcfg_ofs + 12 ||
	    si->si_ofs.ddata_ofs < si->si_ofs.opcfg_ofs + 23 ||
	    si->si_ofs.mdata_ofs < si->si_ofs.ddata_ofs ||
	    si->si_ofs.map_sz < si->si_ofs.mdata_ofs)
		return -EPROTO;
	return rc;
}

static int cyttsp4_si_get_cydata(struct cyttsp4 *cd)
{
	struct cyttsp4_sysinfo *si = &cd->sysinfo;
	int read_offset;
	int mfgid_sz, calc_mfgid_sz;
	void *p;
	int rc;

	if (si->si_ofs.test_ofs <= si->si_ofs.cydata_ofs) {
		dev_err(cd->dev,
			"%s: invalid offset test_ofs: %zu, cydata_ofs: %zu\n",
			__func__, si->si_ofs.test_ofs, si->si_ofs.cydata_ofs);
		return -EINVAL;
	}

	si->si_ofs.cydata_size = si->si_ofs.test_ofs - si->si_ofs.cydata_ofs;
	dev_dbg(cd->dev, "%s: cydata size: %zd\n", __func__,
			si->si_ofs.cydata_size);

	p = krealloc(si->si_ptrs.cydata, si->si_ofs.cydata_size, GFP_KERNEL);
	if (p == NULL) {
		dev_err(cd->dev, "%s: failed to allocate cydata memory\n",
			__func__);
		return -ENOMEM;
	}
	si->si_ptrs.cydata = p;

	read_offset = si->si_ofs.cydata_ofs;

	/* Read the CYDA registers up to MFGID field */
	rc = cyttsp4_adap_read(cd, read_offset,
			offsetof(struct cyttsp4_cydata, mfgid_sz)
				+ sizeof(si->si_ptrs.cydata->mfgid_sz),
			si->si_ptrs.cydata);
	if (rc < 0) {
		dev_err(cd->dev, "%s: fail read cydata r=%d\n",
			__func__, rc);
		return rc;
	}

	/* Check MFGID size */
	mfgid_sz = si->si_ptrs.cydata->mfgid_sz;
	calc_mfgid_sz = si->si_ofs.cydata_size - sizeof(struct cyttsp4_cydata);
	if (mfgid_sz != calc_mfgid_sz) {
		dev_err(cd->dev, "%s: mismatch in MFGID size, reported:%d calculated:%d\n",
			__func__, mfgid_sz, calc_mfgid_sz);
		return -EINVAL;
	}

	read_offset += offsetof(struct cyttsp4_cydata, mfgid_sz)
			+ sizeof(si->si_ptrs.cydata->mfgid_sz);

	/* Read the CYDA registers for MFGID field */
	rc = cyttsp4_adap_read(cd, read_offset, si->si_ptrs.cydata->mfgid_sz,
			si->si_ptrs.cydata->mfg_id);
	if (rc < 0) {
		dev_err(cd->dev, "%s: fail read cydata r=%d\n",
			__func__, rc);
		return rc;
	}

	read_offset += si->si_ptrs.cydata->mfgid_sz;

	/* Read the rest of the CYDA registers */
	rc = cyttsp4_adap_read(cd, read_offset,
			sizeof(struct cyttsp4_cydata)
				- offsetof(struct cyttsp4_cydata, cyito_idh),
			&si->si_ptrs.cydata->cyito_idh);
	if (rc < 0) {
		dev_err(cd->dev, "%s: fail read cydata r=%d\n",
			__func__, rc);
		return rc;
	}

	cyttsp4_pr_buf(cd->dev, cd->pr_buf, (u8 *)si->si_ptrs.cydata,
		si->si_ofs.cydata_size, "sysinfo_cydata");
	return rc;
}

static int cyttsp4_si_get_test_data(struct cyttsp4 *cd)
{
	struct cyttsp4_sysinfo *si = &cd->sysinfo;
	void *p;
	int rc;

	si->si_ofs.test_size = si->si_ofs.pcfg_ofs - si->si_ofs.test_ofs;
	p = krealloc(si->si_ptrs.test, si->si_ofs.test_size, GFP_KERNEL);
	if (!p)
		return -ENOMEM;
	si->si_ptrs.test = p;
	rc = cyttsp4_adap_read(cd, si->si_ofs.test_ofs, si->si_ofs.test_size, p);
	/* The old Perrier firmware's captured block is all zero. Do not apply
	 * the later Gen4 POST bit meanings and print false scanning/CRC failures.
	 */
	if (!rc)
		dev_dbg(cd->dev, "Perrier Gen4 test block: %*ph\n", (int)si->si_ofs.test_size, p);
	return rc;
}

static int cyttsp4_si_get_pcfg_data(struct cyttsp4 *cd)
{
	struct cyttsp4_sysinfo *si = &cd->sysinfo;
	void *p;
	int rc;

	if (si->si_ofs.opcfg_ofs <= si->si_ofs.pcfg_ofs) {
		dev_err(cd->dev,
			"%s: invalid offset opcfg_ofs: %zu, pcfg_ofs: %zu\n",
			__func__, si->si_ofs.opcfg_ofs, si->si_ofs.pcfg_ofs);
		return -EINVAL;
	}

	si->si_ofs.pcfg_size = si->si_ofs.opcfg_ofs - si->si_ofs.pcfg_ofs;

	p = krealloc(si->si_ptrs.pcfg, si->si_ofs.pcfg_size, GFP_KERNEL);
	if (p == NULL) {
		dev_err(cd->dev, "%s: failed to allocate pcfg memory\n",
			__func__);
		return -ENOMEM;
	}
	si->si_ptrs.pcfg = p;

	rc = cyttsp4_adap_read(cd, si->si_ofs.pcfg_ofs, si->si_ofs.pcfg_size,
			si->si_ptrs.pcfg);
	if (rc < 0) {
		dev_err(cd->dev, "%s: fail read pcfg data r=%d\n",
			__func__, rc);
		return rc;
	}

	si->si_ofs.max_x = merge_bytes((si->si_ptrs.pcfg->res_xh
			& CY_PCFG_RESOLUTION_X_MASK), si->si_ptrs.pcfg->res_xl);
	si->si_ofs.x_origin = !!(si->si_ptrs.pcfg->res_xh
			& CY_PCFG_ORIGIN_X_MASK);
	si->si_ofs.max_y = merge_bytes((si->si_ptrs.pcfg->res_yh
			& CY_PCFG_RESOLUTION_Y_MASK), si->si_ptrs.pcfg->res_yl);
	si->si_ofs.y_origin = !!(si->si_ptrs.pcfg->res_yh
			& CY_PCFG_ORIGIN_Y_MASK);
	si->si_ofs.max_p = merge_bytes(si->si_ptrs.pcfg->max_zh,
			si->si_ptrs.pcfg->max_zl);

	cyttsp4_pr_buf(cd->dev, cd->pr_buf,
		       (u8 *)si->si_ptrs.pcfg,
		       si->si_ofs.pcfg_size, "sysinfo_pcfg_data");
	return rc;
}

static int cyttsp4_si_get_opcfg_data(struct cyttsp4 *cd)
{
	struct cyttsp4_sysinfo *si = &cd->sysinfo;
	struct cyttsp4_opcfg *op;
	unsigned int field;
	int rc;

	si->si_ofs.opcfg_size = si->si_ofs.ddata_ofs - si->si_ofs.opcfg_ofs;
	/* Old Perrier firmware has only the 23-byte base descriptor. */
	op = kzalloc(sizeof(*op), GFP_KERNEL);
	if (!op)
		return -ENOMEM;
	if (si->si_ofs.opcfg_size < 23 || si->si_ofs.opcfg_size > sizeof(*op)) {
		kfree(op);
		return -EPROTO;
	}
	rc = cyttsp4_adap_read(cd, si->si_ofs.opcfg_ofs, si->si_ofs.opcfg_size, op);
	if (rc) {
		kfree(op);
		return rc;
	}
	kfree(si->si_ptrs.opcfg);
	si->si_ptrs.opcfg = op;
	si->si_ofs.cmd_ofs = op->cmd_ofs;
	si->si_ofs.rep_ofs = op->rep_ofs;
	si->si_ofs.rep_sz = merge_bytes(op->rep_szh, op->rep_szl);
	si->si_ofs.num_btns = op->num_btns;
	si->si_ofs.tt_stat_ofs = op->tt_stat_ofs;
	si->si_ofs.obj_cfg0 = op->obj_cfg0;
	si->si_ofs.max_tchs = op->max_tchs & CY_BYTE_OFS_MASK;
	si->si_ofs.tch_rec_size = op->tch_rec_size & CY_BYTE_OFS_MASK;
	si->si_ofs.mode_size = si->si_ofs.tt_stat_ofs + 1;
	si->si_ofs.data_size = si->si_ofs.max_tchs * si->si_ofs.tch_rec_size;
	/* This DT match covers the measured older Perrier firmware profile. */
	if (!si->si_ofs.max_tchs || si->si_ofs.max_tchs > 10 ||
	    si->si_ofs.tch_rec_size != 7 || op->num_btns ||
	    si->si_ofs.rep_ofs < 1 ||
	    si->si_ofs.tt_stat_ofs != si->si_ofs.rep_ofs + 2 ||
	    si->si_ofs.mode_size + si->si_ofs.data_size > 256 ||
	    si->si_ofs.rep_sz != 3 + si->si_ofs.data_size)
		return -EPROTO;
	memset(si->si_ofs.tch_abs, 0, sizeof(si->si_ofs.tch_abs));
	for (field = 0; field < CY_NUM_TCH_FIELDS; field++) {
		struct cyttsp4_tch_abs_params *tch = &si->si_ofs.tch_abs[field];
		const struct cyttsp4_tch_rec_params *rec = &op->tch_rec_old[field];
		unsigned int bits = rec->size;

		tch->ofs = rec->loc & CY_BYTE_OFS_MASK;
		tch->bofs = rec->loc >> CY_BOFS_SHIFT;
		if (bits > 16)
			return -EPROTO;
		tch->size = cyttsp4_bits_2_bytes(bits, &tch->max);
		if (tch->ofs + tch->size > si->si_ofs.tch_rec_size ||
		    (tch->size > 1 && tch->bofs) ||
		    (tch->size == 1 && bits + tch->bofs > 8))
			return -EPROTO;
	}
	if (si->si_ofs.tch_abs[CY_TCH_T].max > 32 ||
	    !si->si_ofs.tch_abs[CY_TCH_T].size ||
	    !si->si_ofs.tch_abs[CY_TCH_X].size ||
	    !si->si_ofs.tch_abs[CY_TCH_Y].size ||
	    si->si_ofs.tch_abs[CY_TCH_E].max != 4)
		return -EPROTO;
	return 0;
}

static int cyttsp4_si_get_ddata(struct cyttsp4 *cd)
{
	struct cyttsp4_sysinfo *si = &cd->sysinfo;
	void *p;
	int rc;

	si->si_ofs.ddata_size = si->si_ofs.mdata_ofs - si->si_ofs.ddata_ofs;

	p = krealloc(si->si_ptrs.ddata, si->si_ofs.ddata_size, GFP_KERNEL);
	if (p == NULL) {
		dev_err(cd->dev, "%s: fail alloc ddata memory\n", __func__);
		return -ENOMEM;
	}
	si->si_ptrs.ddata = p;

	rc = cyttsp4_adap_read(cd, si->si_ofs.ddata_ofs, si->si_ofs.ddata_size,
			si->si_ptrs.ddata);
	if (rc < 0)
		dev_err(cd->dev, "%s: fail read ddata data r=%d\n",
			__func__, rc);
	else
		cyttsp4_pr_buf(cd->dev, cd->pr_buf,
			       (u8 *)si->si_ptrs.ddata,
			       si->si_ofs.ddata_size, "sysinfo_ddata");
	return rc;
}

static int cyttsp4_si_get_mdata(struct cyttsp4 *cd)
{
	struct cyttsp4_sysinfo *si = &cd->sysinfo;
	void *p;
	int rc;

	si->si_ofs.mdata_size = si->si_ofs.map_sz - si->si_ofs.mdata_ofs;

	p = krealloc(si->si_ptrs.mdata, si->si_ofs.mdata_size, GFP_KERNEL);
	if (p == NULL) {
		dev_err(cd->dev, "%s: fail alloc mdata memory\n", __func__);
		return -ENOMEM;
	}
	si->si_ptrs.mdata = p;

	rc = cyttsp4_adap_read(cd, si->si_ofs.mdata_ofs, si->si_ofs.mdata_size,
			si->si_ptrs.mdata);
	if (rc < 0)
		dev_err(cd->dev, "%s: fail read mdata data r=%d\n",
			__func__, rc);
	else
		cyttsp4_pr_buf(cd->dev, cd->pr_buf,
			       (u8 *)si->si_ptrs.mdata,
			       si->si_ofs.mdata_size, "sysinfo_mdata");
	return rc;
}

static int cyttsp4_si_get_btn_data(struct cyttsp4 *cd)
{
	/* Perrier's three front keys use the OMAP keypad, not CYTTSP4 buttons. */
	return cd->sysinfo.si_ofs.num_btns ? -EOPNOTSUPP : 0;
}

static int cyttsp4_si_get_op_data_ptrs(struct cyttsp4 *cd)
{
	struct cyttsp4_sysinfo *si = &cd->sysinfo;
	void *p;

	p = krealloc(si->xy_mode, si->si_ofs.mode_size, GFP_KERNEL|__GFP_ZERO);
	if (p == NULL)
		return -ENOMEM;
	si->xy_mode = p;

	p = krealloc(si->xy_data, si->si_ofs.data_size, GFP_KERNEL|__GFP_ZERO);
	if (p == NULL)
		return -ENOMEM;
	si->xy_data = p;

	p = krealloc(si->btn_rec_data,
			si->si_ofs.btn_rec_size * si->si_ofs.num_btns,
			GFP_KERNEL|__GFP_ZERO);
	if (p == NULL)
		return -ENOMEM;
	si->btn_rec_data = p;

	return 0;
}

static void cyttsp4_si_put_log_data(struct cyttsp4 *cd)
{
	struct cyttsp4_sysinfo *si = &cd->sysinfo;

	dev_dbg(cd->dev, "%s: cydata_ofs =%4zd siz=%4zd\n", __func__,
		si->si_ofs.cydata_ofs, si->si_ofs.cydata_size);
	dev_dbg(cd->dev, "%s: test_ofs   =%4zd siz=%4zd\n", __func__,
		si->si_ofs.test_ofs, si->si_ofs.test_size);
	dev_dbg(cd->dev, "%s: pcfg_ofs   =%4zd siz=%4zd\n", __func__,
		si->si_ofs.pcfg_ofs, si->si_ofs.pcfg_size);
	dev_dbg(cd->dev, "%s: opcfg_ofs  =%4zd siz=%4zd\n", __func__,
		si->si_ofs.opcfg_ofs, si->si_ofs.opcfg_size);
	dev_dbg(cd->dev, "%s: ddata_ofs  =%4zd siz=%4zd\n", __func__,
		si->si_ofs.ddata_ofs, si->si_ofs.ddata_size);
	dev_dbg(cd->dev, "%s: mdata_ofs  =%4zd siz=%4zd\n", __func__,
		si->si_ofs.mdata_ofs, si->si_ofs.mdata_size);

	dev_dbg(cd->dev, "%s: cmd_ofs       =%4zd\n", __func__,
		si->si_ofs.cmd_ofs);
	dev_dbg(cd->dev, "%s: rep_ofs       =%4zd\n", __func__,
		si->si_ofs.rep_ofs);
	dev_dbg(cd->dev, "%s: rep_sz        =%4zd\n", __func__,
		si->si_ofs.rep_sz);
	dev_dbg(cd->dev, "%s: num_btns      =%4zd\n", __func__,
		si->si_ofs.num_btns);
	dev_dbg(cd->dev, "%s: num_btn_regs  =%4zd\n", __func__,
		si->si_ofs.num_btn_regs);
	dev_dbg(cd->dev, "%s: tt_stat_ofs   =%4zd\n", __func__,
		si->si_ofs.tt_stat_ofs);
	dev_dbg(cd->dev, "%s: tch_rec_size  =%4zd\n", __func__,
		si->si_ofs.tch_rec_size);
	dev_dbg(cd->dev, "%s: max_tchs      =%4zd\n", __func__,
		si->si_ofs.max_tchs);
	dev_dbg(cd->dev, "%s: mode_size     =%4zd\n", __func__,
		si->si_ofs.mode_size);
	dev_dbg(cd->dev, "%s: data_size     =%4zd\n", __func__,
		si->si_ofs.data_size);
	dev_dbg(cd->dev, "%s: map_sz        =%4zd\n", __func__,
		si->si_ofs.map_sz);

	dev_dbg(cd->dev, "%s: btn_rec_size   =%2zd\n", __func__,
		si->si_ofs.btn_rec_size);
	dev_dbg(cd->dev, "%s: btn_diff_ofs   =%2zd\n", __func__,
		si->si_ofs.btn_diff_ofs);
	dev_dbg(cd->dev, "%s: btn_diff_size  =%2zd\n", __func__,
		si->si_ofs.btn_diff_size);

	dev_dbg(cd->dev, "%s: max_x    = 0x%04zX (%zd)\n", __func__,
		si->si_ofs.max_x, si->si_ofs.max_x);
	dev_dbg(cd->dev, "%s: x_origin = %zd (%s)\n", __func__,
		si->si_ofs.x_origin,
		si->si_ofs.x_origin == CY_NORMAL_ORIGIN ?
		"left corner" : "right corner");
	dev_dbg(cd->dev, "%s: max_y    = 0x%04zX (%zd)\n", __func__,
		si->si_ofs.max_y, si->si_ofs.max_y);
	dev_dbg(cd->dev, "%s: y_origin = %zd (%s)\n", __func__,
		si->si_ofs.y_origin,
		si->si_ofs.y_origin == CY_NORMAL_ORIGIN ?
		"upper corner" : "lower corner");
	dev_dbg(cd->dev, "%s: max_p    = 0x%04zX (%zd)\n", __func__,
		si->si_ofs.max_p, si->si_ofs.max_p);

	dev_dbg(cd->dev, "%s: xy_mode=%p xy_data=%p\n", __func__,
		si->xy_mode, si->xy_data);
}

static int cyttsp4_get_sysinfo_regs(struct cyttsp4 *cd)
{
	struct cyttsp4_sysinfo *si = &cd->sysinfo;
	int rc;

	rc = cyttsp4_si_data_offsets(cd);
	if (rc < 0)
		return rc;

	rc = cyttsp4_si_get_cydata(cd);
	if (rc < 0)
		return rc;

	rc = cyttsp4_si_get_test_data(cd);
	if (rc < 0)
		return rc;

	rc = cyttsp4_si_get_pcfg_data(cd);
	if (rc < 0)
		return rc;

	rc = cyttsp4_si_get_opcfg_data(cd);
	if (rc < 0)
		return rc;

	rc = cyttsp4_si_get_ddata(cd);
	if (rc < 0)
		return rc;

	rc = cyttsp4_si_get_mdata(cd);
	if (rc < 0)
		return rc;

	rc = cyttsp4_si_get_btn_data(cd);
	if (rc < 0)
		return rc;

	rc = cyttsp4_si_get_op_data_ptrs(cd);
	if (rc < 0) {
		dev_err(cd->dev, "%s: failed to get_op_data\n",
			__func__);
		return rc;
	}

	cyttsp4_si_put_log_data(cd);

	/* provide flow control handshake */
	rc = cyttsp4_handshake(cd, si->si_data.hst_mode);
	if (rc < 0)
		dev_err(cd->dev, "%s: handshake fail on sysinfo reg\n",
			__func__);

	si->ready = true;
	return rc;
}

static void cyttsp4_queue_startup_(struct cyttsp4 *cd)
{
	if (!cd->stopping && cd->startup_state == STARTUP_NONE) {
		cd->startup_state = STARTUP_QUEUED;
		schedule_work(&cd->startup_work);
		dev_dbg(cd->dev, "%s: cyttsp4_startup queued\n", __func__);
	} else {
		dev_dbg(cd->dev, "%s: startup_state = %d\n", __func__,
			cd->startup_state);
	}
}



static void cyttsp4_lift_all(struct cyttsp4_mt_data *md)
{
	if (!md->input)
		return;
	input_mt_sync_frame(md->input);
	input_sync(md->input);
	md->num_prv_tch = 0;
}

static void cyttsp4_get_touch_axis(struct cyttsp4_mt_data *md,
	int *axis, int size, int max, u8 *xy_data, int bofs)
{
	int i;

	for (i = 0, *axis = 0; i < size; i++)
		*axis = (*axis << 8) | (xy_data[i] >> bofs);
	*axis &= max - 1;
}

static void cyttsp4_get_touch(struct cyttsp4_mt_data *md,
	struct cyttsp4_touch *touch, u8 *xy_data)
{
	struct cyttsp4_sysinfo *si = md->si;
	enum cyttsp4_tch_abs abs;

	for (abs = CY_TCH_X; abs < CY_TCH_NUM_ABS; abs++)
		cyttsp4_get_touch_axis(md, &touch->abs[abs],
			si->si_ofs.tch_abs[abs].size, si->si_ofs.tch_abs[abs].max,
			xy_data + si->si_ofs.tch_abs[abs].ofs,
			si->si_ofs.tch_abs[abs].bofs);
}



static void cyttsp4_get_mt_touches(struct cyttsp4_mt_data *md, int count)
{
	struct cyttsp4_touch touches[10];
	struct cyttsp4_sysinfo *si = md->si;
	u32 ids = 0;
	int i, slot;

	/* Validate a complete frame before publishing any contacts. */
	for (i = 0; i < count; i++) {
		struct cyttsp4_touch *t = &touches[i];
		unsigned int id;

		cyttsp4_get_touch(md, t, si->xy_data + i * si->si_ofs.tch_rec_size);
		id = t->abs[CY_TCH_T];
		if (id >= si->si_ofs.tch_abs[CY_TCH_T].max || id >= 32 ||
		    (ids & BIT(id)) || t->abs[CY_TCH_O])
			goto invalid;
		ids |= BIT(id);
		if (t->abs[CY_TCH_E] != CY_EV_LIFTOFF &&
		    (t->abs[CY_TCH_X] >= si->si_ofs.max_x ||
		     t->abs[CY_TCH_Y] >= si->si_ofs.max_y))
			goto invalid;
	}
	for (i = 0; i < count; i++) {
		struct cyttsp4_touch *t = &touches[i];

		if (t->abs[CY_TCH_E] == CY_EV_LIFTOFF)
			continue;
		slot = input_mt_get_slot_by_key(md->input, t->abs[CY_TCH_T]);
		if (slot < 0)
			continue;
		input_mt_slot(md->input, slot);
		input_mt_report_slot_state(md->input, MT_TOOL_FINGER, true);
		touchscreen_report_pos(md->input, &md->prop,
				       t->abs[CY_TCH_X], t->abs[CY_TCH_Y], true);
		input_report_abs(md->input, ABS_MT_PRESSURE, t->abs[CY_TCH_P]);
		input_report_abs(md->input, ABS_MT_TOUCH_MAJOR, t->abs[CY_TCH_W]);
	}
	input_mt_sync_frame(md->input);
	input_sync(md->input);
	md->num_prv_tch = count;
	return;
invalid:
	dev_warn_ratelimited(&md->input->dev, "invalid Gen4 contact frame\n");
	cyttsp4_lift_all(md);
}

/* read xy_data for all current touches */
static int cyttsp4_xy_worker(struct cyttsp4 *cd)
{
	struct cyttsp4_mt_data *md = &cd->md;
	struct device *dev = &md->input->dev;
	struct cyttsp4_sysinfo *si = md->si;
	u8 num_cur_tch;
	u8 hst_mode;
	u8 rep_len;
	u8 rep_stat;
	u8 tt_stat;
	int rc = 0;

	/*
	 * Get event data from cyttsp4 device.
	 * The event data includes all data
	 * for all active touches.
	 * Event data also includes button data
	 */
	/*
	 * Use 2 reads:
	 * 1st read to get mode + button bytes + touch count (core)
	 * 2nd read (optional) to get touch 1 - touch n data
	 */
	hst_mode = si->xy_mode[CY_REG_BASE];
	rep_len = si->xy_mode[si->si_ofs.rep_ofs];
	rep_stat = si->xy_mode[si->si_ofs.rep_ofs + 1];
	tt_stat = si->xy_mode[si->si_ofs.tt_stat_ofs];
	dev_vdbg(dev, "%s: %s%02X %s%d %s%02X %s%02X\n", __func__,
		"hst_mode=", hst_mode, "rep_len=", rep_len,
		"rep_stat=", rep_stat, "tt_stat=", tt_stat);

	num_cur_tch = GET_NUM_TOUCHES(tt_stat);
	dev_vdbg(dev, "%s: num_cur_tch=%d\n", __func__, num_cur_tch);

	if (rep_len == 0 && num_cur_tch > 0) {
		dev_err(dev, "%s: report length error rep_len=%d num_tch=%d\n",
			__func__, rep_len, num_cur_tch);
		goto cyttsp4_xy_worker_exit;
	}

	if (num_cur_tch > si->si_ofs.max_tchs ||
	    num_cur_tch > 10 || rep_len != 2 + num_cur_tch * si->si_ofs.tch_rec_size ||
	    IS_BAD_PKT(rep_stat) || IS_LARGE_AREA(tt_stat)) {
		cyttsp4_lift_all(md);
		return -EPROTO;
	}

	/* read touches */
	if (num_cur_tch > 0) {
		rc = cyttsp4_adap_read(cd, si->si_ofs.tt_stat_ofs + 1,
				num_cur_tch * si->si_ofs.tch_rec_size,
				si->xy_data);
		if (rc < 0) {
			dev_err(dev, "%s: read fail on touch regs r=%d\n",
				__func__, rc);
			goto cyttsp4_xy_worker_exit;
		}
	}

	/* print xy data */
	cyttsp4_pr_buf(dev, cd->pr_buf, si->xy_data, num_cur_tch *
		si->si_ofs.tch_rec_size, "xy_data");

	/* check any error conditions */
	if (IS_BAD_PKT(rep_stat)) {
		dev_dbg(dev, "%s: Invalid buffer detected\n", __func__);
		rc = 0;
		goto cyttsp4_xy_worker_exit;
	}

	if (IS_LARGE_AREA(tt_stat))
		dev_dbg(dev, "%s: Large area detected\n", __func__);

	if (num_cur_tch > si->si_ofs.max_tchs) {
		dev_err(dev, "%s: too many tch; set to max tch (n=%d c=%zd)\n",
				__func__, num_cur_tch, si->si_ofs.max_tchs);
		num_cur_tch = si->si_ofs.max_tchs;
	}

	/* extract xy_data for all currently reported touches */
	dev_vdbg(dev, "%s: extract data num_cur_tch=%d\n", __func__,
		num_cur_tch);
	if (num_cur_tch)
		cyttsp4_get_mt_touches(md, num_cur_tch);
	else
		cyttsp4_lift_all(md);

	rc = 0;

cyttsp4_xy_worker_exit:
	return rc;
}

static int cyttsp4_mt_attention(struct cyttsp4 *cd)
{
	struct device *dev = cd->dev;
	struct cyttsp4_mt_data *md = &cd->md;
	int rc = 0;

	if (!md->si)
		return 0;

	mutex_lock(&md->report_lock);
	if (!md->is_suspended) {
		/* core handles handshake */
		rc = cyttsp4_xy_worker(cd);
	} else {
		dev_vdbg(dev, "%s: Ignoring report while suspended\n",
			__func__);
	}
	mutex_unlock(&md->report_lock);
	if (rc < 0)
		dev_err(dev, "%s: xy_worker error r=%d\n", __func__, rc);

	return rc;
}

static irqreturn_t cyttsp4_irq(int irq, void *handle)
{
	struct cyttsp4 *cd = handle;
	struct device *dev = cd->dev;
	enum cyttsp4_mode cur_mode;
	u8 cmd_ofs = cd->sysinfo.si_ofs.cmd_ofs;
	u8 mode[3];
	int rc;

	/*
	 * Check whether this IRQ should be ignored (external)
	 * This should be the very first thing to check since
	 * ignore_irq may be set for a very short period of time
	 */
	if (atomic_read(&cd->ignore_irq)) {
		dev_vdbg(dev, "%s: Ignoring IRQ\n", __func__);
		return IRQ_HANDLED;
	}

	dev_dbg(dev, "%s int:0x%x\n", __func__, cd->int_status);

	mutex_lock(&cd->system_lock);

	/* Just to debug */
	if (cd->sleep_state == SS_SLEEP_ON || cd->sleep_state == SS_SLEEPING)
		dev_vdbg(dev, "%s: Received IRQ while in sleep\n", __func__);

	rc = cyttsp4_adap_read(cd, CY_REG_BASE, sizeof(mode), mode);
	if (rc) {
		dev_err(cd->dev, "%s: Fail read adapter r=%d\n", __func__, rc);
		goto cyttsp4_irq_exit;
	}
	dev_vdbg(dev, "%s mode[0-2]:0x%X 0x%X 0x%X\n", __func__,
			mode[0], mode[1], mode[2]);

	if (IS_BOOTLOADER(mode[0], mode[1])) {
		cur_mode = CY_MODE_BOOTLOADER;
		dev_vdbg(dev, "%s: bl running\n", __func__);
		if (cd->mode == CY_MODE_BOOTLOADER) {
			/* Signal bootloader heartbeat heard */
			wake_up(&cd->wait_q);
			goto cyttsp4_irq_exit;
		}

		/* switch to bootloader */
		dev_dbg(dev, "%s: restart switch to bl m=%d -> m=%d\n",
			__func__, cd->mode, cur_mode);

		/* catch operation->bl glitch */
		if (cd->mode != CY_MODE_UNKNOWN) {
			/* Incase startup_state do not let startup_() */
			cd->mode = CY_MODE_UNKNOWN;
			cyttsp4_queue_startup_(cd);
			goto cyttsp4_irq_exit;
		}

		/*
		 * do not wake thread on this switch since
		 * it is possible to get an early heartbeat
		 * prior to performing the reset
		 */
		cd->mode = cur_mode;

		goto cyttsp4_irq_exit;
	}

	switch (mode[0] & CY_HST_MODE) {
	case CY_HST_OPERATE:
		cur_mode = CY_MODE_OPERATIONAL;
		dev_vdbg(dev, "%s: operational\n", __func__);
		break;
	case CY_HST_CAT:
		cur_mode = CY_MODE_CAT;
		dev_vdbg(dev, "%s: CaT\n", __func__);
		break;
	case CY_HST_SYSINFO:
		cur_mode = CY_MODE_SYSINFO;
		dev_vdbg(dev, "%s: sysinfo\n", __func__);
		break;
	default:
		cur_mode = CY_MODE_UNKNOWN;
		dev_err(dev, "%s: unknown HST mode 0x%02X\n", __func__,
			mode[0]);
		break;
	}

	/* Check whether this IRQ should be ignored (internal) */
	if (cd->int_status & CY_INT_IGNORE) {
		dev_vdbg(dev, "%s: Ignoring IRQ\n", __func__);
		goto cyttsp4_irq_exit;
	}

	/* Check for wake up interrupt */
	if (cd->int_status & CY_INT_AWAKE) {
		cd->int_status &= ~CY_INT_AWAKE;
		wake_up(&cd->wait_q);
		dev_vdbg(dev, "%s: Received wake up interrupt\n", __func__);
		goto cyttsp4_irq_handshake;
	}

	/* Expecting mode change interrupt */
	if ((cd->int_status & CY_INT_MODE_CHANGE)
			&& (mode[0] & CY_HST_MODE_CHANGE) == 0) {
		cd->int_status &= ~CY_INT_MODE_CHANGE;
		dev_dbg(dev, "%s: finish mode switch m=%d -> m=%d\n",
				__func__, cd->mode, cur_mode);
		cd->mode = cur_mode;
		wake_up(&cd->wait_q);
		goto cyttsp4_irq_handshake;
	}

	/* compare current core mode to current device mode */
	dev_vdbg(dev, "%s: cd->mode=%d cur_mode=%d\n",
			__func__, cd->mode, cur_mode);
	if ((mode[0] & CY_HST_MODE_CHANGE) == 0 && cd->mode != cur_mode) {
		/* Unexpected mode change occurred */
		dev_err(dev, "%s %d->%d 0x%x\n", __func__, cd->mode,
				cur_mode, cd->int_status);
		dev_dbg(dev, "%s: Unexpected mode change, startup\n",
				__func__);
		cyttsp4_queue_startup_(cd);
		goto cyttsp4_irq_exit;
	}

	/* Expecting command complete interrupt */
	dev_vdbg(dev, "%s: command offset:0x%x\n", __func__, cmd_ofs);
	if ((cd->int_status & CY_INT_EXEC_CMD)
			&& cmd_ofs < sizeof(mode) && (mode[cmd_ofs] & CY_CMD_COMPLETE)) {
		cd->int_status &= ~CY_INT_EXEC_CMD;
		dev_vdbg(dev, "%s: Received command complete interrupt\n",
				__func__);
		wake_up(&cd->wait_q);
		/*
		 * It is possible to receive a single interrupt for
		 * command complete and touch/button status report.
		 * Continue processing for a possible status report.
		 */
	}

	/* This should be status report, read status regs */
	if (cd->mode == CY_MODE_OPERATIONAL) {
		dev_vdbg(dev, "%s: Read status registers\n", __func__);
		rc = cyttsp4_load_status_regs(cd);
		if (rc < 0)
			dev_err(dev, "%s: fail read mode regs r=%d\n",
				__func__, rc);
	}

	cyttsp4_mt_attention(cd);

cyttsp4_irq_handshake:
	/* handshake the event */
	dev_vdbg(dev, "%s: Handshake mode=0x%02X r=%d\n",
			__func__, mode[0], rc);
	rc = cyttsp4_handshake(cd, mode[0]);
	if (rc < 0)
		dev_err(dev, "%s: Fail handshake mode=0x%02X r=%d\n",
				__func__, mode[0], rc);

	/*
	 * a non-zero udelay period is required for using
	 * IRQF_TRIGGER_LOW in order to delay until the
	 * device completes isr deassert
	 */


cyttsp4_irq_exit:
	mutex_unlock(&cd->system_lock);
	return IRQ_HANDLED;
}

static void cyttsp4_start_wd_timer(struct cyttsp4 *cd)
{
	if (cd->stopping || !CY_WATCHDOG_TIMEOUT)
		return;

	mod_timer(&cd->watchdog_timer, jiffies +
			msecs_to_jiffies(CY_WATCHDOG_TIMEOUT));
}

static void cyttsp4_stop_wd_timer(struct cyttsp4 *cd)
{
	if (!CY_WATCHDOG_TIMEOUT)
		return;

	/*
	 * Ensure we wait until the watchdog timer
	 * running on a different CPU finishes
	 */
	timer_delete_sync(&cd->watchdog_timer);
	cancel_work_sync(&cd->watchdog_work);
	timer_delete_sync(&cd->watchdog_timer);
}

static void cyttsp4_watchdog_timer(struct timer_list *t)
{
	struct cyttsp4 *cd = timer_container_of(cd, t, watchdog_timer);

	dev_vdbg(cd->dev, "%s: Watchdog timer triggered\n", __func__);

	schedule_work(&cd->watchdog_work);

}

static int cyttsp4_request_exclusive(struct cyttsp4 *cd, void *ownptr,
		int timeout_ms)
{
	int t = msecs_to_jiffies(timeout_ms);
	bool with_timeout = (timeout_ms != 0);

	mutex_lock(&cd->system_lock);
	if (!cd->exclusive_dev && cd->exclusive_waits == 0) {
		cd->exclusive_dev = ownptr;
		goto exit;
	}

	cd->exclusive_waits++;
wait:
	mutex_unlock(&cd->system_lock);
	if (with_timeout) {
		t = wait_event_timeout(cd->wait_q, !cd->exclusive_dev, t);
		if (IS_TMO(t)) {
			dev_err(cd->dev, "%s: tmo waiting exclusive access\n",
				__func__);
			mutex_lock(&cd->system_lock);
			cd->exclusive_waits--;
			mutex_unlock(&cd->system_lock);
			return -ETIME;
		}
	} else {
		wait_event(cd->wait_q, !cd->exclusive_dev);
	}
	mutex_lock(&cd->system_lock);
	if (cd->exclusive_dev)
		goto wait;
	cd->exclusive_dev = ownptr;
	cd->exclusive_waits--;
exit:
	mutex_unlock(&cd->system_lock);

	return 0;
}

/*
 * returns error if was not owned
 */
static int cyttsp4_release_exclusive(struct cyttsp4 *cd, void *ownptr)
{
	mutex_lock(&cd->system_lock);
	if (cd->exclusive_dev != ownptr) {
		mutex_unlock(&cd->system_lock);
		return -EINVAL;
	}

	dev_vdbg(cd->dev, "%s: exclusive_dev %p freed\n",
		__func__, cd->exclusive_dev);
	cd->exclusive_dev = NULL;
	wake_up(&cd->wait_q);
	mutex_unlock(&cd->system_lock);
	return 0;
}

static int cyttsp4_wait_bl_heartbeat(struct cyttsp4 *cd)
{
	long t;
	int rc = 0;

	/* wait heartbeat */
	dev_vdbg(cd->dev, "%s: wait heartbeat...\n", __func__);
	t = wait_event_timeout(cd->wait_q, cd->mode == CY_MODE_BOOTLOADER,
			msecs_to_jiffies(CY_CORE_RESET_AND_WAIT_TIMEOUT));
	if (IS_TMO(t)) {
		dev_err(cd->dev, "%s: tmo waiting bl heartbeat cd->mode=%d\n",
			__func__, cd->mode);
		rc = -ETIME;
	}

	return rc;
}

static int cyttsp4_wait_sysinfo_mode(struct cyttsp4 *cd)
{
	long t;

	dev_vdbg(cd->dev, "%s: wait sysinfo...\n", __func__);

	t = wait_event_timeout(cd->wait_q, cd->mode == CY_MODE_SYSINFO,
			msecs_to_jiffies(CY_CORE_SYSINFO_TIMEOUT));
	if (IS_TMO(t)) {
		dev_err(cd->dev, "%s: tmo waiting exit bl cd->mode=%d\n",
			__func__, cd->mode);
		mutex_lock(&cd->system_lock);
		cd->int_status &= ~CY_INT_MODE_CHANGE;
		mutex_unlock(&cd->system_lock);
		return -ETIME;
	}

	return 0;
}

static int cyttsp4_reset_and_wait(struct cyttsp4 *cd)
{
	int rc;

	/* reset hardware */
	mutex_lock(&cd->system_lock);
	dev_dbg(cd->dev, "%s: reset hw...\n", __func__);
	cd->mode = CY_MODE_UNKNOWN;
	rc = cyttsp4_hw_hard_reset(cd);
	mutex_unlock(&cd->system_lock);
	if (rc < 0) {
		dev_err(cd->dev, "%s:Fail hw reset r=%d\n", __func__, rc);
		return rc;
	}

	return cyttsp4_wait_bl_heartbeat(cd);
}

/*
 * returns err if refused or timeout; block until mode change complete
 * bit is set (mode change interrupt)
 */
static int cyttsp4_set_mode(struct cyttsp4 *cd, int new_mode)
{
	u8 new_dev_mode;
	u8 mode;
	long t;
	int rc;

	switch (new_mode) {
	case CY_MODE_OPERATIONAL:
		new_dev_mode = CY_HST_OPERATE;
		break;
	case CY_MODE_SYSINFO:
		new_dev_mode = CY_HST_SYSINFO;
		break;
	case CY_MODE_CAT:
		new_dev_mode = CY_HST_CAT;
		break;
	default:
		dev_err(cd->dev, "%s: invalid mode: %02X(%d)\n",
			__func__, new_mode, new_mode);
		return -EINVAL;
	}

	/* change mode */
	dev_dbg(cd->dev, "%s: %s=%p new_dev_mode=%02X new_mode=%d\n",
			__func__, "have exclusive", cd->exclusive_dev,
			new_dev_mode, new_mode);

	mutex_lock(&cd->system_lock);
	rc = cyttsp4_adap_read(cd, CY_REG_BASE, sizeof(mode), &mode);
	if (rc < 0) {
		mutex_unlock(&cd->system_lock);
		dev_err(cd->dev, "%s: Fail read mode r=%d\n",
			__func__, rc);
		goto exit;
	}

	/* Clear device mode bits and set to new mode */
	mode &= ~CY_HST_MODE;
	mode |= new_dev_mode | CY_HST_MODE_CHANGE;

	cd->int_status |= CY_INT_MODE_CHANGE;
	rc = cyttsp4_adap_write(cd, CY_REG_BASE, sizeof(mode), &mode);
	mutex_unlock(&cd->system_lock);
	if (rc < 0) {
		dev_err(cd->dev, "%s: Fail write mode change r=%d\n",
				__func__, rc);
		goto exit;
	}

	/* wait for mode change done interrupt */
	t = wait_event_timeout(cd->wait_q,
			(cd->int_status & CY_INT_MODE_CHANGE) == 0,
			msecs_to_jiffies(CY_CORE_MODE_CHANGE_TIMEOUT));
	dev_dbg(cd->dev, "%s: back from wait t=%ld cd->mode=%d\n",
			__func__, t, cd->mode);

	if (IS_TMO(t)) {
		dev_err(cd->dev, "%s: %s\n", __func__,
				"tmo waiting mode change");
		mutex_lock(&cd->system_lock);
		cd->int_status &= ~CY_INT_MODE_CHANGE;
		mutex_unlock(&cd->system_lock);
		rc = -EINVAL;
	}

exit:
	return rc;
}

static void cyttsp4_watchdog_work(struct work_struct *work)
{
	struct cyttsp4 *cd =
		container_of(work, struct cyttsp4, watchdog_work);
	u8 *mode;
	int retval;

	mutex_lock(&cd->system_lock);
	retval = cyttsp4_load_status_regs(cd);
	if (retval < 0) {
		dev_err(cd->dev,
			"%s: failed to access device in watchdog timer r=%d\n",
			__func__, retval);
		cyttsp4_queue_startup_(cd);
		goto cyttsp4_timer_watchdog_exit_error;
	}
	mode = &cd->sysinfo.xy_mode[CY_REG_BASE];
	if (IS_BOOTLOADER(mode[0], mode[1])) {
		dev_err(cd->dev,
			"%s: device found in bootloader mode when operational mode\n",
			__func__);
		cyttsp4_queue_startup_(cd);
		goto cyttsp4_timer_watchdog_exit_error;
	}

	cyttsp4_start_wd_timer(cd);
cyttsp4_timer_watchdog_exit_error:
	mutex_unlock(&cd->system_lock);
}

static int cyttsp4_core_sleep_(struct cyttsp4 *cd)
{
	enum cyttsp4_sleep_state ss = SS_SLEEP_ON;
	enum cyttsp4_int_state int_status = CY_INT_IGNORE;
	int rc = 0;
	u8 mode[2];

	/* Already in sleep mode? */
	mutex_lock(&cd->system_lock);
	if (cd->sleep_state == SS_SLEEP_ON) {
		mutex_unlock(&cd->system_lock);
		return 0;
	}
	cd->sleep_state = SS_SLEEPING;
	mutex_unlock(&cd->system_lock);

	cyttsp4_stop_wd_timer(cd);

	/* Wait until currently running IRQ handler exits and disable IRQ */
	disable_irq(cd->irq);

	dev_vdbg(cd->dev, "%s: write DEEP SLEEP...\n", __func__);
	mutex_lock(&cd->system_lock);
	rc = cyttsp4_adap_read(cd, CY_REG_BASE, sizeof(mode), &mode);
	if (rc) {
		mutex_unlock(&cd->system_lock);
		dev_err(cd->dev, "%s: Fail read adapter r=%d\n", __func__, rc);
		goto error;
	}

	if (IS_BOOTLOADER(mode[0], mode[1])) {
		mutex_unlock(&cd->system_lock);
		dev_err(cd->dev, "%s: Device in BOOTLOADER mode.\n", __func__);
		rc = -EINVAL;
		goto error;
	}

	mode[0] |= CY_HST_SLEEP;
	rc = cyttsp4_adap_write(cd, CY_REG_BASE, sizeof(mode[0]), &mode[0]);
	mutex_unlock(&cd->system_lock);
	if (rc) {
		dev_err(cd->dev, "%s: Fail write adapter r=%d\n", __func__, rc);
		goto error;
	}
	dev_vdbg(cd->dev, "%s: write DEEP SLEEP succeeded\n", __func__);

	rc = 0; /* Supplies remain enabled during controller sleep. */

	if (rc < 0) {
		dev_err(cd->dev, "%s: HW Power down fails r=%d\n",
				__func__, rc);
		goto error;
	}

	/* Give time to FW to sleep */
	msleep(50);

	goto exit;

error:
	ss = SS_SLEEP_OFF;
	int_status = CY_INT_NONE;
	cyttsp4_start_wd_timer(cd);

exit:
	mutex_lock(&cd->system_lock);
	cd->sleep_state = ss;
	cd->int_status |= int_status;
	mutex_unlock(&cd->system_lock);
	enable_irq(cd->irq);
	return rc;
}

static int cyttsp4_startup_(struct cyttsp4 *cd)
{
	int retry = CY_CORE_STARTUP_RETRY_COUNT;
	int rc;

	cyttsp4_stop_wd_timer(cd);

reset:
	if (retry != CY_CORE_STARTUP_RETRY_COUNT)
		dev_dbg(cd->dev, "%s: Retry %d\n", __func__,
			CY_CORE_STARTUP_RETRY_COUNT - retry);

	/* reset hardware and wait for heartbeat */
	rc = cyttsp4_reset_and_wait(cd);
	if (rc < 0) {
		dev_err(cd->dev, "%s: Error on h/w reset r=%d\n", __func__, rc);
		if (retry--)
			goto reset;
		goto exit;
	}

	/* exit bl into sysinfo mode */
	dev_vdbg(cd->dev, "%s: write exit ldr...\n", __func__);
	mutex_lock(&cd->system_lock);
	cd->int_status &= ~CY_INT_IGNORE;
	cd->int_status |= CY_INT_MODE_CHANGE;

	rc = cd->bus_ops->exit_bootloader(cd->dev);
	mutex_unlock(&cd->system_lock);
	if (rc < 0) {
		dev_err(cd->dev, "%s: Fail write r=%d\n", __func__, rc);
		if (retry--)
			goto reset;
		goto exit;
	}

	rc = cyttsp4_wait_sysinfo_mode(cd);
	if (rc < 0) {
		u8 buf[sizeof(ldr_err_app)];
		int rc1;

		/* Check for invalid/corrupted touch application */
		rc1 = cyttsp4_adap_read(cd, CY_REG_BASE, sizeof(ldr_err_app),
				buf);
		if (rc1) {
			dev_err(cd->dev, "%s: Fail read r=%d\n", __func__, rc1);
		} else if (!memcmp(buf, ldr_err_app, sizeof(ldr_err_app))) {
			dev_err(cd->dev, "%s: Error launching touch application\n",
				__func__);
			mutex_lock(&cd->system_lock);
			cd->invalid_touch_app = true;
			mutex_unlock(&cd->system_lock);
			goto exit_no_wd;
		}

		if (retry--)
			goto reset;
		goto exit;
	}

	mutex_lock(&cd->system_lock);
	cd->invalid_touch_app = false;
	mutex_unlock(&cd->system_lock);

	/* read sysinfo data */
	dev_vdbg(cd->dev, "%s: get sysinfo regs..\n", __func__);
	rc = cyttsp4_get_sysinfo_regs(cd);
	if (rc < 0) {
		dev_err(cd->dev, "%s: failed to get sysinfo regs rc=%d\n",
			__func__, rc);
		if (retry--)
			goto reset;
		goto exit;
	}

	rc = cyttsp4_set_mode(cd, CY_MODE_OPERATIONAL);
	if (rc < 0) {
		dev_err(cd->dev, "%s: failed to set mode to operational rc=%d\n",
			__func__, rc);
		if (retry--)
			goto reset;
		goto exit;
	}

	cyttsp4_lift_all(&cd->md);

	/* restore to sleep if was suspended */
	mutex_lock(&cd->system_lock);
	if (cd->sleep_state == SS_SLEEP_ON) {
		cd->sleep_state = SS_SLEEP_OFF;
		mutex_unlock(&cd->system_lock);
		cyttsp4_core_sleep_(cd);
		goto exit_no_wd;
	}
	mutex_unlock(&cd->system_lock);

exit:
	cyttsp4_start_wd_timer(cd);
exit_no_wd:
	return rc;
}

static int cyttsp4_startup(struct cyttsp4 *cd)
{
	int rc;

	mutex_lock(&cd->system_lock);
	cd->startup_state = STARTUP_RUNNING;
	mutex_unlock(&cd->system_lock);

	rc = cyttsp4_request_exclusive(cd, cd->dev,
			CY_CORE_REQUEST_EXCLUSIVE_TIMEOUT);
	if (rc < 0) {
		dev_err(cd->dev, "%s: fail get exclusive ex=%p own=%p\n",
				__func__, cd->exclusive_dev, cd->dev);
		goto exit;
	}

	rc = cyttsp4_startup_(cd);

	if (cyttsp4_release_exclusive(cd, cd->dev) < 0)
		/* Don't return fail code, mode is already changed. */
		dev_err(cd->dev, "%s: fail to release exclusive\n", __func__);
	else
		dev_vdbg(cd->dev, "%s: pass release exclusive\n", __func__);

exit:
	mutex_lock(&cd->system_lock);
	cd->startup_state = STARTUP_NONE;
	mutex_unlock(&cd->system_lock);

	/* Wake the waiters for end of startup */
	wake_up(&cd->wait_q);

	return rc;
}

static void cyttsp4_startup_work_function(struct work_struct *work)
{
	struct cyttsp4 *cd =  container_of(work, struct cyttsp4, startup_work);
	int rc;

	rc = cyttsp4_startup(cd);
	if (rc < 0)
		dev_err(cd->dev, "%s: Fail queued startup r=%d\n",
			__func__, rc);
}

static void cyttsp4_free_si_ptrs(struct cyttsp4 *cd)
{
	struct cyttsp4_sysinfo *si = &cd->sysinfo;

	if (!si)
		return;

	kfree(si->si_ptrs.cydata);
	kfree(si->si_ptrs.test);
	kfree(si->si_ptrs.pcfg);
	kfree(si->si_ptrs.opcfg);
	kfree(si->si_ptrs.ddata);
	kfree(si->si_ptrs.mdata);
	kfree(si->btn);
	kfree(si->xy_mode);
	kfree(si->xy_data);
	kfree(si->btn_rec_data);
}

static int cyttsp4_core_sleep(struct cyttsp4 *cd)
{
	int rc;

	rc = cyttsp4_request_exclusive(cd, cd->dev,
			CY_CORE_SLEEP_REQUEST_EXCLUSIVE_TIMEOUT);
	if (rc < 0) {
		dev_err(cd->dev, "%s: fail get exclusive ex=%p own=%p\n",
				__func__, cd->exclusive_dev, cd->dev);
		return 0;
	}

	rc = cyttsp4_core_sleep_(cd);

	if (cyttsp4_release_exclusive(cd, cd->dev) < 0)
		dev_err(cd->dev, "%s: fail to release exclusive\n", __func__);
	else
		dev_vdbg(cd->dev, "%s: pass release exclusive\n", __func__);

	return rc;
}

static int cyttsp4_core_wake_(struct cyttsp4 *cd)
{
	int rc;

	mutex_lock(&cd->system_lock);
	if (cd->sleep_state == SS_SLEEP_OFF && cd->mode == CY_MODE_OPERATIONAL) {
		mutex_unlock(&cd->system_lock);
		return 0;
	}
	cd->sleep_state = SS_SLEEP_OFF;
	cd->startup_state = STARTUP_RUNNING;
	cd->int_status &= ~(CY_INT_IGNORE | CY_INT_AWAKE | CY_INT_MODE_CHANGE);
	mutex_unlock(&cd->system_lock);
	/* The older Perrier controller did not wake through the later Gen4
	 * read-only I2C wake sequence. Its stock recovery callback supports a
	 * full reset. Reuse our verified reset/application-launch path instead
	 * of driving the IRQ line as an output, as the legacy callback did.
	 * core_wake() already holds exclusive ownership.
	 */
	rc = cyttsp4_startup_(cd);
	mutex_lock(&cd->system_lock);
	cd->startup_state = STARTUP_NONE;
	cd->sleep_state = rc ? SS_SLEEP_ON : SS_SLEEP_OFF;
	mutex_unlock(&cd->system_lock);
	wake_up(&cd->wait_q);
	if (rc)
		cyttsp4_stop_wd_timer(cd);
	else
		dev_info(cd->dev, "Gen4 resume reinitialized existing application\n");
	return rc;
}

static int cyttsp4_core_wake(struct cyttsp4 *cd)
{
	int rc;

	rc = cyttsp4_request_exclusive(cd, cd->dev,
			CY_CORE_REQUEST_EXCLUSIVE_TIMEOUT);
	if (rc < 0) {
		dev_err(cd->dev, "%s: fail get exclusive ex=%p own=%p\n",
				__func__, cd->exclusive_dev, cd->dev);
		return 0;
	}

	rc = cyttsp4_core_wake_(cd);

	if (cyttsp4_release_exclusive(cd, cd->dev) < 0)
		dev_err(cd->dev, "%s: fail to release exclusive\n", __func__);
	else
		dev_vdbg(cd->dev, "%s: pass release exclusive\n", __func__);

	return rc;
}

static int cyttsp4_core_suspend(struct device *dev)
{
	struct cyttsp4 *cd = dev_get_drvdata(dev);
	struct cyttsp4_mt_data *md = &cd->md;
	int rc;

	md->is_suspended = true;

	rc = cyttsp4_core_sleep(cd);
	if (rc < 0) {
		dev_err(dev, "%s: Error on sleep\n", __func__);
		return -EAGAIN;
	}
	return 0;
}

static int cyttsp4_core_resume(struct device *dev)
{
	struct cyttsp4 *cd = dev_get_drvdata(dev);
	struct cyttsp4_mt_data *md = &cd->md;
	int rc;

	md->is_suspended = false;

	rc = cyttsp4_core_wake(cd);
	if (rc < 0) {
		dev_err(dev, "%s: Error on wake\n", __func__);
		return -EAGAIN;
	}

	return 0;
}

EXPORT_GPL_RUNTIME_DEV_PM_OPS(cyttsp4_pm_ops,
			      cyttsp4_core_suspend, cyttsp4_core_resume, NULL);

static int cyttsp4_mt_open(struct input_dev *input)
{
	return pm_runtime_resume_and_get(input->dev.parent);
}

static void cyttsp4_mt_close(struct input_dev *input)
{
	pm_runtime_put(input->dev.parent);
}


static int cyttsp4_setup_input_device(struct cyttsp4 *cd)
{
	struct cyttsp4_mt_data *md = &cd->md;
	struct cyttsp4_sysinfo *si = &cd->sysinfo;
	int rc;

	/* Verify the same panel profile and axis ranges used by the proven driver. */
	if (merge_bytes(si->si_ptrs.cydata->ttpidh, si->si_ptrs.cydata->ttpidl) != 1 ||
	    si->si_ptrs.cydata->fw_ver_major != 1 || si->si_ptrs.cydata->fw_ver_minor != 1 ||
	    si->si_ofs.max_x != 1280 || si->si_ofs.max_y != 800)
		return -ENODEV;
	input_set_abs_params(md->input, ABS_MT_POSITION_X, 0, si->si_ofs.max_x - 1, 0, 0);
	input_set_abs_params(md->input, ABS_MT_POSITION_Y, 0, si->si_ofs.max_y - 1, 0, 0);
	input_set_abs_params(md->input, ABS_MT_PRESSURE, 0, si->si_ofs.max_p, 0, 0);
	input_set_abs_params(md->input, ABS_MT_TOUCH_MAJOR, 0, 255, 0, 0);
	touchscreen_parse_properties(md->input, true, &md->prop);
	rc = input_mt_init_slots(md->input, si->si_ofs.max_tchs,
				 INPUT_MT_DIRECT | INPUT_MT_DROP_UNUSED);
	if (rc)
		return rc;
	return input_register_device(md->input);
}

static int cyttsp4_mt_probe(struct cyttsp4 *cd)
{
	struct cyttsp4_mt_data *md = &cd->md;
	int rc;

	mutex_init(&md->report_lock);
	md->input = input_allocate_device();
	if (!md->input)
		return -ENOMEM;
	md->input->name = "Cypress CYTTSP4";
	scnprintf(md->phys, sizeof(md->phys), "%s/input0", dev_name(cd->dev));
	md->input->phys = md->phys;
	md->input->id.bustype = cd->bus_ops->bustype;
	md->input->id.vendor = 0x04b4;
	md->input->id.product = 1;
	md->input->id.version = 0x0101;
	md->input->dev.parent = cd->dev;
	md->input->open = cyttsp4_mt_open;
	md->input->close = cyttsp4_mt_close;
	input_set_drvdata(md->input, md);
	rc = cyttsp4_setup_input_device(cd);
	if (rc) {
		md->si = NULL;
		input_free_device(md->input);
		md->input = NULL;
	} else {
		md->si = &cd->sysinfo;
	}
	return rc;
}

struct cyttsp4 *cyttsp4_probe(const struct cyttsp4_bus_ops *ops,
		struct device *dev, u16 irq, size_t xfer_buf_size)
{
	struct cyttsp4 *cd;
	int rc;

	if (!dev->of_node || !irq)
		return ERR_PTR(-EINVAL);
	cd = kzalloc(sizeof(*cd), GFP_KERNEL);
	if (!cd)
		return ERR_PTR(-ENOMEM);
	cd->dev = dev;
	cd->bus_ops = ops;
	cd->irq = irq;
	cd->in_bootloader = true;
	cd->xfer_buf_size = xfer_buf_size;
	cd->xfer_buf = kzalloc(xfer_buf_size, GFP_KERNEL);
	if (!cd->xfer_buf) {
		rc = -ENOMEM;
		goto free_cd;
	}
	/* Acquire everything before driving pins, including a deferred supplier. */
	cd->vdd = devm_regulator_get(dev, "vdd");
	if (IS_ERR(cd->vdd)) {
		rc = dev_err_probe(dev, PTR_ERR(cd->vdd), "cannot get touch VDD\n");
		goto free_xfer;
	}
	cd->vddio = devm_regulator_get(dev, "vddio");
	if (IS_ERR(cd->vddio)) {
		rc = dev_err_probe(dev, PTR_ERR(cd->vddio), "cannot get touch VDDIO\n");
		goto free_xfer;
	}
	cd->reset_gpio = devm_gpiod_get(dev, "reset", GPIOD_ASIS);
	if (IS_ERR(cd->reset_gpio)) {
		rc = dev_err_probe(dev, PTR_ERR(cd->reset_gpio), "cannot get touch reset\n");
		goto free_xfer;
	}
	mutex_init(&cd->system_lock);
	mutex_init(&cd->adap_lock);
	init_waitqueue_head(&cd->wait_q);
	INIT_WORK(&cd->startup_work, cyttsp4_startup_work_function);
	INIT_WORK(&cd->watchdog_work, cyttsp4_watchdog_work);
	timer_setup(&cd->watchdog_timer, cyttsp4_watchdog_timer, 0);
	dev_set_drvdata(dev, cd);
	rc = request_threaded_irq(irq, NULL, cyttsp4_irq, IRQF_ONESHOT, dev_name(dev), cd);
	if (rc)
		goto clear_data;
	/* Stock perrier_init enables the 5 V rail, then the 3.3 V rail. */
	rc = regulator_enable(cd->vdd);
	if (rc)
		goto free_irq;
	rc = regulator_enable(cd->vddio);
	if (rc)
		goto disable_vdd;
	rc = gpiod_direction_output(cd->reset_gpio, 0);
	if (rc)
		goto disable_vddio;
	rc = cyttsp4_startup(cd);
	if (rc)
		goto stop;
	pm_runtime_set_active(dev);
	pm_runtime_enable(dev);
	rc = cyttsp4_mt_probe(cd);
	if (rc) {
		pm_runtime_disable(dev);
		goto stop;
	}
	dev_info(dev, "Gen4 DT cold startup: %zux%zu, %zu contacts, %zu-byte records, irq %d\n",
		 cd->sysinfo.si_ofs.max_x, cd->sysinfo.si_ofs.max_y, cd->sysinfo.si_ofs.max_tchs,
		 cd->sysinfo.si_ofs.tch_rec_size, irq);
	return cd;
stop:
	WRITE_ONCE(cd->stopping, true);
	disable_irq(irq);
	cyttsp4_stop_wd_timer(cd);
	cancel_work_sync(&cd->startup_work);
	cyttsp4_free_si_ptrs(cd);
disable_vddio:
	regulator_disable(cd->vddio);
disable_vdd:
	regulator_disable(cd->vdd);
free_irq:
	free_irq(irq, cd);
clear_data:
	dev_set_drvdata(dev, NULL);
free_xfer:
	kfree(cd->xfer_buf);
free_cd:
	kfree(cd);
	return ERR_PTR(rc);
}
EXPORT_SYMBOL_GPL(cyttsp4_probe);



void cyttsp4_remove(struct cyttsp4 *cd)
{
	struct device *dev = cd->dev;

	WRITE_ONCE(cd->stopping, true);
	pm_runtime_barrier(dev);
	pm_runtime_disable(dev);
	disable_irq(cd->irq);
	cyttsp4_stop_wd_timer(cd);
	cancel_work_sync(&cd->startup_work);
	/* No IRQ/work can use the input device or sysinfo after this point. */
	input_unregister_device(cd->md.input);
	cd->md.input = NULL;
	free_irq(cd->irq, cd);
	regulator_disable(cd->vddio);
	regulator_disable(cd->vdd);
	cyttsp4_free_si_ptrs(cd);
	kfree(cd->xfer_buf);
	dev_set_drvdata(dev, NULL);
	kfree(cd);
}
EXPORT_SYMBOL_GPL(cyttsp4_remove);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Cypress TrueTouch(R) Standard touchscreen core driver");
MODULE_AUTHOR("Cypress");
