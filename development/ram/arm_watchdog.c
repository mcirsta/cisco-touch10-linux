/* SPDX-License-Identifier: GPL-2.0-only */
/* Arm this board's existing watchdog through its kernel API, then close it.
 * Exact stock release/shutdown paths were audited: NOWAYOUT leaves it running
 * after close, and shutdown skips an unopened watchdog. No MMIO or storage IO.
 */
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define WDIOC_KEEPALIVE _IOR('W', 5, int)
#define WDIOC_SETTIMEOUT _IOWR('W', 6, int)
#define WDIOC_GETTIMEOUT _IOR('W', 7, int)

int main(int argc, char **argv)
{
    if (argc != 2 || (strcmp(argv[1], "15") && strcmp(argv[1], "120"))) {
        fprintf(stderr, "Usage: arm-watchdog 15|120 (arms timer and closes; requires verified NOWAYOUT)\n");
        return 2;
    }
    int requested = atoi(argv[1]), actual = requested;
    int fd = open("/dev/watchdog", O_WRONLY | O_CLOEXEC);
    if (fd < 0) { perror("open watchdog"); return 1; }
    if (ioctl(fd, WDIOC_SETTIMEOUT, &actual) ||
        ioctl(fd, WDIOC_GETTIMEOUT, &actual) || actual != requested ||
        ioctl(fd, WDIOC_KEEPALIVE, 0)) {
        perror("configure watchdog");
        close(fd);
        return 1;
    }
    if (close(fd)) { perror("close watchdog"); return 1; }
    printf("WATCHDOG_ARMED_CLOSED=%d\n", actual);
    return 0;
}
