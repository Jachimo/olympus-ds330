#!/usr/bin/env python3
"""Full linear dump of the DS-330 data object.
Proven binding style from probe_ctypes.py (individual assignments, no getattr
loop, no error_name in hot path). Protocol: 1-byte command on EP 0x02, INT
status on 0x83, then bulk data on 0x81."""
import ctypes as C
import sys

lib = C.CDLL("/usr/lib/x86_64-linux-gnu/libusb-1.0.so.0")
lib.libusb_init.argtypes = [C.POINTER(C.c_void_p)]
lib.libusb_init.restype = C.c_int
lib.libusb_get_device_list.argtypes = [C.c_void_p, C.POINTER(C.POINTER(C.c_void_p))]
lib.libusb_get_device_list.restype = C.c_ssize_t
lib.libusb_get_device_descriptor.argtypes = [C.c_void_p, C.c_void_p]
lib.libusb_get_device_descriptor.restype = C.c_int
lib.libusb_get_bus_number.argtypes = [C.c_void_p]
lib.libusb_get_bus_number.restype = C.c_uint8
lib.libusb_get_device_address.argtypes = [C.c_void_p]
lib.libusb_get_device_address.restype = C.c_uint8
lib.libusb_open.argtypes = [C.c_void_p, C.POINTER(C.c_void_p)]
lib.libusb_open.restype = C.c_int
lib.libusb_kernel_driver_active.argtypes = [C.c_void_p, C.c_int]
lib.libusb_kernel_driver_active.restype = C.c_int
lib.libusb_set_configuration.argtypes = [C.c_void_p, C.c_int]
lib.libusb_set_configuration.restype = C.c_int
lib.libusb_claim_interface.argtypes = [C.c_void_p, C.c_int]
lib.libusb_claim_interface.restype = C.c_int
lib.libusb_bulk_transfer.argtypes = [C.c_void_p, C.c_uint8, C.c_void_p, C.c_int,
                                     C.POINTER(C.c_int), C.c_uint]
lib.libusb_bulk_transfer.restype = C.c_int
lib.libusb_interrupt_transfer.argtypes = [C.c_void_p, C.c_uint8, C.c_void_p, C.c_int,
                                          C.POINTER(C.c_int), C.c_uint]
lib.libusb_interrupt_transfer.restype = C.c_int

class Desc(C.Structure):
    _fields_ = [("bLength", C.c_uint8), ("bDescriptorType", C.c_uint8),
                ("bcdUSB", C.c_uint16), ("bDeviceClass", C.c_uint8),
                ("bDeviceSubClass", C.c_uint8), ("bDeviceProtocol", C.c_uint8),
                ("bMaxPacketSize0", C.c_uint8), ("idVendor", C.c_uint16),
                ("idProduct", C.c_uint16), ("bcdDevice", C.c_uint16),
                ("iManufacturer", C.c_uint8), ("iProduct", C.c_uint8),
                ("iSerialNumber", C.c_uint8), ("bNumConfigurations", C.c_uint8)]

def bulk_out(h, data, timeout=3000):
    sent = C.c_int()
    r = lib.libusb_bulk_transfer(h, 0x02, (C.c_ubyte * len(data)).from_buffer_copy(bytearray(data)),
                                 len(data), C.byref(sent), timeout)
    return r, sent.value

def bulk_in(h, size=64, timeout=3000):
    buf = (C.c_ubyte * size)()
    got = C.c_int()
    r = lib.libusb_bulk_transfer(h, 0x81, buf, size, C.byref(got), timeout)
    return r, bytes(buf[:max(got.value, 0)])

def int_in(h, timeout=5000):
    buf = (C.c_ubyte * 8)()
    got = C.c_int()
    r = lib.libusb_interrupt_transfer(h, 0x83, buf, 8, C.byref(got), timeout)
    return r, bytes(buf[:max(got.value, 0)])

def main():
    cmd = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x78
    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 32
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
            print(f"DS-330 bus {lib.libusb_get_bus_number(d)} addr {lib.libusb_get_device_address(d)}")
            found = d
    if not found:
        sys.exit("DS-330 not found")
    h = C.c_void_p()
    lib.libusb_open(found, C.byref(h))
    lib.libusb_free_device_list(devs, 1)
    print("claim:", lib.libusb_claim_interface(h, 0))

    with open("dump.txt", "w") as f:
        for page in range(pages):
            r, _ = bulk_out(h, bytes([cmd]))
            if r != 0:
                print(f"page {page}: OUT error {r}"); break
            ri, st = int_in(h)
            if ri != 0 or not st:
                print(f"page {page}: INT error {ri} st={st.hex()}"); break
            rr, data = bulk_in(h)
            if rr != 0 or not data:
                print(f"page {page}: IN error {rr} st={st.hex()}"); break
            f.write(f"page {page:3d} [{st.hex()}] {data.hex()}\n")
            if page % 8 == 0:
                print(f"page {page}: {data[:16].hex()}")
    print("done")

main()
