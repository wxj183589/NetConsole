# NetConsole 实际采集数据优先治理 Phase 1 审计

日期：2026-10-15
审计分支：`codex-A/actual-data-priority-field-merge-20261014`
最新 main 基线：`c5ca5f67`
PR：[#84](https://github.com/wxj183589/NetConsole/pull/84)，保持 OPEN

## 结论

已确认根因是 `merge_fit_ap_rows_by_identity()` 在较高优先级记录胜出时使用整行覆盖。较新记录的空值会抹掉另一条同身份记录中的有效光衰、LLDP 或接口字段。

PR #84 的字段级补缺方向正确，但原提交仍有两个遗漏：

1. `_is_missing_display()` 使用 `str(value or "")`，会把数值 `0` 和布尔 `False` 当成缺失；这会覆盖例如 `lldp_confidence=0` 的当前清理事实。
2. 当前记录明确离线时，不能从较早在线记录恢复 IP、光衰、LLDP、Radio 或连接状态等运行态。

本次最小修复保留首选记录的非缺失字段，仅从可信同身份的当前记录补稳定身份/资料字段；`0`、`0.0` 和 `False` 均视为有效值。两条记录都有明确状态时按采集/更新时间选择较新状态。当前明确离线时不回填运行态字段。

历史 LLDP/光衰不进入该合并函数。轨旁业务仍由独立历史路径消费，并通过 `data_source=historical_lldp`、stale/current 字段表达来源；历史值不会被伪装为当前在线值。

## 来源和身份边界

- `merge_fit_ap_rows_by_identity()` 的生产输入是 `ac_fit_ap_resources` 与 `ac_fit_ap_optical` 的 Current 投影，不读取历史表。
- 合并键保持 AC 作用域，并优先使用 `ap_uuid`、规范化 MAC 或序列号；同名无强身份记录不合并。
- 同一 MAC 出现在不同 AC 时保持分离；MAC、序列号、AP 名称、Radio/BSSID 和 LLDP 拓扑不互相折叠。
- 当前 FIT-AP 状态仍由 AC Current 决定；光衰阈值、在线/离线判断、AP Identity 关联、DTO/API 和 Excel 列均未改动。
- 基础资料仍只作为既有补充来源，不把运行态写回正式资料。

## 修改文件

- `src/netconsole/services/trackside_ap_business.py`
  - 字段级合并保护有效零值/布尔值。
  - 明确离线时不恢复旧运行态字段。
- `tests/test_trackside_ap_business_optimization.py`
  - 补充交替缺失、多条重复、零值/False、当前离线、AC/MAC/名称边界、历史值隔离测试。
- `docs/investigations/actual_data_priority_audit_20261014.md`
  - 更新根因、审计边界和正式数据只读统计。

未修改采集器、设备管理、AP Identity 基础规则、数据库 Schema、公共 DTO/REST API、导出列、MESH、Online MR、Ground、Task Center 或 Electron Runtime。

## 字段合并前后差异

| 情况 | 旧逻辑 | 当前逻辑 |
| --- | --- | --- |
| 首选记录有值 | 整行覆盖 | 首选非缺失字段优先 |
| 首选记录为空、回退记录有值 | 可能清空或只在低优先级分支补值 | 仅同身份可信记录按字段补缺 |
| `0` / `False` | 被当成缺失 | 保留为有效值 |
| 当前明确离线 | 可能恢复旧 IP/光衰/LLDP | 保留离线事实，不回填运行态 |
| 历史 LLDP/光衰 | 不应进入该函数 | 继续走历史/stale 独立路径 |
| 同 AC 重复身份 | 可能整行丢字段 | 字段级合并 |
| 跨 AC 同 MAC、同名不同 MAC、无身份 | 不应合并 | 保持独立或原样透传 |

## 正式数据只读统计

查询范围为 `D:\NetConsoleData\sites` 下宁波和杭州目录；SQLite 使用只读 URI 打开，仅执行 SELECT/PRAGMA。未执行 UPDATE、DELETE、VACUUM、迁移、重建、采集或设备连接。

`当前值与历史值冲突` 的口径是：当前资源/光衰与对应身份最近一条历史记录在状态、IP、Rx/Tx 或 LLDP/接口字段上同时有值且不相等的记录数；资源维度与光衰维度分别计数后相加，可能同一 AP 在两个维度各计一次。该冲突是历史变化证据，不代表把历史值提升为 Current。

| 局点 | Current FIT-AP 原始/合并后 | 同 AC 重复身份组/记录 | 同 MAC 多 AC | 身份歧义组/记录 | 当前-历史冲突 | 合并后状态变化 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 杭州 `hzdt-09` | 148 / 148 | 0 / 0 | 0 | 0 / 0 | 0 | 0 |
| 杭州 `hzl10` | 932 / 932 | 0 / 0 | 0 | 0 / 0 | 448 | 0 |
| 杭州地铁4号线-信号-A网 | 0 / 0 | 0 / 0 | 0 | 0 / 0 | 0 | 0 |
| 杭州地铁4号线-信号-B网 | 0 / 0 | 0 / 0 | 0 | 0 / 0 | 0 | 0 |
| 宁波地铁10号线 | 914 / 914 | 0 / 0 | 0 | 0 / 0 | 1030 | 0 |
| 宁波地铁12号线 | 994 / 994 | 0 / 0 | 0 | 0 / 0 | 0 | 0 |
| 宁波地铁1号线 | 685 / 685 | 0 / 0 | 0 | 0 / 0 | 546 | 0 |
| 宁波地铁6号线 | 602 / 602 | 0 / 0 | 0 | 0 / 0 | 0 | 0 |

当前数据没有出现同 AC 重复身份，因此本次字段保留修复在现场 Current 行上未产生数量变化；这不替代隔离重复数据回归。

### 字段有效数

正式数据上旧逻辑与新逻辑的有效 Rx、Tx、LLDP 和接口字段数量完全相同。原因是当前八个局点均没有同 AC 重复身份；新逻辑没有人为增加历史字段。

## 性能

- 正式数据只读合并耗时（资源+光衰当前行合并，20 次中位数）：`hzdt-09 3.750 ms`、`hzl10 16.804 ms`、宁波10号线 `23.422 ms`、宁波12号线 `25.705 ms`、宁波1号线 `17.161 ms`、宁波6号线 `15.471 ms`。
- 隔离千级基准：1000 条记录、500 个 AP 身份、每个身份两条交替缺失记录；合并后 500 条。20 次中位数 `3.087 ms`，最大 `4.407 ms`。
- 算法仍是单次内存索引和字段遍历，没有新增数据库查询、N+1 访问或持久化内存增长。

## 回归和未完成项

已完成：

- `tests/test_trackside_ap_business_optimization.py`：`28 passed`。
- 修改范围 Ruff：PASS。
- `git diff --check`：PASS。
- 正式数据只读统计：完成；正式数据库未修改。

已完成分支验证：

- 相关 AC/Trackside/AP Identity consumer：`418 passed, 3 warnings`。
- Python 全量：`5133 passed, 2 skipped, 33 warnings`。
- Renderer Vitest：`181 files / 1310 tests passed`；typecheck、build：PASS。
- Electron：`38 files / 303 tests passed`；typecheck、main build：PASS。
- Architecture Green Gates：`8/8 PASS`；Main Contract Smoke：`12 passed`；Baseline-aware Python：`5133 passed, 2 skipped, 33 warnings`，`NEW_FAILURES=0`。
- `git diff --check`：PASS。

推送后的 GitHub CI 尚待远端完成；真实设备采集、Windows GUI、安装/升级、现场 Excel/WPS 和跨机器验收仍为人工/PENDING，不由自动化或只读数据库统计替代。

## 后续仅登记

- PR #78：后续审查数据库升级、备份/回滚、AC 扩展回滚和基础资料回滚 Authority；本阶段未移植代码。
- PR #83：本阶段不重新修改 RSSI，也未引入其额外站点安全回退逻辑。
