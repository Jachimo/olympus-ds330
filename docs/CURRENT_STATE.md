# DS-330 Protocol Reverse Engineering — CURRENT STATE

Date: 2026-11-20
Status: Blocker — file DATA read not yet found
See: DS-330_PROTOCOL.md (protocol reference), DS-330_NOTES.md (project log)

---

## What we know (confirmed, reproducible)

### Device
- Olympus DS-330 digital voice recorder
- USB ID: 07b4:0206, USB 1.10, bus-powered, shows "REMOTE" display
- 5 interfaces: If 0 = vendor-specific file transfer (bulk 0x02 out,
  bulk 0x81 in, interrupt 0x83 in), If 1-4 = standard USB Audio (UAC1)
- Device contains ONE recording: file "JSMYTHE001" in folder "DICTATE"
- Device label: "JSMYTHE"

### Protocol model (confirmed)
1. BULK OUT 0x02: send 1-2 byte command `[cmd][arg]`
2. INTERRUPT IN 0x83: 8-byte status packet
   - `06 00 00 00 01 00 00 00` = accepted, data stage follows
   - `ffff000001000000` = rejected
   - `0000000001000000` = idle/ready
3. BULK IN 0x81: 64-byte data pages (stream auto-advances cursor)

### Confirmed commands

| Command | Arg | Returns | Maps to DSX API |
|---------|-----|---------|-----------------|
| 0x40 | 0x01 | 17-page file info object (1088 B) | GetFileInfoFirst/Next |
| 0x40 | 0x02 | Page 1 of file info object | " |
| 0x47 | 0x00/0x01 | 41 zero bytes | GetFileNum? |
| 0x47 | 0x02 | "DICTATE" (folder 1) | GetFolderName |
| 0x47 | 0x03 | "LECTURE " (folder 2) | GetFolderName |
| 0x47 | 0x04 | "TO DO   " (folder 3) | GetFolderName |
| 0x47 | 0x05 | "RANDOM  " (folder 4) | GetFolderName |
| 0x78 | 0x00 | 42-byte config/capability blob | GetRecoderInfo |
| 0x79 | 0x00 | 16 bytes: dword 0x0097a565 ×2 | GetMemorySize/FreeSpace |
| 0x95 | 0x00 | "JSMYTHE" (device label) | GetRecoderInfo |
| 0xb2 | 0x00 | "DS-330    JSMYTHE" (model+label) | GetDeviceInfo |
| 0xb3 | 0x00 | 16 00 00 ... (small value) | unknown |
| 0xc0 | 0x00 | 26-byte blob (non-deterministic) | one-shot/calibration |
| 0xd1 | 0x00 | 00 c0 d0 00 ... (14 bytes) | unknown |

### File info object structure (0x40 stream, 17 pages = 1088 bytes)

Page 0: `4a 54 55 54 30 30 30 31` "JSMYTHE001" — file name
         `00 02 64 73 73` `.dss` magic (version 2)
         `01 00 01 00 02 00 00 00` — flags
         `4a 54 55 54 54 4c 45 20` "JSMYTHE" — label
         `01 00 00 00` — flags
         `fe ff ff ff ff` — ?
         `30 32 30 31 30 31 30 30 30 31 30 35 30 32 30 31` "0201010001050201" — date
Page 1: `31 30 30 32 34 31 32 30 30 32 33 30 36` "1002412002306" — date cont
         `ff 07` — ?
         ff — fill
Pages 2-7: ff — erased slots
Page 8: `90 27 15 00` (LE dword 0x00152790 = 1,384,080) — size?
Pages 9-16: zeros/FF

### The blocker

The actual `.dss` recording data (~1.38 MB) is NOT in the 17-page info
object. No 2-byte command produces the recording bytes. Full 2-byte command
space (0x00-0xff) swept twice: only the commands listed above respond.

### Negative results (tested, no response)
- 0x7b (flash sector read): 1-byte, 2-byte, and 4-byte args all rejected
  on this firmware state. Earlier C-probe "55AA" read must have been from
  a different device state or command misinterpretation.
- 0x41-0x46 with arg 0x01: rejected (except 0x47 and 0x78-0xd1).
- 0x48, 0x49, 0x4a, 0x4b-0x4f, 0x50, 0x51, 0x52 with 1-byte args: rejected.
- 0x30, 0x33 with args: rejected.
- 0x40 with args 0x03-0x0f, 0x11-0x20, 0x40-0xff: rejected (arg 0x01-0x02 only).
- All EP0 vendor control transfers (0xC0, bRequest 0x00-0x20): return r=0
  but no data — not the file path either.

---

## What we DON'T know (open questions)

