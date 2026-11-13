// SPDX-License-Identifier: GPL-2.0-only
/*
 * Bounded, read-only TWL6032 voltage register probe for the stock kernel.
 *
 * The first message in each I2C_RDWR pair supplies a register address;
 * the second reads its value. No PMIC register value is written. The fixed
 * list covers offset EPROM and the three voltage selectors used by Cisco's
 * OMAP voltage-controller table.
 */

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include <linux/i2c-dev.h>
#include <linux/i2c.h>

#define PMIC_ADDRESS 0x48

static int read_register(int fd, uint8_t reg, uint8_t *value)
{
	struct i2c_msg messages[2] = {
		{
			.addr = PMIC_ADDRESS,
			.flags = 0,
			.len = 1,
			.buf = &reg,
		},
		{
			.addr = PMIC_ADDRESS,
			.flags = I2C_M_RD,
			.len = 1,
			.buf = value,
		},
	};
	struct i2c_rdwr_ioctl_data transfer = {
		.msgs = messages,
		.nmsgs = 2,
	};
	int result;

	result = ioctl(fd, I2C_RDWR, &transfer);
	if (result == 2)
		return 0;
	if (result >= 0)
		errno = EIO;
	return -1;
}

int main(void)
{
	static const struct {
		uint8_t address;
		const char *name;
	} registers[] = {
		{ 0xe0, "offset_efuse" },
		{ 0x55, "smps1_mpu_selector" },
		{ 0x5b, "smps2_core_selector" },
		{ 0x49, "smps5_iva_selector" },
	};
	int fd;
	size_t i;

	fd = open("/dev/i2c-1", O_RDWR | O_CLOEXEC);
	if (fd < 0) {
		fprintf(stderr, "open /dev/i2c-1: %s\n", strerror(errno));
		return 1;
	}

	for (i = 0; i < sizeof(registers) / sizeof(registers[0]); i++) {
		uint8_t value = 0;

		if (read_register(fd, registers[i].address, &value) < 0) {
			fprintf(stderr, "read 0x%02x: %s\n",
				registers[i].address, strerror(errno));
			close(fd);
			return 1;
		}
		printf("%s,0x%02x,0x%02x\n", registers[i].name,
		       registers[i].address, value);
	}

	close(fd);
	return 0;
}
