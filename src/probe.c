/* DS-330 USB probe: enumerate, open, claim interface 0, poll endpoints.
 * No libusb dev headers on this box - prototypes declared manually.
 * Build: gcc probe.c -o probe /usr/lib/x86_64-linux-gnu/libusb-1.0.so.0 /lib/x86_64-linux-gnu/libudev.so.1
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>

typedef struct libusb_context libusb_context;
typedef struct libusb_device libusb_device;
typedef struct libusb_device_handle libusb_device_handle;

extern int  libusb_init(libusb_context **ctx);
extern void libusb_exit(libusb_context *ctx);
extern ssize_t libusb_get_device_list(libusb_context *ctx, libusb_device ***list);
extern void libusb_free_device_list(libusb_device **list, int unref);
struct libusb_device_descriptor {
    uint8_t  bLength, bDescriptorType; uint16_t bcdUSB;
    uint8_t  bDeviceClass, bDeviceSubClass, bDeviceProtocol, bMaxPacketSize0;
    uint16_t idVendor, idProduct, bcdDevice;
    uint8_t  iManufacturer, iProduct, iSerialNumber, bNumConfigurations;
};
extern int libusb_get_device_descriptor(libusb_device *dev,
                                        struct libusb_device_descriptor *desc);
extern uint8_t libusb_get_bus_number(libusb_device *dev);
extern uint8_t libusb_get_device_address(libusb_device *dev);
extern uint8_t libusb_get_port_number(libusb_device *dev);
extern int  libusb_open(libusb_device *dev, libusb_device_handle **handle);
extern void libusb_close(libusb_device_handle *handle);
extern int  libusb_kernel_driver_active(libusb_device_handle *h, int iface);
extern int  libusb_detach_kernel_driver(libusb_device_handle *h, int iface);
extern int  libusb_set_configuration(libusb_device_handle *h, int cfg);
extern int  libusb_claim_interface(libusb_device_handle *h, int iface);
extern int  libusb_bulk_transfer(libusb_device_handle *h, unsigned char ep,
                                 unsigned char *data, int len, int *transferred,
                                 unsigned int timeout);
extern int  libusb_interrupt_transfer(libusb_device_handle *h, unsigned char ep,
                                      unsigned char *data, int len, int *tr,
                                      unsigned int timeout);
extern const char *libusb_error_name(int errcode);

static const char *errname(int r) { return libusb_error_name(r); }

int main(void) {
    libusb_context *ctx = NULL;
    int r = libusb_init(&ctx);
    fprintf(stderr, "init=%d\n", r);

    libusb_device **list;
    ssize_t n = libusb_get_device_list(ctx, &list);
    libusb_device *found = NULL;
    for (ssize_t i = 0; i < n; i++) {
        struct libusb_device_descriptor d;
        fprintf(stderr, "checkpoint3 i=%zd\n", i);
        libusb_get_device_descriptor(list[i], &d);
        if (d.idVendor == 0x07b4 && d.idProduct == 0x0206) {
            fprintf(stderr, "DS-330: bus %d addr %d port %d\n",
                   libusb_get_bus_number(list[i]),
                   libusb_get_device_address(list[i]),
                   libusb_get_port_number(list[i]));
            found = list[i];
        }
    }
    if (!found) { printf("not found\n"); return 1; }

    libusb_device_handle *h = NULL;
    r = libusb_open(found, &h);
    printf("open=%d (%s)\n", r, r ? errname(r) : "ok");

    /* kernel_driver_active segfaults in this libusb version - skipped */

    r = libusb_set_configuration(h, 1);
    printf("set_config=%d (%s)\n", r, r ? errname(r) : "ok");
    r = libusb_claim_interface(h, 0);
    printf("claim if0=%d (%s)\n", r, r ? errname(r) : "ok");
    if (r) return 1;

    unsigned char buf[64];
    int rx = 0;

    r = libusb_interrupt_transfer(h, 0x83, buf, 8, &rx, 1500);
    printf("INT 0x83: r=%d(%s) n=%d data=", r, r ? errname(r) : "ok", rx);
    for (int i = 0; i < rx; i++) printf("%02x", buf[i]);
    printf("\n");

    r = libusb_bulk_transfer(h, 0x81, buf, 64, &rx, 1500);
    printf("BULK 0x81: r=%d(%s) n=%d data=", r, r ? errname(r) : "ok", rx);
    for (int i = 0; i < rx; i++) printf("%02x", buf[i]);
    printf("\n");

    libusb_close(h);
    libusb_exit(ctx);
    return 0;
}
