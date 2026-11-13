// SPDX-License-Identifier: GPL-2.0-only
/* One bounded 350 MHz Perrier SMPS1 undervolt probe, entirely in RAM. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/utsname.h>
#include <time.h>
#include <unistd.h>

#define PRM_BASE 0x4a306000u
#define PRM_SIZE 8192u
#define VC_VALID (1u << 24)
#define VC_ACK (1u << 14)
#define VC_ERRORS (7u << 11)
#define VC_STATUS (VC_ACK | VC_ERRORS)
#define VC_COMMAND(vsel) (((uint32_t)(vsel) << 16) | (0x55u << 8) | 0x12u)
#ifndef TARGET_SELECTOR
#error TARGET_SELECTOR must be fixed at build time
#endif
#if TARGET_SELECTOR != 0x24 && TARGET_SELECTOR != 0x20
#error Only the reviewed 0x24 and 0x20 steps are permitted
#endif
#define TARGET_UV (709000L + ((TARGET_SELECTOR) - 1L) * 12660L)

static volatile uint32_t *prm;
static char ina_voltage[256];

static uint32_t word(unsigned int offset)
{
	return prm[offset / 4u];
}

static void put(unsigned int offset, uint32_t value)
{
	prm[offset / 4u] = value;
	__sync_synchronize();
}

static long read_number(const char *path)
{
	char buf[80], *end;
	long value;
	FILE *file = fopen(path, "r");

	if (!file || !fgets(buf, sizeof(buf), file)) {
		if (file)
			fclose(file);
		fprintf(stderr, "cannot read %s\n", path);
		return LONG_MIN;
	}
	fclose(file);
	errno = 0;
	value = strtol(buf, &end, 10);
	if (errno || end == buf || (*end != '\n' && *end != '\0')) {
		fprintf(stderr, "invalid number in %s\n", path);
		return LONG_MIN;
	}
	return value;
}

static int exact_file(const char *path, const char *expected)
{
	char buf[100];
	FILE *file = fopen(path, "r");
	int ok;

	if (!file || !fgets(buf, sizeof(buf), file)) {
		if (file)
			fclose(file);
		return 0;
	}
	fclose(file);
	buf[strcspn(buf, "\n")] = '\0';
	ok = strcmp(buf, expected) == 0;
	return ok;
}

static int safe_runtime(void)
{
	struct utsname name;
	glob_t matches = { 0 };
	long temp, clock;
	int ok;

	temp = read_number("/sys/class/thermal/thermal_zone0/temp");
	clock = read_number("/sys/devices/system/cpu/cpufreq/policy0/cpuinfo_cur_freq");
	if (getuid() != 0 || uname(&name) ||
	    strcmp(name.release, "6.18.48-perrier-ram114") ||
	    !exact_file("/run/touch10-ram", "perrier-interactive-ram114") ||
	    !exact_file("/sys/devices/system/cpu/online", "0-1") ||
	    !exact_file("/sys/devices/system/cpu/cpufreq/policy0/scaling_governor", "userspace") ||
	    clock != 350000 || temp < 0 || temp >= 70000 ||
	    !exact_file("/sys/block/mmcblk0/ro", "1"))
		return 0;
	if (glob("/sys/bus/i2c/devices/3-0041/hwmon/hwmon*/in1_input",
		  0, NULL, &matches) || matches.gl_pathc != 1) {
		globfree(&matches);
		return 0;
	}
	ok = snprintf(ina_voltage, sizeof(ina_voltage), "%s",
		      matches.gl_pathv[0]) < (int)sizeof(ina_voltage);
	globfree(&matches);
	return ok;
}

static int expected_prm(void)
{
	static const struct { unsigned int offset; uint32_t value; } expected[] = {
		{ 0x1b10u, 0x00000300u }, /* PRM_VOLTCTRL */
		{ 0x1b58u, 0x00000000u }, /* MPU VP disabled */
		{ 0x1b64u, 0x00011129u }, /* inherited MPU VP selector */
		{ 0x1b88u, 0x00121212u }, /* TWL6032 slave addresses */
		{ 0x1b8cu, 0x0055495bu }, /* voltage register map */
		{ 0x1b90u, 0x00564a5cu }, /* command register map */
		{ 0x1b98u, 0x29290500u }, /* MPU ON/RET/OFF */
		{ 0x1ba4u, 0x00001717u }, /* VC channel config */
		{ 0x1ba8u, 0x00000000u }, /* VC I2C mode */
		{ 0x1bacu, 0x00006026u }, /* inherited VC I2C clock */
	};
	size_t i;

	for (i = 0; i < sizeof(expected) / sizeof(expected[0]); i++) {
		if (word(expected[i].offset) != expected[i].value) {
			fprintf(stderr, "PRM preflight failed at %08x: %08x != %08x\n",
				PRM_BASE + expected[i].offset,
				word(expected[i].offset), expected[i].value);
			return 0;
		}
	}
	return word(0x1ba0u) == VC_COMMAND(0x28u) &&
	       !(word(0x10u) & VC_ERRORS);
}

