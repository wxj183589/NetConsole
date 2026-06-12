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

If `data/sites/demo/db/devices.db` does not exist, the application creates the database, initializes the latest `devices` table, and inserts demo devices. If it already exists, the application uses it directly and does not change the table structure automatically.

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
- Search and filters
- CSV import/export
- CSV template export

Devices can enable SSH and Telnet independently. SNMPv1, SNMPv2c, and SNMPv3 are reserved configuration flags and can also be enabled independently. No real SSH, Telnet, or SNMP collection is implemented yet.

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

This stage does not implement SSH, Telnet execution, Netmiko, task center, config backup, config diff, terminal, SNMP collection, optical modules, LLDP, topology, or serial functionality.

## Follow-Up Plan

Recommended next steps:

- Improve device form validation
- Add CSV import template under `project/resources/templates/`
- Add application icons under `project/resources/icons/`
- Prepare future PyInstaller portable packaging
- Add manual UI smoke checks
