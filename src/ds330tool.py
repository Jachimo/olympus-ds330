#!/usr/bin/env python3
"""ds330tool — Linux tool for the Olympus DS-330 digital voice recorder.

Talks to the recorder over its vendor USB interface (07b4:0206,
interface 0) and replicates the core functions of the Windows-only
DSS Player 2002 / DictWnd software:

  info       show device identity, folders, file table, dates
  download   download a recording as .dss (byte-identical to the
             Windows player's output), optionally converted to .wav
  settime    set the recorder's clock from the computer clock
  reset      reset the device (recovery without replugging)

The wire protocol was reverse-engineered from USB captures of the
original player; the reference is docs/DS-330_PROTOCOL.md. This module
mirrors that document's structure: a thin typed transport (class Usb),
a declarative frame/sequence model (the dataclasses below), and one
generic executor (DS330.run_sequence).

Requirements: python3 (3.8+, stdlib only) and system libusb-1.0 loaded
via ctypes. Optional: ffmpeg for `--wav` conversion.

License: GPL-3.0 — see LICENSE.
"""
import argparse
import ctypes as C
import datetime
import os
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

VID = 0x07B4
PID = 0x0206
INTERFACE = 0
EP_OUT = 0x02
EP_IN = 0x81
EP_INT = 0x83
PAGE = 64

LIBUSB_PATH = "libusb-1.0.so.0"  # soname; resolves via ldconfig everywhere

LIBUSB_TIMEOUT = -7
LIBUSB_BUSY = -6


class DS330Error(Exception):
    """Base error for this tool."""


class UsbError(DS330Error):
    """USB-level failure (transfer, enumeration, permissions)."""


class ProtocolRejected(DS330Error):
    """The device actively rejected a command frame."""


# ---------------------------------------------------------------------------
# Transport: thin, typed ctypes wrapper over system libusb-1.0
# ---------------------------------------------------------------------------

# USB device descriptor: 18 bytes, packed. Parsed via struct.unpack
# (a ctypes Structure with _pack_ would trigger CPython's packed-layout
# deprecation on python 3.14+).
_DESCRIPTOR_FMT = "<BBHBBBBHHHBBBB"  # sizeof == 18, like usb_device_descriptor


def parse_device_descriptor(buf: bytes):
    """Unpack an 18-byte libusb device descriptor -> dict."""
    if len(buf) < 18:
        raise UsbError(f"short device descriptor ({len(buf)} bytes)")
    keys = ("bLength", "bDescriptorType", "bcdUSB", "bDeviceClass",
            "bDeviceSubClass", "bDeviceProtocol", "bMaxPacketSize0",
            "idVendor", "idProduct", "bcdDevice", "iManufacturer",
            "iProduct", "iSerialNumber", "bNumConfigurations")
    return dict(zip(keys, struct.unpack(_DESCRIPTOR_FMT, buf[:18])))


def _libudev_paths():
    """Absolute paths to the system libudev, if present. libusb-1.0
    depends on libudev.so.1; non-system pythons (e.g. Linuxbrew builds,
    which link a private glibc) cannot resolve that dependency through
    their own library search path, so we pre-load it by absolute path
    with RTLD_GLOBAL first (established live: this makes brew python
    load the system libusb cleanly)."""
    import ctypes.util
    import glob
    paths = []
    found = ctypes.util.find_library("udev")
    if found and os.path.isabs(found):
        paths.append(found)
    paths += sorted(glob.glob("/usr/lib/*/libudev.so.1")
                    + glob.glob("/lib/*/libudev.so.1")
                    + glob.glob("/usr/lib/libudev.so.1"))
    return paths


def load_libusb():
    """Open the system libusb. Tries the plain soname first (resolves
    via ldconfig on any distro), then libudev-preloading fallbacks for
    non-system pythons. Raises UsbError with an actionable message if
    nothing works."""
    candidates = [LIBUSB_PATH, "libusb-1.0.so"]
    attempts = []
    for name in candidates:
        try:
            return C.CDLL(name)
        except OSError as e:
            attempts.append(f"{name}: {e}")
    for udev in _libudev_paths():
        try:
            C.CDLL(udev, mode=C.RTLD_GLOBAL)
        except OSError as e:
            attempts.append(f"preload {udev}: {e}")
            continue
        # after preloading libudev, load libusb itself by absolute path:
        # non-system pythons also cannot resolve the bare soname
        import glob
        for lib in sorted(glob.glob("/usr/lib/*/libusb-1.0.so.0")
                          + glob.glob("/lib/*/libusb-1.0.so.0")):
            try:
                return C.CDLL(lib)
            except OSError as e:
                attempts.append(f"via {udev}, {lib}: {e}")
    raise UsbError(
        "cannot load libusb-1.0 (is it installed?). Tried:\n  "
        + "\n  ".join(attempts)
        + f"\nNote: this python is {sys.executable} -- non-system pythons "
          "(e.g. Linuxbrew) need special handling to load the system "
          "libusb; if this persists, try the distro python3.")


