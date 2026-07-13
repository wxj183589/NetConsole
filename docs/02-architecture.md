# Architecture

NetConsole Desktop Qt Edition is a local desktop application.

```text
main.py
  |
  v
src/netconsole/app.py
  |
  v
PySide6 MainWindow
  |
  +-- Device Management Page
  +-- Device Dialog
  +-- Device Table
  |
  v
DeviceRepository
  |
  v
SQLite .local/data/sites/<site_name>/db/devices.db
```

Main layers:

- `src/netconsole/core/`: paths, sites, database setup, application bootstrap, i18n
- `src/netconsole/models/`: data models
- `src/netconsole/repositories/`: SQLite persistence
- `src/netconsole/services/`: import/export and demo data
- `src/netconsole/ui/`: PySide6 windows, pages, dialogs, and widgets

`PathResolver` owns project and runtime paths. Application code should request paths from `PathResolver` instead of scattering path strings through feature modules.

The built-in demonstration site is named `demo`. Its database is:

```text
.local/data/sites/demo/db/devices.db
```

When this database file is missing, the app creates the latest `devices` table and inserts demo devices. When it already exists, the app uses it directly and does not change its table structure automatically.
