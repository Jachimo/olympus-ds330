#include <libusb-1.0/libusb.h>
#include <stdio.h>
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
    libusb_device_handle *h;
    int r = libusb_open(found, &h);
    if (r) { printf("open=%d\n", r); return 1; }
    libusb_claim_interface(h, 0);
    unsigned char tx[8]={0x40,0,0,0}, rx[64]; int rxn=0, sent;
    libusb_bulk_transfer(h, 0x02, tx, 4, &sent, 500);
    int r2 = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 2000);
    printf("0x40 probe: r=%d n=%d\n", r2, rxn);
    for (int i = 0; i < rxn && i < 24; i++) printf("%02x", rx[i]);
    printf("\n");
    return 0;
}
