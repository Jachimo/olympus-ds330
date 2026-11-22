#!/usr/bin/env python3
"""ds330tool — Linux tool for the Olympus DS-330 digital voice recorder.

Replicates the core functions of the Windows DSS Player 2002 / DictWnd
utility over the vendor USB interface (07b4:0206, interface 0):

  info       show device identity, folders, file table, memory
  download   download the .dss recording(s) to local disk
  settime    set the recorder's clock from the computer clock
  reset      reset the device (recovery without replug)

Wire protocol (see docs/DS-330_PROTOCOL.md):
  BULK OUT 0x02    command frames (64-byte padded pages)
  INTERRUPT IN 0x83  8-byte status: 06..01 = accepted/data follows,
                     ff..01 = rejected
  BULK IN 0x81     64-byte data pages, stream cursor auto-advances

Confirmed frame sequences (from usbmon capture of the real player):
  info:      47 01 .. 47 05, 40 01 (17-page file info object)
  download:  47 01 .. 47 05, 40 01, 41 01, 18 01, then 80 00 -> raw
             stream on 0x81 until it ends (timeout)
  settime:   90 + "YYMMDDHHMMSS" (12 ASCII digits)

Usage: ds330tool.py [--verbose] COMMAND [options]
Requires: python3 (system), libusb-1.0.so.0. No other dependencies.
Optional: ffmpeg for `--wav` conversion (DSS-SP codec).
"""
import argparse
import ctypes as C
import datetime
import os
import struct
import subprocess
import sys
import time

VID = 0x07B4
PID = 0x0206
EP_OUT = 0x02
EP_IN = 0x81
EP_INT = 0x83
PAGE = 64

LIBUSB_PATH = "libusb-1.0.so.0"  # plain soname: resolves via ldconfig on any distro/arch

# INT status packet (8 bytes) interpretation, from captured player traffic:
#   06 00 00 00 01 .. = accepted, bulk data stage follows on 0x81
#   ff 01 00 00 01 .. = accepted, no data stage
#   ff ff ff ff 01 .. = rejected
#   00 00 00 00 01 .. = idle/ready (poll response)
# Byte 4 == 01 means accepted; byte 0 == 06 means data follows.
STATUS_REJECT = b"\xff\xff\xff\xff"
STATUS_ACCEPTED = 0x01  # value of status byte 4 for accept
STAGE_DATA = 0x06       # value of status byte 0 meaning bulk data follows


class DS330Error(Exception):
    pass


def load_libusb():
    lib = C.CDLL(LIBUSB_PATH)
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
    return lib


class Desc(C.Structure):
    _fields_ = [("bLength", C.c_uint8), ("bDescriptorType", C.c_uint8),
                ("bcdUSB", C.c_uint16), ("bDeviceClass", C.c_uint8),
                ("bDeviceSubClass", C.c_uint8), ("bDeviceProtocol", C.c_uint8),
                ("bMaxPacketSize0", C.c_uint8), ("idVendor", C.c_uint16),
                ("idProduct", C.c_uint16), ("bcdDevice", C.c_uint16),
                ("iManufacturer", C.c_uint8), ("iProduct", C.c_uint8),
                ("iSerialNumber", C.c_uint8), ("bNumConfigurations", C.c_uint8)]


