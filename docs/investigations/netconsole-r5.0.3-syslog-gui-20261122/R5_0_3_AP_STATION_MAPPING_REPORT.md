# R5.0.3 AP and Station Mapping Report

Heartbeat projection consumes explicit peer identity fields (`peer_ap_name`, BSSID/MAC, station, section) and de-duplicates exact tuples. Fresh Syslog uses its explicit AP identity and station/section fields. No fuzzy name or cross-site fallback is introduced in this path; missing values remain empty/unknown.

The `hzdt-09` database contains 189 FIT AP resources, 189 AP entities, 378 radio-current rows, and 251 current LLDP neighbor rows. These are read-only inspection counts from a read-only SQLite connection. Renderer heartbeat and Syslog presentation tests passed.

`AP_MAC_MAPPING=PASS (explicit identity contract)`; `AP_NAME_MAPPING=PASS (unique explicit field only)`; `STATION_MAPPING=PASS/UNKNOWN when source absent`; `REAL_DATA_RECORD_TRACE=hzdt-09 archive and devices.db`.
