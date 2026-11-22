# R5.0.3 120-Second Boundary Report

The implementation uses an inclusive stale boundary: age `>= 120` seconds is stale, while age `< 120` seconds is fresh. The exact 120-second test and future-timestamp test passed in `tests/test_ground_unattended_position_projection.py`; reconciliation tests also verify delayed AC evidence and future evidence handling.

| Boundary | Expected source | Result |
|---|---|---|
| now / 1s / 60s / 119s | SYSLOG | covered by fresh projection contract |
| exactly 120s and older | AC_MESH_LINK fallback | PASS at exact boundary |
| no Syslog identity | AC_MESH_LINK or NO_DATA | PASS by projection contract |
| future Syslog relative to reference | neither as current evidence | PASS |

Historical playback uses the supplied reference/cursor time in the projection tests; the desktop deep-drag, backward-drag, and stale-request race were not manually verified in this run.

`SYSLOG_FRESHNESS_120S=PASS`; `PLAYBACK_TIME_REFERENCE=PASS (unit contract), GUI_NOT_VERIFIED`.
