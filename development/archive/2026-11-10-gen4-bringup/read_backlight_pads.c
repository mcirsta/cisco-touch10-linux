// SPDX-License-Identifier: GPL-2.0-only
/* Only PROT_READ mappings of already identified GPIO and pad registers. */
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/mman.h>
#include <unistd.h>

int main(void)
{
    int fd = open("/dev/mem", O_RDONLY | O_SYNC);
    if (fd < 0) { perror("open /dev/mem"); return 1; }
    volatile uint32_t *gpio = mmap(NULL, 4096, PROT_READ, MAP_SHARED, fd, 0x4805b000);
    volatile uint16_t *pads = mmap(NULL, 4096, PROT_READ, MAP_SHARED, fd, 0x4a100000);
    if (gpio == MAP_FAILED || pads == MAP_FAILED) { perror("mmap"); return 2; }
    uint32_t oe = gpio[0x134 / 4], out = gpio[0x13c / 4];
    printf("GPIO5_OE=%08x GPIO5_DATAOUT=%08x\n", oe, out);
    printf("GPIO151 output=%u value=%u real_pad_154=%04x wrong_pad_156=%04x\n",
           !(oe & (1u << 23)), !!(out & (1u << 23)), pads[0x154 / 2], pads[0x156 / 2]);
    printf("GPIO157 output=%u value=%u pad_160=%04x\n",
           !(oe & (1u << 29)), !!(out & (1u << 29)), pads[0x160 / 2]);
    printf("GPIO102 pad_092=%04x GPIO163 pad_16c=%04x PWM pad_1d2=%04x\n",
           pads[0x92 / 2], pads[0x16c / 2], pads[0x1d2 / 2]);
    munmap((void *)gpio, 4096);
    munmap((void *)pads, 4096);
    close(fd);
    return 0;
}
