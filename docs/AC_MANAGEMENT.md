# AC 管理

轨旁端口 PVID 候选发现只使用当前逐站规划的 VLAN 集合；最终核验在 AP 身份解析后，将实际端口 PVID 与该 AP 归属站点的规划 VLAN 比较，不通过交换机所属站点或 VLAN 反推 AP 身份。相同 VLAN 跨站点是合法情况。旧 VLAN 分组数据不参与当前候选或核验。规划和核验细节见 [轨旁 AP 逐站规划](AP_MANAGEMENT_VLAN_GROUPS.md)。

## 当前状态

Electron AC/FIT-AP 处于 `PARTIAL / IMPLEMENTED_UNVERIFIED`。`/ac-management/fit-aps` 已不再是数据库只读页：Feature `web.ac_refresh` 的“更新 AC 信息”“更新 FIT-AP 资源”和 AP 详情“深度更新”都会创建持久化后台任务，经共享 Python Application Service 连接所选 H3C AC、保存 raw/命令记录并更新当前局点数据库。页面也已接入两项受控 AC 写动作、FIT-AP 资源 XLSX、当前 AC 范围的 OmniPeek 名称表导出和桌面版单 AP 外部终端；这些闭环仍待 Electron 人工和真实 AC/AP 验收，全部缺口完成前不得标记 `COMPLETE`。

`web.ac_dangerous_actions` 与 `web.ac_fit_ap_external_terminal` 已从开发隐藏项转为正式客户版默认功能。Feature Profile schema v2 会在升级首次加载时把 schema v1 中这两项的旧默认关闭状态迁移为正式默认值；用户在 v2 及以后主动关闭的选择保持不变，不要求删除 AppData。

以列车为中心的 Mesh-Link 在线监控已并入 `/rail-transit/train-online`，AC 管理不再提供独立页面、导航或页面 Feature。底层 API 与 `web.rail_train_online` 共用门禁，Parser、Query Service、历史快照和 `ac_mesh_link_refresh` Task 继续作为列车在线状态的事实源。完整领域与匹配规则见 [轨道交通无线业务模型](RAIL_TRANSIT_WIRELESS.md)。

当前 FIT-AP 更新链路为：

```text
Vue AC 管理 -> POST /api/ac-management/refresh/fit-ap
  -> AcWebApplicationService -> ac_fit_ap_resources_refresh Job
  -> AcResourceService -> H3C CLI collector/parser -> AcRepository
  -> 当前局点 devices.db + raw/commands JSONL
  -> Worker 终态返回有界持久化摘要 + reload_required
  -> Vue 通过分页 GET 重新读取 SQLite + 全局任务中心展示任务详情
```

查询仍通过 SQLite URI `mode=ro` 和 `PRAGMA query_only=ON`；写入只发生在后台采集 Worker 的 `AcRepository`。数据库升级仅对 `ac_fit_ap_resources` 与 Radio history 执行幂等加列，不删除、不重建主库。

`ac_info_refresh`、`ac_fit_ap_detail_refresh` 和 `ac_fit_ap_resources_refresh`
的 collect 终态均不携带完整 FIT-AP 资源、LLDP、BSSID 或 raw，只返回
更新计数、collect run、失败命令摘要、snapshot revision、
`data_persisted`、`reload_required` 及页面所需的小型 collection 摘要。
这使采集回执与资源查询彻底分离，避免大局点结果超过 Worker 1 MiB
单帧限制。兼容 `mode=load` 仍可返回完整快照；活动页面使用正式分页接口
读取资源。

`ac_fit_ap_optical_refresh` 的 collect 终态同样只返回成功/失败数量、
collect run、并发与重试轮次、持久化状态和 AP Identity 聚合，不返回完整
FIT-AP 资源、光衰行或逐项 Identity 明细。页面在任务完成后重新查询
SQLite；兼容 `mode=load` 仍返回完整光衰快照。单 AP 日志耗时从线程实际
执行开始计算，不再包含等待线程池槽位的时间；Windows 并发上限保持 64，
AP 控制台启用、三条 Telnet 采集命令和超时不变。

## 页面能力

