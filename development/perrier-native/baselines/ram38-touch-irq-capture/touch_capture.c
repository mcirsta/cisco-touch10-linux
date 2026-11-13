/* SPDX-License-Identifier: GPL-2.0-only */
/* Bounded, passive Gen4 touch and IRQ capture during the LCD pattern. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

enum { REPORT_BYTES = 64, SAMPLES = 600, MAX_REPORTS = 48 };

int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    int bus = open("/dev/i2c-1", O_RDWR | O_CLOEXEC);
    int mem = open("/dev/mem", O_RDONLY | O_SYNC);
    volatile uint32_t *gpio = mem < 0 ? MAP_FAILED :
        mmap(NULL, 4096, PROT_READ, MAP_SHARED, mem, 0x4805b000);
    if (bus < 0 || mem < 0 || gpio == MAP_FAILED ||
        ioctl(bus, I2C_SLAVE, 0x67) < 0) {
        printf("PERRIER_TOUCH_CAPTURE_OPEN bus=%d mem=%d gpio=%d errno=%d\n",
               bus, mem, gpio != MAP_FAILED, errno);
        if (gpio != MAP_FAILED) munmap((void *)gpio, 4096);
        if (bus >= 0) close(bus);
        if (mem >= 0) close(mem);
        return 1;
    }
    uint8_t previous[REPORT_BYTES] = {0}, current[REPORT_BYTES];
    unsigned changes = 0, logged = 0, irq_low = 0, irq_edges = 0, errors = 0;
    int old_irq = -1;
    printf("PERRIER_TOUCH_WINDOW_START samples=%u period_ms=50\n", SAMPLES);
    for (unsigned sample = 0; sample < SAMPLES; ++sample) {
        int irq = !!(gpio[0x138 / 4] & (1u << 14));
        if (!irq) irq_low++;
        if (old_irq >= 0 && irq != old_irq) {
            irq_edges++;
            printf("PERRIER_TOUCH_IRQ sample=%u value=%d\n", sample, irq);
        }
        old_irq = irq;
        uint8_t reg = 0;
        ssize_t selected = write(bus, &reg, 1);
        ssize_t count = selected == 1 ? read(bus, current, sizeof(current)) : -1;
        if (selected != 1 || count != sizeof(current)) {
            errors++;
            printf("PERRIER_TOUCH_CAPTURE_ERROR sample=%u select=%zd read=%zd errno=%d\n",
                   sample, selected, count, errno);
            break;
        }
        if (sample == 0 || memcmp(current, previous, sizeof(current))) {
            if (sample) changes++;
            if (logged < MAX_REPORTS) {
                printf("PERRIER_TOUCH_CAPTURE sample=%u irq=%d data=", sample, irq);
                for (unsigned i = 0; i < sizeof(current); ++i)
                    printf("%02x", current[i]);
                printf("\n");
                logged++;
            }
            memcpy(previous, current, sizeof(current));
        }
        usleep(50000);
    }
    printf("PERRIER_TOUCH_WINDOW_END changes=%u logged=%u irq_low=%u irq_edges=%u errors=%u\n",
           changes, logged, irq_low, irq_edges, errors);
    munmap((void *)gpio, 4096);
    close(mem);
    close(bus);
    return errors ? 1 : 0;
}
