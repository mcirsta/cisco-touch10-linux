/* Volatile OMAP4 peripheral-boot test using the signed reference eMMC MLO.
 *
 * Input is pinned by byte length, SHA-256, certificate markers, USB VID:PID,
 * and physical port path. The target's ROM has not accepted this eMMC-format
 * MLO over USB. The program itself has no flash-writing operation. If the
 * target code executes from SRAM, static analysis shows its PPA provides
 * security services and its ISW initializes MMC and reads bootloader images.
 */
#include <errno.h>
#include <fcntl.h>
#include <libusb-1.0/libusb.h>
#include <linux/usbdevice_fs.h>
#include <openssl/evp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#define MLO_SIZE 41628U
#define EXACT_MLO_SIZE 41024U
#define EXACT_PPA_2ND_SIZE 0x3f9cU
#define EXACT_PPA_2ND_PLUS4_SIZE 0x3fa0U
#define FOREIGN_2ND_SIZE 21552U
#define FOREIGN_32K_SIZE 32768U
#define FOREIGN_24K_SIZE 24576U
#define FOREIGN_28K_SIZE 28672U
#define FOREIGN_31K_SIZE 31744U
#define FOREIGN_34K_SIZE 34816U
#define CH_SIZE 512U

static const unsigned char expected_sha256[32] = {
    0x6f, 0x84, 0xcd, 0x9e, 0xec, 0xb3, 0xc2, 0xb2,
    0x14, 0x53, 0x98, 0xfb, 0x50, 0xe1, 0xf0, 0xde,
    0x05, 0x26, 0xec, 0x4e, 0xe7, 0x72, 0xce, 0x95,
    0x7a, 0x53, 0x94, 0x88, 0x4e, 0xd4, 0x34, 0xed,
};
static const unsigned char exact_mlo_sha256[32] = {
    0x2b, 0x80, 0xcf, 0x8b, 0x39, 0x8c, 0x3c, 0xb1,
    0x09, 0xd4, 0xda, 0x02, 0x88, 0x31, 0xff, 0x48,
    0x81, 0xc8, 0xb0, 0xea, 0x0f, 0xa8, 0xc3, 0x31,
    0x67, 0xa6, 0xd6, 0xb0, 0x0e, 0x62, 0xe4, 0x27,
};
static const unsigned char foreign_2nd_sha256[32] = {
    0x52, 0x60, 0xb7, 0x7c, 0xb3, 0x82, 0x22, 0x15,
    0x61, 0x44, 0xf1, 0x02, 0xc3, 0x41, 0x49, 0xe7,
    0xf8, 0x37, 0xad, 0x80, 0xe8, 0xcd, 0xc3, 0xa2,
    0x65, 0x01, 0xdd, 0x5e, 0x8b, 0xee, 0xeb, 0xb0,
};

static double now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}

