/* Read-only GET_ID query for the currently enumerated Touch 10 ROM USB port. */
#include <libusb-1.0/libusb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int check_sibling(void) {
    FILE *f = fopen("/sys/bus/usb/devices/2-1.1.1/serial", "r");
    if (!f) return 0;
    char serial[64] = {0};
    int ok = fgets(serial, sizeof(serial), f) &&
             strcmp(serial, "D3081QEX\n") == 0;
    fclose(f);
    return ok;
}

int main(void) {
    if (!check_sibling()) {
        fputs("Touch 10 FTDI sibling serial mismatch.\n", stderr);
        return 2;
    }
    libusb_context *ctx = NULL;
    int rc = libusb_init(&ctx);
    if (rc) return 1;
    libusb_device **list = NULL;
    ssize_t count = libusb_get_device_list(ctx, &list);
    if (count < 0) { libusb_exit(ctx); return 1; }
    int found = 0;
    int got_id = 0;
    for (ssize_t i = 0; i < count; ++i) {
        struct libusb_device_descriptor d;
        uint8_t path[8];
        int n = libusb_get_port_numbers(list[i], path, sizeof(path));
        if (libusb_get_bus_number(list[i]) != 2 || n != 3 ||
            path[0] != 1 || path[1] != 1 || path[2] != 2 ||
            libusb_get_device_descriptor(list[i], &d) ||
            d.idVendor != 0x0451 || d.idProduct != 0xd010) continue;
        ++found;
        libusb_device_handle *h = NULL;
        rc = libusb_open(list[i], &h);
        if (rc) { printf("open: %s\n", libusb_error_name(rc)); break; }
        int cfg = 0;
        rc = libusb_get_configuration(h, &cfg);
        printf("configuration: %d, rc=%s\n", cfg, libusb_error_name(rc));
        if (rc == 0 && cfg == 0) rc = libusb_set_configuration(h, 1);
        if (rc == 0) rc = libusb_claim_interface(h, 0);
        if (rc) { printf("claim: %s\n", libusb_error_name(rc)); libusb_close(h); break; }
        unsigned char req[4] = {0x03, 0x00, 0x03, 0xf0};
        unsigned char response[256];
        int sent = 0, received = 0;
        rc = libusb_bulk_transfer(h, 0x01, req, 4, &sent, 1000);
        printf("GET_ID request: %s, %d/4 bytes\n", libusb_error_name(rc), sent);
        if (rc == 0 && sent == 4) {
            rc = libusb_bulk_transfer(h, 0x81, response, sizeof(response),
                                      &received, 1000);
            printf("GET_ID response: %s, %d bytes\n", libusb_error_name(rc), received);
            if (rc == 0 && received >= 6)
                printf("identity prefix: %02x %02x %02x %02x %02x %02x\n",
                       response[0], response[1], response[2], response[3],
                       response[4], response[5]);
            got_id = rc == 0 && received == 81;
        }
        libusb_release_interface(h, 0);
        libusb_close(h);
        break;
    }
    if (!found) puts("No matching ROM USB device is present.");
    libusb_free_device_list(list, 1);
    libusb_exit(ctx);
    return found && got_id ? 0 : 1;
}
