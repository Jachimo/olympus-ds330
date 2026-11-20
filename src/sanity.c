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
    unsigned char tx[8], rx[64]; int rxn=0, sent;
    for (int a = 0; a < 6; a++) {
        tx[0]=0x33; tx[1]=a; tx[2]=0; tx[3]=0;
        libusb_bulk_transfer(h, 0x02, tx, 4, &sent, 500);
        int r = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 800);
        printf("33 a%d r=%d n=%d: ", a, r, rxn);
        for (int i = 0; i < rxn && i < 24; i++) printf("%02x", rx[i]);
        printf("\n");
        libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 100);
    }
    return 0;
}
