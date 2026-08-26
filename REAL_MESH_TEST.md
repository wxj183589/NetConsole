# Real MESH Test

日期：2026-08-26

## 环境

- 数据根：`D:\NetConsoleData-dev`；局点：宁波地铁12号线。
- catalog profiles：36；indexed sessions：3；可展示 sessions：2；pending：0。
- 选取真实 session：`5e92aeef-485a-4545-b0cf-46727482a488:3`；link records 99,299，active 51,324，standby 47,975，events 8,490。

## 服务端真实查询

| 场景 | 结果 | 耗时 | 负载 |
| --- | --- | ---: | --- |
| 列表 1,000 行 | PASS | 633.13ms | total 99,299，返回 1,000 |
| 时间轴 1,000 条 | PASS | 517.37ms | total 8,500，返回 1,000 |
| Active path chart | PASS | 1,056.00ms | 1,000 points，payload 1,062,943 bytes |
| Trackside signal chart | PASS | 1,607.57ms | 3,319 points，128 series，payload 2,223,840 bytes |

服务端结果没有超出 chart budget，source rows 99,299 被按窗口/关键事件预算选择；没有执行解析、迁移或写回。

## 限制

本轮没有重新采集 Electron GUI 1,000 行滚动 FPS、long task、heap snapshot，也没有完成 MESH 报告导出文件的全套人工打开核验；这些保持 PARTIAL，不用服务端耗时替代 GUI 证据。