class Usb:
    """One libusb device handle for the DS-330's vendor interface.

    All methods raise on failure — no (code, value) tuples and no
    silently-swallowed transfer errors. Timeouts surface as
    TimeoutError so the protocol layer can treat them as end-of-stream.
    """

    _SYMS = [
        ("libusb_init", [C.POINTER(C.c_void_p)], C.c_int),
        ("libusb_get_device_list",
         [C.c_void_p, C.POINTER(C.POINTER(C.c_void_p))], C.c_ssize_t),
        ("libusb_get_device_descriptor", [C.c_void_p, C.c_void_p], C.c_int),
        ("libusb_open", [C.c_void_p, C.POINTER(C.c_void_p)], C.c_int),
        ("libusb_free_device_list", [C.POINTER(C.c_void_p), C.c_int], None),
        ("libusb_claim_interface", [C.c_void_p, C.c_int], C.c_int),
        ("libusb_release_interface", [C.c_void_p, C.c_int], C.c_int),
        ("libusb_close", [C.c_void_p], None),
        ("libusb_exit", [C.c_void_p], None),
        ("libusb_reset_device", [C.c_void_p], C.c_int),
        ("libusb_bulk_transfer",
         [C.c_void_p, C.c_uint8, C.c_void_p, C.c_int,
          C.POINTER(C.c_int), C.c_uint], C.c_int),
        ("libusb_interrupt_transfer",
         [C.c_void_p, C.c_uint8, C.c_void_p, C.c_int,
          C.POINTER(C.c_int), C.c_uint], C.c_int),
    ]

    def __init__(self, timeout_ms=2000):
        self.timeout_ms = timeout_ms
        self._lib = load_libusb()
        for name, argtypes, restype in self._SYMS:
            fn = getattr(self._lib, name)
            fn.argtypes = argtypes
            fn.restype = restype
        self._ctx = C.c_void_p()
        if (r := self._lib.libusb_init(C.byref(self._ctx))) != 0:
            raise UsbError(f"libusb_init failed: {r}")
        self._handle = None

    # -- lifecycle ----------------------------------------------------------

    def open(self):
        """Find the DS-330, open it, claim the vendor interface."""
        devs = C.POINTER(C.c_void_p)()
        n = self._lib.libusb_get_device_list(self._ctx, C.byref(devs))
        if n < 0:
            raise UsbError(f"libusb_get_device_list: {n}")
        try:
            for i in range(n):
                dev = devs[i]
                buf = (C.c_ubyte * 32)()
                if self._lib.libusb_get_device_descriptor(dev, buf) != 0:
                    continue
                desc = parse_device_descriptor(bytes(buf))
                if desc["idVendor"] == VID and desc["idProduct"] == PID:
                    # libusb_open takes its own reference, so open before the
                    # list is freed; freeing first dangles `dev`.
                    handle = C.c_void_p()
                    if (r := self._lib.libusb_open(dev, C.byref(handle))) != 0:
                        raise UsbError(f"libusb_open: {r}")
                    self._handle = handle
                    break
        finally:
            self._lib.libusb_free_device_list(devs, 1)
        if self._handle is None:
            raise UsbError("DS-330 not found (USB %04x:%04x). Is it connected?"
                           % (VID, PID))
        self._claim()

    def _claim(self):
        r = self._lib.libusb_claim_interface(self._handle, INTERFACE)
        if r == LIBUSB_BUSY:
            self._close_handle()
            raise UsbError(f"interface {INTERFACE} is busy "
                           "(claimed by a kernel driver?)")
        if r != 0:
            self._close_handle()
            raise UsbError(
                f"claim_interface({INTERFACE}): {r} "
                "(permissions? install udev/99-ds330.rules and replug)")

    def _close_handle(self):
        if self._handle:
            self._lib.libusb_release_interface(self._handle, INTERFACE)
            self._lib.libusb_close(self._handle)
            self._handle = None

    def close(self):
        self._close_handle()
        if self._ctx:
            self._lib.libusb_exit(self._ctx)
            self._ctx = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()

    def reset(self):
        """libusb_reset_device, then re-open (the device re-enumerates)."""
        if self._handle is None:
            raise UsbError("not open")
        r = self._lib.libusb_reset_device(self._handle)
        # the old handle is dead after a reset regardless of return value
        self._lib.libusb_close(self._handle)
        self._handle = None
        time.sleep(1.5)  # re-enumeration settle time (established live)
        self.open()
        return r

    # -- transfers -----------------------------------------------------------

    def bulk_out(self, data: bytes, timeout_ms=None) -> int:
        buf = (C.c_ubyte * len(data)).from_buffer_copy(data)
        sent = C.c_int()
        r = self._lib.libusb_bulk_transfer(self._handle, EP_OUT, buf, len(buf),
                                           C.byref(sent), self._to(timeout_ms))
        if r != 0 or sent.value != len(data):
            raise UsbError(f"bulk OUT (ep {EP_OUT:02x}): code {r}, "
                           f"sent {sent.value}")
        return sent.value

    def bulk_in(self, size=PAGE, timeout_ms=None) -> bytes:
        buf = (C.c_ubyte * size)()
        got = C.c_int()
        r = self._lib.libusb_bulk_transfer(self._handle, EP_IN, buf, size,
                                           C.byref(got), self._to(timeout_ms))
        if r == LIBUSB_TIMEOUT:
            raise TimeoutError(f"bulk IN (ep {EP_IN:02x}): timeout")
        if r != 0:
            raise UsbError(f"bulk IN (ep {EP_IN:02x}): code {r}")
        return bytes(buf[:got.value])

    def interrupt_in(self, timeout_ms=None) -> bytes:
        buf = (C.c_ubyte * 8)()
        got = C.c_int()
        r = self._lib.libusb_interrupt_transfer(self._handle, EP_INT, buf, 8,
                                                C.byref(got),
                                                self._to(timeout_ms))
        if r == LIBUSB_TIMEOUT:
            raise TimeoutError(f"interrupt IN (ep {EP_INT:02x}): timeout")
        if r != 0:
            raise UsbError(f"interrupt IN (ep {EP_INT:02x}): code {r}")
        return bytes(buf[:got.value])

    def _to(self, timeout_ms):
        return self.timeout_ms if timeout_ms is None else timeout_ms


