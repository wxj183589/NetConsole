# AC 管理

## 当前状态

Electron AC/FIT-AP 处于 `PARTIAL / IMPLEMENTED_UNVERIFIED`。`/ac-management/fit-aps` 已不再是数据库只读页：Feature `web.ac_refresh` 的“更新 AC 信息”“更新 FIT-AP 资源”和 AP 详情“深度更新”都会创建持久化后台任务，经共享 Python Application Service 连接所选 H3C AC、保存 raw/命令记录并更新当前局点数据库。现有自动闭环仍待 Electron 人工和真实 AC 验收；历史行为只通过 Git 与最终迁移矩阵核对，全部缺口完成前不得标记 `COMPLETE`。

以列车为中心的 Mesh-Link 在线监控已并入 `/rail-transit/train-online`，AC 管理不再提供独立页面、导航或页面 Feature。底层 API 与 `web.rail_train_online` 共用门禁，Parser、Query Service、历史快照和 `ac_mesh_link_refresh` Task 继续作为列车在线状态的事实源。完整领域与匹配规则见 [轨道交通无线业务模型](RAIL_TRANSIT_WIRELESS.md)。

当前 FIT-AP 更新链路为：

```text
Vue AC 管理 -> POST /api/ac-management/refresh/fit-ap
  -> AcWebApplicationService -> ac_fit_ap_resources_refresh Job
  -> AcResourceService -> H3C CLI collector/parser -> AcRepository
  -> 当前局点 devices.db + raw/commands JSONL
  -> web-tasks 恢复模块结果 + 统一任务窗口停止/日志/Artifact
  -> Vue 刷新结构化结果
```

查询仍通过 SQLite URI `mode=ro` 和 `PRAGMA query_only=ON`；写入只发生在后台采集 Worker 的 `AcRepository`。数据库升级仅对 `ac_fit_ap_resources` 与 Radio history 执行幂等加列，不删除、不重建主库。

## 页面能力

- AC 总览：管理 IP、型号、软件版本、AP 总数、在线/离线/未认证、Radio 数量、关联光衰异常和数据更新时间；
- FIT-AP：后端搜索、筛选、排序和分页，默认按连接交换机自然升序、其次按归一化端口自然升序，缺失项后置；前端通过统一 `NcDataTable` 保存列显隐、顺序、手工列宽和固定位置，物理接口统一显示 `GE/XGE/25GE/40GE/100GE` 简称；FIT-AP、配置、Radio、历史、Mesh-Link、AP 扩展和规划页面不再各自维护列宽算法；
- AP 详情：基本信息、connection-record、Radio 1/2 状态/模式/频段/信道/带宽/利用率/功率/客户端/BSSID、LLDP/端口、交换机光模块和 AP 侧光衰；
- 真实更新：AC CPU/内存/型号/版本/HTTPS 端口、FIT-AP 普通资源、所选 AP 深度 BSSID 和 FIT-AP 光衰；FIT-AP 光衰默认共享并发 64，运行时按平台上限和目标 AP 数裁剪，并通过 `tasks.db` resource key 阻止同一 AC 与轨旁更新重复执行；任务进度、取消、失败、部分命令失败、页面重启恢复和完成后结果刷新；业务页只保留紧凑摘要，停止、日志和 Artifact 统一在 Electron 任务窗口处理；
- 真实 AC 写操作：只保留历史产品契约中的“固化新 AP”和“开启 AP 远程登录”两项固定命令；Feature `web.ac_dangerous_actions` 默认关闭，启用后必须经过命令预览、摘要校验、二次确认、真实后台 Task、取消和持久化审计；不在 AC 页扩展单独 `save force`；
- 配置快照：历史列表、受控正文分块、行号、搜索和同批次 running/saved 差异；
- 刷新：总览和详情 15 秒，FIT-AP 与快照历史 30 秒；页面隐藏或卸载后停止，连续失败三次后降为 60 秒并保留最后一次成功数据。
- Mesh-Link 底层能力：AC 管理只保留受控采集、Parser、结构化快照、raw 和基础设施查询，不再呈现列车监控页面。列车、CT/TC 端点、当前 AP、RSSI、位置、匹配状态和两侧收光统一由“轨道交通 / 列车在线情况”展示。

