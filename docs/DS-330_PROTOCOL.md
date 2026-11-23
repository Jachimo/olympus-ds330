# Olympus DS-330 USB Protocol — Reverse Engineering Notes

**Device:** Olympus DS-330 digital voice recorder (ca. 2002)  
**USB ID:** 07b4:0206 (vendor Olympus, "DIGITAL VOICE RECORDER DS-330")  
**USB version:** 1.10, bus-powered, full-speed. Display shows "REMOTE" when
connected and idle.  
**See DS-330_NOTES.md for the wider project log.** This document is the
protocol reference.  
Status: **COMPLETE** — download, clock-set, and full file-table
enumeration all work end-to-end from Linux (`src/ds330tool.py`).  
Last updated: 2026-11-22.  

---

## 1. USB device structure

5 interfaces in configuration 1:

| If | Purpose | Endpoints |
|----|---------|-----------|
| 0 | **Vendor-specific — file transfer / control** | Bulk OUT 0x02 (commands), Bulk IN 0x81 (data), Interrupt IN 0x83 (status) |
| 1–4 | Standard USB Audio (UAC1) mic + speaker PCM paths | ISO, 8/11.025/16/22.05 kHz 16-bit mono |

Interface 0 is not claimed by any kernel driver (as of Nov 2026), so the libusb
extractor doesn't specifically unbind. 

The audio interfaces are irrelevant to file extraction, and aren't especially
impressive by modern standards.  But if you wanted to use them... they're there.

Endpoint max packet size: 64 bytes (full-speed, bulk).

## 2. Frame model

These commands target **interface 0** only. The pattern:

1. **Command:** BULK OUT 0x02, 1–14 bytes: `[cmd][arg...]`, zero-padded
to a full 64-byte page (the device inspects only the leading bytes).
   Commands are 1–2 bytes for most queries, but 3 bytes for the
   open-file frame (`18 <folder> <file>`) and 13 bytes for clock set
   (`90` + 12 ASCII digits).
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

### 0x40 / 0x41 — file info: first/next per folder (CONFIRMED, REVISED 2026-11-22)
- `40 NN` → returns the FIRST file's 17-page (1088-byte) info object of
  folder NN (1–5 = A–E). Each bulk_in returns the next page; the page
  cursor auto-advances. A 3-byte `40 NN <byte>` form behaves the same
  (third byte ignored); other args return no data.
- `41 NN` → returns the NEXT file's info object of folder NN, advancing a
  per-session cursor; an empty data stage means the folder is exhausted.
  (With exactly one file on device, `41 01` returning no data made it
  look like a mere "flush" in the original player capture.)
- Enumeration per folder: `40 NN`, then repeat `41 NN` until empty. The
  cursor resets on USB reconnect. Must run before the label/memory
  queries (§9.7 ordering).
- Verified live (3 files, folders A and E): `40 01` → file 1's object,
  `40 05` → the RANDOM folder's first file, `41 05` → its second file,
  a further `41 05` → empty.
- Contents of the 17-page object (per file, example "<RECORDING-NAME>"):
  - page 0: file header: `"<RECORDING-NAME>"` (name), `02 64 73 73 01 00 01 00 02 00
    00 00` (dss magic), `"<USER-LABEL>"` (label), date digits from offset
    0x2F: `020101000105020101002412002306` (30 ASCII digits; see §3.1)
  - page 1: date continuation + `ff 07 ff` padding
  - pages 2–7: FF fill (erased slots)
  - page 8: dword `90 27 15 00` (LE 0x00152790 = 1,386,384) — a
    flash-region/metadata size, NOT the file size (it is ~58% of the
    DSS file size — likely the compressed-audio payload length)
  - pages 9–16: zeros/FF
- This object is the same data that command `00` primes (older C-based dump
  read 32 pages via `00`; the file header was at page 15 of that dump).

### 3.1 File-info date digits (SOLVED 2026-11-22)
Object offsets 0x2F–0x4C hold 30 ASCII digits (an earlier read started at
0x30 and silently dropped the first digit):

    digits[0:12]   record start, YYMMDDHHMMSS
    digits[12:24]  record stop,  YYMMDDHHMMSS
    digits[24:30]  duration,      HHMMSS

On the reference recording: start 2002-01-01 00:01:05, stop 2002-01-01
00:24:12, duration 00:23:06. stop − start tracks the duration (the
duration field runs one second short). A recorder with an unset clock
stamps files with its power-on default (observed: 2002-01-01).
Decoder: `decode_date_digits()` in src/ds330tool.py (unit-tested against
the live capture in tests/data/fileinfo.bin).

