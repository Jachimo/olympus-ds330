"""Tests for ds330tool, built on real device captures where possible.

fixtures (tests/data/, captured 2026-11-22 from a live DS-330 via the
§9.4 download sequence, with personal labels sanitized):

  fileinfo.bin   the raw 17-page (1088 B) file-info object
  stream.bin     the raw `80 00` data-phase stream (2,697,408 B)
  reference.dss  extract_dss(stream.bin) — decodes cleanly via ffmpeg

Pure-protocol tests use a FakeUsb that replays scripted frame/status/data
responses, so run_sequence()'s frame rules are tested without hardware.
"""
import datetime
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

import ds330tool as t  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "data")


def fixture(name):
    with open(os.path.join(DATA, name), "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# decode_date_digits — layout: start(12) + stop(12) + duration(6), ASCII
# ---------------------------------------------------------------------------

REF_DIGITS = "020101000105020101002412002306"  # captured from a real file


def test_date_digits_reference_recording():
    d = t.decode_date_digits(REF_DIGITS)
    assert d["start"] == datetime.datetime(2002, 1, 1, 0, 1, 5)
    assert d["stop"] == datetime.datetime(2002, 1, 1, 0, 24, 12)
    assert d["duration"] == datetime.timedelta(minutes=23, seconds=6)
    # stop - start tracks the duration (here within 1s: the recorder's
    # own duration field is one second shorter than the two stamps)
    assert abs((d["stop"] - d["start"]) - d["duration"]) <= datetime.timedelta(seconds=1)


@pytest.mark.parametrize("bad", ["", None, "abc", "1" * 29, "9" * 30 + "x",
                                 "991301010000991301010000000000"])
def test_date_digits_rejects_garbage(bad):
    assert t.decode_date_digits(bad) is None


def test_date_digits_ignores_padding():
    assert t.decode_date_digits(REF_DIGITS + "\x00\x07\xff")["duration"]
    assert t.decode_date_digits("\xff" + REF_DIGITS) == \
        t.decode_date_digits(REF_DIGITS)


# ---------------------------------------------------------------------------
# parse_file_info — real captured object
# ---------------------------------------------------------------------------

def test_parse_file_info_real():
    fi = t.parse_file_info(fixture("fileinfo.bin"))
    assert fi["name"] == "DP300001"          # sanitized in fixture
    assert fi["format"] == "dss"
    assert fi["label"] == "USER"
    assert fi["flash_region"] == 1386384    # page 8 [+0x09] LE dword
    assert fi["dates"]["start"] == datetime.datetime(2002, 1, 1, 0, 1, 5)
    assert fi["dates"]["stop"] == datetime.datetime(2002, 1, 1, 0, 24, 12)
    assert fi["dates"]["duration"] == datetime.timedelta(minutes=23, seconds=6)


def test_parse_file_info_rejects_short():
    assert t.parse_file_info(None) == {}
    assert t.parse_file_info(b"\x00" * 100) == {}
    assert t.parse_file_info(b"\x00" * 1088) is not None


# ---------------------------------------------------------------------------
# extract_dss — real captured stream, byte-for-byte checked
# ---------------------------------------------------------------------------

def test_extract_dss_real_stream_roundtrip():
    stream = fixture("stream.bin")
    dss = t.extract_dss(stream)
    assert dss == fixture("reference.dss")


def test_extract_dss_layout_periods():
    stream = fixture("stream.bin")
    dss = t.extract_dss(stream)
    # documented layout: 2-byte preamble, first 512 at 2, then repeating
    # 64-byte bookkeeping + 512-byte dss (period 576)
    assert dss[:512] == stream[2:2 + 512]
    # second block: stream[578:1090], with the dss[792] fixup applied
    # (792 - 512 == 280 within this block)
    block = bytearray(stream[2 + 512 + 64:2 + 512 + 64 + 512])
    block[280] = 0xFE
    assert dss[512:1024] == bytes(block)
    # bookkeeping bytes must not leak into the output (sample a few frames)
    for base in (2 + 512, 2 + 512 + 576, 2 + 512 + 2 * 576):
        book = stream[base:base + 64]
        if book.strip(b"\x00"):
            assert book not in dss


def test_extract_dss_fixup_byte_792():
    stream = bytearray(b"\x00" * (2 + 512 + 64 + 512))
    stream[0] = 0xAA  # preamble marker (must be dropped)
    dss = t.extract_dss(bytes(stream))
    assert dss[0] != 0xAA            # preamble dropped
    assert len(dss) == 1024          # both 512-byte blocks extracted
    assert dss[792] == 0xFE           # header flag fixup
    assert dss[793] == 0


def test_extract_dss_too_short():
    with pytest.raises(t.DS330Error):
        t.extract_dss(b"\x00" * 100)


def test_extract_dss_synthetic():
    dss = bytes(range(256)) * 4      # 1024 bytes of test pattern
    stream = b"\xaa\xbb" + dss[:512] + b"BOOK" * 16 + dss[512:1024] + b"TAIL"
    assert t.extract_dss(stream) == dss[:792] + b"\xfe" + dss[793:]


# ---------------------------------------------------------------------------
# Frame model + run_sequence — scripted FakeUsb (no hardware)
# ---------------------------------------------------------------------------

class FakeUsb:
    """Replays scripted responses: a status packet per OUT frame, then
    scripted bulk-IN pages per data stage."""

    def __init__(self, script):
        # script: list of (frame_bytes_prefix -> (status, [data pages]))
        self.script = script
        self.sent = []
        self.bulk_in_pages = []

    def open(self):
        pass

    def close(self):
        pass

    def bulk_out(self, data, timeout_ms=None):
        self.sent.append(bytes(data))
        status, pages = self.script[len(self.sent) - 1]
        self._status = status
        self.bulk_in_pages = list(pages)

    def interrupt_in(self, timeout_ms=None):
        return self._status

    def bulk_in(self, size=t.PAGE, timeout_ms=None):
        if not self.bulk_in_pages:
            raise TimeoutError("bulk IN: timeout")
        return self.bulk_in_pages.pop(0)


ACCEPT = t.ACCEPT_DATA          # 06..01: accepted, data stage follows
ACCEPT_NO = t.ACCEPT_NODATA     # ff 01..: accepted, no data stage


def test_run_sequence_full_download():
    # the §9.4 download, replayed with plausible page contents
    dev_page = b"\x00\x00\x00\x00" + b"DP300001"
    fi = bytearray(t.PAGE * 17)
    fi[0:8] = b"DP300001"
    fi[0x0A:0x0D] = b"dss"
    fi[0x2F:0x4D] = REF_DIGITS.encode()
    fi[8 * t.PAGE + 9:][:4] = (1386384).to_bytes(4, "little")
    script = [
        (ACCEPT, [b"\x00" * 64]),                    # init
        (ACCEPT, [b"DS-330  USER"]),                 # device-info
        (ACCEPT, [b"\x01" + b"\x00" * 63]),          # file-count
        (ACCEPT, [dev_page]),                        # folder-1
        (ACCEPT, [dev_page]), (ACCEPT, [dev_page]), (ACCEPT, [dev_page]),
        (ACCEPT, [bytes(fi)]),                        # file-info (17 pages)
        (ACCEPT_NO, []),                             # file-info-flush
        (ACCEPT, [b"\x00\x96\x24\x00"]),             # open-file
        (ACCEPT_NO, []),                             # data-phase
    ]
    fake = FakeUsb(script)
    dev = t.DS330(usb=fake)
    r = dev.run_sequence(t.download_sequence(), folder=1, file_index=1)
    # every frame went out as a zero-padded 64-byte page
    assert all(len(s) == 64 for s in fake.sent)
    assert fake.sent[0][:2] == b"\xf0\x00"
    # the folder and file selector bytes were injected (frame #10)
    assert fake.sent[9] == b"\x18\x01\x01" + b"\x00" * 61
    assert fake.sent[10][:2] == b"\x80\x00"
    # file-info parsed from the scripted pages
    fi = t.parse_file_info(r["file-info"])
    assert fi["name"] == "DP300001"
    assert fi["dates"]["duration"] == datetime.timedelta(minutes=23, seconds=6)


def test_run_sequence_rejection():
    fake = FakeUsb([(t.REJECT, [])])
    dev = t.DS330(usb=fake)
    with pytest.raises(t.ProtocolRejected):
        dev.run_sequence([t.INIT])


def test_run_sequence_open_file_selector_bytes():
    fake = FakeUsb([(ACCEPT, [b"\x00" * 64])] * 11)
    dev = t.DS330(usb=fake)
    dev.run_sequence(t.download_sequence(), folder=5, file_index=3)
    assert fake.sent[9][:3] == b"\x18\x05\x03"


def test_run_sequence_rejects_unknown_status():
    fake = FakeUsb([(b"\x00" * 8, [])])
    dev = t.DS330(usb=fake)
    with pytest.raises(t.ProtocolRejected):
        dev.run_sequence([t.INIT])


def test_run_sequence_stream_phase_reads_until_timeout():
    fi = bytearray(t.PAGE * 17)
    script = [(ACCEPT_NO, [])] + [(ACCEPT, [b"\x01" * 64])] * 2 \
        + [(ACCEPT_NO, [])]
    fake = FakeUsb(script)
    # patch bulk_in to emit 3 pages then timeout inside the stream phase
    pages = [b"AAAA", b"BBBB"]

    def bulk_in(size=t.PAGE, timeout_ms=None):
        if pages:
            return bytes(pages.pop(0)).ljust(64, b"\x00")
        raise TimeoutError("timeout")

    fake.bulk_in = bulk_in
    dev = t.DS330(usb=fake)
    r = dev.run_sequence([t.FILE_INFO_FLUSH, t.DATA_PHASE,
                           t.STREAM, t.STREAM])
    # both StreamPhase steps see the SAME accumulated stream
    assert r["stream"].startswith(b"AAAA")
    assert b"BBBB" in r["stream"]


def test_set_time_frame():
    fake = FakeUsb([(ACCEPT_NO, [])])
    dev = t.DS330(usb=fake)
    when = datetime.datetime(2026, 11, 22, 2, 12, 17)
    got = dev.set_time(when)
    assert got == when
    assert fake.sent[0][:13] == \
        b"\x90" + b"261122021217"  # captured player frame, decoded


# ---------------------------------------------------------------------------
# CLI settime --utc / --time wiring
# ---------------------------------------------------------------------------

def test_main_settime_utc_sends_utc_clock(monkeypatch, capsys):
    sent = {}

    class FakeDS330:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def reset(self):
            pass

        def set_time(self, when):
            sent["when"] = when
            return when

    class FakeDT(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            base = cls(2026, 11, 22, 12, 34, 56)
            return base if tz is None else base.replace(tzinfo=tz)

    monkeypatch.setattr(t, "DS330", FakeDS330)
    monkeypatch.setattr(t.datetime, "datetime", FakeDT)
    assert t.main(["settime", "--utc"]) == 0
    # the naive UTC wall time was sent, not the local time
    assert sent["when"] == datetime.datetime(2026, 11, 22, 12, 34, 56)


def test_main_settime_utc_with_explicit_time(monkeypatch, capsys):
    sent = {}

    class FakeDS330:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def reset(self):
            pass

        def set_time(self, when):
            sent["when"] = when
            return when

    monkeypatch.setattr(t, "DS330", FakeDS330)
    assert t.main(["settime", "--utc", "--time", "20261122120000"]) == 0
    # explicit digits are used verbatim, tagged as UTC only in intent
    assert sent["when"] == datetime.datetime(2026, 11, 22, 12, 0, 0)


def test_descriptor_layout():
    # USB device descriptor: 18 packed bytes; unpack must round-trip VID/PID
    desc = bytes([18, 1]) + struct.pack("<H", 0x0110) + bytes([9, 0, 0, 8]) \
        + struct.pack("<H", 0x07B4) + struct.pack("<H", 0x0206) \
        + struct.pack("<H", 0x0100) + bytes([1, 2, 3, 1])
    assert len(desc) == 18
    parsed = t.parse_device_descriptor(desc)
    assert parsed["idVendor"] == t.VID
    assert parsed["idProduct"] == t.PID
    assert parsed["bLength"] == 18

# ---------------------------------------------------------------------------
# usb-level error mapping / folder resolution
# ---------------------------------------------------------------------------

def test_usb_error_hierarchy():
    assert issubclass(t.UsbError, t.DS330Error)
    assert issubclass(t.ProtocolRejected, t.DS330Error)


@pytest.mark.parametrize("spec,expected", [
    ("1", 1), ("5", 5), ("a", 1), ("E", 5), ("A", 1),
    ("random", 5), ("RANDOM", 5), ("dictate", 2), ("lecture", 3),
    ("to do", 4), ("todo", 4), ("TODO", 4),
])
def test_resolve_folder(spec, expected):
    assert t.resolve_folder(spec) == expected


@pytest.mark.parametrize("bad", ["0", "6", "f", "music", "", "a1"])
def test_resolve_folder_rejects(bad):
    with pytest.raises(t.DS330Error):
        t.resolve_folder(bad)
