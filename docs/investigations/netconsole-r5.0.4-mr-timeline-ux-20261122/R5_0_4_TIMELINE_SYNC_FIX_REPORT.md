# R5.0.4 Supplemental Timeline Sync Fix

## Scope

This supplemental fix closes the gap between the shared Vue viewport state and the native ECharts dataZoom state for the five playback charts:

- global navigator;
- primary management-IP heartbeat RTT/loss;
- backup management-IP heartbeat RTT/loss;
- primary simulated Quick Ping;
- backup simulated Quick Ping;
- Peer AP RSSI interval chart.

The primary and backup heartbeat charts remain backed by the real monitoring response. Quick Ping remains explicitly renderer-only simulated data and does not access the network or write history.

## Implementation evidence

- Quick Ping now receives the complete queried domain and emits absolute ISO timestamps for both ECharts `startValue/endValue` and percentage-based dataZoom payloads.
- Quick Ping replaces `xAxis` and `dataZoom` together with the series and y-axis, so parent viewport updates reach the native chart instance.
- All programmatic chart `setOption` calls use `silent: true`; a chart reacting to a parent viewport update cannot create a dataZoom feedback loop.
- Hover/cursor movement updates only the shared cursor. Event-row activation continues to recenter the shared viewport through `locate`.
- Primary/backup heartbeat charts use the same absolute time-domain and two-series color contract as the Quick Ping presentation while retaining their real-data source.

## Verification

```text
GROUND_UNATTENDED_TESTS=PASS (6 files, 20 tests)
QUICK_PING_SYNC_OPTION_TEST=PASS (absolute domain and dataZoom contract)
GROUND_HISTORY_SHARED_VIEWPORT_TEST=PASS (viewport and cursor fan-out to chart stubs)
RENDERER_BUILD=PASS
ELECTRON_TYPECHECK=PASS
DIFF_CHECK=PASS
WORKSPACE_LAYOUT_CHECK=FAIL (pre-existing unmanaged worktree directories; no cleanup performed)
GUI_NATIVE_FIVE_CHART_INTERACTION=NOT_VERIFIED
GUI_1920X1080=NOT_VERIFIED
GUI_2560X1440=NOT_VERIFIED
```

No production data, real devices, or business history records were accessed or modified by this supplemental validation.
