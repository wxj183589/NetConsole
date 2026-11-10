# 数据完整性与隔离

## 只读来源

本轮 Electron / Service 使用隔离快照：

D:\study\NetConsole-Workspace\test-data\NetConsole\mesh-phase11-8-run-001

未将具有写入能力的运行态连接到 D:\NetConsoleData-dev，也未使用
D:\NetConsoleData。没有复制完整 Production 或 Dev 数据根。

## 重要文件

| 文件 | bytes | SHA256 |
| --- | ---: | --- |
| 原始 gzip | 2,892,510 | F53990D5448F297EA8CBC6901D87132FCF3F616C61149FEAA4E875829A3B0FC7 |
| parsed SQLite | 156,786,688 | 2630D9CF03CD5AC3146E11D449DB5964DD8E7DD97666136D56EB09AA40B77271 |
| mesh SQLite | 249,856 | 7D45597929601C48848BA65471F0270EACA5489CD6CD662B2AF74D45CDD3A191 |

运行允许隔离 Catalog / task / report metadata 变化；不要求把隔离运行库强行
恢复到启动前哈希。原始 gzip 未被修改。

## 计数一致性

- parsed samples / active_points：44470
- ACTIVE raw full range：44470
- link details total：108700
- active segments：8091
- switch events：8101
- parse issues：2865
- AP peer mapping / resolve cache：1231 / 1231
- 报告和链路明细导出均通过 ZIP 和 worksheet XML 结构校验

## 结果

PASS。视觉样本有界只限制 ECharts 输入，不改变 raw cache、导出、详情或
完整索引的数据来源；Radio 2 空数据按真实查询结果显示。
