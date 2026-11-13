/* One-shot Touch 10 OMAP4460 ROM speedup-poll reachability probe.
 *
 * This program accepts exactly one pinned image per invocation. --check only
 * verifies local files. --run waits for the pinned USB ROM port, then sends
 * one BOOT command, one length, and the image in 512-byte USBFS transfers.
 * It has no eMMC or persistent-storage command. A successful host transfer
 * does not prove that the ROM accepted or executed the image.
 */
#include <errno.h>
#include <fcntl.h>
#include <linux/usbdevice_fs.h>
#include <openssl/evp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#define ROOT "/home/marius/ext_proj/touch10"
#define USB_PORT "2-1.1.2"
#define FTDI_PORT "2-1.1.1"
#define IMAGE_SIZE 0x3f9cU
#define SOURCE_SIZE 41024U
#define ROM_SIZE 49152U
#define TABLE_OFFSET 0xa4U
#define TABLE_SIZE 0x110U
#define ROM_WORD 0x16793a22U
#define WAIT_SECONDS 3600.0

#ifdef HANDOFF_POLL
#define POLL_ADDRESS 0x00402104U
#else
#define POLL_ADDRESS 0x00036f54U
#endif

static const char *source_path = ROOT "/firmware/codec-ce9.9.0/extracted/MLO";
static const char *rom_path = ROOT "/analysis/bootrom/omap4460-bootrom-lowalias.bin";
static const char *source_sha = "2b80cf8b398c3cb109d4da028831ff4881c8b0ea0fa8c33167a6d6b00e62e427";
static const char *rom_sha = "7fd0176dbdf06cfa42f147a5c0a923abb1f2fa269b82d0352fa02a5bd3b8efff";
static const char *signed_sha = "e8518b985280b6c99e0d451d24a259563ed6b15b061858761e734eca4167694e";

struct variant {
    const char *name;
    const char *path;
    const char *sha;
    uint32_t poll_value;
    uint32_t mode_low;
    uint32_t mode_high;
};

static const struct variant variants[] = {
#ifdef HANDOFF_POLL
    { "clear", ROOT "/evidence/bootrom-handoff-poll-2026-11-08/clear.bin",
      "6512bc7c0829531a39300d076848cd2ca3565a158bd4b67b00555c718a6cb18e", 0U, 1U, 0U },
    { "set", ROOT "/evidence/bootrom-handoff-poll-2026-11-08/set.bin",
      "e95f661d12e7badb4d73d62b99117304211ca70f4b9de17a556fc66bf6db9716", 0U, 0U, 1U },
#else
    { "pass", ROOT "/evidence/bootrom-speedup-poll-2026-11-07/pass.bin",
      "b1f63f73a4b4554f28d41867e5a8637b3eb49bc051c3738f6c24737ba396cca9", ROM_WORD, 1U, 1U },
    { "stall", ROOT "/evidence/bootrom-speedup-poll-2026-11-07/stall.bin",
      "482ea59b6e671bf0af7c9d380e39c0b9973a5905a43bf4b84566914fbe130c75", ROM_WORD + 1U, 1U, 1U },
#endif
};

static double stamp(clockid_t clock_id) {
    struct timespec value;
    if (clock_gettime(clock_id, &value) != 0) return -1;
    return (double)value.tv_sec + (double)value.tv_nsec / 1000000000.0;
}

static uint32_t le32(const unsigned char *bytes) {
    return (uint32_t)bytes[0] | (uint32_t)bytes[1] << 8 |
           (uint32_t)bytes[2] << 16 | (uint32_t)bytes[3] << 24;
}

static unsigned char *read_exact(const char *path, size_t size) {
    FILE *file = fopen(path, "rb");
    if (!file) {
        fprintf(stderr, "%s: %s\n", path, strerror(errno));
        return NULL;
    }
    unsigned char *data = malloc(size);
    if (!data) {
        fclose(file);
        return NULL;
    }
    int exact = fread(data, 1, size, file) == size && fgetc(file) == EOF && !ferror(file);
    fclose(file);
    if (!exact) {
        fprintf(stderr, "%s: expected exactly %zu bytes\n", path, size);
        free(data);
        return NULL;
    }
    return data;
}

