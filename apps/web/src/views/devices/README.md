# 设备管理页面

## 当前状态

设备管理由 Electron 唯一桌面宿主中的 Vue Renderer 提供。设备列表、快速详情抽屉和完整详情页已进入永久架构，但人工桌面操作和真实设备采集仍未完成，状态保持 `IMPLEMENTED_UNVERIFIED / REAL_DEVICE_PENDING`，不得写成 `COMPLETE`。

## 页面入口

- `DeviceManagementView.vue`：设备列表、筛选、批量选择和快速详情抽屉入口。
- `DeviceDetailView.vue`：`/devices/:deviceId` 完整设备详情路由。
- `../../components/device-detail/DeviceDetailPanel.vue`：快速抽屉和完整页共用的展示组件。

快速抽屉和完整页必须复用同一套 API、DTO 和 presentation 组件。Renderer 只负责布局、筛选、分页、展示和轻量交互，不识别设备版本、不判断设备能力、不选择设备命令，也不直接访问 SQLite、SSH、Agent 或 Electron Main。

设备主列表、OmniPeek 预览、能力事实、详情分区和历史表格已迁移到 `NcDataTable`。表头/内容默认居中，描述和错误等长文本按列类型明确左对齐；列宽由公共文本测量、字段类型基线和可视区剩余空间共同计算，分区/历史偏好按 section/kind 隔离。设备主列表由系统名、分组、站点和主备地址共同拉伸，站点优先；复选框、登录协议、时间、状态和操作列保持边界。页面不再散写 Element Plus 列宽、`header-align`、`measureText()` 或平均分配算法。

## 读取与刷新顺序

1. 打开抽屉或完整页时只读取数据库中的最近 overview 快照，不立即连接设备。
2. 页签只按 overview 返回的 `visible_sections` 显示；接口、光模块、LLDP、配置、任务和关联业务在首次激活时懒加载。CPU/内存只保留在 overview 基础摘要中。
3. 历史和大表使用服务端分页、筛选与受控详情接口，不一次性返回全量数据。
4. “刷新全部”提交稳定 Operation ID `device.inventory.collect`，由 `DeviceOperationService` 进入现有 Task Center；页面不建立第二套任务状态。
5. 当前设备详情通过共享 Task Store 轮询任务状态。任务进入 `COMPLETED`、`FAILED` 或 `CANCELLED` 后，页面重新读取 overview 和已经加载的页签。
6. 页面切换设备、页签或筛选时使用 generation 避免旧请求覆盖新状态；卸载时释放 polling、请求状态和图表/观察器资源。

## 新增/编辑表单连接测试

- SSH 已启用且地址、端口、用户名和认证信息有效时，可在不保存设备的情况下提交真实连接测试；测试按钮在任务运行期间保持 loading，并保留“打开任务窗口”入口。
- 编辑已有设备时，密码留空且未勾选清除会由 Worker 按 `device_uuid` 解析已保存凭据；输入新密码只用于本次测试，不写回设备数据库；显式清除且没有新密码时拒绝提交。
- 非敏感表单字段进入安全 Job 参数，临时密码只走共享 Job Runtime 的一次性敏感 bootstrap。任务结果在弹窗内显示安全消息、失败分类和耗时，成功不会自动保存，失败不会清空表单。
- SSH 测试复用现有 Netmiko/隧道执行器，覆盖参数校验、凭据解析、连接、握手、认证、会话验证和终态阶段。自动测试已覆盖成功、认证失败、超时、拒绝、凭据不落盘与异常恢复；真实 H3C MR 仍需现场验收，因此模块状态保持 `IMPLEMENTED_UNVERIFIED / REAL_DEVICE_PENDING`。

## 数据来源

