---
name: netconsole-device-management-skill
description: "NetConsole 设备管理、Device CRUD、主地址唯一性、分组/角色/建设阶段/当前工作状态、凭据、连接测试、批量采集、设备 CSV 导入导出、SecureCRT 或外部终端任务时使用。AC/FIT-AP、设备 SFTP 或配置快照任务不使用本 Skill。"
---

# 目标

维护设备资料、只读事实快照、连接与采集任务、导入导出和受控桌面动作的完整纵向链，保护设备身份、凭据和多厂商失败关闭语义。

# 触发与反例

触发示例：

- “修改设备新增/编辑/复制、IP 更新或批量状态维护。”
- “修复连接测试、设备详情刷新或 CSV 导入导出。”
- “调整 SecureCRT/Xshell/PuTTY 预检和启动。”

不应触发：

- “修改 AC/FIT-AP 资源或受控 AC 动作。”
- “下载设备文件或比较配置快照。”

# 输入与输出

- 输入：设备 UUID、资料字段、厂商/角色/Profile、任务或文件操作、兼容格式和预期业务结果。
- 输出：Device Application/Service/Repository/API/Vue 的最小修改、数据与凭据影响、任务/Artifact 行为和验证。
- 允许修改生产代码：允许，限设备管理纵向链和测试；不得借机修改 AC、SFTP、配置采集或轨旁业务规则。

# 开始前读取

- `apps/desktop_renderer/src/views/devices/README.md`、`docs/DEVICE_VENDOR_IMPORT_AND_COLLECTION.md`、`docs/external-terminal/README.md`。
- `src/netconsole/backend/api/device_management_router.py`、`src/netconsole/models/api/device_management.py`。
- `src/netconsole/services/device_management_web_service.py`、`src/netconsole/services/device_operation_service.py`、`src/netconsole/services/device_detail_query_service.py`。
- `src/netconsole/repositories/device_repository.py`、`src/netconsole/repositories/device_detail_repository.py`、`resources/device_command_profiles.json`。
- `apps/desktop_renderer/src/views/devices/`、`apps/desktop_renderer/src/api/deviceManagement.ts` 和相关 pytest/Vitest。

# 当前架构事实

- 正式链为 Vue -> FastAPI Router -> Application/Query Service -> Repository/Job；Renderer 不选择命令、判断设备版本或访问 SQLite/SSH。
- `device_uuid` 是稳定身份；主地址唯一且变更必须保留事务完整性。IP 可参与受控导入匹配，但名称、站点文本和 IP 不能替代跨领域稳定关联键。
- `device_vendor` 保留用户原文，`vendor_key` 只用于驱动解析；未适配采集使用 `SKIPPED`，不等于设备无效、离线或导入失败。
- 设备详情先读已保存快照，显式刷新才提交稳定 Operation ID `device.inventory.collect`；大表由服务端排序、筛选和分页。
- 普通 DTO 不返回密码、SNMP community 或 Token；显式凭据查看只允许受信 Electron 本机会话的单字段动作。

# 工作流程

若变更触及共享 API client、NcDataTable、Task/Job、Export、Feature、DataRoot 或公共 DTO，编码前先组合 `netconsole-change-review-skill` 完成消费者审计。

1. 明确资料写入、查询快照、连接测试、采集、导入、导出或外部终端中的唯一目标，先追到现有 Service/Repository。
2. 新增字段先更新 model/schema 兼容、Repository、DTO、Service、Router、TypeScript 类型和 Vue；保持旧库、旧 CSV 和缺失值语义。
3. 新增/编辑/复制和批量更新使用稳定 UUID 与事务；空凭据保留旧值，只有明确清除标记才删除，秘密不进入任务参数、日志或普通响应。
4. 在任何 SSH/SNMP/CLI 前调用设备采集能力解析；未知厂商、角色或 Command Profile 失败关闭，不回退到 H3C/ZTE 最接近实现。
5. 网络与批量采集进入 Job Center；`COMPLETED` 与设备可达/认证/部分成功分开表达，页面终态后重新读取事实快照。
6. CSV 先预览编码、哈希、匹配依据和冲突，再在单事务重新预检并提交；不得用名称猜测地址变更，不得忽略错误行后部分写入。
7. 正式导出按 selected/filtered_all 明确范围，走 Export Process、公共 Artifact 和用户预选保存路径；取消选择不得创建任务。
8. 外部终端只提交设备 UUID 与语义终端类型，复用后端预检和白名单；Renderer 不提交程序、argv、路径或凭据。

# 禁止模式与不变量

- 不把 AC/FIT-AP 当普通设备采集，也不让通用详情刷新调用 AC 专用命令。
- 不从设备名、编号、IP 或模糊站名推断正式 `station_id`、厂商驱动或轨旁关联。
- 不使用 `errors="ignore"` 读取导入文件，不在普通导出中泄露明文秘密。
- 不在 Renderer 中拼接关联业务、阈值、采集命令、SQL 或导出文件。
- 不把未适配采集、暂停使用、认证失败、不可达和 Worker 异常合并成一个状态。

# 验证与失败报告

- 覆盖 CRUD、地址唯一/交换、旧 schema、凭据保留/替换/清除、连接状态、Profile 支持/跳过、批量部分结果和事务回滚。
- 导入导出覆盖 UTF-8 BOM/UTF-8/GB18030/GBK、旧列格式、空值、冲突、范围、取消、Artifact 完整性和保存失败重试。
- 运行受影响的 `tests/test_device_management_web_api.py`、设备详情/导入导出测试及设备页面定向 Vitest；共享表格改动增加公共消费者回归。
- 报告命令/Profile 是否变化、schema/凭据/文件影响、任务语义、真实设备与 Electron 对话框未验证范围。

# 相关 Skills

- L3/L4 影响审计：`netconsole-change-review-skill`。
- AC/FIT-AP：`netconsole-ac-management-skill`。
- 设备文件：`netconsole-device-files-skill`。
- 配置快照：`netconsole-config-collection-skill`。
- Job、文件交互和导出：`netconsole-job-center-skill`、`netconsole-user-file-interaction-skill`、`netconsole-export-report-skill`。
