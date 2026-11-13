// SPDX-License-Identifier: GPL-2.0-only
/* Read-only 20-second paired CPUfreq/regulator/VC observation in ram114. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
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
#define COUNT 200

static int number_fd(int fd)
{
	char buf[40], *end;
	long value;
	ssize_t n;

	if (lseek(fd, 0, SEEK_SET) < 0)
		return -1;
	n = read(fd, buf, sizeof(buf) - 1);
	if (n <= 0)
		return -1;
	buf[n] = '\0';
	errno = 0;
	value = strtol(buf, &end, 10);
	if (errno || end == buf || value < 0 || value > 2000000)
		return -1;
	return (int)value;
}

static int exact_file(const char *path, const char *expected)
{
	char buf[100];
	FILE *file = fopen(path, "r");

	if (!file || !fgets(buf, sizeof(buf), file)) {
		if (file)
			fclose(file);
		return 0;
	}
	fclose(file);
	buf[strcspn(buf, "\n")] = '\0';
	return !strcmp(buf, expected);
}

int main(void)
{
	struct utsname name;
	struct timespec start, next, now;
	glob_t matches = { 0 };
	volatile uint32_t *prm;
	char path[256];
	int fd_mem = -1, fd_freq = -1, fd_hw = -1, fd_uv = -1;
	int i, found = 0;
	void *mapping = MAP_FAILED;

	if (getuid() || uname(&name) ||
	    strcmp(name.release, "6.18.48-perrier-ram114") ||
	    !exact_file("/run/touch10-ram", "perrier-interactive-ram114") ||
	    !exact_file("/sys/devices/system/cpu/online", "0-1") ||
	    !exact_file("/sys/devices/system/cpu/cpufreq/policy0/scaling_governor", "schedutil")) {
		fputs("ram114 schedutil preflight failed\n", stderr);
		return 2;
	}
	if (glob("/sys/class/regulator/regulator*/name", 0, NULL, &matches))
		return 2;
	for (i = 0; i < (int)matches.gl_pathc; i++) {
		if (!exact_file(matches.gl_pathv[i], "perrier-vdd-mpu"))
			continue;
		if (found++)
			goto out;
		if (snprintf(path, sizeof(path), "%s", matches.gl_pathv[i]) >=
		    (int)sizeof(path))
			goto out;
		{
			char *leaf = strrchr(path, '/') + 1;
			size_t room = sizeof(path) - (size_t)(leaf - path);

			if (snprintf(leaf, room, "microvolts") >= (int)room)
				goto out;
		}
	}
	if (found != 1)
		goto out;
	fd_freq = open("/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq",
		       O_RDONLY | O_CLOEXEC);
	fd_hw = open("/sys/devices/system/cpu/cpufreq/policy0/cpuinfo_cur_freq",
		     O_RDONLY | O_CLOEXEC);
	fd_uv = open(path, O_RDONLY | O_CLOEXEC);
	fd_mem = open("/dev/mem", O_RDONLY | O_SYNC | O_CLOEXEC);
	if (fd_freq < 0 || fd_hw < 0 || fd_uv < 0 || fd_mem < 0)
		goto out;
	mapping = mmap(NULL, PRM_SIZE, PROT_READ, MAP_SHARED, fd_mem, PRM_BASE);
	if (mapping == MAP_FAILED)
		goto out;
	prm = mapping;
	if (clock_gettime(CLOCK_MONOTONIC, &start))
		goto out;
	next = start;
	puts("ms,policy_khz,hardware_khz,regulator_uv,vc_before,vc_after,valid_before,valid_after,vc_irq");
	for (i = 0; i < COUNT; i++) {
		uint32_t before = prm[0x1ba0u / 4u];
		uint32_t irq = prm[0x10u / 4u];
		int hw = number_fd(fd_hw);
		uint32_t after = prm[0x1ba0u / 4u];
		int freq = number_fd(fd_freq);
		int uv = number_fd(fd_uv);
		long long ms;

		if (hw < 0 || freq < 0 || uv < 0 ||
		    clock_gettime(CLOCK_MONOTONIC, &now))
			goto out;
		ms = (now.tv_sec - start.tv_sec) * 1000LL +
		     (now.tv_nsec - start.tv_nsec) / 1000000LL;
		printf("%lld,%d,%d,%d,%u,%u,%u,%u,%08x\n", ms, freq, hw, uv,
		       (before >> 16) & 0xffu, (after >> 16) & 0xffu,
		       !!(before & (1u << 24)), !!(after & (1u << 24)), irq);
		next.tv_nsec += 100000000;
		if (next.tv_nsec >= 1000000000) {
			next.tv_sec++;
			next.tv_nsec -= 1000000000;
		}
		if (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL))
			goto out;
	}
	munmap(mapping, PRM_SIZE);
	close(fd_mem);
	close(fd_uv);
	close(fd_hw);
	close(fd_freq);
	globfree(&matches);
	return 0;
out:
	fputs("sampler failed\n", stderr);
	if (mapping != MAP_FAILED)
		munmap(mapping, PRM_SIZE);
	if (fd_mem >= 0)
		close(fd_mem);
	if (fd_uv >= 0)
		close(fd_uv);
	if (fd_hw >= 0)
		close(fd_hw);
	if (fd_freq >= 0)
		close(fd_freq);
	globfree(&matches);
	return 2;
}
