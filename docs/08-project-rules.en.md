# NetConsole Project Rule Index and Recurring Conventions

This file keeps the legacy `08` entry point, but active rules no longer come from the historical Qt documents. Use the repository `AGENTS.md`, [Development Rules](DEVELOPMENT_RULES.md), [Repository Layout](development/repository-layout.md), and the relevant topic document as the current authority. Legacy Qt/QThread/QWidget rules are only historical evidence in the [Qt -> Electron archive](archive/migrations/qt-to-electron/README.md).

## Evidence Order

When deciding status or updating docs, use this order:

1. Current production code, Feature Registry, PathResolver, and build scripts.
2. Current tests, architecture guards, release scripts, and fixtures.
3. Current topic docs, README files, migration matrix, and archive reports.
4. Git history and historical plans.

Read the version only from `src/netconsole/core/version.py`, user-visible features only from `src/netconsole/core/feature_registry.py`, and data paths only from `src/netconsole/core/paths.py`. Documentation paths for source files use `src/netconsole/...`; use `netconsole.*` only for Python imports or package names.

## Active Architecture Boundary

- The only formal desktop product is Electron Main + Preload + Vue + FastAPI/Python Core. Qt/PySide6/QFluentWidgets source, runtime, dependencies, test fixtures, startup probes, and fallback entries must not be reintroduced.
- Running `main.py` without arguments starts the source Electron Desktop. `--mode web|server` is local development diagnostics only, not a second product runtime.
- Vue owns layout, input, tables, charts, and display formatting. Electron owns windows, managed lifecycle, and the allowlisted Native Bridge. FastAPI routers only perform auth, DTO mapping, Application Service calls, and response mapping.
- Device commands, SSH/Telnet/SNMP, SQLite, parsers, exports, compression, collection state machines, AP matching, and rail-transit business rules belong in Python Core Application/Domain/Repository/Parser/Adapter boundaries.
- IO, CPU, network, parsing, compression, large queries, and batch work that can exceed 300 ms goes through Job Center. All formal exports use the separate Export Process.

## Repository and Runtime Data

- Business code lives in `src/netconsole`; Electron, Web, and Agent live in `apps/desktop_electron`, `apps/web`, and `apps/agent`. Do not recreate historical or vague directories such as `apps/desktop`, `src/netconsole/ui`, `frontend`, `desktop`, `netconsole`, or `project`.
- The repository root only keeps project-level config, entries, and allowlisted directories. Runtime data, logs, SQLite files, captures, collection output, temporary exports, and formal reports must not be committed.
- Locate paths through `PathResolver`, resource helpers, or the script's own location. Do not use `Path.cwd()` for source, resources, config, or runtime data, and do not patch `sys.path` to hide package layout problems.
- Development data uses a controlled local data root or `.local/`; packaged builds use the system app data directory or a user-selected export directory. Historical migration and cleanup must be dry-run, manifest-based, and allowlisted. Never silently delete user databases, raw logs, sessions, or formal reports.
- When adding directories, moving files, or changing Agent/tool/build paths, also check imports, tests, build arguments, frontend working directories, Agent entries, doc links, and resource resolution.

## Features, UI, and Tables

- New user-visible modules, pages, tabs, actions, or buttons must be registered in Feature Registry. Pages use FeatureGate/config for visibility, but Feature state never replaces backend auth or safety checks.
- User-facing text belongs in i18n. Credentials, tokens, communities, private keys, device passwords, and unsanitized identity samples must not enter API responses, task results, localStorage, or normal logs.
- New tables default to `NcDataTable + NcTableColumn`. Missing values display as `—`, while real zero values remain `0`. Do not add direct `el-table` pages; new or migrated tables must update `docs/ui/TABLE_INVENTORY.md` and include focused tests.
- Column widths are calculated by shared components from headers, sampled content, icon/tag/button chrome, and the visible area in two phases. If the container is too narrow, use horizontal scrolling; never compress headers or multiply string length by a fixed pixel value.
- Status colors, themes, the sidebar, Element Plus, and ECharts use Design Tokens. Automated tests do not replace Electron visual checks across sizes, scaling, light, dark, and system modes.

## Tasks, Artifacts, and Native Bridge

