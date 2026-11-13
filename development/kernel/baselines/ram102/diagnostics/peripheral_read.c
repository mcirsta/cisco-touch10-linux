// SPDX-License-Identifier: GPL-2.0-only
// Fixed-address, read-only baseline/check for Perrier peripheral bring-up.
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

static int reg_read(int fd, unsigned addr, unsigned reg, unsigned bytes)
{
	uint8_t pointer = reg, data[2] = {0};
	struct i2c_msg messages[] = {
		{ .addr = addr, .len = 1, .buf = &pointer },
		{ .addr = addr, .flags = I2C_M_RD, .len = bytes, .buf = data },
	};
	struct i2c_rdwr_ioctl_data transfer = { .msgs = messages, .nmsgs = 2 };
	if (ioctl(fd, I2C_RDWR, &transfer) != 2) {
		perror("I2C register read");
		return -1;
	}
	return bytes == 2 ? (data[0] << 8) | data[1] : data[0];
}

int main(int argc, char **argv)
{
	int stock = argc == 2 && !strcmp(argv[1], "stock");
	if (argc != 2 || (!stock && strcmp(argv[1], "ram"))) return 2;
	int pmic = open(stock ? "/dev/i2c-1" : "/dev/i2c-0", O_RDWR | O_CLOEXEC);
	int sensors = open(stock ? "/dev/i2c-4" : "/dev/i2c-3", O_RDWR | O_CLOEXEC);
	if (pmic < 0 || sensors < 0) { perror("I2C open"); return 1; }
	const unsigned bases[] = {0x10, 0x16, 0x22, 0x28, 0x34,
		0x50, 0x54, 0x58, 0x5c, 0x60, 0x64, 0x68, 0x6c, 0x70, 0x74};
	for (unsigned i = 0; i < sizeof(bases) / sizeof(bases[0]); i++) {
		for (unsigned offset = 0; offset <= (i < 5 ? 4 : 3); offset++) {
			unsigned reg = 0x30 + bases[i] + offset;
			int value = reg_read(pmic, 0x48, reg, 1);
			if (value < 0) return 1;
			printf("PMIC %02x %02x\n", reg, value);
		}
	}
	for (unsigned addr = 0x40; addr <= 0x41; addr++) {
		for (unsigned reg = 0; reg <= 0x0f; reg++) {
			int value = reg_read(sensors, addr, reg, 2);
			if (value < 0) return 1;
			printf("INA %02x %02x %04x\n", addr, reg, value);
		}
	}
	const unsigned pwm_regs[] = {0x92, 0xba, 0xbb, 0xbd, 0xbe};
	for (unsigned i = 0; i < sizeof(pwm_regs) / sizeof(pwm_regs[0]); i++) {
		int value = reg_read(pmic, 0x49, pwm_regs[i], 1);
		if (value < 0) return 1;
		printf("PWM %02x %02x\n", pwm_regs[i], value);
	}
	close(sensors);
	close(pmic);
	return 0;
}
