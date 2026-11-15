# AP 静态台账正式集成报告

日期：2026-11-15
工作树：`codex-A/ap-ledger-sql-opt-20261115`
数据范围：仅隔离资料解析与隔离导入预览；未打开 `D:\NetConsoleData`、`D:\NetConsoleData-dev` 或现场设备。

## 输入资料核对

任务指定的汇总 Excel、二期 FIT-AP Excel 和 `1q(1)(2).zip` 在本机未找到。实际可读资料为桌面上的 `1q(1).zip`，其中包含 21 个车站 LLDP 文本、`AC-fit-AP.txt`、`AC查询.txt`、`address.txt` 和交换机资料。旧版 9 号线 AP Excel 未作为 LLDP 权威源使用。

LLDP 文件中的站点归属来自文件/目录的显式站点范围；不从 AP 名称、IP、MAC 尾号或前缀推断站点。交换机 `Local Interface` 写入正式上联端口，邻居侧 `Port ID` 仅作为审计字段保留。

## 真实资料解析结果

| 指标 | 结果 |
| --- | ---: |
| LLDP 原始邻居行 | 464 |
| 精确 MAC 交叉确认的 AP | 422 |
| 非 AP LLDP 邻居（排除） | 42 |
| LLDP 站点数 | 21 |
| AC/AP 解析行 | 495 |
| AC 地址表行 | 494 |
| 未能由 LLDP 精确确认的 AC 行 | 73 |
| 站点/交换机提示符缺失的 AP 行 | 26 |
| 自动冲突行 | 0 |

缺少交换机提示符的 26 行保留为待现场确认，不填充默认交换机。AC-only 行不伪造交换机、端口或站点归属。

## 正式链路

已复用现有 AP 基础资料导入预览/应用链路，并新增 LLDP 来源元数据：

- `建设阶段`
- `来源类型`
- `来源设备`
- `来源时间`
- 邻居侧 `Port ID`
- 精确完整 MAC 身份证据和 `switch_lldp` 静态权威标记

正式台账工作簿：

`D:\study\NetConsole-Workspace\diagnostic\ap-ledger-sql-opt-20261115\杭州地铁9号线一期_AP静态台账_20261115.xlsx`

该工作簿只包含正式导入工作表 `ap_switch_port_point_table`，表头之外为 422 条可导入台账行；未把审计统计页混入正式导入表，避免导入器将统计行误识别为 AP。

在隔离测试 Site 上通过现有正式预览链路得到：

| 分类 | 数量 |
| --- | ---: |
| CREATE | 422 |
| UPDATE | 0 |
| UNCHANGED | 0 |
| CONFLICT | 0 |
| INVALID | 0 |
| WARNING | 422（隔离 Site 没有对应正式车站/AC 运行态，不阻断导入） |

该结果是隔离副本预览分类，不是正式 Site 写入结果。受控 apply、重复导入、冲突保护和 rollback 使用现有专项测试覆盖；本轮没有向真实或长期开发数据写入。

## 保护规则

- LLDP 是交换机、Local Interface 和站点范围的静态权威源；AC FIT-AP 只作为 AP/MAC 补充和精确交叉校验。
- 已有人工确认字段不会被低优先级导入源无条件覆盖。
- 同一 MAC 多站点/交换机/端口、同一端口多 MAC 和 MAC/名称不一致保留为冲突证据，不自动选一条覆盖旧值。
- 静态台账与 AC 运行态分离；AC 离线或 LLDP 过期不删除静态资料。
- Mesh-Link 查询使用批量 Identity 反查；AC 无运行态时可回退到当前 Site 的正式静态 AP 资料。

## 未完成边界

二期 189 AP 以及一期 AC 差异 72 的任务指定 Excel 未提供，因此本轮只确认实际归档资料的 422/21/464/42/73 结果；二期数量和完整现场验收标记为 `FIELD_VALIDATION_PENDING`，没有用旧 Excel 或推断数据冒充验收。
