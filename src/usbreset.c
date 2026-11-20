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
    if (libusb_open(found, &h)) { printf("open fail\n"); return 1; }
    int r = libusb_reset_device(h);
    printf("reset=%d\n", r);
    return 0;
}
