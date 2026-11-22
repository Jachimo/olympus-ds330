#!/usr/bin/env python3
"""Parse a usbmon pcap (linktype 220, Linux usbmon) and print DS-330 traffic.

Filters to the DS-330's interface-0 endpoints by default:
  bulk OUT 0x02 (commands), bulk IN 0x81 (data), interrupt IN 0x83 (status).

Usage: python3 parse_pcap.py FILE.pcap [--ep 02:81:83] [--maxdata N]
"""
import struct
import sys

# usbmon 64-byte header ( Documentation/USB/usbmon )
# u64 id; u8 type; u8 xfer_type; u8 epnum; u16 busnum; i16 devnum;
# then (after first 16 bytes) more fields; payload length at offset 0x20 (caplen/len)
HDR_LEN = 64


def parse(path, eps, maxdata):
    data = open(path, "rb").read()
    gh = struct.unpack("<IHHiIIIHHIIHH", data[:40])  # pcap global header
    magic = gh[0]
    off = 24
    idx = 0
    while off + 16 <= len(data):
        caplen, origlen = struct.unpack("<II", data[off + 8:off + 16])
        pkt = data[off + 16: off + 16 + caplen]
        off += 16 + caplen
        idx += 1
        if len(pkt) < HDR_LEN:
            continue
        epnum = pkt[4]  # endpoint number incl. direction bit
        xfer_type = pkt[5]
        # offset 0x10: ts sec, 0x14: ts usec, 0x1c: length, 0x20: flags
        length = struct.unpack("<I", pkt[0x1c:0x20])[0]
        status = struct.unpack("<I", pkt[0x20:0x24])[0]
        payload = pkt[HDR_LEN:HDR_LEN + min(length, caplen - HDR_LEN)]
        ep = epnum & 0x7f
        direction = "OUT" if epnum < 0x80 else "IN "
        epname = f"{ep:02x}"
        # xfer types: 0=isoc 1=intr 2=control 3=bulk
        xt = {0: "isoc", 1: "intr", 2: "ctrl", 3: "bulk"}.get(xfer_type, "?")
        if epname in eps:
            show = payload[:maxdata]
            print(f"[{idx:5d}] ep=0x{epnum:02x} {direction} {xt:4s} len={length:5d} "
                  f"st={status:#x} data={show.hex()}")
        elif maxdata < 0:  # -1 = dump everything short
            print(f"[{idx:5d}] ep=0x{epnum:02x} {direction} {xt:4s} len={length:5d} st={status:#x}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    if not args:
        print(__doc__)
        sys.exit(1)
    path = args[0]
    eps = {"02", "81", "83"}
    maxdata = 64
    for a in args[1:]:
        if a.startswith("--ep"):
            eps = set(args[args.index(a) + 1].split(":"))
        if a == "--all":
            maxdata = 32
    parse(path, eps, maxdata)