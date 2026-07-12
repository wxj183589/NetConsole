# Database

NetConsole uses SQLite for local management data.

Main database path:

```text
.local/data/sites/<site_name>/db/devices.db
```

The schema in code is the current source of truth for a new database.

The built-in demonstration site is `demo`. If `.local/data/sites/demo/db/devices.db` does not exist, the application creates the latest tables and inserts demo devices plus Device Facts, Interfaces, and LLDP demo data.

If the database already exists, the application uses it directly and does not change its table structure or add missing demo fact data automatically. For development testing, delete `.local/data/sites/demo/db/devices.db` manually and restart the application to regenerate the current demo database. No database upgrade or demo backfill logic is used.

Current local tables:

- `devices`
- `collect_runs`
- `device_facts`
- `device_interfaces`
- `device_lldp_neighbors`

## Device Identity

- `id`: local auto-increment primary key inside `devices.db`
- `device_uuid`: stable UUID string for future cross-database references

Future task, config, and metrics data should reference devices by `device_uuid`, not by the local `id`.

## SSH And Telnet

Devices can support SSH and Telnet at the same time:

- `ssh_enabled`, `ssh_port`
- `telnet_enabled`, `telnet_port`

At least one of SSH or Telnet must be enabled. SSH is enabled by default on port `22`; Telnet is disabled by default on port `23`.

## SNMP Reserved Fields

SNMP versions are independent flags:

- `snmp_v1_enabled`
- `snmp_v2c_enabled`
- `snmp_v3_enabled`

SNMPv2c is enabled by default. SNMPv3 keeps reserved auth/privacy fields, including `snmpv3_auth_password` and `snmpv3_priv_password`. No SNMP collection is implemented in this stage.

SNMPv3 auth protocol options are `MD5` and `SHA`. Privacy protocol options are `DES56`, `3DES`, `AES128`, `AES192`, and `AES256`. CSV import maps old `DES` to `DES56` and old `AES` to `AES128`.

## CSV

CSV import supports two structures:

- Simplified template CSV: one Chinese header row, one example row, then user-entered device data
- Complete export CSV: one English header row with all database fields, then device data

The simplified template fields are:

```text
设备名称, IP地址, 厂商, 站点/位置, 设备类型, SSH启用, SSH端口, Telnet启用, Telnet端口, 用户名, 密码, Enable密码, SNMPv1, SNMPv2c, SNMPv3, SNMP端口, SNMP只读团体字, SNMP读写团体字, 标签, 备注
```

The complete export fields are:

```text
id, device_uuid, name, sysname, station, device_vendor, device_type, ip_address, ssh_enabled, ssh_port, telnet_enabled, telnet_port, auth_mode, username, password, snmp_v1_enabled, snmp_v2c_enabled, snmp_v3_enabled, snmp_port, snmp_ro_community, snmp_rw_community, snmpv3_security_level, snmpv3_auth_protocol, snmpv3_auth_password, snmpv3_priv_protocol, snmpv3_priv_password, tags, remark, created_at, updated_at
```

Legacy CSV files with `协议` and `端口` headers are still accepted as import input and mapped to SSH or Telnet fields.

## Metrics

High-frequency collection data is reserved for future files under:

```text
.local/data/sites/<site_name>/metrics/YYYY-MM.db
```

No metrics database is created in this stage.
