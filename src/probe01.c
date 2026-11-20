/* DS-330 probe using legacy libusb-0.1 API (stable, no hotplug threads).
 * Build: gcc probe01.c -o probe01 /usr/lib/x86_64-linux-gnu/libusb-0.1.so.4
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>

typedef struct usb_dev_handle usb_dev_handle;
struct usb_device;
typedef struct usb_bus { struct usb_bus *next; char dirname[1024+1]; struct usb_device *devices; } usb_bus;
typedef struct usb_device { struct usb_device *next,*prev; unsigned char devnum; unsigned char num_children; char filename[255]; } usb_device;
struct usb_descriptor_header { unsigned char bLength, bDescriptorType; };
struct usb_config_descriptor { unsigned char bLength,bDescriptorType; unsigned short wTotalLength; unsigned char bNumInterfaces,bConfigurationValue,iConfiguration; unsigned char bmAttributes,bMaxPower; };
extern void usb_init(void);
extern int usb_find_busses(void);
extern int usb_find_devices(void);
extern usb_bus *usb_get_busses(void);
extern usb_dev_handle *usb_open(usb_device *dev);
extern int usb_close(usb_dev_handle *h);
extern int usb_set_configuration(usb_dev_handle *h, int cfg);
extern int usb_claim_interface(usb_dev_handle *h, int iface);
extern int usb_bulk_read(usb_dev_handle *h, unsigned int ep, char *bytes, int size, int timeout);
extern int usb_bulk_write(usb_dev_handle *h, unsigned int ep, char *bytes, int size, int timeout);
extern int usb_interrupt_read(usb_dev_handle *h, unsigned int ep, char *bytes, int size, int timeout);

/* device descriptor we care about (offset 8=idVendor, 10=idProduct) */
struct devdesc { unsigned char bl, dt; unsigned short bcdUSB; unsigned char cls, sub, proto, mps; unsigned short vid, pid; };

int main(void) {
    usb_init();
    usb_find_busses();
    int n = usb_find_devices();
    printf("find_devices=%d\n", n);

    usb_bus *bus = usb_get_busses();
    usb_device *found = NULL;
    for (; bus; bus = bus->next) {
        for (usb_device *d = bus->devices; d; d = d->next) {
            /* descriptor is prefixed at the struct in 0.1 API: d->descriptor area
               begins right after next/prev/devnum/children/filename; easiest is
               to parse raw: vid at offset 8 of the device descriptor. The 0.1
               struct embeds 'descriptor' as first field of usb_device? In the
               0.1 ABI, usb_device begins with next,prev,devnum,children,
               filename[256],bus,... then descriptor struct. We avoid struct
               guessing: scan the known descriptor memory layout via offset table
               instead. Simpler: match vid/pid via /proc/bus/usb-less trick is
               gone; use libusb0's own struct layout header (known ABI):
               struct usb_device { next, prev, devnum, num_children,
               filename[255], bus*, descriptor, config* } -> descriptor at
               offset 8+8+1+1+255+8 = 281? fragile.
            */
            (void)d;
        }
    }
    /* Practical approach: rely on linux device file presence:
       read /proc? Not needed - we can use sysfs to find the bus/device path,
       then match by scanning descriptors via usb_open on each candidate.
       Instead: parse descriptor from /sys kernel (busnum/devnum file) */
    (void)found;
    return 0;
}
