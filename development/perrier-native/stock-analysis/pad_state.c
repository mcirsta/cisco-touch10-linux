// SPDX-License-Identifier: GPL-2.0-only
// Read only the four OMAP4460 CORE pad registers relevant to the backlight.
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/mman.h>
#include <unistd.h>

struct pad {
    const char *name;
    unsigned int offset;
};

static const struct pad pads[] = {
    { "usbb1_ulpitll_dat6 / gpio94 / timer10_pwm", 0x0d6 },
    { "mcspi4_clk / gpio151 / backlight_pad", 0x156 },
    { "usbb2_ulpitll_clk / gpio157 / lcd_5v_enable", 0x160 },
    { "dpm_emu18 / gpio190 / timer10_pwm", 0x1d2 },
};

int main(void)
{
    int fd = open("/dev/mem", O_RDONLY | O_SYNC);
    if (fd < 0) {
        perror("open /dev/mem");
        return 1;
    }
    volatile uint16_t *regs = mmap(NULL, 4096, PROT_READ, MAP_SHARED,
                                   fd, 0x4a100000);
    if (regs == MAP_FAILED) {
        perror("map CORE padconf");
        close(fd);
        return 2;
    }
    for (unsigned int i = 0; i < sizeof(pads) / sizeof(pads[0]); i++) {
        uint16_t value = regs[pads[i].offset / 2];
        printf("0x4a100%03x %-46s raw=0x%04x mode=%u\n",
               pads[i].offset, pads[i].name, value, value & 7);
    }
    munmap((void *)regs, 4096);
    close(fd);
    return 0;
}
