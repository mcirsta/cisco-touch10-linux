/* SPDX-License-Identifier: GPL-2.0-only */
/* Temporary, auto-restoring Perrier DISPC core clock source comparison. */
#define _GNU_SOURCE
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <unistd.h>

#define DSS_BASE 0x58000000u
#define DSS_CONTROL (0x40u / 4u)
static volatile sig_atomic_t stop;
static void halt(int sig) { (void)sig; stop = 1; }

int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    char compatible[256] = {};
    int fd = open("/proc/device-tree/compatible", O_RDONLY);
    ssize_t n = fd < 0 ? -1 : read(fd, compatible, sizeof(compatible));
    if (fd >= 0) close(fd);
    if (n <= 0 || !memmem(compatible, (size_t)n, "cisco,perrier-ram", 17)) return 2;
    fd = open("/run/dss-clock-trial.lock", O_CREAT | O_RDWR | O_CLOEXEC, 0600);
    if (fd < 0 || flock(fd, LOCK_EX | LOCK_NB)) return 3;
    int mem = open("/dev/mem", O_RDWR | O_SYNC | O_CLOEXEC);
    if (mem < 0) return 4;
    volatile uint32_t *dss = mmap(NULL, 4096, PROT_READ | PROT_WRITE,
                                  MAP_SHARED, mem, DSS_BASE);
    if (dss == MAP_FAILED) return 5;
    uint32_t original = dss[DSS_CONTROL];
    printf("DSS_CLOCK_BEFORE control=%08x\n", original);
    if (original != 0x00000003u) return 6;
    struct sigaction sa = {.sa_handler = halt};
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);
    __sync_synchronize();
    dss[DSS_CONTROL] = original | 0x100u;
    __sync_synchronize();
    uint32_t changed = dss[DSS_CONTROL];
    printf("DSS_CLOCK_STOCK_SELECTOR control=%08x seconds=600\n", changed);
    if (changed != 0x00000103u) return 7;
    for (unsigned i = 0; i < 600 && !stop; ++i) sleep(1);
    uint32_t current = dss[DSS_CONTROL];
    if (current != 0x00000103u) {
        printf("DSS_CLOCK_CHANGED_EXTERNALLY control=%08x\n", current);
        return 8;
    }
    dss[DSS_CONTROL] = original;
    __sync_synchronize();
    printf("DSS_CLOCK_RESTORED control=%08x\n", dss[DSS_CONTROL]);
    return dss[DSS_CONTROL] == original ? 0 : 9;
}
