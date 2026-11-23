# Ping Migration Parity

## 对照范围

对照基线来自迁移前 `pingChartStatus.ts` 和 `quickPingStatistics.ts` 的实现及其测试输入。Backend 测试覆盖：别名、显式状态优先级、空值、未知值、失败原因、RTT 异常、丢包率边界、重复样本、跨秒边界和连续样本。

## 已保持的行为

- 显式状态优先于 `ok`、超时、错误原因、丢包率和 RTT；
- `TIMEOUT`/`PACKET_LOSS` 的 RTT 展示为空，成功无 RTT 为未知；
- 缺省丢包率按状态投影为 0 或 100，真实数值限制在 0 到 100；
- 统计按样本身份去重，不按数组位置分组；
- 自然秒边界使用 UTC 毫秒时间戳和半开区间；
- 输出桶和点位按时间排序，未知样本保留在总数中。

## Golden 对照

Golden 输入保留在 `tests/test_ground_unattended_ping_business.py` 的固定样本中。迁移后的 Python 结果由单元测试断言；Renderer 测试只验证对 Backend 投影字段的展示和图表映射，产品运行路径不再保留旧 TypeScript 业务实现。

## 状态

`BUSINESS_PARITY=PASS`（固定输入和定向调用链已通过）。真实设备、真实生产数据和跨机器验收不在本轮授权范围，仍需按发布 Gate 单独执行。