static int verify_sha(const unsigned char *data, size_t size, const char *expected,
                      const char *label) {
    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned int digest_size = 0;
    char hex[65];
    if (EVP_Digest(data, size, digest, &digest_size, EVP_sha256(), NULL) != 1 ||
        digest_size != 32U) {
        fprintf(stderr, "%s: SHA-256 calculation failed\n", label);
        return 0;
    }
    for (unsigned int i = 0; i < digest_size; ++i)
        snprintf(hex + 2U * i, sizeof(hex) - 2U * i, "%02x", digest[i]);
    if (strcmp(hex, expected) != 0) {
        fprintf(stderr, "%s: SHA-256 mismatch (got %s)\n", label, hex);
        return 0;
    }
    return 1;
}

static int verify_layout(const unsigned char *image, const unsigned char *source,
                         const unsigned char *rom, const struct variant *selected) {
    if (le32(source) != 0x4000U || le32(source + 4) != 0x6040U ||
        memcmp(source + 0x14, "MLO\0", 4) != 0 ||
        le32(source + 0x20) != 0xc00U || le32(source + 0x24) != 0x339cU ||
        le32(source + 0x40) != 0x200U || le32(source + 0x44) != 0x960U ||
        memcmp(source + 0x60, "\xff\xff\xff\xff\xff\xff\xff\xff", 8) != 0) {
        fputs("Reference MLO TOC differs from the reviewed layout\n", stderr);
        return 0;
    }
#ifndef HANDOFF_POLL
    if (le32(rom + (POLL_ADDRESS - 0x30000U)) != ROM_WORD) {
        fputs("Captured ROM literal differs from the reviewed value\n", stderr);
        return 0;
    }
#else
    (void)rom;
#endif
    if (le32(image) != 0U || le32(image + 4) != 0x200U ||
        memcmp(image + 0x14, "2ND\0", 4) != 0 ||
        memcmp(image + 0x34, "PRIMAPP\0", 8) != 0 ||
        memcmp(image + 0x54, "KEYS", 4) != 0 ||
        memcmp(image + 0x60, source + 0x60, 0x20) != 0 ||
        memcmp(image + 0x200, "CertPK_\0", 8) != 0 ||
        memcmp(image + 0xc00, "CertPPA\0", 8) != 0) {
        fputs("Probe TOC or certificate markers differ from the reviewed layout\n", stderr);
        return 0;
    }
    if (le32(image + TABLE_OFFSET) != ROM_WORD ||
        le32(image + TABLE_OFFSET + 4) != 1U ||
        le32(image + TABLE_OFFSET + 8) != POLL_ADDRESS ||
        le32(image + TABLE_OFFSET + 12) != selected->poll_value ||
        le32(image + TABLE_OFFSET + 0x108) != selected->mode_low ||
        le32(image + TABLE_OFFSET + 0x10c) != selected->mode_high) {
        fputs("Probe speedup-poll table differs from the reviewed encoding\n", stderr);
        return 0;
    }
    for (size_t offset = TABLE_OFFSET + 16U; offset < TABLE_OFFSET + 0x108U; ++offset) {
        if (image[offset] != 0) {
            fputs("Probe has an unexpected additional speedup entry\n", stderr);
            return 0;
        }
    }
    /* Every change must be in the unsigned outer header. The key and PPA
     * region is checked both byte-for-byte and by its pinned SHA-256. */
    for (size_t offset = 0; offset < IMAGE_SIZE; ++offset) {
        int mutable = offset < 8U || (offset >= 0x14U && offset < 0x18U) ||
                      (offset >= TABLE_OFFSET && offset < TABLE_OFFSET + TABLE_SIZE);
        if (!mutable && image[offset] != source[offset]) {
            fprintf(stderr, "Probe differs from reference at forbidden offset 0x%zx\n", offset);
            return 0;
        }
    }
    if (memcmp(image + 0x200, source + 0x200, IMAGE_SIZE - 0x200U) != 0 ||
        !verify_sha(image + 0x200, IMAGE_SIZE - 0x200U, signed_sha, "signed region")) {
        fputs("Signed region is not identical to the reference MLO\n", stderr);
        return 0;
    }
    return 1;
}

