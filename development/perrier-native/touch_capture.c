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

#ifdef PERRIER_TOUCH_FEEDBACK
static void draw_mark(uint8_t *pixels, size_t pitch, unsigned x, unsigned y)
{
    if (!pixels || pitch < 1280u * 4u || x >= 1280 || y >= 800) return;
    for (int dy = -22; dy <= 22; ++dy) {
        int py = (int)y + dy;
        if (py < 0 || py >= 800) continue;
        uint32_t *row = (uint32_t *)(pixels + (size_t)py * pitch);
        for (int dx = -22; dx <= 22; ++dx) {
            int px = (int)x + dx;
            if (px < 0 || px >= 1280) continue;
            if (dx > -4 && dx < 4 && dy > -4 && dy < 4)
                row[px] = 0xffffffff; /* white center */
            else if (dx > -19 && dx < 19 && dy > -19 && dy < 19)
                row[px] = 0xffff0000; /* red contact marker */
            else
                row[px] = 0xff000000; /* black outline */
        }
    }
}

static void draw_report(uint8_t *pixels, size_t pitch, const uint8_t *report,
                        unsigned sample)
{
    unsigned contacts = report[11] & 0x1f;
    if (report[2] != 0x66 || report[3] != 0x03 || report[8] != 0x03 ||
        contacts == 0 || contacts > 7 || report[9] != 2 + 7 * contacts)
        return;
    for (unsigned i = 0; i < contacts; ++i) {
        const uint8_t *record = report + 12 + 7 * i;
        unsigned x = ((unsigned)record[0] << 8) | record[1];
        unsigned y = ((unsigned)record[2] << 8) | record[3];
        if (x < 1280 && y < 800) {
            draw_mark(pixels, pitch, x, y);
            printf("PERRIER_TOUCH_FEEDBACK sample=%u contact=%u x=%u y=%u\n",
                   sample, i, x, y);
        }
    }
}
#endif

int touch_capture_run(uint8_t *pixels, size_t pitch)
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
#ifdef PERRIER_TOUCH_FEEDBACK
            draw_report(pixels, pitch, current, sample);
#endif
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

#ifndef PERRIER_TOUCH_FEEDBACK
int main(void)
{
    return touch_capture_run(NULL, 0);
}
#endif