static double wall_now(void) {
    struct timespec t;
    clock_gettime(CLOCK_REALTIME, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}

static int read_sysfs_number(const char *path, int base) {
    FILE *f = fopen(path, "r");
    if (!f) return -1;
    char buf[32];
    int result = -1;
    if (fgets(buf, sizeof(buf), f)) {
        char *end = NULL;
        unsigned long value = strtoul(buf, &end, base);
        if (end != buf && value <= 65535UL) result = (int)value;
    }
    fclose(f);
    return result;
}

static int read_sysfs_serial(const char *path, const char *expected) {
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    char value[64];
    int matched = fgets(value, sizeof(value), f) &&
        strncmp(value, expected, strlen(expected)) == 0 &&
        (value[strlen(expected)] == '\n' || value[strlen(expected)] == '\0');
    fclose(f);
    return matched;
}

static int validate_usbfs_port(const char *port, int *bus) {
    /* The ROM is the second function behind the Touch 10 service hub; the
     * first is its FTDI UART with this observed serial number. */
    const char *last_dot = strrchr(port, '.');
    if (!last_dot || strcmp(last_dot, ".2") != 0 ||
        strlen(port) >= 48) return 0;
    for (const char *p = port; *p; ++p) {
        if ((*p < '0' || *p > '9') && *p != '-' && *p != '.') return 0;
    }
    char *end;
    unsigned long value = strtoul(port, &end, 10);
    if (end == port || *end != '-' || value < 1 || value > 999) return 0;
    char sibling[64], path[128];
    snprintf(sibling, sizeof(sibling), "%.*s.1", (int)(last_dot - port), port);
    snprintf(path, sizeof(path), "/sys/bus/usb/devices/%s/idVendor", sibling);
    if (read_sysfs_number(path, 16) != 0x0403) return 0;
    snprintf(path, sizeof(path), "/sys/bus/usb/devices/%s/idProduct", sibling);
    if (read_sysfs_number(path, 16) != 0x6015) return 0;
    snprintf(path, sizeof(path), "/sys/bus/usb/devices/%s/serial", sibling);
    if (!read_sysfs_serial(path, "D3081QEX")) return 0;
    *bus = (int)value;
    return 1;
}

static int usbfs_send(int fd, const unsigned char *data, int length,
                      const char *label) {
    struct usbdevfs_bulktransfer transfer = {
        .ep = 0x01,
        .len = (unsigned int)length,
        .timeout = 1000,
        .data = (void *)data,
    };
    double started = wall_now();
    int sent = ioctl(fd, USBDEVFS_BULK, &transfer);
    int err = errno;
    printf("%.6f %s: %d/%d bytes, errno=%d (%s), duration=%.3f ms\n",
           started, label, sent, length, sent < 0 ? err : 0,
           sent < 0 ? strerror(err) : "success", (wall_now() - started) * 1000);
    return sent == length ? 0 : 1;
}

static int usbfs_probe(int fd, const unsigned char *mlo, unsigned int image_size,
                       int stream, int header_only, int current_configuration) {
    if (current_configuration == 1) {
        printf("%.6f Configuration already 1 in sysfs; skipping reset-prone SETCONFIGURATION.\n",
               wall_now());
    } else {
        int configuration = 1;
        double configured_at = wall_now();
        int config_rc = ioctl(fd, USBDEVFS_SETCONFIGURATION, &configuration);
        int config_err = errno;
        printf("%.6f Set configuration 1 (sysfs was %d): %d, errno=%d (%s), duration=%.3f ms\n",
               configured_at, current_configuration, config_rc,
               config_rc < 0 ? config_err : 0,
               config_rc < 0 ? strerror(config_err) : "success",
               (wall_now() - configured_at) * 1000);
        if (config_rc < 0) return 1;
    }
    int interface = 0;
    double started = wall_now();
    int rc = ioctl(fd, USBDEVFS_CLAIMINTERFACE, &interface);
    int err = errno;
    printf("%.6f Claim interface: %d, errno=%d (%s), duration=%.3f ms\n",
           started, rc, rc < 0 ? err : 0, rc < 0 ? strerror(err) : "success",
           (wall_now() - started) * 1000);
    if (rc < 0) return 1;
    const unsigned char boot[4] = {0x02, 0x00, 0x03, 0xf0};
    const unsigned char size[4] = {
        image_size & 0xff, (image_size >> 8) & 0xff,
        (image_size >> 16) & 0xff, (image_size >> 24) & 0xff,
    };
    int failed = usbfs_send(fd, boot, 4, "BOOT") ||
        usbfs_send(fd, size, 4, "image length");
    if (!failed && stream) {
        failed = usbfs_send(fd, mlo, (int)image_size, "2ND continuous image");
    } else {
        unsigned int send_size = header_only ? 1024U : image_size;
        for (unsigned int offset = 0; !failed && offset < send_size;) {
            unsigned int remaining = send_size - offset;
            int length = remaining < 512U ? (int)remaining : 512;
            char label[48];
            snprintf(label, sizeof(label), "image packet 0x%04x", offset);
            failed = usbfs_send(fd, mlo + offset, length, label);
            offset += (unsigned int)length;
        }
    }
    ioctl(fd, USBDEVFS_RELEASEINTERFACE, &interface);
    return failed;
}

static int matches(libusb_device *dev) {
    uint8_t ports[8];
    struct libusb_device_descriptor d;
    int n = libusb_get_port_numbers(dev, ports, sizeof(ports));
    return libusb_get_bus_number(dev) == 3 && n == 2 &&
        ports[0] == 2 && ports[1] == 2 &&
        libusb_get_device_descriptor(dev, &d) == 0 &&
        d.idVendor == 0x0451 && d.idProduct == 0xd010;
}

static int send_exact(libusb_device_handle *h, const unsigned char *data,
                      int length, const char *what, unsigned int timeout_ms) {
    int sent = 0;
    int rc = libusb_bulk_transfer(h, 0x01, (unsigned char *)data, length,
                                  &sent, timeout_ms);
    printf("%s: %s, %d/%d bytes\n", what, libusb_error_name(rc), sent, length);
    return rc == 0 && sent == length ? 0 : 1;
}

static void put_le32(unsigned char *p, uint32_t value) {
    p[0] = value & 0xff;
    p[1] = (value >> 8) & 0xff;
    p[2] = (value >> 16) & 0xff;
    p[3] = (value >> 24) & 0xff;
}

static unsigned char *make_void_ch(void) {
    unsigned char *image = calloc(1, CH_SIZE);
    if (!image) return NULL;

    /* TI OMAP4 TRM tables 27-47/27-48: one disabled CHSETTINGS item.
     * The structure matches a known valid OMAP first sector:
     *   TOC offset 0x40, item size 0x0c, closing item of 0xffffffff words,
     *   key 0xc0c0c0c1, Valid=0, Version=1.
     */
    put_le32(image + 0x00, 0x40);
    put_le32(image + 0x04, 0x0c);
    memcpy(image + 0x14, "CHSETTINGS", 10);
    memset(image + 0x20, 0xff, 0x20);
    put_le32(image + 0x40, 0xc0c0c0c1);
    image[0x44] = 0;
    image[0x45] = 1;
    return image;
}

static int send_image_packets(libusb_device_handle *h, const unsigned char *data,
                              unsigned int size, const char *label) {
    unsigned int offset = 0;
    while (offset < size) {
        unsigned int remaining = size - offset;
        int length = remaining < 512U ? (int)remaining : 512;
        int sent = 0;
        int rc = libusb_bulk_transfer(h, 0x01, (unsigned char *)data + offset,
                                      length, &sent, 2000);
        printf("%s packet at 0x%04x: %s, %d/%d bytes\n",
               label, offset, libusb_error_name(rc), sent, length);
        if (rc != 0 || sent != length) return 1;
        offset += (unsigned int)sent;
        /* The HS ROM handled a four-byte image but stalled a single large MLO
         * URB after one 512-byte max-packet. Give its first-sector parser time
         * to run before submitting the next independently completed transfer.
         */
        usleep(2000);
    }
    return 0;
}

static unsigned char *read_and_verify(const char *path, int exact) {
    unsigned int image_size = exact ? EXACT_MLO_SIZE : MLO_SIZE;
    const unsigned char *expected = exact ? exact_mlo_sha256 : expected_sha256;
    unsigned char *data = malloc(image_size);
    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned int digest_len = 0;
    if (!data) return NULL;

    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "%s: %s\n", path, strerror(errno));
        free(data);
        return NULL;
    }
    size_t got = fread(data, 1, image_size, f);
    int extra = fgetc(f);
    int read_error = ferror(f);
    fclose(f);
    if (read_error || got != image_size || extra != EOF) {
        fprintf(stderr, "Refusing MLO with size other than %u bytes.\n", image_size);
        free(data);
        return NULL;
    }
    if (memcmp(data + 0x200, "CertPK_\0", 8) != 0 ||
        memcmp(data + 0xc00, "CertPPA\0", 8) != 0 ||
        memcmp(data + 0x4000, "CertISW\0", 8) != 0 ||
        EVP_Digest(data, image_size, digest, &digest_len, EVP_sha256(), NULL) != 1 ||
        digest_len != sizeof(expected_sha256) ||
        memcmp(digest, expected, sizeof(expected_sha256)) != 0) {
        fputs("MLO markers or SHA-256 mismatch; refusing upload.\n", stderr);
        free(data);
        return NULL;
    }
    return data;
}

