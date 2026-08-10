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
- Source development, Electron development, the Python Backend, package validation, and formal installs all read the installer-registered `HKLM\Software\NetConsole\DataRoot` by default. `NETCONSOLE_DATA_ROOT` is only an explicit override. If the persistent root is missing, startup must fail instead of falling back to LocalAppData, user directories, the repository, the install directory, or system Temp.
- Automated tests, release smoke, and installer smoke must explicitly use `RuntimeMode.TEST` and a unique `D:\NetConsoleTestData\<run-id>`. They must not read the machine pointer, formal site databases, real sessions, or reports, and they may only clean up their own run-id.
- Historical migration and cleanup must be dry-run, manifest-based, allowlisted, and verified with SHA-256 plus SQLite `quick_check/integrity_check`. Same-path different-content files go to `migrations/conflicts/`; user databases, raw logs, sessions, and formal reports must never be silently overwritten or deleted.
- When adding directories, moving files, or changing Agent/tool/build paths, also check imports, tests, build arguments, frontend working directories, Agent entries, doc links, and resource resolution.

## Installer, Sites, and Packages

- The NSIS installer must classify the candidate data root before any write, then probe only inside that root with a unique temporary file, flush/close, same-directory rename, content readback, and cleanup. After a successful probe, it must not reject the directory merely because it contains ordinary files.
- The data-root page allows non-existent paths, empty directories, valid existing roots, and directories that contain non-conflicting ordinary files. It must not append a `NetConsoleData` child, rename the root, move files across volumes, overwrite manifests, or read/modify existing databases and collection files.
- Before publishing the registry pointer, the packaged Backend must atomically initialize the standard directories plus `config/storage-manifest.json`, or validate an existing manifest as compatible. Damaged, root-mismatched, or incompatible manifests fail installation while preserving the original files.
- Site Registry stable `site_id` and cross-machine `site_uuid` are the synchronization authorities. Display names are presentation only; imports, returns, and merges must not overwrite data by display name or local autoincrement IDs.
- v4 `full_migration` is an unencrypted ordinary ZIP with no migration password. It directly contains the site database plus device SSH/Telnet passwords, SNMP communities, and tunnel credentials, so it must only be stored in trusted locations. Sanitized share, field collection, collection return, and legacy no-credential packages must remove secrets and mark credentials for re-entry.
- `collection_return` may merge only after matching the same `site_uuid`, using stable UUIDs, task/event IDs, file SHA-256, and preflight conflict policy. Delete requests are recorded and shown by default; they do not automatically delete devices, APs, trains, raw files, reports, or history.
- Tray "quick site switch" only sends the target `site_id` intent back to Settings. It must reuse site-switch preflight, active-task blocking, workspace snapshots, Backend restart, and rollback. Electron Main does not accept site names or lists supplied by the Renderer.

## Features, UI, and Tables

- New user-visible modules, pages, tabs, actions, or buttons must be registered in Feature Registry. Pages use FeatureGate/config for visibility, but Feature state never replaces backend auth or safety checks.
- User-facing text belongs in i18n. Credentials, tokens, communities, private keys, device passwords, and unsanitized identity samples must not enter API responses, task results, localStorage, or normal logs.
- Tool Collection is an Electron Desktop-only launcher for user-selected third-party `.exe` files. It uses `module.tools` / `web.tool_collection` and independent Electron `userData` storage; it must not write into the Python Backend, site databases, the data root, `.ncsite`, or `.ncresult`, and launch/reveal requests pass only tool IDs.
- New tables default to `NcDataTable + NcTableColumn`. Missing values display as `—`, while real zero values remain `0`. Do not add direct `el-table` pages; new or migrated tables must update `docs/ui/TABLE_INVENTORY.md` and include focused tests.
- Column widths are calculated by shared components from headers, sampled content, icon/tag/button chrome, and the visible area in two phases. If the container is too narrow, use horizontal scrolling; never compress headers or multiply string length by a fixed pixel value.
- Status colors, themes, the sidebar, Element Plus, and ECharts use Design Tokens. Automated tests do not replace Electron visual checks across sizes, scaling, light, dark, and system modes.

