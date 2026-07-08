# NetConsole Project Rules

This document captures durable NetConsole project conventions. Read it before adding features, optimizing existing behavior, fixing issues, or creating automation so the same rules do not need to be repeated in every conversation.

## Scope

- Applies to code, documentation, tests, and packaging work under `D:\study\NetConsole`.
- Applies to the local Windows desktop application shape of NetConsole.
- Applies to rail-transit PIS / DCS train-ground wireless WLAN subsystem operations, diagnostics, data processing, and reporting features.
- Applies to H3C device commissioning, collection, analysis, and operations-assistance scenarios.

## Automated Review Scope

NetConsole daily and weekly automated reviews are for the project development process only. They are not intended to build a general personal profile of the user.

Review and persist:

- Project development conventions
- Code implementation details
- Business-rule boundaries
- Directory, naming, documentation, and testing conventions
- Project-wide rules for feature flags, import/export, reports, packaging, and release work
- Details Codex should automatically follow when developing NetConsole code later

Do not review or persist:

- The user's personal profession, background, or preferences outside this project
- Automation suggestions unrelated to NetConsole
- General personal working habits that should apply to other projects
- Unconfirmed business inferences

## General Principles

- Solve the current business goal first; do not expand unrelated features.
- Prefer minimal, clear, and verifiable implementations.
- Keep changes tightly scoped to the request and avoid opportunistic unrelated refactors.
- New capabilities should have clear validation criteria and cover the key business path.
- Prefer the project virtual environment `.venv`; use the system environment only when the project environment is unavailable.
- Use Chinese by default for repository commit messages, push descriptions, and user-facing change notes.

## Development Entry Points and Documentation Boundaries

- Before non-trivial changes, read `README.md`, `docs/README.md`, `docs/DEVELOPMENT_CONVENTIONS.md`, and `docs/CODEX_WORKFLOW.md`.
- For packaging and release work, also read `docs/BUILD_AND_RELEASE.md` and `docs/THIRD_PARTY_DEPENDENCIES.md`.
- For data layout, site isolation, or runtime paths, also read `docs/DATA_LAYOUT.md`, and treat `PathResolver` and current code as authoritative.
- Documentation cleanup should normally modify only `README.md` and `docs/`; do not include opportunistic business-code changes.
- When historical numbered docs conflict with current topic docs or code, document the "current implementation and items to unify" first instead of adding business migration in a docs-only task.

## Chinese Text and Encoding Rules

- Source files, Markdown, JSON, TOML, YAML, CSV, and exported logs use UTF-8 by default.
- Python text reads and writes must specify `encoding`; JSON containing Chinese text should be written with `ensure_ascii=False`.
- On Windows / PowerShell, initialize UTF-8 terminal encoding before commands involving Chinese text, paths, logs, H3C output, MIB files, CSV, or XLSX.
- Do not treat mojibake in PowerShell / Codex terminal output as proof that a file is corrupted; inspect raw bytes and the actual read encoding when needed.
- For H3C device output, historical logs, MIB files, and external CSV input, try `utf-8-sig` / `utf-8` first, then `gb18030` / `gbk`.
- Prefer the shared helpers in `netconsole/utils/text_encoding.py` for reading and cleanup instead of scattering fallback encoding loops across modules.
- Do not delete Chinese descriptions, MIB Chinese fields, or Chinese UI copy to avoid decoding issues.

## Feature and Optimization Rules

### User-Facing Features Must Use Feature Flags

New user-facing modules, pages, tabs, actions, buttons, or entry points should use the centralized feature-flag system by default.

Requirements:

- Register the new feature ID in `netconsole/core/feature_registry.py`.
- Expose the setting through the existing feature-flag configuration page and profile flow.
- Use `FeatureGate` to control UI creation, entry visibility, or action handling.
- Avoid scattered one-off `if` checks inside pages.
- Feature state uses four boolean fields: `visible`, `enabled`, `client_package`, and `internal_only`.
- Customer effective state must cascade through parent features; if a parent is hidden, internal-only, or not in the customer package, child features must not be visible or enabled.
- `module.feature_switch` and `system.feature_flags` are protected internal features and must not be enabled in customer mode through local overrides.

Exceptions:

- Pure internal refactors, non-user-facing fixes, and test helpers do not need a new feature ID.
- If a requirement explicitly defines the change as a permanent baseline capability, document why it does not use a feature flag.

### Fluent Command Bars and Page Action Boundaries

Module-level actions in the Fluent main window should be hosted by `NCCommandBar` and forwarded to the raw page button or handler.

Requirements:

- Command-bar buttons must have Chinese text and icons; do not leave only hidden legacy page buttons as the effective control.
- Module-level command bars should contain cross-page primary actions only; tab-level, table-level, and file-list context actions stay in the local page.
- The file-management module command bar should only contain connection actions: connect, disconnect, refresh connection status, and open WinSCP.
- The config-collection module command bar should only contain save config, download config, compare config, open directory, and refresh; snapshot, diff export, and delete actions stay in the local panel.
- Multi-tab modules such as AC management and rail transit must not mix tab-specific actions into the global command bar.

Validation should check command-bar text, icons, hidden legacy buttons, and whether clicking the command-bar button triggers the real raw-page behavior.

### WPS Scope Boundary

Do not add, repair, or preserve the following online-document capabilities by default unless explicitly requested:

- WPS cloud services
- WPS API
- KDocs
- Online spreadsheet sync
- Online document sync

Still in scope:

- Local `.xlsx` export
- Formatting improvements for files opened in WPS Office or Microsoft Office
- Frozen headers, filters, column widths, autofit, text formatting, and worksheet naming for local Excel files

Decision rule:

- If the user mentions "WPS opening result" or "WPS compatibility", treat it as local `.xlsx` file experience by default.
- Do not automatically expand it into cloud documents, online collaboration, or API integration.

### Car-Network and Point-Table Rules

Car-network diagnostics, train network diagnostics, and point-table generation should prefer a unified normalized rule set.

Requirements:

- Do not add production migration logic only to preserve historically inconsistent output unless explicitly requested.
- Do not preserve legacy `remark` descriptions when generating point tables or applying global rules.
- Regenerate `remark` from the current node identity, node type, end, and rule.
- Keep descriptions consistent across trains where possible.

Decision rule:

- If legacy data conflicts with the current unified rules, use the current rules by default.
- If historical output must be preserved, document that it is an explicit compatibility requirement.

### Local-First Behavior

NetConsole is a local Windows desktop tool. Prefer local data, local files, and local runtime behavior by default.

Requirements:

- Do not introduce cloud sync, online accounts, or remote document services as default dependencies.
- Keep project data under project-controlled or release-package-controlled directories by default.
- Import, export, analysis, and diagnostics should focus on local files and field device connections.

### AP Extension Belonging Import Rules

FIT-AP extension metadata, trackside AP layout tables, and signal A/B network layout tables should converge on the AP extension belonging fields.

Requirements:

- Standard templates and export templates should keep fields such as belonging type, station, section, section start station, section end station, yard, and area.
- Belonging type uses one normalized semantic set: station, section, yard, or unknown; it may be inferred from station, section, yard, and area values.
- When smart-importing signal A/B network layout tables, sheet names `A网` / `B网` determine the network domain; adjacent titles infer section endpoints, while yard/depot titles infer yard and area.
- Legacy metadata matching templates containing only AP name, station, mileage, location note, and direction are no longer valid import templates; use the current extension metadata template.
- AP MAC matching remains based on normalized MAC values; extension points without online resources should be treated as extension-not-online state.

Validation should cover A/B network recognition, section/yard inference, standard template headers, legacy-template rejection, and resource matching results.

### Online MR Collection and Analysis Rules

Vehicle MR online collection, raw logs, realtime cache, parser cache, and chart timelines must stay traceable.

Requirements:

- Raw task output is written to each task raw file and is not mirrored to `collector_output_raw.log` by default.
- `collector_output_raw.log` records collector process logs only; `terminal_monitor_raw.log` records device terminal-monitor output only. Do not mix them.
- Repeat collection connections should run only the minimal streaming prepare commands, not the full initialization command set; stopped collectors must not start new repeat connections.
- When parsing online MR RX streams, split sample blocks by recognized commands and use the primary sampling command time as the sample timestamp.
- If parser cache health checks find collapsed mesh-link samples, concatenated active-peer MAC values, or timeline anomalies, mark the cache stale and reparse.
- fping raw samples must preserve local time; when `display clock` provides a device-time offset, also write the device-aligned time and prefer device-second buckets for 1-second summaries.
- Without a device-time offset, fping summaries fall back to local-second buckets and keep `offset_source=none`.
- Active-link switch realtime events come only from `terminal_monitor_raw.log`; `switch_history` files must not backfill active-link switch realtime events.
- Adding hover markers or reference lines to dynamic charts must not change the original axis range.

### Raw MR MESH Large-Data Rules

Raw MR MESH logs may be large or imported from multiple files, so parsing, charts, and reports must prioritize traceability and performance.

Requirements:

- When directory-level `mesh.sqlite` acts as a catalog and entry point, detailed parsed data comes from the per-file parsed SQLite referenced by `source_files.parsed_db_path`.
- Charts, details, and reports filtered by source file must resolve to the corresponding detail database instead of assuming the catalog database contains all `mesh_links` rows.
- compact v2 parsed databases should use scalar columns for RSSI, channel busy, rate, retry, and error metrics; only fall back to `metrics_json` / `deltas_json` for legacy databases.
- Large-sample charts should draw only the visible window or a downsampled result while preserving switch points, anchors, and other important samples; do not draw every sample at once.
- Page switching, MR selection, and table refreshes should use debouncing, lazy loading, and repository caching so the same MR is not loaded repeatedly.

Validation should cover per-file parsed DB queries, compact v2 scalar metrics, source-file-filtered charts and reports, visible-window rendering, all-view downsampling, and duplicate-load debouncing.

### IPERF Follow-Collection Rules

Vehicle MR follow-collection IPERF traffic should follow the collection lifecycle instead of using a short fixed test duration as the formal collection duration.

Requirements:

- Online MR presets use default port `5201`.
- Follow-collection mode uses `FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS`; the current protection duration is `86400` seconds.
- Run a 1-second preflight before collection start and reconnect; preflight must not enable `follow_collection`.
- TCP low-bandwidth cases without an explicit block size use the existing `16K` fallback.
- IPERF logs should record `duration_mode=follow_collection` and the protection duration so later analysis can explain the run.

### Data Paths and Site Isolation

Business data paths should be obtained through `PathResolver` or existing path services.

Requirements:

- Do not hard-code the user's local machine paths in production code, tests, or documentation rules.
- Site data must remain isolated; devices, reports, collection records, and caches must not be mixed across sites.
- Raw collection logs, parsed results, report outputs, and backup files should live in separate areas instead of one mixed directory.
- Documentation tasks must not directly change directory logic; directory structure changes should update implementation, migration strategy, and tests first.

### UI Table Rules

When adding or modifying table-style pages, follow `docs/ui_table_guidelines.md`.

Requirements:

- Batch-selection columns must use `CheckBoxOnlyDelegate`; do not use `setCellWidget(QCheckBox)`.
- Select-all, invert-selection, and clear-selection actions must synchronize table `CheckStateRole` and internal selection state.
- Initialize column widths by content and allow user resizing; do not default to `QHeaderView.Stretch` to compress every column.
- Use horizontal scrolling for wide tables; long paths, errors, remarks, and command-output fields should use elision and tooltips.

### Build and Release Boundaries

Packaging and release work should follow `docs/BUILD_AND_RELEASE.md` and the build scripts under `project/`.

Requirements:

- Release output must go under the versioned `release/` directory and must not pollute the project root.
- Release packages use the whitelist: `NetConsole.exe`, `_internal`, `data`, `runtime`, and `tools`.
- `docs/`, `tests/`, `project/`, and source-form `netconsole/` must not be shipped in user release packages.
- Internal and customer editions are handled through the existing `--build-editions` and feature profile flow, not by copying separate code trees.
- Check external tool source files such as `fping` and `iperf3` before packaging; runtime tool paths must not hard-code user-local paths.
- Explain any non-interactive build that skips smoke tests.

### Third-Party Dependency Boundaries

- QFluentWidgets must use the `qfluentwidgets` package from `PySide6-Fluent-Widgets==1.11.2`.
- Do not mix `PyQt-Fluent-Widgets`, `PyQt6-Fluent-Widgets`, or `PySide2-Fluent-Widgets`.
- Do not use QFluentWidgets Pro components; commercial use requires separate license confirmation.
- Mica / Acrylic / blur effects must degrade gracefully; effect initialization failure must not block application startup.

## Validation Rules

Choose validation scope based on change risk:

- Documentation changes: verify paths, file names, and key content.
- Pure logic changes: add or run the relevant pytest coverage first.
- UI entry or feature-flag changes: verify visible, hidden, enabled, and disabled states.
- Excel / report export changes: verify local file generation and inspect headers, column widths, filters, frozen panes, and formats.
- Car-network, vehicle MR, trackside AP, MESH, IPERF, and related business changes: verify core parsing, key states, and exception branches.

## What Should Not Become Project Rules

- One-off temporary requests.
- Unconfirmed inferences about user preferences.
- General personal preferences unrelated to NetConsole.
- Compatibility code that only applies to a single experiment.

## Maintenance

- Update this document when the user explicitly confirms a new durable project preference.
- When code behavior and this document conflict, first decide whether the document is outdated or the code has drifted from the rule.
- New rules should be short, precise, executable, and include decision boundaries where possible.