static unsigned char *read_foreign_2nd(const char *path) {
    unsigned char *data = malloc(FOREIGN_2ND_SIZE);
    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned int digest_len = 0;
    if (!data) return NULL;
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "%s: %s\n", path, strerror(errno));
        free(data);
        return NULL;
    }
    size_t got = fread(data, 1, FOREIGN_2ND_SIZE, f);
    int extra = fgetc(f);
    int read_error = ferror(f);
    fclose(f);
    if (read_error || got != FOREIGN_2ND_SIZE || extra != EOF ||
        memcmp(data + 0x14, "2ND\0", 4) != 0 ||
        memcmp(data + 0x200, "CertPK_\0", 8) != 0 ||
        memcmp(data + 0xc00, "CertPPA\0", 8) != 0 ||
        EVP_Digest(data, FOREIGN_2ND_SIZE, digest, &digest_len,
                   EVP_sha256(), NULL) != 1 ||
        digest_len != sizeof(foreign_2nd_sha256) ||
        memcmp(digest, foreign_2nd_sha256, sizeof(foreign_2nd_sha256)) != 0) {
        fputs("Foreign 2ND image size, markers, or SHA-256 mismatch.\n", stderr);
        free(data);
        return NULL;
    }
    return data;
}

static int probe(libusb_device *dev, libusb_device_handle *h,
                 const unsigned char *ch, const unsigned char *mlo, int fast) {
    int rc;
    if (!h) {
        rc = libusb_open(dev, &h);
        if (rc < 0) {
            fprintf(stderr, "Open: %s\n", libusb_error_name(rc));
            return 1;
        }
    }
    int current = 0;
    rc = libusb_get_configuration(h, &current);
    if (rc == 0 && current == 0) rc = libusb_set_configuration(h, 1);
    if (rc == 0) rc = libusb_claim_interface(h, 0);
    if (rc < 0) {
        fprintf(stderr, "USB setup: %s\n", libusb_error_name(rc));
        libusb_close(h);
        return 1;
    }

    const unsigned char get_id[4] = {0x03, 0x00, 0x03, 0xf0};
    const unsigned char boot[4] = {0x02, 0x00, 0x03, 0xf0};
    const unsigned char ch_length[4] = {
        CH_SIZE & 0xff, (CH_SIZE >> 8) & 0xff,
        (CH_SIZE >> 16) & 0xff, (CH_SIZE >> 24) & 0xff,
    };
    const unsigned char mlo_length[4] = {
        MLO_SIZE & 0xff, (MLO_SIZE >> 8) & 0xff,
        (MLO_SIZE >> 16) & 0xff, (MLO_SIZE >> 24) & 0xff,
    };
    unsigned char id[256];
    int received = 0;
    if (fast) {
        /* One cold-boot attempt to separate the 250-ms USB boot window from
         * parser rejection. The physical port and MLO hash were checked
         * before any outbound request. Skip optional GET_ID and CH traffic.
         */
        printf("Fast transfer start Unix time: %.6f\n", wall_now());
        if (send_exact(h, boot, sizeof(boot), "Fast MLO BOOT", 1000)) goto error;
        if (send_exact(h, mlo_length, sizeof(mlo_length), "Fast MLO length", 1000)) goto error;
        if (send_exact(h, mlo, MLO_SIZE, "Fast pinned MLO", 1000)) goto error;
        puts("Fast transfer finished. Check serial for the 2014 MLO banner.");
        libusb_release_interface(h, 0);
        libusb_close(h);
        return 0;
    }
    if (send_exact(h, get_id, sizeof(get_id), "GET_ID", 1000)) goto error;
    rc = libusb_bulk_transfer(h, 0x81, id, sizeof(id), &received, 1000);
    printf("ASIC ID: %s, %d bytes\n", libusb_error_name(rc), received);
    if (rc != 0 || received != 81 || id[0] != 5 || id[1] != 1 ||
        id[2] != 5 || id[3] != 1 || id[4] != 0x44 || id[5] != 0x40) {
        fputs("Unexpected ASIC ID; refusing upload.\n", stderr);
        goto error;
    }
    /* MPKH TLV starts at byte 35: type 0x14, length 33, format 1. */
    if (id[35] != 0x14 || id[36] != 33 || id[37] != 1 ||
        memcmp(id + 38,
            "\x8b\x84\x6a\x5a\x4b\xd7\x8d\x86\xfd\xbe\xee\x1c\x4c\xe0\xed\x07"
            "\x4e\x91\xb9\xf5\x01\xf8\x06\x52\xd1\xb6\x08\x4b\x1c\x0f\xa7\x42",
            32) != 0) {
        fputs("Target MPKH mismatch; refusing upload.\n", stderr);
        goto error;
    }

    if (send_exact(h, boot, sizeof(boot), "CH BOOT", 1000)) goto error;
    if (send_exact(h, ch_length, sizeof(ch_length), "CH length", 1000)) goto error;
    if (send_image_packets(h, ch, CH_SIZE, "CH")) goto error;

    /* The ROM treats a CH as its own transfer, executes it, then returns to
     * peripheral synchronization on the still-open USB endpoints.
     */
    usleep(50000);
    received = 0;
    if (send_exact(h, get_id, sizeof(get_id), "Post-CH GET_ID", 1000)) goto error;
    rc = libusb_bulk_transfer(h, 0x81, id, sizeof(id), &received, 1000);
    printf("Post-CH ASIC ID: %s, %d bytes\n", libusb_error_name(rc), received);
    if (rc != 0 || received != 81 || id[0] != 5 || id[4] != 0x44 ||
        id[5] != 0x40) {
        fputs("ROM did not return to synchronization after CH.\n", stderr);
        goto error;
    }

    if (send_exact(h, boot, sizeof(boot), "MLO BOOT", 1000)) goto error;
    if (send_exact(h, mlo_length, sizeof(mlo_length), "MLO length", 1000)) goto error;
    if (send_image_packets(h, mlo, MLO_SIZE, "MLO")) goto error;
    puts("Transfer finished. Check serial for the 2014 MLO banner.");
    libusb_release_interface(h, 0);
    libusb_close(h);
    return 0;
error:
    libusb_release_interface(h, 0);
    libusb_close(h);
    return 1;
}