static unsigned char *validated_image(const struct variant *selected) {
    unsigned char *source = read_exact(source_path, SOURCE_SIZE);
    unsigned char *rom = read_exact(rom_path, ROM_SIZE);
    unsigned char *image = read_exact(selected->path, IMAGE_SIZE);
    int valid = source && rom && image &&
        verify_sha(source, SOURCE_SIZE, source_sha, "reference MLO") &&
        verify_sha(rom, ROM_SIZE, rom_sha, "captured ROM") &&
        verify_sha(image, IMAGE_SIZE, selected->sha, selected->name) &&
        verify_layout(image, source, rom, selected);
    free(source);
    free(rom);
    if (!valid) {
        free(image);
        return NULL;
    }
    printf("%.6f Checked %s: %u bytes, SHA-256 %s; selected 2ND at zero, signed region unchanged.\n",
           stamp(CLOCK_REALTIME), selected->name, IMAGE_SIZE, selected->sha);
    return image;
}

static int read_sysfs_number(const char *path, int base) {
    FILE *file = fopen(path, "r");
    if (!file) return -1;
    char text[32];
    int result = -1;
    if (fgets(text, sizeof(text), file)) {
        char *end = NULL;
        unsigned long value = strtoul(text, &end, base);
        if (end != text && value <= 65535UL) result = (int)value;
    }
    fclose(file);
    return result;
}

static int validate_ftdi_sibling(void) {
    const char *base = "/sys/bus/usb/devices/" FTDI_PORT "/";
    char path[128], serial[64];
    snprintf(path, sizeof(path), "%sidVendor", base);
    if (read_sysfs_number(path, 16) != 0x0403) return 0;
    snprintf(path, sizeof(path), "%sidProduct", base);
    if (read_sysfs_number(path, 16) != 0x6015) return 0;
    snprintf(path, sizeof(path), "%sserial", base);
    FILE *file = fopen(path, "r");
    if (!file) return 0;
    int valid = fgets(serial, sizeof(serial), file) != NULL &&
        (strcmp(serial, "D3081QEX\n") == 0 || strcmp(serial, "D3081QEX") == 0);
    fclose(file);
    return valid;
}

static int usbfs_send(int fd, const unsigned char *data, unsigned int length,
                      const char *label) {
    struct usbdevfs_bulktransfer transfer = {
        .ep = 0x01, .len = length, .timeout = 1000, .data = (void *)data,
    };
    double started = stamp(CLOCK_REALTIME);
    int written = ioctl(fd, USBDEVFS_BULK, &transfer);
    int error = errno;
    printf("%.6f %s: %d/%u bytes, errno=%d (%s), duration=%.3f ms\n",
           started, label, written, length, written < 0 ? error : 0,
           written < 0 ? strerror(error) : "success",
           (stamp(CLOCK_REALTIME) - started) * 1000.0);
    return written == (int)length ? 0 : 1;
}

static int upload_once(int fd, const unsigned char *image, int configuration) {
    if (configuration == 0) {
        int one = 1;
        if (ioctl(fd, USBDEVFS_SETCONFIGURATION, &one) < 0) {
            fprintf(stderr, "%.6f SETCONFIGURATION: %s\n", stamp(CLOCK_REALTIME), strerror(errno));
            return 1;
        }
    } else if (configuration != 1) {
        fprintf(stderr, "Unexpected USB configuration %d\n", configuration);
        return 1;
    }
    int interface = 0;
    if (ioctl(fd, USBDEVFS_CLAIMINTERFACE, &interface) < 0) {
        fprintf(stderr, "%.6f CLAIMINTERFACE: %s\n", stamp(CLOCK_REALTIME), strerror(errno));
        return 1;
    }
    static const unsigned char boot[] = { 0x02, 0x00, 0x03, 0xf0 };
    static const unsigned char length[] = {
        IMAGE_SIZE & 0xff, (IMAGE_SIZE >> 8) & 0xff,
        (IMAGE_SIZE >> 16) & 0xff, (IMAGE_SIZE >> 24) & 0xff,
    };
    int failed = usbfs_send(fd, boot, sizeof(boot), "BOOT") ||
                 usbfs_send(fd, length, sizeof(length), "image length");
    for (unsigned int offset = 0; !failed && offset < IMAGE_SIZE;) {
        unsigned int remaining = IMAGE_SIZE - offset;
        unsigned int count = remaining < 512U ? remaining : 512U;
        char label[48];
        snprintf(label, sizeof(label), "image packet 0x%04x", offset);
        failed = usbfs_send(fd, image + offset, count, label);
        offset += count;
    }
    if (ioctl(fd, USBDEVFS_RELEASEINTERFACE, &interface) < 0)
        fprintf(stderr, "%.6f RELEASEINTERFACE: %s\n", stamp(CLOCK_REALTIME), strerror(errno));
    if (!failed)
        printf("%.6f Host transfer complete; ROM acceptance and execution remain unconfirmed.\n",
               stamp(CLOCK_REALTIME));
    return failed;
}