static int command(uint8_t selector)
{
	const uint32_t value = VC_COMMAND(selector);
	struct timespec start, now, nap = { 0, 50000 };
	uint32_t status, observed;
	long long elapsed_ns;

	/* Clear only prior bypass acknowledgement/error status (W1C). */
	put(0x10u, VC_STATUS);
	if (word(0x10u) & VC_STATUS) {
		fprintf(stderr, "VC status did not clear: %08x\n", word(0x10u));
		return 0;
	}
	put(0x1ba0u, value);
	put(0x1ba0u, value | VC_VALID);
	if (clock_gettime(CLOCK_MONOTONIC, &start))
		return 0;
	do {
		observed = word(0x1ba0u);
		if (!(observed & VC_VALID))
			break;
		nanosleep(&nap, NULL);
		if (clock_gettime(CLOCK_MONOTONIC, &now))
			return 0;
		elapsed_ns = (now.tv_sec - start.tv_sec) * 1000000000LL +
			(now.tv_nsec - start.tv_nsec);
	} while (elapsed_ns < 100000000LL);
	status = word(0x10u);
	printf("VC selector=%02x bypass=%08x irq=%08x\n", selector,
	       word(0x1ba0u), status);
	return !(word(0x1ba0u) & VC_VALID) &&
	       (status & VC_STATUS) == VC_ACK &&
	       (observed & ~VC_VALID) == value;
}

static int sample(const char *label, long *millivolt, long min_mv, long max_mv)
{
	long voltage = read_number(ina_voltage);
	long temp = read_number("/sys/class/thermal/thermal_zone0/temp");
	long clock = read_number("/sys/devices/system/cpu/cpufreq/policy0/cpuinfo_cur_freq");

	printf("SAMPLE %s mV=%ld temp_mC=%ld kHz=%ld\n", label,
	       voltage, temp, clock);
	*millivolt = voltage;
	return voltage >= min_mv && voltage <= max_mv && temp < 75000 &&
	       clock == 350000 && exact_file("/sys/devices/system/cpu/online", "0-1");
}

int main(void)
{
	struct timespec settle = { 2, 0 }, restore_settle = { 0, 500000000 };
	long before = 0, low = 0, restored = 0;
	int fd, lower_started = 0, failed = 0, restore_ok = 0;
	void *mapping;

	setvbuf(stdout, NULL, _IONBF, 0);
	if (!safe_runtime()) {
		fputs("RAM runtime preflight failed\n", stderr);
		return 2;
	}
	fd = open("/dev/mem", O_RDWR | O_SYNC | O_CLOEXEC);
	if (fd < 0) {
		perror("open /dev/mem");
		return 2;
	}
	mapping = mmap(NULL, PRM_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED,
		       fd, PRM_BASE);
	if (mapping == MAP_FAILED) {
		perror("mmap PRM");
		close(fd);
		return 2;
	}
	prm = mapping;
	if (!expected_prm() || !sample("before", &before, 1160, 1240)) {
		fputs("PRM or rail preflight failed\n", stderr);
		failed = 1;
		goto out;
	}
	lower_started = 1;
	if (!command(TARGET_SELECTOR)) {
		fputs("lower command failed; restoring selector\n", stderr);
		failed = 1;
		goto restore;
	}
	nanosleep(&settle, NULL);
	if (!sample("low", &low, TARGET_UV / 1000 - 35,
	            TARGET_UV / 1000 + 35) ||
	    low > before - (TARGET_SELECTOR == 0x24 ? 20 : 60)) {
		fputs("lower rail check failed; restoring selector\n", stderr);
		failed = 1;
	}
restore:
	if (lower_started) {
		if (!(word(0x1ba0u) & VC_VALID))
			restore_ok = command(0x28u);
		else
			fputs("VC command still pending; host must reboot stock\n", stderr);
		if (restore_ok) {
			nanosleep(&restore_settle, NULL);
			if (!sample("restored", &restored, 1160, 1240) ||
			    labs(restored - before) > 16)
				restore_ok = 0;
		}
		if (!restore_ok)
			failed = 1;
	}
	if (!failed && restore_ok)
		printf("VC_LOW_STEP_PASS target=%02x\n", TARGET_SELECTOR);
out:
	munmap(mapping, PRM_SIZE);
	close(fd);
	return failed ? 1 : 0;
}
