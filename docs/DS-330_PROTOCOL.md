# Olympus DS-330 USB Protocol — Reverse Engineering Notes

**Device:** Olympus DS-330 digital voice recorder (ca. 2002)
**USB ID:** 07b4:0206 (vendor Olympus, "DIGITAL VOICE RECORDER DS-330")
**USB version:** 1.10, bus-powered, full-speed. Display shows "REMOTE" when
connected and idle.
**See DS-330_NOTES.md for the wider project log.** This document is the
protocol reference. Status: reverse-engineering IN PROGRESS; file download
not yet achieved. Last updated: 2026-11-20.

---

## 1. USB device structure

5 interfaces in configuration 1:

| If | Purpose | Endpoints |
|----|---------|-----------|
| 0 | **Vendor-specific — file transfer / control** | Bulk OUT 0x02 (commands), Bulk IN 0x81 (data), Interrupt IN 0x83 (status) |
| 1–4 | Standard USB Audio (UAC1) mic + speaker PCM paths | ISO, 8/11.025/16/22.05 kHz 16-bit mono |

Interface 0 is never claimed by any kernel driver, so a native libusb
extractor needs no unbind dance. The audio interfaces are irrelevant to
file extraction (analog/USB-audio routes are out of scope by stipulation).

Endpoint max packet size: 64 bytes (full-speed bulk).

## 2. Frame model (confirmed)

All commands target **interface 0** only. The pattern:

1. **Command:** BULK OUT 0x02, 1–2 bytes (`[cmd][arg]`).
2. **Status:** INTERRUPT IN 0x83, 8 bytes:
   - `06 00 00 00 01 00 00 00` = command accepted, data stage follows
   - `ffff000001000000` = command rejected (no data stage will come)
   - `0000000001000000` = idle/ready (seen after fresh enumeration)
   - `ff01000001000000` = also seen post-enumeration
   - b=01 in byte 4 = accepted; a=06 in byte 0 = bulk data stage follows
3. **Data:** BULK IN 0x81, 64-byte pages.

Notes:
- The INT status is only reliably sent for the **first** page of a stream;
  subsequent pages can be read with plain bulk_in until timeout.
- On some firmware states the status read times out but the bulk data still
  arrives (seen with 0x40 streams).
- Commands that are rejected produce `out=0` but `in=-7` (LIBUSB_ERROR_TIMEOUT)
  with no data.

## 3. Command map (empirically confirmed)

Format: `cmd [arg]` → response. Verified with device reset between probes.

### 0x40 — file info object stream (CONFIRMED, deterministic)
- `40 01` → starts a 17-page (1088-byte) sequential stream. Each bulk_in
  returns the next page; the cursor auto-advances and does NOT reset when
  the command is repeated. `40 02` starts at page 1. Args 11, 12, ff: no
  response. Stream ends with timeout after last page (deterministic, 3x
  verified).
- Contents of the 17-page object (one file on device, "JSMYTHE001"):
  - page 0: file header: `"JSMYTHE001"` (name), `02 64 73 73 01 00 01 00 02 00
    00 00` (dss magic), `"JSMYTHE"` (label), date string `02010100010502010`
  - page 1: date continuation `1002412002306` + `ff07`
  - pages 2–7: FF fill (erased slots)
  - page 8: dword `90 27 15 00` (LE 0x00152790 = 1,384,080) — size or region
  - pages 9–16: zeros/FF
- This object is the same data that command `00` primes (older C-based dump
  read 32 pages via `00`; the file header was at page 15 of that dump).

### 0x47 — status/counter (CONFIRMED)
- `47 01` and `47 00000000` → ~41 bytes of zeros. Possibly GetFileNum or
  OpenFile. Does NOT redirect the 0x40 stream to file data (tested).

### 0x95 — device label (CONFIRMED)
- `95 01` → `"JSMYTHE"` (16 bytes, zero-padded). The recorder's user label.

### 0xb2 — device identity (CONFIRMED)
- `b2 01` → `"DS-330    JSMYTHE"` (model name + user label, zero-padded).

### 0xb3 — single value (CONFIRMED)
- `b3 01` → `10 00 00 ...` (16 bytes). Unknown (maybe max file count or
  folder count).

### 0xc0 — binary blob (CONFIRMED)
- `c0 01` → 26 bytes: `a0 d2 0a 05 0e 04 00 b0 07 00 00 20 92 be db 83 5c
  43 f2 20 c2 aa 5f b5 00 00`. Possibly device settings or calibration.

