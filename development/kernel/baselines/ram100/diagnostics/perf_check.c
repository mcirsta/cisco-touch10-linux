// SPDX-License-Identifier: GPL-2.0-only
// Bounded userspace PMU counters and overflow sampling through perf_event_open.
#include <errno.h>
#include <linux/perf_event.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

struct result { uint64_t value, enabled, running; };

static int event(uint64_t config, uint64_t period)
{
	struct perf_event_attr attr = {0};
	attr.type = PERF_TYPE_HARDWARE;
	attr.size = PERF_ATTR_SIZE_VER0; // Also supported by the stock 3.4 ABI.
	attr.config = config;
	attr.disabled = 1;
	// Cortex-A9 has no per-mode event filtering. Count this task in all
	// modes rather than requesting unsupported user-only filtering.
	attr.read_format = PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING;
	attr.sample_period = period;
	attr.sample_type = PERF_SAMPLE_IP;
	attr.wakeup_events = 1;
	return syscall(__NR_perf_event_open, &attr, 0, -1, -1, 0);
}

static uint64_t nanoseconds(void)
{
	struct timespec now;
	clock_gettime(CLOCK_MONOTONIC, &now);
	return (uint64_t)now.tv_sec * 1000000000 + now.tv_nsec;
}

int main(void)
{
	int cycles = event(PERF_COUNT_HW_CPU_CYCLES, 1000000);
	int instructions = event(PERF_COUNT_HW_INSTRUCTIONS, 0);
	if (cycles < 0 || instructions < 0) { perror("PMU event open"); return 1; }
	long page = sysconf(_SC_PAGESIZE);
	size_t map_size = page * 9;
	struct perf_event_mmap_page *metadata = mmap(NULL, map_size, PROT_READ | PROT_WRITE,
							MAP_SHARED, cycles, 0);
	if (metadata == MAP_FAILED) { perror("PMU ring"); return 1; }
	if (ioctl(cycles, PERF_EVENT_IOC_ENABLE, 0) || ioctl(instructions, PERF_EVENT_IOC_ENABLE, 0)) {
		perror("PMU enable"); return 1;
	}
	uint64_t start = nanoseconds();
	volatile uint32_t value = 1;
	for (unsigned i = 0; i < 5000000; ++i) value = (value * 1664525 + 1013904223) ^ i;
	uint64_t elapsed = nanoseconds() - start;
	if (ioctl(instructions, PERF_EVENT_IOC_DISABLE, 0) || ioctl(cycles, PERF_EVENT_IOC_DISABLE, 0)) return 1;
	struct result c, ins;
	if (read(cycles, &c, sizeof(c)) != sizeof(c) || read(instructions, &ins, sizeof(ins)) != sizeof(ins)) return 1;
	__sync_synchronize();
	uint64_t head = metadata->data_head;
	unsigned samples = 0, lost = 0;
	uint64_t offset = 0;
	char *ring = (char *)metadata + page;
	while (offset < head && head <= (uint64_t)page * 8) {
		struct perf_event_header header;
		memcpy(&header, ring + offset, sizeof(header));
		if (header.size < sizeof(header) || offset + header.size > head) return 1;
		if (header.type == PERF_RECORD_SAMPLE) ++samples;
		if (header.type == PERF_RECORD_LOST) ++lost;
		offset += header.size;
	}
	printf("PMU cycles=%llu instructions=%llu elapsed_ns=%llu samples=%u lost=%u head=%llu enabled_ns=%llu running_ns=%llu checksum=%u\n",
		(unsigned long long)c.value, (unsigned long long)ins.value,
		(unsigned long long)elapsed, samples, lost, (unsigned long long)head,
		(unsigned long long)c.enabled, (unsigned long long)c.running, value);
	munmap(metadata, map_size);
	close(instructions); close(cycles);
	return c.value > 1000000 && ins.value > 1000000 && samples > 0 && !lost && offset == head ? 0 : 1;
}
