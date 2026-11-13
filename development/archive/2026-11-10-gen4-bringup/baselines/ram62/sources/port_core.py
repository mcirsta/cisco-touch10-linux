#!/usr/bin/env python3
"""Reproduce the DT/modern-input port from the archived Linux v6.10 core."""
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
s = (HERE / 'reference/cyttsp4_core.c').read_text()


def replace(old, new):
    global s
    assert s.count(old) == 1, old[:100]
    s = s.replace(old, new)


def function(name, body):
    global s
    pattern = (r'(?m)^(?:static )?(?:int|void|irqreturn_t|struct cyttsp4 \*)\s*'
               + name + r'\([\s\S]*?^}\n')
    s, count = re.subn(pattern, lambda _: body.strip() + '\n', s, count=1)
    assert count == 1, name


replace('#include <linux/gpio.h>', '#include <linux/gpio/consumer.h>\n#include <linux/regulator/consumer.h>')
replace('static const u8 ldr_exit[] = {\n\t0xFF, 0x01, 0x3B, 0x00, 0x00, 0x4F, 0x6D, 0x17\n};\n', '')
replace('from_timer(cd, t, watchdog_timer)', 'timer_container_of(cd, t, watchdog_timer)')
replace('#define CY_CORE_RESET_AND_WAIT_TIMEOUT\t\t500',
        '#define CY_CORE_RESET_AND_WAIT_TIMEOUT\t\t500\n#define CY_CORE_SYSINFO_TIMEOUT\t\t\t10000')
replace('t = wait_event_timeout(cd->wait_q, cd->mode == CY_MODE_SYSINFO,\n\t\t\tmsecs_to_jiffies(CY_CORE_MODE_CHANGE_TIMEOUT));',
        't = wait_event_timeout(cd->wait_q, cd->mode == CY_MODE_SYSINFO,\n\t\t\tmsecs_to_jiffies(CY_CORE_SYSINFO_TIMEOUT));')

function('cyttsp4_hw_hard_reset', r'''
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
''')

# Check offset order and minimum block sizes before the old allocation/read code.
replace('si->si_ofs.map_sz = merge_bytes(si->si_data.map_szh,\n\t\t\tsi->si_data.map_szl);\n\tsi->si_ofs.map_sz', 'si->si_ofs.map_sz')
needle = '\tsi->si_ofs.mdata_ofs = merge_bytes(si->si_data.mdata_ofsh,\n\t\t\tsi->si_data.mdata_ofsl);\n\treturn rc;'
replace(needle, needle.replace('\treturn rc;', '''	if ((si->si_data.hst_mode & ~CY_HST_TOGGLE) != CY_HST_SYSINFO ||
	    si->si_ofs.map_sz > 256 ||
	    si->si_ofs.cydata_ofs < sizeof(si->si_data) ||
	    si->si_ofs.test_ofs < si->si_ofs.cydata_ofs + sizeof(struct cyttsp4_cydata) ||
	    si->si_ofs.pcfg_ofs < si->si_ofs.test_ofs + sizeof(struct cyttsp4_test) ||
	    si->si_ofs.opcfg_ofs < si->si_ofs.pcfg_ofs + 12 ||
	    si->si_ofs.ddata_ofs < si->si_ofs.opcfg_ofs + 23 ||
	    si->si_ofs.mdata_ofs < si->si_ofs.ddata_ofs ||
	    si->si_ofs.map_sz < si->si_ofs.mdata_ofs)
		return -EPROTO;
	return rc;'''))

function('cyttsp4_si_get_opcfg_data', r'''
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
''')

function('cyttsp4_si_get_btn_data', r'''
static int cyttsp4_si_get_btn_data(struct cyttsp4 *cd)
{
	/* Perrier's three front keys use the OMAP keypad, not CYTTSP4 buttons. */
	return cd->sysinfo.si_ofs.num_btns ? -EOPNOTSUPP : 0;
}
''')

function('cyttsp4_si_get_test_data', r'''
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
''')

function('cyttsp4_lift_all', r'''
static void cyttsp4_lift_all(struct cyttsp4_mt_data *md)
{
	if (!md->input)
		return;
	input_mt_sync_frame(md->input);
	input_sync(md->input);
	md->num_prv_tch = 0;
}
''')
function('cyttsp4_report_slot_liftoff', '')
function('cyttsp4_final_sync', '')
function('cyttsp4_get_touch_axis', r'''
static void cyttsp4_get_touch_axis(struct cyttsp4_mt_data *md,
	int *axis, int size, int max, u8 *xy_data, int bofs)
{
	int i;

	for (i = 0, *axis = 0; i < size; i++)
		*axis = (*axis << 8) | (xy_data[i] >> bofs);
	*axis &= max - 1;
}
''')

# Keep the upstream descriptor-based extraction; common touchscreen helpers own
# all DT transforms, in the same order as the tested handoff driver.
function('cyttsp4_get_touch', r'''
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
''')

