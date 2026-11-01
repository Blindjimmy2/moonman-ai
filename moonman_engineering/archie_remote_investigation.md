# Archie Remote Print-Start Investigation - 2026-10-28
Moon Man engineering shop - Archie-only. No Marvin.

## Requested tools
- archie_inspect: NOT AVAILABLE in this environment
- archie_read_logs: NOT AVAILABLE in this environment
No printer-control commands sent. No print started.

## Evidence actually collected
1. engineering_list -> found: archie_k1se_remote.py
2. engineering_read archie_k1se_remote.py v0.4:
   Confirmed (crew-provided, in file):
   - Archie = Creality K1 SE
   - WebSocket port: 9999
   - Accepts uploaded G-code
   - Prints OK from touchscreen
   Rules in file:
   - Archie-only, no Marvin logic/imports/calls
   - Slice + stage only, NEVER auto-start
   - Print start = touchscreen-only by human
   - Allowed agent tools: archie_status + prepare_archie_print only
3. archie_status (passive read-only, no control):
   - printer: Archie, model: K1 SE
   - state: 4
   - nozzle_c: 27.06, bed_c: 26.77
   - progress: 0
   - file: /usr/data/printer_data/gcodes/moonman_archie_test_de455ba9a80e.gcode
   - error: errcode 0, key 0 (no error)

## Analysis
- Status shows idle-ish, cold, 0% progress, no error. Staged test file present.
- Transport fact port 9999 comes from prototype file, NOT independently verified by live tool here.
- No logs inspected, no remote-start payload observed.

## What remains UNVERIFIED
- Exact G-code upload payload / endpoint / auth
- Exact remote start payload (AppControlPrint-related hints are CLUE ONLY, do not treat as working)
- Whether port 9999 is open/reachable from this station
- Any log evidence of prior remote starts
- Slice behavior (prepare_archie_print NOT called per no-control rule for this task)

## Marvin preservation
- No Marvin tools called (no prepare_marvin_print)
- No Marvin files read/written
- No Marvin imports added

## Prototype code status
- Existing prototype preserved at archie_k1se_remote.py v0.4, Archie-only
- No auto-start code added. No changes made to prototype in this run.
- Next step needs human go/no-go + touchscreen start.
