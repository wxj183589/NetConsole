# 旧版 NetConsole 模块与入口契约

Renderer 侧栏由 [导航注册表](../../apps/desktop_renderer/src/navigation/registry.ts) 生成，工作区通过 [Vue Router](../../apps/desktop_renderer/src/router/routes.ts) 懒加载。已有 [Feature Registry](../../src/netconsole/core/feature_registry.py) 决定功能交付与权限，路由守卫负责深链，侧栏分组只表达业务归属。模块间使用 Service、API 和含稳定 ID 的路由，通过当前局点确定数据范围。

| 入口 | 导航与数据责任 |
| --- | --- |
| 设备资料 | 设备管理保留设备主体和接入资料。档案索引使用设备管理分页 API，按设备 UUID 打开档案 |
| 控制台 | 通用会话、快捷交互和会话内 SFTP。协议与会话状态由原模块承载 |
| 无线管理 | FIT-AP 资源与 AP 扩展等现有无线入口。未实现的 AC 占位能力继续隐藏 |
| 轨道交通 | 组织结构、基础资料、无线看板、轨旁 AP、MESH、地面实时和回放、车载 MR 实时和回放 |
| 设备任务 | 任务中心、配置采集中心、设备诊断下载。任务中心负责执行和历史，具体采集模块继续负责参数与结果呈现 |
| 工具集 | 外部独立工具 |
| 文件管理 | 本地受管文件与设备文件传输使用独立入口。设备侧 SFTP 会话仍从控制台使用 |
| 网络服务 | 连通性检测、流量测试、无线扫描、本机监听服务、网络测试组件。原工作区和权限保留 |
| 软件说明与维护 | 运行日志、任务日志、服务日志、命令参考、清理、版本记录、开源许可、关于与系统设置 |

## 路由与工作区

- `/devices/archive`（`device-archives`）是档案索引。`/devices/:deviceId`（`device-detail`）是每台设备的档案页，工作区以设备 UUID 标识。设备管理行、双击和右键复用该入口。
- `/rail-transit/ground-unattended` 与 `/rail-transit/ground-unattended-replay` 是独立路由和工作区，共用 `module.ground_unattended`。车载 MR 保留 `online-mr`、`online-mr-analysis` 路径，回放保留 `session_id` 工作区身份。
- `/file-manager`（`device-file-manager`）归本地受管文件，组件为 `FileManagerWorkspaceView.vue`。`/device-files`（`device-file-downloads`）归设备文件传输，默认复用 `FileManagementView.vue`，用 `view=sftp` 打开原双向 SFTP 工作区。`/file-management` 与带 `device_uuid` 的旧本地文件深链保留传输兼容跳转。`/device-files/diagnostics` 路由归设备任务。
- `/tools/connectivity`、`/tools/network-components` 和 `/tools/network-services` 等保留 URL 与独立 gate。已有浏览器入口继续走现有 API，桌面组件仍由 Electron 白名单管理。组件配置当前管理 fping 和 iPerf3，连通性与监听工作区各自复用原服务。
- `/command-reference` 继续跳到维护页的命令参考，保留 query/hash。`/storage-management` 继续进入系统设置的局点存储。保留 AC、工具、原地面监控与旧看板兼容跳转。

## 设备档案与消费边界

设备主表由设备管理写入。`device_uuid` 是档案、任务和业务关系使用的稳定身份。设备名称和 IP 用于展示、搜索和连接。设备档案页面复用 `DeviceDetailPanel`、设备管理 API 与 `DeviceDetailApplicationService`，沿用当前局点、能力页签、懒加载与服务端分页。概览、接口、光模块、LLDP、配置、任务及关联业务继续消费各自领域的已保存事实，技术快照更新走原显式采集任务。

设备基本资料在设备管理更新，组织关系在组织结构更新，无线业务在无线模块更新，任务记录及 Artifact 由任务领域维护。档案暴露只读聚合与到相应入口的跳转。旧数据库字段、导入格式、配置快照与任务历史的读取契约继续兼容。导航与档案索引无数据库迁移或新写入路径。

## 文件、观察与任务

文件生命周期按现有所有者管理。设备传输负责远端连接和受管下载，文件管理负责本地受管目录，任务中心提供执行状态和 Artifact 引用。Explorer 动作由 Electron Main 验证由本地文件服务签发的受管路径或令牌。软件内部任务、运行与服务事件由维护工具消费，设备任务视图按 API 的领域与局点范围查询。

## 变更影响与复验

菜单与路由为共享契约，消费者包括应用侧栏、资源工作区、桌面专属入口、Feature Snapshot 和 Full/Customer 配置、设备与轨交入口、文件、任务、网络服务及维护页。导航沿用已有 feature ID、路径和命名路由，设备档案的独立索引沿用设备模块授权。缓存消费者包括工作区 tab 与已经加载的档案分区。轨交新回放组件及任务、文件和日志改动与相应分支合并后复验。真实 GUI、设备访问和制品验收以集成记录为准。