### 0x47 — status/counter (CONFIRMED)
- `47 01` → 41 bytes: dword 1 + zeros. GetFileNum-like; the dword is 1
  even with zero or three files, so its semantics are unclear.
- `47 01` doubles as folder A's scan entry (folder A has no readable
  name; `47 02..05` are folders B–E). Does NOT redirect the 0x40 stream
  to file data (tested).

### 0x95 — device label (CONFIRMED)
- `95 01` → `"<USER-LABEL>"` (16 bytes, zero-padded). The recorder's user label.

### 0xb2 — device identity (CONFIRMED)
- `b2 01` → `"DS-330    <USER-LABEL>"` (model name + user label, zero-padded).

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

## 4. Commands that do NOT work

All tested on fresh state (device reset between each), `out=0 in=-7`:

- `0x7b` flash-sector read: 1-byte args (00,01,02,03,10,20), 4-byte LE args
  (0,1,2), and single-byte — all rejected. NOT the sector path on this FW.
- `0x42`, `0x43`, `0x44`, `0x45`, `0x46`, `0x30`, `0x33` with `01`
  arg — rejected. (0x40 and 0x41 were on the original rejected list but
  are now CONFIRMED working as the folder-scoped first/next file-info
  pair — see §3; the original probe only ever got an empty response
  because the device held no recordings at probe time.)
- `0x50`, `0x48`, `0x51`, `0x52` with 1-byte and 4-byte args — rejected.
  The DLL IOCTL→wire mapping is NOT a simple offset-4 correspondence.
- `0x40` with args 06–10, 11, 12, 20, 40, 81, ff — no data returned
  (only 01–05, the folder selectors, produce the info object).

## 5. Session management

- `libusb_reset_device()` + fresh open/claim fully recovers the device state
  without replug. Old cursor state survives until reset.
- Device re-enumerates on reset (address changes); re-open from scratch.
- set_configuration(1) returns LIBUSB_ERROR_BUSY (-6) but claim_interface(0)
  succeeds — safe to ignore the busy error.

## 6. Toolchain notes

- Reference tool: `src/ds330tool.py` (Python ctypes + libusb-1.0.so.0,
  stdlib only). System python3.10 works directly. Linuxbrew python3.14
  also works since 2026-11-22: its private glibc cannot resolve the
  libusb soname or libusb's libudev dependency, so the tool pre-loads
  the system libudev by absolute path (RTLD_GLOBAL) and then opens
  libusb by absolute path as a fallback.
- ctypes binding gotchas:
  - Do NOT `libusb_free_device_list` before `libusb_open` (open takes
    its own reference; freeing first = SIGSEGV).
  - The 18-byte USB device descriptor can be read into a plain ubyte
    buffer and parsed with `struct.unpack("<BBHBBBBHHHBBBB")` — a
    ctypes Structure with `_pack_` also works but is deprecated on
    python 3.14+ (packed-layout deprecation).
  - Descriptor fields are little-endian: idVendor 07b4 = bytes B4 07.
- `cmdscan.py` sweeps the full 2-byte command space with reset between
  probes; output kept on the internal branch).

## 7. Open questions (historical — main questions solved)

The .dss recording bytes are NOT in the 17-page info object (page 8 dword
is a metadata size, not the audio). SOLVED (2026-11-21): the data path is
the 3-byte `18 <folder> <file>` open + `80 00` data phase (§9.4),
confirmed by usbmon capture of the real player. The earlier hypotheses
are kept for history:

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

| DSX API | wire command | confidence |
|---------|--------------|------------|
| GetDeviceInfo / ConectConfirm | `b2 00` (model + label) | confirmed |
| GetRecoderInfo / capability table | `78` | confirmed (content undecoded) |
| GetMemorySize | `79` | low |
| GetFileNum | `47 01` (dword is 1 regardless — semantics unclear) | low |
| GetFolderName | `47 02..05` (folders B–E; user-settable names) | confirmed |
| GetFileInfoFirst | `40 NN` (first file of folder NN) | confirmed |
| GetFileInfoNext | `41 NN` (next file; empty = exhausted) | confirmed |
| OpenFile/ReadFile | `18 <folder> <file>` + `80 00` data phase | confirmed |
| SetPCTime | `90` + YYMMDDHHMMSS ASCII | confirmed |
| DeleteFile | `A0 <folder> <file WORD x2>` (§9.9) | confirmed |
| SetFolderName | ? | none — future work |

