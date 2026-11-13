// SPDX-License-Identifier: GPL-2.0-only
// Passive clock, PWM and GPIO snapshot. All maps are PROT_READ.
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/mman.h>
#include <unistd.h>

static volatile uint32_t *map_page(int fd, uintptr_t base)
{
    return mmap(NULL, 4096, PROT_READ, MAP_SHARED, fd, base);
}

int main(void)
{
    int fd = open("/dev/mem", O_RDONLY | O_SYNC);
    if (fd < 0) { perror("open /dev/mem"); return 1; }
    volatile uint32_t *cm = map_page(fd, 0x4a009000);
    if (cm == MAP_FAILED) { perror("map CM2 L4PER"); close(fd); return 2; }
    // CM2 + L4_PER_CM(0x1400) + TIMER10_CLKCTRL(0x28) / GPIO5(0x78).
    uint32_t timerclk = cm[0x428 / 4], gpioclk = cm[0x478 / 4];
    uint32_t gpio4clk = cm[0x470 / 4], gpio6clk = cm[0x480 / 4];
    printf("PERRIER_BACKLIGHT_CLOCK timer10=%08x gpio5=%08x\n", timerclk, gpioclk);
    printf("PERRIER_RAIL_CLOCK gpio4=%08x gpio6=%08x\n", gpio4clk, gpio6clk);
    munmap((void *)cm, 4096);
    if ((timerclk & 3) != 0) {
        volatile uint32_t *timer = map_page(fd, 0x48086000);
        if (timer != MAP_FAILED) {
            uint32_t count0 = timer[0x28 / 4];
            usleep(5000);
            uint32_t count1 = timer[0x28 / 4];
            printf("PERRIER_BACKLIGHT_TIMER tclr=%08x tcrr0=%08x tcrr1=%08x tldr=%08x tmar=%08x\n",
                   timer[0x24 / 4], count0, count1, timer[0x2c / 4], timer[0x38 / 4]);
            munmap((void *)timer, 4096);
        } else perror("map timer10");
    }
    if ((gpioclk & 3) != 0) {
        volatile uint32_t *gpio = map_page(fd, 0x4805b000);
        if (gpio != MAP_FAILED) {
            uint32_t oe = gpio[0x134 / 4], in = gpio[0x138 / 4];
            uint32_t out = gpio[0x13c / 4];
            printf("PERRIER_BACKLIGHT_GPIO5 oe=%08x out=%08x gpio151_out=%u gpio151_output=%u gpio157_out=%u gpio157_output=%u\n",
                   oe, out, !!(out & (1u << 23)), !(oe & (1u << 23)),
                   !!(out & (1u << 29)), !(oe & (1u << 29)));
            printf("PERRIER_TOUCH_GPIO5 gpio141_reset_out=%u gpio141_output=%u gpio142_irq_in=%u gpio142_input=%u in=%08x\n",
                   !!(out & (1u << 13)), !(oe & (1u << 13)),
                   !!(in & (1u << 14)), !!(oe & (1u << 14)), in);
            munmap((void *)gpio, 4096);
        } else perror("map gpio5");
    }
    if ((gpio4clk & 3) != 0) {
        volatile uint32_t *gpio = map_page(fd, 0x48059000);
        if (gpio != MAP_FAILED) {
            uint32_t oe = gpio[0x134 / 4], in = gpio[0x138 / 4];
            uint32_t out = gpio[0x13c / 4];
            printf("PERRIER_BRIDGE_RESET_GPIO oe=%08x in=%08x out=%08x gpio102_out=%u gpio102_output=%u gpio102_in=%u\n",
                   oe, in, out, !!(out & (1u << 6)), !(oe & (1u << 6)),
                   !!(in & (1u << 6)));
            printf("PERRIER_TOUCH_POWER_GPIO4 gpio120_5v_out=%u gpio120_output=%u gpio121_3v3_out=%u gpio121_output=%u\n",
                   !!(out & (1u << 24)), !(oe & (1u << 24)),
                   !!(out & (1u << 25)), !(oe & (1u << 25)));
            munmap((void *)gpio, 4096);
        } else perror("map gpio4");
    }
    if ((gpio6clk & 3) != 0) {
        volatile uint32_t *gpio = map_page(fd, 0x4805d000);
        if (gpio != MAP_FAILED) {
            uint32_t oe = gpio[0x134 / 4], in = gpio[0x138 / 4];
            uint32_t out = gpio[0x13c / 4];
            printf("PERRIER_PANEL_RAIL_GPIO oe=%08x in=%08x out=%08x gpio163_out=%u gpio163_output=%u gpio163_in=%u\n",
                   oe, in, out, !!(out & (1u << 3)), !(oe & (1u << 3)),
                   !!(in & (1u << 3)));
            munmap((void *)gpio, 4096);
        } else perror("map gpio6");
    }
    close(fd);
    return 0;
}
