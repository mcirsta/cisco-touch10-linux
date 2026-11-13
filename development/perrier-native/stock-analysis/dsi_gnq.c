// SPDX-License-Identifier: GPL-2.0-only
// Read-only OMAP4 DSI generic capabilities register.
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/mman.h>
#include <unistd.h>

int main(void)
{
    int fd = open("/dev/mem", O_RDONLY | O_SYNC);
    if (fd < 0) { perror("open"); return 1; }
    volatile uint32_t *dsi = mmap(NULL, 4096, PROT_READ, MAP_SHARED,
                                  fd, 0x58004000);
    if (dsi == MAP_FAILED) { perror("mmap"); close(fd); return 2; }
    uint32_t gnq = dsi[0x44 / 4];
    printf("DSI_GNQ=%08x VP1_LINE_BUFFER_SIZE=%u\n", gnq, (gnq >> 12) & 7);
    munmap((void *)dsi, 4096);
    close(fd);
    return 0;
}
