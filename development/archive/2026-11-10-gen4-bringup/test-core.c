
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
enum cyttsp4_tch_abs {	/* for ordering within the extracted touch data array */
	CY_TCH_X,	/* X */
	CY_TCH_Y,	/* Y */
	CY_TCH_P,	/* P (Z) */
	CY_TCH_T,	/* TOUCH ID */
	CY_TCH_E,	/* EVENT ID */
	CY_TCH_O,	/* OBJECT ID */
	CY_TCH_W,	/* SIZE */
	CY_TCH_MAJ,	/* TOUCH_MAJOR */
	CY_TCH_MIN,	/* TOUCH_MINOR */
	CY_TCH_OR,	/* ORIENTATION */
	CY_TCH_NUM_ABS
};
struct cyttsp4_tch_rec_params {
	u8 loc;
	u8 size;
} __packed;
struct cyttsp4_opcfg {
	u8 cmd_ofs;
	u8 rep_ofs;
	u8 rep_szh;
	u8 rep_szl;
	u8 num_btns;
	u8 tt_stat_ofs;
	u8 obj_cfg0;
	u8 max_tchs;
	u8 tch_rec_size;
	struct cyttsp4_tch_rec_params tch_rec_old[CY_NUM_TCH_FIELDS];
	u8 btn_rec_size;	/* btn record size (in bytes) */
	u8 btn_diff_ofs;	/* btn data loc, diff counts  */
	u8 btn_diff_size;	/* btn size of diff counts (in bits) */
	struct cyttsp4_tch_rec_params tch_rec_new[CY_NUM_EXT_TCH_FIELDS];
} __packed;
struct cyttsp4_touch {
	int abs[CY_TCH_NUM_ABS];
};
struct cyttsp4_tch_abs_params {
	size_t ofs;	/* abs byte offset */
	size_t size;	/* size in bits */
	size_t max;	/* max value */
	size_t bofs;	/* bit offset */
};
struct cyttsp4_sysinfo_ofs {
	size_t chip_type;
	size_t cmd_ofs;
	size_t rep_ofs;
	size_t rep_sz;
	size_t num_btns;
	size_t num_btn_regs;	/* ceil(num_btns/4) */
	size_t tt_stat_ofs;
	size_t tch_rec_size;
	size_t obj_cfg0;
	size_t max_tchs;
	size_t mode_size;
	size_t data_size;
	size_t map_sz;
	size_t max_x;
	size_t x_origin;	/* left or right corner */
	size_t max_y;
	size_t y_origin;	/* upper or lower corner */
	size_t max_p;
	size_t cydata_ofs;
	size_t test_ofs;
	size_t pcfg_ofs;
	size_t opcfg_ofs;
	size_t ddata_ofs;
	size_t mdata_ofs;
	size_t cydata_size;
	size_t test_size;
	size_t pcfg_size;
	size_t opcfg_size;
	size_t ddata_size;
	size_t mdata_size;
	size_t btn_keys_size;
	struct cyttsp4_tch_abs_params tch_abs[CY_TCH_NUM_ABS];
	size_t btn_rec_size; /* btn record size (in bytes) */
	size_t btn_diff_ofs;/* btn data loc ,diff counts, (Op-Mode byte ofs) */
	size_t btn_diff_size;/* btn size of diff counts (in bits) */
};

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
static inline size_t merge_bytes(u8 high, u8 low)
{
	return (high << 8) + low;
}

static int cyttsp4_bits_2_bytes(unsigned int nbits, size_t *max)
{
	*max = 1UL << nbits;
	return (nbits + 7) / 8;
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
    assert(count >= 0 && count <= 10);
    active = 0;
    for (int i = 0; i < count; i++) {
        struct cyttsp4_touch t;
        cyttsp4_get_touch(md, &t, md->si->xy_data + i * md->si->si_ofs.tch_rec_size);
        if (t.abs[CY_TCH_E] != 3) decoded[active++] = t;
    }
}
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
