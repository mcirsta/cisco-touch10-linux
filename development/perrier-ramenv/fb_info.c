/* SPDX-License-Identifier: GPL-2.0-only */
#include <fcntl.h>
#include <linux/fb.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <unistd.h>
int main(void)
{
    int fd = open("/dev/fb0", O_RDONLY);
    struct fb_var_screeninfo var = {0};
    struct fb_fix_screeninfo fix = {0};
    if (fd < 0 || ioctl(fd, FBIOGET_VSCREENINFO, &var) ||
        ioctl(fd, FBIOGET_FSCREENINFO, &fix)) return 1;
    printf("visible=%ux%u virtual=%ux%u offset=%u,%u depth=%u stride=%u\n",
           var.xres,var.yres,var.xres_virtual,var.yres_virtual,var.xoffset,var.yoffset,
           var.bits_per_pixel,fix.line_length);
    printf("pixel_clock_ps=%u margins=%u,%u,%u,%u sync=%u,%u rotate=%u\n",
           var.pixclock,var.left_margin,var.right_margin,var.upper_margin,var.lower_margin,
           var.hsync_len,var.vsync_len,var.rotate);
    close(fd);
    return 0;
}
