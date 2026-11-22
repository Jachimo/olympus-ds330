#!/usr/bin/env python3
"""Full download of the .dss recording from the DS-330.

Sequence (confirmed by probe93seq.py):
  1. Send 0xc0 handshake (unlocks file-read session)
  2. Send 93 frame: 93 <mode> <count_lo> <count_hi>
  3. Read 64-byte pages on bulk IN until timeout

Usage: python3 probe93full.py [outfile]
"""
import sys
import time
sys.path.insert(0, "/usr/lib/x86_64-linux-gnu")
import ctypes as C

lib = C.CDLL("/usr/lib/x86_64-linux-gnu/libusb-1.0.so.0")
for fn, argt, rest in [
    ("libusb_init", [C.POINTER(C.c_void_p)], C.c_int),
    ("libusb_get_device_list", [C.c_void_p, C.POINTER(C.POINTER(C.c_void_p))], C.c_ssize_t),
    ("libusb_get_device_descriptor", [C.c_void_p, C.c_void_p], C.c_int),
    ("libusb_open", [C.c_void_p, C.POINTER(C.c_void_p)], C.c_int),
    ("libusb_free_device_list", [C.POINTER(C.c_void_p), C.c_int], None),
    ("libusb_claim_interface", [C.c_void_p, C.c_int], C.c_int),
    ("libusb_release_interface", [C.c_void_p, C.c_int], C.c_int),
    ("libusb_close", [C.c_void_p], None),
    ("libusb_exit", [C.c_void_p], None),
    ("libusb_bulk_transfer", [C.c_void_p, C.c_uint8, C.c_void_p, C.c_int,
                              C.POINTER(C.c_int), C.c_uint], C.c_int),
    ("libusb_interrupt_transfer", [C.c_void_p, C.c_uint8, C.c_void_p, C.c_int,
                                   C.POINTER(C.c_int), C.c_uint], C.c_int),
]:
    getattr(lib, fn).argtypes = argt
    getattr(lib, fn).restype = rest


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
    lib.libusb_free_device_list(devs, 1)
    if not found:
        sys.exit("DS-330 not found")
    h = C.c_void_p()
    lib.libusb_open(found, C.byref(h))
    r = lib.libusb_claim_interface(h, 0)
    if r != 0:
        sys.exit(f"claim failed: {r}")
    return h


def main():
    outfile = sys.argv[1] if len(sys.argv) > 1 else "logs/jsmythe001.dss"
    mode = 0
    count = 0x0144
    frame = bytes([0x93, mode, count & 0xff, (count >> 8) & 0xff])
    h = open_device()

    # Step 1: handshake
    r, sent = bulk_out(h, bytes([0xc0]))
    ri, st = int_in(h)
    print(f"handshake: OUT r={r} sent={sent} INT r={ri} st={st.hex() if st else 'none'}")
    data = b""
    for _ in range(64):
        rr, chunk = bulk_in(h)
        if rr != 0 or not chunk:
            break
        data += chunk
    print(f"handshake data: {len(data)} bytes")

    # Step 2: 93 frame
    r, sent = bulk_out(h, frame)
    ri, st = int_in(h)
    accepted = ri == 0 and st and st[:4] != b"\xff\xff\xff\xff"
    print(f"93 frame: OUT r={r} sent={sent} st={st.hex() if st else 'none'} accepted={accepted}")
    if not accepted:
        sys.exit("93 rejected")

    # Step 3: read until timeout
    total = 0
    start = time.time()
    with open(outfile, "wb") as f:
        while True:
            rr, chunk = bulk_in(h, timeout=2000)
            if rr != 0 or not chunk:
                print(f"IN r={rr} after {total} bytes ({time.time()-start:.1f}s)")
                break
            f.write(chunk)
            total += len(chunk)
            if total % 65536 == 0:
                print(f"  {total} bytes ({time.time()-start:.1f}s)")
    print(f"TOTAL: {total} bytes -> {outfile}")

    lib.libusb_release_interface(h, 0)
    lib.libusb_close(h)


main()
