/* SPDX-License-Identifier: GPL-2.0-only */
/* One guarded, temporary KMS scanout test for the Perrier LVDS panel. */
#include <drm/drm.h>
#include <drm/drm_mode.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

#define WIDTH 1280u
#define HEIGHT 800u

static int failed(const char *stage)
{
    printf("PERRIER_PATTERN_ERROR stage=%s errno=%d\n", stage, errno);
    return 1;
}

int main(void)
{
    int fd = open("/dev/dri/card0", O_RDWR | O_CLOEXEC);
    if (fd < 0) return failed("open");

    struct drm_mode_card_res res = {0};
    if (ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &res)) return failed("resources-count");
    if (res.count_crtcs != 1 || res.count_connectors != 1 || res.count_encoders != 1) {
        printf("PERRIER_PATTERN_GUARD crtcs=%u connectors=%u encoders=%u\n",
               res.count_crtcs, res.count_connectors, res.count_encoders);
        return 2;
    }
    uint32_t crtc_id = 0, connector_id = 0;
    res.crtc_id_ptr = (uintptr_t)&crtc_id;
    res.connector_id_ptr = (uintptr_t)&connector_id;
    res.count_encoders = 0;
    res.count_fbs = 0;
    if (ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &res)) return failed("resources-ids");
    if (!crtc_id || !connector_id) return failed("ids");

    struct drm_mode_get_connector conn = {.connector_id = connector_id};
    if (ioctl(fd, DRM_IOCTL_MODE_GETCONNECTOR, &conn)) return failed("connector-count");
    if (conn.connector_type != DRM_MODE_CONNECTOR_LVDS || conn.connection != 1 ||
        conn.count_modes != 1 || conn.count_encoders != 1) {
        printf("PERRIER_PATTERN_GUARD connector_type=%u connection=%u modes=%u encoders=%u\n",
               conn.connector_type, conn.connection, conn.count_modes, conn.count_encoders);
        return 2;
    }
    struct drm_mode_modeinfo mode = {0};
    uint32_t encoder_id = 0;
    conn.modes_ptr = (uintptr_t)&mode;
    conn.encoders_ptr = (uintptr_t)&encoder_id;
    conn.count_props = 0;
    if (ioctl(fd, DRM_IOCTL_MODE_GETCONNECTOR, &conn)) return failed("connector-mode");
    if (mode.hdisplay != WIDTH || mode.vdisplay != HEIGHT ||
        mode.vrefresh != 60 || !encoder_id) {
        printf("PERRIER_PATTERN_GUARD mode=%ux%u@%u encoder=%u\n",
               mode.hdisplay, mode.vdisplay, mode.vrefresh, encoder_id);
        return 2;
    }
    struct drm_mode_get_encoder enc = {.encoder_id = encoder_id};
    if (ioctl(fd, DRM_IOCTL_MODE_GETENCODER, &enc)) return failed("encoder");
    if (!(enc.possible_crtcs & 1)) return failed("encoder-crtc");

    struct drm_mode_create_dumb dumb = {.width = WIDTH, .height = HEIGHT, .bpp = 32};
    if (ioctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &dumb)) return failed("create-dumb");
    if (dumb.pitch < WIDTH * 4 || dumb.size < (uint64_t)dumb.pitch * HEIGHT)
        return failed("dumb-layout");
    printf("PERRIER_PATTERN_BUFFER pitch=%u size=%llu handle=%u\n",
           dumb.pitch, (unsigned long long)dumb.size, dumb.handle);

    struct drm_mode_map_dumb map = {.handle = dumb.handle};
    if (ioctl(fd, DRM_IOCTL_MODE_MAP_DUMB, &map)) return failed("map-dumb");
    uint8_t *pixels = mmap(NULL, dumb.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, map.offset);
    if (pixels == MAP_FAILED) return failed("mmap");
    for (unsigned y = 0; y < HEIGHT; ++y) {
        uint32_t *row = (uint32_t *)(pixels + (size_t)y * dumb.pitch);
        for (unsigned x = 0; x < WIDTH; ++x) {
            uint32_t color = 0x00006020; /* dark green */
            if (x < 32 || x >= WIDTH-32 || y < 32 || y >= HEIGHT-32)
                color = 0x00ff00ff; /* magenta border */
            if (x >= 96 && x < 520 && y >= 100 && y < 420)
                color = 0x0000ff00; /* large green block */
            if (x >= 760 && x < 1184 && y >= 380 && y < 700)
                color = 0x00ffffff; /* white block */
            row[x] = color;
        }
    }

    struct drm_mode_fb_cmd fb = {
        .width = WIDTH, .height = HEIGHT, .pitch = dumb.pitch,
        .bpp = 32, .depth = 24, .handle = dumb.handle
    };
    if (ioctl(fd, DRM_IOCTL_MODE_ADDFB, &fb)) return failed("addfb");
    struct drm_mode_crtc crtc = {
        .set_connectors_ptr = (uintptr_t)&connector_id,
        .count_connectors = 1, .crtc_id = crtc_id, .fb_id = fb.fb_id,
        .mode_valid = 1, .mode = mode
    };
    printf("PERRIER_PATTERN_SETCRTC_BEGIN crtc=%u connector=%u fb=%u mode=%s\n",
           crtc_id, connector_id, fb.fb_id, mode.name);
    if (ioctl(fd, DRM_IOCTL_MODE_SETCRTC, &crtc)) return failed("setcrtc");
    printf("PERRIER_PATTERN_SETCRTC_OK\n");
    struct drm_mode_crtc active = {.crtc_id = crtc_id};
    if (ioctl(fd, DRM_IOCTL_MODE_GETCRTC, &active))
        printf("PERRIER_PATTERN_GETCRTC errno=%d\n", errno);
    else
        printf("PERRIER_PATTERN_GETCRTC fb=%u mode_valid=%u width=%u height=%u match=%u\n",
               active.fb_id, active.mode_valid, active.mode.hdisplay,
               active.mode.vdisplay, active.fb_id == fb.fb_id &&
               active.mode_valid && active.mode.hdisplay == WIDTH &&
               active.mode.vdisplay == HEIGHT);
    sleep(45);
    printf("PERRIER_PATTERN_WINDOW_END\n");
    /* The temporary kernel reboots to stock. Closing DRM may disable scanout. */
    close(fd);
    return 0;
}