1. **How to read the actual .dss recording bytes.** The recording is
   somewhere in the device's 32 MB flash. No 2-byte command reaches it.
   Possible: 3+ byte commands, higher-level session state required,
   different USB interface, or flash sectors need a protocol we haven't
   discovered.

2. **The DLL IOCTL→wire protocol mapping.** We know the complete DSX API
   (32 functions exported from DSXUSB.DLL) and the complete IOCTL map
   (0x98ff2004–0x98ff20a4). We also know the WinDK kernel driver's URB
   structure layout. But we cannot map IOCTL→wire bytes without running
   the driver or a more careful static analysis of DSXUSB.SYS.

3. **Date/time encoding.** The file info has two date strings:
   "02010100010502010" (page 0) and "1002412002306" (page 1). These don't
   obviously parse as any standard date format. Likely Olympus-specific
   binary encoding stored as ASCII digits.

4. **0xc0 non-determinism.** Returns different content on separate
   sessions. Maybe a rolling counter or one-shot-per-enumeration.

---

## Toolchain state

- Working reference reader: `dumpall.py` (Python ctypes + libusb-1.0.so.0)
- Working command scanner: `cmdscan.py` / `cmdscan.txt`
- No C compiler needed (headers absent from system); python3.10 ctypes works
- Linuxbrew python3.14 does NOT work (missing libudev)
- udev rule installed: `/etc/udev/rules.d/99-ds330.rules` (MODE 0666)
- Device can be reset via `libusb_reset_device()` without replug

## Alternative approaches (not yet tried)

1. **QEMU/KVM Windows VM with USB passthrough** of the DS-330, running
   real DSS Player 2002 (with valid serial from CD sleeve if obtainable),
   while capturing with `usbmon` on the host. This is the highest-probability
   path to discovering the file-data read protocol.

2. **Deep static analysis of DSXUSB.SYS** — the kernel driver builds the
   actual USB transfers via WinDK's CUsb class. Reversing the exact
   command byte sequences requires careful disassembly of the URB
   construction functions (~12k lines of x86 code).

3. **Reverse the Olympus Mac DSS Player** (from the user's ISO) — the
   Mac version used the same USB device and was downloaded free from
   Olympus. Binary might be easier to reverse than the Windows driver.

4. **Try the Olympus DS-330 as a USB audio device** — the ISO interface
   provides real-time audio streaming. Could capture audio this way as a
   fallback (loses original .dss file format and timestamps).

## Recommended next step

Try the Windows VM/QEMU + usbmon capture approach. This avoids blind
probing and gives us the exact wire bytes the Olympus software uses.

## Wine Status (Nov 21)

- DSS Player 2002 fully installed in wineprefix (installer ran; serial gate
  applies to registration only, not runtime).
- DSSPlay.exe (player) runs under Wine; DictWnd.exe (downloader) also runs and
  shows the Download Tray UI with no serial prompt.
- Wine CANNOT access the DS-330: the device path goes through
  DSXUSB.dll -> DeviceIoControl("\\\\.\\DSXUSB0") -> DSXUSB.SYS kernel driver,
  which Wine cannot load. No device enumeration in the player's Device Manager.
- usbmon capture attempted while Wine was running: captured only background
  bus traffic, no player traffic.

## DictWnd Static Analysis

See docs/DICTWND_ANALYSIS.md. DictWnd resolves all 32 DSXUSB exports at
runtime and drives the download sequence via thin shims.

## Next Steps

1. Windows VM (QEMU/KVM) with USB passthrough of the DS-330.
2. Install DRIVERS/DSX (DSXUSB.INF + DSXUSB.SYS + DSXUSB.DLL) standalone --
   no serial needed.
3. Copy wineprefix/drive_c/Program Files/DSSPlayer2002 into the VM (bypasses
   installer serial gate entirely).
4. Run DictWnd.exe in the VM, download JSMYTHE001, capture with usbmon on host
   (sudo tcpdump -i usbmon2 -s0 -w logs/usbmon2_dictwnd.pcap).
5. Compare captured wire bytes against DSXUSB.SYS handler analysis
   (docs/DS-330_PROTOCOL.md) to resolve the 0x93 mode/count semantics and
   the 325-byte DownloadDataBase buffer layout.

## 2026-11-21 — GOAL ACHIEVED (data path solved)
- Raw stream → DSS extraction rule fully decoded and verified byte-for-byte.
- `src/extract_dss.py` produces a DSS file identical to the player's output;
  ffmpeg converts it to 23:03 WAV (DSS-SP codec).
- Remaining: automate raw-stream acquisition on Linux end-to-end (the
  probe/`93`-command path works but is slow); extraction itself is proven.
