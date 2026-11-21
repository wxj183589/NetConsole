# R5.0.4 UI Design Report

R5.0.4 is scoped to the historical playback Renderer. The backend Syslog, Heartbeat and Quick Ping contracts are unchanged.

- `GroundHistoryPlayback.vue` now presents the current global window immediately after MR identity and before all chart regions.
- RTT/loss, simulated Quick Ping and Peer AP regions remain vertically stacked and keep their existing chart semantics.
- The top navigator shows the selected visible range and remains the only owner of viewport state (`visibleStart`, `visibleEnd`, `cursorTime`).
- Collapse transitions only affect presentation; they do not call `query()` or regenerate Quick Ping rows.

`UI_LAYOUT=PASS (source and targeted component tests)`; native Electron click-through remains a separate acceptance gate.
