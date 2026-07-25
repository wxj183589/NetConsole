# Database

NetConsole uses SQLite for local management data.

Main database path relative to the active application data root:

```text
sites/<site_name>/db/devices.db
```

The schema in code is the current source of truth for a new database.

The built-in demonstration site is `demo`. If `sites/demo/db/devices.db` does not exist in an explicitly initialized test or demo root, the application creates the latest tables and inserts demo devices plus Device Facts, Interfaces, and LLDP demo data. Persistent production roots never silently create a second empty data tree.

If the database already exists, `Database.initialize()` applies only additive, idempotent schema updates and records `schema_metadata`; it does not backfill demo facts or delete existing rows. The current migration adds the non-secret device credential state table without rewriting existing device credentials. Never delete a user database to apply an upgrade. Development fixtures must use a temporary data root.

Current schema version: `2026.07.24.device_credential_state`. The prior query-plan evidence and rollback boundaries remain recorded in [the E6 database archive](archive/migrations/electron-only/E6-2026-07-18.md).

Current local tables:

- `devices`
- `collect_runs`
- `device_facts`
- `device_interfaces`
- `device_lldp_neighbors`
- `device_credential_states`

## Device Identity

- `id`: local auto-increment primary key inside `devices.db`
- `device_uuid`: stable UUID string for future cross-database references

Future task, config, and metrics data should reference devices by `device_uuid`, not by the local `id`.

## SSH And Telnet

Devices can support SSH and Telnet at the same time:

- `ssh_enabled`, `ssh_port`
- `telnet_enabled`, `telnet_port`

At least one of SSH or Telnet must be enabled. SSH is enabled by default on port `22`; Telnet is disabled by default on port `23`.

## Device Credential State

Device secrets continue to use the existing local `devices` table storage model. This release does not add DPAPI, a master key, encryption, or a second credential database.

`device_credential_states` stores only non-secret migration state keyed by `device_uuid + credential_field`: `available / missing / needs_reentry / key_file_missing`, source, safe error code and update time. A `sanitized_share`, field package, return package or legacy credential-free `.ncsite` clears `password`, SSH/Telnet passwords, SNMP community and tunnel passwords, then records `needs_reentry / imported_reference / CREDENTIAL_REENTRY_REQUIRED` for affected devices. Connection preflight refuses to create a task until the required local credentials are entered again. A v4 `full_migration` package is an unencrypted ordinary ZIP containing the complete database and therefore restores complete credentials without setting `needs_reentry`; it does not accept a migration password or contain `payload.enc`.

Device editing keeps an existing secret when its password input is unchanged, replaces it only when a new non-empty secret is submitted, and deletes it only through an explicit clear field. A complete username/secret pair clears stale `needs_reentry`; additive database initialization repairs old incorrect markers only when the actual secret remains present and usable. Ordinary list/detail/edit-profile DTOs expose configuration booleans rather than stored plaintext secrets. Only an authenticated Electron desktop session on `127.0.0.1` can request one selected field through the explicit reveal action; the value is cleared from Renderer form memory when the editor closes. The package format does not change the existing local database-at-rest format.

## Device SNMP Fields

Device management supports read-only SNMP v1 and v2c only:

- `snmp_v1_enabled`
- `snmp_v2c_enabled`
- `snmp_port`
- `snmp_ro_community`
- `snmp_timeout_ms`
- `snmp_retries`

SNMPv2c is enabled by default. The active model, API and import/export contract do not support SNMPv3, read-write community strings or SNMP SET. Device SNMP is limited to connection testing and basic read-only identification.

Older databases may still contain retired SNMPv3 and read-write columns. Additive initialization does not drop or rewrite those columns, so existing user data remains intact; current repositories ignore them and never expose them through active DTOs. No destructive migration is performed merely to remove a product capability.

## CSV

CSV import and export use one versioned current template with a Chinese header row. Export omits secret columns unless the explicitly authorized caller requests a credential-bearing local export. The current fields are:

```text
设备名称, 主用地址, 备用地址, 协议, 端口, 用户名, 密码, 厂商, 设备类型, 分组, 归属站点, 是否启用SSH隧道, 隧道主机1地址, 隧道主机1端口, 隧道主机1用户名, 隧道主机1密码, 隧道主机2地址, 隧道主机2端口, 隧道主机2用户名, 隧道主机2密码, SNMP启用, SNMPv1, SNMPv2c, SNMP端口, SNMP只读团体字, SNMP超时毫秒, SNMP重试, 备注
```

`协议` 与 `端口` 映射为 SSH 或 Telnet。v1.3.8/早期 v1.3.9 的上一版合法模板仍可导入，缺少的设备 SNMP 字段按 v2c、161、2000 ms、1 次重试默认值补齐；其他未知或错列旧表头不会被猜测兼容。SNMPv3、RW community 和 SET 字段不接受导入，也不进入导出。

## Metrics

High-frequency collection data is reserved for future files under:

```text
sites/<site_name>/cache/metrics/YYYY-MM.db
```

No metrics database is created in this stage.
