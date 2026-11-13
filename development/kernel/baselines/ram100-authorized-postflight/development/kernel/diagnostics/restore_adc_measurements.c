// SPDX-License-Identifier: GPL-2.0-only
// Restore only the three measurement enables changed by the mainline ADC.
// No GPIO, regulator, charger, IRQ, selector or calibration writes.
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/utsname.h>
#include <unistd.h>

static int read_reg(int fd, uint8_t address, uint8_t reg)
{
	uint8_t value;
	struct i2c_msg messages[] = {
		{ .addr = address, .len = 1, .buf = &reg },
		{ .addr = address, .flags = I2C_M_RD, .len = 1, .buf = &value },
	};
	struct i2c_rdwr_ioctl_data transfer = { .msgs = messages, .nmsgs = 2 };
	return ioctl(fd, I2C_RDWR, &transfer) == 2 ? value : -1;
}

static int write_reg(int fd, uint8_t address, uint8_t reg, uint8_t value)
{
	uint8_t data[] = { reg, value };
	struct i2c_msg message = { .addr = address, .len = 2, .buf = data };
	struct i2c_rdwr_ioctl_data transfer = { .msgs = &message, .nmsgs = 1 };
	return ioctl(fd, I2C_RDWR, &transfer) == 1 ? 0 : -1;
}

int main(int argc, char **argv)
{
	struct utsname name;
	if (argc != 2 || strcmp(argv[1], "--restore") || uname(&name) || strcmp(name.release, "3.4.113+")) return 2;
	int identity = open("/sys/bus/i2c/devices/1-0048/name", O_RDONLY | O_CLOEXEC);
	char chip[32] = {0};
	if (identity < 0) return 2;
	ssize_t length = read(identity, chip, sizeof(chip) - 1);
	close(identity);
	if (length != 8 || strcmp(chip, "twl6032\n")) return 2;
	int fd = open("/dev/i2c-1", O_RDWR | O_CLOEXEC);
	if (fd < 0) return 1;
	int misc = read_reg(fd, 0x48, 0xe4);
	int vbus = read_reg(fd, 0x49, 0x04);
	int id = read_reg(fd, 0x49, 0x06);
	if ((misc != 0 && misc != 7) || (vbus != 4 && vbus != 5) || (id != 0x14 && id != 0x15)) {
		fprintf(stderr, "Unexpected ADC controls: %02x %02x %02x; refused\n", misc, vbus, id);
		close(fd); return 1;
	}
	unsigned writes = 0;
	if (misc == 7) {
		if (write_reg(fd, 0x48, 0xe4, 0)) { close(fd); return 1; }
		++writes;
	}
	// The USB controls are SET/CLR aliases. Clear only measurement bit 0.
	if (id == 0x15) {
		if (write_reg(fd, 0x49, 0x07, 1)) { close(fd); return 1; }
		++writes;
	}
	if (vbus == 5) {
		if (write_reg(fd, 0x49, 0x05, 1)) { close(fd); return 1; }
		++writes;
	}
	misc = read_reg(fd, 0x48, 0xe4);
	vbus = read_reg(fd, 0x49, 0x04);
	id = read_reg(fd, 0x49, 0x06);
	close(fd);
	printf("ADC_RESTORE writes=%u misc=%02x vbus=%02x id=%02x\n", writes, misc, vbus, id);
	return misc == 0 && vbus == 4 && id == 0x14 ? 0 : 1;
}
