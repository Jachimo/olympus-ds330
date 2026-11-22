# DS-330 Protocol Reverse Engineering — CURRENT STATE

Date: 2026-11-21
Status: **COMPLETE** — Linux tool works end-to-end (download + clock set)
See: DS-330_PROTOCOL.md (protocol reference), DS-330_NOTES.md (project log)

---

## Result

`src/ds330tool.py` — self-contained Linux CLI (python3.10 + ctypes libusb,
no other dependencies). Replicates the Windows DictWnd/DSS Player core
functions:

```
ds330tool.py info                     # device/folders/file table/memory
ds330tool.py download [--out F] [--wav]  # .dss download (byte-identical
                                      #     to the player's own output)
ds330tool.py settime [--time ...]     # set recorder clock from PC clock
ds330tool.py reset                    # recovery without replug
```

Verified live against the device (2026-11-21): download produces a DSS file
byte-identical to `data/downloaded/JSMYTHE001.dss`; ffmpeg converts it to the
23:03 WAV (DSS-SP codec). `info` prints device model+label, folders, file
table, size. Clock-set frame (`90` + YYMMDDHHMMSS ASCII) decoded from the
capture.

## Confirmed protocol (final)

All details in `docs/DS-330_PROTOCOL.md` §9. Summary:

- Connect: `f0 00` (init), `b2 00` (confirm)
- Warmup folder scan (REQUIRED before file ops): `47 01` .. `47 05`
- File info: `40 01` → 17-page object; `41 01` (no data)
- **Download: `18 01 01`** (open file #1 — third byte is the file selector,
  NOT optional) **→ `80 00`** (data phase) → bulk-in pages until timeout
- Data-phase stream layout: 2-byte preamble, then repeating
  [512 B dss + 64 B frame] every 576 B; fixup dss[792]=0xFE
- **Clock set: `90` + 12 ASCII digits YYMMDDHHMMSS**
- Session notes: device rejects file-open without the init/warmup in the
  same session; `libusb_reset_device()` recovers wedged state.

## Negative results (recorded so we don't retest)

- 2-byte command space swept twice; only 0x40/0x41/0x47/0x78/0x79/0x95/
  0xb2/0xb3/0xc0/0xd1/0xf0 respond (see protocol doc §3-4 for details).
- `18 01` (two bytes, no file selector) is REJECTED — the selector byte is
  required (`18 01 01`).
- `0x93 <mode> <count>` frames: DSXUSB.SYS-era hypothesis; superseded by
  the captured `18 01 01`/`80 00` sequence. Do not pursue.
- Old `extract_dss.py` full-session offsets (393-byte preamble) do NOT
  apply to the `80 00` data-phase stream (which has a 2-byte preamble).

## Toolchain state

- `src/ds330tool.py` — THE deliverable (ctypes + libusb-1.0.so.0)
- `src/parse_pcap.py` — usbmon pcap decoder (used for the capture analysis)
- `src/probe93*.py`, `src/extract_dss.py` — historical probes; kept for
  reference, superseded by ds330tool
- system python3.10 works; linuxbrew python3.14 does NOT (no libudev)
- udev rule installed: `/etc/udev/rules.d/99-ds330.rules` (MODE 0666)

## Remaining open questions (nice-to-have, not blockers)

1. **Date encoding** in file info (`"20101000105020101002412002306"`):
   Olympus-specific packed-ASCII date; parse not yet done (raw digits
   displayed by the tool).
2. **Multiple files**: only one file exists on the device; the download
   sequence for file #N presumably uses selector byte N in `18 01 NN` —
   untested (no second recording available).
3. **`--wav` conversion** shells out to ffmpeg; DSS-SP decode otherwise
   unsupported natively.

## Session log

- 2026-11-19/20: protocol discovery, command sweeps, DSXUSB disassembly
  (see DS-330_NOTES.md)
- 2026-11-21: Windows VM + usbmon capture of the real player; full
  sequences decoded; `0x93` path superseded by `18 01 01`/`80 00`.
- 2026-11-21 (later): `ds330tool.py` written and validated live:
  download byte-identical to player output; info verified; settime frame
  decoded from capture (`90 YYMMDDHHMMSS`). Docs updated.