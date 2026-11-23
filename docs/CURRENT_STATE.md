# DS-330 Protocol Reverse Engineering — CURRENT STATE

Date: 2026-11-22
Status: **COMPLETE** — v1.0 driver works end-to-end (download + clock set)
See: DS-330_PROTOCOL.md (protocol reference), DS-330_NOTES.md (project log)

---

## Result

`src/ds330tool.py` — self-contained Linux CLI (python3 3.8+, ctypes libusb,
stdlib only, no other dependencies), restructured (2026-11-22) as a v1.0
driver: typed USB transport, declarative frame/sequence model mirroring the
protocol reference, one generic sequence executor. Full test suite:
`tests/` (23 tests, pytest), built on fixtures captured from the live
device (`tests/data/`: raw stream, file-info object, reference DSS —
personal labels sanitized).

```
ds330tool.py info                     # device/folders/file table/dates
ds330tool.py download [-i N] [--wav]  # .dss download (byte-identical
                                      #     to the player's own output)
ds330tool.py settime [--time ...]     # set recorder clock from PC clock
ds330tool.py reset                    # recovery without replug
```

Verified live against the device (2026-11-22, v1.0 code): download produces
a DSS byte-identical to the captured reference fixture (except sanitized
label bytes); ffmpeg decodes it (DSS-SP); `info` prints decoded record
dates; wedge recovery (auto reset + retry) works in practice.

## Confirmed protocol (final)

All details in `docs/DS-330_PROTOCOL.md` §9. Summary:

- Connect: `f0 00` (init), `b2 00` (confirm)
- Warmup folder scan (REQUIRED before file ops): `47 01` .. `47 05`
- File info (SOLVED 2026-11-22): `40 NN` = first file's info of folder
  NN; `41 NN` = next file (empty data stage = folder exhausted);
  per-session cursor. `info` now enumerates the full file table.
  (With one file on device this looked like `40 01` + `41 01` flush.)