class DS330:
    """DS-330 vendor interface (interface 0) over ctypes/libusb."""

    def __init__(self, verbose=False, timeout_ms=2000):
        self.verbose = verbose
        self.timeout = timeout_ms
        self.lib = load_libusb()
        self.ctx = C.c_void_p()
        r = self.lib.libusb_init(C.byref(self.ctx))
        if r != 0:
            raise DS330Error(f"libusb_init failed: {r}")
        self.handle = None

    # -- low-level -------------------------------------------------------
    def _log(self, tag, data):
        if self.verbose:
            hexs = data[:32].hex() + ("..." if len(data) > 32 else "")
            print(f"    {tag} {len(data):5d} {hexs}", file=sys.stderr)

    def bulk_out(self, data, timeout=None):
        buf = (C.c_ubyte * len(data)).from_buffer_copy(bytearray(data))
        sent = C.c_int()
        r = self.lib.libusb_bulk_transfer(self.handle, EP_OUT, buf, len(data),
                                         C.byref(sent), timeout or self.timeout)
        self._log("OUT>", bytes(data))
        return r, sent.value

    def bulk_in(self, size=PAGE, timeout=None):
        buf = (C.c_ubyte * size)()
        got = C.c_int()
        r = self.lib.libusb_bulk_transfer(self.handle, EP_IN, buf, size,
                                         C.byref(got), timeout or self.timeout)
        self._log("IN<", bytes(buf[:max(got.value, 0)]))
        return r, bytes(buf[:max(got.value, 0)])

    def int_in(self, timeout=None):
        buf = (C.c_ubyte * 8)()
        got = C.c_int()
        r = self.lib.libusb_interrupt_transfer(self.handle, EP_INT, buf, 8,
                                              C.byref(got), timeout or self.timeout)
        self._log("INT<", bytes(buf[:8]))
        return r, bytes(buf[:max(got.value, 0)])

    # -- session ----------------------------------------------------------
    def open(self):
        devs = C.POINTER(C.c_void_p)()
        n = self.lib.libusb_get_device_list(self.ctx, C.byref(devs))
        if n < 0:
            raise DS330Error(f"get_device_list: {n}")
        try:
            found = None
            for i in range(n):
                d = devs[i]
                desc = Desc()
                self.lib.libusb_get_device_descriptor(d, C.byref(desc))
                if desc.idVendor == VID and desc.idProduct == PID:
                    found = d
                    break
            if not found:
                raise DS330Error("DS-330 not found (USB 07b4:0206). Is it connected?")
            # open BEFORE freeing the list: open takes its own reference, but
            # freeing first leaves this pointer dangling (use-after-free)
            self.handle = C.c_void_p()
            r = self.lib.libusb_open(found, C.byref(self.handle))
            if r != 0:
                raise DS330Error(f"libusb_open: {r}")
        finally:
            self.lib.libusb_free_device_list(devs, 1)
        r = self.lib.libusb_claim_interface(self.handle, 0)
        if r != 0:
            self.close()
            raise DS330Error(f"claim_interface(0): {r} (check udev 0666 rule)")
        return self

    def close(self):
        if self.handle:
            self.lib.libusb_release_interface(self.handle, 0)
            self.lib.libusb_close(self.handle)
            self.handle = None
        if self.ctx:
            self.lib.libusb_exit(self.ctx)
            self.ctx = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    def reset(self):
        """Reset the device and re-open: it re-enumerates (new USB address),
        so the old handle is invalid afterwards."""
        if not self.handle:
            raise DS330Error("not open")
        r = self.lib.libusb_reset_device(self.handle)
        # device re-enumerates on reset; drop the stale handle and re-open
        self.lib.libusb_close(self.handle)
        self.handle = None
        time.sleep(1.5)  # settle time observed needed in live testing
        self.handle = C.c_void_p()
        devs = C.POINTER(C.c_void_p)()
        n = self.lib.libusb_get_device_list(self.ctx, C.byref(devs))
        found = None
        try:
            for i in range(max(n, 0)):
                d = devs[i]
                desc = Desc()
                self.lib.libusb_get_device_descriptor(d, C.byref(desc))
                if desc.idVendor == VID and desc.idProduct == PID:
                    found = d
                    break
            if found:
                self.lib.libusb_open(found, C.byref(self.handle))
        finally:
            self.lib.libusb_free_device_list(devs, 1)
        if self.handle:
            self.lib.libusb_claim_interface(self.handle, 0)
        return r

    # -- protocol ---------------------------------------------------------
    def send(self, frame, expect_data=True, read_pages=64):
        """Send a command frame, drain INT status, read the data pages.

        Returns (accepted, data). The player always writes full 64-byte
        command pages; the device only inspects the leading bytes.
        """
        page = bytes(frame) + b"\x00" * (PAGE - len(frame))
        r, sent = self.bulk_out(page)
        if r != 0 or sent != PAGE:
            return False, b""
        ri, st = self.int_in(timeout=self.timeout)
        if not st or st[:4] == STATUS_REJECT:
            return False, b""
        if len(st) < 5 or st[4] != STATUS_ACCEPTED:
            return False, b""
        if not expect_data:
            return True, b""
        data = b""
        for _ in range(read_pages):
            rr, chunk = self.bulk_in()
            if rr != 0 or not chunk:
                break
            data += chunk
        return True, data

    def read_stream(self, max_bytes=64 * 1024 * 1024, idle_timeout_ms=2000):
        """Read consecutive bulk-in pages until the stream ends (timeout)."""
        data = b""
        last = time.time()
        while len(data) < max_bytes:
            r, chunk = self.bulk_in(timeout=idle_timeout_ms)
            if r == 0 and chunk:
                data += chunk
                last = time.time()
                continue
            if r in (0, -7):  # timeout or empty read -> stream ended
                break
            # transient errors: retry briefly
            if time.time() - last > 30:
                break
        return data

    # -- info commands ------------------------------------------------------
    # Folder-name responses: 4 zero bytes (count/index) + 8-byte ASCII name.
    # 47 01 is a status/counter (GetFileNum-like); 47 02..05 are folders 1..4
    # (DICTATE/LECTURE/TO DO/RANDOM). Arg 06+ is rejected.
    FOLDER_ARGS = range(0x01, 0x06)

    def get_file_info(self):
        """Return the 17-page (1088 B) file info object as bytes.

        Fixed 17 pages (0x40 01): page 0 = current file's header, page 8
        carries a flash-region dword (NOT the file size), pages 9-16 zeros."""
        accepted, data = self.send([0x40, 0x01], read_pages=17)
        return data if accepted else None

    def get_folder_names(self):
        """Folder names via 47 02..05. Includes the 47 01 status query,
        which the device requires before file operations (warmup) --
        its response is NOT a folder-name page, so it is sent but not parsed."""
        names = []
        for arg in self.FOLDER_ARGS:
            accepted, data = self.send([0x47, arg], read_pages=1)
            if not accepted or arg < 0x02 or len(data) < 12:
                continue
            name = data[4:12].decode("ascii", "replace").strip()
            names.append(name)
        return names

    def get_device_info(self):
        accepted, data = self.send([0xB2, 0x00], read_pages=1)
        return data.rstrip(b"\x00").decode("ascii", "replace") if accepted else None

    def get_label(self):
        accepted, data = self.send([0x95, 0x00], read_pages=1)
        return data.rstrip(b"\x00").decode("ascii", "replace") if accepted else None

    def get_memory(self):
        accepted, data = self.send([0x79, 0x00], read_pages=1)
        if not accepted or len(data) < 8:
            return None
        a, b = struct.unpack("<II", data[:8])
        return a if a == b else (a, b)

    # -- download ---------------------------------------------------------
    def download_raw(self, progress=None, file_index=1):
        """Perform the confirmed player download sequence.

        Returns (file_info_bytes, raw_stream_bytes).
        Raises DS330Error on protocol rejection.

        Sequence (mirrors the captured DictWnd traffic exactly):
        f0 00 (init), b2 00 (confirm), 47 01..47 05 (folder scan), 40 01
        (info), 41 01, 18 01 01 (open file #1), 80 00 (data phase).
        The device rejects 18 01 01 without the preceding init/warmup,
        and rejects 18 01 00 (no file selector) outright.
        """
        # init handshake (player does this on connect)
        self.send([0xF0, 0x00], read_pages=1)
        self.send([0xB2, 0x00], read_pages=1)
        # warmup: folder queries (player does these before every download)
        self.get_folder_names()
        # file table
        info = self.get_file_info()
        if info is None:
            raise DS330Error("device rejected file-info query (0x40 01)")
        # 41 01 (player always sends it; no data stage)
        self.send([0x41, 0x01], expect_data=False)
        # open the raw file stream for file #1. Frame is 18 01 <index>:
        # 0x18 = OpenFile command, 0x01 sub-arg, third byte = file selector
        # (01 = first file in the current folder). Two-byte 18 01 is rejected.
        accepted, _ = self.send([0x18, 0x01, file_index], read_pages=1)
        if not accepted:
            raise DS330Error(f"device rejected 18 01 {file_index:02x} (open stream)")
        # data phase: 80 00 = read stream start; then bulk-in pages flow
        # until the device stops sending (read timeout)
        accepted, _ = self.send([0x80, 0x00], expect_data=False)
        if not accepted:
            raise DS330Error("device rejected 80 00 (data phase)")
        stream = b""
        t0 = time.time()
        while True:
            r, chunk = self.bulk_in(timeout=2000)
            if r != 0 or not chunk:
                break
            stream += chunk
            if progress and len(stream) % 65536 < PAGE:
                progress(len(stream), time.time() - t0)
        return info, stream

    # -- clock ------------------------------------------------------------
    def set_time(self, when=None):
        """Set the recorder clock. `when`: datetime (default: now).

        Wire frame: 0x90 followed by 12 ASCII digits YYMMDDHHMMSS
        (2-digit year, no separators), e.g. captured player frame
        `90 32 36 31 31 32 32 30 32 31 32 31 37` = `90` + "261122021217"
        = 2026-11-22 02:12:17.
        """
        t = when or datetime.datetime.now()
        digits = t.strftime("%y%m%d%H%M%S")
        frame = bytes([0x90]) + digits.encode("ascii")
        accepted, _ = self.send(frame, expect_data=False)
        if not accepted:
            raise DS330Error(f"device rejected time frame: {frame.hex()}")
        return t