- AC 总览：管理 IP、型号、软件版本、AP 总数、在线/离线/未认证、Radio 数量、关联光衰异常和数据更新时间；
- FIT-AP：后端搜索、筛选、排序和分页，默认按连接交换机自然升序、其次按归一化端口自然升序，缺失项后置；前端通过统一 `NcDataTable` 保存列显隐、顺序、手工列宽和固定位置，物理接口统一显示 `GE/XGE/25GE/40GE/100GE` 简称；FIT-AP、配置、Radio、历史、Mesh-Link、AP 扩展和规划页面不再各自维护列宽算法；
- FIT-AP 资源导出：Feature `web.ac_fit_ap_resource_export` 提供“当前筛选结果 / 已选择 AP / 当前 AC 全部 AP”三种范围，筛选复用页面 Query Service 且不携带分页。用户点击后先选择最终 `.xlsx` 路径，取消不创建任务；确认后 Export Process 从当前局点只读 SQLite 重新查询，按规范化 MAC 去重。MAC 缺失时使用 `AC ID + AP 名称`，保证“AP资源清单”一台 AP 一行，“Radio明细”一条 Radio 一行，并附“导出说明”。缺失的光衰、LLDP、站点、区间、MAC 或 Radio 保持空白并写入“数据完整性”，单台缺失不阻断整份文件。Artifact 就绪后直接写入预选位置，不再突然弹出第二个保存窗口；失败时保留 Artifact 并允许在任务中心重新选择位置。该导出用于资产核对，不替代设备管理清单或 OmniPeek `.nam` 名称表，也不会在导出时连接 AC、AP 或交换机；
- AP 详情：基本信息、connection-record、Radio 1/2 状态/模式/频段/信道/带宽/利用率/功率/客户端/BSSID、LLDP/端口、交换机光模块和 AP 侧光衰；
- 真实更新：AC CPU/内存/型号/版本/HTTPS 端口、FIT-AP 普通资源、批量 Radio BBSSID、所选 AP 深度 BSSID 和 FIT-AP 光衰；FIT-AP 光衰默认共享并发 64，运行时按平台上限和目标 AP 数裁剪，并通过 `tasks.db` resource key 阻止同一 AC 与轨旁更新重复执行；任务进度、取消、失败、部分命令失败、页面重启恢复和完成后结果刷新；业务页只保留紧凑摘要，停止、日志和 Artifact 统一在 Electron 任务窗口处理；
- 单 AP 定向更新接受 H3C 常见 `xxxx-xxxx-xxxx` MAC，后端统一规范化为标准格式；前端提交时优先使用 `ap_uuid`，其次 `ap_mac`，最后 `ap_name`，避免展示格式差异误拦稳定目标。
- 真实 AC 写操作：只保留历史产品契约中的“固化新 AP”和“开启 AP 远程登录”两项固定命令；Feature `web.ac_dangerous_actions` 是正式客户版默认功能，仍必须经过命令预览、摘要校验、二次确认、真实后台 Task、取消和持久化审计；不在 AC 页扩展单独 `save force`；
- OmniPeek 名称表：Feature `ac.omnipeek_name_table_export` 是正式客户版默认功能。窗口提供线路名、输出目录、三类数据源及真实数量、轨旁/车载导出内容、Radio 模式、颜色、结构化逐行预览、状态筛选、搜索、分页、选择和受控强制导出；AP 扩展信息只匹配当前 AC 的 FIT-AP，车载 MR 由用户决定是否加入。预览和 `.nam` 导出分别进入 Job Center 与 Export Process，继续复用共享 MAC 推导、冲突校验、导出日志、Artifact 清单、取消和恢复规则；
- 单 AP 外部终端：FIT-AP 行菜单由 `NcDataTable` 的类型安全菜单模型统一渲染，保留详情、光衰更新和复制动作。Feature `web.ac_fit_ap_external_terminal` 与 `desktop.native_bridge` 均为正式 Electron 默认功能；Python 只接受 AC/AP/终端类型语义 ID。H3C FIT-AP 外部终端使用固定 Telnet 23 端口直接打开，不保存、不读取、不传递 FIT-AP 用户名和密码，也不依赖设备管理中同 IP 设备或 SSH 配置。系统设置中的终端路径仍由 `available_external_terminal_configs` 管理，再通过 `DesktopActionService` 启动。Browser/Server、离线和无 IP 场景拒绝，API 不接收或返回程序路径、参数、协议、端口、用户名和密码；
- 配置快照：历史列表、受控正文分块、行号、搜索和同批次 running/saved 差异；
- 刷新：总览和详情 15 秒，FIT-AP 与快照历史 30 秒；页面隐藏或卸载后停止，连续失败三次后降为 60 秒并保留最后一次成功数据。
- Mesh-Link 底层能力：AC 管理只保留受控采集、Parser、结构化快照、raw 和基础设施查询，不再呈现列车监控页面。列车、CT/TC 端点、当前 AP、RSSI、位置、匹配状态和两侧收光统一由“轨道交通 / 列车在线情况”展示。

