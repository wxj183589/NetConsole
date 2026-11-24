# Phase 4 消费者审计

基线 fddf1912（远端同 SHA），DevStatus b158e25。产品工作树 clean；复用原工作树创建 codex-A/rail-business-integration-phase4，保留旧分支，不合并 main。Phase 3/3.6 PARTIAL，历史 Full Gate 与本轮结果分开。删除冻结不变。

| 消费者 | 运行事实/工程来源 | 重复与风险 | 本轮措施 |
| --- | --- | --- | --- |
| Devices | 设备资产/事实 Repository；DeviceDetailQueryService 自行遍历基础设施树 | 局部拼装缺 revision/time/状态 | 将既有 DTO 和基础设施投影复用于公共查询 |
| Ground Inventory | Site BaseData MR + formal train_mr，Ground inventory 是运行投影 | revision 已缓存；失败需与未关联区分 | 只读上下文批量附加，保留引擎和历史；上下文失败不清库存 |
| Position/Heartbeat/Syslog/Ping | Ground 当前投影/事件/NDJSON、AP Identity 完整 MAC | 当前 AP 名称不能反推历史 | 当前工程信息单独附加，历史事件不改；原位置引擎不改 |
| Trackside | device facts/LLDP/FIT-AP/optical/Identity + base point/plan | 页面导出共享冻结快照；缺建设项目/工程上下文 | 在共同投影层加入上下文，使用已有 source revisions，保留端口/Identity冲突 |
| AC/FIT-AP | AcManagementQueryService 的 AC UUID / Current | 工程服务与实际 AP 管理需分开 | AC 返回独立上下文/服务站点；不合并 Current |
| Wireless | BaseData、AC、TrainCommunication、MESH、Job、Online MR 聚合 | TTL 缓存未验证工程 revision，缺稳定工程筛选 | 增加上下文筛选/工程revision验证，不改运行指标算法 |
| MESH | profile linked_device_uuid/id，解析库/raw/历史报告 | 当下名称/AP location enrichment不等于历史身份 | 当前/历史工程上下文单独提供，不覆盖解析身份；无稳定绑定保持未确认 |
| Online MR | session_meta 原始device_id/name + parsed/raw/outputs | 旧会话只存numeric ID/名字时不能猜UUID | 用可证明ID解析/显式UUID查询，历史与当前并列，失败隔离 |

基础设施维护工程组织与关系；设备管理维护设备资产/连接/采集；运行库与归档继续归业务自身。无新增表、无跨库全局 revision。关系改变推进 Site revision；它只覆盖工程事实，不能代表运行库原子一致。

风险 L3（公共只读DTO/消费者和导出快照），无 Schema/删除/运行引擎改造。写入关系仍走既有 Application Service；新增上下文只读。不得从 IP、名称、MAC相似推断稳定绑定。缺失、失败、陈旧、冲突与历史明确区分。现有旧字段保留兼容，不删除历史字段。

验证顺序：上下文 → Ground（含100MR/50列车）→ Trackside快照/导出 → AC/Wireless → MESH/Online MR → Renderer/Electron与跨模块。每阶段独立提交，真实数据/设备/安装包/全量Gate均NOT RUN。本轮不允许因为上下文失败清空运行事实或重建历史位置。
