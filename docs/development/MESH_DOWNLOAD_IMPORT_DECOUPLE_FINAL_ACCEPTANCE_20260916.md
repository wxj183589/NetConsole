# MESH 下载与导入解耦最终主线验收

日期：2026-09-16

## 最终状态

```text
PR_58=MERGED
FEATURE_COMMIT=ec458be0a416fa13c1319fbf23605a61871520b0
MERGE_COMMIT=f1bc8f17ad0bf435552181b31ee6b99e2ce5b3c6
MESH_DOWNLOAD_IMPORT_DECOUPLE=MERGED_VALIDATED
MERGE_ACCEPTANCE=PASS
POST_MERGE_L4_ACCEPTANCE=PASS_BASELINE_AWARE
BASELINE_FAILURES=5
FEATURE_REGRESSIONS=0
POST_MERGE_NEW_FAILURES=0
BRANCH_CLEANUP_ELIGIBLE=YES
```

本记录将 PR #58 的最终代码主线验收正式收口为通过。这里的 `PASS_BASELINE_AWARE` 不表示把原始失败数字改写为零；它表示合并前已经用同一 Python、pytest、环境、工作目录、nodeid 和参数在 `github/main` 与 feature 分支完成 A-B 对照，合并后再次复验，5 个失败均为同一既有 baseline，未发现 feature 新增回归。

## 交付内容

PR #58 将车载 MR 的远端下载与 MESH 登记/解析/派生维护生命周期解耦：

- `.part` 完成大小与 SHA-256 校验并原子发布后，`file_management_download` 父任务立即进入 `COMPLETED`。
- 后续 MESH 登记、解析和派生数据维护由独立 `file_management_mesh_import` 子任务执行。
- MESH 子任务失败、取消、重试或启动恢复不会反转已经完成的下载父任务，不会删除已落盘 raw，也不会因为分析重试重新连接设备或重新下载 raw。
- 下载队列在 raw 安全落盘后立即释放，不再等待 MESH 解析/维护收尾。
- 保留当前 FileTransfer、Site Relay、canonical `relay_site_id`、Host Key、SFTP reconnect 和 SCP fallback 契约。

## 合并前 A-B 证据

以下 5 个 nodeid 在 pre-merge `github/main@20e28531b68e4f225971bb44ca0782b89ce734e2` 与 feature `ec458be0a416fa13c1319fbf23605a61871520b0` 上均复现相同异常类型、核心断言/错误和最终业务失败位置，因此分类为 `BASELINE_FAILURE`：

1. `tests/test_h3c_ac_refresh_simulation.py::test_simulated_h3c_r1612p01_ac_refresh_uses_legacy_retry_and_persists`
2. `tests/test_offline_ap_ledger_async.py::test_trackside_switch_offline_forces_downstream_ap_offline_even_when_ac_run`
3. `tests/test_online_mr_collection.py::test_netmiko_shell_connection_falls_backs_to_tunnel_and_releases_session`
4. `tests/test_zte_optical_work_scope_integration.py::test_zte_invalid_interface_snapshot_is_not_presented_as_current`
5. `tests/test_zte_optical_work_scope_integration.py::test_zte_connection_failure_does_not_present_old_realtime_state`

> 注：第 3 项名称以实际仓库 nodeid 为准；最终判定依据是已保存的 A-B 测试日志和同一失败签名，不以本文中的人工转录作为新的测试事实来源。

A-B 汇总：

```text
BASELINE_FAILURES=5
FEATURE_REGRESSIONS=0
NEW_FAILURES=0
```

## 合并后 L4 结果

合并提交：`f1bc8f17ad0bf435552181b31ee6b99e2ce5b3c6`

实际结果：

- Python：`4925 passed, 2 skipped, 5 failed, 33 warnings`
- Renderer：`181 files / 1305 tests passed`
- Electron：`37 files / 298 tests passed`
- Architecture：`12/12`
- Main Contract：`12 passed`
- Consumer：`241 passed`
- FileTransfer Relay/SFTP/SCP/Host Key：`16 passed`
- Ruff：PASS
- compileall：PASS
- docs validation：PASS
- diff check：PASS

Python 的 5 个失败与合并前 A-B 已确认的 5 个 baseline 一致，因此本次合并验收按用户确认采用 baseline-aware 放行：

```text
POST_MERGE_L4_ACCEPTANCE=PASS_BASELINE_AWARE
POST_MERGE_NEW_FAILURES=0
```

不将原始 `5 failed` 隐藏、删除或改写为 `0 failed`。

## GitHub CI 红灯口径

PR 合并后的两个 GitHub Engineering Hardening 红灯在 pytest 启动前即因 runner 不存在工作流硬编码的 `D:\study\...` 数据根而中止。它们属于 CI runner / workflow 环境路径配置问题，不是 PR #58 的产品代码回归。

```text
CI_CODE_REGRESSION=NO
CI_ENVIRONMENT_CONFIGURATION_FAILURE=YES
MERGE_ACCEPTANCE_BLOCKED_BY_CI=NO
CI_WORKFLOW_PATH_FIX=PENDING
```

CI workflow 的绝对路径治理应作为独立任务处理，不在本次 MESH 功能修复中扩大范围。

## 数据与发布边界

本轮合并与复验：

```text
PRODUCTION_DATA_MUTATION=NO
DEVELOPMENT_REAL_DATA_MUTATION=NO
VERSION_BUMP=NO
PACKAGE_BUILD=NO
TAG_CREATED=NO
RELEASE_CREATED=NO
```

## 独立现场验收项

以下项目没有因为本次代码放行而自动变成 PASS，继续作为独立后续门禁：

```text
REAL_DEVICE_ACCEPTANCE=PENDING
GUI_ACCEPTANCE=PENDING
INSTALLER_ACCEPTANCE=PENDING
FIELD_MESH_CANCEL_RESTART_ACCEPTANCE=PENDING
```

这些现场项不改变当前代码主线状态：

```text
MESH_DOWNLOAD_IMPORT_DECOUPLE=MERGED_VALIDATED
MERGE_ACCEPTANCE=PASS
```
