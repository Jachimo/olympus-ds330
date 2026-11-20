#!/usr/bin/env python3
"""DS-330 probe using libusb-0.1 via ctypes (crash-free on this box)."""
import ctypes, struct, sys

lib = ctypes.CDLL("/usr/lib/x86_64-linux-gnu/libusb-0.1.so.4")
lib.usb_init()
lib.usb_find_busses()
lib.usb_find_devices()
lib.usb_get_busses.restype = ctypes.c_void_p

# structs (linux libusb-0.1 ABI, 64-bit):
# usb_bus: next*, prev*, dirname[256], devices*, location(4), root_dev* 
# usb_device: next*, prev*, devnum u8, num_children u8, filename[256],
#             bus*, descriptor(embedded 18B), config*
OFF_DESCRIPTOR = 8+8+1+1+256+8  # = 274 -> padded? libusb-0.1 packs filename[255+1]=256

def read_mem(ptr, size):
    buf = (ctypes.c_ubyte*size)()
    ctypes.memmove(buf, ptr, size)
    return bytes(buf)

# Walk device list. usb_bus layout check: dirname at 16.
bus_ptr = lib.usb_get_busses()
lib.usb_get_busses.restype = ctypes.c_void_p
bus_ptr = lib.usb_get_busses()
print("bus list:", hex(bus_ptr or 0))

# We'll scan via usb_get_busses: struct usb_bus { next*, prev*, dirname[256], devices* }
while bus_ptr:
    dirname = read_mem(bus_ptr+16, 256).split(b'\0')[0].decode()
    devptr_off = 16+256
    devptr = int.from_bytes(read_mem(bus_ptr+devptr_off, 8), 'little')
    print(f"bus {dirname}: devices@{hex(devptr)}")
    while devptr:
        # usb_device: next(8) prev(8) devnum(1) num_children(1) filename(256) bus(8) descriptor(18)
        desc = read_mem(devptr+274, 18)
        vid, pid = struct.unpack_from('<HH', desc, 8)
        print(f"  dev at {hex(devptr)}: vid={vid:04x} pid={pid:04x}")
        if vid == 0x07b4 and pid == 0x0206:
            print("  ^ FOUND DS-330")
        devptr = int.from_bytes(read_mem(devptr, 8), 'little')
    bus_ptr = int.from_bytes(read_mem(bus_ptr, 8), 'little')
