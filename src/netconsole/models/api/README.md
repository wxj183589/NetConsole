# API DTO 模型

本目录定义 FastAPI 与 Web/Electron 之间的 Pydantic 请求、响应和分页模型，按业务域拆分。DTO 只表达契约和校验，不访问数据库、设备或执行任务。

修改字段、枚举或可空性时同步 Router、Application Service、Web `types/api` 与测试；敏感凭据不得进入响应模型。

## 用途与边界

本目录定义 FastAPI 与 Web/Electron 之间的 Pydantic 请求、响应、分页和事件 DTO；只做契约校验，不访问数据库、设备、文件或任务执行器。

## 主要入口

各业务域 `*.py` 提供 DTO，`common.py` 和 `task.py` 提供共享分页/任务结构；Router 与 Web API 类型是主要消费者。

### Device Detail DTO

`device_detail.py` 是设备快速详情抽屉和完整详情页的后端契约，按职责包含：

- `DeviceDetailSourceDTO`：采集时间、来源和对应 Task ID；
- `DevicePlatformFactsDTO`、`DeviceDetailCapabilityDTO` 与 Command Profile DTO：平台事实、能力、页签和可执行状态；
- `DeviceOverviewDTO`：设备概览、接口/任务摘要、最近错误和 `visible_sections`；
- 接口列表、接口详情与分页 DTO；
- 光模块、LLDP 邻居及分页 DTO；LLDP 只公开本地接口、邻居系统名/MAC/接口/IP、关联设备和采集事实，不包含邻居能力或型号；
- 配置快照、设备任务及分页 DTO；
- `DeviceBusinessRelationDTO` 与轨旁 AP、FIT-AP、Online MR 关联结构；
- 历史记录分页 DTO；
- 刷新请求和 Task 响应 DTO。

设备详情不定义独立 Health DTO；CPU/内存只作为 overview 的可空基础摘要。接口 DTO 不公开入/出速率、入/出错误、CRC 错误、错误总数和最后变化；光模块 DTO 不公开采集 `status` 或内部阈值来源，只保留后端判定的严重性和中文原因。其他未知事实同样使用 `None/null`，不得伪造 `0`。关联业务保持显式嵌套对象，Renderer 不应重新推断字段关系。所有列表接口使用有上限的分页模型；详情、错误和来源字段不得暴露密码、community、Token、服务器绝对路径或原始环境变量。

`DeviceLldpNeighborDTO` 不定义邻居 `capabilities`、`model`。底层历史 schema/Repository 可以为旧数据兼容继续保存这些列，但 API DTO、OpenAPI、Web 类型、表格、历史详情和导出不得重新暴露。设备 overview、光模块和 FIT-AP DTO 中语义不同的型号字段不受影响。

## 依赖关系

模型依赖 Pydantic 和领域值约束，被 Backend API、Application Service 和前端 `src/types` 映射；模型不反向依赖 Vue/Electron。

## 数据与状态

DTO 表示单次请求/响应或事件快照，不持有长期状态；Token、密码、community 等凭据必须被模型排除或脱敏。

## 测试与修改

修改字段、枚举、可空性或序列化时先运行对应 API、Router boundary、Web API 和 Pydantic 定向测试，检查旧客户端兼容性；全量测试和生产构建只在最终集成组合上运行。当前低 CPU 限制下，本轮文档同步未运行测试或构建。

## 生成与清理

模型不生成文件；测试 JSON、快照和临时响应写入 pytest 临时目录，禁止把真实设备回显或凭据写入 fixture。

## 相关文档

参见 [FastAPI API](../../backend/api/README.md)、[设备管理页面](../../../../apps/desktop_renderer/src/views/devices/README.md)、[API 边界审计](../../../../docs/development/API_APPLICATION_BOUNDARY.md)和[Web 架构](../../../../docs/architecture/RUNTIME.md)。
