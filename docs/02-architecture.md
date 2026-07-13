# Architecture

The authoritative architecture is [ARCHITECTURE.md](ARCHITECTURE.md). This numbered document is retained for compatibility.

NetConsole adopts the following target layers for all new and migrated code:

```text
apps/desktop_qt -> src/netconsole/presentation/qt
apps/web -> src/netconsole/api
presentation/qt and api -> application -> domain
infrastructure -> application ports and domain
```

- `domain` contains framework-free models, rules, and value objects.
- `application` contains use cases, ApplicationService, DTOs, and port interfaces.
- `infrastructure` contains SSH, SNMP, database, file, process, network, parser, and report implementations.
- Qt and FastAPI are adapters that call the same ApplicationService; Qt pages do not implement collection, parsing, database, or report business logic.

The existing `apps/desktop`, `src/netconsole/ui`, `backend/api`, `services`, `repositories`, `parsers`, and `adapters` directories are compatibility locations under gradual migration, not the target structure. Modules migrate when they are changed; there is no one-time repository rewrite.

`PathResolver` owns project and runtime paths. Application code should request paths from `PathResolver` instead of scattering path strings through feature modules.

The built-in demonstration site is named `demo`. Its database is:

```text
.local/data/sites/demo/db/devices.db
```

When this database file is missing, the app creates the latest `devices` table and inserts demo devices. When it already exists, the app uses it directly and does not change its table structure automatically.