static int run(const unsigned char *image) {
    if (!validate_ftdi_sibling()) {
        fprintf(stderr, "Pinned Touch 10 FTDI sibling %s / D3081QEX is absent\n", FTDI_PORT);
        return 1;
    }
    char path[128];
    snprintf(path, sizeof(path), "/sys/bus/usb/devices/%s/devnum", USB_PORT);
    int baseline_devnum = read_sysfs_number(path, 10);
    snprintf(path, sizeof(path), "/sys/bus/usb/devices/%s/idVendor", USB_PORT);
    int baseline_vendor = read_sysfs_number(path, 16);
    snprintf(path, sizeof(path), "/sys/bus/usb/devices/%s/idProduct", USB_PORT);
    int baseline_product = read_sysfs_number(path, 16);
    if (baseline_vendor != 0x0451 || baseline_product != 0xd010)
        baseline_devnum = -1;
    int saw_disconnect = baseline_devnum < 0;
    printf("%.6f Ready: waiting up to %.0f seconds for a fresh %s TI 0451:d010 enumeration; current devnum=%d.\n",
           stamp(CLOCK_REALTIME), WAIT_SECONDS, USB_PORT, baseline_devnum);
    double deadline = stamp(CLOCK_MONOTONIC) + WAIT_SECONDS;
    while (stamp(CLOCK_MONOTONIC) < deadline) {
        snprintf(path, sizeof(path), "/sys/bus/usb/devices/%s/devnum", USB_PORT);
        int devnum = read_sysfs_number(path, 10);
        snprintf(path, sizeof(path), "/sys/bus/usb/devices/%s/idVendor", USB_PORT);
        int vendor = read_sysfs_number(path, 16);
        snprintf(path, sizeof(path), "/sys/bus/usb/devices/%s/idProduct", USB_PORT);
        int product = read_sysfs_number(path, 16);
        if (devnum < 1 || devnum > 127 || vendor != 0x0451 || product != 0xd010) {
            saw_disconnect = 1;
            usleep(1000);
            continue;
        }
        if (baseline_devnum >= 0 && devnum == baseline_devnum && !saw_disconnect) {
            usleep(1000);
            continue;
        }
        if (!validate_ftdi_sibling()) {
            fputs("FTDI sibling disappeared before upload; aborting\n", stderr);
            return 1;
        }
        snprintf(path, sizeof(path), "/sys/bus/usb/devices/%s/bConfigurationValue", USB_PORT);
        int configuration = read_sysfs_number(path, 10);
        if (configuration != 0 && configuration != 1) {
            usleep(1000);
            continue;
        }
        snprintf(path, sizeof(path), "/dev/bus/usb/002/%03d", devnum);
        int fd = open(path, O_RDWR | O_CLOEXEC);
        if (fd < 0) {
            if (errno == EPERM || errno == EACCES) {
                fprintf(stderr, "%s: %s; USB access is required\n", path, strerror(errno));
                return 1;
            }
            usleep(1000);
            continue;
        }
        printf("%.6f Opened pinned %s at %s, configuration %d.\n",
               stamp(CLOCK_REALTIME), USB_PORT, path, configuration);
        int result = upload_once(fd, image, configuration);
        close(fd);
        return result;
    }
    fputs("Timed out waiting for pinned TI ROM USB device\n", stderr);
    return 1;
}

int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IOLBF, 0);
    if (argc != 3 ||
        (strcmp(argv[1], "--check") != 0 && strcmp(argv[1], "--run") != 0)) {
        fprintf(stderr, "Usage: %s --check|--run variant\n", argv[0]);
        return 2;
    }
    const struct variant *selected = NULL;
    for (size_t i = 0; i < sizeof(variants) / sizeof(variants[0]); ++i)
        if (strcmp(argv[2], variants[i].name) == 0) selected = &variants[i];
    if (!selected) {
        fputs("Select exactly one compiled-in variant\n", stderr);
        return 2;
    }
    unsigned char *image = validated_image(selected);
    if (!image) return 1;
    int result = strcmp(argv[1], "--run") == 0 ? run(image) : 0;
    free(image);
    return result;
}
