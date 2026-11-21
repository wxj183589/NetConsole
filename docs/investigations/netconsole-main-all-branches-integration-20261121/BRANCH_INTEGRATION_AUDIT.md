# Branch Integration Audit

Date: 2026-11-21

| Branch | HEAD | Result | Evidence |
| --- | --- | --- | --- |
| `github/main` | `0b8fa04c` | ALREADY_MERGED baseline | Fast-forwarded into main first |
| `codex/netconsole-v1.5.17-maintenance-20261121` | `6dc938c7` | READY_TO_MERGE | Depends on github/main; merged as `299c52a6` |
| `codex/netconsole-r5.0-collection-playback-20261121` | `c4e4b285` | READY_TO_MERGE | Depends on v1.5.17; merged as `a6b7fc29` |
| `codex/netconsole-r5.0.1-dev-runtime-gui-20261121` | `ea751b23` | READY_TO_MERGE | Depends on R5.0; merged as `389bc3e3` |
| `codex-A/netconsole-v1516-post-merge-20261121` | `36a29cdb` | DOCS_ONLY / ALREADY_MERGED | Three acceptance docs; history retained by merge `3bd8e8f1` |
| `codex/netconsole-original-maintenance-20261120` | `6d8a7918` | SUPERSEDED | Product commits already represented by remote v1.5.16 integration; no new product delta after comparison |

All local worktrees and remote GitHub refs were inventoried after `git fetch github --no-prune`. Historical remote feature branches with independent commits remain retained and were not blindly merged; they are superseded or require a separate scoped review.

The pre-existing untracked `docs/investigations/sql-architecture-review-20261118/` was preserved.
