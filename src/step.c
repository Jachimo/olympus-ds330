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
    libusb_device_handle *h; if (libusb_open(found, &h)) return 1;
    libusb_claim_interface(h, 0);
    unsigned char tx[8], rx[64]; int rxn=0, sent, r;
    tx[0]=0x00;
    r = libusb_bulk_transfer(h, 0x02, tx, 1, &sent, 1000);
    printf("prime bulk: r=%d sent=%d\n", r, sent);
    r = libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 2000);
    printf("prime int: r=%d n=%d data=", r, rxn);
    for (int i = 0; i < rxn; i++) printf("%02x", rx[i]);
    printf("\n");
    tx[0]=0x40; tx[1]=0; tx[2]=0; tx[3]=0;
    r = libusb_bulk_transfer(h, 0x02, tx, 4, &sent, 1000);
    printf("0x40 bulk: r=%d sent=%d\n", r, sent);
    r = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 3000);
    printf("0x40 read: r=%d n=%d data=", r, rxn);
    for (int i = 0; i < rxn; i++) printf("%02x", rx[i]);
    printf("\n");
    return 0;
}