## Tasks, Artifacts, and Native Bridge

- Task DTOs and results must not leak local absolute paths, task secrets, device credentials, or backend tokens. The task window accepts only controlled `taskId/module/status`.
- Worker JSONL frames have a hard `1,048,576 bytes` limit. Normal task terminal results return bounded summaries only; full large lists, raw echoes, diffs, config text, and detail rows must be read through Repository pagination, managed Artifacts, or domain query APIs instead of raising the protocol limit.
- User-final export copies must first register a fixed action in `exportActionRegistry.ts` and then reuse `useUserSelectedExport`. If the user cancels the save-path dialog, no task is created, no Artifact is generated, and no success message is shown; save retry reuses the same Artifact.
- User-visible imports must use Browser `File/FileList` or Electron Main-specific pickers. Cancellation does not call the backend, file inputs are cleared after processing, and frontend extension filters never replace backend file-contract, schema, non-empty-data, and ZIP traversal validation.
- Electron Native Bridge is limited to allowlisted actions: file/directory/save-path pickers, controlled artifact downloads, temporary capability opening, HTTPS external links, settings tool selection, and controlled settings actions. It must not provide generic commands, arbitrary paths, arbitrary URLs/headers, full `ipcRenderer`, or shell arguments.
- The Renderer cannot open local paths directly. Artifact downloads are handled by Electron Main with an in-memory token, streamed `.part` output, atomic replacement, and short-lived type-specific capabilities. Save-only files may receive no open/reveal capability.
- Export, device-file, config snapshot, MESH, Online MR, and network-tool downloads must reuse formal Artifact endpoints. Electron Main/Preload must not read databases, generate reports, or interpret business files.

## Commands, SNMP, and Device Files

- `resources/command_reference.json` and the Command Reference page are read-only catalogs, not execution allowlists.
- Production commands must be in versioned Command Profiles with Operation, step, selector, parser/DTO contract, risk level, and validation evidence. Unknown vendors, roles, platforms, software versions, or unverified profiles must fail closed.
- Stable profiles currently include read-only `device.inventory.collect` and controlled-write `device.sftp.enable`. Except for explicit profiles, pages, routers, and generic services must not execute arbitrary CLI.
- SNMP only exists as device-management v1/v2c read-only basic identification. SNMPv3, RW community, SET, Trap, generic MIB/OID dictionaries, generic collection platforms, and SNMP Center remain forbidden.
- The device-file page stays read-only SFTP: connect, disconnect, browse, refresh, select, and download. Auto-enabling SFTP is a separate controlled `config_write` device operation requiring user authorization, a confirmed unavailable SFTP subsystem, and an exact `device.sftp.enable` profile. It must not be an implicit side effect of file browsing.
- The ZTE trackside-switch Adapter currently declares real-device validation only for C89E-4 Release read-only collection; do not generalize it to all ZXR10/5960X models. Normal detail collection uses the fixed seven-command read-only Profile, while the trackside optical fast path runs only `show version` and one `show opticalinfo brief` per device. Config writes, per-port detail collection, and unverified models must fail closed or remain pending validation.

## Rail-Transit Boundaries