int main(int argc, char **argv) {
    int fast = argc == 3 && strcmp(argv[2], "--fast") == 0;
    int direct = argc == 3 && strcmp(argv[2], "--direct") == 0;
    int usbfs = argc == 3 && strcmp(argv[2], "--usbfs") == 0;
    int usbfs_port_arg = argc == 4 && strcmp(argv[2], "--usbfs-port") == 0;
    int usbfs_exact_port_arg = argc == 4 && strcmp(argv[2], "--usbfs-exact-port") == 0;
    int usbfs_exact_ppa_2nd = argc == 4 && strcmp(argv[2], "--usbfs-exact-ppa-2nd") == 0;
    int usbfs_exact_ppa_2nd_plus4 = argc == 4 && strcmp(argv[2], "--usbfs-exact-ppa-2nd-plus4") == 0;
    int usbfs_ulo_name = argc == 4 && strcmp(argv[2], "--usbfs-port-ulo-name") == 0;
    int usbfs_2nd_name = argc == 4 && strcmp(argv[2], "--usbfs-port-2nd-name") == 0;
    int usbfs_2nd_stream = argc == 4 && strcmp(argv[2], "--usbfs-port-2nd-stream") == 0;
    int usbfs_foreign_header = argc == 4 && strcmp(argv[2], "--usbfs-foreign-header-only") == 0;
    int usbfs_foreign_long = argc == 4 && strcmp(argv[2], "--usbfs-foreign-header-long-length") == 0;
    int usbfs_foreign_cisco_span = argc == 4 && strcmp(argv[2], "--usbfs-foreign-header-cisco-span") == 0;
    int usbfs_foreign_32k = argc == 4 && strcmp(argv[2], "--usbfs-foreign-header-32k") == 0;
    int usbfs_foreign_24k = argc == 4 && strcmp(argv[2], "--usbfs-foreign-header-24k") == 0;
    int usbfs_foreign_28k = argc == 4 && strcmp(argv[2], "--usbfs-foreign-header-28k") == 0;
    int usbfs_foreign_31k = argc == 4 && strcmp(argv[2], "--usbfs-foreign-header-31k") == 0;
    int usbfs_foreign_34k = argc == 4 && strcmp(argv[2], "--usbfs-foreign-header-34k") == 0;
    int foreign_header = usbfs_foreign_header || usbfs_foreign_long ||
                         usbfs_foreign_cisco_span || usbfs_foreign_32k ||
                         usbfs_foreign_24k || usbfs_foreign_28k ||
                         usbfs_foreign_31k || usbfs_foreign_34k;
    if (argc != 2 && !fast && !direct && !usbfs && !usbfs_port_arg &&
        !usbfs_exact_port_arg && !usbfs_exact_ppa_2nd &&
        !usbfs_exact_ppa_2nd_plus4 &&
        !usbfs_ulo_name && !usbfs_2nd_name && !usbfs_2nd_stream &&
        !foreign_header) {
        fprintf(stderr, "Usage: %s image [--fast|--direct|--usbfs|--usbfs-port BUS-PORT.2|--usbfs-exact-port BUS-PORT.2|--usbfs-exact-ppa-2nd BUS-PORT.2|--usbfs-exact-ppa-2nd-plus4 BUS-PORT.2|--usbfs-port-ulo-name BUS-PORT.2|--usbfs-port-2nd-name BUS-PORT.2|--usbfs-port-2nd-stream BUS-PORT.2|--usbfs-foreign-header-only BUS-PORT.2|--usbfs-foreign-header-long-length BUS-PORT.2|--usbfs-foreign-header-cisco-span BUS-PORT.2|--usbfs-foreign-header-32k BUS-PORT.2|--usbfs-foreign-header-24k BUS-PORT.2|--usbfs-foreign-header-28k BUS-PORT.2|--usbfs-foreign-header-31k BUS-PORT.2|--usbfs-foreign-header-34k BUS-PORT.2]\n", argv[0]);
        return 2;
    }
    const char *usbfs_port = (usbfs_port_arg || usbfs_exact_port_arg || usbfs_exact_ppa_2nd || usbfs_exact_ppa_2nd_plus4 || usbfs_ulo_name || usbfs_2nd_name || usbfs_2nd_stream || foreign_header) ? argv[3] : "3-2.2";
    if (usbfs_port_arg || usbfs_exact_port_arg || usbfs_exact_ppa_2nd || usbfs_exact_ppa_2nd_plus4 || usbfs_ulo_name || usbfs_2nd_name || usbfs_2nd_stream || foreign_header) usbfs = 1;
    int usbfs_bus = 3;
    if (usbfs && !validate_usbfs_port(usbfs_port, &usbfs_bus)) {
        fprintf(stderr, "Refusing USBFS port %s: Touch 10 FTDI sibling identity is missing.\n", usbfs_port);
        return 2;
    }
    unsigned char *mlo = foreign_header ? read_foreign_2nd(argv[1]) :
                         read_and_verify(argv[1], usbfs_exact_port_arg || usbfs_exact_ppa_2nd || usbfs_exact_ppa_2nd_plus4);
    if (!mlo) return 1;
    if (usbfs_exact_ppa_2nd || usbfs_exact_ppa_2nd_plus4) {
        if (memcmp(mlo, "\x00\x40\x00\x00\x40\x60\x00\x00", 8) != 0 ||
            memcmp(mlo + 0x20, "\x00\x0c\x00\x00\x9c\x33\x00\x00", 8) != 0 ||
            memcmp(mlo + 0x14, "MLO\0", 4) != 0) {
            fputs("Exact MLO TOC layout mismatch; refusing PPA control.\n", stderr);
            free(mlo);
            return 2;
        }
        put_le32(mlo, 0x0c00);
        put_le32(mlo + 4, usbfs_exact_ppa_2nd_plus4 ? 0x33a0 : 0x339c);
        memcpy(mlo + 0x14, "2ND\0", 4);
        printf("Volatile exact-PPA 2ND control: total %u bytes, signed PPA and root key unchanged; PRIMAPP TOC size unchanged.\n",
               usbfs_exact_ppa_2nd_plus4 ? EXACT_PPA_2ND_PLUS4_SIZE : EXACT_PPA_2ND_SIZE);
    }
    if (usbfs_foreign_cisco_span) {
        if (memcmp(mlo, "\x00\x1a\x00\x00\x30\x3a\x00\x00", 8) != 0) {
            fputs("Foreign 2ND TOC does not have the expected original span.\n", stderr);
            free(mlo);
            return 2;
        }
        put_le32(mlo, 0x4000);
        put_le32(mlo + 4, 0x629c);
        puts("Volatile header-only control: 2ND span changed to Cisco offset/size; PRIMAPP size kept small.");
    }
    if (usbfs_foreign_32k || usbfs_foreign_24k || usbfs_foreign_28k ||
        usbfs_foreign_31k || usbfs_foreign_34k) {
        if (memcmp(mlo, "\x00\x1a\x00\x00\x30\x3a\x00\x00", 8) != 0) {
            fputs("Foreign 2ND TOC does not have the expected original span.\n", stderr);
            free(mlo);
            return 2;
        }
        unsigned int total = usbfs_foreign_32k ? FOREIGN_32K_SIZE :
                             usbfs_foreign_34k ? FOREIGN_34K_SIZE :
                             usbfs_foreign_31k ? FOREIGN_31K_SIZE :
                             usbfs_foreign_28k ? FOREIGN_28K_SIZE : FOREIGN_24K_SIZE;
        put_le32(mlo + 4, total - 0x1a00);
        printf("Volatile header-only control: 2ND item ends at %u bytes; PRIMAPP unchanged.\n", total);
    }
    if (foreign_header)
        printf("Bounded foreign 2ND format control: declared length %u, at most two 512-byte sectors sent.\n",
               usbfs_foreign_32k ? FOREIGN_32K_SIZE :
               usbfs_foreign_34k ? FOREIGN_34K_SIZE :
               usbfs_foreign_31k ? FOREIGN_31K_SIZE :
               usbfs_foreign_28k ? FOREIGN_28K_SIZE :
               usbfs_foreign_24k ? FOREIGN_24K_SIZE :
               (usbfs_foreign_long || usbfs_foreign_cisco_span) ? MLO_SIZE : FOREIGN_2ND_SIZE);
    if (usbfs_ulo_name || usbfs_2nd_name || usbfs_2nd_stream) {
        if (memcmp(mlo + 0x14, "MLO\0", 4) != 0) {
            fputs("Reference TOC does not contain expected MLO name.\n", stderr);
            free(mlo);
            return 2;
        }
        memcpy(mlo + 0x14, (usbfs_2nd_name || usbfs_2nd_stream) ? "2ND\0" : "ULO\0", 4);
        printf("Volatile test: outer TOC item name MLO -> %s at 0x14; certificate regions unchanged.\n",
               (usbfs_2nd_name || usbfs_2nd_stream) ? "2ND" : "ULO");
    }
    unsigned char *ch = make_void_ch();
    if (!ch) {
        free(mlo);
        return 1;
    }
    setvbuf(stdout, NULL, _IOLBF, 0);
    libusb_context *ctx = NULL;
    int rc = libusb_init(&ctx);
    if (rc < 0) {
        fprintf(stderr, "libusb: %s\n", libusb_error_name(rc));
        free(ch);
        free(mlo);
        return 1;
    }
    printf("Waiting 10 minutes for the pinned Touch 10 OMAP ROM USB path (%s).\n",
           usbfs ? "direct usbfs" : direct ? "direct sysfs" :
           fast ? "fast" : "CH then MLO");
    double deadline = now() + 600;
    if (direct || usbfs) {
        while (now() < deadline) {
            char sysfs_path[128];
            snprintf(sysfs_path, sizeof(sysfs_path), "/sys/bus/usb/devices/%s/devnum", usbfs_port);
            int devnum = read_sysfs_number(sysfs_path, 10);
            snprintf(sysfs_path, sizeof(sysfs_path), "/sys/bus/usb/devices/%s/idVendor", usbfs_port);
            int vendor = read_sysfs_number(sysfs_path, 16);
            snprintf(sysfs_path, sizeof(sysfs_path), "/sys/bus/usb/devices/%s/idProduct", usbfs_port);
            int product = read_sysfs_number(sysfs_path, 16);
            if (devnum < 1 || devnum > 127 ||
                vendor != 0x0451 || product != 0xd010) {
                usleep(1000);
                continue;
            }
            char path[64];
            snprintf(path, sizeof(path), "/dev/bus/usb/%03d/%03d", usbfs_bus, devnum);
            int fd = open(path, O_RDWR | O_CLOEXEC);
            if (fd < 0) {
                usleep(1000);
                continue;
            }
            printf("%.6f Opened %s\n", wall_now(), path);
            if (usbfs) {
                snprintf(sysfs_path, sizeof(sysfs_path),
                         "/sys/bus/usb/devices/%s/bConfigurationValue", usbfs_port);
                int current_configuration = read_sysfs_number(sysfs_path, 10);
                rc = usbfs_probe(fd, mlo,
                                 usbfs_foreign_32k ? FOREIGN_32K_SIZE :
                                 usbfs_foreign_34k ? FOREIGN_34K_SIZE :
                                 usbfs_foreign_31k ? FOREIGN_31K_SIZE :
                                 usbfs_foreign_28k ? FOREIGN_28K_SIZE :
                                 usbfs_foreign_24k ? FOREIGN_24K_SIZE :
                                 (usbfs_foreign_long || usbfs_foreign_cisco_span) ? MLO_SIZE :
                                 usbfs_foreign_header ? FOREIGN_2ND_SIZE :
                                 usbfs_exact_ppa_2nd_plus4 ? EXACT_PPA_2ND_PLUS4_SIZE :
                                 usbfs_exact_ppa_2nd ? EXACT_PPA_2ND_SIZE :
                                 usbfs_exact_port_arg ? EXACT_MLO_SIZE : MLO_SIZE,
                                 usbfs_2nd_stream, foreign_header,
                                 current_configuration);
                close(fd);
                libusb_exit(ctx);
                free(ch);
                free(mlo);
                return rc;
            }
            libusb_device_handle *h = NULL;
            rc = libusb_wrap_sys_device(ctx, fd, &h);
            if (rc != 0) {
                close(fd);
                usleep(1000);
                continue;
            }
            struct libusb_device_descriptor descriptor;
            libusb_device *wrapped = libusb_get_device(h);
            if (libusb_get_device_descriptor(wrapped, &descriptor) != 0 ||
                descriptor.idVendor != 0x0451 || descriptor.idProduct != 0xd010) {
                fputs("Wrapped USB identity mismatch; refusing upload.\n", stderr);
                libusb_close(h);
                close(fd);
                break;
            }
            printf("Direct open of %s at Unix time %.6f\n", path, wall_now());
            double found_at = now();
            rc = probe(NULL, h, ch, mlo, 1);
            printf("Probe elapsed after direct open: %.3f seconds\n", now() - found_at);
            close(fd);
            libusb_exit(ctx);
            free(ch);
            free(mlo);
            return rc;
        }
        libusb_exit(ctx);
        free(ch);
        free(mlo);
        fputs("Direct USB device not found.\n", stderr);
        return 1;
    }
    while (now() < deadline) {
        libusb_device **list = NULL;
        ssize_t count = libusb_get_device_list(ctx, &list);
        if (count < 0) break;
        for (ssize_t i = 0; i < count; ++i) {
            if (!matches(list[i])) continue;
            printf("Found TI ROM at bus %u address %u.\n",
                   libusb_get_bus_number(list[i]), libusb_get_device_address(list[i]));
            double found_at = now();
            rc = probe(list[i], NULL, ch, mlo, fast);
            printf("Probe elapsed after discovery: %.3f seconds\n", now() - found_at);
            libusb_free_device_list(list, 1);
            libusb_exit(ctx);
            free(ch);
            free(mlo);
            return rc;
        }
        libusb_free_device_list(list, 1);
        usleep(20000);
    }
    libusb_exit(ctx);
    free(ch);
    free(mlo);
    fputs("ROM device not found.\n", stderr);
    return 1;
}
