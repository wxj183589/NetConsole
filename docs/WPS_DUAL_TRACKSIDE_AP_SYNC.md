# 轨旁 AP 业务 WPS 双目标同步

本功能将当前局点、`rail_transit.trackside_ap_business` 的一次冻结快照同时发送到两个独立目标：

- 普通在线表格：`wps_standard_spreadsheet`，按 Sheet 执行 `FULL_REPLACE` 或 `APPEND_SNAPSHOT`。
- 智能表格：`wps_smart_sheet`，目标配置默认关闭。当前仅提供只读连接探针；多维表正式写入标记为 `RUNTIME_UNVERIFIED`，在 WPS 运行时完成 API 验收前不会宣称同步成功。

两个目标共享同一个 `snapshot_revision`、`snapshot_sha256`、工作簿数据和父批次，但每个目标拥有独立的在线文档地址、webhook、DPAPI 凭据、`target_batch_id`、稳定 `binding_id`、身份校验、状态和重试记录。默认目标名称从当前局点的 `display_name` 动态生成；仅历史硬编码默认名会自动纠正，用户自定义名绝不覆盖。普通数据库不保存明文 Token；Windows 使用 DPAPI 加密保存凭据，开发连接验证可以临时使用目标专属环境变量 `NETCONSOLE_WPS_STANDARD_AIRSCRIPT_TOKEN` 或 `NETCONSOLE_WPS_SMART_AIRSCRIPT_TOKEN`。

轨旁 AP 页面中的“配置云文档”会分别保存每个目标的“在线文档连接”“webhook地址”和“脚本令牌”。保存 webhook 后，服务端从 webhook 的 `/file/{document_id}/.../script/{script_id}/sync_task` 路径固定文档和脚本身份；同步前会拒绝空地址、非 HTTPS、非 `kdocs.cn` 域名、IP 地址、查询参数和身份不一致的配置。普通在线表格与智能表格不能交叉复用 webhook 或脚本令牌。

连接门禁是：`BOUND` 允许同步；`UNBOUND` 只有在本次请求显式确认初始化绑定时允许；`UNKNOWN` 必须先执行连接测试；`MISMATCH` 直接拒绝。连接测试、写入能力探针和 `sync_test_sheet` 分别持久化执行时间、状态、操作、文档 ID、脚本 ID、脚本版本、部署 ID 和脱敏消息；只有成功的连接测试更新“当前远端脚本身份”。因此旧版本连接失败可以作为该操作的历史诊断保留，但不会冒充当前远端版本。

修改在线文档连接、webhook、webhook 中的文档 ID 或脚本 ID 会清除旧连接身份、绑定状态和三类验证，并将运行时能力降级为 `DEPLOYMENT_PENDING`。保存完全相同的连接地址和 webhook 是 no-op；修改超时、启用开关或 Token 不会清除远端部署身份、运行时探针或绑定身份。前端仅在草稿真实变化或输入新 Token 时保存，未修改配置时“测试连接”直接执行连接测试。

普通在线表格的数据写入链路已由杭州地铁 10 号线真实 9 Sheet 同步确认，证据等级为 `USER_FIELD_CONFIRMED`。`2.3.0-standard` 新增的格式恢复、Sheet 排序和系统 Sheet 隐藏已完成 DTO/脚本自动化，状态为 `IMPLEMENTED_RUNTIME_PENDING`；在新版脚本部署到 WPS 并完成视觉对比前，不得写成真实格式验收通过。

## 普通表格镜像契约

普通在线表格复用轨旁 AP 本地 XLSX 的同一次冻结快照和同一个 workbook builder，不维护第二套样式。`WorkbookDTO` 按本地 `workbook.worksheets` 顺序携带每个业务 Sheet 的 `sheet_order`、可见性、标签色、合并区域、行高、列宽、冻结窗格和矩形 `format_runs`。每个 Format Run 包含 Range 地址及字体、填充、数字格式、对齐和边框；连续同格式单元格先横向合并，再将相邻行的同列区间纵向合并，避免逐单元格 AirScript 调用。

`FULL_REPLACE` 的远端顺序是：取消旧合并、`Range.Clear()` 清除旧值和旧样式、写入二维 `Value2`、恢复合并/宽高/Format Run/冻结窗格/可见性，最后按 `sheet_order` 从后向前调用 `Sheet.Move({Before, After})`。本地已删除的格式不会依靠旧 WPS 单元格残留。

