# Application Service 组合层

本目录编排跨 Repository、Service、Job 和 Export 的用户用例，为 FastAPI 与 Electron Backend 提供稳定调用边界。它不实现 Router DTO，也不把业务状态放入 Vue。

主要子域为 AC、桌面动作和轨道交通；修改用例编排时检查依赖层测试、事务/任务边界和错误映射，长耗时工作必须进入 Job/Export。

## 用途与边界

本目录编排跨 Repository、Service、Job 和 Export 的用户用例，为 FastAPI/Electron Backend 提供稳定调用边界；不实现 Router DTO 或 Vue 业务。

## 主要入口

`ac/`、`desktop/` 和 `rail_transit/` 提供领域应用入口，公共用例通过业务 Service、Query Service 和 Job Center 组合。`device_detail.py` 提供 `DeviceDetailApplicationService`，统一设备详情只读查询与刷新任务提交，不复制设备管理 Service。

### 设备详情用例

`DeviceDetailApplicationService` 将 overview、接口、光模块、LLDP、配置快照、任务和关联业务查询委托给 `DeviceDetailQueryService`，将刷新委托给 `DeviceOperationService`。接口、光模块和 LLDP 的分页历史端点目前仍由 `DeviceManagementWebService` 使用字段白名单安全映射，后续收敛时不得改变公开 `DeviceHistoryPageDTO`。设备详情不提供独立 Health 用例；CPU/内存只保留在 overview 基础摘要。打开详情只读取最近数据库快照；耗时设备连接只能通过现有 Task Center 提交。

LLDP 用例必须把历史 Repository 行映射为公开 DTO，主动丢弃邻居 `capabilities`、`model`；不能把原始数据库字典直接交给 Router。该映射不删除或改写历史数据库字段。

刷新使用稳定 Operation ID `device.inventory.collect`，应用层不拼命令、不识别设备版本，也不直接访问 SQLite。未知或未验证厂商、角色、平台、Command Profile 必须由下层服务失败关闭。H3C `wireless_controller` 通过明确登记的 Comware 通用只读 Profile 刷新设备事实、接口、光模块和 LLDP；AC 业务关联继续只读复用 AC Query Service，FIT-AP/Radio/受控动作不进入设备详情用例。H3C MR 关联信息只读复用 Online MR Query Service，基础设备详情刷新走独立 `mobile_router` Profile，不能被通用交换机刷新接管。

## 依赖关系

Application 层向下依赖 Service、Repository、Job/Export adapter，向上由 FastAPI 或 Desktop 调用；禁止把设备连接和 SQL 直接写进 Router。

## 数据与状态

用例通过 PathResolver/Repository 读写业务数据，通过 Job/Export 传递长任务状态；应用层不持有跨请求的 SQLite connection 或 Renderer 状态。

## 测试与修改

开发阶段运行对应 Application/API/Repository/Job 定向测试和依赖层 Guard。新增用例先定义输入输出、错误、事务、取消和权限边界，再接入 Router。当前低 CPU 限制下，本轮文档同步未运行测试；全量测试和生产构建待用户解除限制后补跑。

## 生成与清理

长耗时 IO/CPU/网络进入 Job，正式文件进入 Export Process；临时会话、数据库和报告由 PathResolver/Job/Export 白名单清理，不静默删除原始数据。

## 相关文档

参见 [设备管理页面](../../../apps/desktop_renderer/src/views/devices/README.md)、[业务服务](../services/README.md)、[下一阶段开发指南](../../../docs/DEVELOPMENT_GUIDE.md)、[API 边界审计](../../../docs/API_APPLICATION_BOUNDARY_AUDIT.md)和[Job Center](../../../docs/JOB_CENTER.md)。
