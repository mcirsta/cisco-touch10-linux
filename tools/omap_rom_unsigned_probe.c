/* Bounded, volatile OMAP4 USB secure-boot check for the owner's Touch 10.
 * Sends GET_ID, BOOT, then a 4-byte unsigned peripheral-boot image containing
 * a single ARM branch-to-self instruction. Peripheral boot images start with
 * executable code; the GP header used for non-XIP memory boot is not present.
 * The guest image has no storage I/O. It can leave the unit stopped until a
 * power cycle if the ROM executes it.
 * This is not a firmware backup or an exploit. This program sends no signed
 * loader and performs no storage I/O.
 */
#include <libusb-1.0/libusb.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>
#include <unistd.h>

static double now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
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
                      int length, const char *what) {
    int sent = 0;
    int rc = libusb_bulk_transfer(h, 0x01, (unsigned char *)data, length,
                                  &sent, 1000);
    printf("%s: %s, %d/%d bytes\n", what, libusb_error_name(rc), sent, length);
    return rc == 0 && sent == length ? 0 : 1;
}

static int probe(libusb_device *dev) {
    libusb_device_handle *h = NULL;
    int rc = libusb_open(dev, &h);
    if (rc < 0) {
        fprintf(stderr, "Open: %s\n", libusb_error_name(rc));
        return 1;
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
    unsigned char id[256];
    int received = 0;
    if (send_exact(h, get_id, sizeof(get_id), "GET_ID")) goto error;
    rc = libusb_bulk_transfer(h, 0x81, id, sizeof(id), &received, 1000);
    printf("ASIC ID: %s, %d bytes\n", libusb_error_name(rc), received);
    if (rc != 0 || received != 81 || id[0] != 5 || id[1] != 1 ||
        id[2] != 5 || id[3] != 1 || id[4] != 0x44 || id[5] != 0x40) {
        fputs("Unexpected ASIC ID; refusing upload.\n", stderr);
        goto error;
    }

    /* The sole payload is ARM `b .` (EAFFFFFE), loaded at 0x40300000.
     * OMAP4 peripheral boot takes raw executable code after the host-provided
     * length; unlike non-XIP memory boot, it does not take a GP header.
     */
    const unsigned char boot[4] = {0x02, 0x00, 0x03, 0xf0};
    const unsigned char image_length[4] = {4, 0, 0, 0};
    const unsigned char image[4] = {0xfe, 0xff, 0xff, 0xea};
    if (send_exact(h, boot, sizeof(boot), "BOOT")) goto error;
    if (send_exact(h, image_length, sizeof(image_length), "Image length")) goto error;
    if (send_exact(h, image, sizeof(image), "Unsigned raw ARM image")) goto error;
    puts("Transfer finished. Observe serial boot and USB disconnect; power-cycle if it stops.");
    libusb_release_interface(h, 0);
    libusb_close(h);
    return 0;
error:
    libusb_release_interface(h, 0);
    libusb_close(h);
    return 1;
}

int main(void) {
    setvbuf(stdout, NULL, _IOLBF, 0);
    libusb_context *ctx = NULL;
    int rc = libusb_init(&ctx);
    if (rc < 0) {
        fprintf(stderr, "libusb: %s\n", libusb_error_name(rc));
        return 1;
    }
    puts("Waiting 10 minutes for OMAP ROM at USB bus 3, ports 2.2.");
    double deadline = now() + 600;
    while (now() < deadline) {
        libusb_device **list = NULL;
        ssize_t count = libusb_get_device_list(ctx, &list);
        if (count < 0) break;
        for (ssize_t i = 0; i < count; ++i) {
            if (!matches(list[i])) continue;
            printf("Found TI ROM at bus %u address %u.\n",
                   libusb_get_bus_number(list[i]), libusb_get_device_address(list[i]));
            rc = probe(list[i]);
            libusb_free_device_list(list, 1);
            libusb_exit(ctx);
            return rc;
        }
        libusb_free_device_list(list, 1);
        usleep(20000);
    }
    libusb_exit(ctx);
    fputs("ROM device not found.\n", stderr);
    return 1;
}
