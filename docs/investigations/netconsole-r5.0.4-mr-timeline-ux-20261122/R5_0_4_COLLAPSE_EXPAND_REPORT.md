# R5.0.4 Collapse/Expand Report

The playback page has five independent default-expanded states:

1. primary management IP RTT/loss;
2. backup management IP RTT/loss;
3. primary simulated Quick Ping;
4. backup simulated Quick Ping;
5. Peer AP active interval RSSI.

The backup sections are no longer coupled. A missing backup IP still produces no backup RTT or backup Quick Ping region. Collapsing a region leaves the title bar, preserves `visibleStart`, `visibleEnd`, and `cursorTime`, and does not issue a history request. Re-expanding mounts the chart with the current global window.

Targeted behavior coverage verifies five toggles and independent chart removal. The transition uses bounded opacity/max-height animation and the chart component's existing mount/resize lifecycle.

`MAIN_RTT_COLLAPSIBLE=PASS`; `BACKUP_RTT_COLLAPSIBLE=PASS`; `MAIN_QUICK_PING_COLLAPSIBLE=PASS`; `BACKUP_QUICK_PING_COLLAPSIBLE=PASS`; `PEER_AP_COLLAPSIBLE=PASS`.