### 0x47 — new discoveries (2026-11-20; numbering corrected 2026-11-22)
- `47 01` → 41 bytes: dword 1 + zeros (counter/status, previously known)
- `47 02` → `00 00 00 00 "DICTATE" 00...` — a folder NAME (user-set
  label; folders B–E via args 02–05; see below)
- `47 03..05` → the other folder names (LECTURE / TO DO / RANDOM on
  this device); `47 06+` rejected
- `47 01 02` (3-byte form) → also responds with zeros (same as 47 01)

### 0x47 02 discovery analysis
CORRECTED (2026-11-22): the string "DICTATE" is NOT intrinsically
significant — it is just a folder label the user of this particular
device set at some point (folder names are user-settable; see below).
Any resemblance to the dictation software's "Dictation Module"
terminology is coincidental. The labels matter to the user's own
organization, not to the software. The 4 leading zero bytes are a
count/index field.

### 0x47 — folder names discovered (2026-11-20 continued; numbering corrected 2026-11-22)
- `47 02` → `00 00 00 00 "DICTATE" 00...` — folder B's name
- `47 03` → `00 00 00 00 "LECTURE " 00...` — folder C's name
- `47 04` → `00 00 00 00 "TO DO   " 00...` — folder D's name
- `47 05` → `00 00 00 00 "RANDOM  " 00...` — folder E's name
- `47 01` → 41 bytes: dword 1 + zeros (folder A's scan entry; A exposes
  no readable name)
- Format: 4 zero bytes (count/index) + 8-byte ASCII name + zero pad
- This maps to DSXGetFolderName/SetFolderName in the DSX API.
- The recorder's folder names are USER-SETTABLE per device (the
  Windows software can rename them); DICTATE/LECTURE/TO DO/RANDOM are
  this device's values, not constants. Always read names via
  `47 02..05`; never hardcode name->folder mappings in tooling.
- `47 06` and higher: rejected (only 5 folders, A–E).

### Updated 0x47 mapping (superseded by §3 and §9.7)
- `47 01` = GetFileNum-like counter (dword 1 even with 0 or 3 files;
  semantics unclear) + folder A's scan entry
- `47 NN` = GetFolderName for folder NN (folders 2–5 = B–E named;
  folder 1 = A returns the counter)

### File data hypothesis update (SUPERSEDED — solved via `18`/`80`)
Historical hypothesis (2026-11-20): file data accessed by select
folder (0x47) then select file (0x40 arg) then read data pages, or a
dedicated command in the 0x48+ range. Reality (2026-11-21): the
`18 <folder> <file>` open + `80 00` data phase (§9.4); the 0x48+ range
is rejected, and 0x40/0x41 are metadata-only (§9.3).

### 0x47 folder name mapping (2026-11-20)
- 0x47 02..05 = this device's folder names for folders B–E; user-set
  values, not constants (this device: B=DICTATE, C=LECTURE, D=TO DO,
  E=RANDOM).
- 0x47 06+ rejected. 0x47 01 = 41 zero bytes.
- Folder selection via 0x47 does NOT change 0x40 stream content.
- 0x48/0x49/0x4a all rejected. 0x47 01 02 = same as 0x47 01 (3-byte ignored).
- SUPERSEDED (2026-11-22): the 0x40 stream IS folder-scoped (`40 NN` =
  first file of folder NN) — the 2026-11-20 probes only ever saw the
  folder-A object because `40 01` was the only form tried. File data
  itself uses the `18 <folder> <file>` / `80 00` path (§9.4).

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

### Updated conclusions (superseded by the §9 capture analysis)
- The device has a small number of info/status commands (0x47, 0x78, 0x79,
  0x95, 0xb2, 0xb3, 0xc0, 0xd1) and a folder-scoped info stream (0x40/0x41).
- The 0x40 stream returns 17 pages = one file's metadata (name, date,
  folder, size dword). The actual .dss recording bytes are NOT accessible
  via any tested 2-byte command.
- SOLVED LATER (2026-11-21/22): file data uses the 3-byte
  `18 <folder> <file>` open + `80 00` data phase (§9.4); the file table
  is `40 NN`/`41 NN` first/next (§9.3). The hypotheses below are obsolete.
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

### 0x93 file-read command (2026-11-20, from DSXUSB.SYS + DSXUSB.DLL analysis)

Confirmed wire frame for the file-data read path:

```
BULK OUT 0x02:  93 <mode> <count_lo> <count_hi>
```

Modes (from DsXIoctlOpenDSSFileUp, SYS:0x1167e, IOCTL 0x98ff2070):
- mode 0 -> count 0x0144 (324 bytes)
- mode 1 -> count 0x001c (28 bytes)
- mode 2 -> count 0x00c9 (201 bytes)
- mode 3 -> count 0x0144 (324 bytes)

DLL side (DSXDownloadDataBase at 0x100031e0) confirms: it allocates a
325-byte stack buffer, writes ONLY buffer[0] = mode byte, and passes it
to IOCTL 0x98ff2070. The kernel driver builds the actual 4-byte wire
frame from the mode byte. On success the DLL calls 0x10003e20 (status
drain) then 0x10003d70 (data read into caller buffer) — and it requires
the status drain to return 2 before reading data.

Probe result (probe93.py, mode 0, cold session):
- OUT 93 00 44 01 -> accepted (sent=4)
- INT status: ffff000001000000  = REJECTED
- Bulk IN: timeout (r=-7), 0 bytes

Conclusion: the 4-byte 93 frame is the correct wire format, but the
device rejects it from a cold session. A session-state prerequisite is
required — likely an init/handshake sequence (possibly the 0xc0 command,
which is non-deterministic and may be a session seed exchange) or a
prior file-select command. The real DSS Player performs this sequence
before every download.

## Caller-Side Sequencing (see docs/DICTWND_ANALYSIS.md)

DictWnd.exe resolves all 32 DSXUSB exports and drives the download:
InitUSBPort -> ConectConfirm -> GetFileNum -> GetFileInfoFirst/Next ->
OpenFile/ReadFile per file.

## 9. COMPLETE CONFIRMED SEQUENCES (from usbmon capture)

Captured 2026-11-21 from a Windows VM running the real DSS Player with
usbmon on the host (pcap files kept on the internal branch; decode
script `src/parse_pcap.py`). All commands are sent as full 64-byte
bulk-OUT pages (zero-padded).

### 9.1 Connect / init handshake
| Frame | Response (INT 0x83) | Data (0x81) | Meaning |
|-------|--------------------|-------------|---------|
| `f0 00` | `06..01` | 1 page | InitUSBPort |
| `b2 00` | `06..01` | 1 page `"DS-330  <label>"` | ConectConfirm / GetDeviceInfo |

