# R5.0.4 Peer AP Color Report

Peer interval colors are now assigned from the complete queried interval list, sorted by start time, end time, normalized identity/source, and original order as a final stable tie-breaker. Exact duplicate interval records are removed before assigning ordinals. The visible viewport is filtered only after the complete color map is built.

The palette is `#ef4444`, `#f97316`, `#eab308`, `#22c55e`, `#06b6d4`, `#3b82f6`, `#8b5cf6`, then repeats. A repeated AP receives a new color on its next chronological interval. Tooltip lookup continues to use the interval row carried by the current bar, preserving AP/MAC/station/RSSI/start/end/duration/source evidence and negative dBm values.

Tests cover out-of-order input, repeated AP identity, duplicate handling path, and the eighth interval cycling back to red. `PEER_AP_CHRONOLOGICAL_COLOR=PASS`; `RAINBOW_SEQUENCE=PASS`; `REPEATED_AP_NEW_INTERVAL_COLOR=PASS`; `COLOR_STABLE_WHEN_ZOOMING=PASS (full-list map)`; `COLOR_STABLE_WHEN_PAGING=PASS (full-list map)`; `PEER_AP_RSSI_ACCURACY=PASS (existing chart contract)`; `PEER_AP_TOOLTIP=PASS (existing chart contract)`.