- Rail-transit base data is maintained through `/rail-transit/base-data` and starts locked. Writes require Feature, environment/session authorization, target scope, revision checks, and backend transactions. Formal data, imported candidates, and runtime data must not masquerade as each other.
- Base data does not create a second database. Stations/sections, trackside APs, onboard MRs, and planning data reuse the current site's `devices.db`; failures must fully roll back and preserve the frontend edit buffer.
- `/rail-transit/train-communication` is the fixed onboard TC1/TC2 six-node communication page, not the wireless dashboard. It must not aggregate trackside AP, RSSI, fping, iPerf, Online MR, Agent, or Mesh-Link data.
- Each train-communication point table may contain only the six nodes `TC1-MR/TC1-SW/TC1-SRV/TC2-MR/TC2-SW/TC2-SRV`; saves use a SHA-256 revision. The generation task returns an edit-buffer preview only, always with `save_result=false`. `COMPLETED` does not mean the preview is usable; missing or invalid nodes must leave the current edit buffer unchanged.
- Trackside AP per-station planning uses "one station, one row" as the active model. It maintains only sequence, stable `station_id`, AP count, management VLAN, and notes. Management VLAN is a business property, not an identity key; shared VLANs and AP count `0` are valid, legacy VLAN-group tables are retained only for compatibility, and an empty per-station plan must not be revived from historical data.
- Ground Unattended is an independent `/rail-transit/ground-unattended` page and `web.ground_unattended` Feature. It does not reuse the manual Online MR page state and does not compress all-day unattended operation into one Online MR Session. Page unload stops only polling; when the Electron main window hides to the tray, the Backend, AC polling, fleet ping, and deep collection continue.
- Ground Unattended scheduling must use structured mainline classification, multi-target fping sharding, typed Online MR requests, concurrency budgets, coverage rounds, atomic ZIP archiving, and startup recovery. Real AC/MR, long-running fping, tray-hidden execution, and leftover-process checks remain manual field gates.
- The unified AP Identity index now handles high-volume Peer/BSSID resolution for MESH, Ground, Online/Vehicle MR, and wireless scan. AC Mesh-Link, direct Identity joins in base-data queries, trackside AP business, report reads, and device/LLDP binding remain P1/P2 work in the consumer audit. Normal queries only read the existing index in `devices.db`; they do not connect to AC, run SSH/SNMP, or call `ensure/rebuild` during GET. `unresolved/ambiguous` results must keep the original observation and diagnostic reason.

## Validation and Release

- During development, run the focused pytest, Vitest, Ruff, Go test, Electron test/typecheck/build/smoke, or architecture single gate that directly covers the change. Full pytest, full frontend test/build, Package Smoke, and the nine architecture gates run on the final real code combination.
- Tests must not read or write `D:\NetConsoleData`, formal site databases, real sessions, or reports. Use `D:\NetConsoleTestData\<run-id>`, fake services, or an explicit test `NETCONSOLE_DATA_ROOT`.
- Electron-only release gates include the nine architecture guards, no Qt dependency/resource/license residue, locked Python constraints, SBOM/Notice, allowlisted local fping/iPerf tools, package smoke, and Windows graphical manual validation.
- Formal NSIS builds must start from a committed, clean worktree whose `HEAD` has been pushed to the current upstream. The final installer name contains the Git short commit, and the PE identity, embedded installer manifest, data-root include hash, Backend/Frontend commits, and two SHA-256 reads must match the current build inputs.
- The automated release manifest must keep `real_windows_install_status=PENDING` until isolated Windows GUI validation covers non-existent directories, empty directories, ordinary-file directories, and valid existing roots. Unit tests, Backend smoke, and unpacked Electron smoke cannot infer `PASS`.
- Architecture exceptions must be exact to `rule_id + path` and include reason, owner domain, creation time, expiry time, and test. Directory wildcards, stale exceptions, and deleting tests to pass are forbidden.

## High-Confidence Additions This Week (2026-08-03 to 2026-08-09)

- Base Data editing remains explicitly unlocked per subpage: overview, stations/sections, trackside AP, trackside AP planning, and trains/onboard MR each have their own scope snapshot and draft. Locked views stay read-only; dirty drafts require an explicit save, discard, or cancel decision on navigation, and revision conflicts must not overwrite server data.
- Manual Online MR collection may select at most two MRs. The site-wide single-task restriction is removed, but the same-MR mutex and shared active/start/finalization budgets remain. Ground Unattended may use only remaining MR capacity and must not stop manual work. Real-time pages reuse read-only session raw/session/parsed resources; raw files remain the fact source, while reparsing and reports use Job Center and Export Process respectively.
- Online MR normal stop and finalization must flush fping/iPerf first, then stop SSH, wait for writers/connections, write metadata, parse, verify file stability, atomically publish the ZIP, and only then enter the terminal task state. If flush or file stability cannot be confirmed, the session must not be marked normally complete or publish a formal ZIP.
- Trackside AP WPS synchronization stores connection, webhook, binding, and deployment state independently per site and target; standard spreadsheets and smart sheets must not be cross-used. Changing document connection, webhook, or document/script identity clears prior remote validation and sets `DEPLOYMENT_PENDING`; scripts must return parseable JSON through top-level `return main();`.
- Formal WPS synchronization must persist `target_batch_id`, credential-free request payload, and the source format manifest before submitting an asynchronous Job Center task. After a timeout or uncertain connection, the original `task_id` is queried and never submitted again. The fixed business Sheet registry, shared Workbook Builder, sheet order, and format read-back are protocol boundaries; format failures may return warnings but must not turn successful data writes into failures.

