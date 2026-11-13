/* SPDX-License-Identifier: GPL-2.0-only */
/* Bounded Gen4 descriptor capture; always attempt to restore operational mode.
 * Implements only the host-mode transition and handshake from upstream cyttsp4.
 */
#include <errno.h>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <unistd.h>

static int read_at(int fd, uint8_t reg, void *buf, size_t count)
{
    return write(fd, &reg, 1) == 1 && read(fd, buf, count) == (ssize_t)count ? 0 : -1;
}

static int write_mode(int fd, uint8_t mode)
{
    uint8_t data[2] = {0, mode};
    return write(fd, data, sizeof(data)) == sizeof(data) ? 0 : -1;
}

static int set_mode(int fd, uint8_t requested)
{
    uint8_t mode;
    if (read_at(fd, 0, &mode, 1) || (mode & 7)) return -1;
    if (write_mode(fd, (mode & 0x80) | requested | 8)) return -1;
    for (unsigned i = 0; i < 100; i++) {
        usleep(10000);
        if (read_at(fd, 0, &mode, 1)) return -1;
        if ((mode & 0x7f) == requested) return 0;
    }
    return -1;
}

int main(void)
{
    uint8_t data[256], mode;
    int result = 1, restore;
    int fd = open("/dev/i2c-1", O_RDWR | O_CLOEXEC);
    setvbuf(stdout, NULL, _IONBF, 0);
    if (fd < 0 || ioctl(fd, I2C_SLAVE, 0x67) || read_at(fd, 0, &mode, 1) ||
        (mode & 0x7f)) {
        puts("SYSINFO_NOT_OPERATIONAL");
        return 1;
    }
    if (!set_mode(fd, 0x10) && !read_at(fd, 0, data, sizeof(data))) {
        printf("SYSINFO_DATA ");
        for (unsigned i = 0; i < sizeof(data); i++) printf("%02x", data[i]);
        puts("");
        if (!write_mode(fd, data[0] ^ 0x80)) result = 0;
    }
    restore = set_mode(fd, 0);
    if (!restore && !read_at(fd, 0, &mode, 1))
        restore = write_mode(fd, mode ^ 0x80);
    printf("SYSINFO_RESTORE_OPERATIONAL result=%d errno=%d\n", restore, errno);
    close(fd);
    return result || restore;
}
