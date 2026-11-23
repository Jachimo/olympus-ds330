# AGENTS.md — DS-330 Linux driver

Instructions for AI agents and humans continuing this project.

## Project

`ds330tool` — a Linux tool for the Olympus DS-330 digital voice recorder:
download `.dss` recordings, set the clock, inspect the device. The USB
protocol is proprietary and was fully reverse-engineered (see docs/).

## Read first (in this order)

1. `docs/CURRENT_STATE.md` — what is confirmed, quirks, open questions
2. `docs/DS-330_PROTOCOL.md` — protocol reference (frame model, commands,
   status codes, session quirks)

## Working rules

- **Update `docs/CURRENT_STATE.md` at the end of every working session.**
  New confirmed facts, new negative results, changed blockers.
- Record negative results (rejected commands, no-response probes) — they
  are as valuable as positives and prevent re-testing. The 2-byte command
  space has been swept twice already; don't re-sweep it.
- The code has three layers (src/ds330tool.py): `Usb` transport,
  declarative `Frame`/`StreamPhase` protocol model, and
  `DS330.run_sequence()` executor. Protocol changes belong in the frame
  definitions near the top of the protocol section, not in the executor.
- Run `python3 -m pytest tests/` after any change. Hardware-free; the
  `tests/data/` fixtures are real device captures (labels sanitized —
  keep personal device data out of commits).
- Toolchain: system python3 (3.10 verified) + system `libusb-1.0.so.0`
  via ctypes. Linuxbrew python3.14 does NOT work (missing libudev).
- Only USB interface 0 matters. Interfaces 1–4 are UAC1 audio, out of scope.
- Branches: `private` holds internal artifacts (vendor binaries,
  disassembly, raw logs) and is never pushed to GitHub (a pre-push hook
  enforces this). `github` is the publish branch; feature work happens
  on branches off it (e.g. `v1.0`).

## Known-good frame model (do not re-derive)

1. BULK OUT 0x02: `[cmd][arg]` (1–2 bytes, zero-padded to 64-byte pages)
2. INTERRUPT IN 0x83: 8-byte status; `06 00 00 00 01 00 00 00` = accepted,
   data stage follows; `ffff000001000000` = rejected
3. BULK IN 0x81: 64-byte pages

## Session quirks (live-established — see protocol doc §9.7)

- Init + folder-scan warmup must precede file operations in a session.
- Query file info (`40 01`) before label/memory (`95 00`/`79 00`) — the
  device stops answering `40 01` after them.
- A wedged device needs a reset (`ds330tool.py reset`); it can also take
  >2 s to answer frames while wedged (tool uses an 8 s timeout).

## Open questions (from CURRENT_STATE.md)

- Multi-file download: `18 <folder> <file>` verified with files in two
  folders. The `40 01` file-info object only describes one file per
  session; whether it can report other folders' files is unknown.
- `47 01` (file-count) and `79 00` (memory) encodings not fully understood.
- IOCTL→wire mapping of DSXUSB.DLL/SYS (0x98ff2004–0x98ff20a4) — internal
  branch only; the driver no longer needs it.
