# R5.0.3 hzdt-09 DEV Startup Report

The existing independent DEV instance was not restarted. Runtime logs at `D:\NetConsoleRuntime-dev\R5.0.1\logs` show:

- `data_root=D:\NetConsoleData-dev environment=DEVELOPMENT`
- `site=hzdt-09 database_path=D:\NetConsoleData-dev\sites\hzdt-09\db\devices.db`
- `GROUND_COLLECTION_DISABLED ... mode=playback_only`
- Electron `backend.health_ready`, `renderer.mounted`, and `desktop.interactive`
- tray site synchronization for `hzdt-09`

`site_meta.json` identifies `杭州地铁9号线`. SQLite inspection used a read-only connection; no device listener, SSH relay, ARP, or现场采集 was started by this run.

`DEV_DATA_ROOT=D:\NetConsoleData-dev`; `DEV_SITE=hzdt-09`; `DEV_RUNTIME_ROOT=D:\NetConsoleRuntime-dev\R5.0.1`; `DEV_MODE_VERIFIED=PASS`; `HZDT09_SITE_LOADED=PASS`; `BACKEND_HEALTH=PASS`; `RENDERER_MOUNTED=PASS`; `DESKTOP_INTERACTIVE=PASS`.
