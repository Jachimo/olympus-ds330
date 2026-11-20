/* DS-330 command probe: send candidate handshake frames on EP 0x02,
 * read response on EP 0x81. Batch 1: single bytes 0x00-0xff and a few
 * common 4-byte patterns (from DSX buffer shape: [cmd][0][0][0]).
 */
#include <libusb-1.0/libusb.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>

static void hexprint(const char *label, unsigned char *b, int n) {
    printf("%s[%d]=", label, n);
    for (int i = 0; i < n; i++) printf("%02x", b[i]);
    printf("\n");
}

int main(void) {
    libusb_context *ctx = NULL;
    if (libusb_init(&ctx)) return 1;
    libusb_device **list;
    ssize_t n = libusb_get_device_list(ctx, &list);
    libusb_device *found = NULL;
    for (ssize_t i = 0; i < n; i++) {
        struct libusb_device_descriptor d;
        libusb_get_device_descriptor(list[i], &d);
        if (d.idVendor == 0x07b4 && d.idProduct == 0x0206) found = list[i];
    }
    if (!found) { printf("not found\n"); return 1; }
    libusb_device_handle *h = NULL;
    int r = libusb_open(found, &h);
    if (r) { printf("open=%d\n", r); return 1; }
    r = libusb_claim_interface(h, 0);
    printf("claim=%d\n", r);
    if (r) return 1;

    unsigned char tx[64], rx[64];
    int rxn = 0;

    /* Part 1: single-byte commands */
    printf("== single-byte commands ==\n");
    for (int c = 0x00; c <= 0xff; c++) {
        tx[0] = (unsigned char)c;
        int sent = 0;
        r = libusb_bulk_transfer(h, 0x02, tx, 1, &sent, 500);
        if (r != 0) continue; /* unaccepted; move on */
        r = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 800);
        if (r == 0 && rxn > 0) {
            printf("cmd %02x ->", c);
            hexprint("", rx, rxn);
        }
        /* also check interrupt ep */
        r = libusb_interrupt_transfer(h, 0x83, rx, 8, &rxn, 100);
        if (r == 0 && rxn > 0) {
            printf("cmd %02x int->", c);
            hexprint("", rx, rxn);
        }
    }

    /* Part 2: 4-byte commands [c][0][0][0] */
    printf("== 4-byte commands [c][0][0][0] ==\n");
    for (int c = 0x00; c <= 0xff; c++) {
        tx[0] = (unsigned char)c; tx[1] = tx[2] = tx[3] = 0;
        int sent = 0;
        r = libusb_bulk_transfer(h, 0x02, tx, 4, &sent, 500);
        if (r != 0) continue;
        r = libusb_bulk_transfer(h, 0x81, rx, 64, &rxn, 800);
        if (r == 0 && rxn > 0) {
            printf("cmd4 %02x ->", c);
            hexprint("", rx, rxn);
        }
    }

    printf("scan done\n");
    libusb_close(h);
    libusb_exit(ctx);
    return 0;
}
