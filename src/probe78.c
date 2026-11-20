/* Deeper probe of the 0x78/0x79 info-read commands: send, then drain bulk IN
 * repeatedly; try neighboring command bytes. */
#include <libusb-1.0/libusb.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    libusb_context *ctx = NULL;
    if (libusb_init(&ctx)) return 1;
    libusb_device **list; ssize_t n = libusb_get_device_list(ctx, &list);
    libusb_device *found = NULL;
    for (ssize_t i = 0; i < n; i++) {
        struct libusb_device_descriptor d;
        libusb_get_device_descriptor(list[i], &d);
        if (d.idVendor == 0x07b4 && d.idProduct == 0x0206) found = list[i];
    }
    if (!found) { printf("not found\n"); return 1; }
    libusb_device_handle *h;
    if (libusb_open(found, &h)) { printf("open fail\n"); return 1; }
    libusb_claim_interface(h, 0);

    unsigned char tx[8], rx[64];
    int rxn = 0, r, sent;

    /* A: send 0x78, drain up to 8 x 64-byte bulk reads */
    printf("== A: 0x78 then drain ==\n");
    tx[0] = 0x78;
    libusb_bulk_transfer(h, 0x02, tx, 1, &sent, 500);
    for (int k = 0; k < 8; k++) {
        r = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 1000);
        if (r == 0 && rxn) {
            printf("page%d[%d]=", k, rxn);
            for (int i = 0; i < rxn; i++) printf("%02x", rx[i]);
            printf("\n");
        } else break;
    }
    for (int k = 0; k < 3; k++) {
        r = libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 500);
        if (r == 0 && rxn) {
            printf("int=");
            for (int i = 0; i < rxn; i++) printf("%02x", rx[i]);
            printf("\n");
        } else break;
    }

    /* B: 0x79 then drain */
    printf("== B: 0x79 then drain ==\n");
    tx[0] = 0x79;
    libusb_bulk_transfer(h, 0x02, tx, 1, &sent, 500);
    for (int k = 0; k < 8; k++) {
        r = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 1000);
        if (r == 0 && rxn) {
            printf("page%d[%d]=", k, rxn);
            for (int i = 0; i < rxn; i++) printf("%02x", rx[i]);
            printf("\n");
        } else break;
    }
    for (int k = 0; k < 3; k++) {
        r = libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 500);
        if (r == 0 && rxn) {
            printf("int=");
            for (int i = 0; i < rxn; i++) printf("%02x", rx[i]);
            printf("\n");
        } else break;
    }

    /* C: neighbors 0x7b..0x7f */
    printf("== C: 0x7b..0x7f ==\n");
    for (int c = 0x7b; c <= 0x7f; c++) {
        tx[0] = c;
        libusb_bulk_transfer(h, 0x02, tx, 1, &sent, 500);
        r = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 800);
        if (r == 0 && rxn) {
            printf("%02x bulk[%d]=", c, rxn);
            for (int i = 0; i < rxn; i++) printf("%02x", rx[i]);
            printf("\n");
        }
        r = libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 300);
        if (r == 0 && rxn) {
            printf("%02x int=", c);
            for (int i = 0; i < rxn; i++) printf("%02x", rx[i]);
            printf("\n");
        }
    }

    libusb_close(h);
    libusb_exit(ctx);
    return 0;
}
