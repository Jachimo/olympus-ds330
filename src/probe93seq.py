#!/usr/bin/env python3
"""Test whether a prerequisite command unlocks the 0x93 file-read frame.

The bare 93 00 44 01 frame is rejected from a cold session. The real
player must perform some init sequence first. This script tries each
known command (and combinations) as a prerequisite, then sends the 93
frame and reports whether the device accepts it.

Usage: python3 probe93seq.py [prereq_list]
  prereq_list: comma-separated hex commands to try as prerequisite, e.g.
  "c0,d1,78,b2" (default: all known commands, one at a time)
"""
import sys
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
    ("libusb_reset_device", [C.c_void_p], C.c_int),
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


def send_cmd(h, cmd, arg=None, read_pages=17, timeout=3000):
    """Send a 1-2 byte command, drain status, read data pages."""
    frame = bytes([cmd]) if arg is None else bytes([cmd, arg])
    r, sent = bulk_out(h, frame)
    ri, st = int_in(h)
    if ri != 0 or not st or st[:4] == b"\xff\xff\xff\xff":
        return r, sent, st, []
    data = b""
    for _ in range(read_pages):
        rr, chunk = bulk_in(h, timeout=timeout)
        if rr != 0 or not chunk:
            break
        data += chunk
    return r, sent, st, data


def try_93(h, mode=0):
    count = {0: 0x0144, 1: 0x001c, 2: 0x00c9, 3: 0x0144}[mode]
    frame = bytes([0x93, mode, count & 0xff, (count >> 8) & 0xff])
    r, sent = bulk_out(h, frame)
    ri, st = int_in(h)
    accepted = ri == 0 and st and st[:4] != b"\xff\xff\xff\xff"
    data = b""
    if accepted:
        for _ in range(64):
            rr, chunk = bulk_in(h)
            if rr != 0 or not chunk:
                break
            data += chunk
    return accepted, st, data


def main():
    prereqs = sys.argv[1].split(",") if len(sys.argv) > 1 else [
        "c0", "d1", "78", "79", "95", "b2", "b3", "47", "40", "c0:c0",
        "c0:d1", "d1:c0", "78:c0", "b2:b3"]
    h = open_device()
    results = []
    for p in prereqs:
        seq = [int(x, 16) for x in p.split(":")]
        # reset device between attempts so each starts from a clean state
        lib.libusb_reset_device(h)
        import time
        time.sleep(1.5)
        for cmd in seq:
            r, sent, st, data = send_cmd(h, cmd)
            print(f"  prereq {cmd:02x}: st={st.hex() if st else 'none'} data={len(data)}B")
        ok, st93, data93 = try_93(h)
        print(f"[{p}] 93 frame accepted={ok} st={st93.hex() if st93 else 'none'} data={len(data93)}B")
        results.append((p, ok, st93, data93))
        if ok and data93:
            print(f"  *** SUCCESS with prereq {p}: {len(data93)} bytes ***")
            with open("logs/probe93seq_success.bin", "wb") as f:
                f.write(data93)
    lib.libusb_release_interface(h, 0)
    lib.libusb_close(h)
    print("\nSummary:")
    for p, ok, st, d in results:
        print(f"  {p}: accepted={ok} data={len(d)}")


main()