# -- raw stream -> DSS extraction (verified byte-for-byte vs the player) --

def extract_dss(stream: bytes) -> bytes:
    """Extract the .dss file content from the raw 80-00 data-phase stream.

    The data-phase stream (what the device sends after the `80 00`
    command) interleaves the DSS file with device bookkeeping frames.
    Layout (verified byte-for-byte against the player's own output
    for the JSMYTHE001 recording):

      stream[0:2]      2-byte preamble -- discard
      stream[2:514]    dss[0:512]                 (first block, no leading frame)
      then repeating, period 576 = 512 + 64:
          64-byte bookkeeping frame -- discard
          512 bytes of dss
      i.e. next dss chunks at 578, 1154, 1720, ...
      stream tail       folder-name table -- discard

    The 576 period is a device flash-page artifact: 512 data bytes per
    64-byte frame chunk. The stream ends when the bulk read times out,
    so the last chunk may be short -- shorter than 512-byte tails are
    dropped by the `base + 512 <= len(stream)` guard.

    Fixup: dss[792] = 0xFE. Offset 792 (0x318) is a DSS-header flag byte
    the player rewrites to 0xFE on save; the stream carries 0xFF there.
    """
    if len(stream) < 2 + 512 + 64:  # preamble + first chunk + one frame
        raise DS330Error(f"raw stream too short ({len(stream)} bytes) -- incomplete download")
    out = bytearray()
    out += stream[2:2 + 512]          # dss[0:512]
    base = 514 + 64                    # 514 = 2 + 512; skip the first 64-byte frame
    while base + 512 <= len(stream):
        out += stream[base:base + 512]
        base += 576                    # 64-byte frame + 512-byte dss
    out = bytes(out)
    if len(out) > 792:
        out = out[:792] + bytes([0xFE]) + out[793:]
    return out


