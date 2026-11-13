/* Bounded Touch 10 ROM USB reset experiment. Sends GET_ID only. */
#include <libusb-1.0/libusb.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static const uint8_t get_id[4] = {0x03, 0x00, 0x03, 0xf0};
static const uint8_t mpkh[32] = {
    0x8b,0x84,0x6a,0x5a,0x4b,0xd7,0x8d,0x86,
    0xfd,0xbe,0xee,0x1c,0x4c,0xe0,0xed,0x07,
    0x4e,0x91,0xb9,0xf5,0x01,0xf8,0x06,0x52,
    0xd1,0xb6,0x08,0x4b,0x1c,0x0f,0xa7,0x42,
};

static double stamp(void) {
    struct timespec t;
    clock_gettime(CLOCK_REALTIME, &t);
    return (double)t.tv_sec + (double)t.tv_nsec / 1e9;
}

static int sysfs_line_is(const char *path, const char *expected) {
    FILE *f = fopen(path, "r");
    char line[128];
    int same = f && fgets(line, sizeof(line), f) &&
        strcspn(line, "\r\n") == strlen(expected) &&
        strncmp(line, expected, strlen(expected)) == 0;
    if (f) fclose(f);
    return same;
}

static int parse_target(const char *name, int *bus, uint8_t ports[8], int *count) {
    int b, a, c, d;
    char extra;
    char sibling[128];
    if (sscanf(name, "%d-%d.%d.%d%c", &b, &a, &c, &d, &extra) != 4 ||
        b < 1 || b > 255 || a < 1 || a > 255 || c < 1 || c > 255 || d != 2)
        return 0;
    snprintf(sibling, sizeof(sibling),
             "/sys/bus/usb/devices/%d-%d.%d.1/idVendor", b, a, c);
    if (!sysfs_line_is(sibling, "0403")) return 0;
    snprintf(sibling, sizeof(sibling),
             "/sys/bus/usb/devices/%d-%d.%d.1/idProduct", b, a, c);
    if (!sysfs_line_is(sibling, "6015")) return 0;
    snprintf(sibling, sizeof(sibling),
             "/sys/bus/usb/devices/%d-%d.%d.1/serial", b, a, c);
    if (!sysfs_line_is(sibling, "D3081QEX")) return 0;
    *bus = b;
    ports[0] = a; ports[1] = c; ports[2] = d; *count = 3;
    return 1;
}

static libusb_device *find_target(libusb_context *ctx, int bus,
                                  const uint8_t *ports, int count) {
    libusb_device **list = NULL, *result = NULL;
    ssize_t n = libusb_get_device_list(ctx, &list);
    int matches = 0;
    if (n < 0) return NULL;
    for (ssize_t i = 0; i < n; ++i) {
        uint8_t path[8];
        struct libusb_device_descriptor d;
        int got = libusb_get_port_numbers(list[i], path, sizeof(path));
        if (libusb_get_bus_number(list[i]) != bus || got != count ||
            memcmp(path, ports, (size_t)count) != 0 ||
            libusb_get_device_descriptor(list[i], &d) != 0 ||
            d.idVendor != 0x0451 || d.idProduct != 0xd010) continue;
        ++matches;
        result = libusb_ref_device(list[i]);
    }
    libusb_free_device_list(list, 1);
    if (matches == 1) return result;
    if (result) libusb_unref_device(result);
    return NULL;
}

static int open_ready(libusb_device *dev, libusb_device_handle **handle) {
    int config = 0;
    int rc = libusb_open(dev, handle);
    if (rc == 0) rc = libusb_get_configuration(*handle, &config);
    if (rc == 0 && config == 0) rc = libusb_set_configuration(*handle, 1);
    if (rc == 0 && config != 0 && config != 1) rc = LIBUSB_ERROR_INVALID_PARAM;
    if (rc == 0) rc = libusb_claim_interface(*handle, 0);
    printf("%.6f USB open/config/claim: %s (config before=%d)\n",
           stamp(), libusb_error_name(rc), config);
    if (rc != 0 && *handle) { libusb_close(*handle); *handle = NULL; }
    return rc;
}