### 9.2 Folder scan (warmup before file operations — REQUIRED)
`47 01` -> 1 page (status/GetFileNum-ish, `01 00 00 00 ...`; folder A's
scan entry — A exposes no readable name)
`47 02` -> 1 page `00*4 + "DICTATE"` (folder B's name; user-set)
`47 03` -> `"LECTURE "` (folder C)
`47 04` -> `"TO DO   "` (folder D)
`47 05` -> `"RANDOM  "` (folder E)
Skipping this warmup makes the device reject the file-open command.

### 9.3 File info (REVISED 2026-11-22: folder-scoped first/next)
`40 NN` -> 17-page (1088 B) info object for the FIRST file of folder NN
(see §3). Response page 0 carries the file header (name/dss magic/label/
date), page 8 offset +0x09 carries a flash-region dword (NOT the file
size; roughly 58% of the DSS size — the compressed-audio payload).
`41 NN` -> the NEXT file's info object of folder NN; empty data stage
when the folder is exhausted. (In the original player capture the device
held exactly one file, so `41 01` looked like a no-data flush; the
player in fact uses it to walk the file list — GetFileInfoFirst/Next in
the DSX API.) Full file table: `40 NN`, repeat `41 NN` until empty,
per folder 1–5. Cursor is per-session; enumerate BEFORE the label/
memory queries (§9.7).

### 9.4 File download (the money sequence)
| Frame | Notes |
|-------|-------|
| `18 01 01` | OpenFile — **`18 <folder> <file>`**: second byte is the folder (01–05 = device folders A–E), third byte is the 1-based file within it. Response page `00 96 24 00 ...` |
| `80 00` | Data phase start. Then bulk-in pages stream until timeout. |

`18 01 01` — NOT `18 01 00`: both selector bytes are required; sending
`18 01` (two bytes) is rejected.

Folder model (established live, 2026-11-22): folders 1–5 = A–E.
`47 02..05` return the names of folders B–E (names are user-settable per
device — DICTATE/LECTURE/TO DO/RANDOM are this device's values);
`47 01` is folder A's query (status/zeros — no name readable for A).
Setting folder names is NOT yet decoded (the Windows software can do it).
An `18 <folder> <file>` pointing at a nonexistent file yields an empty
data stream (no error). Verified with recordings in A and E:
`18 05 01`/`18 05 02` download both RANDOM-folder files, `18 02 01`
(empty folder) returns an empty stream.

### 9.5 Data-phase stream layout (verified byte-for-byte)
The `80 00` data stream is NOT the same layout as the old probe-era
full-session stream. It is:
```
stream[0:2]      preamble (2 bytes) — discard
stream[2:514]    dss[0:512]
then repeating:  64-byte frame (discard) + 512 bytes of dss
                 (period 576 bytes), i.e. next dss chunk at 578, 1154, 1720...
stream tail       folder-name table — discard
```
Single fixup: dss[792] = 0xFE (flag byte the player sets; stream carries
0xFF). Extractor: `extract_dss()` in `src/ds330tool.py` (implements the
data-phase layout above; unit-tested against a real captured stream in
`tests/data/`). The legacy `src/extract_dss.py` offsets apply only to
full player-session captures with their 393-byte preamble.

### 9.6 Clock set (SetPCTime)
```
90 <12 ASCII digits YYMMDDHHMMSS>
```
e.g. captured frame `90 32 36 31 31 32 32 30 32 31 32 31 37` =
`0x90` + `"261122021217"` = 2026-11-22 02:12:17. Response: accepted status.

### 9.9 File delete (decoded 2026-11-23 from DSXUSB.SYS, live-verified)
```
A0 <folder 1-5> <file WORD LE> <file WORD LE>
```
- 6-byte frame; the two WORDs carry the same 1-based file index (the
  device's duplicated-data pattern). Accepted with no data stage.
- Deleting a nonexistent file is silently accepted (no error).
- **The device wedges briefly after a successful delete** (observed
  live): the next frame times out until a reset — reset+re-open right
  after deleting.
- Verified live: deleting RANDOM's file 2 then file 1; the file table
  re-enumerates correctly and remaining files still download.

### 9.7 Session management notes (live-tested)
- The device rejects `18 <folder> <file>` (file open) unless the §9.1+§9.2
  init/warmup ran first in the same session.
- **Query order matters (2026-11-22):** the device stops answering
  `40 NN`/`41 NN` after a `95 00` (label) or `79 00` (memory) query in
  the same session — always enumerate the file table before those.
  The tool's `info()` does.
- **Wedge behavior (2026-11-22):** a stale session produces transfer
  failures (bulk OUT timeout, interrupt status timeouts); a device reset
  plus retry fixes it. A wedged device can take >2 s to answer a frame
  (observed up to ~5 s) — use a generous timeout for the interrupt
  status (the tool uses 8 s). Data-stage pages, by contrast, arrive
  back-to-back or not at all — a 1 s timeout there is correct and keeps
  `info` fast.
- `libusb_reset_device()` + fresh open fully recovers any wedged state.
- `set_configuration(1)` returns BUSY (-6); ignore.
- The 0x40/0x41 enumeration cursor is per-session and resets on USB
  reconnect (fresh session starts at each folder's first file).

## Raw stream → DSS extraction (SOLVED, 2026-11-21)

The bulk-in stream captured during a player download is the DSS file with
insertions. The `80 00` **data-phase** layout (what `DS330.download_raw`
returns, verified byte-for-byte against the player's own output for the same recording):

    stream[0:2]          preamble — discard
    stream[2:514]        dss[0:512]
    then repeating:      64-byte frame (discard) + 512 bytes dss
                         (next dss chunk at 578, 1154, 1720, ... period 576)

Single fixup: dss[792] = 0xFE (player sets it; stream carries 0xFF).

Extractor: `src/ds330tool.py` `extract_dss()` — used by `ds330tool download`;
output verified byte-identical to the player's output for the same recording; ffmpeg converts
it (`ffmpeg -i out.dss out.wav` → 11.025 kHz mono, 23:03 duration, DSS-SP
codec). `src/extract_dss.py` keeps the legacy FULL-SESSION layout (393-byte
preamble; applies only to captures that include the pre-`80 00` traffic).

**NOTE:** The `93 <mode> <count>` frames in the 0x93 section are DSXUSB.SYS
URB-level encodings from static analysis; the actual device wire protocol is
the `18 01 01` / `80 00` sequence in §9.4, confirmed by capture. The 0x93
path was superseded.
