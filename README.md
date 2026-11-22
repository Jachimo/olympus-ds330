# Olympus DS-330 USB Extractor

Goal: pull DSS recordings off a legacy Olympus DS-330 digital voice
recorder (ca. 2002) on a modern Linux box, then convert DSS → WAV/MP3.

**Status: SOLVED.** The full wire protocol is reverse-engineered and
`src/ds330tool.py` downloads `.dss` recordings (byte-identical to the
Windows player's own output) and sets the recorder clock, natively on
Linux. See `docs/CURRENT_STATE.md` for the live state and
`docs/DS-330_PROTOCOL.md` for the protocol reference.

## Usage

```sh
python3.10 src/ds330tool.py info              # device/folders/file table
python3.10 src/ds330tool.py download --wav   # download .dss + convert
python3.10 src/ds330tool.py settime          # set recorder clock from PC
python3.10 src/ds330tool.py reset            # recover wedged device
```

Requires system python3 (3.10) and libusb-1.0; `--wav` needs ffmpeg.

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
- Protocol highlights (see DS-330_PROTOCOL.md §9): init `f0 00`/`b2 00`,
  folder warmup `47 01..05`, file info `40 01`, download `18 01 01` →
  `80 00` data phase, clock set `90` + YYMMDDHHMMSS ASCII.
