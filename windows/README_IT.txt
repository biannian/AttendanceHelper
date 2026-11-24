AttendanceHelper - folder build (for IT)
========================================

Copy the whole AttendanceHelper folder to the target PC.
Run AttendanceHelper.exe inside that folder.
Do not copy the exe alone; keep the _internal folder next to it.

This folder build starts faster than the single-file exe
(no extract-to-temp on every launch).

Config files (.env, config.json) are created next to the exe,
not inside _internal.

Tray:
- Left click    = progress detail
- Double-click  = open door
- Right click   = menu (open door / refresh / stats / settings / exit)
