/* Probe 4-byte command forms [cmd][a][b][c] over promising ranges.
 * For each cmd byte, try arg byte values 0..3 (arg in second byte).
 * Watch bulk IN for responses. Also test 0x7b with explicit address bytes
 * to see if sector addressing is possible. */
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

static void show(unsigned char *rx, int rxn) {
    for (int i = 0; i < rxn && i < 32; i++) printf("%02x", rx[i]);
    if (rxn > 32) printf("...");
    printf("\n");
}

int main(void) {
    libusb_device_handle *h = open_dev();
    if (!h) { printf("open fail\n"); return 1; }

    unsigned char tx[8], rx[64];
    int rxn = 0, r, sent;

    /* Part A: 4-byte commands over ranges 0x00-0x10, 0x30-0x50, 0x60-0x78,
     * arg1 in {0,1}. Only report when bulk data returns. */
    int ranges[] = {0x00,0x10, 0x30,0x50, 0x60,0x78};
    printf("== 4-byte cmd scan ==\n");
    for (int ri = 0; ri < 3; ri++) {
        for (int c = ranges[ri*2]; c <= ranges[ri*2+1]; c++) {
            for (int arg = 0; arg <= 1; arg++) {
                tx[0]=c; tx[1]=arg; tx[2]=0; tx[3]=0;
                libusb_bulk_transfer(h, 0x02, tx, 4, &sent, 400);
                r = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 600);
                if (r == 0 && rxn) {
                    printf("%02x arg%d bulk[%d]=", c, arg, rxn);
                    show(rx, rxn);
                }
                /* drain int */
                libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 100);
            }
        }
    }

    /* Part B: 0x7b sector read with explicit args: maybe [7b][addr] or
     * [7b][sector_lo] etc. Try single arg variations + 2-byte addresses. */
    printf("== 0x7b addressing ==\n");
    int tries[] = {0,1,2,3,4,5,0x10,0x40,0x80,0xff};
    for (int t = 0; t < 10; t++) {
        tx[0]=0x7b; tx[1]=tries[t]; tx[2]=0; tx[3]=0;
        libusb_bulk_transfer(h, 0x02, tx, 4, &sent, 400);
        r = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 600);
        if (r == 0 && rxn) {
            printf("7b arg%02x bulk[%d]=", tries[t], rxn);
            show(rx, rxn);
        }
        libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 100);
    }
    /* 2-byte sector address: [7b][lo][hi][0] */
    int addrs[] = {0x0001, 0x0002, 0x0100, 0x7c00};
    for (int t = 0; t < 4; t++) {
        tx[0]=0x7b; tx[1]=addrs[t]&0xff; tx[2]=(addrs[t]>>8)&0xff; tx[3]=0;
        libusb_bulk_transfer(h, 0x02, tx, 4, &sent, 400);
        r = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 600);
        if (r == 0 && rxn) {
            printf("7b addr%04x bulk[%d]=", addrs[t], rxn);
            show(rx, rxn);
        }
        libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 100);
    }

    libusb_close(h);
    return 0;
}
