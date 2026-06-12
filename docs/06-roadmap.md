# Roadmap

## Current Stage

Deliver a real local desktop application foundation:

- PySide6 main window
- Device management
- Demo site
- SQLite `devices` table
- Demo devices for UI verification
- CSV import/export
- pytest coverage for non-UI logic

## Next Stage

Recommended next work:

- Polish device form validation
- Add import template generation under `resources/templates/`
- Add more manual UI smoke checks
- Prepare PyInstaller packaging in `scripts/build_portable.ps1`
- Add application icon resources

## Later Stages

Future modules can be considered after the device management foundation is stable:

- SSH/Telnet connection support
- Netmiko integration
- Terminal
- Task center
- Config backup
- Config diff
- SNMP collection
- Optical modules
- LLDP
- Topology

These modules are not implemented in the current stage.
