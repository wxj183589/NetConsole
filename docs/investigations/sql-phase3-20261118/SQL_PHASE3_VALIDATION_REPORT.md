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

- 原始失败 CI Run：`44142115842`（历史证据，Python Required Check FAIL）。
- 最终检查时间：`2026-11-18 02:45:07 UTC`；最终 CI Run：`44221274938`。
- PR：`#121`，最新 HEAD：`fc1d7df9d5814739ac2b1b34d8de47264334722f`，状态 `OPEN`，目标分支 `main`，`MERGEABLE` / `CLEAN`。
- Required Checks：Architecture contract PASS；Baseline debt audit and new failure detection PASS；Docs, path, and diff guards PASS；Electron tests, typecheck, and main build PASS；Main contract smoke PASS；Renderer tests, typecheck, and build PASS；Python regression without baseline debt PASS；Engineering hardening blocking gates PASS。
- Python Job：`134523451223`，`02:10:23Z` 开始，`02:45:01Z` 完成，用时 `34m38s`；无失败步骤、无运行中 Step、无超时结论。
- Python 结果：PASS。原 11 个 Windows 文件锁失败节点已由定向修复与回归测试覆盖；未发现新的 SQL 业务回归。
- Codex Review：已对应最新 HEAD `fc1d7df9d5814739ac2b1b34d8de47264334722f`，无发现、无未解决 Review Thread。
- 阻断项：无；本轮未取消或重启 CI，不自动合并 PR。

## CI 稳定性专项修复

- 针对原 Run 的 11 个失败节点已完成逐项调查，详见 `WINDOWS_CI_FAILURE_INVESTIGATION.md`。
- 修复范围限定为测试清理、Windows 原子文件替换、Demo 测试数据发布移动和回归测试辅助读取；未修改 SQL 业务代码。
- 本地验证：原 11 个失败节点 `11 passed`；Resident Polling `8 passed`；iPerf 失败节点连续 20 次通过；生命周期/API 相关套件 `136 passed, 2 warnings`；修复后组合回归 `59 passed`；Ruff PASS。
- 新 CI Run：`44216699242`（中间验证）和最终 Run `44221274938`；最终 Run 对应 HEAD `fc1d7df9d5814739ac2b1b34d8de47264334722f`，Required Checks 全部 PASS，Python regression `PASS`（`34m38s`）。
- 修复提交：`006c6894d696c72968db1e57fd6252935873810a`；Codex P2 修复提交：`db894e70`（将 Demo 同卷移动改为无复制回退的 `os.rename()` 重试）；最终报告提交：`fc1d7df9`。
- 最新 Codex Review：对应 `fc1d7df9d5`，无发现、无未解决 Review Thread。
- PR #121：`OPEN`、`MERGEABLE`、`CLEAN`；本轮不自动合并。
- 当前状态：`PASS_SQL_PHASE3_CI_STABILITY`。

## 最终状态

`PASS_SQL_PHASE3_CI_STABILITY`
