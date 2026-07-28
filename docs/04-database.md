# Database

NetConsole uses SQLite for local management data.

Main database path relative to the active application data root:

```text
sites/<site_name>/db/devices.db
```

The schema in code is the current source of truth for a new database.

The built-in demonstration site is `demo`. If `sites/demo/db/devices.db` does not exist in an explicitly initialized test or demo root, the application creates the latest tables and inserts demo devices plus Device Facts, Interfaces, and LLDP demo data. Persistent production roots never silently create a second empty data tree.

If the database already exists, `Database.initialize()` applies only additive, idempotent schema updates and records `schema_metadata`; it does not backfill demo facts or delete existing rows. The current migration adds the non-secret device credential state table without rewriting existing device credentials. Never delete a user database to apply an upgrade. Development fixtures must use a temporary data root.

Current schema version: `2026.07.29.device_primary_address_identity`. The prior query-plan evidence and rollback boundaries remain recorded in [the E6 database archive](archive/migrations/electron-only/E6-2026-07-18.md).

The 2026-07-29 additive migration adds `devices.normalized_primary_address`.
Because every site has its own `devices.db`, the partial unique index on that
column enforces the business key "current site + normalized primary address";
the same address remains valid in another site database. Empty addresses are
excluded from the index. The stable database identity remains `id` together
with `device_uuid`; changing an address never rebuilds a device row.

Initialization normalizes existing non-empty primary addresses with Python's
standard IP parser, backfills the derived column, checks the complete final
set, and creates the index in one transaction. Before an existing site is
upgraded, SQLite Backup API writes a verified copy below
`files/backups/database-migrations/`. Invalid or duplicate historical
addresses stop the migration with the site, address, device IDs and names;
the original rows, schema version and indexes remain unchanged. The migration
never deletes, merges or selects one conflicting device.

The 2026-07-28 additive migration adds `admin_status`, `physical_status`,
`media_attribute`, `media_type`, and `category` to both current and historical
interface tables, together with port mode, Native/Tagged/Untagged VLAN,
PVID source/verification, collection status/time, and warning fields. It also
adds the ZTE LLDP brief/detail fields (scope, chassis and port identifiers,
holdtime/TTL, descriptions, capabilities, PVID, MAU, and maximum frame size) to
both LLDP tables. Initialization is idempotent and keeps all existing interface,
optical, LLDP, and history rows.

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
- `normalized_primary_address`: normalized IPv4/IPv6 business match key, unique only inside the current site's database

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

CSV import and export use one versioned current template with a Chinese header row. Export omits secret columns unless the explicitly authorized caller requests a credential-bearing local export. The current 30 fields are:

```text
设备名称, 主用地址, 备用地址, 协议, 端口, 用户名, 密码, 厂商, 设备类型, 分组, 归属站点, 是否启用SSH隧道, 隧道主机1地址, 隧道主机1端口, 隧道主机1用户名, 隧道主机1密码, 隧道主机2地址, 隧道主机2端口, 隧道主机2用户名, 隧道主机2密码, SNMP启用, SNMPv1, SNMPv2c, SNMP端口, SNMP只读团体字, SNMP超时毫秒, SNMP重试, 备注, 设备ID, 原主用地址
```

The 28-field predecessor and the earlier 21-field template remain importable.
`设备ID` is the preferred stable match when changing an address;
`原主用地址` allows matching the existing row before applying `主用地址`.
Without either field, `SITE_PRIMARY_IP` matches the normalized current address
inside the selected site. Explicit `DEVICE_NAME` matching remains available
but never participates implicitly in address matching.

Import exposes `UPDATE_ONLY` and `UPSERT`. An unmatched `UPDATE_ONLY` row is a
hard error and creates nothing; `UPSERT` may create it. Preview reports every
row as `CREATE / UPDATE / UNCHANGED / NOT_FOUND / CONFLICT / INVALID`, and any
hard error prevents all writes. Confirmation re-runs preview under one
`BEGIN IMMEDIATE` transaction. Empty cells preserve stored values, especially
credentials; `__CLEAR__` is the explicit clear marker. Stored credentials are
never included in ordinary exports.

`协议` 与 `端口` 映射为 SSH 或 Telnet。v1.3.8/早期 v1.3.9 的上一版合法模板仍可导入，缺少的设备 SNMP 字段按 v2c、161、2000 ms、1 次重试默认值补齐；其他未知或错列旧表头不会被猜测兼容。SNMPv3、RW community 和 SET 字段不接受导入，也不进入导出。

## Metrics

High-frequency collection data is reserved for future files under:

```text
sites/<site_name>/cache/metrics/YYYY-MM.db
```

No metrics database is created in this stage.
