# Archie Communication Protocol - Investigation 2026-10-28

Moon Man's field notes from orbit (aka the shop desk).

## Tools Tested
1. `archie_inspect(seconds=5)` -> SUCCESS, read-only
2. `archie_read_logs(lines=100)` -> FAILED, ssh_unavailable

## Confirmed Facts from `archie_inspect`
- Mode: `read_only` - never sends control commands. Good, I like my printers un-startled.
- Printer: `Archie`, Model: `K1 SE`
- Hostname: `Archie`, MAC: `FCEE280A34F1`
- Connection: `wssPort: 443`, `videoPort: 443`, `webrtcSupport: 1`, `video: 1`
- Info version: `1.0.0`
- DWIN versions: `CR4CU220812S11` / `1.3.5.22`
- Telemetry sample:
  - `nozzleTemp: 27.0 -> 27.04`, `bedTemp0: 26.64`, targets all `0`
  - `curPosition: X:219.00 Y:113.50 Z:124.89`
  - `state: 4`, `deviceState: 0`, `connect: 1`
  - `printFileName: /usr/data/printer_data/gcodes/moonman_archie_test_de455ba9a80e.gcode`
  - `printProgress: 0`, `TotalLayer: 0`, `layer: 0`
- Message pattern: 1x full status dump + 2x delta updates (`connectionCount: 2`, `nozzleTemp` bump)
- Motion limits observed: `velocityLimits: 600`, `accelerationLimits: 5000`, `accelToDecelLimits: 2500`, `cornerVelocityLimits: 10`
- Material: `pressureAdvance: 0.044000`, `smoothTime: 0.040000`
- Limits: `maxNozzleTemp: 300`, `maxBedTemp: 100`, `maxBoxTemp: 60`

Interpretation (guess, labeled as such): Looks like Creality K1 SE WebSocket push over TLS on 443, JSON dicts, full-state then deltas. WebRTC for camera.

## Failure from `archie_read_logs`
- Status: `ssh_unavailable`
- Log: empty string
- Error: `root@192.168.1.10: Permission denied (publickey,password).`
- Interpretation: Tool uses non-interactive SSH for Klipper logs, no control commands. Currently locked out - needs key/password fix. No logs retrieved.

## What I Did NOT Do
- No print started. Archie stays chilly at 27C.
- No Marvin modifications. Marvin is innocent.
- No CAD changes. Knob v007 still 28.0mm x 25.0mm, shaft 6.0mm.

Next: fix SSH creds for Archie if we want Klipper logs, else stick to WebSocket inspect.
