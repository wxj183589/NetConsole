# 设备资产生命周期

资产只使用 devices.device_uuid；没有第二套资产表或删除标记 Schema。

| 操作 | 正式行为 | 历史与其他关系 |
| --- | --- | --- |
| 新增/复制 | DeviceManagementWebService → DeviceRepository.create；生成新 UUID | 复制不迁移原资产历史 |
| 编辑/导入更新 | Repository.update；地址冲突与凭据规则保留 | UUID 保持，CSV overwrite 只更新匹配资产，不用 DELETE 重建 |
| 停用 | 现有 work_scope_status=excluded，表示排除当前调试/自动采集 | 不是通用设备电源停用；不删关系、任务、会话、报告 |
| 工程解除 | RelationshipApplicationService → Repository 结束单条关系 | 设备、其他服务范围、历史与采集均保留 |
| MR 解除/更换 | 结束旧 assignment；更换建立新 assignment | 旧 MR UUID、旧会话、MESH/raw/报告不迁移 |
| AC 服务解除 | 结束工程服务站点关系 | FIT-AP Current 仍按 ac_device_uuid 独立，历史不删除 |
| 分组删除 | 解除 group_id，再删分组 | 不删 devices |
| 资产物理删除 | 本阶段禁止；token/batch/Repository 均拒绝 | 无独立保留政策、完整证据与授权，不开放 |

FIT-AP 运行资源删除是另一项 AC 受控 Job（含独立 Feature/确认/目标归属），不是 devices 资产删除或工程解除；本次未运行设备命令、未改变其能力。局点删除/首次初始化失败回收、文件与日志保留策略也不是资产删除授权，不能通过这些入口绕过禁止真实历史删除的任务范围。

历史证据默认保留；删除预检不调用自动清理、VACUUM、checkpoint、归档迁移、路径删除或数据库升级。