# ---------------------------------------------------------------------------
# Protocol: declarative model (mirrors docs/DS-330_PROTOCOL.md §9)
# ---------------------------------------------------------------------------

# INT status packet (8 bytes), as seen in captured player traffic:
#   06 00 00 00 01 ..  accepted, bulk data stage follows on 0x81
#   ff 01 00 00 01 ..  accepted, no data stage
#   ff ff ff ff 01 ..  rejected
#   00 00 00 00 01 ..  idle/ready (poll response)
# byte 4 == 01 -> accepted; byte 0 == 06 -> data stage follows.
STATUS_ACCEPTED_BYTE = 4
STATUS_ACCEPTED = 0x01
STATUS_DATA_STAGE = 0x06
STATUS_REJECT_PREFIX = b"\xff\xff\xff\xff"

ACCEPT_DATA = b"\x06\x00\x00\x00\x01\x00\x00\x00"   # accepted, data follows
ACCEPT_NODATA = b"\xff\x01\x00\x00\x01\x00\x00\x00"  # accepted, no data stage
REJECT = b"\xff\xff\xff\xff\x01\x00\x00\x00"          # rejected


@dataclass(frozen=True)
class Frame:
    """One command frame in a sequence.

    bytes   wire bytes, unpadded. Commands travel as zero-padded
            64-byte pages; the device inspects only the leading bytes.
    pages   bulk-IN pages to read for the data stage (0 = none).
    name    handle for results/errors; defaults to the wire bytes.
    suffix  optional callable producing dynamic trailing byte(s)
            (e.g. the folder/file selector in `18 <folder> <file>`),
            appended to `bytes`.
    """

    bytes: bytes
    pages: int = 0
    name: str = ""
    suffix: Optional[Callable[[dict], bytes]] = None

    def wire(self, params: dict) -> bytes:
        b = self.bytes + (self.suffix(params) if self.suffix else b"")
        if len(b) > PAGE:
            raise DS330Error(f"frame {self.name or b.hex()!r} exceeds {PAGE} bytes")
        return b

    def key(self) -> str:
        return self.name or self.bytes.hex()


@dataclass(frozen=True)
class StreamPhase:
    """Marker step: read bulk-IN pages until timeout (end of data)."""

    name: str = "stream"


# §9.1 connect/init handshake
INIT = Frame(b"\xf0\x00", pages=1, name="init")
DEVICE_INFO = Frame(b"\xb2\x00", pages=1, name="device-info")

