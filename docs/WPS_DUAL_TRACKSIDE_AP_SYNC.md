# 轨旁 AP 业务 WPS 双目标同步

本功能将当前局点、`rail_transit.trackside_ap_business` 的一次冻结快照同时发送到两个独立目标：

- 普通在线表格：`wps_standard_spreadsheet`，按 Sheet 执行 `FULL_REPLACE` 或 `APPEND_SNAPSHOT`。
- 智能表格：`wps_smart_sheet`，目标配置默认关闭。当前仅提供只读连接探针；多维表正式写入标记为 `RUNTIME_UNVERIFIED`，在 WPS 运行时完成 API 验收前不会宣称同步成功。

两个目标共享同一个 `snapshot_revision`、`snapshot_sha256`、工作簿数据和父批次，但每个目标拥有独立的在线文档地址、webhook、DPAPI 凭据、`target_batch_id`、稳定 `binding_id`、身份校验、状态和重试记录。默认目标名称从当前局点的 `display_name` 动态生成；仅历史硬编码默认名会自动纠正，用户自定义名绝不覆盖。普通数据库不保存明文 Token；Windows 使用 DPAPI 加密保存凭据，开发连接验证可以临时使用目标专属环境变量 `NETCONSOLE_WPS_STANDARD_AIRSCRIPT_TOKEN` 或 `NETCONSOLE_WPS_SMART_AIRSCRIPT_TOKEN`。

轨旁 AP 页面中的“配置云文档”会分别保存每个目标的“在线文档连接”“webhook地址”和“脚本令牌”。保存 webhook 后，服务端从 webhook 的 `/file/{document_id}/...` 路径固定文档身份；同步前会拒绝空地址、非 HTTPS、非 `kdocs.cn` 域名、IP 地址、查询参数和身份不一致的配置。

## AirScript 部署

脚本源码位于：

- [`tools/wps_airscript/trackside_ap_standard_spreadsheet_sync.js`](../tools/wps_airscript/trackside_ap_standard_spreadsheet_sync.js)
- [`tools/wps_airscript/trackside_ap_smart_sheet_sync.js`](../tools/wps_airscript/trackside_ap_smart_sheet_sync.js)
- [`tools/wps_airscript/trackside_ap_standard_spreadsheet_connection_probe.js`](../tools/wps_airscript/trackside_ap_standard_spreadsheet_connection_probe.js)
- [`tools/wps_airscript/trackside_ap_smart_sheet_connection_probe.js`](../tools/wps_airscript/trackside_ap_smart_sheet_connection_probe.js)

需要分别复制到对应 WPS 文档并发布。Codex 不能直接修改或发布远端 AirScript。脚本中的 WPS `Application` 对象调用需以当前 WPS AirScript 运行时的实际 API 为准，仓库自动化测试只覆盖本地协议、身份、幂等数据模型和敏感信息边界，不能替代 WPS 运行时验收。

AirScript `sync_task` 的 HTTP 200 响应按 WPS 执行 envelope 解析：外层 `status=finished` 后读取 `data.result`，其中允许是 JSON 字符串或对象；再校验 NetConsole 的 `protocol_version`、`target_type`、`target_code`、`document_id`、`script_version` 和 `deployment_id`。直接返回协议对象仅作为本地测试 double 的兼容形式，不能据此宣称远端脚本已验证。脚本版本与部署 ID 由本地常量和脚本常量共同维护，每次发布脚本必须同步更新。

连接探针只读取 `Context.argv` 与既有 `_NetConsoleSyncMeta`，不创建 Sheet、字段或记录，不清空、不删除、不初始化绑定。它返回 `UNBOUND`、`BOUND` 或绑定元数据，供界面显示当前局点、目标文档与远端绑定局点。仓库没有可替代 WPS 编辑器的 AirScript 运行时；四个脚本都必须以顶层 `return main();` 返回 JSON。仅调用 `main();` 或使用 `console.log(main())` 会使 webhook 的 `data.result` 缺少协议结果，即使 WPS 编辑器显示“执行完毕”，也不能视为连接验证通过。

普通表格在正式同步前必须运行 `runtime_write_probe`：只在 `_NetConsoleRuntimeProbe` 写入并读回 2×2 数组，成功后目标才标为 `VERIFIED`。正式脚本使用 `Value2` 写二维数组，追加模式通过 N 行 Range 的 `EntireRow.Insert()` 插行；业务写入前严格核验远端 `_NetConsoleSyncMeta` 的 `document_id`、`binding_id`、`site_id`、`business_key`、`target_code` 和 `target_type`。未绑定文档必须在 UI 二次确认后才允许初始化；任一不一致返回 `WPS_DOCUMENT_BINDING_MISMATCH`，不会触碰业务 Sheet。

智能表格脚本不再使用未验证的 `book.Tables`、`DataTables`、`EnsureFields`、`DeleteWhere` 或 `AddRecords`。正式写入前需要在目标运行时核对官方 `Application.Sheet`、`Application.Field`、`Application.Record.CreateRecords` 和 `Application.Record.DeleteRecords` 的实际参数、分页和限额；未完成前脚本返回 `WPS_SMART_SHEET_RUNTIME_UNVERIFIED`。

连接测试失败会返回阶段化脱敏诊断：`LOCAL_CONFIGURATION`、`HTTP_AUTH`、`SCRIPT_EXECUTION`、`PROTOCOL_HANDSHAKE`、`DOCUMENT_IDENTITY` 或 `SUCCESS`，并在适用时包含 HTTP 状态、WPS 错误码、原因和建议。HTTP 错误正文最多读取 64 KiB，不保存令牌、请求头、完整 webhook 或业务 payload；真实 403 原因仍取决于 WPS 返回内容和远端账号/脚本权限。

## 真实验证顺序

1. 在“配置云文档”中为每个目标独立保存在线文档地址、webhook 和脚本令牌；智能表格默认关闭。
2. 使用界面的“复制连接测试脚本”，在对应文档新建 AirScript 2.0 脚本，确认末尾是 `return main();`，运行只读探针后再复制同一个脚本的 webhook。
3. 回到 NetConsole 更新 webhook，点击“测试连接”，先确认 `sync_task` 的 `data.result` 不是 `[Undefined]`，再核对返回的 `document_id`、`target_type`、`target_code`、`protocol_version`、脚本版本和部署 ID。
4. 通过“复制正式同步脚本”替换同一个脚本内容并保存，再重新测试；不要把普通表格和智能表格 webhook 交叉使用。
5. 对普通表格点击“测试写入能力”，确认 `_NetConsoleRuntimeProbe` 的二维数组写入与回读通过；未通过时正式同步保持禁用。
6. 首次同步会显示当前局点与未绑定文档的二次确认；只有确认后才初始化远端绑定。绑定不匹配时停止写入并在任务详情显示错误码、失败 Sheet 和失败操作。
7. 确认当前局点业务 revision 后，手动点击页面的“同步云文档”。
8. 分别检查普通表格历史概览追加、智能表格批次记录追加、两个目标的 revision/SHA-256 一致和幂等重试。
9. 任一目标失败时，只重试失败目标；已成功目标不重复写入。

同步按钮只提交 `trackside_ap_wps_sync` Job Center 任务，不在 FastAPI 请求线程执行工作簿构建或 webhook 网络请求。任务完成后，在统一任务中心查看父任务的 `SUCCESS`、`PARTIAL_SUCCESS` 或 `FAILED` 业务结果，以及普通表格和智能表格各自的目标结果。

当前令牌已在会话中公开出现，真实验证完成后应在 WPS 重新生成令牌，再通过安全配置入口录入新令牌。