static int query_id(libusb_device_handle *h, const char *label) {
    uint8_t response[256] = {0};
    int sent = 0, received = 0;
    int rc = libusb_bulk_transfer(h, 0x01, (unsigned char *)get_id,
                                  sizeof(get_id), &sent, 500);
    printf("%.6f %s GET_ID OUT: %s %d/4\n", stamp(), label,
           libusb_error_name(rc), sent);
    if (rc != 0 || sent != 4) return 1;
    rc = libusb_bulk_transfer(h, 0x81, response, sizeof(response),
                              &received, 500);
    printf("%.6f %s GET_ID IN: %s %d bytes\n", stamp(), label,
           libusb_error_name(rc), received);
    if (rc != 0 || received != 81 || response[0] != 5 ||
        response[1] != 1 || response[2] != 5 || response[3] != 1 ||
        response[4] != 0x44 || response[5] != 0x40 ||
        response[35] != 0x14 || response[36] != 33 ||
        response[37] != 1 || memcmp(response + 38, mpkh, 32) != 0) {
        puts("Target identity mismatch or incomplete reply.");
        return 1;
    }
    printf("%.6f %s identity matched; flags byte 6=0x%02x\n",
           stamp(), label, response[6]);
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 3 || strcmp(argv[1], "--run") != 0) {
        fprintf(stderr, "Usage: %s --run BUS-PORT.PORT.2\n", argv[0]);
        return 2;
    }
    int bus, count;
    uint8_t ports[8];
    if (!parse_target(argv[2], &bus, ports, &count)) {
        fputs("Target port or FTDI sibling verification failed.\n", stderr);
        return 2;
    }
    libusb_context *ctx = NULL;
    if (libusb_init(&ctx) != 0) return 2;
    printf("%.6f Waiting up to 180 seconds for pinned TI ROM at %s\n",
           stamp(), argv[2]);
    fflush(stdout);
    libusb_device *dev = NULL;
    double limit = stamp() + 180.0;
    while (!dev && stamp() < limit) {
        dev = find_target(ctx, bus, ports, count);
        if (!dev) usleep(5000);
    }
    if (!dev) { puts("ROM device did not appear."); libusb_exit(ctx); return 1; }
    printf("%.6f Pinned ROM device found\n", stamp());
    libusb_device_handle *h = NULL;
    int status = 1;
    if (open_ready(dev, &h) != 0) goto done;
    if (query_id(h, "baseline 1") || query_id(h, "baseline 2")) goto done;
    usleep(10000); /* ROM is now waiting for its next four-byte command. */
    printf("%.6f Resetting only the pinned TI ROM USB device\n", stamp());
    fflush(stdout);
    double reset_started = stamp();
    int rc = libusb_reset_device(h);
    printf("%.6f libusb_reset_device: %s (%.3f seconds)\n",
           stamp(), libusb_error_name(rc), stamp() - reset_started);
    libusb_close(h); h = NULL;
    libusb_unref_device(dev); dev = NULL;
    /* A port reset may assign a new USB address; rediscover by physical path. */
    limit = stamp() + 2.2;
    while (!h && stamp() < limit) {
        dev = find_target(ctx, bus, ports, count);
        if (dev) {
            printf("%.6f Pinned ROM device rediscovered\n", stamp());
            if (open_ready(dev, &h) != 0) {
                libusb_unref_device(dev);
                dev = NULL;
            }
        }
        if (!h) usleep(5000);
    }
    if (!h) { puts("No usable pinned ROM device after reset."); goto done; }
    status = query_id(h, "post-reset");
done:
    if (h) { libusb_release_interface(h, 0); libusb_close(h); }
    if (dev) libusb_unref_device(dev);
    libusb_exit(ctx);
    printf("%.6f Probe result: %s\n", stamp(), status ? "no post-reset ID" : "post-reset ID received");
    return status;
}
