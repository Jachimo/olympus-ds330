#!/usr/bin/env python3
"""Extract a valid DSS file from the raw USB bulk-in stream captured from a
Olympus DS-330 (via the DSXUSB protocol or usbmon capture).

Layout of the raw stream (verified byte-for-byte against the player's own
output, JSMYTHE001.dss):
  stream[0:393]        preamble (device file table), discarded
  stream[393:1417]     dss[0:1024]        (1024 bytes)
  stream[1417:4162]    device info blob (2745 bytes), discarded
  stream[4162:4674]    dss[1024:1536]     (512 bytes)
  then repeating:      64-byte frame (discarded) + 512 bytes of dss
  stream tail          folder-name table (DICTATE/LECTURE/TO DO/RANDOM), discarded

The single-byte fixup: dss[792] is 0xfe in the player output where the stream
carries 0xff (a flag byte the player sets itself); not needed for playback.
"""
import sys

def extract(stream: bytes) -> bytes:
    out = bytearray()
    out += stream[393:1417]
    out += stream[4162:4674]
    base = 4738
    while base + 512 <= len(stream):
        out += stream[base:base + 512]
        base += 576
    out = bytes(out)
    # player sets this flag byte itself (stream carries 0xff)
    if len(out) > 792:
        out = out[:792] + bytes([0xFE]) + out[793:]
    return out

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: extract_dss.py raw_stream.bin out.dss")
        sys.exit(1)
    data = extract(open(sys.argv[1], "rb").read())
    open(sys.argv[2], "wb").write(data)
    print(f"wrote {len(data)} bytes to {sys.argv[2]}")
