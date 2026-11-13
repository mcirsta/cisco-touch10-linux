// SPDX-License-Identifier: GPL-2.0-only
// Read only CORE pad mux candidates for the three-key matrix. The same
// keypad signal can appear on multiple OMAP4 pads; this does not select one.
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/mman.h>
#include <unistd.h>

struct pad { const char *name; unsigned int offset; };
static const struct pad pads[] = {
    { "row0 candidate A", 0x050 },
    { "row1 candidate A", 0x052 },
    { "col4 candidate A", 0x060 },
    { "col5 candidate A", 0x062 },
    { "col4 candidate B", 0x068 },
    { "col5 candidate B", 0x06a },
    { "col4 candidate C", 0x17e },
    { "col5 candidate C", 0x180 },
    { "col4 candidate D", 0x184 },
    { "col5 candidate D", 0x186 },
    { "row0 candidate B", 0x188 },
    { "row1 candidate B", 0x18a },
    { "row0 candidate C", 0x18e },
    { "row1 candidate C", 0x190 },
};

int main(void)
{
    int fd = open("/dev/mem", O_RDONLY | O_SYNC);
    if (fd < 0) { perror("open /dev/mem"); return 1; }
    volatile const uint16_t *regs = mmap(NULL, 4096, PROT_READ, MAP_SHARED,
                                         fd, 0x4a100000);
    if (regs == MAP_FAILED) { perror("map CORE padconf"); close(fd); return 2; }
    for (unsigned int i = 0; i < sizeof(pads)/sizeof(pads[0]); i++) {
        uint16_t value = regs[pads[i].offset/2];
        printf("0x4a100%03x %-16s raw=0x%04x mode=%u\n",
               pads[i].offset, pads[i].name, value, value & 7);
    }
    munmap((void *)regs, 4096);
    close(fd);
    return 0;
}