# §9.2 folder scan (required warmup before any file operation).
# `47 01` is a status/counter (GetFileNum-like) response, NOT a folder
# name, so `info` keeps it but does not parse it as one.
FOLDER_SCAN = [Frame(b"\x47\x01", pages=1, name="file-count")] + [
    Frame(b"\x47" + bytes([a]), pages=1, name=f"folder-{a - 1}")
    for a in range(2, 6)]

# §9.3 file info
FILE_INFO = Frame(b"\x40\x01", pages=17, name="file-info")
FILE_INFO_FLUSH = Frame(b"\x41\x01", name="file-info-flush")

# §9.4 download: `18 <folder> <file>` — second byte is the folder
# (1–5 = device folders A–E; A is unnamed, B–E are named DICTATE/
# LECTURE/TO DO/RANDOM per the 47 02..05 queries), third byte is the
# 1-based file within it — then `80 00` starts the data phase.
OPEN_FILE = Frame(b"\x18", pages=1, name="open-file",
                  suffix=lambda p: bytes([p["folder"], p["file_index"]]))
DATA_PHASE = Frame(b"\x80\x00", name="data-phase")
STREAM = StreamPhase()

# §9.6 clock set: `90` + 12 ASCII digits YYMMDDHHMMSS
SET_TIME = Frame(b"\x90", name="set-time",
                 suffix=lambda p: p["when"].strftime("%y%m%d%H%M%S").encode("ascii"))

# §9.7: single-frame queries used by `info`
LABEL_QUERY = Frame(b"\x95\x00", pages=1, name="label")
MEMORY_QUERY = Frame(b"\x79\x00", pages=1, name="memory")


def info_sequence() -> Sequence:
    """§9.1+§9.2 session (identity + folder warmup)."""
    return [INIT, DEVICE_INFO, *FOLDER_SCAN]


def download_sequence() -> Sequence:
    """§9.4 session (data stream accumulated under results["stream"])."""
    return [INIT, DEVICE_INFO, *FOLDER_SCAN, FILE_INFO, FILE_INFO_FLUSH,
            OPEN_FILE, DATA_PHASE, STREAM]


# ---------------------------------------------------------------------------
# Executor: one generic runner for every sequence
# ---------------------------------------------------------------------------

