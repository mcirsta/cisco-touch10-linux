/* Identification-only OMAP4 USB ROM probe. Never uploads or boots an image.
 * Protocol reference: kousu/omapboot, commit
 * 6057fa6100ffb3c1d1b26cfbf9c861526ff413d0, OMAP.py GET_ID.
 * Scope: VID:PID 0451:d010 on observed physical path bus 3, ports 2.2.
 */
#include <libusb-1.0/libusb.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static double monotime(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}

static int matches(libusb_device *dev, struct libusb_device_descriptor *desc) {
    uint8_t path[8];
    int n = libusb_get_port_numbers(dev, path, sizeof(path));
    return libusb_get_bus_number(dev) == 3 && n == 2 && path[0] == 2 && path[1] == 2
        && libusb_get_device_descriptor(dev, desc) == 0
        && desc->idVendor == 0x0451 && desc->idProduct == 0xd010;
}

static void print_blocks(const unsigned char *buf, int size) {
    if (size < 1) return;
    unsigned pos = 1;
    printf("ASIC response blocks: %u\n", buf[0]);
    for (unsigned i = 0; i < buf[0]; ++i) {
        if (pos + 2 > (unsigned)size) {
            puts("Incomplete block header; raw response retained."); return;
        }
        unsigned type = buf[pos++], len = buf[pos++];
        if (len == 0 || pos + len > (unsigned)size) {
            puts("Incomplete block; raw response retained."); return;
        }
        printf("Block 0x%02x, %u bytes, format marker 0x%02x", type, len, buf[pos]);
        if (type == 1 && len >= 5) {
            printf(", model bytes %02x%02x, CH byte %02x, revision byte %02x",
                buf[pos+1], buf[pos+2], buf[pos+3], buf[pos+4]);
        }
        puts("");
        pos += len;
    }
    if (pos != (unsigned)size) printf("Trailing bytes: %u\n", size - pos);
}

static int identify(libusb_device *dev, const char *output) {
    libusb_device_handle *handle = NULL;
    struct libusb_config_descriptor *config = NULL;
    int rc = libusb_open(dev, &handle), iface = -1;
    if (rc < 0) {
        fprintf(stderr, "Open: %s\n", libusb_error_name(rc)); return 1;
    }
    rc = libusb_get_config_descriptor(dev, 0, &config);
    if (rc < 0) goto error;
    unsigned char ep_in = 0, ep_out = 0;
    for (unsigned i = 0; i < config->bNumInterfaces && iface < 0; ++i) {
        const struct libusb_interface_descriptor *alt = &config->interface[i].altsetting[0];
        unsigned char in = 0, out = 0;
        for (unsigned j = 0; j < alt->bNumEndpoints; ++j) {
            const struct libusb_endpoint_descriptor *ep = &alt->endpoint[j];
            printf("Interface %u endpoint 0x%02x attributes 0x%02x maxpacket %u\n",
                alt->bInterfaceNumber, ep->bEndpointAddress, ep->bmAttributes, ep->wMaxPacketSize);
            if ((ep->bmAttributes & LIBUSB_TRANSFER_TYPE_MASK) == LIBUSB_TRANSFER_TYPE_BULK) {
                if (ep->bEndpointAddress & LIBUSB_ENDPOINT_IN) in = ep->bEndpointAddress;
                else out = ep->bEndpointAddress;
            }
        }
        if (in == 0x81 && out == 0x01) {
            iface = alt->bInterfaceNumber; ep_in = in; ep_out = out;
        }
    }
    if (iface < 0) { puts("Expected bulk endpoint pair not found; sending nothing."); rc = -2; goto error; }
    int current = 0;
    rc = libusb_get_configuration(handle, &current);
    if (rc < 0) goto error;
    if (current == 0) {
        /* Transient USB configuration only, not a firmware setting. */
        rc = libusb_set_configuration(handle, config->bConfigurationValue);
        if (rc < 0) goto error;
    }
    rc = libusb_claim_interface(handle, iface);
    if (rc < 0) goto error;
    /* The sole outbound protocol payload: little-endian GET_ID 0xF0030003. */
    unsigned char request[4] = {0x03, 0x00, 0x03, 0xf0};
    unsigned char response[1024];
    int sent = 0, received = 0;
    rc = libusb_bulk_transfer(handle, ep_out, request, sizeof(request), &sent, 500);
    if (rc == 0 && sent == 4)
        rc = libusb_bulk_transfer(handle, ep_in, response, sizeof(response), &received, 500);
    else if (rc == 0) rc = LIBUSB_ERROR_IO;
    if (rc == 0 && received > 0) {
        FILE *file = fopen(output, "wbx");
        if (!file) { perror("Output"); rc = LIBUSB_ERROR_IO; }
        else {
            size_t written = fwrite(response, 1, received, file);
            int closed = fclose(file);
            if (written != (size_t)received || closed != 0) rc = LIBUSB_ERROR_IO;
            else { printf("Saved %d ASIC-ID bytes to %s\n", received, output); print_blocks(response, received); }
        }
    } else if (rc == 0) rc = LIBUSB_ERROR_IO;
    libusb_release_interface(handle, iface);
error:
    if (rc < 0) fprintf(stderr, "Probe: %s\n", libusb_error_name(rc));
    if (config) libusb_free_config_descriptor(config);
    libusb_close(handle);
    return rc < 0;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s NEW_ASIC_ID_OUTPUT_FILE\n", argv[0]); return 2;
    }
    if (access(argv[1], F_OK) == 0) { fputs("Output already exists; refusing overwrite.\n", stderr); return 2; }
    setvbuf(stdout, NULL, _IOLBF, 0);
    libusb_context *ctx = NULL;
    int rc = libusb_init(&ctx);
    if (rc < 0) { fprintf(stderr, "libusb: %s\n", libusb_error_name(rc)); return 1; }
    puts("Waiting up to 600 seconds for 0451:d010 on bus 3, ports 2.2. Identification only.");
    double deadline = monotime() + 600;
    while (monotime() < deadline) {
        libusb_device **list = NULL;
        ssize_t n = libusb_get_device_list(ctx, &list);
        for (ssize_t i = 0; i < n; ++i) {
            struct libusb_device_descriptor desc;
            if (!matches(list[i], &desc)) continue;
            printf("Found TI ROM device, bus %u address %u, USB %04x\n",
                libusb_get_bus_number(list[i]), libusb_get_device_address(list[i]), desc.bcdUSB);
            rc = identify(list[i], argv[1]);
            libusb_free_device_list(list, 1); libusb_exit(ctx); return rc;
        }
        if (list) libusb_free_device_list(list, 1);
        usleep(20000);
    }
    libusb_exit(ctx); fputs("No matching ROM device before timeout.\n", stderr); return 1;
}
