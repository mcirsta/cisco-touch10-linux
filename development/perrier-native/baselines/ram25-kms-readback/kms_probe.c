/* SPDX-License-Identifier: GPL-2.0-only */
/* KMS discovery using only GET ioctls for the inherited framebuffer. */
#include <drm/drm.h>
#include <drm/drm_mode.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

int main(void)
{
    /* The first GETCONNECTOR fills modes only for the current DRM master. */
    int fd = open("/dev/dri/card0", O_RDWR | O_CLOEXEC);
    if (fd < 0) {
        printf("PERRIER_DRM_OPEN errno=%d\n", errno);
        return 1;
    }
    struct drm_mode_card_res res = {0};
    if (ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &res)) {
        printf("PERRIER_DRM_RESOURCES errno=%d\n", errno);
        close(fd);
        return 1;
    }
    printf("PERRIER_DRM_RESOURCES crtcs=%u connectors=%u encoders=%u fbs=%u\n",
           res.count_crtcs, res.count_connectors, res.count_encoders,
           res.count_fbs);
    if (res.count_connectors != 1 || res.count_crtcs != 1) {
        close(fd);
        return 1;
    }
    uint32_t connector_id = 0;
    /* Query only connector IDs. Other nonzero counts require output arrays. */
    res.count_crtcs = 0;
    res.count_encoders = 0;
    res.count_fbs = 0;
    res.connector_id_ptr = (uintptr_t)&connector_id;
    res.count_connectors = 1;
    if (ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &res)) {
        printf("PERRIER_DRM_CONNECTOR_ID errno=%d\n", errno);
        close(fd);
        return 1;
    }
    struct drm_mode_get_connector conn = {.connector_id = connector_id};
    if (ioctl(fd, DRM_IOCTL_MODE_GETCONNECTOR, &conn)) {
        printf("PERRIER_DRM_CONNECTOR errno=%d\n", errno);
        close(fd);
        return 1;
    }
    printf("PERRIER_DRM_CONNECTOR id=%u connection=%u modes=%u encoders=%u\n",
           conn.connector_id, conn.connection, conn.count_modes,
           conn.count_encoders);
    if (conn.count_modes > 0 && conn.count_modes <= 16) {
        struct drm_mode_modeinfo modes[16] = {0};
        conn.modes_ptr = (uintptr_t)modes;
        conn.count_encoders = 0;
        conn.count_props = 0;
        if (ioctl(fd, DRM_IOCTL_MODE_GETCONNECTOR, &conn) == 0) {
            for (unsigned i = 0; i < conn.count_modes && i < 16; ++i)
                printf("PERRIER_DRM_MODE name=%s width=%u height=%u refresh=%u\n",
                       modes[i].name, modes[i].hdisplay, modes[i].vdisplay,
                       modes[i].vrefresh);
        } else {
            printf("PERRIER_DRM_MODES errno=%d\n", errno);
        }
    }
    close(fd);
    return 0;
}