`AP上线情况概览` 使用 `APPEND_SNAPSHOT`：先在顶部插入本次快照行，只对新插入的矩形取消继承合并并执行 `Range.Clear()`，再写入值和恢复合并、行高及 Format Run。旧历史块不执行 Clear，也不重新应用 Format Run，避免覆盖历史备注或人工颜色；列宽作为 Sheet 级属性按当前本地模板更新。

所有 `_NetConsole*` Sheet 在业务 Sheet 排序完成后移动到末尾并隐藏，包括 `_NetConsoleSyncMeta`、`_NetConsoleRuntimeProbe` 和 `_NetConsoleSyncTest`。格式、冻结窗格、标签色或 Sheet 移动等非关键 API 在真实 WPS 运行时不支持时，脚本继续保留核心数据成功，返回有界 `format_warnings`，目标和父批次状态为 `SUCCESS_WITH_WARNINGS`。`Value2`、插行或业务 Sheet 创建失败仍返回 `FAILED`。

## AirScript 部署

脚本源码位于：

- [`tools/wps_airscript/trackside_ap_standard_spreadsheet_sync.js`](../tools/wps_airscript/trackside_ap_standard_spreadsheet_sync.js)
- [`tools/wps_airscript/trackside_ap_smart_sheet_sync.js`](../tools/wps_airscript/trackside_ap_smart_sheet_sync.js)
- [`tools/wps_airscript/trackside_ap_standard_spreadsheet_connection_probe.js`](../tools/wps_airscript/trackside_ap_standard_spreadsheet_connection_probe.js)
- [`tools/wps_airscript/trackside_ap_smart_sheet_connection_probe.js`](../tools/wps_airscript/trackside_ap_smart_sheet_connection_probe.js)

需要分别复制到对应 WPS 文档并发布。Codex 不能直接修改或发布远端 AirScript。脚本中的 WPS `Application` 对象调用需以当前 WPS AirScript 运行时的实际 API 为准，仓库自动化测试只覆盖本地协议、身份、幂等数据模型和敏感信息边界，不能替代 WPS 运行时验收。

AirScript `sync_task` 的 HTTP 200 响应按 WPS 执行 envelope 解析：外层 `status=finished` 后读取 `data.result`，其中允许是 JSON 字符串或对象；再校验 NetConsole 的 `protocol_version`、`target_type`、`target_code`、`document_id`、`script_id`、`script_version` 和 `deployment_id`。直接返回协议对象仅作为本地测试 double 的兼容形式，不能据此宣称远端脚本已验证。WPS 编辑器显示“执行完毕”只代表编辑器执行结束，不代表 webhook 有返回值；必须确认 `data.result` 不是 `[Undefined]`。四个部署脚本的顶层入口必须是 `return main();`，不能使用单独 `main();` 或 `console.log(main())`。脚本版本与部署 ID 由本地常量和脚本常量共同维护，每次发布脚本必须同步更新。

连接探针只读取 `Context.argv` 与既有 `_NetConsoleSyncMeta`，不创建 Sheet、字段或记录，不清空、不删除、不初始化绑定。它返回 `UNBOUND`、`BOUND` 或绑定元数据，供界面显示当前局点、目标文档与远端绑定局点。仓库没有可替代 WPS 编辑器的 AirScript 运行时；四个脚本都必须以顶层 `return main();` 返回 JSON。仅调用 `main();` 或使用 `console.log(main())` 会使 webhook 的 `data.result` 缺少协议结果，即使 WPS 编辑器显示“执行完毕”，也不能视为连接验证通过。

普通表格在正式同步前必须依次完成成功连接测试、运行时能力探针和 `sync_test_sheet`：只操作并隐藏 `_NetConsoleRuntimeProbe` 或 `_NetConsoleSyncTest`，验证 `Application.Worksheets` 的枚举/定位/创建、`Value2` 标量与二维数组读写、`UsedRange`、`ClearContents`、`EntireRow.Insert` 和 `Visible`。正式同步门禁要求远端确认身份、运行时探针身份和同步测试身份全部与当前 webhook 的同一 `document_id`、`script_id`、`script_version` 和 `deployment_id` 匹配；旧版本成功状态不能复用。正式脚本使用 `Value2` 写二维数组，追加模式通过 N 行 Range 的 `EntireRow.Insert()` 插行；业务写入前严格核验远端 `_NetConsoleSyncMeta` 的 `document_id`、`binding_id`、`site_id`、`business_key`、`target_code` 和 `target_type`。未绑定文档必须在 UI 二次确认后才允许初始化；任一不一致返回 `WPS_DOCUMENT_BINDING_MISMATCH`，不会触碰业务 Sheet。