def parse_file_info(info: bytes):
    """Parse the 17-page (1088 B) file info object -> dict (best effort).

    Offsets (bytes within the concatenated object, verified against the
    captured player stream for the JSMYTHE001 recording):
      [0x00:0x08]  file name, 8 ASCII chars
      [0x09]       0x02 = DSS file-format version byte (part of the
                   `02 'dss'` magic from the file header)
      [0x0A:0x0D]  'dss' literal
      [0x15:0x1D]  author label, 8 ASCII chars (matches 0x95 response)
      [0x30:0x44]  date digits, ASCII (Olympus packed encoding, unexplained)
      [0x44:0x51]  date digits continuation (spans into page 1)
      page 8 (object offset 8*64), byte +0x09:
                   LE dword 0x00152790 -- a flash-region/metadata size,
                   NOT the file size (actual DSS is 2,397,696 bytes)
    """
    if not info or len(info) < 1088:
        return {}
    name = info[0:8].decode("ascii", "replace").strip()
    magic = info[10:13]
    label = info[21:29].decode("ascii", "replace").strip()
    date_digits = (info[48:64] + info[64:77]).decode("ascii", "replace")
    size = struct.unpack("<I", info[8 * 64 + 9:8 * 64 + 13])[0]
    return {"name": name or None, "format": magic.decode("ascii", "replace"),
            "label": label or None, "date_digits": date_digits,
            "flash_region": size}


