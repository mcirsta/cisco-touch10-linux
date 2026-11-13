/* SPDX-License-Identifier: GPL-2.0-only */
/* Adopt the stock-armed 120-second WDT2. Only WTGR is ever written. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/reboot.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#define WDT_BASE 0x4a314000u
#define WCLR (0x24/4)
#define WCRR (0x28/4)
#define WLDR (0x2c/4)
#define WTGR (0x30/4)
#define WWPS (0x34/4)
#define WSPR (0x48/4)
#define LOAD_120 0xffc40000u
#define SOCKET_PATH "/run/ram-guard.sock"
static volatile uint32_t *regs;

static double monotonic(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) _exit(2);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

static int pending_clear(void)
{
    double end = monotonic() + 0.1;
    while (regs[WWPS] & 0x1f) {
        if (monotonic() >= end) return -1;
        usleep(100);
    }
    return 0;
}

static int reload(void)
{
    if (regs[WLDR] != LOAD_120 || (regs[WCLR] & 0x3c) != 0x20 ||
        regs[WSPR] != 0x4444 || pending_clear())
        return -1;
    uint32_t next = ~regs[WTGR];
    __sync_synchronize();
    regs[WTGR] = next;
    __sync_synchronize();
    if (pending_clear() || regs[WTGR] != next) return -1;
    uint32_t remaining = 0u - regs[WCRR];
    return remaining > 118u * 32768u && remaining <= 120u * 32768u ? 0 : -1;
}

static void state(const char *mode, double lease, unsigned pings)
{
    FILE *f = fopen("/run/guard.json.tmp", "w");
    if (!f) return;
    fprintf(f, "{\"pid\":%ld,\"state\":\"%s\",\"monotonic\":%.3f,"
               "\"lease_deadline\":%.3f,\"pings\":%u,\"counter\":%u,"
               "\"load\":%u,\"timeout_seconds\":120}\n",
            (long)getpid(), mode, monotonic(), lease, pings, regs[WCRR], regs[WLDR]);
    fclose(f);
    rename("/run/guard.json.tmp", "/run/guard.json");
}

static int board_ok(void)
{
    char data[256] = {0};
    int fd = open("/proc/device-tree/compatible", O_RDONLY);
    if (fd < 0) return 0;
    ssize_t n = read(fd, data, sizeof(data)-1);
    close(fd);
    return n > 0 && memmem(data, n, "cisco,perrier-ram", 17);
}

static int command(const char *cmd)
{
    int s = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    struct sockaddr_un addr = {.sun_family = AF_UNIX};
    strcpy(addr.sun_path, SOCKET_PATH);
    if (s < 0 || sendto(s, cmd, strlen(cmd), 0,
                       (struct sockaddr *)&addr, sizeof(addr)) != (ssize_t)strlen(cmd)) {
        perror("ram-guard command");
        return 1;
    }
    close(s);
    return 0;
}

int main(int argc, char **argv)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    if (argc != 2) return 2;
    if (!strcmp(argv[1], "renew") || !strcmp(argv[1], "expire") || !strcmp(argv[1], "reboot"))
        return command(argv[1]);
    int inspect = !strcmp(argv[1], "inspect");
    if (!inspect && strcmp(argv[1], "daemon")) return 2;
    if (!inspect && !board_ok()) { fprintf(stderr, "wrong board\n"); return 1; }
    int lock = -1;
    if (!inspect) {
        lock = open("/run/ram-guard.lock", O_RDWR | O_CREAT | O_CLOEXEC, 0600);
        if (lock < 0 || flock(lock, LOCK_EX | LOCK_NB)) {
            perror("watchdog lock");
            return 1;
        }
    }
    int fd = open("/dev/mem", (inspect ? O_RDONLY : O_RDWR) | O_SYNC | O_CLOEXEC);
    regs = fd < 0 ? MAP_FAILED : mmap(NULL, 4096,
                    PROT_READ | (inspect ? 0 : PROT_WRITE), MAP_SHARED, fd, WDT_BASE);
    if (regs == MAP_FAILED) { perror("watchdog mmap"); return 1; }
    printf("WDT2 rev=%08x control=%08x counter=%08x load=%08x trigger=%08x pending=%08x spr=%08x\n",
           regs[0], regs[WCLR], regs[WCRR], regs[WLDR], regs[WTGR], regs[WWPS], regs[WSPR]);
    if (inspect) return 0;
    uint32_t before = regs[WCRR];
    usleep(20000);
    uint32_t delta = regs[WCRR] - before;
    if (delta == 0 || delta > 32768 || regs[WLDR] != LOAD_120 ||
        (regs[WCLR] & 0x3c) != 0x20 || regs[WSPR] != 0x4444 || pending_clear()) {
        fprintf(stderr, "watchdog inheritance validation failed\n"); return 1;
    }
    int s = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    struct sockaddr_un addr = {.sun_family = AF_UNIX};
    strcpy(addr.sun_path, SOCKET_PATH);
    unlink(SOCKET_PATH);
    if (s < 0 || bind(s, (struct sockaddr *)&addr, sizeof(addr))) return 1;
    chmod(SOCKET_PATH, 0600);
    double lease = monotonic() + 90, next_ping = 0;
    unsigned pings = 0;
    int expired = 0;
    printf("PERRIER_GUARD_READY boot_grace=90 lease=60 watchdog=120\n");
    for (;;) {
        struct pollfd p = {.fd = s, .events = POLLIN};
        if (poll(&p, 1, 250) < 0 && errno != EINTR) return 1;
        if (p.revents & POLLIN) {
            char cmd[32] = {0};
            ssize_t n = recv(s, cmd, sizeof(cmd)-1, 0);
            if (n > 0 && !expired) {
                if (!strcmp(cmd, "renew")) lease = monotonic() + 60;
                else if (!strcmp(cmd, "expire")) {
                    expired = 1;
                    state("hardware_expiry_test", lease, pings);
                    printf("PERRIER_GUARD_FEED_STOPPED hardware_expiry_test\n");
                } else if (!strcmp(cmd, "reboot")) {
                    state("reboot_requested", lease, pings);
                    reboot(RB_AUTOBOOT);
                    return 1;
                }
            }
        }
        double now = monotonic();
        if (!expired && now >= lease) {
            state("lease_expired", lease, pings);
            printf("PERRIER_GUARD_LEASE_EXPIRED\n");
            reboot(RB_AUTOBOOT);
            return 1;
        }
        if (now >= next_ping) {
            if (!expired) {
                if (reload()) {
                    state("reload_failed", lease, pings);
                    fprintf(stderr, "watchdog reload failed\n"); return 1;
                }
                ++pings;
            }
            state(expired ? "hardware_expiry_test" : "feeding", lease, pings);
            next_ping = now + 5;
        }
    }
}
