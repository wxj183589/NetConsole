# 轨旁 AP 业务 WPS 云文档同步

本功能把当前局点 `rail_transit.trackside_ap_business` 的一次冻结快照手动同步到一个 WPS 在线表格。产品只支持：

- `target_code = wps_standard_spreadsheet`
- `target_type = WPS_STANDARD_SPREADSHEET`

轨旁 AP 页面只提供“同步云文档”“打开云文档”和“配置云文档”。连接地址、Webhook、脚本令牌、Binding、部署身份和诊断按局点独立保存。Windows 使用 DPAPI 加密保存脚本令牌，API、任务参数、日志、错误详情和持久化请求载荷都不得包含明文令牌。

## 已验收基线

普通在线表格的正式脚本是：

- 脚本版本：`2.8.4-standard`
- 部署 ID：`trackside-ap-standard-2.8.4`
- 源码：[`tools/wps_airscript/trackside_ap_standard_spreadsheet_sync.js`](../tools/wps_airscript/trackside_ap_standard_spreadsheet_sync.js)
- 连接探针：[`tools/wps_airscript/trackside_ap_standard_spreadsheet_connection_probe.js`](../tools/wps_airscript/trackside_ap_standard_spreadsheet_connection_probe.js)

该脚本是杭州地铁 10 号线当前 `LAST_KNOWN_GOOD`。产品层或配置 UI 调整不得改变其数据写入、历史追加、Sheet 顺序、标签色、格式、冻结窗格、筛选、Binding、异步任务或读回协议，也不得仅因此升级脚本版本。现有局点的文档链接、Webhook、令牌、Binding 和同步历史必须继续有效，用户不需要重新部署远端脚本。

WPS 编辑器显示“执行完毕”不代表 Webhook 有业务返回值。两个部署脚本都必须以顶层 `return main();` 返回 JSON；必须确认 `sync_task` 的 `data.result` 不是 `[Undefined]`。

## 配置与身份门禁

“配置云文档”保留以下信息：

- 启用云文档同步
- 请求超时
- 在线文档连接
- Webhook 地址
- 脚本令牌
- 文档 ID、脚本 ID、脚本版本和部署 ID
- 本地与远端 Binding ID
- 远端局点和业务身份
- 连接、写入、同步测试、标签色和列宽诊断

保存 Webhook 后，服务端从 `/file/{document_id}/.../script/{script_id}/sync_task` 固定文档和脚本身份。空地址、非 HTTPS、非 `kdocs.cn` 域名、IP 地址、查询参数或身份不一致的配置均被拒绝。

绑定门禁：

- `BOUND`：允许同步。
- `UNBOUND`：仅在用户显式确认首次绑定后允许写入。
- `UNKNOWN`：必须先测试连接。
- `LEGACY_BINDING_ID_MISMATCH`：必须显式升级旧版 Binding。
- `MISMATCH`：拒绝同步和迁移。

`binding_id` 按规范化后的 `site_id + business_key + target_code` 使用 `wpsbind:v1` 规则确定性生成。更换数据根或恢复副本不会改变同一局点业务的 Binding，不同局点保持隔离。

修改在线文档连接、Webhook、文档 ID 或脚本 ID会清除旧远端身份和本地验证状态，并将运行时能力降级为 `DEPLOYMENT_PENDING`。修改超时、启用开关或令牌不清除已验证部署身份和绑定。

## 工作簿协议

本地 XLSX 和 WPS 使用同一次冻结快照与同一个 Workbook Builder。固定业务顺序为：

1. `AP上线情况概览`
2. `轨旁AP业务`
3. `当前异常光衰`
4. `AP光衰处理记录`
5. `AP离线情况`
6. `AP离线台账`
7. `新增上线AP概览`
8. `待关联在线AP`
9. `交换机光模块统计`