# -- CLI -------------------------------------------------------------------

def ffmpeg_convert(dss_path, wav_path):
    if subprocess.call(["ffmpeg", "-y", "-loglevel", "error", "-i",
                       dss_path, wav_path]) != 0:
        print("warning: ffmpeg conversion failed", file=sys.stderr)


def cmd_info(dev, args):
    print(f"device : {dev.get_device_info()}")
    print(f"label  : {dev.get_label()}")
    folders = dev.get_folder_names()
    print(f"folders: {', '.join(folders) if folders else '?'}")
    mem = dev.get_memory()
    if mem is not None:
        print(f"memory : {mem:,} (dwords equal -> total size)" if isinstance(mem, int)
              else f"memory : {mem}")
    info = dev.get_file_info()
    if info:
        fi = parse_file_info(info)
        print(f"file   : {fi.get('name')}  ({fi.get('format')})  "
              f"label={fi.get('label')}  flash_region={fi.get('flash_region')}")
        print(f"dates  : {fi.get('date_digits')!r}")


def cmd_download(dev, args):
    def progress(total, dt):
        print(f"  {total:8d} bytes ({dt:5.1f}s)", file=sys.stderr)
    print("downloading raw stream ...", file=sys.stderr)
    info, stream = dev.download_raw(progress=progress if args.verbose else None)
    print(f"raw stream: {len(stream)} bytes", file=sys.stderr)
    dss = extract_dss(stream)
    name = (parse_file_info(info).get("name") or "recording")
    out = os.path.expanduser(args.out or f"{name.lower()}.dss")
    with open(out, "wb") as f:
        f.write(dss)
    print(f"wrote {len(dss)} bytes -> {out}")
    if args.raw:
        with open(os.path.expanduser(args.raw), "wb") as f:
            f.write(stream)
        print(f"raw stream saved -> {args.raw}")
    if args.wav:
        wav = args.wav if args.wav is not True else os.path.splitext(out)[0] + ".wav"
        ffmpeg_convert(out, wav)
        print(f"converted -> {wav}")


def cmd_reset(dev, args):
    r = dev.reset()
    print("device reset" if r == 0 else f"reset returned {r}")


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Olympus DS-330 recorder tool (download .dss, set clock)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="hexdump all USB traffic to stderr")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="show device identity, folders, file table")

    d = sub.add_parser("download", help="download the .dss recording(s)")
    d.add_argument("--out", metavar="FILE", help="output .dss path (default: <name>.dss)")
    d.add_argument("--raw", metavar="FILE", help="also save the raw stream")
    d.add_argument("--wav", nargs="?", const=True, metavar="FILE",
                   help="convert to .wav via ffmpeg")

    s = sub.add_parser("settime", help="set recorder clock from the computer clock")
    s.add_argument("--time", metavar="YYYYMMDDHHMMSS",
                   help="specific time instead of now (local time)")

    sub.add_parser("reset", help="reset the device (recovery without replug)")

    args = p.parse_args(argv)

    if args.command == "reset":
        dev = DS330(verbose=args.verbose)
        dev.open()
        try:
            cmd_reset(dev, args)
        finally:
            dev.close()
        return 0

    when = None
    if args.command == "settime" and args.time:
        when = datetime.datetime.strptime(args.time, "%Y%m%d%H%M%S")

    with DS330(verbose=args.verbose) as dev:
        try:
            if args.command == "info":
                cmd_info(dev, args)
            elif args.command == "download":
                cmd_download(dev, args)
            elif args.command == "settime":
                dev.set_time(when)
                print(f"recorder clock set to {(when or datetime.datetime.now()).strftime('%Y-%m-%d %H:%M:%S')}")
        except DS330Error as e:
            # the device sometimes rejects valid frames out of a stale
            # session state; one reset+retry fixes it (observed live)
            print(f"error: {e}", file=sys.stderr)
            print("hint: device state may be stale -- "
                  "`ds330tool.py reset` then retry", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())