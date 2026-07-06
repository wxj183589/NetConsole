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

Exceptions:

- Pure internal refactors, non-user-facing fixes, and test helpers do not need a new feature ID.
- If a requirement explicitly defines the change as a permanent baseline capability, document why it does not use a feature flag.

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
