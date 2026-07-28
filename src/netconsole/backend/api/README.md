# FastAPI API

本目录实现 HTTP/WebSocket Router、DTO 适配和依赖注入边界。Router 不得直接连接设备、SQLite、导出进程或实现业务状态机。

主要入口为各领域路由模块和 `main.py`；用例由 Application/Query Service 提供。修改接口后运行对应 API、未认证边界、架构分层测试。

## 设备详情 API

`device_management_router.py` 在 `/api/device-management/devices/{device_uuid}` 下登记 overview、interfaces、interface detail、transceivers、LLDP、config snapshots、tasks、business associations 和 refresh 路由。设备详情不注册独立 Health API，CPU/内存只由 overview 返回基础摘要。路由提供 tag、summary、Pydantic DTO 和错误响应，并把分页、筛选和刷新请求交给 `DeviceDetailApplicationService`；Router 不直接执行 SQLite、SSH、设备命令或业务关联。

读取接口只返回最近快照、overview 基础摘要和现有业务 Query Service 结果。打开页面不会连接设备。`POST /refresh` 只提交现有 Task Center 操作 `device.inventory.collect`，由 `DeviceOperationService` 和版本化 Command Profile 再次校验执行边界；H3C `switch`、`wireless_controller`、`mobile_router` 分别匹配明确登记的 Comware 只读 Profile，未知或未验证厂商、角色、平台、Profile 失败关闭。无线控制器刷新仍使用原设备 `device_uuid`，不会调用 AC/FIT-AP 专用采集 Router。

LLDP Router 响应使用显式 DTO 白名单，只公开本地接口、归一化本地接口、邻居系统名/MAC/接口/IP、关联设备 UUID、关联状态和采集时间；历史 Repository 中可能存在的邻居 `capabilities`、`model` 不进入 API。Router 不得通过任意字典回传这两个字段。

接口公开 DTO 不返回入/出速率、入/出错误、CRC 错误、错误总数或最后变化；光模块公开 DTO 不返回采集 `status` 或内部阈值来源。Repository、采集内部和历史数据库可以继续保存这些兼容字段，但 Router、OpenAPI、历史白名单和 Web 类型不得重新暴露。光模块只公开后端判定的 `severity` 与中文 `severity_reason`，Renderer 不得自行计算功率阈值。

生产 Electron 后端默认不暴露 `/docs` 或 OpenAPI 浏览页；路由本身仍进入受控开发诊断模式的 OpenAPI 契约。响应不得包含密码、community、Token、服务端绝对路径或任意环境变量。

相关契约见 [API DTO 模型](../../models/api/README.md)、[Application Service](../../application/README.md)、[业务服务](../../services/README.md)和[设备管理页面](../../../../apps/web/src/views/devices/README.md)。当前低 CPU 限制下已运行设备详情定向 API/Query 测试；生产构建和全量测试仍延后。
