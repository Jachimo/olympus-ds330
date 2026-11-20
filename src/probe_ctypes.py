#!/usr/bin/env python3
"""DS-330 probe via ctypes/libusb-1.0 directly (no pyusb - its cython binding
stack-smashes with python3.14 + this libusb)."""
import ctypes as C
import sys

lib = C.CDLL("/usr/lib/x86_64-linux-gnu/libusb-1.0.so.0")

lib.libusb_init.argtypes = [C.POINTER(C.c_void_p)]
lib.libusb_init.restype = C.c_int
lib.libusb_get_device_list.argtypes = [C.c_void_p, C.POINTER(C.POINTER(C.c_void_p))]
lib.libusb_get_device_list.restype = C.c_ssize_t
lib.libusb_free_device_list.argtypes = [C.POINTER(C.c_void_p), C.c_int]
lib.libusb_get_device_descriptor.argtypes = [C.c_void_p, C.c_void_p]
lib.libusb_get_device_descriptor.restype = C.c_int
lib.libusb_get_bus_number.argtypes = [C.c_void_p]
lib.libusb_get_bus_number.restype = C.c_uint8
lib.libusb_get_device_address.argtypes = [C.c_void_p]
lib.libusb_get_device_address.restype = C.c_uint8
lib.libusb_get_port_number.argtypes = [C.c_void_p]
lib.libusb_get_port_number.restype = C.c_uint8
lib.libusb_open.argtypes = [C.c_void_p, C.POINTER(C.c_void_p)]
lib.libusb_open.restype = C.c_int
lib.libusb_close.argtypes = [C.c_void_p]
lib.libusb_claim_interface.argtypes = [C.c_void_p, C.c_int]
lib.libusb_claim_interface.restype = C.c_int
lib.libusb_kernel_driver_active.argtypes = [C.c_void_p, C.c_int]
lib.libusb_kernel_driver_active.restype = C.c_int
lib.libusb_detach_kernel_driver.argtypes = [C.c_void_p, C.c_int]
lib.libusb_set_configuration.argtypes = [C.c_void_p, C.c_int]
lib.libusb_set_configuration.restype = C.c_int
lib.libusb_bulk_transfer.argtypes = [C.c_void_p, C.c_uint8, C.c_void_p, C.c_int,
                                     C.POINTER(C.c_int), C.c_uint]
lib.libusb_bulk_transfer.restype = C.c_int
lib.libusb_interrupt_transfer.argtypes = [C.c_void_p, C.c_uint8, C.c_void_p, C.c_int,
                                          C.POINTER(C.c_int), C.c_uint]
lib.libusb_interrupt_transfer.restype = C.c_int
lib.libusb_error_name.argtypes = [C.c_int]
lib.libusb_error_name.restype = C.c_char_p

class Desc(C.Structure):
    _fields_ = [("bLength", C.c_uint8), ("bDescriptorType", C.c_uint8),
                ("bcdUSB", C.c_uint16), ("bDeviceClass", C.c_uint8),
                ("bDeviceSubClass", C.c_uint8), ("bDeviceProtocol", C.c_uint8),
                ("bMaxPacketSize0", C.c_uint8), ("idVendor", C.c_uint16),
                ("idProduct", C.c_uint16), ("bcdDevice", C.c_uint16),
                ("iManufacturer", C.c_uint8), ("iProduct", C.c_uint8),
                ("iSerialNumber", C.c_uint8), ("bNumConfigurations", C.c_uint8)]

def errname(r):
    s = lib.libusb_error_name(r)
    return s.decode() if s else str(r)

ctx = C.c_void_p()
print("libusb_init:", lib.libusb_init(C.byref(ctx)))

devs = C.POINTER(C.c_void_p)()
n = lib.libusb_get_device_list(ctx, C.byref(devs))
found = None
for i in range(n):
    d = devs[i]
    desc = Desc()
    lib.libusb_get_device_descriptor(d, C.byref(desc))
    if desc.idVendor == 0x07B4 and desc.idProduct == 0x0206:
        print(f"DS-330 at bus {lib.libusb_get_bus_number(d)} "
              f"addr {lib.libusb_get_device_address(d)} "
              f"port {lib.libusb_get_port_number(d)}")
        found = d
if not found:
    sys.exit("DS-330 not found")

h = C.c_void_p()
r = lib.libusb_open(found, C.byref(h))
print("open:", r, errname(r) if r else "ok")

ka = lib.libusb_kernel_driver_active(h, 0)
print("kernel driver on if0:", ka)
if ka == 1:
    print("detach:", lib.libusb_detach_kernel_driver(h, 0))

r = lib.libusb_set_configuration(h, 1)
print("set_configuration(1):", r, errname(r) if r else "ok")
r = lib.libusb_claim_interface(h, 0)
print("claim_interface(0):", r, errname(r) if r else "ok")
if r != 0:
    sys.exit(1)

buf = (C.c_ubyte * 64)()
rx = C.c_int(0)

r = lib.libusb_interrupt_transfer(h, 0x83, buf, 8, C.byref(rx), 1000)
print(f"INT 0x83: r={r} ({errname(r) if r else 'ok'}) n={rx.value} "
      f"data={bytes(buf[:max(rx.value,0)]).hex()}")

r = lib.libusb_bulk_transfer(h, 0x81, buf, 64, C.byref(rx), 1000)
print(f"BULK 0x81: r={r} ({errname(r) if r else 'ok'}) n={rx.value} "
      f"data={bytes(buf[:max(rx.value,0)]).hex()}")
