# Post-Merge Test Report

| Gate | Result |
| --- | --- |
| Python targeted suite | PASS: 255 collected, 255 passed after version expectation sync |
| Python compileall | PASS |
| Renderer Vitest | PASS: 212 files, 1546 tests |
| Electron Vitest | PASS: 38 files, 318 tests |
| Electron typecheck | PASS |
| Renderer typecheck/build | PASS |
| Workspace layout | BLOCKED: two pre-existing unmanaged DevStatus directories |

The initial Python run had one stale v1.5.16 assertion; it was corrected in `tests/test_version_build_identity.py` and rerun successfully.
