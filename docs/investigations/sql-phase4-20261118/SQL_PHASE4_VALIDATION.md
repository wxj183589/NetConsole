# SQL Phase 4 Validation

## Targeted tests

Command:

```text
.venv\Scripts\python.exe -m pytest tests/test_ac_mesh_link_query_service.py tests/test_ground_unattended_heartbeat_state.py tests/test_ground_unattended_heartbeat_resident.py tests/test_ground_unattended_heartbeat_inventory.py tests/test_ground_unattended_api.py tests/test_ground_unattended_history_query.py tests/test_ground_unattended_history_archive_query.py -q
```

Result: `145 passed, 1 warning`.

Additional checks:

- Ruff on modified source/test: PASS.
- `python -m py_compile` on modified source/test: PASS.
- `git diff --check`: PASS.
- `python -m scripts.architecture.cli direct-sql-access`: PASS.
- `python -m scripts.check_workspace_layout`: PASS after removal of the temporary profiling directory.
- `python -m scripts.quality.check_change_impact --paths ...`: PASS, L2 local history contract.

## Data safety

All new fixtures were isolated synthetic SQLite data. No device, GUI, production database or real development database was accessed.

```text
PRODUCTION_DATA_MODIFIED=0
DATABASES_REMOVED=0
DEV_REAL_DATA_MODIFIED=0
```

## Final gate refresh (2026-11-18)

- PR #122 HEAD: `8c1aed0184981b2f65763af1f057c835306bb38f3`.
- CI Run `44255040507`: Architecture, baseline, docs/path, Electron, main contract and Renderer checks PASS; Python Required Check IN_PROGRESS at inspection time.
- Codex Review: PASS for the latest HEAD, no major findings or unresolved review threads.
- Warning: one third-party `StarletteDeprecationWarning` from the `httpx`/Starlette TestClient compatibility layer. No resource leak or unfinished task was observed; no warning suppression was added.
- Status remains `PARTIAL_SQL_PHASE4` until Python completes.
