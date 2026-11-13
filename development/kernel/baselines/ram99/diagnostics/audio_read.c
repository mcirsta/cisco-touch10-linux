// SPDX-License-Identifier: GPL-2.0-only
// Fixed, non-destructive codec/clock/expander reads; skip interrupt status.
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

static int reg_read(int fd, unsigned addr, uint8_t reg)
{
	uint8_t value = 0;
	struct i2c_msg messages[] = {
		{ .addr = addr, .len = 1, .buf = &reg },
		{ .addr = addr, .flags = I2C_M_RD, .len = 1, .buf = &value },
	};
	struct i2c_rdwr_ioctl_data transfer = { .msgs = messages, .nmsgs = 2 };
	return ioctl(fd, I2C_RDWR, &transfer) == 2 ? value : -1;
}

int main(int argc, char **argv)
{
	int stock = argc == 2 && !strcmp(argv[1], "stock");
	if (argc != 2 || (!stock && strcmp(argv[1], "ram"))) return 2;
	int bus = open(stock ? "/dev/i2c-1" : "/dev/i2c-0", O_RDWR | O_CLOEXEC);
	int port = open(stock ? "/dev/i2c-4" : "/dev/i2c-3", O_RDWR | O_CLOEXEC);
	if (bus < 0 || port < 0) { perror("Audio read open"); return 1; }
	const unsigned regs[] = {1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
		16, 17, 18, 19, 20, 21, 22, 23, 30, 45};
	for (unsigned i = 0; i < sizeof(regs) / sizeof(regs[0]); i++) {
		int value = reg_read(bus, 0x4b, regs[i]);
		if (value < 0) { perror("Codec read"); return 1; }
		printf("CODEC %02x %02x\n", regs[i], value);
	}
	for (unsigned reg = 0xbc; reg <= 0xc1; reg++) {
		int value = reg_read(bus, 0x48, reg);
		if (value < 0) return 1;
		printf("CLOCK_REG %02x %02x\n", reg, value);
	}
	uint8_t value;
	struct i2c_msg message = { .addr = 0x24, .flags = I2C_M_RD, .len = 1, .buf = &value };
	struct i2c_rdwr_ioctl_data transfer = { .msgs = &message, .nmsgs = 1 };
	if (ioctl(port, I2C_RDWR, &transfer) != 1) return 1;
	printf("GPIO_RAW %02x\n", value);
	close(port); close(bus);
	return 0;
}
