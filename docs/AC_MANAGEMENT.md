# AC 管理

## 当前状态

阶段 5C-4 在完整 Web 控制台中增加 AC 管理只读页面，入口为 `/ac-management`，Feature key 为 `web.ac_management`。Qt AC 页面仍是设备连接、采集和写操作的唯一生产入口；Web 页面只展示当前局点已有数据。

阶段 5C-5 增加独立的 `/ac-management/mesh-links` 页面，Feature key 为 `web.ac_mesh_links`。阶段 5C-5A 再增加 Feature key `ac.mesh_link.refresh` 的受控手工刷新。该页面展示“车载 MR ↔ 轨旁 FIT-AP”的 AC Mesh-Link 快照，不把 MR 建模为无线客户端。完整领域与匹配规则见 [轨道交通无线业务模型](RAIL_TRANSIT_WIRELESS.md)。

Web 只读链路为：

```text
Vue AC 管理
  -> GET /api/ac-management/*
  -> AcManagementQueryService
  -> AcRepository + 现有光衰/配置规则
  -> 当前局点 devices.db / 受控配置快照
```

Query Service 通过 SQLite URI `mode=ro` 和 `PRAGMA query_only=ON` 复用现有 `AcRepository` 查询，不初始化 schema、不修复数据、不更新时间戳。配置快照只能通过 `snapshot_id` 读取，路径必须是当前局点目录内的相对路径。

## 页面能力

- AC 总览：管理 IP、型号、软件版本、AP 总数、在线/离线/未认证、Radio 数量、关联光衰异常和数据更新时间；
- FIT-AP：后端搜索、筛选、排序和分页，前端列显隐、手工列宽及横向滚动；
- AP 详情：基本信息、Radio 1/2、LLDP/端口、交换机光模块和 AP 侧光衰；
- 配置快照：历史列表、受控正文分块、行号、搜索和同批次 running/saved 差异；
- 刷新：总览和详情 15 秒，FIT-AP 与快照历史 30 秒；页面隐藏或卸载后停止，连续失败三次后降为 60 秒并保留最后一次成功数据。
- Mesh-Link 在线监控：车载 MR 状态、当前轨旁 AP、Mesh Radio、RSSI、站点/区间、AP 在线与光衰关联、最近快照和切换事件；可选择 AC 创建一次 `ac_mesh_link_refresh` 任务，任务完成后自动刷新结构化数据和 raw。页面隐藏或卸载只停止轮询，不取消后台任务。

轨道交通 FIT-AP 资源采用 Mesh 接口/射频链路语义，仅展示 Mesh Radio 1/2 的信道、带宽、功率、BSSID 等真实采集字段，不展示客户端数量。当前数据库没有可靠的 Mesh Radio 状态、模式和频段时，API 返回空值，页面显示“--”，不得根据 Radio ID、信道或其他无关字段推测。Web DTO 不返回 AP/设备序列号，不显示 Radio 3 和端口变化列。

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
```

`refresh` 是 Mesh-Link 路由唯一 POST，只接受 `controller_id` 和 `include_switch_history`。请求不能携带命令、用户名或密码；同一 AC 的活动任务重复提交时返回已有 Task。Web 不连接设备，Worker 从当前局点设备库读取受控凭据，固定执行：

```text
screen-length disable
display clock
display wlan mesh-link ap
display wlan mesh-link switch-history  # 仅布尔开关启用
```

不存在固化 AP、`save force`、远程登录、任意命令、SNMP SET、删除或配置下发接口，也不提供自动周期刷新。

原始回显位于当前局点 `files/rail_transit/ac_mesh_link/snapshots/<session_id>/raw/`。Worker 先在 `.staging` 完整写入 UTF-8 raw 和无绝对路径的 metadata，再原子移动到正式目录并在单个 SQLite 事务中写入结构化快照。数据库提交失败时 raw 转入受控 `failures/<task_id>`，最新成功快照保持不变。命令明确返回零条链路时生成有效空快照；空回显、命令错误或格式无法识别时任务失败，不把全部 MR 改成离线。

## 保留在 Qt 的能力

- 除 Mesh-Link 白名单手工刷新外的 AC 连接和新采集；
- FIT-AP 资源、Radio、LLDP 与光衰刷新；
- 固化新上线 AP、开启 AP 远程登录和批量命令；
- `save force`、配置采集任务和其他设备写操作；
- 导出及现有 Qt AC 工作流。

Web 页面稳定前不替换 Qt AC 页面，也不改变现有 AC 命令、数据库 schema 或采集文件。

## 定向验证

```powershell
.venv\Scripts\python.exe -m pytest tests/test_ac_management_query_service.py -q
.venv\Scripts\python.exe -m pytest tests/test_ac_management_web_api.py -q
.venv\Scripts\python.exe -m pytest tests/test_ac_mesh_link_refresh_service.py tests/test_ac_mesh_link_refresh_job.py tests/test_ac_mesh_link_refresh_api.py -q
.venv\Scripts\python.exe -m pytest tests/test_ac_mesh_link_query_service.py tests/test_ac_mesh_link_web_api.py -q
cd apps/web
npm run test -- AcManagement
npm run test -- AcMeshLink
npm run build
```

自动测试不连接真实 AC。真实局点验证必须显式设置 `NETCONSOLE_ALLOW_REAL_AC_TEST=1` 并指定局点和 AC，只执行上述固定白名单命令；本阶段不提供默认真实设备测试入口。