## High-Confidence Additions This Week (2026-07-27 to 2026-08-03)

- User file interactions have converged on fixed export actions, the shared export coordinator, and dedicated import pickers. Pages must not create private export state machines, auto-open save dialogs, or create tasks after cancellation.
- The Worker protocol's 1 MiB frame limit is now a handler design boundary: terminal events carry summaries only, while details, large text, and raw data are exposed through paged queries or Artifacts.
- AP Identity has moved from shadow assessment to the production unified index and completed the P0 high-volume paths in the consumer audit; P1/P2 remain open. Index refreshes are triggered only by explicit write events, and normal GET and search paths stay read-only.
- Trackside AP base data and per-station planning use stable IDs as the relationship boundary. Station names, VLANs, AP names, neighbor IPs, system names, and similarity must not bypass `station_id`, exact MAC, and AP Identity evidence.
- The ZTE C89E-4 read-only Adapter now has an initial real-device boundary. That validation does not authorize all ZXR10 models, config writes, or per-port recapture.
- Tool Collection is an independent Electron module. Third-party EXEs, icons, launch permissions, and the administrator helper stay within Electron userData/Native Bridge control and do not enter site data or the Python Backend.
- Formal release gates continue to record build identity, installer manifest, SHA-256, packaged Backend/Frontend commits, and `real_windows_install_status=PENDING` separately. Windows Server 2012 field compatibility does not replace isolated GUI installer validation.

## High-Confidence Additions This Week (2026-07-20 to 2026-07-27)

- The unified data root is now a hard boundary across source development, Electron, Backend, package validation, and formal installation: the machine-level `DataRoot` is the only persistent pointer, while automated tests use only isolated test roots.
- Installer data-root validation now follows the fixed sequence classify first, probe second, initialize/publish pointer last; ordinary-file directories are allowed and existing content must not be overwritten.
- v4 full migration packages are explicitly passwordless, unencrypted trusted-location ZIPs that keep credentials; all other package types remain sanitized and require credential re-entry.
- Workspace tabs, multiple windows, and tray residency are formal Electron interactions, but site switching still returns to the controlled Settings flow.
- Ground Unattended is an independent rail-transit Feature and data directory; real long-duration operation, real AC/MR, and tray-hidden execution still require manual gates.
- Train-communication point-table generation is a preview contract, not a save contract. Task completion only means scheduling ended; the page must validate returned node structure before displaying it.

## High-Confidence Additions This Week (2026-07-13 to 2026-07-20)

- Electron-only work has moved from parallel migration to active product boundary: Qt is now historical evidence only, not a test, dependency, runtime, or fallback path.
- The unified task window, controlled artifact downloads, and Native Bridge capabilities are the default cross-module interaction model; local paths and credentials do not return to the Renderer.
- All 77 standard Web tables have moved to the shared table component. Future tables must update the inventory and focused tests in the same change.
- Data root, Site Registry, `.ncsite`, backup/restore, and migration are managed by Python Application Services. Install, uninstall, and upgrade must not delete the user data root or Electron bootstrap.
- Rail-transit base-data editing, fixed communication topology, and controlled SFTP enablement now have explicit boundaries, but real-device, real-site, and Electron visual validation still need separate records. Fake or unit tests cannot replace them.
