/* Read-only clock mux inspection on the stock Perrier kernel. */
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/mman.h>
#include <unistd.h>

int main(void)
{
    const off_t base = 0x4a307000;
    int fd = open("/dev/mem", O_RDONLY | O_SYNC);
    if (fd < 0) { perror("open /dev/mem"); return 1; }
    volatile const uint32_t *page = mmap(0, 4096, PROT_READ, MAP_SHARED, fd, base);
    if (page == MAP_FAILED) { perror("mmap timer clock"); return 2; }
    /* CLKCTRL base 0x4a307820 plus (0x40 - 0x20) index. */
    uint32_t value = page[0x840 / 4];
    printf("CM_WKUP_TIMER1_CLKCTRL=%08x CLKSEL=%u\n", value, (value >> 24) & 1);
    volatile const uint32_t *timer = mmap(0, 4096, PROT_READ, MAP_SHARED, fd, 0x4a318000);
    if (timer == MAP_FAILED) { perror("mmap timer1"); return 3; }
    for (unsigned offset = 0; offset <= 0x58; offset += 4)
        printf("TIMER1+%02x=%08x\n", offset, timer[offset / 4]);
    munmap((void *)timer, 4096);
    munmap((void *)page, 4096);
    close(fd);
    return 0;
}
