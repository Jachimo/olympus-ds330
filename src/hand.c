#include <libusb-1.0/libusb.h>
#include <stdio.h>
#include <string.h>
int main(void) {
    libusb_context *ctx; libusb_init(&ctx);
    libusb_device **list; ssize_t n = libusb_get_device_list(ctx, &list);
    libusb_device *found = NULL;
    for (ssize_t i = 0; i < n; i++) {
        struct libusb_device_descriptor d;
        libusb_get_device_descriptor(list[i], &d);
        if (d.idVendor == 0x07b4 && d.idProduct == 0x0206) found = list[i];
    }
    if (!found) { printf("not found\n"); return 1; }
    libusb_device_handle *h; if (libusb_open(found, &h)) { printf("open fail\n"); return 1; }
    libusb_claim_interface(h, 0);
    unsigned char tx[8], rx[64]; int rxn=0, sent, r;
    /* candidate handshake: send byte c, read int ep; then 0x40 probe */
    for (int c = 0; c <= 0x0f; c++) {
        tx[0]=c;
        libusb_bulk_transfer(h, 0x02, tx, 1, &sent, 300);
        libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 300);
        /* now try 0x40 file-info */
        tx[0]=0x40; tx[1]=1; tx[2]=0; tx[3]=0;
        libusb_bulk_transfer(h, 0x02, tx, 4, &sent, 300);
        r = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 700);
        if (r == 0 && rxn) {
            printf("init %02x -> 0x40 WORKS: ", c);
            for (int i = 0; i < 24; i++) printf("%02x", rx[i]);
            printf("\n");
        }
        libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 100);
    }
    printf("handshake scan done\n");
    return 0;
}
