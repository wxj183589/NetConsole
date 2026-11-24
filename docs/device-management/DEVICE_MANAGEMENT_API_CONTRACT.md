# 设备管理 API 契约

现有 `/api/device-management/devices`、CRUD、分组、连接测试、导入导出和详情分区接口保持兼容。

`GET /api/device-management/devices/{device_uuid}/overview` 新增 `engineering_context`。字段包括 `affiliation_status`、`line_name`、`node_uid`、`node_type`、`node_code`、`node_name`、`role`、`project_names` 和 `service_stations`。该对象是只读投影，不接受写入。

设备列表 DTO 新增 `engineering_affiliation` 展示字段。查询服务无法读取基础设施时返回 `未关联轨道交通基础设施` 或详情中的 `unavailable` 状态，不能阻断设备资产接口。

普通设备写入请求保留旧工程字段以兼容旧客户端和旧数据库。Phase 2 页面不提交这些字段，也不提供建设阶段、工作范围或站点关系的维护操作。
