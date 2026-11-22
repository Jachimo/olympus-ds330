# Olympus DS-330 — Software Survey Notes (2026)

Device: Olympus DS-330 digital voice recorder (~2001-2003), 2x AAA, mini-USB,
no removable media, records DSS (Digital Speech Standard) format files.
Goal: get recordings off the device and convert DSS -> WAV/MP3, preferring
Linux / CLI tools.

## The two problems

1. **USB download**: early Olympus DS-series recorders predate USB mass
   storage. The DS-330 does NOT mount as a USB drive; it uses a proprietary
   Olympus USB protocol (Olympus vendor ID `07b4`) that only Olympus's
   "DSS Player" software spoke. This is the hard part.
2. **DSS decode/conversion**: DSS files are a proprietary container with an
   embedded codec (DSS-SP, a CELP-family speech codec). This part is now
   well-solved by open source.

## DSS file conversion (problem 2) — SOLVED on Linux

| Tool | Lang | What it does | Status (2026) |
|---|---|---|---|
| FFmpeg (`dss_sp` decoder + `dss` demuxer) | C | `ffmpeg -i file.dss file.wav` / pipe to `libmp3lame` for MP3 | Long-supported in mainline; DS2 (.ds2 / DSS Pro) support merged via FFmpeg PRs #25689/#25881 (~2023-2024) |
| https://github.com/hirparak/dss-codec | Rust | Open-source decoder for DSS/DS2, CLI `dss-decode` -> WAV; MIT. 25 stars, active 2026 | Active |
| https://github.com/IACBI/DS2_To_Mp3_Converter | Python | Native Python decoder, DSS/DS2 -> MP3/WAV without FFmpeg | Active (pushed 2026-11) |
| https://github.com/Guillain-RDCDE/DS2-Anywhere | JS/Rust/WASM | Opens Olympus/Grundig dictation files anywhere; work being upstreamed into FFmpeg; MIT | Very active (2026-11) |
| https://github.com/robrawks/ds2-converter | JS | DS2/DSS -> WAV/MP3 batch converter (browser app + headless CLI) | Active mid-2026 |
| https://github.com/Paxtez/dss_decode_gui | Python | Drag-and-drop GUI, DSS/DS2 -> WAV | New (2026-09) |
| https://github.com/arkane-systems/arkane-fileproperties-dss | C# | Library that parses DSS file headers only (no audio decode) | Maintained |

Notes:
- The DS-330 records classic `.dss` (DSS v1, SP/LP modes, DSS-SP codec),
  which FFmpeg has decoded for years — the newer DS2 work only matters for
  later recorders (DS-4000 and up, `.ds2` / DSS Pro).
- Practical one-liner: `ffmpeg -i recording.dss -acodec libmp3lame recording.mp3`

## USB download (problem 1) — the hard part

- No official Linux support from Olympus, ever. Official path was
  DSS Player / DSS Player Lite on Windows/macOS.
- GitHub search for DS-330-specific download tooling: nothing relevant
  (all "DS330" repos are university course repos, unrelated).
- The device enumerates under Olympus vendor ID `07b4` and does not expose
  mass storage, so `lsblk`/`dmesg` will show a device but no mountable
  volume.
- **Wine is the standard community workaround** for getting DSS Player Lite
  to run on Linux; libusb passthrough of Olympus devices through Wine is
  generally reported workable for older devices. (Verifying details —
  pending web research.)
- Analog fallback that always works: the DS-330 has a 3.5mm earphone jack,
  so any recording can be extracted by line-in playback on any machine,
  though that loses the original file timestamps and adds a generation.

## Leads to verify / pending research