- Task DTOs and results must not leak local absolute paths, task secrets, device credentials, or backend tokens. The task window accepts only controlled `taskId/module/status`.
- Electron Native Bridge is limited to allowlisted actions: file/directory/save-path pickers, controlled artifact downloads, temporary capability opening, HTTPS external links, settings tool selection, and controlled settings actions. It must not provide generic commands, arbitrary paths, arbitrary URLs/headers, full `ipcRenderer`, or shell arguments.
- The Renderer cannot open local paths directly. Artifact downloads are handled by Electron Main with an in-memory token, streamed `.part` output, atomic replacement, and short-lived type-specific capabilities. Save-only files may receive no open/reveal capability.
- Export, device-file, config snapshot, MESH, Online MR, and network-tool downloads must reuse formal Artifact endpoints. Electron Main/Preload must not read databases, generate reports, or interpret business files.

## Commands, SNMP, and Device Files

- `resources/command_reference.json` and the Command Reference page are read-only catalogs, not execution allowlists.
- Production commands must be in versioned Command Profiles with Operation, step, selector, parser/DTO contract, risk level, and validation evidence. Unknown vendors, roles, platforms, software versions, or unverified profiles must fail closed.
- Stable profiles currently include read-only `device.inventory.collect` and controlled-write `device.sftp.enable`. Except for explicit profiles, pages, routers, and generic services must not execute arbitrary CLI.
- SNMP only exists as device-management v1/v2c read-only basic identification. SNMPv3, RW community, SET, Trap, generic MIB/OID dictionaries, generic collection platforms, and SNMP Center remain forbidden.
- The device-file page stays read-only SFTP: connect, disconnect, browse, refresh, select, and download. Auto-enabling SFTP is a separate controlled `config_write` device operation requiring user authorization, a confirmed unavailable SFTP subsystem, and an exact `device.sftp.enable` profile. It must not be an implicit side effect of file browsing.

## Rail-Transit Boundaries

- Rail-transit base data is maintained through `/rail-transit/base-data` and starts locked. Writes require Feature, environment/session authorization, target scope, revision checks, and backend transactions. Formal data, imported candidates, and runtime data must not masquerade as each other.
- Base data does not create a second database. Stations/sections, trackside APs, onboard MRs, and planning data reuse the current site's `devices.db`; failures must fully roll back and preserve the frontend edit buffer.
- `/rail-transit/train-communication` is the fixed onboard TC1/TC2 six-node communication page, not the wireless dashboard. It must not aggregate trackside AP, RSSI, fping, iPerf, Online MR, Agent, or Mesh-Link data.
- AP Identity remains read-only shadow/diagnostics. It must not take over production matching, page display, export fields, or database writes. Unavailable or failed diagnostics must not change the original Job/Export terminal state.

## Validation and Release

- During development, run the focused pytest, Vitest, Ruff, Go test, Electron test/typecheck/build/smoke, or architecture single gate that directly covers the change. Full pytest, full frontend test/build, Package Smoke, and the nine architecture gates run on the final real code combination.
- Tests must not read or write `D:\NetConsoleData`, formal site databases, real sessions, or reports. Use `D:\NetConsoleTestData\<run-id>`, fake services, or an explicit test `NETCONSOLE_DATA_ROOT`.
- Electron-only release gates include the nine architecture guards, no Qt dependency/resource/license residue, locked Python constraints, SBOM/Notice, allowlisted local fping/iPerf tools, package smoke, and Windows graphical manual validation.
- Architecture exceptions must be exact to `rule_id + path` and include reason, owner domain, creation time, expiry time, and test. Directory wildcards, stale exceptions, and deleting tests to pass are forbidden.

## High-Confidence Additions This Week (2026-07-13 to 2026-07-20)

- Electron-only work has moved from parallel migration to active product boundary: Qt is now historical evidence only, not a test, dependency, runtime, or fallback path.
- The unified task window, controlled artifact downloads, and Native Bridge capabilities are the default cross-module interaction model; local paths and credentials do not return to the Renderer.
- All 77 standard Web tables have moved to the shared table component. Future tables must update the inventory and focused tests in the same change.
- Data root, Site Registry, `.ncsite`, backup/restore, and migration are managed by Python Application Services. Install, uninstall, and upgrade must not delete the user data root or Electron bootstrap.
- Rail-transit base-data editing, fixed communication topology, and controlled SFTP enablement now have explicit boundaries, but real-device, real-site, and Electron visual validation still need separate records. Fake or unit tests cannot replace them.
