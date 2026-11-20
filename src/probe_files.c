/* Walk the file list: repeated 0x40 (arg1) to test auto-advance;
 * then 0x40 arg with incrementing arg byte (file index selector?);
 * then try 0x46/0x47 with args for file data. */
#include <libusb-1.0/libusb.h>
#include <stdio.h>
#include <string.h>

static libusb_device_handle *open_dev(void) {
    libusb_context *ctx = NULL;
    if (libusb_init(&ctx)) return NULL;
    libusb_device **list; ssize_t n = libusb_get_device_list(ctx, &list);
    libusb_device *found = NULL;
    for (ssize_t i = 0; i < n; i++) {
        struct libusb_device_descriptor d;
        libusb_get_device_descriptor(list[i], &d);
        if (d.idVendor == 0x07b4 && d.idProduct == 0x0206) found = list[i];
    }
    if (!found) return NULL;
    libusb_device_handle *h;
    if (libusb_open(found, &h)) return NULL;
    if (libusb_claim_interface(h, 0)) return NULL;
    return h;
}

static int show(unsigned char *rx, int rxn, int full) {
    int n = full ? rxn : (rxn < 40 ? rxn : 40);
    for (int i = 0; i < n; i++) printf("%02x", rx[i]);
    if (!full && rxn > n) printf("...");
    printf("\n");
    return 0;
}

int main(void) {
    libusb_device_handle *h = open_dev();
    if (!h) { printf("open fail\n"); return 1; }
    unsigned char tx[8], rx[64];
    int rxn = 0, r, sent;

    /* A: repeat 0x40 arg1 five times - does it auto-advance? */
    printf("== A: 0x40 arg1 x5 ==\n");
    for (int k = 0; k < 5; k++) {
        tx[0]=0x40; tx[1]=1; tx[2]=0; tx[3]=0;
        libusb_bulk_transfer(h, 0x02, tx, 4, &sent, 400);
        r = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 800);
        if (r == 0 && rxn) { printf("iter%d: ", k); show(rx, rxn, 0); }
        libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 100);
    }

    /* B: 0x40 with arg byte 0..7 - file index? */
    printf("== B: 0x40 arg0..7 ==\n");
    for (int a = 0; a <= 7; a++) {
        tx[0]=0x40; tx[1]=a; tx[2]=0; tx[3]=0;
        libusb_bulk_transfer(h, 0x02, tx, 4, &sent, 400);
        r = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 800);
        if (r == 0 && rxn) { printf("arg%d: ", a); show(rx, rxn, 0); }
        libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 100);
    }

    /* C: 0x41 with args 0..3 */
    printf("== C: 0x41 arg0..3 ==\n");
    for (int a = 0; a <= 3; a++) {
        tx[0]=0x41; tx[1]=a; tx[2]=0; tx[3]=0;
        libusb_bulk_transfer(h, 0x02, tx, 4, &sent, 400);
        r = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 800);
        if (r == 0 && rxn) { printf("arg%d: ", a); show(rx, rxn, 0); }
        libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 100);
    }

    /* D: 0x46/0x47 with args 0..3 - file data? */
    printf("== D: 0x46,0x47 args ==\n");
    for (int c = 0x46; c <= 0x47; c++) {
        for (int a = 0; a <= 3; a++) {
            tx[0]=c; tx[1]=a; tx[2]=0; tx[3]=0;
            libusb_bulk_transfer(h, 0x02, tx, 4, &sent, 400);
            r = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 800);
            if (r == 0 && rxn) {
                printf("%02x arg%d bulk[%d]=", c, a, rxn);
                show(rx, rxn, 0);
            }
            libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 100);
        }
    }

    libusb_close(h);
    return 0;
}