Radio State/Usage/Clients 来自真实 `display wlan ap all radio` fixture；Mode/Band 只从 H3C `display wlan ap all radio type` 原文提取，缺失时显示“--”，不按 RID 或信道推断。connection-record 与 radio type 已用 H3C 官方样例做契约测试，仍需真实 AC 验收。普通批量更新在固定命令序列中执行 `display wlan ap all radio verbose filter bbssid`，该命令使用独立 120 秒读取超时并属于可选增强证据：成功时合并 Radio BBSSID，空结果或失败时记录 `bbssid_collect_status/bbssid_error` 并保留原始命令回显，不得丢弃已经由必需命令采集到的 FIT-AP 资源。已有 BSSID 会被保留。单 AP 深度更新使用同一受控命令并只 upsert 所选 AP，不删除同 AC 的其他 AP，也不猜测尚无事实源的 name 作用域 verbose 命令。Web DTO 不返回 AP/设备序列号，不显示 Radio 3。

Electron 的“打开 AC Web”使用固定 HTTPS URL 规则：优先使用已采集端口，缺失或无效时回退 443；Python DTO 生成受控 URL，Vue 只通过现有 Electron 外部 URL Bridge 打开。

FIT-AP 详情已提供站点、里程、点位说明和方向保存入口；保存通过受控后台任务写入现有元数据表。归属站点缺失时，Query Service 只在 LLDP 已匹配/部分匹配且邻居唯一对应有站点的交换机时返回建议；页面明确标记“保存后才写入”，不自动修改元数据。Radio、LLDP、光衰历史按 AP UUID 分页读取，仅返回展示白名单字段，不向 Web 暴露 `raw_log_path`，并继续遵守 Web 既有序列号脱敏边界。

## 光衰关联规则

光衰阈值继续复用 `compute_ap_status`、`compute_switch_status` 与 `classify_optical_health()`，Vue 不重复计算。AP 在线状态和光模块健康状态是两个独立维度：在线 AP 的一般/严重光功率告警同样进入当前异常、概览和轨旁 AP 导出；离线 AP 的正常光功率不会伪造为光衰异常。Web 展示状态为：

| 状态 | 含义 |
| --- | --- |
| `normal` | 已有数据且阈值结果正常 |
| `warning` | 最新有效样本为关注、提示或一般光功率告警 |
| `critical` | 最新有效样本为严重告警、链路异常、链路断开或无光 |
| `no_data` | 没有可用光衰结果，或设备明确返回无光模块 |

“关联光衰异常”只统计 `data_freshness=fresh` 的 `warning` 和 `critical`，按 AP 身份去重；同 AP 多个异常接口仍保留全部明细。当前有效期为 24 小时，超期样本标记 `stale`，保留在历史中但不作为实时正常或当前异常计数。设备明确返回 `no_module` 时显示“无光模块”，不计入光衰异常；`no_light` 仅在模块存在且接收光功率缺失或低于无光阈值时按严重异常处理。详情页同时展示 AP 在线状态、光衰判定、告警等级、原因、数据状态与最近更新时间。

## 配置查看

配置列表仅包含当前局点中 AC 对应的 `config_snapshots`。API 不返回绝对路径，只返回 `snapshot:<id>` 和文件名。正文继续调用现有 `extract_h3c_configuration_body`，差异继续调用 `compare_config_text` 和 `build_side_by_side_rows`，没有改变配置裁剪或 diff 算法。

正文单次最多返回 200,000 字符，页面默认按 100,000 字符分块加载；diff 选择时加载一次，不轮询。对比响应按同批次 running/saved 快照 ID 与受控局点相对路径读取，返回左右完整清洗正文、标签、结构化行、计数摘要和兼容 `raw_diff`；Renderer 不解析 Unified Diff 还原正文。缺失、失败或 0B 快照不会打开空白对比器。