class DS330:
    """The DS-330 protocol on top of the Usb transport.

    Sequences (info_sequence(), download_sequence(), [SET_TIME]) are
    lists of Frame/StreamPhase steps. run_sequence() walks them and
    applies the frame rules established from the player captures:

    - commands go out as zero-padded 64-byte pages
    - an 8-byte interrupt status follows; byte 4 == 01 means accepted
      (a leading ff ff ff ff means rejected)
    - a frame with pages > 0 reads that many bulk-IN pages
    - a StreamPhase step reads bulk-IN pages until timeout (end of data)
    """

    def __init__(self, verbose=False, timeout_ms=2000, usb: Optional[Usb] = None):
        self.verbose = verbose
        self.usb = usb if usb is not None else Usb(timeout_ms=timeout_ms)

    # -- lifecycle ----------------------------------------------------------

    def open(self):
        self.usb.open()
        return self

    def close(self):
        self.usb.close()

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    def reset(self):
        """Reset the device and re-open (recovery without replug)."""
        return self.usb.reset()

    # -- protocol -----------------------------------------------------------

    def run_sequence(self, steps: Sequence, progress: Optional[Callable] = None,
                     **params) -> dict:
        """Execute Frame/StreamPhase steps; return results keyed by name.

        Dynamic frame bytes come from `params` (e.g. file_index=2,
        when=datetime(...)). Raises ProtocolRejected if the device
        answers a frame with the reject status; transport errors
        propagate as UsbError/TimeoutError.
        """
        results = {}
        stream = bytearray()
        t0 = time.time()
        for step in steps:
            if isinstance(step, StreamPhase):
                while True:
                    try:
                        stream += self.usb.bulk_in(timeout_ms=2000)
                    except TimeoutError:
                        break
                    if progress and len(stream) % 65536 < PAGE:
                        progress(len(stream), time.time() - t0)
                results[step.name] = bytes(stream)
                continue
            wire = step.wire(params)
            page = wire + b"\x00" * (PAGE - len(wire))
            self._trace("OUT>", page)
            self.usb.bulk_out(page)
            status = self._trace("INT<", self.usb.interrupt_in())
            if status[:len(STATUS_REJECT_PREFIX)] == STATUS_REJECT_PREFIX:
                raise ProtocolRejected(
                    f"device rejected {step.key()!r} "
                    f"(frame {wire.hex()}, status {status.hex()})")
            if len(status) <= STATUS_ACCEPTED_BYTE or \
                    status[STATUS_ACCEPTED_BYTE] != STATUS_ACCEPTED:
                raise ProtocolRejected(
                    f"unexpected status {status.hex()} for {step.key()!r}")
            if step.pages:
                data = bytearray()
                for _ in range(step.pages):
                    try:
                        data += self.usb.bulk_in()
                    except TimeoutError:
                        break
                results[step.key()] = bytes(data)
        return results

    def _trace(self, tag, data):
        if self.verbose:
            hexs = data[:32].hex() + ("..." if len(data) > 32 else "")
            print(f"    {tag} {len(data):5d} {hexs}", file=sys.stderr)
        return data

    # -- high-level operations (each = documented sequences) ----------------

    def folder_names(self):
        """The device's user-set folder names for folders B-E (47 02..05).
        Folder A's query (47 01) returns status, not a name. Names are
        device-specific and user-configurable — never assume defaults."""
        r = self.run_sequence([INIT, DEVICE_INFO, *FOLDER_SCAN])
        names = []
        for f in FOLDER_SCAN[1:]:
            page = r.get(f.key(), b"")
            names.append(page[4:12].decode("ascii", "replace").strip()
                         if len(page) >= 12 else "")
        return names

    def resolve_folder(self, spec):
        """Resolve a CLI folder spec against THIS device's folder names."""
        try:
            return resolve_folder(spec)
        except DS330Error:
            if str(spec).strip().isdigit() or len(str(spec).strip()) == 1:
                raise
            return resolve_folder(spec, names=self.folder_names())

    def info(self) -> dict:
        """Device identity, label, folders, memory, file table.

        Query order matters (established live): `40 01` stops being
        answered after the label (`95 00`) or memory (`79 00`) queries,
        so the file-info query runs first.
        """
        r = self.run_sequence([*info_sequence(), FILE_INFO,
                                LABEL_QUERY, MEMORY_QUERY])
        folders = [p[4:12].decode("ascii", "replace").strip()
                   for f in FOLDER_SCAN[1:] if len(p := r.get(f.key(), b"")) >= 12]
        label = self._query(LABEL_QUERY, r)
        memory = self._query(MEMORY_QUERY, r)
        fi = parse_file_info(r.get(FILE_INFO.key()))
        return {
            "device": ascii_stripped(r.get(DEVICE_INFO.key())),
            "label": label,
            "folders": [f for f in folders if f],
            "memory": memory,
            "file_info": fi or None,
        }

    def _query(self, frame: Frame, r=None):
        data = (r or self.run_sequence([frame])).get(frame.key(), b"")
        if frame is MEMORY_QUERY:
            if len(data) < 8:
                return None
            a, b = struct.unpack("<II", data[:8])
            # the two dwords echo each other; do not guess if they disagree
            return a if a == b else None
        return ascii_stripped(data) or None

    def download_raw(self, folder=1, file_index=1, progress=None):
        """§9.4 session: open `18 <folder> <file>` and stream it.

        `folder` is 1–5 (device folders A–E; folder 5 is RANDOM), and
        `file_index` is the 1-based file within that folder. An empty
        stream means the folder/file does not exist.
        """
        r = self.run_sequence(download_sequence(), progress=progress,
                              folder=folder, file_index=file_index)
        fi = parse_file_info(r.get(FILE_INFO.key())) or None
        return fi, r.get(STREAM.name, b"")

    def set_time(self, when: Optional[datetime.datetime] = None
                 ) -> datetime.datetime:
        """§9.6: `90` + 12 ASCII digits YYMMDDHHMMSS.

        `when` is a naive wall-clock time as it should appear on the
        recorder. Default: the computer's local time; the CLI's --utc
        option passes UTC instead so recording stamps are zone-independent.
        """
        when = when or datetime.datetime.now()
        self.run_sequence([SET_TIME], when=when)
        return when


def ascii_stripped(data: bytes) -> str:
    return data.rstrip(b"\x00").decode("ascii", "replace").strip()


# ---------------------------------------------------------------------------
# Parsing: file-info object, date stamps, raw stream -> DSS bytes
# ---------------------------------------------------------------------------

