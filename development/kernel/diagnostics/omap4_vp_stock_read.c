// SPDX-License-Identifier: GPL-2.0-only
/*
 * Read-only OMAP4460 voltage-processor snapshot for stock Linux.
 *
 * The physical page and five word offsets are fixed at build time. This
 * helper opens /dev/mem read-only, maps one page read-only, reads only the
 * documented OMAP4 PRM registers below, and exits. It has no arguments or
 * device write path. Values are raw programmed selectors, not measured VDD.
 */

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#define PRM_PAGE_BASE 0x4a307000u
#define PRM_PAGE_SIZE 4096u

static const struct {
	const char *name;
	unsigned int offset;
} registers[] = {
	{ "vp_core_voltage", 0xb4cu },
	{ "vp_mpu_config", 0xb58u },
	{ "vp_mpu_voltage", 0xb64u },
	{ "vp_iva_voltage", 0xb7cu },
	{ "vc_mpu_command", 0xb98u },
};

int main(void)
{
	void *mapping;
	int fd;
	size_t i;

	if (sysconf(_SC_PAGESIZE) != PRM_PAGE_SIZE) {
		fputs("unexpected page size\n", stderr);
		return 1;
	}
	fd = open("/dev/mem", O_RDONLY | O_SYNC | O_CLOEXEC);
	if (fd < 0) {
		fprintf(stderr, "open /dev/mem: %s\n", strerror(errno));
		return 1;
	}
	mapping = mmap(NULL, PRM_PAGE_SIZE, PROT_READ, MAP_SHARED, fd,
		       PRM_PAGE_BASE);
	if (mapping == MAP_FAILED) {
		fprintf(stderr, "mmap PRM page: %s\n", strerror(errno));
		close(fd);
		return 1;
	}
	for (i = 0; i < sizeof(registers) / sizeof(registers[0]); i++) {
		const unsigned int offset = registers[i].offset;
		const volatile uint32_t *word =
			(const volatile uint32_t *)((const char *)mapping + offset);
		const uint32_t value = *word;

		printf("%s,0x%08x,0x%08x\n", registers[i].name,
		       PRM_PAGE_BASE + offset, value);
	}
	munmap(mapping, PRM_PAGE_SIZE);
	close(fd);
	return 0;
}
