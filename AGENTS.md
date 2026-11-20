# AGENTS.md — DS-330 reverse-engineering workspace

Instructions for AI agents and humans continuing this investigation.

## Project

Extract `.dss` recordings from an Olympus DS-330 over USB on Linux.
The protocol is proprietary; everything is being reverse-engineered.

## Read first (in this order)

1. `docs/CURRENT_STATE.md` — what is confirmed, what the current blocker is
2. `docs/DS-330_PROTOCOL.md` — protocol reference (frame model, commands, status codes)
3. `docs/DS-330_NOTES.md` — background survey (DSS decode landscape, alternative approaches)

## Working rules

- **Update `docs/CURRENT_STATE.md` at the end of every working session.**
  New confirmed facts, new negative results, changed blockers.
- Record negative results (rejected commands, no-response probes) — they
  are as valuable as positives and prevent re-testing. The 2-byte command
  space has been swept twice already; don't re-sweep it.
- Toolchain: Python 3.10 ctypes + system `libusb-1.0.so.0` is the proven
  binding (`src/dumpall.py`, `src/probe_ctypes.py`, `src/cmdscan.py`).
  Linuxbrew python3.14 does NOT work (missing libudev). C binaries compile
  against `thirdparty/libusb-local/`.
- Device resets between probe sessions via `libusb_reset_device()`
  (`src/usbreset`); no replug needed. udev rule grants 0666.
- Only USB interface 0 matters. Interfaces 1–4 are UAC1 audio, out of scope.

## Known-good frame model (do not re-derive)

1. BULK OUT 0x02: `[cmd][arg]` (1–2 bytes)
2. INTERRUPT IN 0x83: 8-byte status; `06 00 00 00 01 00 00 00` = accepted,
   data stage follows; `ffff000001000000` = rejected
3. BULK IN 0x81: 64-byte pages

## Open questions (from CURRENT_STATE.md)

- How to read the actual `.dss` recording bytes (~1.38 MB in 32 MB flash).
  No 2-byte command reaches it. Consider 3+ byte commands, session state,
  or watch a real DSS Player session.
- IOCTL→wire mapping of DSXUSB.DLL/SYS (0x98ff2004–0x98ff20a4).
- Olympus-specific date/time encoding in file info pages.

## Recommended next step

Windows VM (QEMU/KVM) with USB passthrough, run real DSS Player 2002
(`data/iso_root/`), capture wire bytes with `usbmon` on the host.

## Environment

- `wineprefix/` and `venv/` must stay at repo root (absolute paths inside).
- `Olympus_DSS_Player_Software.ISO` is the source of `data/iso_root/` and
  `thirdparty/wine-setup/` (both extracted from it).
- `archive/` holds unrelated files (LLM debugging notes); ignore for this project.