AC 页面通过本域 Adapter 转为 `SharedConfigDiffModel`，与配置采集中心共同使用 `apps/web/src/components/config-diff/ConfigDiffViewer.vue`。共享 Viewer 统一 Monaco Worker、Model 生命周期、并排/内联、换行、导航、明暗主题、大文件保护和结构化降级，但不依赖 AC 或配置采集 Store/API。当前 `config_snapshots` 没有任务 ID 字段，DTO 的 `task_id` 保持空值，不从文件名或路径猜测任务关联。

## API 与受控刷新边界

```text
GET /api/ac-management/summary
GET /api/ac-management/aps
GET /api/ac-management/aps/{ap_id}
GET /api/ac-management/aps/{ap_id}/radios
GET /api/ac-management/aps/{ap_id}/lldp
GET /api/ac-management/aps/{ap_id}/optical
GET /api/ac-management/optical-anomalies
GET /api/ac-management/config-snapshots
GET /api/ac-management/config-snapshots/{snapshot_id}
GET /api/ac-management/config-snapshots/{snapshot_id}/diff
POST /api/ac-management/refresh/fit-ap
POST /api/ac-management/actions/plans
POST /api/ac-management/actions/plans/{plan_id}/confirm
POST /api/ac-management/actions/plans/{plan_id}/execute
GET  /api/ac-management/actions/plans/{plan_id}
GET  /api/ac-management/actions/plans/{plan_id}/audit
POST /api/ac-management/fit-aps/omnipeek/preview
GET  /api/ac-management/fit-aps/omnipeek/preview/{task_id}
POST /api/ac-management/fit-aps/omnipeek/export
POST /api/ac-management/fit-aps/export
GET  /api/ac-management/fit-aps/omnipeek/preferences
PUT  /api/ac-management/fit-aps/omnipeek/preferences
GET  /api/ac-management/fit-aps/omnipeek/artifacts/{artifact_id}/download
GET  /api/ac-management/fit-aps/artifacts/{artifact_id}/download
GET  /api/ac-management/fit-aps/external-terminal/options
POST /api/ac-management/fit-aps/{ap_id}/external-terminal

# deprecated 底层 Mesh-Link 契约；不再对应 AC 用户页面
GET /api/ac-management/mesh-links/summary
GET /api/ac-management/mesh-links/current
GET /api/ac-management/mesh-links/mrs
GET /api/ac-management/mesh-links/mrs/{mr_id}
GET /api/ac-management/mesh-links/snapshots
GET /api/ac-management/mesh-links/raw-tail
POST /api/ac-management/mesh-links/refresh

# 正式列车在线入口
GET  /api/rail-transit/train-online/trains
GET  /api/rail-transit/train-online/trains/{train_id}
GET  /api/rail-transit/train-online/trains/{train_id}/events
POST /api/rail-transit/train-online/refresh
GET  /api/ac-management/web-tasks/{task_id}
POST /api/ac-management/web-tasks/{task_id}/cancel
POST /api/ac-management/web-tasks/recover
```

Mesh-Link `refresh` 只接受 `controller_id` 和 `include_switch_history`。请求不能携带命令、用户名或
密码；Vue 不连接设备，Worker 从当前局点设备库读取受控凭据，固定执行：

```text
screen-length disable
display clock
display wlan mesh-link ap
display wlan mesh-link switch-history  # 仅布尔开关启用
```

没有地面无人值守常驻 Poller 时，接口继续创建或复用原 `ac_mesh_link_refresh` 一次性 Task：单次建立
连接、采集快照并关闭，供人工刷新、单次诊断和非无人值守场景使用。已有相同控制器的
`ac_mesh_link_resident_poll` 时，接口不创建第二个 Task 或 SSH 会话，只向现有 Worker 写入立即轮询
请求，响应返回 resident `task_id`、本次 `request_id`、`task_mode=resident` 和“已请求常驻 AC 会话
立即刷新”。两种模式共用 `AcMeshLinkSnapshotCollector`，生成相同的 raw、parser 版本和快照结构。

常驻 Poller 仅由地面无人值守 Supervisor 管理，每台 AC 一个受控 Worker 和一个活动 SSH 会话；同一
连接内周期采集，连接失效时在同一 Task 内重连。上述 Mesh-Link 契约不存在固化 AP、`save force`、
远程登录、任意命令、SNMP SET、删除或配置下发接口；AC/FIT-AP 页面写动作只允许
`ACTION_DEFINITIONS` 中两项固定计划，不复用 Mesh-Link 接口。

