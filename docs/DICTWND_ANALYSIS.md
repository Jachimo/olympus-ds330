# DictWnd.exe Static Analysis

## Import Chain

`DictWnd.exe` does NOT link `DSXUSB.dll` directly. Its import table contains
`CFGMGR32.dll` and `SETUPAPI.dll` (device enumeration), plus `DSSSUP.dll`,
`dwprops.dll`, `MSVCRT`, `MFC42`. It loads `DSXUSB.dll` at runtime via
`LoadLibrary`/`GetProcAddress` (string `DSXUSB.dll` at VA 0x4b4054, pushed at
`0x481746`). Device detection string `DSXUSB Device` at VA `0x4b429c`
(referenced at `0x4842ca`).

## Function Resolution Table

Object layout: `esi+0x04` = HMODULE of DSXUSB.dll; `esi+0x20..0x98` = resolved
function pointers. Resolved at code `0x4817a3`..`0x481a79` via `GetProcAddress`
(edi = `ds:0x49516c`).

| Object offset | Function |
|---|---|
| 0x20 | DSXConectConfirm |
| 0x24 | DSXGetDeviceInfo |
| 0x28 | DSXInitUSBPort |
| 0x2c | DSXCloseUSBPort |
| 0x30 | DSXSetCOMPower |
| 0x34 | DSXGetFileNum |
| 0x38 | DSXGetFileInfoFirst |
| 0x3c | DSXGetFileInfoNext |
| 0x40 | DSXStartPlayback |
| 0x44 | DSXStartRecording |
| 0x48 | DSXGetEncodeData |
| 0x4c | DSXStop |
| 0x50 | DSXOpenFile |
| 0x54 | DSXReadFile |
| 0x58 | DSXDeleteFile |
| 0x5c | DSXGetFolderName |
| 0x60 | DSXSetFolderName |
| 0x64 | DSXSetHeaderInfo |
| 0x68 | DSXOpenFileUP |
| 0x6c | DSXWriteFile |
| 0x70 | DSXSetRecoderInfo |
| 0x74 | DSXGetRecoderInfo |
| 0x78 | DSXUploadDataBase |
| 0x7c | DSXDownloadDataBase |
| 0x80 | DSXSetPCTime |
| 0x84 | DSXGetDeviceFreeSpace |
| 0x88 | DSXGetMemorySize |
| 0x8c | DSXGetPhisicalSector |
| 0x90 | DSXGetLogicalSector |
| 0x94 | DSXStartFirmwareUpdate |
| 0x98 | DSXBusReset |

All 32 exports are resolved. Missing any one => ebx=0 (failure path).

## Wrapper Functions (thin shims)

- `0x481dc0` — inline tail-jump to `[ecx+0x20]` (DSXConectConfirm) after
  checking `+0x04`, `+0xa4`, `+0x18`; returns 2 if not ready.
- `0x481df0` — shim for DSXInitUSBPort `[esi+0x28]`; on return==2 sets
  `[esi+0xa0]+0x04 = 1` (connected flag).
- `0x481e40` — shim for DSXCloseUSBPort `[ecx+0x2c]`; clears connected flag.
- `0x481e70` — shim for DSXGetFileNum `[ecx+0x34]`.
- `0x481ea0` — shim for DSXGetFileInfoFirst `[esi+0x38]`.

Every shim: validates three fields (+0x04 dll handle, +0xa4, +0x18), then
passthrough call. Return value 2 = error/not-ready convention throughout.

## Connect Sequence

Main connect path at `0x44c6cc`: `call DWORD PTR [eax+0x28]` (DSXInitUSBPort)
inside a message-pump loop (`0x44c4c8` loop via `ds:0x495e74`), i.e. the player
drives connect from its message handler, not a one-shot.

## DSXDownloadDataBase Call Sites (object offset 0x7c)

- `0x40d857` — first call, then `0x481df0` (InitUSBPort shim) at `0x40d86a`,
  then `0x4823d0` at `0x40d881`.
- `0x40d8ba` — second call in same function (second object `[esi+0x868]`).
- `0x4153c7` / `0x41544f` — pair: first call, then buffer-struct fill
  (`[esp+0x70]=1 or 2`, `[esp+0x7c]=0x0c14 or 0x0414` WORD), then a second
  DownloadDataBase call. This looks like the file-listing double-buffer
  exchange.
- `0x41fb59`, `0x421f71`, `0x421fd4`, `0x422033`, `0x422094` — further sites.

## Key Takeaway

DictWnd drives the device through the same 32-export API we already mapped to
IOCTLs. The connect sequence is InitUSBPort -> ConectConfirm -> GetFileNum ->
GetFileInfoFirst/Next -> per-file OpenFile/ReadFile. The 325-byte
DownloadDataBase buffer is invoked repeatedly (>=10 sites), consistent with
per-file or per-chunk transfers rather than one bulk dump.

## Doc Updates

- `docs/CURRENT_STATE.md` — add Wine outcome (player runs, no kernel driver in
  Wine, so no device access; VM required for wire capture).
- `docs/DS-330_PROTOCOL.md` — add pointer to this file for caller-side
  sequencing.