`AP上线情况概览` 与 `新增上线AP概览` 是两个独立业务 Sheet。前者使用 `PREPEND_SNAPSHOT`：顶部依次写日期、更新时间、表头、当前统计、合计和一行空白，再保留旧历史；后者使用 `FULL_REPLACE`。

其余业务 Sheet 使用 `FULL_REPLACE`。正式同步在写值后执行 `reorderBusinessSheets()` 并重新枚举 Worksheets；顺序读回不一致时返回 `WPS_SHEET_ORDER_VERIFY_FAILED`。配置 UI 不提供独立 Sheet 排序探针，正式同步的排序和读回校验继续保留。

标签色：

- `AP上线情况概览`、`轨旁AP业务`：`#C6EFCE`
- `当前异常光衰`：`#FFEB9C`
- `AP光衰处理记录`：`#DDEBF7`
- `AP离线情况`、`AP离线台账`：`#D9D9D9`

冻结规则：`AP上线情况概览` 不冻结；其余八个业务 Sheet 只冻结首行，不冻结列。格式镜像继续覆盖 ColumnWidth、AutoFit、RowHeight、Font、Fill、NumberFormat、Alignment、Merge、Border、Freeze Pane 和 AutoFilter，并执行远端读回验证。格式失败返回 `SUCCESS_WITH_WARNINGS`，不得把已成功的数据写入误报为失败。

## 异步执行与恢复

用户只配置 WPS 编辑器复制的 `.../sync_task` Webhook。后端由唯一解析器派生：

- 探针：`.../sync_task`
- 正式提交：`.../task`
- 查询：`/api/v3/script/task`

正式同步先持久化 `target_batch_id`、无凭据请求载荷和源格式清单，再提交远端任务。完整 `task_id` 只保存在局点 `sync/wps_sync.sqlite`，UI 和日志只展示脱敏 ID。

取得 `task_id` 后的超时、连接复位、临时 DNS、5xx 或 429 记为 `REMOTE_RESULT_UNKNOWN`，继续使用原任务 ID 查询，绝不重复 POST。Backend 重启后优先恢复未完成批次。只有 WPS 明确返回终态脚本错误时才记为 `WPS_REMOTE_EXECUTION_FAILED`。

Job Center 任务名称为“轨旁 AP 业务 WPS 云文档同步”。任务结果仍使用单元素 `targets` 数组，以保持任务详情与历史结构稳定；数组中只会有一个 WPS 云文档结果。

## 本地升级迁移

功能收敛后，`WpsSyncRepository.initialize()` 会执行一次精确、幂等的退役目标清理：

- 只删除已退役目标的本地配置、运行记录和专属诊断。
- 只删除完全由已退役目标引用的本地凭据。
- 若凭据仍被当前 WPS 云文档引用，则必须保留。
- 混合历史批次保留当前云文档运行记录并重算计数；仅包含退役目标的批次删除。
- 删除不再使用的独立排序探针诊断列。
- 重复初始化为 no-op。

迁移不访问 WPS API，不删除、清空或修改任何远端文档。测试只能使用临时数据根，不能使用正式业务数据根。

## 部署与验证

1. 打开 WPS 在线表格和文档共享 AirScript。
2. 复制连接测试脚本，粘贴、保存并运行。
3. 从同一个共享脚本复制 Webhook，回 NetConsole 保存 Webhook 和令牌。
4. 测试连接，确认文档、脚本、部署和 Binding 身份。
5. 在同一个共享脚本中全量替换为正式同步脚本并保存。
6. 执行“重新验证当前部署”，依次完成连接、写入能力和同步测试 Sheet。
7. 必要时独立复查标签色或列宽能力。
8. 返回轨旁 AP 页面执行“同步云文档”。
9. 在任务中心核对远端状态、9 个 Sheet、格式读回和业务抽样结果。
10. 自动报告通过后只做一次整体视觉抽查。

NetConsole 不会远程替用户编辑或发布 AirScript。重新创建文档共享脚本会改变 `script_id`，旧 Webhook 随之失效。