原始回显位于当前局点 `files/rail_transit/ac_mesh_link/snapshots/<session_id>/raw/`。Worker 先在 `.staging` 完整写入 UTF-8 raw 和无绝对路径的 metadata，再原子移动到正式目录并在单个 SQLite 事务中写入结构化快照。数据库提交失败时 raw 转入受控 `failures/<task_id>`，最新成功快照保持不变。命令明确返回零条链路时生成有效空快照；空回显、命令错误或格式无法识别时任务失败，不把全部 MR 改成离线。

## 尚未完成或验收的 Electron 能力

- 动作页只把 `plan_id` 写入 `localStorage`，UI 和日志不展示 `confirm_token`；但当前 `AcActionPlanDTO` 仍把 Token 返回 Renderer，前端确认请求从内存 plan 回传。该实现尚未满足“Renderer 永不接收确认 Token”的严格边界，需后续改为服务端短期绑定或等价方案；修复前不得描述为 Token 完全未暴露给前端；
- FIT-AP 资源 XLSX 已接入 Export Process、`WebArtifactStore`、任务中心和共享用户目标协调器：Electron 在创建任务前通过 Preload Bridge 打开系统保存对话框，Artifact 完成后用预选目标、大小与 SHA-256 落盘；取消不创建任务，失败不删除 Artifact，可在任务中心重新选择位置。浏览器通过 Artifact 响应启动下载但不宣称验证本地落盘。固定样例已通过 openpyxl 结构校验，但真实局点 145 AP/290 Radio、WPS/Excel/LibreOffice 打开和 Electron 系统保存对话框仍待人工验收；详情页 Radio/LLDP/光衰历史独立 XLSX 仍未实现。批量删除、详情元数据保存及历史查看已进入永久链。AP 点表导入已归并到“轨道交通 / 基础资料”的统一预览、合并和审计链，AC 页不再显示独立导入入口；
- AC OmniPeek NAM 已接入共享 Export Process、`WebArtifactStore` 当前局点 `trackside_ap_outputs` 受控根、统一任务中心和 Electron 受控另存为；仍需用现场 OmniPeek 验证实际导入结果；
- 旧版 FIT-AP 登录凭据保存实现已废弃；当前 FIT-AP 外部终端固定生成 SecureCRT `/TELNET <AP_IP> 23`、Xshell `-url telnet://<AP_IP>:23` 或 PuTTY `-telnet <AP_IP> -P 23`，即使系统设置启用“启动外部终端时传递密码”也不会传递 FIT-AP 用户名或密码，也不会查询设备管理中的同 IP 记录。真实 AP 可达性和三类终端版本兼容仍需人工验收；
- AP 扩展信息导入和重命名命令导出由轨道交通基础资料统一承载；AC 侧不提供第二套入口。基础资料联动详情使用规范化 MAC 唯一匹配得到的 FIT-AP/AC ID，重复 MAC 不自动择一；
- 配置采集任务属于配置采集中心的对等范围，不在 AC 页扩展新设备命令；
- Electron 原生另存为、打开文件/目录和真实 AC 工作流人工验收。

上述能力和真实设备验收完成前保持 `PARTIAL / REAL_DEVICE_PENDING`，不得标记 `COMPLETE`。

## 定向验证

```powershell
.venv\Scripts\python.exe -m pytest tests/test_ac_management.py tests/test_ac_domain_job.py tests/test_ac_web_parity.py tests/test_ac_management_web_api.py -q
.venv\Scripts\python.exe -m pytest tests/test_fit_ap_resource_export.py -q
.venv\Scripts\python.exe -m pytest tests/test_ac_mesh_link_refresh_service.py tests/test_ac_mesh_link_refresh_job.py tests/test_ac_mesh_link_refresh_api.py -q
.venv\Scripts\python.exe -m pytest tests/test_ac_mesh_link_query_service.py tests/test_ac_mesh_link_web_api.py -q
cd apps/web
pnpm exec vitest run src/views/ac-management/AcManagementView.test.ts src/views/ac-management/AcManagementView.behavior.test.ts src/stores/acManagement.test.ts src/api/acWebParity.test.ts
pnpm exec vue-tsc --noEmit -p tsconfig.app.json
```

自动测试不连接真实 AC。connection-record、radio type 与整条设备链路标记 `REAL_DEVICE_PENDING`，不得用 Fake 结果替代现场验收。
