# NetConsole Product

NetConsole is a local Windows desktop tool for network device management.

Current product direction:

- Python 3.13
- PySide6 desktop UI
- SQLite local storage
- Development and portable runtime layout
- Local files only, no AppData dependency

The first stage only delivers a usable device management foundation. It is intended for UI testing, table inspection, import/export verification, and future desktop packaging work.

Current scope:

- Main window
- Chinese/English text switching
- Demo site
- SQLite `devices` table
- Demo devices
- Device list, add, edit, delete
- Search and filters
- CSV import/export
- CSV template export

Out of scope for this stage:

- SSH
- Telnet execution
- Netmiko
- Task center
- Config backup
- Config diff
- Terminal
- SNMP collection
- Optical modules
- LLDP
- Topology
