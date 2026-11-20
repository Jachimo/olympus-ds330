/* Full linear dump: prime with 0x00, then read N pages via 0x40.
 * Writes pages to stdout as index + hex + ascii. */
#include <libusb-1.0/libusb.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
    int npages = argc > 1 ? atoi(argv[1]) : 256;
    libusb_context *ctx; libusb_init(&ctx);
    libusb_device **list; ssize_t n = libusb_get_device_list(ctx, &list);
    libusb_device *found = NULL;
    for (ssize_t i = 0; i < n; i++) {
        struct libusb_device_descriptor d;
        libusb_get_device_descriptor(list[i], &d);
        if (d.idVendor == 0x07b4 && d.idProduct == 0x0206) found = list[i];
    }
    if (!found) { fprintf(stderr, "not found\n"); return 1; }
    libusb_device_handle *h;
    if (libusb_open(found, &h)) { fprintf(stderr, "open fail\n"); return 1; }
    libusb_claim_interface(h, 0);

    unsigned char tx[8], rx[64];
    int rxn = 0, sent;

    /* prime */
    tx[0] = 0x00;
    libusb_bulk_transfer(h, 0x02, tx, 1, &sent, 1000);
    for (int k = 0; k < 2; k++)
        libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 2000);

    for (int p = 0; p < npages; p++) {
        tx[0]=0x40; tx[1]=0; tx[2]=0; tx[3]=0;
        libusb_bulk_transfer(h, 0x02, tx, 4, &sent, 500);
        int r = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 1200);
        if (r != 0 || rxn == 0) {
            fprintf(stderr, "page %d: stream end (r=%d)\n", p, r);
            break;
        }
        printf("%04d: ", p);
        for (int i = 0; i < 64; i++) printf("%02x", rx[i]);
        printf("  |");
        for (int i = 0; i < 64; i++) printf("%c", (rx[i]>=32&&rx[i]<127)?rx[i]:'.');
        printf("|\n");
        libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 60);
    }
    return 0;
}
