// SPDX-License-Identifier: GPL-2.0-only
// Read-only snapshot of the TC358765 while the stock driver owns the panel.
#include <errno.h>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

struct item { uint16_t reg; const char *name; };

static const struct item registers[] = {
    {0x0104, "PPI_STARTPPI"}, {0x0114, "PPI_LPTXTIMECNT"},
    {0x0134, "PPI_LANEENABLE"}, {0x013c, "PPI_TX_RX_TA"},
    {0x0164, "PPI_D0S_CLRSIPOCOUNT"}, {0x0168, "PPI_D1S_CLRSIPOCOUNT"},
    {0x016c, "PPI_D2S_CLRSIPOCOUNT"}, {0x0170, "PPI_D3S_CLRSIPOCOUNT"},
    {0x0204, "DSI_STARTDSI"}, {0x0210, "DSI_LANEENABLE"},
    {0x0214, "DSI_LANESTATUS0"}, {0x0218, "DSI_LANESTATUS1"},
    {0x0220, "DSI_INTSTATUS"}, {0x0300, "DSIERRCNT"},
    {0x0450, "VPCTRL"}, {0x0454, "HTIM1"}, {0x0458, "HTIM2"},
    {0x045c, "VTIM1"}, {0x0460, "VTIM2"}, {0x0464, "VFUEN"},
    {0x0480, "LV_MX0003"}, {0x0484, "LV_MX0407"},
    {0x0488, "LV_MX0811"}, {0x048c, "LV_MX1215"},
    {0x0490, "LV_MX1619"}, {0x0494, "LV_MX2023"},
    {0x0498, "LV_MX2427"}, {0x049c, "LVCFG"},
    {0x04a0, "LVPHY0"}, {0x0500, "SYSSTAT"},
    {0x0580, "IDREG"},
};

int main(int argc, char **argv)
{
    const char *device = argc == 2 ? argv[1] : "/dev/i2c-3";
    if (argc > 2) {
        fprintf(stderr, "usage: %s [/dev/i2c-N]\n", argv[0]);
        return 2;
    }
    int fd = open(device, O_RDWR | O_CLOEXEC);
    if (fd < 0) {
        perror(device);
        return 1;
    }
    for (unsigned i = 0; i < sizeof(registers)/sizeof(registers[0]); ++i) {
        uint8_t addr[2] = { registers[i].reg >> 8, registers[i].reg & 255 };
        uint8_t value[4] = {0};
        struct i2c_msg messages[2] = {
            { .addr = 0x0f, .flags = 0, .len = 2, .buf = addr },
            { .addr = 0x0f, .flags = I2C_M_RD, .len = 4, .buf = value },
        };
        struct i2c_rdwr_ioctl_data transfer = { .msgs = messages, .nmsgs = 2 };
        if (ioctl(fd, I2C_RDWR, &transfer) < 0) {
            fprintf(stderr, "%04x %-24s ERROR %s\n", registers[i].reg,
                    registers[i].name, strerror(errno));
            close(fd);
            return 2;
        }
        uint32_t word = (uint32_t)value[0] | ((uint32_t)value[1] << 8) |
                        ((uint32_t)value[2] << 16) | ((uint32_t)value[3] << 24);
        printf("%04x %-24s %08x\n", registers[i].reg, registers[i].name, word);
    }
    close(fd);
    return 0;
}
