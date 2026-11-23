# v1.5.18 Renderer Ping Migration Test Report

日期：2026-11-23

## 已执行

| 范围 | 命令/结果 |
| --- | --- |
| Backend 业务与 Ground 回归 | `python -m pytest -q tests/test_ground_unattended_ping_business.py tests/test_ground_unattended_api.py tests/test_ground_unattended_heartbeat_playback.py tests/test_ground_unattended_usability.py tests/test_ground_unattended_history_archive_query.py`：79 passed，1 warning |
| Python 全量 | `python -m pytest -q`：5716 passed、2 skipped、34 warnings：PASS |
| Python 编译 | `python -m py_compile`（业务模块、Application Service、DTO）：PASS |
| Ruff | 迁移模块和测试：PASS |
| Renderer 定向 | 4 个文件、19 tests：PASS |
| Renderer 页面 | QuickPingPage/GroundHistoryPlayback：2 文件、19 tests：PASS |
| Renderer 全量 | `pnpm test`：219 files、1584 tests：PASS |
| Renderer production build | `pnpm build`：PASS（Vite chunk size warning，仅提示） |
| Electron 类型检查 | `pnpm run typecheck`：PASS |
| Electron 全量 | `pnpm test`：41 files、324 tests：PASS |
| Architecture Guard | `scripts/architecture/run_all.py`：12/12，0 finding、0 waived：PASS |
| Workspace Layout | `python -m scripts.check_workspace_layout --repo-root . --workspace-root D:\study\NetConsole-Workspace`：PASS |
| Change Impact | `python -m scripts.quality.check_change_impact --paths ...`：L2，exit 0；本轮另行完成 L4 消费者审计文档 |
| Docs Path Guards | `tests/test_project_docs_layout.py tests/quality/test_directory_readmes.py`：22 passed：PASS |
| Diff 格式 | `git diff --check`：PASS |

## 未执行或未完成

- 真实 UI 点击和真实设备：`NOT VERIFIED`；
- Root Layout：`FAIL`，仅命中既有根目录历史文件 `NETCONSOLE_V1_5_17_RELEASE_NOTES.md`、`V1_5_17_CHANGELOG.md`，本轮未修改；
- 版本契约、main-contract-smoke 和完整 Release Gate：`NOT RUN`；
- 大批量、多设备和跨时间范围性能对比：`NOT VERIFIED`。

因此本轮不能把 Architecture Guard 或定向测试通过写成正式发布 PASS。
