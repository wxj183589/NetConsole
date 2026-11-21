# R5.0.4 Global Timeline Report

The navigator is rendered before the five chart regions. Every RTT, Quick Ping and Peer chart receives the same `visibleStart`, `visibleEnd`, and `cursorTime`; chart `datazoom` and axis-pointer events emit back to the single playback owner. Event location now recenters the current visible span around the event (clamped to the queried range), updates the cursor, and schedules the bounded event refresh.

The global range remains in the parent when a chart is collapsed, so remounting cannot restore a stale per-chart window. Reset still uses the existing run range control.

`GLOBAL_TIME_WINDOW_TOP=PASS (component order)`; `GLOBAL_TIME_WINDOW_VISIBLE=PASS (range text and navigator)`; `SINGLE_GLOBAL_TIMELINE=PASS`; `FIVE_CHARTS_SYNCED=PASS (shared props and source test)`; `COLLAPSED_CHART_TIME_SYNC=PASS`; `EVENT_TIME_SYNC=PASS (component behavior)`.
