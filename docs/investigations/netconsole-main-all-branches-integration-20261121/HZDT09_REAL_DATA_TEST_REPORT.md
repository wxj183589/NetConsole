# hzdt-09 Real Data Test Report

The DEV site database was queried read-only for evidence. `PRAGMA integrity_check` returned `ok`. The site contains 117 devices, 189 AP entities, 327 collection runs, 1,890 recent FIT-AP resource rows, 3,624 radio history rows, 2,501 interface history rows, 783 LLDP history rows, 4,335 optical history rows, 2,371 MAC aliases, and 509 extension points.

These records establish real historical data availability for site loading and playback. No mock data was inserted and no production root was accessed. GUI-level metric-by-metric interaction remains pending manual user inspection.
