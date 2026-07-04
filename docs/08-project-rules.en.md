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
