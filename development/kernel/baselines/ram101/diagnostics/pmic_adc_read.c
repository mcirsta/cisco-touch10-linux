// SPDX-License-Identifier: GPL-2.0-only
// Non-destructive reads of ADC configuration/calibration, never IRQ status.
#include <fcntl.h>
#include <linux/i2c.h>
#include <linux/i2c-dev.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

static int read_reg(int fd, unsigned address, unsigned reg)
{
	uint8_t pointer = reg, value;
	struct i2c_msg messages[] = {
		{ .addr = address, .len = 1, .buf = &pointer },
		{ .addr = address, .flags = I2C_M_RD, .len = 1, .buf = &value },
	};
	struct i2c_rdwr_ioctl_data transfer = { .msgs = messages, .nmsgs = 2 };
	if (ioctl(fd, I2C_RDWR, &transfer) != 2) return -1;
	return value;
}

int main(int argc, char **argv)
{
	if (argc != 2 || (strcmp(argv[1], "stock") && strcmp(argv[1], "ram"))) return 2;
	int fd = open(!strcmp(argv[1], "stock") ? "/dev/i2c-1" : "/dev/i2c-0", O_RDWR | O_CLOEXEC);
	if (fd < 0) { perror("ADC diagnostic open"); return 1; }
	const unsigned usb_adc[] = { 0x04, 0x06, 0x2e, 0x35, 0x36, 0x90, 0xd4, 0xd7 };
	int value = read_reg(fd, 0x48, 0xe4);
	if (value < 0) return 1;
	printf("ADC_CFG 48 e4 %02x\n", value);
	for (unsigned i = 0; i < sizeof(usb_adc) / sizeof(usb_adc[0]); ++i) {
		value = read_reg(fd, 0x49, usb_adc[i]);
		if (value < 0) return 1;
		printf("ADC_CFG 49 %02x %02x\n", usb_adc[i], value);
	}
	for (unsigned reg = 0xcd; reg <= 0xdc; ++reg) {
		value = read_reg(fd, 0x4a, reg);
		if (value < 0) return 1;
		printf("ADC_TRIM %02x %02x\n", reg, value);
	}
	close(fd);
	return 0;
}