### 0xd1 — small value (CONFIRMED)
- `d1 01` → `00 c0 d0 00 00 ...` (14 bytes). Unknown.

### 0x78 — device info (CONDITIONAL)
- `78` (single byte) → 64-byte page: `01 03 d9 01 ff 18 02 df 01 20 04 00
  00 00 00 21 02 04 01 22 02 01 01 22 03 02 04 07 1a 05 01 03 00 02 0f 1b
  08 c0 c0 a1 01 55 08 00 20 1b 0a c1 41 99 01 55 64 f0 ff ff 20 1b 0a c1
  41 99 01 55 64 f0 ff ff` — looks like a config/capability table (contains
  sample-rate/codec codes). NOTE: `78 01` returns all-FF (rejected), and
  after a stream has already run, `78` also returns all-FF. Likely one-shot
  per session.

### 0x79 — status (CONDITIONAL)
- `79` (single byte) → 16 bytes with two copies of dword `0x0097a565`
  (9,943,141). Likely memory size or free space. Same one-shot caveat as
  0x78.

## 4. Commands that do NOT respond (negative results)

All tested on fresh state (device reset between each), `out=0 in=-7`:

- `0x7b` flash-sector read: 1-byte args (00,01,02,03,10,20), 4-byte LE args
  (0,1,2), and single-byte — all rejected. NOT the sector path on this FW.
- `0x41`, `0x42`, `0x43`, `0x44`, `0x45`, `0x46`, `0x30`, `0x33` with `01`
  arg — rejected.
- `0x50`, `0x48`, `0x51`, `0x52` with 1-byte and 4-byte args — rejected.
  The DLL IOCTL→wire mapping is NOT a simple offset-4 correspondence.
- `0x40` with args 02 (works = page 1), 11, 12, ff — 11/12/ff rejected.

## 5. Session management

- `libusb_reset_device()` + fresh open/claim fully recovers the device state
  without replug. Old cursor state survives until reset.
- Device re-enumerates on reset (address changes); re-open from scratch.
- set_configuration(1) returns LIBUSB_ERROR_BUSY (-6) but claim_interface(0)
  succeeds — safe to ignore the busy error.

## 6. Toolchain notes

- Reference reader: `dumpall.py` (Python ctypes + libusb-1.0.so.0, no
  compiler headers needed). System python3.10 works; linuxbrew python3.14
  lacks libudev and cannot load libusb.
- ctypes binding gotchas:
  - Do NOT `libusb_free_device_list` before `libusb_open` (open takes its
    own reference; freeing first = SIGSEGV).
  - Device descriptor must be read via a proper `Desc` STRUCTURE with
    `byref()`; a raw ubyte array segfaults.
  - `idVendor` is little-endian in the raw bytes: 07b4 = bytes B4 07.
- `cmdscan.py` sweeps the full 2-byte command space with reset between
  probes; output in `cmdscan.txt`/`cmdscan.log`.

## 7. Open questions — path to file download

The .dss recording bytes are NOT in the 17-page info object (page 8 dword
is too small for a real recording; likely metadata size). Hypotheses:

1. File data is read via a different command family (0x50+ range retested
   negative; maybe 3-byte or longer commands, or commands not in 0x00–0xff).
2. Or via `0x40` with a 2-byte arg selecting file number (e.g. `40 02 00`).
3. DSX API surface (from DSXUSB.DLL static analysis, see DS-330_NOTES.md):
   GetFileNum, GetFileInfoFirst/Next, OpenFile(UP), ReadFile, WriteFile,
   SetHeaderInfo, GetEncodeData(Ex), GetLogicalSector, GetPhisicalSector,
   GetMemorySize, GetRecoderInfo, SetPCTime, DeleteFile, StartFirmwareUpdate.
   The wire protocol must map onto these; the IOCTL codes are known
   (0x98ff2004–0x98ff20a4) but the IOCTL→wire mapping is not offset-4.

## 8. Mapping to DSX API (semantic reference)

| DSX API | likely wire command | confidence |
|---------|--------------------|------------|
| GetDeviceInfo | 0x78 / 0xb2 | medium |
| GetMemorySize | 0x79 | low |
| GetFileInfoFirst/Next | 0x40 stream | high |
| GetFileNum | 0x47 | low |
| GetFolderName | 0x95 | medium |
| GetRecoderInfo | 0xc0 | low |
| SetPCTime | ? | none |
| DeleteFile | ? | none |
| OpenFile/ReadFile | ? | none — main blocker |

