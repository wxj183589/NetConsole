# Phase 11.6 数据完整性报告

## 审计结论

当前链路保持“原始事实、结构化结果、业务派生、展示和导出分层”。本轮未修改 parser 语义、SQLite schema、原始日志或真实数据根。

| 环节 | 审计结果 | 证据 |
|---|---|---|
| 文件识别/来源 | session/source locator 使用受管 source_id，raw 缺失时明确 warning | mesh_analysis_query_service.py source summary、artifact tests |
| Parser/字段 | LinkCnt、LinkState、AP/Peer/Radio、RSSI、Noise、Rate、CPU、Memory、Busy、TxDesFreeCnt、Tx/Rx、Retry/Err、GARP/MulJoin 有模型和读写路径 | mesh_log_models.py；mesh_log_analysis_service.py；query DTO |
| 缺失/非法值 | numeric 转换失败保留 null；业务统计只接收有限数值；不把缺失补 0 | mesh_business_statistics.py；mesh_monitor_sampling.py |
| 身份 | 物理 AP MAC 精确归并；名称和不确定 Peer 不能替代身份 | AP identity/mesh business tests |
| 主备 | 按采样 link_role/link_count 建序列；LinkCnt=0 只影响派生业务结果，raw/zero query 保留 | query service zero path、sampling tests |
| 统计 | AP 质量只用正有限 ACTIVE RSSI；阈值和角色/Radio 筛选进入缓存 key | business statistics tests |
| 导出 | business/diagnostic 列集分离；diagnostic 保留 raw line/source evidence；XLSX writer 启用 ZIP64 | mesh_link_detail_export.py；export tests |
| 真实证据 | Phase 11.2 Service 只读 evidence 验证 nearest、counter 元数据、465→240 降采样；DB/raw hash 前后一致 | docs/reports/mesh-phase11-2/real-service-query-validation.json |

## 风险和边界

- 当前定向测试使用 fixture/合成数据；真实只读 evidence 不覆盖每一项现场字段。
- 业务 UI 精简不等于底层追溯删除；来源、行号、raw evidence 只在诊断/维护路径保留。
- 未执行生产数据写入、schema migration、设备写入或完整数据复制。
- Excel/WPS GUI 未验收，不能把结构验证提升为业务文件 GUI PASS。
