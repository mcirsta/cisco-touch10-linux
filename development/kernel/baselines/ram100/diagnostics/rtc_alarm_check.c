// SPDX-License-Identifier: GPL-2.0-only
// One RTC alarm event; restore cached alarm and exact original alarm/IRQ bytes.
#include <errno.h>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <linux/rtc.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t stopped;
static void stop(int signal) { (void)signal; stopped = 1; }

static int read_bytes(int fd, uint8_t reg, uint8_t *data, unsigned count)
{
	struct i2c_msg messages[] = {
		{ .addr = 0x48, .len = 1, .buf = &reg },
		{ .addr = 0x48, .flags = I2C_M_RD, .len = count, .buf = data },
	};
	struct i2c_rdwr_ioctl_data transfer = { .msgs = messages, .nmsgs = 2 };
	return ioctl(fd, I2C_RDWR, &transfer) == 2 ? 0 : -1;
}

static int restore_alarm_bytes(int fd, const uint8_t alarm[6], uint8_t irq)
{
	uint8_t saved[7] = {0x08};
	uint8_t saved_irq[2] = {0x12, irq};
	memcpy(saved + 1, alarm, 6);
	struct i2c_msg messages[] = {
		{ .addr = 0x48, .len = sizeof(saved), .buf = saved },
		{ .addr = 0x48, .len = sizeof(saved_irq), .buf = saved_irq },
	};
	struct i2c_rdwr_ioctl_data transfer = { .msgs = messages, .nmsgs = 2 };
	return ioctl(fd, I2C_RDWR, &transfer) == 2 ? 0 : -1;
}

static double monotonic(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec + t.tv_nsec / 1e9;
}

int main(void)
{
	signal(SIGTERM, stop); signal(SIGINT, stop); signal(SIGHUP, stop);
	int rtc = open("/dev/rtc0", O_RDWR | O_NONBLOCK | O_CLOEXEC);
	int bus = open("/dev/i2c-0", O_RDWR | O_CLOEXEC);
	if (rtc < 0 || bus < 0) { perror("RTC test open"); return 1; }
	struct rtc_wkalrm original = {0}, test = {0};
	struct rtc_time now = {0};
	uint8_t saved[6], old_irq = 255, after[6], irq_after = 255;
	if (ioctl(rtc, RTC_WKALM_RD, &original) || ioctl(rtc, RTC_RD_TIME, &now) ||
	    read_bytes(bus, 0x08, saved, 6) || read_bytes(bus, 0x12, &old_irq, 1)) {
		perror("RTC backup"); return 1;
	}
	if (original.enabled || old_irq != 0) {
		fputs("RTC test requires an idle, disabled alarm\n", stderr); return 1;
	}
	struct tm tm = { .tm_sec = now.tm_sec, .tm_min = now.tm_min, .tm_hour = now.tm_hour,
		.tm_mday = now.tm_mday, .tm_mon = now.tm_mon, .tm_year = now.tm_year };
	time_t target = timegm(&tm) + 5;
	if (!gmtime_r(&target, &tm)) return 1;
	test.time.tm_sec = tm.tm_sec; test.time.tm_min = tm.tm_min; test.time.tm_hour = tm.tm_hour;
	test.time.tm_mday = tm.tm_mday; test.time.tm_mon = tm.tm_mon; test.time.tm_year = tm.tm_year;
	test.enabled = 1;
	unsigned long event = 0;
	while (read(rtc, &event, sizeof(event)) > 0) { }
	double start = monotonic();
	int ok = 0;
	if (ioctl(rtc, RTC_WKALM_SET, &test)) {
		perror("RTC arm");
	} else {
		struct pollfd pollfd = { .fd = rtc, .events = POLLIN };
		if (!stopped && poll(&pollfd, 1, 10000) > 0 &&
		    read(rtc, &event, sizeof(event)) == sizeof(event) && (event & RTC_AF)) ok = 1;
	}
	double elapsed = monotonic() - start;
	// A disabled RTC_WKALM_SET restores the core cache but not the hardware
	// alarm bytes. Restore those exact saved bytes too; never set calendar time.
	int cached = ioctl(rtc, RTC_WKALM_SET, &original);
	int disabled = ioctl(rtc, RTC_AIE_OFF, 0);
	int restored = restore_alarm_bytes(bus, saved, old_irq);
	if (read_bytes(bus, 0x08, after, 6) || read_bytes(bus, 0x12, &irq_after, 1)) restored = -1;
	int same = !restored && !memcmp(saved, after, 6) && irq_after == old_irq;
	printf("RTC_ALARM fired=%d event=%08lx elapsed=%.3f cached_restored=%d disabled=%d bytes_restored=%d\n",
		ok, event, elapsed, cached == 0, disabled == 0, same);
	close(bus); close(rtc);
	return ok && cached == 0 && disabled == 0 && same && elapsed >= 3 && elapsed < 9 ? 0 : 1;
}
