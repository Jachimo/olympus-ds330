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
    if (!found) return 1;
    libusb_device_handle *h;
    if (libusb_open(found, &h)) return 1;
    libusb_claim_interface(h, 0);
    unsigned char tx[8], rx[64];
    int rxn=0, r, sent;
    for (int a = 0; a < 256; a++) {
        tx[0]=0x33; tx[1]=a; tx[2]=0; tx[3]=0;
        libusb_bulk_transfer(h, 0x02, tx, 4, &sent, 400);
        r = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 700);
        if (r == 0 && rxn) {
            /* print page only if it contains 'JSMY' or non-FF/00 mix */
            int has_target = memmem(rx, rxn, "JSMY", 4) != NULL;
            int allsame = 1;
            for (int i = 1; i < rxn; i++) if (rx[i]!=rx[0]) { allsame=0; break; }
            if (has_target || !allsame) {
                printf("page%3d: ", a);
                for (int i = 0; i < 40; i++) printf("%02x", rx[i]);
                printf(" | ");
                /* ascii */
                for (int i = 0; i < 20; i++) printf("%c", rx[i]>=32&&rx[i]<127?rx[i]:'.');
                printf("\n");
            }
        }
        libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 60);
    }
    return 0;
}
