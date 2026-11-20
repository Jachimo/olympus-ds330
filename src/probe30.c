#include <libusb-1.0/libusb.h>
#include <stdio.h>
#include <string.h>
static void show(unsigned char *rx, int rxn) {
    for (int i = 0; i < rxn && i < 40; i++) printf("%02x", rx[i]);
    printf("\n");
}
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
    if (!found) return 1;
    libusb_device_handle *h;
    if (libusb_open(found, &h)) return 1;
    libusb_claim_interface(h, 0);
    unsigned char tx[8], rx[64];
    int rxn=0, r, sent;
    for (int c = 0x30; c <= 0x3f; c++) {
        for (int a = 0; a <= 2; a++) {
            tx[0]=c; tx[1]=a; tx[2]=0; tx[3]=0;
            libusb_bulk_transfer(h, 0x02, tx, 4, &sent, 400);
            r = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 700);
            if (r == 0 && rxn) { printf("%02x a%d [%d]=", c, a, rxn); show(rx, rxn); }
            libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 100);
        }
    }
    return 0;
}
