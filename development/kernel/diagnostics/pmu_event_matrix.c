// SPDX-License-Identifier: GPL-2.0-only
// Bounded perf API characterization; no direct coprocessor or debug writes.
#include <linux/perf_event.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>

int main(void)
{
	const unsigned events[] = { 0x01, 0x03, 0x04, 0x06, 0x07, 0x08, 0x0c, 0x11, 0x68 };
	for (unsigned i = 0; i < sizeof(events) / sizeof(events[0]); ++i) {
		struct perf_event_attr attr = {0};
		attr.type = PERF_TYPE_RAW;
		attr.size = PERF_ATTR_SIZE_VER0;
		attr.config = events[i];
		attr.disabled = 1;
		attr.read_format = PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING;
		int fd = syscall(__NR_perf_event_open, &attr, 0, -1, -1, 0);
		if (fd < 0) { perror("Raw event open"); return 1; }
		if (ioctl(fd, PERF_EVENT_IOC_ENABLE, 0)) return 1;
		volatile uint32_t value = 1;
		for (unsigned j = 0; j < 1000000; ++j) value = (value * 1664525 + 1013904223) ^ j;
		if (ioctl(fd, PERF_EVENT_IOC_DISABLE, 0)) return 1;
		struct { uint64_t value, enabled, running; } result;
		if (read(fd, &result, sizeof(result)) != sizeof(result)) return 1;
		printf("RAW event=%02x count=%llu enabled_ns=%llu running_ns=%llu checksum=%u\n",
			events[i], (unsigned long long)result.value,
			(unsigned long long)result.enabled, (unsigned long long)result.running, value);
		close(fd);
	}
	return 0;
}
