// SPDX-License-Identifier: GPL-2.0-only
/*
 * Fixed, read-only OMAP4460 PRM voltage-controller/processor snapshot.
 *
 * All words are documented at 0x4a307b10..0x4a307bac in the OMAP4460 TRM.
 * They occupy one 4 KiB page. This program has no arguments, write-capable
 * mapping, ioctl, device register write or persistent-storage path.
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
	{ "voltctrl", 0xb10u },
	{ "voltsetup_core_off", 0xb28u },
	{ "voltsetup_mpu_off", 0xb2cu },
	{ "voltsetup_iva_off", 0xb30u },
	{ "voltsetup_core_ret_sleep", 0xb34u },
	{ "voltsetup_mpu_ret_sleep", 0xb38u },
	{ "voltsetup_iva_ret_sleep", 0xb3cu },
	{ "vp_core_config", 0xb40u },
	{ "vp_core_vlimitto", 0xb48u },
	{ "vp_core_voltage", 0xb4cu },
	{ "vp_core_vstepmax", 0xb50u },
	{ "vp_core_vstepmin", 0xb54u },
	{ "vp_mpu_config", 0xb58u },
	{ "vp_mpu_vlimitto", 0xb60u },
	{ "vp_mpu_voltage", 0xb64u },
	{ "vp_mpu_vstepmax", 0xb68u },
	{ "vp_mpu_vstepmin", 0xb6cu },
	{ "vp_iva_config", 0xb70u },
	{ "vp_iva_vlimitto", 0xb78u },
	{ "vp_iva_voltage", 0xb7cu },
	{ "vp_iva_vstepmax", 0xb80u },
	{ "vp_iva_vstepmin", 0xb84u },
	{ "vc_smps_sa", 0xb88u },
	{ "vc_smps_ra_vol", 0xb8cu },
	{ "vc_smps_ra_cmd", 0xb90u },
	{ "vc_core_command", 0xb94u },
	{ "vc_mpu_command", 0xb98u },
	{ "vc_iva_command", 0xb9cu },
	{ "vc_cfg_channel", 0xba4u },
	{ "vc_cfg_i2c_mode", 0xba8u },
	{ "vc_cfg_i2c_clk", 0xbacu },
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
