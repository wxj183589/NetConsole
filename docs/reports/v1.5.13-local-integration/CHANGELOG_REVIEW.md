# v1.5.13 更新日志核查

## 核查结果

- 唯一现有产品日志：`docs/CHANGELOG.md`。
- 新增条目：`v1.5.13 - 2026-11-10（本地集成记录，未发布）`。
- 既有 `## 未发布` 保留，仅继续承载未进入本轮的 Ground 条目；没有创建第二套 changelog。
- 历史顺序仍以 v1.5.12、v1.5.11 等既有版本为准。

## 版本源

| 位置 | 实际值 | 处理 |
| --- | --- | --- |
| `src/netconsole/core/version.py` | `v1.5.12` | 保留，不降级或擅自同步 |
| `apps/desktop_electron/package.json` | `1.5.12` | 保留；本轮不生成 Release |
| Electron `productName` | `NetConsole v1.5.12 by wxj` | 保留；避免版本线不一致 |
| `docs/CHANGELOG.md` | v1.5.13 本地集成记录 | 已新增，明确未发布 |

## 内容与代码核对

已写入的 MESH 内容均由本轮选定提交和 Phase 11.9/11.10 已有验收报告支撑：

- 大范围/百万级日志加载、有限视觉采样和原始数据完整保留。
- raw sample、派生、历史分页、建链分页缓存，缺失区间精准补齐。
- counter continuity、link continuity、Tooltip、滚轮时间轴、主链路/AP/Radio/双端统计。
- 命中缓存后的 HTTP/SQL 重复查询修复。
- 真实 Electron 工作台交互、筛选/分页/列设置以及 MESH Excel/链路明细导出回归。

未将 DataRoot、Ground、Job Center 或未完成的 Excel 实机、真实设备、长期稳定性验收写入 v1.5.13 完成项。