- Whether anyone has reverse-engineered the Olympus USB protocol
  (search terms tried: "olympus dss linux usb download", "ds330 linux",
  vendor ID 07b4, SourceForge "odsstools").
  - [The "odsstools"
    project](https://sourceforge.net/projects/odsstools/) shows last
    activity in 2007 and contains one file, "dsstimescript.tar.bz2",
    which is just a trivial file-renaming utility. No real conversion
    or parsing of the DSS file format.
- Wine + DSS Player Lite reports for Linux.
- Whether later Olympus DS models that DO support USB mass storage (or the
  DM series) are a firmware-comparable alternative — not relevant to
  extracting from this specific unit, but context.

---

## USB enumeration data (captured 2026-11-19, device connected, display = "REMOTE")

`lsusb`: `Bus 002 Device 011: ID 07b4:0206 Olympus Optical Co., Ltd Digital
Voice Recorder DS-330`

Confirmed:
- Runs on USB bus power, works with NO batteries installed.
- USB 1.10, bus-powered, MaxPower 500mA.
- bDeviceClass 0 (per-interface classes), bMaxPacketSize0 = 32.
- iManufacturer "OLYMPUS OPTICAL CO.,LTD.", iProduct "DIGITAL VOICE
  RECORDER DS-330", no serial number string.
- ONE configuration, FIVE interfaces. Nothing binds a storage driver —
  interface 0 stays unclaimed (no kernel driver attaches), audio interfaces
  are handled by snd-usb-audio (ALSA).

### Interface map

| If | Class | Purpose | Endpoints |
|----|-------|---------|-----------|
| 0 | 0xFF vendor-specific (ff/ff/ff) | **The file-transfer/command channel** | EP 0x81 Bulk IN (64B), EP 0x02 Bulk OUT (64B), EP 0x83 Interrupt IN (8B, interval 50ms) |
| 1 | Audio Control | Mic input terminal (recording path) | none |
| 2 | Audio Streaming | Mic -> PC (PCM isochronous, alt 1) | EP 0x84 ISO IN, 8/11.025/16/22.05 kHz, 16-bit mono |
| 3 | Audio Control | Speaker output terminal (playback path) | none |
| 4 | Audio Streaming | PC -> speaker (PCM isochronous, alt 1) | EP 0x05 ISO OUT, same 4 sample rates |

Key deductions:
- Interface 0 (vendor-specific, bulk pair + status interrupt) is almost
  certainly the DSS Player download channel: bulk OUT = commands, bulk IN =
  responses/file data, interrupt IN = event/status notifications.
- The recorder also exposes a plain USB Audio (UAC1) microphone and speaker
  — this is the "USB microphone / audio playback" mode. The DISPLAY SHOWING
  "REMOTE" indicates the device has entered its PC-link command mode, i.e.
  it is already listening on interface 0's bulk endpoints.
- Because interface 0 is unclaimed by any kernel driver, userspace can
  claim it directly via libusb (no driver unbinding needed). The audio
  interfaces are separately usable (ALSA: appears as a USB audio device for
  live monitoring / analog-free PCM capture of the mic).
- STIPULATED OUT OF SCOPE (user decision): analog 3.5mm jack capture and
  USB-audio PCM capture are 1x-realtime re-recording routes; they lose
  original files/timestamps and make the device effectively useless. NOT
  investigating further. The only acceptable solution is the proprietary
  bulk protocol (interface 0) delivering original .dss files.

### Next steps (reverse-engineering plan)

1. Install Wine + DSS Player Lite (free download from OM System), or use a
   Windows VM — only as a protocol oracle.
2. Load usbmon, capture Bus 002 traffic while DSS Player performs:
   device open, file listing, one file download, (optionally) erase.
3. Decode the command set from the capture; expect simple fixed-length
   command frames on EP 0x02 with responses on EP 0x81, and possibly
   status/notify frames on EP 0x83.
4. Implement a native extractor (Go or Python + libusb/usb.core) claiming
   interface 0 only, leaving audio interfaces untouched.

---

## Serial number hunt (2026-11-19)

- Windows DSS Player 2002 installer (from archive.org ISO) demands a serial
  number. Serials embedded in the ISO scripts: RD31732, RDX4681, R2K1019,
  RFP4926, RDP8393 (root menu product picker) — ALL REJECTED by the installer
  ("Illegal license number!!"). The check bytecode shows: length must be 7,
  then three extraction/compare checks (==0, <=9,999,999, ==1) — an
  algorithmic checksum, not a literal table.
- History (user): recorder obtained USED in 2005, no software included.
  Software was DOWNLOADED from Olympus website (Mac version, user was
  Mac-only then). Unknown whether Mac version needed a serial at all.
- DiskTracker DB (~/Documents/Databases/DiskTracker DB.sqlite) surveyed:
  - Vol 13 'jsmythe' (CD, mounted 2026-11-19): Mac DSS Player prefs all
    EMPTY (DSS Preference, DSS Preferences = 0 bytes; plists = only Finder
    dialog positions). NO serial stored.
  - Vol 20 '080724 Misc Files' (CD): UNREADABLE. Held Mac DSS Player Lite
    .sit files. If readable it would give the free Lite player (Lite may
    not require a serial) — re-try this disc when possible.
  - Vol 82 'jsmythe' (encrypted image on disc jsmythe-071003): same prefs,
    probably same empty result.
  - Vol 193 'Hotswap A' (HD): burn staging copies of same .sit files.
- CONCLUSION: no serial number ever existed for the Mac download (free
  player). The Windows installer's serial demand is a dead end for license
  recovery; the WIN32 installer may accept a dummy if the check can be
  bypassed, OR use DSS Player Lite for Windows (free, no serial historically),
  OR skip Windows entirely.

## NEW STRATEGY - skip Windows DSS Player entirely

The DSX USB driver API (DSXUSB.DLL exports: DSXGetFileNum, DSXGetFileInfoFirst/
Next, DSXOpenFile, DSXReadFile, DSXGetFolderName, DSXGetMemorySize, etc.) is
known. The protocol can be captured WITHOUT a licensed player:

Option A: run DSS Player Lite (Windows) under Wine - free download, no
serial historically. If it supports DS-330 download, sniff that.
Option B: capture the protocol from the MAC DSS Player the user already had?
Mac used different USB stack; not helpful for libusb capture. BUT the user's
Mac DSS Player worked with this recorder - meaning the DSX protocol is
implementable from any host.
Option C: reverse the DSXUSB.SYS/.DLL command framing directly (we have the
binaries; the IOCTL set maps 1:1 to the DSX* functions).
Option D: brute-force the USB command set with libusb from Linux directly:
simple command/response protocol likely; try known Olympus command bytes.

## Olympus DS-series USB protocol - known knowledge (for Option D)

Community knowledge on Olympus DS series (DS-330/DS-150/DS-320): the devices
speak a simple command/response over bulk EPs. Related open-source work:
- gphoto2 has some Olympus support (mostly cameras, not voice recorders).
- The 'libnjb'-era devices and 'olympus' tools on SourceForge target cameras.
- No known open-source implementation of the DSX voice-recorder protocol.

Plan: load usbmon on bus 2, and either (A) sniff Wine+Lite doing a download,
or (D) probe the device directly with libusb: send candidate command frames
on EP 0x02, read responses on EP 0x81. The interrupt EP 0x83 likely signals
readiness/events.

---

## DSX driver static analysis (2026-11-19)

### Binary inventory
- DSXUSB.SYS (75,652 B, PE32 native, Win98/2000 kernel driver, built on
  BlueWater Systems WinDK 2.7 - a USB framework, not raw WDM)
- DSXUSB.DLL (73,728 B, PE32 user-mode wrapper: CreateFileA on \\.\DsX%d,
  DeviceIoControl per API call)
- DSXUSB.INF binds USB\VID_07B4&PID_0206&Mi_00 (interface 0 of our device)

### Full DSX API surface (32 exports, ordinals 1-32)
DSXBusReset, DSXCloseUSBPort, DSXConectConfirm, DSXDeleteFile,
DSXDownloadDataBase, DSXGetDeviceFreeSpace, DSXGetDeviceInfo,
DSXGetEncodeData, DSXGetEncodeDataEx, DSXGetFileInfoFirst,
DSXGetFileInfoNext, DSXGetFileNum, DSXGetFolderName, DSXGetLogicalSector,
DSXGetMemorySize, DSXGetPhisicalSector, DSXGetRecoderInfo, DSXInitUSBPort,
DSXOpenFile, DSXOpenFileUP, DSXReadFile, DSXSetCOMPower, DSXSetFolderName,
DSXSetHeaderInfo, DSXSetPCTime, DSXSetRecoderInfo, DSXStartFirmwareUpdate,
DSXStartPlayback, DSXStartRecording, DSXStop, DSXUploadDataBase, DSXWriteFile

### IOCTL map (DLL -> SYS; device 0x98ff, function codes 0x801-0x829)
Extracted from push-imm32 before each DeviceIoControl call in the DLL,
correlated with enclosing export:

  0x98ff2004  InitUSBPort
  0x98ff200c  ConectConfirm (also SetCOMPower)
  0x98ff2010  GetFileInfoFirst
  0x98ff2014  GetFileInfoNext
  0x98ff2020  GetEncodeDataEx
  0x98ff2030  SetPCTime
  0x98ff2034  DeleteFile
  0x98ff203c  GetEncodeData
  0x98ff2040  BusReset (variant)
  0x98ff2044  BusReset (variant)
  0x98ff2048  OpenFile
  0x98ff204c  WriteFile (also StartFirmwareUpdate)
  0x98ff2054  GetFileNum
  0x98ff2058  SetFolderName
  0x98ff205c  OpenFileUP
  0x98ff2060  GetRecoderInfo
  0x98ff2064  SetRecoderInfo
  0x98ff2070  DownloadDataBase
  0x98ff207c  GetDeviceFreeSpace
  0x98ff2084  BusReset (variant)
  0x98ff208c  GetMemorySize
  0x98ff209c  StartFirmwareUpdate
  0x98ff20a0  GetPhisicalSector
  0x98ff20a4  GetLogicalSector

### IOCTL request buffer shape (from DSXGetFileNum, DSXConectConfirm disasm)
- GetFileNum: 4-byte input buffer; first byte = argument & 0xff (folder idx?)
- ConectConfirm: 4-byte buffer, first byte = argument; response byte codes:
  returns 0xb normally; if arg==9 waits 1000 ms (Sleep 0x3e8) then 0xb;
  if arg==0xa returns 0xc
- Many commands: small (4-byte) in-buffer, response read after

### SYS-side structure
WinDK framework: URB context with URB function code at struct+0x2128.
URB functions used: 1 (x4), 2 (x3), 3, 4 (x5), 5 (x4), 9, a, d, 10, 40.
Named DsXIoctl* handlers (36 total) map 1:1 to the DSX API. Note
DsXIoctlGetDevData/SetDevData/GetLastStatus and the template URB blobs at
.sys+0x12022/0x12634 suggest the WinDK layer abstracts the USB transfer
construction; the actual wire bytes to the device are built inside the
CUsb class helpers (SelectConfiguration, GetConfiguration, etc).

### What this means for the Linux extractor
The Win98-era WinDK USB layer is thick; extracting exact wire bytes from
static analysis of the SYS is slow. FASTER PATH: the DLL user-mode layer
is thin (CreateFile/DeviceIoControl only), so the same DSX calls can be
made from Wine WITHOUT any driver - except the .SYS is still needed as the
USB transport on Windows...

DECISION: skip deep SYS reversing. Two viable paths:
1. Run the real DSS Player (any version) under Wine with usbmon capture to
   learn the wire protocol in one shot (oracle-based).
2. Direct libusb probing from Linux using the semantic knowledge above:
   the protocol is a small command/response over bulk EP 0x02/0x81 with
   status via interrupt EP 0x83; InitUSBPort/ConectConfirm are the handshake.
   Try known Olympus DS command patterns (R/D prefixes observed in DSX
   strings) to elicit responses.

Also: Wine will run the DLL's user-mode code fine, but the .SYS won't load
under Wine (kernel driver). Wine + usbmirrored usbmon needs a real Windows
VM (QEMU) for the oracle run. QEMU with USB passthrough of 07b4:0206 is the
cleanest oracle: run actual DSS Player 2002 (with valid serial from CD
sleeve, if found) or DSS Player Lite, capture on Linux side via usbmon.

---

## Live USB protocol probing (2026-11-20)

### Access setup
- udev rule installed: /etc/udev/rules.d/99-ds330.rules
  (SUBSYSTEM usb, VID 07b4 PID 0206, MODE 0666). Works.
- System libusb 1.0.0.3.0 has a crashy udev path; local build of libusb
  1.0.28 (--disable-udev) in ./libusb-local works fine.
- probe tools: probe_clean.c (open/claim/EP status), probe_scan.c (byte scan)
  Built with: gcc X.c -o X -I./libusb-local/include libusb-local/lib/libusb-1.0.so

### EP behavior at rest
- set_configuration(1) -> BUSY (config already active - harmless)
- claim interface 0: OK
- Bulk IN 0x81 and Int IN 0x83: silent at rest (timeouts)

### Single-byte command scan (EP 0x02 -> EP 0x81/0x83)
MAJOR FINDING: the interrupt EP 0x83 responds to most single-byte commands
with an 8-byte status packet. Bulk IN 0x81 responds for a few commands.

Default int response (sent for ~most commands):  ff ff 00 00 01 00 00 00
Anomalous responses observed:
  cmd 0x18: int = ff 01 00 00 01 00 00 00   (second byte 01 vs ff)
  cmd 0x30: int = 06 00 00 00 01 00 00 00   (first byte 06!)
  cmd 0x40: int = ff 01 00 00 01 00 00 00
  cmd 0x41: int = ff 01 00 00 01 00 00 00
  cmd 0x46: int = ff 01 00 00 01 00 00 00
  cmd 0x47: bulk = 64 bytes of zeros; int = 06 00 ...
  cmd 0x4a: int = 06 00 ...
  cmd 0x78: bulk = 64 bytes of STRUCTURED DATA! int = 06 00 ...
  cmd 0x79: bulk = 64 bytes of STRUCTURED DATA (continuation?)
  cmd 0x7a: bulk = 64 bytes of zeros; no int noted

cmd 0x78 bulk payload (hex):
  01 03 d9 01 ff 18 02 df 01 20 04 00 00 00 00 21
  02 04 01 22 02 01 01 22 03 02 04 07 1a 05 01 03
  00 02 0f 1b 08 c0 c0 a1 01 55 08 00 20 1b 0a c1
  41 99 01 55 64 f0 ff ff 20 1b 0c 82 41 18 ea 61
cmd 0x79 bulk payload:
  f0 01 07 f6 03 01 ee 1b 0c 83 41 18 ea 61 70 01
  07 76 03 01 ee 15 14 05 00 20 20 20 ... (padding)
  with ASCII "1.3" visible near offset ~0x28 ("...00 03 12 e 33 00" ->
  possibly version string "1.3" or "13.0")

INTERPRETATION:
- 0x78/0x79 = "read device info structure" (64-byte pages), int EP signals
  "data available/page complete" with 06 00 ...
- The int EP status packet format looks like [a][b][0][0][1][0][0][0]:
  ff=busy/default, 01=some ack state, 06=data-ready/complete
- Response "06 00 00 00 01 00 00 00" seems to mean "bulk data stage done"
- Single-byte protocol confirmed: command byte on EP 0x02, response data
  on EP 0x81 (64B chunks), status on EP 0x83 (8B)

NEXT:
1. Deeper scan: 2-byte commands, and read more pages after 0x78/0x79 (does
   0x79 repeat with more data? or other command advances page?)
2. Map single-byte 0x78.. to DSX API: GetDeviceInfo likely = 0x78 region.
   GetFileNum etc. probably nearby.
3. Cross-check DSXGetFileNum expects 4-byte buffer w/ first byte arg ->
   try 4-byte commands for file ops.

### Deep probe results (probe78.c)

cmd 0x78: streams a repeating 2-page (128-byte) device info structure,
  ASCII "1.3" version string visible. Likely DSXGetDeviceInfo/GetRecoderInfo.
cmd 0x79: 16-byte payload ff ff ff ff ff ff 00 00 65 a5 97 00 00 65 a5 97
  Two copies of dword 0x0097a565 (9,939,301). Candidate: memory size/free
  space or seconds counter (GetMemorySize/GetDeviceFreeSpace).
cmd 0x7b: 64-byte SECTOR READ ending in ... 05 5a aa (boot-signature-like).
  Likely DSXGetLogicalSector/GetPhisicalSector - flash sector read!
cmd 0x7c-0x7e: no bulk response.

Int-EP status format: [a][b] 00 00 01 00 00 00
  b=01 command accepted; a=06 bulk data stage follows/completes.

NEXT: figure out 0x7b sector addressing (4-byte command forms), then find
file-list commands (GetFileNum / GetFileInfoFirst/Next) to locate .dss files.

### 4-byte command scan results (probe4.c)

FILE METADATA FOUND via 4-byte commands in the 0x40-0x48 range:
- 0x40 arg1: "<RECORDING-NAME>" + ".dss" + "JSMYTHE   " name field -> file info!
  (DSXGetFileInfoFirst/Next candidates)
- 0x41 arg0: ASCII "1002412002306" + ff 07 ff ff... (date/time-ish field?)
- 0x42-0x45: all-FF pages = empty file slots (0x44 arg1 has 90 27 15 00)
- 0x48 arg1: FF prefix then zeros (tail of info struct)

0x7b is a GENERIC "read object N" command (arg = object index):
  arg0 = flash boot sector (55AA), arg2/3 = the 0x78/0x79 info pages,
  arg0x10 = the 16-byte memory-info response.
0x78/0x79 are page-addressed aliases of the same info object.

NEXT: 
1. How to advance file list: repeated 0x40 arg1? (FileInfoNext semantics)
2. Decode "1002412002306" - date/time?
3. 0x46/0x47 gave 64 zeros earlier - maybe file-data read (download)!

### CRITICAL DISCOVERY: 0x40 is a SEQUENTIAL STREAM READ (2026-11-20)

"0x40 arg1" is NOT a command-with-args: it is "read next 64-byte page" of a
linear data object, auto-advancing an internal cursor on EVERY call. The
hand.c test proved this: after ANY single-byte prime (0x00), each 0x40 call
returned the NEXT page:

  page0: "<RECORDING-NAME>" 00 02 "dss" 01 00 01 00 02 00 00 "JSMYTHE      " 01 00 00
  page1: "1002412002306" ff 07 ff ff ...
  page2-7: ff ff (erased slots)
  page8: ff*18 90 27 15 00 ff*39   <- 0x00152790 = 1,384,336 embedded value
  ...
  page11+: 00 00 ... (zero region, with ff at some offsets)

This explains everything: 0x40 = DSXGetFileInfoFirst/Next style sequential
read (the arg byte is ignored/unknown), 0x41 = same/alt cursor, 0x33 etc
also behaved like paged reads when args incremented (0x33 a0=name, a1=date
= it advanced the cursor too!).

The device can WEDGE if you send hundreds of rapid commands without reading
the cursor properly - the 256-arg sweep produced no output because the
cursor state machine was already exhausted/misaligned. Replugging resets.
libusb_reset_device + init byte 0x00 re-primes it.

The file info structure (per file, 64-byte pages):
  p0: name "<RECORDING-NAME>" + 00 02 + "dss" + 01 00 01 00 02 00 00 + label
      "JSMYTHE" padded + 01 00 00...
  p1: "1002412002306" + ff 07 + ff fill  <- date/time? unknown encoding
  ...
  p8: ff... then dword 0x00152790 = 1384336 (= bytes used? flash region?)

NEXT:
1. Full 0x40 page dump (200+ pages) with replug first: capture the ENTIRE
   data object -> file table layout becomes fully visible.
2. Then find file DATA read command (DSXOpenFile/DSXReadFile) - likely
   requires "open file" command with file number first.

### Python/libusb port complete; 0x40 stream dump reproducible (2026-11-20)

- dumpall.py (ctypes/libusb-1.0, no headers needed): works. Binding gotchas:
  * must NOT call libusb_free_device_list before libusb_open (open takes its
    own ref; freeing first = use-after-free = SIGSEGV exit 139)
  * device descriptor must be read via Desc STRUCTURE with byref(), not raw
    ubyte array + int byte-compare (idVendor check desc[8]==0x07B4 can never
    match; little-endian bytes are B4 07)
  * bulk_out/int_in/bulk_in per page confirmed working.
- 0x40 01 stream: send once (2 bytes), then read pages with plain bulk_in
  (no INT read needed after first page; INT status only for page 0).
- Consistent result across runs: object is 17 pages (0-16), 1088 bytes;
  page 17 read = timeout (-7). Deterministic.
- Mapping to old C dump (0x00 prime, 32 pages): new dump == old pages 15-31.
  File header (<RECORDING-NAME> / dss magic / JSMYTHE / date) at new page 0 = old
  page 15. Old pages 0-14 = 15-page FF preamble read by 0x00 prime.
- Structure: page 0 = file header (name <RECORDING-NAME>, dss magic, label JSMYTHE,
  date "02010100010502010..."), page 1 = date cont "1002412002306" + ff07,
  pages 2-7 = FF fill, page 8 = dword 90 27 15 00 (LE = 0x00152790 =
  1,384,080 bytes - likely file size or region size), pages 9-16 = zeros/FF.
- Next: file DATA read (0x44/0x46 region) to download the actual .dss file.

### Session summary: protocol state machine mapped (2026-11-20)

Working toolchain: Python ctypes + /usr/lib/x86_64-linux-gnu/libusb-1.0.so.0
(system python3.10; linuxbrew python3.14 lacks libudev). dumpall.py is the
reference reader. No C compiler headers needed.

CONFIRMED PROTOCOL:
- Command write: BULK OUT 0x02, 1-2 bytes. Command 0x40 + arg byte.
  Arg selects start page within an object: 0x40 01 = page 0, 0x40 02 = page 1.
- Response: BULK IN 0x81, 64-byte pages. First page preceded by INT 0x83
  status 06 00 00 00 01 00 00 00 ("data stage follows").
- 0x40 stream auto-advances one page per bulk_in; cursor does NOT reset on
  repeat of same command. Re-sending 0x40 01 mid-stream advances cursor.
- Stream ends deterministically: object length + 1 pages, then timeout.
- Device recovery: libusb_reset_device() + fresh open/claim works; no
  replug needed. Old cursor state survives until reset.
- Status ffff000001000000 on INT = command rejected (data stage never comes).

FILE TABLE OBJECT (17 pages, 1088 bytes, reproducible 3x):
- page 0: file header. "<RECORDING-NAME>" name, "dss" magic bytes 02 64 73 73 01 00 01
  00 02 00 00 00, label "JSMYTHE", date string "02010100010502010"
- page 1: date continuation "1002412002306" + ff07
- pages 2-7: FF fill (erased slots)
- page 8: dword 90 27 15 00 (LE 0x00152790 = 1,384,080) - size or region
- pages 9-16: zeros/FF
- Only ONE file on device ("<RECORDING-NAME>").

NEGATIVE RESULTS (tested on fresh state each, out=ok in=timeout):
- 0x7b flash-sector read: no response with 1-byte arg (00,01,02,03,10,20),
  4-byte LE args (0,1,2), or single-byte. NOT the sector path on this FW.
- 0x41/0x42/0x43/0x44/0x45/0x46/0x30/0x33 with 01 arg: no response.
- 0x40 with args 02,11,12,ff: 02 works (=page 1), 11/12/ff no response.
- 0x47 01: responds with 41 bytes mostly zeros (status-ish, not file data).
  0x47 00000000: 41 zero bytes. Possibly GetFileNum-like counter.

OPEN QUESTION - file DATA path: the .dss recording bytes are not in the
17-page info object (page 8 dword is too small for a real recording; likely
a metadata size). Next hypotheses:
1. File data is read via a different command family (0x50+? untested range)
2. Or via 0x40 with a 2-byte arg selecting file number (0x40 02 00 etc.)
3. IOCTL offset-4 mapping hypothesis from DLL analysis still untested:
   GetFileNum=0x50, OpenFile=0x44, ReadFile=0x48 per offset table.

### Offset-4 hypothesis disproven for 0x50/0x48 (2026-11-20)
- 0x50/0x48/0x51/0x52 with 1-byte and 4-byte args: no response. The DLL
  IOCTL→wire mapping is not a simple offset-4 correspondence.
- 0x47 01 and 0x47 00000000 consistently respond with ~41 bytes of zeros
  (status/counter, not file data). 0x47 = likely GetFileNum or OpenFile.
Hypothesis to test next: 0x47 opens a file/session, then 0x40 stream reads
file DATA instead of the info object.

### 0x47-then-0x40 hypothesis disproven (2026-11-20)
- 0x47 01 followed by 0x40 01 stream: returns the same 17-page info object
  (<RECORDING-NAME> header). 0x47 response is a status/counter, not an open-file
  that redirects 0x40 to file data.