def parse_file_info(info) -> dict:
    """Parse the 17-page (1088 B) file-info object.

    Layout (offsets verified against the captured player stream):
      page 0 [0x00:0x08]   file name, 8 ASCII chars
      page 0 [0x09]        0x02 = DSS file-format version byte
      page 0 [0x0A:0x0D]   'dss' literal
      page 0 [0x15:0x1D]   author label, 8 ASCII chars (matches 0x95 query)
      page 0+1 [0x2F:0x4D] 30 ASCII date digits (see decode_date_digits)
      page 1 [0x4D:0x50]  0xFF 0x07 0xFF padding after the digits
      page 8 [+0x09]       LE dword -- flash-region/metadata size,
                           NOT the audio file size
    """
    if not info or len(info) < 17 * PAGE:
        return {}
    name = info[0x00:0x08].decode("ascii", "replace").strip()
    label = info[0x15:0x1D].decode("ascii", "replace").strip()
    date_digits = (info[0x2F:0x40] + info[0x40:0x4D]).decode("ascii", "replace")
    return {
        "name": name or None,
        "format": info[0x0A:0x0D].decode("ascii", "replace"),
        "label": label or None,
        "date_digits": date_digits,
        "dates": decode_date_digits(date_digits),
        "flash_region": struct.unpack("<I", info[8 * PAGE + 9:][:4])[0],
    }


def decode_date_digits(digits) -> Optional[dict]:
    """Decode the 30 ASCII digit stamps in the file-info object.

    Layout (deduced from the captured reference recording, whose player
    output was ~23 minutes long):
      digits[0:12]   start timestamp, YYMMDDHHMMSS
      digits[12:24]  stop timestamp,  YYMMDDHHMMSS
      digits[24:30]  duration,        HHMMSS
    stop - start tracks the duration (within 1s on the reference capture:
    the recorder's own duration field runs one second short), which
    confirms the split. A
    recorder with an unset clock stamps files with its power-on
    default (observed: 2002-01-01 00:01:05).

    Returns {"start", "stop", "duration"} or None if absent/unparseable.
    """
    digits = (digits or "").strip("\x00\xff ")
    if len(digits) < 30 or not digits[:30].isdigit():
        return None
    d = digits[:30]
    try:
        start = datetime.datetime.strptime(d[0:12], "%y%m%d%H%M%S")
        stop = datetime.datetime.strptime(d[12:24], "%y%m%d%H%M%S")
        duration = datetime.timedelta(hours=int(d[24:26]),
                                      minutes=int(d[26:28]),
                                      seconds=int(d[28:30]))
    except ValueError:
        return None
    return {"start": start, "stop": stop, "duration": duration}


