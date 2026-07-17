# AC 管理

## 当前状态

Electron AC/FIT-AP 迁移处于 `PARTIAL / IMPLEMENTED_UNVERIFIED`。`/ac-management/fit-aps` 已不再是数据库只读页：Feature `web.ac_refresh` 的“更新 AC 信息”“更新 FIT-AP 资源”和 AP 详情“深度更新”都会创建持久化后台任务，经共享 Python Application Service 连接所选 H3C AC、保存 raw/命令记录并更新当前局点数据库。现有自动闭环仍待 Electron 人工和真实 AC 验收，Qt 导出/规划等缺口也尚未补齐；Qt 只保留为缺口核对事实源，全部缺口完成前不得标记 `COMPLETE`。

阶段 5C-5 增加独立的 `/ac-management/mesh-links` 页面，Feature key 为 `web.ac_mesh_links`。阶段 5C-5A 再增加 Feature key `ac.mesh_link.refresh` 的受控手工刷新。该页面展示“车载 MR ↔ 轨旁 FIT-AP”的 AC Mesh-Link 快照，不把 MR 建模为无线客户端。完整领域与匹配规则见 [轨道交通无线业务模型](RAIL_TRANSIT_WIRELESS.md)。

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
- FIT-AP：后端搜索、筛选、排序和分页，前端列显隐、手工列宽及横向滚动；
- AP 详情：基本信息、connection-record、Radio 1/2 状态/模式/频段/信道/带宽/利用率/功率/客户端/BSSID、LLDP/端口、交换机光模块和 AP 侧光衰；
- 真实更新：AC CPU/内存/型号/版本/HTTPS 端口、FIT-AP 普通资源、所选 AP 深度 BSSID 和 FIT-AP 光衰；任务进度、取消、失败、部分命令失败、页面重启恢复和完成后结果刷新；业务页只保留紧凑摘要，停止、日志和 Artifact 统一在 Electron 任务窗口处理；
- 真实 AC 写操作：仅迁移 Qt 当前“固化新 AP”和“开启 AP 远程登录”两项固定命令；Feature `web.ac_dangerous_actions` 默认关闭，启用后必须经过命令预览、摘要校验、二次确认、真实后台 Task、取消和持久化审计；不在 AC 页扩展单独 `save force`；
- 配置快照：历史列表、受控正文分块、行号、搜索和同批次 running/saved 差异；
- 刷新：总览和详情 15 秒，FIT-AP 与快照历史 30 秒；页面隐藏或卸载后停止，连续失败三次后降为 60 秒并保留最后一次成功数据。
- Mesh-Link 在线监控：车载 MR 状态、当前轨旁 AP、Mesh Radio、RSSI、站点/区间、AP 在线与光衰关联、最近快照和切换事件；可选择 AC 创建一次 `ac_mesh_link_refresh` 任务，任务完成后自动刷新结构化数据和 raw。页面隐藏或卸载只停止轮询，不取消后台任务。

Radio State/Usage/Clients 来自真实 `display wlan ap all radio` fixture；Mode/Band 只从 H3C `display wlan ap all radio type` 原文提取，缺失时显示“--”，不按 RID 或信道推断。connection-record 与 radio type 已用 H3C 官方样例做契约测试，仍需真实 AC 验收。普通更新不执行全量 `radio verbose`；已有 BSSID 会被保留。单 AP 深度更新执行 Qt 既有 bulk 命令序列并只 upsert 所选 AP，不删除同 AC 的其他 AP，也不猜测尚无事实源的 name 作用域 verbose 命令。Web DTO 不返回 AP/设备序列号，不显示 Radio 3。

Electron 的“打开 AC Web”复用 Qt 相同的 HTTPS URL 规则：优先使用已采集端口，缺失或无效时回退 443；Python DTO 生成受控 URL，Vue 只通过现有 Electron 外部 URL Bridge 打开。

FIT-AP 详情已迁移 Qt 的站点、里程、点位说明和方向保存入口；保存通过受控后台任务写入现有元数据表。Radio、LLDP、光衰历史按 AP UUID 分页读取，仅返回展示白名单字段，不向 Web 暴露 `raw_log_path`，并继续遵守 Web 既有序列号脱敏边界。

## 光衰关联规则

光衰阈值继续复用 `compute_ap_status`、`compute_switch_status` 和统一 severity 规则，Vue 不重复计算。Web 展示状态为：

| 状态 | 含义 |
| --- | --- |
| `normal` | 已有数据且阈值结果正常 |
| `warning` | AP 离线，并关联到关注/提示级光衰结果 |
| `critical` | AP 离线，并关联到告警、链路异常或无光 |
| `no_data` | 没有可用光衰结果 |
| `unrelated` | 检测到异常光衰，但 AP 未离线，不计入 AP 光衰异常 |

“关联光衰异常”只统计 `warning` 和 `critical`。交换机无光但 AP 未离线时显示 `unrelated`，不计入异常总数；缺少采集结果时显示 `no_data`，不误判告警。

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
GET /api/ac-management/mesh-links/summary
GET /api/ac-management/mesh-links/current
GET /api/ac-management/mesh-links/mrs
GET /api/ac-management/mesh-links/mrs/{mr_id}
GET /api/ac-management/mesh-links/snapshots
GET /api/ac-management/mesh-links/raw-tail
POST /api/ac-management/mesh-links/refresh
POST /api/ac-management/refresh/fit-ap
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

## 尚未完成的 Qt 对等能力

- Qt AC 资源页的 AP 信息导出、OmniPeek 名称表导出，以及详情页 Radio/LLDP/光衰历史 XLSX 导出；批量删除、AP 元数据 CSV/XLSX 导入、详情元数据保存及历史查看已迁移；
- FIT-AP CSV、光衰 XLSX、历史 XLSX 与 OmniPeek NAM 的 Export Process worker 已存在，但共享 `WebArtifactStore` 尚未允许对应 AC 来源，且 `.nam` 不在 Artifact 类型白名单；最小共享补丁是把 AC 导出来源映射到当前局点 `trackside_ap_outputs` 受控根，并允许 `.nam`，本分支不修改或复制共享 Artifact/Native Bridge；
- AP 扩展信息与轨旁规划的全部 Qt 导入、导出和编辑入口；
- 配置采集任务属于配置采集中心的对等范围，不在 AC 页扩展新设备命令；
- 导出及现有 Qt AC 工作流。

上述能力和真实设备验收完成前不替换 Qt AC 页面。

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
