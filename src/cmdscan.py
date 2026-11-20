#!/usr/bin/env python3
"""Systematic scan of the 2-byte command space (cmd + 0x01) on EP 0x02,
resetting the device between commands. Logs to cmdscan.txt."""
import ctypes as C, time, sys

lib = C.CDLL("/usr/lib/x86_64-linux-gnu/libusb-1.0.so.0")
lib.libusb_init.argtypes = [C.POINTER(C.c_void_p)]
lib.libusb_init.restype = C.c_int
lib.libusb_get_device_list.argtypes = [C.c_void_p, C.POINTER(C.POINTER(C.c_void_p))]
lib.libusb_get_device_list.restype = C.c_ssize_t
lib.libusb_get_device_descriptor.argtypes = [C.c_void_p, C.c_void_p]
lib.libusb_open.argtypes = [C.c_void_p, C.POINTER(C.c_void_p)]
lib.libusb_open.restype = C.c_int
lib.libusb_claim_interface.argtypes = [C.c_void_p, C.c_int]
lib.libusb_claim_interface.restype = C.c_int
lib.libusb_reset_device.argtypes = [C.c_void_p]
lib.libusb_reset_device.restype = C.c_int
lib.libusb_close.argtypes = [C.c_void_p]
lib.libusb_exit.argtypes = [C.c_void_p]
lib.libusb_bulk_transfer.argtypes = [C.c_void_p, C.c_uint8, C.c_void_p, C.c_int,
                                     C.POINTER(C.c_int), C.c_uint]
lib.libusb_bulk_transfer.restype = C.c_int

class Desc(C.Structure):
    _fields_ = [("bLength", C.c_uint8), ("bDescriptorType", C.c_uint8),
                ("bcdUSB", C.c_uint16), ("bDeviceClass", C.c_uint8),
                ("bDeviceSubClass", C.c_uint8), ("bDeviceProtocol", C.c_uint8),
                ("bMaxPacketSize0", C.c_uint8), ("idVendor", C.c_uint16),
                ("idProduct", C.c_uint16), ("bcdDevice", C.c_uint16),
                ("iManufacturer", C.c_uint8), ("iProduct", C.c_uint8),
                ("iSerialNumber", C.c_uint8), ("bNumConfigurations", C.c_uint8)]

def fresh_session():
    ctx = C.c_void_p()
    lib.libusb_init(C.byref(ctx))
    devs = C.POINTER(C.c_void_p)()
    n = lib.libusb_get_device_list(ctx, C.byref(devs))
    found = None
    for i in range(n):
        d = devs[i]
        desc = Desc()
        lib.libusb_get_device_descriptor(d, C.byref(desc))
        if desc.idVendor == 0x07B4 and desc.idProduct == 0x0206:
            found = d
    if not found:
        sys.exit("DS-330 not found")
    h = C.c_void_p()
    lib.libusb_open(found, C.byref(h))
    lib.libusb_claim_interface(h, 0)
    return h

def reset(h):
    lib.libusb_reset_device(h)
    time.sleep(0.5)
    lib.libusb_close(h)
    return fresh_session()

def out(h, cmd):
    return lib.libusb_bulk_transfer(h, 0x02, (C.c_ubyte * len(cmd)).from_buffer_copy(bytearray(cmd)),
                                    len(cmd), C.byref(C.c_int()), 2000)

def b_in(h, size=64, t=1500):
    buf = (C.c_ubyte * size)()
    got = C.c_int()
    r = lib.libusb_bulk_transfer(h, 0x81, buf, size, C.byref(got), t)
    return r, bytes(buf[:max(got.value, 0)])

with open("cmdscan.txt", "w") as f:
    h = fresh_session()
    for cmd in range(0x100):
        r = out(h, bytes([cmd, 0x01]))
        rr, data = b_in(h)
        if rr == 0 and data:
            print(f"{cmd:02x}: out={r} in={rr} data={data[:32].hex()}")
            f.write(f"{cmd:02x} {data.hex()}\n")
        h = reset(h)
        if cmd % 32 == 0:
            print(f"... {cmd:#04x} done", flush=True)
    print("scan complete")
