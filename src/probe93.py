#!/usr/bin/env python3
"""Probe the 0x93 file-read command discovered in DSXUSB.SYS.

Wire frame (SYS:0x116f7-0x11704): 93 <mode> <count_lo> <count_hi> on EP 0x02,
INT status on 0x83, data stage on EP 0x81. Modes:
  0 -> 0x0144 (324) bytes   2 -> 0x00c9 (201) bytes
  1 -> 0x001c (28)  bytes   3 -> 0x0144 (324) bytes
Timeout 3000 ms for the data stage (SYS 0x116f2).
"""
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
lib.libusb_claim_interface.argtypes = [C.c_void_p, C.c_int]
lib.libusb_claim_interface.restype = C.c_int
lib.libusb_release_interface.argtypes = [C.c_void_p, C.c_int]
lib.libusb_release_interface.restype = C.c_int
lib.libusb_close.argtypes = [C.c_void_p]
lib.libusb_close.restype = None
lib.libusb_exit.argtypes = [C.c_void_p]
lib.libusb_exit.restype = None
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

MODES = {0: 0x0144, 1: 0x001c, 2: 0x00c9, 3: 0x0144}

def open_device():
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
    lib.libusb_free_device_list(devs, 1)
    r = lib.libusb_claim_interface(h, 0)
    if r != 0:
        sys.exit(f"claim failed: {r}")
    return h

def read93(h, mode, outfile=None, maxpages=64):
    count = MODES[mode]
    frame = bytes([0x93, mode, count & 0xff, (count >> 8) & 0xff])
    print(f"== mode {mode}: OUT {frame.hex()}")
    r, sent = bulk_out(h, frame)
    print(f"   OUT r={r} sent={sent}")
    ri, st = int_in(h)
    print(f"   INT r={ri} st={st.hex()}")
    if ri != 0 or not st or st[:4] == b"\xff\xff\xff\xff":
        print("   rejected by device")
        return None
    pages, data = [], b""
    for page in range(maxpages):
        rr, chunk = bulk_in(h)
        if rr != 0 or not chunk:
            print(f"   page {page}: IN r={rr} (stop)")
            break
        pages.append((page, chunk))
        data += chunk
        if len(data) >= count:
            break
    print(f"   read {len(data)} bytes in {len(pages)} pages")
    for p, c in pages[:4]:
        print(f"   p{p}: {c[:24].hex()}")
    if outfile:
        with open(outfile, "ab") as f:
            for p, c in pages:
                f.write(f"page {p:3d} {c.hex()}\n".encode())
    return data

def main():
    h = open_device()
    modes = [int(m) for m in sys.argv[1:]] or [0, 1, 2, 3]
    for m in modes:
        try:
            read93(h, m, outfile="logs/probe93.txt")
        finally:
            pass
    lib.libusb_release_interface(h, 0)
    lib.libusb_close(h)

main()
