/* SPDX-License-Identifier: GPL-2.0-only */
/* RAM-only Gen4 I2C-to-evdev bridge for Qt calibration. No reset or firmware commands. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/input.h>
#include <linux/uinput.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

static int setup_axis(int fd, unsigned code, int maximum)
{
    struct uinput_abs_setup axis = {.code = code};
    axis.absinfo.maximum = maximum;
    return ioctl(fd, UI_SET_ABSBIT, code) < 0 ||
           ioctl(fd, UI_ABS_SETUP, &axis) < 0 ? -1 : 0;
}

static int emit(int fd, unsigned type, unsigned code, int value)
{
    struct input_event event = {.type = type, .code = code, .value = value};
    return write(fd, &event, sizeof(event)) == sizeof(event) ? 0 : -1;
}

int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    int bus = open("/dev/i2c-1", O_RDWR | O_CLOEXEC);
    int ui = open("/dev/uinput", O_WRONLY | O_CLOEXEC);
    if (bus < 0 || ui < 0 || ioctl(bus, I2C_SLAVE, 0x67) < 0 ||
        ioctl(ui, UI_SET_EVBIT, EV_KEY) < 0 ||
        ioctl(ui, UI_SET_KEYBIT, BTN_TOUCH) < 0 ||
        ioctl(ui, UI_SET_EVBIT, EV_ABS) < 0 ||
        ioctl(ui, UI_SET_PROPBIT, INPUT_PROP_DIRECT) < 0 ||
        setup_axis(ui, ABS_MT_SLOT, 0) ||
        setup_axis(ui, ABS_MT_TRACKING_ID, 65535) ||
        setup_axis(ui, ABS_MT_POSITION_X, 1279) ||
        setup_axis(ui, ABS_MT_POSITION_Y, 799)) {
        printf("PERRIER_UINPUT_SETUP_ERROR errno=%d bus=%d ui=%d\n", errno, bus, ui);
        return 1;
    }
    struct uinput_setup setup = {.id = {.bustype = BUS_I2C,
                                           .vendor = 0x04b4, .product = 0x0001}};
    strncpy(setup.name, "Perrier CYTTSP4 RAM touch", sizeof(setup.name)-1);
    if (ioctl(ui, UI_DEV_SETUP, &setup) < 0 || ioctl(ui, UI_DEV_CREATE) < 0) {
        printf("PERRIER_UINPUT_CREATE_ERROR errno=%d\n", errno);
        return 1;
    }
    printf("PERRIER_UINPUT_READY raw_coordinates 1280x800\n");
    uint8_t report[64];
    int active = 0, last_x = -1, last_y = -1, tracking = 1;
    unsigned errors = 0;
    for (unsigned sample = 0; sample < 1500; ++sample) {
        uint8_t reg = 0;
        ssize_t selected = write(bus, &reg, 1);
        ssize_t count = selected == 1 ? read(bus, report, sizeof(report)) : -1;
        if (selected != 1 || count != sizeof(report)) {
            if (++errors == 3) break;
            usleep(50000);
            continue;
        }
        errors = 0;
        unsigned contacts = report[11] & 0x1f;
        if (report[2] != 0x66 || report[3] != 0x03 || report[8] != 0x03 ||
            contacts > 7 || report[9] != 2 + 7 * contacts) {
            usleep(50000);
            continue;
        }
        if (contacts) {
            int x = ((int)report[12] << 8) | report[13];
            int y = ((int)report[14] << 8) | report[15];
            if (x < 1280 && y < 800 && (!active || x != last_x || y != last_y)) {
                emit(ui, EV_ABS, ABS_MT_SLOT, 0);
                if (!active) {
                    emit(ui, EV_ABS, ABS_MT_TRACKING_ID, tracking++);
                    emit(ui, EV_KEY, BTN_TOUCH, 1);
                }
                emit(ui, EV_ABS, ABS_MT_POSITION_X, x);
                emit(ui, EV_ABS, ABS_MT_POSITION_Y, y);
                emit(ui, EV_SYN, SYN_REPORT, 0);
                printf("PERRIER_UINPUT_TOUCH x=%d y=%d\n", x, y);
                last_x = x; last_y = y; active = 1;
            }
        } else if (active) {
            emit(ui, EV_ABS, ABS_MT_SLOT, 0);
            emit(ui, EV_ABS, ABS_MT_TRACKING_ID, -1);
            emit(ui, EV_KEY, BTN_TOUCH, 0);
            emit(ui, EV_SYN, SYN_REPORT, 0);
            active = 0;
        }
        usleep(50000);
    }
    printf("PERRIER_UINPUT_STOP errors=%u\n", errors);
    ioctl(ui, UI_DEV_DESTROY);
    close(ui);
    close(bus);
    return errors ? 1 : 0;
}