def extract_dss(stream: bytes) -> bytes:
    """Extract the .dss file content from the raw `80 00` data stream.

    The stream interleaves the DSS file with device bookkeeping frames
    (verified byte-for-byte against the player's own output):

      stream[0:2]     preamble -- discard
      stream[2:514]   dss[0:512]  (first block, no leading frame)
      then repeating, period 576 = 64 + 512:
          64-byte bookkeeping frame -- discard
          512 bytes of dss
      stream tail     folder-name table -- discard

    The 576 period is a flash-page artifact (512 data bytes per 64-byte
    frame). The stream ends on a bulk-read timeout, so the last chunk
    may be short; incomplete tails are dropped.

    Fixup: dss[792] = 0xFE -- a DSS-header flag byte the player rewrites
    on save; the stream carries 0xFF there.
    """
    PREAMBLE, DATA, BOOK = 2, 512, 64
    if len(stream) < PREAMBLE + DATA + BOOK:
        raise DS330Error(f"raw stream too short ({len(stream)} bytes) -- "
                         "incomplete download")
    out = bytearray(stream[PREAMBLE:PREAMBLE + DATA])
    pos = PREAMBLE + DATA + BOOK  # skip the first bookkeeping frame
    period = BOOK + DATA
    while pos + DATA <= len(stream):
        out += stream[pos:pos + DATA]
        pos += period
    if len(out) > 792:
        out[792] = 0xFE
    return bytes(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def ffmpeg_convert(dss_path, wav_path):
    if subprocess.call(["ffmpeg", "-y", "-loglevel", "error", "-i",
                        dss_path, wav_path]) != 0:
        print("warning: ffmpeg conversion failed", file=sys.stderr)


def cmd_info(dev, args):
    i = dev.info()
    print(f"device : {i['device']}")
    print(f"label  : {i['label']}")
    print(f"folders: {', '.join(i['folders']) if i['folders'] else '?'}")
    if i["memory"] is not None:
        print(f"memory : {i['memory']:,}")
    fi = i["file_info"]
    if not fi:
        print("file   : (none -- no recordings on device)")
        return
    print(f"file   : {fi['name']}  ({fi['format']})  "
          f"label={fi['label']}  flash_region={fi['flash_region']}")
    dates = fi["dates"]
    if dates:
        print(f"dates  : start {dates['start']:%Y-%m-%d %H:%M:%S}  "
              f"stop {dates['stop']:%Y-%m-%d %H:%M:%S}  "
              f"duration {dates['duration']}")
    else:
        print(f"dates  : {fi['date_digits']!r} (unparsed)")


def resolve_folder(spec, names=None):
    """Folder spec -> 1-5. Accepts a number or a letter A-E always;
    folder NAMES are device-specific (user-settable, read via the
    47 02..05 queries) and are only resolved when `names` supplies the
    current device's actual names — as a list where names[0] is folder
    B, ..., names[3] is folder E. Never hardcode name->folder mappings.
    """
    s = str(spec).strip().lower()
    if s in {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}:
        return {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}[s]
    if s.isdigit() and 1 <= int(s) <= 5:
        return int(s)
    if names:
        for i, name in enumerate(names):
            if name and name.strip().lower() == s:
                return i + 2  # names[0] is folder B
        raise DS330Error(
            f"no folder named {spec!r} on this device. Folders: "
            + ", ".join(f"{chr(ord('A') + i + 1)}='{n}'" for i, n in enumerate(names)))
    raise DS330Error(f"bad folder {spec!r}: use 1-5 or A-E"
                    + ("" if names is None else ""))


def parse_dss_header(dss: bytes) -> Optional[dict]:
    """Per-file metadata from the DSS file header itself.

    Offsets (per the DSS format; same stamps as the file-info object):
      [38:50]  record start, YYMMDDHHMMSS ASCII
      [50:62]  record stop,  YYMMDDHHMMSS ASCII
      [62:68]  duration,      HHMMSS ASCII
    Used for output naming: the device's 8-char file names are only
    readable for the first file via the `40 01` object, but every
    downloaded DSS carries its own timestamps.
    """
    try:
        start = datetime.datetime.strptime(dss[38:50].decode("ascii"),
                                           "%y%m%d%H%M%S")
    except ValueError:
        return None
    try:
        stop = datetime.datetime.strptime(dss[50:62].decode("ascii"),
                                          "%y%m%d%H%M%S")
    except ValueError:
        stop = start
    return {"start": start, "stop": stop}


def recording_name(dss: bytes, fallback: str) -> str:
    """Base name for a downloaded recording: <YYYYMMDDTHHMMSS> (ISO 8601
    date/time separator) from the DSS header (folder/timestamp naming),
    or the fallback if the header does not parse."""
    header = parse_dss_header(dss)
    if header:
        return header["start"].strftime("%Y%m%dT%H%M%S")
    return fallback


def save_recording(stream, fi, out, args):
    dss = extract_dss(stream)
    with open(out, "wb") as f:
        f.write(dss)
    # Filesystem timestamps from the recording itself (rsync-style
    # preservation): mtime = when the recording finished (stop), the
    # moment the file's content was complete on the device. atime
    # follows. ctime cannot be set on Linux (kernel-managed).
    header = parse_dss_header(dss)
    if header:
        ts = header["stop"].timestamp()
        os.utime(out, (ts, ts))
    print(f"wrote {len(dss)} bytes -> {out}")
    if args.raw:
        with open(os.path.expanduser(args.raw), "wb") as f:
            f.write(stream)
        print(f"raw stream saved -> {args.raw}")
    if args.wav:
        wav = args.wav if args.wav is not True else os.path.splitext(out)[0] + ".wav"
        ffmpeg_convert(out, wav)
        print(f"converted -> {wav}")
    return out


def cmd_download_one(dev, args):
    def progress(total, dt):
        print(f"  {total:8d} bytes ({dt:5.1f}s)", file=sys.stderr)
    print("downloading raw stream ...", file=sys.stderr)
    folder = dev.resolve_folder(args.folder)
    fi, stream = dev.download_raw(
        folder=folder,
        file_index=args.index,
        progress=progress if args.verbose else None)
    print(f"raw stream: {len(stream)} bytes", file=sys.stderr)
    if not stream:
        raise ProtocolRejected("device returned no data -- "
                               "no recording in that folder at that index?")
    letter = chr(ord("A") + folder - 1)
    fallback = (fi or {}).get("name") or f"{letter}{args.index:02d}"
    out = os.path.expanduser(args.out
                                or f"{letter}{args.index:02d}_"
                                   f"{recording_name(extract_dss(stream), fallback)}.dss")
    return save_recording(stream, fi, out, args)


def cmd_download_all(dev, args):
    """Default (no --folder/--index): download every recording from every
    folder. There is no directory-listing command, so files are found by
    probing `18 <folder> <file>`: an empty data stream cleanly signals
    the end of a folder's file list (established live). Output files are
    named <letter><NN>_<YYYYMMDD-HHMMSS>.dss from the DSS header's
    record-start timestamp, e.g. E01_20261123T005622.dss.
    """
    total = 0
    for folder in range(1, 6):
        letter = chr(ord("A") + folder - 1)
        index = 1
        while True:
            try:
                fi, stream = dev.download_raw(folder=folder, file_index=index)
            except (TimeoutError, UsbError) as e:
                print(f"  {letter}{index:02d}: {e}; resetting and retrying",
                      file=sys.stderr)
                dev.reset()
                fi, stream = dev.download_raw(folder=folder, file_index=index)
            if not stream:
                if index == 1:
                    print(f"folder {letter}: (empty)")
                break
            name = recording_name(extract_dss(stream), f"{letter}{index:02d}")
            out = os.path.expanduser(
                args.out if (args.out and folder == 1 and index == 1)
                else f"{letter}{index:02d}_{name}.dss")
            save_recording(stream, fi, out, args)
            total += 1
            index += 1
    print(f"downloaded {total} recording(s)")
    if total == 0:
        raise ProtocolRejected("no recordings found in any folder")


def cmd_download(dev, args):
    if args.folder is None and args.index is None and not args.out:
        return cmd_download_all(dev, args)
    if args.folder is None:
        args.folder = "1"
    if args.index is None:
        args.index = 1
    return cmd_download_one(dev, args)


def cmd_reset(dev, args):
    dev.reset()
    print("device reset")


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Olympus DS-330 recorder tool (download .dss, set clock)")
    p.add_argument("-v", "--verbose", action="store_true",
                    help="trace all USB frames to stderr")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="show device identity, folders, file table")

    d = sub.add_parser("download", help="download .dss recordings (default: "
                                         "all recordings from all folders)")
    d.add_argument("--folder", "-f", metavar="FOLDER", default=None,
                   help="device folder to read from: 1-5, A-E, or this "
                        "device's folder name (see 'info'; names are "
                        "user-settable per recorder). Default with no "
                        "options: sweep every folder")
    d.add_argument("--index", "-i", metavar="N", type=int, default=None,
                   help="file number within the folder, 1-based. Default "
                        "with no options: sweep every folder")
    d.add_argument("--out", metavar="FILE",
                   help="output .dss path (default: <name>.dss)")
    d.add_argument("--raw", metavar="FILE", help="also save the raw stream")
    d.add_argument("--wav", nargs="?", const=True, metavar="FILE",
                   help="convert to .wav via ffmpeg")

    s = sub.add_parser("settime", help="set recorder clock from the computer clock")
    s.add_argument("--time", metavar="YYYYMMDDTHHMMSS",
                   help="specific time instead of now; a literal T between "
                        "date and time is accepted (and preferred) "
                        "(interpreted as UTC with --utc, local otherwise)")
    s.add_argument("--utc", action="store_true",
                   help="set the clock to UTC instead of the local "
                        "timezone (with --time: interpret the digits as UTC)")

    sub.add_parser("reset", help="reset the device (recovery without replug)")

    args = p.parse_args(argv)
    when = None
    if args.command == "settime":
        if args.time:
            # a literal 'T' between date and time is accepted and
            # preferred everywhere we write timestamps; bare digits work
            when = datetime.datetime.strptime(
                args.time, "%Y%m%dT%H%M%S" if "T" in args.time.upper()
                else "%Y%m%d%H%M%S")
        elif args.utc:
            when = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    try:
        with DS330(verbose=args.verbose, timeout_ms=8000) as dev:
            if args.command == "reset":
                cmd_reset(dev, args)
                return 0
            # The device sometimes wedges out of a stale session state
            # (established live): one reset + retry fixes it. Transient
            # timeouts mid-sequence also recover the same way.
            for attempt in (1, 2):
                try:
                    if args.command == "info":
                        cmd_info(dev, args)
                    elif args.command == "download":
                        cmd_download(dev, args)
                    elif args.command == "settime":
                        t = dev.set_time(when)
                        print(f"recorder clock set to {t:%Y-%m-%d %H:%M:%S}")
                    return 0
                except (TimeoutError, UsbError) as e:
                    if attempt == 2:
                        raise
                    print(f"attempt {attempt} failed ({e}); "
                          "resetting device and retrying ...", file=sys.stderr)
                    dev.reset()
    except DS330Error as e:
        print(f"error: {e}", file=sys.stderr)
        print("hint: device state may be stale -- "
              "`ds330tool.py reset` then retry", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())