智能表格脚本不再使用未验证的 `book.Tables`、`DataTables`、`EnsureFields`、`DeleteWhere` 或 `AddRecords`。正式写入前需要在目标运行时核对官方 `Application.Sheet`、`Application.Field`、`Application.Record.CreateRecords` 和 `Application.Record.DeleteRecords` 的实际参数、分页和限额；未完成前脚本返回 `WPS_SMART_SHEET_RUNTIME_UNVERIFIED`。

连接测试失败会返回阶段化脱敏诊断：`LOCAL_CONFIGURATION`、`HTTP_AUTH`、`SCRIPT_EXECUTION`、`PROTOCOL_HANDSHAKE`、`DOCUMENT_IDENTITY` 或 `SUCCESS`，并在适用时包含 HTTP 状态、WPS 错误码、原因和建议。HTTP 错误正文最多读取 64 KiB，不保存令牌、请求头、完整 webhook 或业务 payload；真实 403 原因仍取决于 WPS 返回内容和远端账号/脚本权限。

## 真实验证顺序

1. 在“配置云文档”中为每个目标独立保存在线文档地址、webhook 和脚本令牌；智能表格默认关闭。
2. 使用界面的“复制连接测试脚本”，在对应文档新建 AirScript 2.0 脚本，确认末尾是 `return main();`，运行只读探针后再复制同一个脚本的 webhook。
3. 回到 NetConsole 更新 webhook，点击“测试连接”，先确认 `sync_task` 的 `data.result` 不是 `[Undefined]`，再核对返回的 `document_id`、`target_type`、`target_code`、`protocol_version`、脚本版本和部署 ID。
4. 通过“复制正式同步脚本”替换同一个脚本内容并保存；普通表格必须确认脚本身份是 `2.3.0-standard` / `trackside-ap-standard-2.3.0`，再重新测试。不要把普通表格和智能表格 webhook 交叉使用。
5. 对普通表格点击“测试写入能力”，确认 `_NetConsoleRuntimeProbe` 的二维数组写入与回读通过；未通过时正式同步保持禁用。
6. 点击“测试同步 Sheet”，确认 `_NetConsoleSyncTest` 写入、回读和清理通过；页面中的连接测试、写入能力和同步测试三条诊断必须显示同一个脚本 ID、版本和部署 ID。
7. 首次同步会显示当前局点与未绑定文档的二次确认；只有确认后才初始化远端绑定。绑定不匹配时停止写入并在任务详情显示错误码、失败 Sheet 和失败操作。
8. 确认当前局点业务 revision 后，手动点击页面的“同步云文档”。
9. 将同一次本地 XLSX 与普通在线表格逐 Sheet 对比名称、顺序、行列数、关键值、合并区域、列宽、行高、表头填充/字体、数字和百分比格式、对齐、换行及边框；允许 WPS 与 openpyxl 的颜色表示和列宽单位存在小幅平台差异。
10. 检查 `AP上线情况概览` 新块位于顶部且旧历史格式未被覆盖，并确认所有 `_NetConsole*` Sheet 已隐藏且位于末尾。
11. 任务为 `SUCCESS_WITH_WARNINGS` 时检查 `format_warnings` 的 Sheet、能力和原因，确认业务值完整后再判断是否接受平台格式差异；数据不完整必须按 `FAILED` 处理。
12. 任一目标失败时，只重试失败目标；已成功目标不重复写入。

同步按钮只提交 `trackside_ap_wps_sync` Job Center 任务，不在 FastAPI 请求线程执行工作簿构建或 webhook 网络请求。任务完成后，在统一任务中心查看父任务的 `SUCCESS`、`SUCCESS_WITH_WARNINGS`、`PARTIAL_SUCCESS` 或 `FAILED` 业务结果，以及普通表格和智能表格各自的目标结果与格式告警。

当前令牌已在会话中公开出现，真实验证完成后应在 WPS 重新生成令牌，再通过安全配置入口录入新令牌。
