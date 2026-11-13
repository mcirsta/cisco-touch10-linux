/* SPDX-License-Identifier: GPL-2.0-only */
/* Bounded host lease through the mainline watchdog API; no register access. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/watchdog.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/ioctl.h>
#include <sys/reboot.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#define SOCKET_PATH "/run/ram-guard.sock"
#define TIMEOUT_SECONDS 120

static double monotonic(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) _exit(2);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

static int board_ok(void)
{
    char data[256];
    int fd = open("/proc/device-tree/compatible", O_RDONLY | O_CLOEXEC);
    if (fd < 0) return 0;
    ssize_t n = read(fd, data, sizeof(data));
    close(fd);
    return n > 0 && memmem(data, n, "cisco,perrier-ram\0", 18);
}

static int sysfs_equals(const char *name, const char *expected)
{
    char path[128], value[128] = {0};
    snprintf(path, sizeof(path), "/sys/class/watchdog/watchdog0/%s", name);
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return 0;
    ssize_t n = read(fd, value, sizeof(value) - 1);
    close(fd);
    if (n <= 0) return 0;
    value[strcspn(value, "\r\n")] = 0;
    return !strcmp(value, expected);
}

static int command(const char *cmd)
{
    int s = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    struct sockaddr_un addr = {.sun_family = AF_UNIX};
    strcpy(addr.sun_path, SOCKET_PATH);
    if (s < 0 || sendto(s, cmd, strlen(cmd), 0,
                       (struct sockaddr *)&addr, sizeof(addr)) != (ssize_t)strlen(cmd)) {
        perror("ram-guard command");
        if (s >= 0) close(s);
        return 1;
    }
    close(s);
    return 0;
}

static int state(int fd, const char *mode, double lease, unsigned pings)
{
    int remaining;
    if (ioctl(fd, WDIOC_GETTIMELEFT, &remaining) ||
        remaining < 0 || remaining > TIMEOUT_SECONDS)
        return -1;
    FILE *f = fopen("/run/guard.json.tmp", "w");
    if (!f) return -1;
    int result = fprintf(f, "{\"pid\":%ld,\"state\":\"%s\","
                         "\"backend\":\"linux-watchdog\",\"monotonic\":%.3f,"
                         "\"lease_deadline\":%.3f,\"pings\":%u,"
                         "\"timeleft_seconds\":%d,\"timeout_seconds\":120,"
                         "\"nowayout\":true}\n",
                         (long)getpid(), mode, monotonic(), lease, pings, remaining);
    int failed = result < 0;
    if (fclose(f)) failed = 1;
    if (failed || rename("/run/guard.json.tmp", "/run/guard.json")) return -1;
    return 0;
}

int main(int argc, char **argv)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    if (argc != 2) return 2;
    if (!strcmp(argv[1], "renew") || !strcmp(argv[1], "expire") || !strcmp(argv[1], "reboot"))
        return command(argv[1]);
    if (strcmp(argv[1], "daemon")) return 2;
    if (!board_ok() || !sysfs_equals("identity", "OMAP Watchdog") ||
        !sysfs_equals("nowayout", "1")) {
        fprintf(stderr, "wrong board or missing OMAP nowayout watchdog\n");
        return 1;
    }
    int lock = open("/run/ram-guard.lock", O_RDWR | O_CREAT | O_CLOEXEC, 0600);
    if (lock < 0 || flock(lock, LOCK_EX | LOCK_NB)) {
        perror("watchdog lock");
        return 1;
    }
    int s = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    struct sockaddr_un addr = {.sun_family = AF_UNIX};
    strcpy(addr.sun_path, SOCKET_PATH);
    unlink(SOCKET_PATH);
    if (s < 0 || bind(s, (struct sockaddr *)&addr, sizeof(addr)) || chmod(SOCKET_PATH, 0600)) {
        perror("watchdog socket");
        return 1;
    }
    int fd = open("/dev/watchdog0", O_WRONLY | O_CLOEXEC);
    struct watchdog_info info = {0};
    int timeout = 0;
    if (fd < 0 || ioctl(fd, WDIOC_GETSUPPORT, &info) ||
        strncmp((char *)info.identity, "OMAP Watchdog", sizeof(info.identity)) ||
        ioctl(fd, WDIOC_GETTIMEOUT, &timeout) || timeout != TIMEOUT_SECONDS ||
        ioctl(fd, WDIOC_KEEPALIVE, 0)) {
        perror("watchdog adoption");
        return 1; /* nowayout leaves the timer armed when the descriptor closes */
    }
    double lease = monotonic() + 90, next_ping = monotonic() + 5;
    unsigned pings = 1;
    const char *mode = "feeding";
    if (state(fd, mode, lease, pings)) return 1;
    printf("PERRIER_GUARD_READY backend=linux-watchdog boot_grace=90 lease=60 watchdog=120\n");
    for (;;) {
        struct pollfd p = {.fd = s, .events = POLLIN};
        if (poll(&p, 1, 250) < 0 && errno != EINTR) return 1;
        int request_reboot = 0;
        if (p.revents & POLLIN) {
            char cmd[32] = {0};
            ssize_t n = recv(s, cmd, sizeof(cmd) - 1, 0);
            if (n > 0 && !strcmp(mode, "feeding")) {
                if (!strcmp(cmd, "renew")) lease = monotonic() + 60;
                else if (!strcmp(cmd, "expire")) {
                    mode = "hardware_expiry_test";
                    if (state(fd, mode, lease, pings)) return 1;
                    puts("PERRIER_GUARD_FEED_STOPPED hardware_expiry_test");
                } else if (!strcmp(cmd, "reboot")) {
                    mode = "reboot_requested";
                    request_reboot = 1;
                }
            }
        }
        double now = monotonic();
        if (!strcmp(mode, "feeding") && now >= lease) {
            mode = "lease_expired";
            puts("PERRIER_GUARD_LEASE_EXPIRED");
            request_reboot = 1;
        }
        if (request_reboot) {
            state(fd, mode, lease, pings);
            reboot(RB_AUTOBOOT);
            perror("ram-guard reboot failed; waiting for hardware expiry");
            /* Keep the fd open and never feed again if software reboot fails. */
        }
        if (now >= next_ping) {
            if (!strcmp(mode, "feeding")) {
                if (ioctl(fd, WDIOC_KEEPALIVE, 0)) {
                    perror("watchdog keepalive");
                    return 1;
                }
                ++pings;
            }
            if (state(fd, mode, lease, pings)) return 1;
            next_ping = now + 5;
        }
    }
}
