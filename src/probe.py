#!/usr/bin/env python3
"""DS-330 probe: enumerate device, detach kernel drivers, claim interface 0,
read EP0 descriptors, and try the interrupt EP for status."""
import sys
import usb.core
import usb.util

VID, PID = 0x07B4, 0x0206

dev = usb.core.find(idVendor=VID, idProduct=PID)
if dev is None:
    sys.exit("DS-330 not found")

print(f"Device: {dev.bus:03d}:{dev.dev:03d} {hex(dev.idVendor)}:{hex(dev.idProduct)}")
print(f"Configurations: {dev.bNumConfigurations}")
for cfg in dev:
    print(f"  Config {cfg.bConfigurationValue}: {cfg.bNumInterfaces} interfaces")
    for itf in cfg:
        print(f"  Iface {itf.bInterfaceNumber} alt {itf.bAlternateSetting} "
              f"class {itf.bInterfaceClass:#x}: {itf.bNumEndpoints} ep")
        for ep in itf:
            print(f"    EP {ep.bEndpointAddress:#04x} attrs={ep.bmAttributes:#04x} "
                  f"max={ep.wMaxPacketSize} interval={ep.bInterval}")

# detach anything bound to interface 0 (none expected; ff-class)
try:
    if dev.is_kernel_driver_active(0):
        print("kernel driver active on if0 -> detaching")
        dev.detach_kernel_driver(0)
except Exception as e:
    print("kernel driver check:", e)

dev.set_configuration()
cfg = dev.get_active_configuration()
itf = cfg[(0, 0)]
print("claimed interface 0")

ep_int = usb.util.find_descriptor(itf, custom_match=lambda e: e.bEndpointAddress == 0x83)
ep_in = usb.util.find_descriptor(itf, custom_match=lambda e: e.bEndpointAddress == 0x81)
ep_out = usb.util.find_descriptor(itf, custom_match=lambda e: e.bEndpointAddress == 0x02)
print(f"EPs: in={ep_in} out={ep_out} int={ep_int}")

# 1) Try reading interrupt EP (status/ready?) non-blocking
import usb.core as u
try:
    data = dev.read(0x83, 8, 100)
    print("INT EP 0x83 ->", bytes(data).hex())
except u.USBError as e:
    print("INT EP 0x83 timeout/empty:", e)

# 2) Try reading bulk IN (maybe device queues something at connect)
try:
    data = dev.read(0x81, 64, 100)
    print("BULK IN 0x81 ->", bytes(data).hex())
except u.USBError as e:
    print("BULK IN 0x81 timeout/empty:", e)
