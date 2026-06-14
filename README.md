# NetConsole Desktop Qt Edition

NetConsole is a local Windows desktop application for network device management. The current edition is a fresh PySide6 desktop implementation using SQLite for local data.

## Python Version

Use Python 3.13.

## Install Dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Start

```powershell
python main.py
```

Or:

```powershell
.\project\scripts\dev_run.ps1
```

## Test

```powershell
pytest
```

Or:

```powershell
.\project\scripts\test.ps1
```

## Data Directory

Development and future portable builds use the project-local `data/` directory.

```text
data/
  sites/
    demo/
      db/
        devices.db
      raw/
      parsed/
      reports/
      backups/
      tasks/
      metrics/
```

The SQLite database for the demo site is:

```text
data/sites/demo/db/devices.db
```

`metrics/` is only reserved in this stage. No metrics database is created.

## Demo Site Data

`demo` is the built-in demonstration site for first startup, UI testing, feature display, and import/export verification.

If `data/sites/demo/db/devices.db` does not exist, the application creates the database, initializes the latest tables, and inserts demo devices. Device Facts, Interfaces, and LLDP demo data are generated only during this first database creation.

If `data/sites/demo/db/devices.db` already exists, the application uses it directly. It does not automatically add missing demo facts, interface data, LLDP data, or change the table structure. For development testing, delete `data/sites/demo/db/devices.db` manually and restart the application to regenerate the current demo database.

Demo devices cover:

- H3C SW: SSH + SNMPv2c
- H3C FIT-AP: Telnet + SNMPv2c
- H3C AC: SSH + Telnet + SNMPv1/v2c/v3
- Huawei SW: SSH
- Ruijie SW: SSH
- H3C FW: SSH + SNMPv3 AuthPriv

Each device has a `device_uuid`. The local `id` is only the auto-increment primary key inside `devices.db`; `device_uuid` is the stable identifier reserved for future cross-database references.

## Current Features

This stage only implements:

- Main window
- Chinese/English switching
- Demo site
- SQLite `devices` table
- Demo device data
- Device list
- Add/edit/delete
- Single-device Netmiko SSH/Telnet test connection
- Single-device H3C detail refresh from the Device Details window
- Search and filters
- CSV import/export
- CSV template export
- Read-only device details for the latest demo Device Facts, Interfaces, and LLDP neighbor data

Devices can enable SSH and Telnet independently. Test Connection and H3C detail refresh use SSH first when SSH is enabled, otherwise Telnet when Telnet is enabled. SNMPv1, SNMPv2c, and SNMPv3 are reserved configuration flags and can also be enabled independently. No terminal session, batch task, backup, SSH/Telnet command workflow, or SNMP collection is implemented yet.

CSV files use `utf-8-sig` encoding. The template export is a simplified Chinese-header CSV for manual entry and includes one example device row. Device export is a complete English-header CSV for backup and re-import.

Simplified template fields:

```text
设备名称, IP地址, 厂商, 站点/位置, 设备类型, SSH启用, SSH端口, Telnet启用, Telnet端口, 用户名, 密码, Enable密码, SNMPv1, SNMPv2c, SNMPv3, SNMP端口, SNMP只读团体字, SNMP读写团体字, 标签, 备注
```

Complete export starts with:

```text
id, device_uuid, name, sysname, station, device_vendor, device_type, ip_address, ssh_enabled, ssh_port, telnet_enabled, telnet_port
```

Imports support both the current template/export formats and legacy CSV files with `协议` and `端口` headers.

The default device export filename is:

```text
<site_name>_YYYY-MM-DD-HHMM.csv
```

Invalid filename characters are replaced with `_`.

## Not Implemented Yet

This stage does not implement terminal sessions, batch tasks, config backup, config diff, device collection/parsing, task center, SNMP collection, optical modules, LLDP collection, topology, or serial functionality.

## Manual Test: Netmiko Test Connection

1. Confirm the demo database has been rebuilt. For development testing, delete `data/sites/demo/db/devices.db` and restart the application if you need fresh demo data.
2. Start NetConsole with `python main.py`.
3. Open Device Management.
4. Select one demo device: AC, SW01, or SW02.
5. Click Test Connection.
6. Expected result: SSH login succeeds and the result dialog shows protocol, address, prompt, and elapsed time.

Demo devices:

```text
AC    10.0.0.51    admin / Admin@123
SW01  10.0.0.52    admin / Admin@123
SW02  10.0.0.53    admin / Admin@123
```

Pytest uses mocked Netmiko connections only. It must not connect to `10.0.0.51`, `10.0.0.52`, or `10.0.0.53`.

## Manual Test: H3C Device Detail Refresh

1. Confirm the demo database has been rebuilt if you need fresh demo data.
2. Start NetConsole with `python main.py`.
3. Open the demo site and Device Management.
4. Open Device Details for AC, SW01, or SW02.
5. Click Refresh.
6. Wait for the result dialog.
7. Confirm Overview, Interfaces, Optical Modules, and LLDP Neighbors refresh from the latest collection data.
8. Confirm raw logs are created under:

```text
data/sites/<site>/raw/collect/<collect_run_uuid>/<device_uuid>.log
data/sites/<site>/raw/collect/<collect_run_uuid>/<device_uuid>_commands.jsonl
```

Detail refresh runs these H3C commands:

```text
screen-length disable
display current-configuration | in sysname
display version
display device
display device manuinfo
display boot-loader
display interface
display transceiver interface
display transceiver diagnosis interface
display lldp neighbor-information list
display lldp neighbor-information verbose
```

Command failures are logged and later commands continue. Pytest uses fixture text and mocked Netmiko connections only.

Device facts prefer `display current-configuration | in sysname` for sysname, `display device` for model, and `display boot-loader` for boot image information. Device detail tables use logical interface sorting so `GigabitEthernet1/0/2` appears before `GigabitEthernet1/0/10`.

## Follow-Up Plan

Recommended next steps:

- Improve device form validation
- Add CSV import template under `project/resources/templates/`
- Add application icons under `project/resources/icons/`
- Prepare future PyInstaller portable packaging
- Add manual UI smoke checks
