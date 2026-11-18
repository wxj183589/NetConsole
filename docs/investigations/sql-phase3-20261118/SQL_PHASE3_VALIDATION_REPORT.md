# SQL Phase 3 验证报告

## 定向测试

- `tests/test_ac_management_query_service.py`
- `tests/test_ac_management_web_api.py`
- `tests/test_ac_mesh_link_query_service.py`
- `tests/test_fit_ap_resource_export.py`
- `tests/test_ground_arp_identity.py`
- `tests/test_ground_unattended_api.py`
- `tests/test_fit_ap_identity_reconciliation.py`

结果：`124 passed, 3 warnings`。

额外验证：

- `python -m py_compile`：PASS（所有修改 Python 文件和画像脚本）。
- Ruff：PASS（修改源码、测试和画像脚本）。
- `python -m scripts.architecture.cli direct-sql-access`：PASS（无输出即无新增违规）。
- `python -m scripts.check_workspace_layout`：PASS。
- `python -m scripts.quality.check_repository_root_layout`：PASS。
- `git diff --check`：PASS。

## 业务正确性

- AC/FIT-AP 归属、名称、MAC、Radio、导出字段和动态 optical/LLDP 现有测试保持通过。
- Mesh-Link Local/Peer、双端 Radio、主备读取、精确匹配、分页和 freshness 现有测试保持通过。
- Ground ARP 完整/部分/失败快照、身份冲突、Site 隔离和批量投影测试通过。

## 数据安全

画像只使用合成 SQLite；未连接真实 AC/MR/交换机。

```text
PRODUCTION_DATA_MODIFIED=0
DATABASES_REMOVED=0
SCHEMA_MODIFIED=0
REAL_DEVICE_CONNECTED=0
```

## CI / PR 门禁

- CI Run：`44142115842`。
- 检查时间：`2026-11-17 18:30:43 UTC`。
- PR：`#121`，最新 HEAD：`d37f98609b61763b49504610343562e1d50d6c14`，状态 `OPEN`，目标分支 `main`。
- Required Checks：Architecture contract PASS；Baseline debt audit and new failure detection PASS；Docs, path, and diff guards PASS；Electron tests, typecheck, and main build PASS；Main contract smoke PASS；Renderer tests, typecheck, and build PASS；Python regression without baseline debt FAIL；Engineering hardening blocking gates FAIL（由 Python FAIL 汇总触发）。
- Python Job：`134247385669`，`17:54:40Z` 开始，`18:28:32Z` 完成；失败步骤为 `Run Python regression with exact baseline deselection`，无运行中 Step，无超时结论。
- Python 结果：`11 failed, 5584 passed, 4 skipped, 34 warnings`。失败集中在隔离测试目录的 Windows 文件锁（`PermissionError` / `WinError 5/32`）引发的 Demo 重建和清理失败，另有 1 项 resident polling 清理文件锁、1 项无关 iPerf 重试断言；当前证据不足以归因于 Phase 3 SQL 修改。
- Codex Review：已对应最新 HEAD `d37f98609b61763b49504610343562e1d50d6c14`，无发现、无未解决 Review Thread。
- 阻断项：Python Required Check FAIL，PR 当前不具备合并条件；未取消或重启 CI，未创建修复提交。

## CI 稳定性专项修复

- 针对原 Run 的 11 个失败节点已完成逐项调查，详见 `WINDOWS_CI_FAILURE_INVESTIGATION.md`。
- 修复范围限定为测试清理、Windows 原子文件替换、Demo 测试数据发布移动和回归测试辅助读取；未修改 SQL 业务代码。
- 本地验证：原 11 个失败节点 `11 passed`；Resident Polling `8 passed`；iPerf 失败节点连续 20 次通过；生命周期/API 相关套件 `136 passed, 2 warnings`；修复后组合回归 `59 passed`；Ruff PASS。
- 新 CI：尚未启动（待本轮提交推送后由 PR 自动触发），因此 Required Checks 尚未重新验证。
- 修复提交：`006c6894d696c72968db1e57fd6252935873810a`；Codex P2 修复提交：`db894e70`（将 Demo 同卷移动改为无复制回退的 `os.rename()` 重试）。上述提交已推送，等待新的 CI Run。
- 当前状态：`BLOCKED_SQL_PHASE3_CI_STABILITY`。

## 最终状态

`BLOCKED_SQL_PHASE3_CI_STABILITY`