### 0x47 — new discoveries (2026-11-20 continued)
- `47 01` → 41 zeros (counter/status, previously known)
- `47 02` → `00 00 00 00 "DICTATE" 00...` — device mode/folder name!
  This is likely GetFolderName or GetDeviceInfo string field.
- `47 03` and higher: untested.
- `47 01 02` (3-byte form) → also responds with zeros (same as 47 01).

### 0x47 02 discovery analysis
The string "DICTATE" is significant: it matches the Olympus dictation
software's "Dictation Module" terminology. This is likely a folder name
or device mode identifier. The 4 leading zero bytes before "DICTATE" are
likely a size/type field.

### 0x47 — folder names discovered (2026-11-20 continued)
- `47 02` → `00 00 00 00 "DICTATE" 00...` — folder 1 name
- `47 03` → `00 00 00 00 "LECTURE " 00...` — folder 2 name
- `47 04` → `00 00 00 00 "TO DO   " 00...` — folder 3 name
- `47 05` → `00 00 00 00 "RANDOM  " 00...` — folder 4 name
- `47 01` → 41 zeros (folder 0? or GetFileNum return=0)
- Format: 4 zero bytes (likely count/index) + 8-byte ASCII name + zero pad
- This maps to DSXGetFolderName/SetFolderName in the DSX API.
- The recorder has default folders DICTATE/LECTURE/TO DO/RANDOM.
- `47 06` and higher: untested, could return more folders or file counts.

### Updated 0x47 mapping
- `47 01` = GetFileNum (file count in current folder = 0? or folder 0)
- `47 NN` = GetFolderName(NN-2) → returns folder name for index NN-2

### File data hypothesis update
File data is likely accessed via a sequence: select folder (0x47 XX),
then select file (0x40 arg?), then read data pages. Or via dedicated
OpenFile/ReadFile commands in the 0x48+ range.

### 0x47 folder name mapping (2026-11-20)
- 0x47 02 = DICTATE, 0x47 03 = LECTURE, 0x47 04 = TO DO, 0x47 05 = RANDOM
- 0x47 06+ rejected. 0x47 01 = 41 zero bytes.
- Folder selection via 0x47 does NOT change 0x40 stream content.
- 0x48/0x49/0x4a all rejected. 0x47 01 02 = same as 0x47 01 (3-byte ignored).
- The 0x40 stream always returns the same 17-page info object regardless
  of folder selection. File data must use a completely different path.

### Arg-0x00 scan results (2026-11-20, second full sweep)
Full 2-byte scan with arg=0x00, reset between each probe:
- 0x47 00 → 41 zero bytes (same as 0x47 01)
- 0x78 00 → 42 bytes: `8f 14 0c ff 00 ff dd 46 53 96 ae ac 55 89 86 4d 47 41
  84 77 af 25 40 0c` — NOT the same as the earlier 0x78 (no arg) version
  string! Different content with arg 0x00 vs single-byte.
- 0x79 00 → all zeros (16 bytes)
- 0x95 00 → `"JSMYTHE"` + zeros (device label)
- 0xb2 00 → `"DS-330    JSMYTHE"` (model + label)
- 0xb3 00 → `10 00 ...` (16)
- 0xc0 00 → `ca 65 61 5d 9a 8e 40 4e 24 74 28 cc 7f c7 e0 05 de 35 21 74
  92 46 3e ed` — different from earlier c0 result! Non-deterministic or
  one-shot per enumeration.
- 0xd1 00 → `00 c0 d0 00 00...` (same as before)
- ALL OTHER COMMANDS (0x00-0xff): no response (timeout)

### Updated conclusions
- The device has a small number of info/status commands (0x47, 0x78, 0x79,
  0x95, 0xb2, 0xb3, 0xc0, 0xd1) and ONE data-stream command (0x40).
- The 0x40 stream returns 17 pages = the file info table. This object
  contains ONLY metadata (file name, date, folder, size dword). The actual
  .dss recording bytes are NOT accessible via any tested 2-byte command.
- The file data likely lives in flash sectors that require either:
  1. A 3+ byte command to address the sector (untested)
  2. A different interface/endpoint
  3. A higher-level protocol session state that we haven't discovered
  4. Being stored in a different USB interface (the audio interfaces 1-4
     may provide DMA access to the same flash via the isochronous endpoints)

### 0xc0 non-determinism note
0xc0 00 returned different content on two separate sessions (first: 26-byte
calibration-looking blob, second: 26-byte different blob). This command may
be one-shot per enumeration or returns rolling data.