| 页面区域 | 当前事实来源 | 说明 |
| --- | --- | --- |
| 概览 | `devices.db.latest_snapshot` | 平台、能力、统计、最近采集和来源元数据；不在开页时连接设备 |
| 接口 | `devices.db.interfaces.latest_snapshot` | 服务端分页和筛选；接口名称归一化由 Python 完成 |
| 光模块 | `devices.db.transceivers.latest_snapshot` | 功率、温度、阈值和告警来自已保存快照 |
| LLDP | `devices.db.lldp.latest_snapshot` | 公开本地接口、邻居系统名/MAC/接口/IP、关联状态和采集时间 |
| 配置 | Config Collection Application Service | 当前仅复用既有 H3C 配置快照、比较和下载契约 |
| 任务 | Task Application Service / `tasks.db` | 设备相关任务摘要、状态和 Task Center 跳转 |
| 关联业务 | 轨旁 AP、AC、Online MR Query Service | 只读关联现有业务事实，不在 Renderer 中拼接关系 |

每组数据应展示采集时间、来源和可用时的 Task ID。后端缺失值使用 `null`，页面显示“—”；合法的数值 `0` 必须保留，不能用伪造的零代替未知值。

LLDP 历史数据按公开 DTO 白名单消费，不进入任意原始对象透传链路。本项是公开契约收口，不执行破坏性 schema 或历史数据清理。

## 厂商、角色和 Command Profile 边界

- 当前设备详情能够展示已入库的多厂商快照，并由 Python 对 H3C/Comware、Huawei/VRP、ZTE/ZXR10 等平台事实和接口名称做归一化。
- 通用设备详情刷新目前只允许 H3C、`switch` / `mobile_router`、Comware 且命中可执行 Command Profile 的组合。
- 当前唯一稳定 Operation ID 是 `device.inventory.collect`；对应资源为 `resources/device_command_profiles.json`，已登记的通用只读 Profile 包括 `h3c.comware.switch.generic.device-inventory.v1` 和 `h3c.comware.mobile_router.generic.device-inventory.v1`。
- 未知或未验证厂商、角色、平台、Profile 必须失败关闭，不能回退执行 H3C 命令。软件版本未知时，也只有厂商、角色、平台精确匹配且资源明确允许的只读通用 Profile 才能执行。
- H3C AC 的关联信息只读复用 AC Query Service，暂不开放通用设备详情刷新；H3C MR 的关联信息只读复用 Online MR Query Service，基础设备详情刷新使用独立 `mobile_router` Profile，不会把 MR 当作通用交换机执行命令。
- Huawei、ZTE 等交换机目前只承诺展示已有快照和归一化结果，不代表设备命令已经验证。V5/V9 等未有真实 fixture/现场证据的版本不得标记为已支持。

## API 与 DTO

设备详情 API、分页和错误契约见 [Web API 客户端](../../api/README.md)与 [FastAPI API](../../../../../src/netconsole/backend/api/README.md)；Pydantic DTO 见 [API DTO 模型](../../../../../src/netconsole/models/api/README.md)，前端映射见 [Web 类型契约](../../types/README.md)。

响应不得包含设备密码、SNMP community、Token、服务端绝对路径或任意环境变量。Artifact 只通过既有受控下载契约交给 Electron Main。

## 修改与验证

新增字段或页签时先更新 Python DTO/Application/Query Service，再同步 Router、TypeScript 类型、API client 和展示；不得在 Vue 中补设备版本、阈值或关联业务规则。新增用户可见文本进入 i18n，样式使用 Element Plus 和 NetConsole Design Token。

开发阶段只运行受影响的 Python API/Service、Vue 组件/路由定向测试。表格展示改动运行设备页面/组件 Vitest、公共表格测试、`vue-tsc` 和 UI Guard；全量测试、Electron Package Smoke 和多尺寸人工视觉矩阵只在最终集成组合执行。

## 相关文档

- [设备详情展示组件](../../components/device-detail/README.md)
- [最终迁移矩阵](../../../../../docs/architecture/MIGRATION_MATRIX.md)
- [历史设备管理兼容入口](../../../../../docs/03-device-management.md)
- [版本化 Command Profile 清单](../../../../../docs/archive/migrations/electron-only/COMMAND-PROFILE-device-inventory-2026-07-18.md)
