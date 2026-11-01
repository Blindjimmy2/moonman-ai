# Archie Upload/Start Investigation - 2026-10-28 15:36-15:39 UTC
Moon Man shop - Archie-only. No Marvin. No commands sent. No print started.

## Tools used (read-only + workspace)
- archie_status -> ok, live
- archie_inspect(seconds=5) -> ok, read_only
- archie_read_logs(lines=500) -> ok, 500 lines 15:36:05 to 15:39:06
- engineering_list / engineering_read -> prior recon

## VERIFIED (direct tool output)
- archie_status:
  - printer Archie, model K1 SE, state 1
  - nozzle 168.32C, bed 90.03C
  - progress 0
  - file `/usr/data/printer_data/gcodes/shaft collar12.7mm.stl_ASA_31m35s.gcode`
  - errcode 0
- archie_inspect:
  - mode read_only, never sends control
  - hostname Archie, MAC FCEE280A34F1, model K1 SE
  - wssPort 443, videoPort 443, webrtcSupport 1, video 1
  - DWIN hw CR4CU220812S11 / sw 1.3.5.22
  - printFileName same as status, printFileType 1
  - printId 6ae25ca1f132864a0bcce0c6, printStartTime 1793219744
  - curPosition moving X 124.5->130.93 Y 225.16 Z 1.5->2.6 in 5s window
  - targetBed 90, targetNozzle 165, autohome X:1 Y:1 Z:1
  - 1x full dump + deltas, connectionCount 1->2
- archie_read_logs 500:
  - print-start sequence present, NOT file load:
    - 15:36:06 bed_mesh fade complete Z 126.74
    - 15:36:11 extruder within range 185
    - 15:36:12 SAFE_MOVE_Z -76.74, ENABLE_STEPS, GET_STEP_CNTS
    - 15:36:17 tri_dis 12.5375
    - 15:36:19 SAFE_MOVE_Z -94.2
    - 15:36:51 tri_dis 94.20625, x_axes xy
    - 15:36:53+ extruder target drops 185->165, print_time climbing 33503->33640
    - 15:37:09 x_park -104.5 / y_park 104.5, RUN_G28_Z start
    - 15:37:14-15:37:17 PRTouch Self Test 1-5 all Pass, 3x coarse probes
    - 15:37:29 CLEAR_NOZZLE_QUICK start hot_min 165 hot_max 235 bed_max 90
    - src 1.44937 at 15:37:37, end 1.35156 at 15:37:43
    - 15:37:43-15:38:54 heat 165->205->235, wipe, cool to 165
    - bed target 90 held, 82.8->90.3C, extruder 176->238->164C
    - print_stall 0 throughout, no shutdown
  - file-loading events: NONE. No filename, no PRINT_START / START_PRINT string in 500 lines.
  - commands/errors: No Unknown command in THIS slice. No heater fault, no homing fail.

## GUESSES (do not weld on this)
- File load happened before 15:36:05 via slicer/cloud/Moonraker, not in klippy.log.
- Prior slice had BOX_ENABLE_CFS_PRINT + M141 Unknowns; absent here because this window starts after upload.
- Port 9999 upload + AppControlPrint start remain CLUE ONLY from prior prototype file, NOT verified live here.

## What remains UNKNOWN / blocked
- Exact G-code upload endpoint / payload / auth
- Exact remote start payload (AppControlPrint hints unconfirmed)
- Whether port 9999 reachable from this station
- Moonraker / cloud history for filename-to-job mapping

## Tools needed if blocked
- Moonraker history / job list query (read-only)
- Local HTTP / WS capture of slicer-to-Archie upload (non-printing)
- Port 9999 reachability probe spec (no start)
- Creality AppControlPrint protocol doc / sample (no execution)
- SSH file list of /usr/data/printer_data/gcodes (read-only, if allowed)

## Marvin preservation
- Zero Marvin tools called. Zero Marvin files read/written. Zero Marvin imports.