Radio State/Usage/Clients 来自真实 `display wlan ap all radio` fixture；Mode/Band 只从 H3C `display wlan ap all radio type` 原文提取，缺失时显示“--”，不按 RID 或信道推断。connection-record 与 radio type 已用 H3C 官方样例做契约测试，仍需真实 AC 验收。普通更新不执行全量 `radio verbose`；已有 BSSID 会被保留。单 AP 深度更新执行已迁入 Application Service 的固定 bulk 命令序列并只 upsert 所选 AP，不删除同 AC 的其他 AP，也不猜测尚无事实源的 name 作用域 verbose 命令。Web DTO 不返回 AP/设备序列号，不显示 Radio 3。

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

配置列表仅包含当前局点中 AC 对应的 `config_snapshots`。API 不返回绝对路径，只返回 `snapshot:<id>` 和文件名。正文继续调用现有 `extract_h3c_configuration_body`，差异继续调用 `compare_config_text`，本阶段没有改变配置裁剪或 diff 算法。

正文单次最多返回 200,000 字符，页面默认按 100,000 字符分块加载；diff 选择时加载一次，不轮询。当前 `config_snapshots` 没有任务 ID 字段，DTO 的 `task_id` 保持空值，不从文件名或路径猜测任务关联。

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

Mesh-Link `refresh` 只接受 `controller_id` 和 `include_switch_history`。请求不能携带命令、用户名或密码；同一 AC 的活动任务重复提交时返回已有 Task。Vue 不连接设备，Worker 从当前局点设备库读取受控凭据，固定执行：

```text
screen-length disable
display clock
display wlan mesh-link ap
display wlan mesh-link switch-history  # 仅布尔开关启用
```

不存在固化 AP、`save force`、远程登录、任意命令、SNMP SET、删除或配置下发接口，也不提供自动周期刷新。

原始回显位于当前局点 `files/rail_transit/ac_mesh_link/snapshots/<session_id>/raw/`。Worker 先在 `.staging` 完整写入 UTF-8 raw 和无绝对路径的 metadata，再原子移动到正式目录并在单个 SQLite 事务中写入结构化快照。数据库提交失败时 raw 转入受控 `failures/<task_id>`，最新成功快照保持不变。命令明确返回零条链路时生成有效空快照；空回显、命令错误或格式无法识别时任务失败，不把全部 MR 改成离线。

## 尚未完成或验收的 Electron 能力

- AP 信息导出、OmniPeek 名称表导出，以及详情页 Radio/LLDP/光衰历史 XLSX 导出仍需按当前代码和 Feature 状态复核；批量删除、AP 元数据 CSV/XLSX 导入、详情元数据保存及历史查看已进入永久链；
- FIT-AP CSV、光衰 XLSX、历史 XLSX 与 OmniPeek NAM 的 Export Process worker 已存在，但共享 `WebArtifactStore` 尚未允许对应 AC 来源，且 `.nam` 不在 Artifact 类型白名单；最小共享补丁是把 AC 导出来源映射到当前局点 `trackside_ap_outputs` 受控根，并允许 `.nam`，本分支不修改或复制共享 Artifact/Native Bridge；
- AP 扩展信息与轨旁规划的导入、导出和编辑闭环；
- 配置采集任务属于配置采集中心的对等范围，不在 AC 页扩展新设备命令；
- Electron 原生另存为、打开文件/目录和真实 AC 工作流人工验收。

上述能力和真实设备验收完成前保持 `PARTIAL / REAL_DEVICE_PENDING`，不得标记 `COMPLETE`。

## 定向验证

```powershell
.venv\Scripts\python.exe -m pytest tests/test_ac_management.py tests/test_ac_domain_job.py tests/test_ac_web_parity.py tests/test_ac_management_web_api.py -q
.venv\Scripts\python.exe -m pytest tests/test_ac_mesh_link_refresh_service.py tests/test_ac_mesh_link_refresh_job.py tests/test_ac_mesh_link_refresh_api.py -q
.venv\Scripts\python.exe -m pytest tests/test_ac_mesh_link_query_service.py tests/test_ac_mesh_link_web_api.py -q
cd apps/web
pnpm exec vitest run src/views/ac-management/AcManagementView.test.ts src/stores/acManagement.test.ts src/api/acWebParity.test.ts
pnpm exec vue-tsc --noEmit -p tsconfig.app.json
```

自动测试不连接真实 AC。connection-record、radio type 与整条设备链路标记 `REAL_DEVICE_PENDING`，不得用 Fake 结果替代现场验收。
