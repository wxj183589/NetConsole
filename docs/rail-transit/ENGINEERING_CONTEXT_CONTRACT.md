# 统一工程上下文

复用 DeviceEngineeringContextDTO，EngineeringContextQueryService 组合已有 BaseData infrastructure 与关系 current/history，不新建表。批量contexts按一次工程revision和基础设施树投影；one为便捷调用。设备详情和专业业务只读消费，失败返回 unavailable，不阻断原业务事实。

状态 associated/unassociated/not_found/unavailable/stale/conflict/historical/unconfirmed 分开。line_id为Site稳定身份；node/station/section/project使用既有稳定ID。关系版本只覆盖工程事实，查询前后漂移或expected_revision不符为stale；不是跨库全局原子快照。

current可以使用旧station_id兼容映射；历史必须由at_time的有效关系重建，缺少记录为unconfirmed，不用当前归属冒充历史。关系名称保留事件快照；device_name当前查询使用资产名称，历史查询使用关系事件名称，原日志/会话身份在业务DTO原字段，不覆盖。仅凭名字/IP/MAC不能传入设备ID。

GET relationships/engineering-context沿用基础设施查看Feature及会话校验，支持最多200个device_uuid、at_time和expected_revision。无缓存写入、无迁移、无Identity重建、无设备采集。context_updated_at是查询时间，不是业务采集时间；temporal_scope/effective_at明确业务时点。删除契约保持can_delete=false。

Router 通过既有 Relationship Application Service 调用统一 Query。模块关闭沿用既有 FeatureGate 的 HTTP 404。`relationship_revision` 是 BaseData Query 的 Site 工程版本；它不是关系写入接口包含额外上下文校验的 mutation `base_revision`，两者不可互换。

当前站点、区间标签优先使用现行工程目录；历史标签使用事件快照。历史线路显示名和节点类型来自现行稳定目录，仅作 ID 的展示参考，不能据此推断未记录的历史关系。AP 点位确认不等于物理 AP 身份确认，`identity_status` 单独返回。AC 的 `service_scope` 携带正式目标站点 ID 供筛选和跳转，不用于推断 FIT-AP 实际归属。
