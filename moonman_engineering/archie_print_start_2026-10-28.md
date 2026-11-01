# Archie Print-Start Watch - 2026-10-28 15:32:24 to 15:36:00 UTC
Source: archie_read_logs lines=500, read-only. No printer commands sent. Marvin untouched.

## CONFIRMED (direct from log text)
- Window covers end of one job + start of next.
- 15:32:26 to 15:34:44: Start macro in progress:
  - Stats: heater_bed target=90, temp 54.3 -> 84.9C rising, pwm=1.000
  - extruder target 165 -> 205 -> 235 -> 165
  - [CLEAR_NOZZLE_QUICK] Start clear_nozzle_quick(), hot_min 165, hot_max 235, bed_max 90
  - src_pos[2]:1.721874999999928 at 15:32:39, end_pos[2]:1.5617187499999998 at 15:32:45
  - [CLEAR_NOZZLE] Down And Wait Temp For 235.00, Start Clear The Noz, Start Cool Down, Start Finish Clear
  - G28 / PRTouch probing + [RUN_STEP_PRTOUCH] events throughout
  - 15:34:11 [SET_BED_TEMPS] temp=90.00 wait=1
  - 15:34:19 Heater heater_bed within range of 90.000
- 15:34:46 to 15:34:59: Previous job ends:
  - 15:34:46.435 Extruder not hot enough
  - 15:34:46.498 wait temp start
  - Stats: heater_bed target=0 temp 85.4, extruder target=0 temp 165.3, print_time frozen at 33388.829 -> 33389.8, buffer_time -> 0.000
  - 15:34:59.553 end print xyz_axes is NULL
  - Cooldown: bed 85.3->80.6C, extruder 158.2->114.8C by 15:35:44
- 15:35:44 to 15:36:00: NEW print-start sequence (your slicer send):
  - 15:35:44.480 Unknown command: BOX_ENABLE_CFS_PRINT
  - 15:35:45.087 wait temp end
  - 15:35:45.520 Unknown command: M141
  - 15:35:46.331 Heater extruder approaching new target of 185.000
  - Stats 15:35:47: heater_bed target=90 temp 80.3 pwm=1.000, extruder target=185 temp 112.6 pwm=1.000, print_time jumps to 33435.741
  - 15:35:49.838 x_axes is NULL, 15:35:49.857 move xy
  - 15:35:49.862 FORCE_MOVE stepper_z distance=0.100 velocity=10.000
  - 15:35:49.870 FORCE_MOVE stepper_y distance=-14.000 velocity=50.000
  - 15:35:49.876 FORCE_MOVE stepper_y distance=7.000 velocity=50.000
  - Heating: bed 80.2->81.3C, extruder 115.4->145.5C by 15:35:59, print_time 33442.081->33451.585
- File-loading events: NONE in these 500 lines. No filename, no PRINT_START / START_PRINT string.
- Other errors: No heater fault, no homing fail, no shutdown. Only the two Unknown commands + the expected not-hot-enough at job end.

## DIFFERENCES vs earlier start in same window
- New start adds BOX_ENABLE_CFS_PRINT unknown (not seen at 15:32-15:34 phase) - suggests slicer profile with CFS flag.
- M141 repeats in both starts - consistent slicer chamber-heat leftover.
- Targets same: bed 90, extruder 185 initial - same profile temps.
- Previous phase ended with heaters to 0 and print_time freeze; new phase restarts print_time climb.

## GUESSES (do not weld on this)
- BOX_ENABLE_CFS_PRINT likely from Creality slicer CFS / multi-color toggle, ignored by Klipper - harmless but new.
- M141 likely chamber temp from slicer, ignored - harmless.
- Filename / file load happens outside klippy.log (Moonraker / cloud) - need Moonraker history to confirm file.
