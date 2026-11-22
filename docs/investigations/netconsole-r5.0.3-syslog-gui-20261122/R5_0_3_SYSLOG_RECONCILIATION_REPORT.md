# R5.0.3 Syslog Reconciliation Report

The inspected service path is `GroundUnattendedApplicationService._heartbeat_association_projection()` and `ground_unattended.ac_reconciliation`. Fresh Syslog requires `FRESH`, `VALID`, `EXACT_IDENTITY`, and an explicit AP name or MAC; otherwise the projection falls back to explicit AC Mesh-Link peer observations and reports the source/reason. Future evidence is rejected and stale evidence is not presented as the active AP.

Targeted reconciliation, position projection, monitoring, heartbeat, and Syslog tests passed. The DEV runtime log records archive Syslog queries for `site_id=hzdt-09` and no collection listener was started. Boundary behavior is detailed in `R5_0_3_120S_BOUNDARY_TEST_REPORT.md`.

`SYSLOG_MR_ISOLATION=PASS (unit coverage)`; `SYSLOG_SITE_ISOLATION=PASS (site-scoped service/query contracts)`; `SYSLOG_TO_MESHLINK_FALLBACK=PASS (unit coverage)`; `MESHLINK_TO_SYSLOG_RECOVERY=PASS (freshness projection coverage)`.