- **Download: `18 <folder> <file>`** (folder 1–5 = A–E, third byte is the
  1-based file within it; resolved issue #2's single-folder limitation)
  **→ `80 00`** (data phase) → bulk-in pages until timeout
- Data-phase stream layout: 2-byte preamble, then repeating
  [512 B dss + 64 B frame] every 576 B; fixup dss[792]=0xFE
- File-info date digits: 30 ASCII digits at object offset 0x2F —
  start YYMMDDHHMMSS + stop YYMMDDHHMMSS + duration HHMMSS
- **Clock set: `90` + 12 ASCII digits YYMMDDHHMMSS**
- Session notes: device rejects file-open without the init/warmup in the
  same session; `libusb_reset_device()` recovers wedged state.

## Session-order and timing quirks (all established live, 2026-11-22)

- **Query order matters**: the device stops answering `40 01` after
  `95 00` (label) or `79 00` (memory) queries in the same session. `info()`
  queries file-info first.
- **Wedge recovery**: a stale session can produce transfer timeouts
  (bulk OUT code -7, interrupt status timeouts); a reset + retry fixes
  it. The CLI does this automatically once.
- **Slow responses**: a wedged/stale device can take >2 s to answer frames
  (observed up to 5 s); the tool uses an 8 s device timeout.
- The `47 01` (file-count) response dword is 1 even with zero files; its
  semantics are unclear. `79 00` (memory) returns 0 dwords when the
  device holds no recordings.

## Negative results (recorded so we don't retest)

- 2-byte command space swept twice; only 0x40/0x41/0x47/0x78/0x79/0x95/
  0xb2/0xb3/0xc0/0xd1/0xf0 respond (see protocol doc §3-4 for details).
- `18 01` (two bytes, no selectors) is REJECTED — both selector bytes are
  required (`18 01 01`).
- `0x93 <mode> <count>` frames: DSXUSB.SYS-era hypothesis; superseded by
  the captured `18 01 01`/`80 00` sequence. Do not pursue.
- Old `extract_dss.py` full-session offsets (393-byte preamble) do NOT
  apply to the `80 00` data-phase stream (which has a 2-byte preamble).

## Toolchain state

- `src/ds330tool.py` — THE deliverable (v1.0 architecture: Usb transport /
  declarative frames / run_sequence executor)
- `tests/` — pytest suite; `tests/data/` live-device fixtures
- `src/parse_pcap.py` — usbmon pcap decoder (used for the capture analysis)
- `src/probe93*.py`, `src/extract_dss.py` — historical probes; kept for
  reference, superseded by ds330tool
- system python3.10 works; linuxbrew python3.14 does NOT (no libudev)
- udev rule shipped in `udev/99-ds330.rules` (tested as MODE 0666)

## Remaining open questions (nice-to-have, not blockers)

1. **Multiple files: SOLVED (2026-11-22).** The open-file frame is
   `18 <folder> <file>` — folders 1–5 = device A–E, both selector bytes
   required. `download --folder F -i N` reads any folder (number,
   letter, or this device's name — names are user-settable per recorder
   and are read live via the 47 02..05 queries, never hardcoded).
   Plain `download` sweeps all folders. Verified live with recordings
   in folders A and E: all download and decode via ffmpeg.
   **File table SOLVED same day:** `40 NN`/`41 NN` = first/next file
   info per folder; `info` lists every recording with names and dates
   (live-verified with 3 files across folders A and E). The DSS header
   also carries per-file timestamps, used for naming and file mtimes.
2. **Folder renaming: SOLVED (2026-11-23).** `4A <folder> <8-byte
   name>` (decoded from the DSXUSB.SYS disassembly, live-verified).
   `rename -f F --name NAME` renames any folder including A; writing
   eight spaces clears a name. Also discovered: `47 01` carries folder
   A's name in the same format as `47 02..05` — it only looked like a
   status counter while A was unnamed.
3. **File deletion: SOLVED (2026-11-23).** `A0 <folder> <file WORD
   x2>`, live-verified including a full sweep of every recording on
   the device (PR #7).
4. **`--wav` conversion** shells out to ffmpeg; DSS-SP decode otherwise
   unsupported natively.
5. **`79 00` (memory) encoding** is not fully understood; harmless to
   leave raw.

## Session log

- 2026-11-19/20: protocol discovery, command sweeps, DSXUSB disassembly
  (see DS-330_NOTES.md)
- 2026-11-21: Windows VM + usbmon capture of the real player; full
  sequences decoded; `0x93` path superseded by `18 01 01`/`80 00`.
- 2026-11-21 (later): `ds330tool.py` written and validated live:
  download byte-identical to player output; info verified; settime frame
  decoded from capture (`90 YYMMDDHHMMSS`). Docs updated.
- 2026-11-22: `github` publish branch created (private analysis/, logs/,
  archive/ stripped from history via git-filter-repo). Date encoding
  solved; `--index` selector added; udev rule shipped; GPL-3.0 added;
  README rewritten for end users.
- 2026-11-22 (later): v1.0 rewrite on branch `v1.0` — three-layer
  architecture (transport / declarative protocol / executor), distinct
  error classes, pytest suite (23 tests) on live-device fixtures.
  New findings: date digits start at 0x2F (not 0x30 — one digit was
  being dropped); query-order dependency (`40 01` before `95/79`);
  auto reset+retry for wedges; 8 s device timeout. Live download
  verified byte-identical to the captured reference (sanitized label
  aside).

- 2026-11-23 (later): Issue #4 (delete after download) solved on branch
  feature/delete-after-download. A0 delete frame live-verified
  (nonexistent-file delete silently accepted); --delete-after implemented with
  on-disk byte verification before any delete. Both RANDOM recordings
  used for live testing per owner instruction.
- 2026-11-23 (continued): Post-delete "wedge" root-caused. A0
  triggers a multi-second flash erase; the device answers the
  interrupt endpoint with continuous idle polls (00..01) until the
  erase finishes, and ignores commands meanwhile. The wedge was OUR
  libusb_reset_device fired mid-erase — that state needs a physical
  replug. delete_file now drains the polls instead of resetting.
  Also verified: renaming edge cases (duplicates allowed on device,
  CLI refuses ambiguous matches; overlong names truncated; NUL/space
  both clear). Full sweep+delete re-run end-to-end: all 4 recordings
  of a fresh test set downloaded, verified, deleted; device empty;
  erase window measured up to 30+ s near end-of-folder.
- 2026-11-23: Issue #3 (folder rename) solved on branch
  feature/rename-folders. Spike on the private branch decoded wire
  frames from the DSXUSB.SYS dispatch handlers: `4A <folder> <name>`
  (rename), `A0 <folder> <file WORD x2>` (delete), `E1` (folder info
  write), `C0 <folder> <file>` (direct file addressing); the driver's
  length field explains the 64-byte pages. Rename live-verified on
  folders A/B/E incl. round-trips and clearing A's name.