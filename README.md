# Olympus DS-330 USB Extractor

Goal: pull DSS recordings off a legacy Olympus DS-330 digital voice
recorder (ca. 2002) on a modern Linux box, then convert DSS → WAV/MP3.

**Status: blocker.** Device enumeration, reset, and the info-object read
are understood; the actual `.dss` recording data read command is NOT yet
found. See `docs/CURRENT_STATE.md` for the live state and `docs/DS-330_PROTOCOL.md`
for the protocol reference.

## Layout

| Path | What |
|---|---|
| `src/` | libusb probe/dump tools (C sources + compiled binaries, Python ctypes scripts). Entry points: `dumpall.c`, `cmdscan.py`, `probe_files.c` |
| `docs/` | Reverse-engineering notes: `DS-330_NOTES.md` (project log/survey), `DS-330_PROTOCOL.md` (wire protocol reference), `CURRENT_STATE.md` (live state — update this after every session) |
| `docs/screenshots/` | Device photos, dialogs, captures |
| `data/` | `iso_root/` (extracted Olympus DSS Player 2002 CD), `dsstimescript` (SourceForge odsstools relic) |
| `thirdparty/` | `libusb-1.0.28` source + local build (`libusb-local/`), `wine-setup` (extracted DSS Player installer; read-only) |
| `logs/` | Hex dumps and command-scan output (`dump.txt`, `dump40.txt`, `cmdscan.txt`, …) |
| `archive/` | Unrelated artifacts (LLM title-gen investigation notes, activity CSV) |
| `wineprefix/`, `venv/` | **Do not move.** Wine prefix (registry paths point here) and Python venv (path baked in) |
| `Olympus_DSS_Player_Software.ISO` | Original CD image (494 MB) — source of `iso_root/` and `wine-setup/` |

## Key facts

- Device: USB ID `07b4:0206`, 5 interfaces; only **interface 0** matters
  (bulk OUT 0x02 = commands, bulk IN 0x81 = data, interrupt IN 0x83 = status).
- No kernel driver claims interface 0, so libusb works directly.
- udev rule: `/etc/udev/rules.d/99-ds330.rules` (MODE 0666).
- DSS decode is a solved problem: `ffmpeg -i file.dss file.mp3`.
- Recommended next step (per CURRENT_STATE.md): Windows VM + usbmon capture
  of real DSS Player traffic to discover the file-data read command.