function('cyttsp4_get_mt_touches', r'''
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
''')

# Discard oversize frames BEFORE the I2C read into xy_data.
replace('\t/* read touches */\n', '''	if (num_cur_tch > si->si_ofs.max_tchs ||
	    num_cur_tch > 10 || rep_len != 2 + num_cur_tch * si->si_ofs.tch_rec_size ||
	    IS_BAD_PKT(rep_stat) || IS_LARGE_AREA(tt_stat)) {
		cyttsp4_lift_all(md);
		return -EPROTO;
	}

	/* read touches */
''')
replace('dev_vdbg(dev, "%s: command byte:0x%x\\n", __func__, mode[cmd_ofs]);',
        'dev_vdbg(dev, "%s: command offset:0x%x\\n", __func__, cmd_ofs);')
replace('&& mode[cmd_ofs] & CY_CMD_COMPLETE)',
        '&& cmd_ofs < sizeof(mode) && (mode[cmd_ofs] & CY_CMD_COMPLETE))')
replace('\tudelay(cd->cpdata->level_irq_udelay);', '')
replace('\tif (cd->startup_state == STARTUP_NONE) {',
        '\tif (!cd->stopping && cd->startup_state == STARTUP_NONE) {')
replace('static void cyttsp4_start_wd_timer(struct cyttsp4 *cd)\n{\n\tif (!CY_WATCHDOG_TIMEOUT)',
        'static void cyttsp4_start_wd_timer(struct cyttsp4 *cd)\n{\n\tif (cd->stopping || !CY_WATCHDOG_TIMEOUT)')
replace('\ttimer_shutdown_sync(&cd->watchdog_timer);\n\tcancel_work_sync(&cd->watchdog_work);',
        '\ttimer_delete_sync(&cd->watchdog_timer);\n\tcancel_work_sync(&cd->watchdog_work);\n\ttimer_delete_sync(&cd->watchdog_timer);')
replace('\trc = cyttsp4_hw_reset(cd);\n\tcd->mode = CY_MODE_UNKNOWN;',
        '\tcd->mode = CY_MODE_UNKNOWN;\n\trc = cyttsp4_hw_reset(cd);')
replace('\trc = cyttsp4_adap_write(cd, CY_REG_BASE, sizeof(ldr_exit),\n\t\t\t(u8 *)ldr_exit);',
        '\trc = cd->bus_ops->exit_bootloader(cd->dev);')

# Sleep retains both supplies. Wake uses the controller's I2C wake transaction,
# avoiding any rail cycling or unproven wake GPIO sequence.
start = s.index('\tif (cd->cpdata->power) {')
end = s.index('\n', s.index('\t}', start) + 2)
# Match the full if/else block in core_sleep_, ending at its error test.
tail = s.index('\n\tif (rc < 0)', start)
s = s[:start] + '\trc = 0; /* Supplies remain enabled during controller sleep. */\n' + s[tail:]
start = s.index('\tif (cd->cpdata->power) {')
tail = s.index('\tmutex_unlock(&cd->system_lock);', start)
s = s[:start] + '\t/* An I2C read wakes the sleeping controller. */\n\tcyttsp4_adap_read(cd, CY_REG_BASE, sizeof(mode), &mode);\n' + s[tail:]
replace('static int cyttsp4_core_wake_(struct cyttsp4 *cd)\n{\n\tstruct device *dev = cd->dev;\n\tint rc;',
        'static int cyttsp4_core_wake_(struct cyttsp4 *cd)\n{\n\tstruct device *dev = cd->dev;')
function('cyttsp4_core_wake_', r'''
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
''')

function('cyttsp4_mt_open', r'''
static int cyttsp4_mt_open(struct input_dev *input)
{
	return pm_runtime_resume_and_get(input->dev.parent);
}
''')
function('cyttsp4_mt_close', r'''
static void cyttsp4_mt_close(struct input_dev *input)
{
	pm_runtime_put(input->dev.parent);
}
''')
function('cyttsp4_setup_input_device', r'''
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
''')
function('cyttsp4_mt_probe', r'''
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
''')

function('cyttsp4_probe', r'''
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
		 si->si_ofs.max_x, si->si_ofs.max_y, si->si_ofs.max_tchs,
		 si->si_ofs.tch_rec_size, irq);
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
'''.replace('si->si_ofs.', 'cd->sysinfo.si_ofs.'))

function('cyttsp4_mt_release', '')
function('cyttsp4_remove', r'''
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
''')

assert 'cpdata' not in s and 'md->pdata' not in s
s = s.replace(' * Contact Cypress Semiconductor',
              ' * DT/regulator/GPIO and Perrier report-profile port for Linux 6.18.\n *\n * Contact Cypress Semiconductor', 1)
(HERE / 'cyttsp4_core.c').write_text(s)
