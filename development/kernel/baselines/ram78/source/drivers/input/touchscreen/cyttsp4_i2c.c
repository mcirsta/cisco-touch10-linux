// SPDX-License-Identifier: GPL-2.0-only
/*
 * Linux v6.10 Cypress Gen4 I2C adapter, ported for the older Perrier firmware.
 * Copyright (C) 2012 Javier Martinez Canillas <javier@dowhile0.org>
 * Copyright (C) 2013 Cypress Semiconductor
 *
 * Stock board data: application 0x67, loader 0x69. Loader traffic is raw I2C,
 * without the later Gen4 0xff prefix or a register byte.
 */
#include "cyttsp4_core.h"
#include <linux/i2c.h>
#include <linux/of.h>

#define PERRIER_APP_ADDR 0x67
#define PERRIER_LOADER_ADDR 0x69

static int cyttsp4_i2c_read(struct device *dev, u8 *xfer_buf,
			  u16 addr, u16 length, void *values)
{
	struct i2c_client *client = to_i2c_client(dev);
	struct cyttsp4 *cd = dev_get_drvdata(dev);
	u8 reg = addr;
	struct i2c_msg msgs[] = {
		{ .addr = client->addr, .len = 1, .buf = &reg },
		{ .addr = client->addr, .flags = I2C_M_RD, .len = length, .buf = values },
	};
	int rc;

	if (cd->in_bootloader) {
		u8 status[7];
		struct i2c_msg msg = {
			.addr = PERRIER_LOADER_ADDR, .flags = I2C_M_RD,
			.len = sizeof(status), .buf = status,
		};

		if (addr || length > sizeof(status))
			return -EINVAL;
		rc = i2c_transfer(client->adapter, &msg, 1);
		if (rc != 1)
			return rc < 0 ? rc : -EIO;
		memcpy(values, status, length);
		return 0;
	}
	if (addr + length > 256)
		return -EINVAL;
	rc = i2c_transfer(client->adapter, msgs, ARRAY_SIZE(msgs));
	return rc == ARRAY_SIZE(msgs) ? 0 : rc < 0 ? rc : -EIO;
}

static int cyttsp4_i2c_write(struct device *dev, u8 *xfer_buf,
			   u16 addr, u16 length, const void *values)
{
	struct i2c_client *client = to_i2c_client(dev);
	struct cyttsp4 *cd = dev_get_drvdata(dev);
	int rc;

	if (cd->in_bootloader || addr + length > 256)
		return -EINVAL;
	xfer_buf[0] = addr;
	memcpy(xfer_buf + 1, values, length);
	rc = i2c_master_send(client, xfer_buf, length + 1);
	return rc == length + 1 ? 0 : rc < 0 ? rc : -EIO;
}

static int cyttsp4_i2c_exit_bootloader(struct device *dev)
{
	struct i2c_client *client = to_i2c_client(dev);
	struct cyttsp4 *cd = dev_get_drvdata(dev);
	/* Stock command 0x3b launches the existing application. */
	u8 command[] = { 0x01, 0x3b, 0x00, 0x00, 0x4f, 0x6d, 0x17 };
	struct i2c_msg msg = {
		.addr = PERRIER_LOADER_ADDR, .len = sizeof(command), .buf = command,
	};
	int rc = i2c_transfer(client->adapter, &msg, 1);

	if (rc != 1)
		return rc < 0 ? rc : -EIO;
	cd->in_bootloader = false;
	dev_info(dev, "Gen4 existing touch application launched at loader address 0x69\n");
	return 0;
}

static const struct cyttsp4_bus_ops cyttsp4_i2c_bus_ops = {
	.bustype = BUS_I2C,
	.read = cyttsp4_i2c_read,
	.write = cyttsp4_i2c_write,
	.exit_bootloader = cyttsp4_i2c_exit_bootloader,
};

static int cyttsp4_i2c_probe(struct i2c_client *client)
{
	struct cyttsp4 *cd;
	struct i2c_client *loader;

	if (!i2c_check_functionality(client->adapter, I2C_FUNC_I2C))
		return -EOPNOTSUPP;
	if (client->addr != PERRIER_APP_ADDR || client->irq <= 0)
		return -EINVAL;
	loader = devm_i2c_new_dummy_device(&client->dev, client->adapter,
					PERRIER_LOADER_ADDR);
	if (IS_ERR(loader))
		return dev_err_probe(&client->dev, PTR_ERR(loader),
				     "cannot reserve touch bootloader address\n");
	cd = cyttsp4_probe(&cyttsp4_i2c_bus_ops, &client->dev, client->irq, 257);
	return PTR_ERR_OR_ZERO(cd);
}

static void cyttsp4_i2c_remove(struct i2c_client *client)
{
	cyttsp4_remove(i2c_get_clientdata(client));
}

static const struct of_device_id cyttsp4_i2c_of_match[] = {
	{ .compatible = "cisco,perrier-cyttsp4" },
	{ }
};
MODULE_DEVICE_TABLE(of, cyttsp4_i2c_of_match);

static struct i2c_driver cyttsp4_i2c_driver = {
	.driver = {
		.name = "cyttsp4",
		.pm = pm_ptr(&cyttsp4_pm_ops),
		.of_match_table = cyttsp4_i2c_of_match,
	},
	.probe = cyttsp4_i2c_probe,
	.remove = cyttsp4_i2c_remove,
};
module_i2c_driver(cyttsp4_i2c_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Cypress Gen4 I2C touchscreen, Perrier DT profile");
