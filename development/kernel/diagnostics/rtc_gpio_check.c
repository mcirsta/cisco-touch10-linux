// SPDX-License-Identifier: GPL-2.0-only
// Fixed-address reads and GPIO-v2 as-is requests: no GPIO direction or value writes.
#include <fcntl.h>
#include <inttypes.h>
#include <linux/gpio.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <linux/rtc.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

static int read_register(int fd, uint8_t reg)
{
	uint8_t value = 0;
	struct i2c_msg messages[] = {
		{ .addr = 0x48, .len = 1, .buf = &reg },
		{ .addr = 0x48, .flags = I2C_M_RD, .len = 1, .buf = &value },
	};
	struct i2c_rdwr_ioctl_data request = { .msgs = messages, .nmsgs = 2 };
	return ioctl(fd, I2C_RDWR, &request) == 2 ? value : -1;
}

static int read_gpio_asis(void)
{
	for (int chip = 0; chip < 16; chip++) {
		char path[40];
		snprintf(path, sizeof(path), "/dev/gpiochip%d", chip);
		int fd = open(path, O_RDONLY | O_CLOEXEC);
		if (fd < 0) continue;
		struct gpiochip_info info = {0};
		if (ioctl(fd, GPIO_GET_CHIPINFO_IOCTL, &info) || info.lines != 8 || strcmp(info.label, "pcf8574")) {
			close(fd);
			continue;
		}
		struct gpio_v2_line_request request = { .num_lines = 8 };
		strcpy(request.consumer, "perrier-port-read");
		// flags=0 requests AS IS, never INPUT/OUTPUT, bias or drive changes.
		for (unsigned i = 0; i < 8; i++) request.offsets[i] = i;
		if (ioctl(fd, GPIO_V2_GET_LINE_IOCTL, &request)) { perror("GPIO as-is request"); close(fd); return -1; }
		struct gpio_v2_line_values values = { .mask = 0xff };
		int status = ioctl(request.fd, GPIO_V2_LINE_GET_VALUES_IOCTL, &values);
		close(request.fd);
		close(fd);
		if (status) { perror("GPIO values"); return -1; }
		printf("GPIO_CDEV %s label=%s value=%02x flags=0\n", path, info.label, (unsigned)values.bits & 255);
		return values.bits & 255;
	}
	fprintf(stderr, "PCF8574 GPIO controller not found\n");
	return -1;
}

static int64_t stamp(const struct rtc_time *rtc)
{
	struct tm tm = { .tm_sec = rtc->tm_sec, .tm_min = rtc->tm_min, .tm_hour = rtc->tm_hour,
		.tm_mday = rtc->tm_mday, .tm_mon = rtc->tm_mon, .tm_year = rtc->tm_year };
	return timegm(&tm);
}

int main(int argc, char **argv)
{
	int stock = argc == 2 && !strcmp(argv[1], "stock");
	if (argc != 2 || (!stock && strcmp(argv[1], "ram"))) return 2;
	int bus = open(stock ? "/dev/i2c-4" : "/dev/i2c-3", O_RDWR | O_CLOEXEC);
	int pmic = open(stock ? "/dev/i2c-1" : "/dev/i2c-0", O_RDWR | O_CLOEXEC);
	int rtc = open("/dev/rtc0", O_RDONLY | O_CLOEXEC);
	if (bus < 0 || pmic < 0 || rtc < 0) { perror("open"); return 1; }
	uint8_t port = 0;
	struct i2c_msg message = { .addr = 0x24, .flags = I2C_M_RD, .len = 1, .buf = &port };
	struct i2c_rdwr_ioctl_data transfer = { .msgs = &message, .nmsgs = 1 };
	if (ioctl(bus, I2C_RDWR, &transfer) != 1) { perror("GPIO raw read"); return 1; }
	printf("GPIO_RAW %02x\n", port);
	if (!stock && read_gpio_asis() != port) return 1;
	for (unsigned reg = 0xbc; reg <= 0xc1; reg++) {
		int value = read_register(pmic, reg);
		if (value < 0) { perror("PMIC clock read"); return 1; }
		printf("CLOCK_REG %02x %02x\n", reg, value);
	}
	struct rtc_time a = {0}, b = {0};
	struct rtc_wkalrm alarm = {0};
	if (ioctl(rtc, RTC_RD_TIME, &a) || ioctl(rtc, RTC_WKALM_RD, &alarm)) { perror("RTC read"); return 1; }
	sleep(2);
	if (ioctl(rtc, RTC_RD_TIME, &b)) { perror("RTC read after"); return 1; }
	printf("RTC %04d-%02d-%02dT%02d:%02d:%02d advance=%" PRId64 " alarm_enabled=%u\n",
		b.tm_year + 1900, b.tm_mon + 1, b.tm_mday, b.tm_hour, b.tm_min, b.tm_sec,
		stamp(&b) - stamp(&a), alarm.enabled);
	close(rtc); close(pmic); close(bus);
	return stamp(&b) - stamp(&a) >= 2 ? 0 : 1;
}
