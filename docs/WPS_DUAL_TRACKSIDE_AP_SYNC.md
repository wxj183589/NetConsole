# 轨旁 AP 业务 WPS 双目标同步

本功能将当前局点、`rail_transit.trackside_ap_business` 的一次冻结快照同时发送到两个独立目标：

- 普通在线表格：`wps_standard_spreadsheet`，按 Sheet 执行 `FULL_REPLACE` 或 `APPEND_SNAPSHOT`。
- 智能表格：`wps_smart_sheet`，目标配置默认关闭。当前仅提供只读连接探针；多维表正式写入标记为 `RUNTIME_UNVERIFIED`，在 WPS 运行时完成 API 验收前不会宣称同步成功。

两个目标共享同一个 `snapshot_revision`、`snapshot_sha256`、工作簿数据和父批次，但每个目标拥有独立的在线文档地址、webhook、DPAPI 凭据、`target_batch_id`、稳定 `binding_id`、身份校验、状态和重试记录。默认目标名称从当前局点的 `display_name` 动态生成；仅历史硬编码默认名会自动纠正，用户自定义名绝不覆盖。普通数据库不保存明文 Token；Windows 使用 DPAPI 加密保存凭据，开发连接验证可以临时使用目标专属环境变量 `NETCONSOLE_WPS_STANDARD_AIRSCRIPT_TOKEN` 或 `NETCONSOLE_WPS_SMART_AIRSCRIPT_TOKEN`。

轨旁 AP 页面中的“配置云文档”会分别保存每个目标的“在线文档连接”“webhook地址”和“脚本令牌”。保存 webhook 后，服务端从 webhook 的 `/file/{document_id}/.../script/{script_id}/sync_task` 路径固定文档和脚本身份；同步前会拒绝空地址、非 HTTPS、非 `kdocs.cn` 域名、IP 地址、查询参数和身份不一致的配置。普通在线表格与智能表格不能交叉复用 webhook 或脚本令牌。

连接门禁是：`BOUND` 允许同步；`UNBOUND` 只有在本次请求显式确认初始化绑定时允许；`UNKNOWN` 必须先执行连接测试；`LEGACY_BINDING_ID_MISMATCH` 必须先由用户显式迁移；`MISMATCH` 直接拒绝。连接测试、写入能力探针、`sync_test_sheet` 和独立 `sheet_order_probe` 分别持久化执行时间、状态、操作、文档 ID、脚本 ID、脚本版本、部署 ID 和脱敏消息；写入探针还完整保存核心能力、可选能力、全量替换与顶部插行就绪状态。诊断和远端身份是诊断证据，不是互相独立的永久硬门禁。正式同步只要求当前运行时写入探针为 `VERIFIED`，并继续执行绑定校验与运行时身份校验。配置页的“重新验证当前部署”会保留 URL、webhook、令牌和绑定，清除本地验证状态后依次执行连接测试、写入能力探针和 `sync_test_sheet`；`sheet_order_probe` 是 Phase A 的独立真实验证，不并入既有三项验证链。上述动作只读取或运行探针，绝不自动修改远端绑定。

本地数据库行标识 `target_id` 与云端逻辑绑定 `binding_id` 已分离。`binding_id` 按规范化后的 `site_id + business_key + target_code` 使用 `wpsbind:v1` 规则确定性生成，因此同一业务目标在开发数据根、恢复副本或重新安装后保持一致，不同局点或目标保持隔离。`wps_sync.sqlite` 只执行幂等增量迁移：旧库新增 `binding_id` 列并只回填空值，不重建表、不删除目标、凭据或历史批次；重复初始化不会改变已有稳定值。这个本地迁移不会自动修改远端 `_NetConsoleSyncMeta`。

连接测试会同时返回本地与远端 Binding ID、远端文档/局点/业务/目标代码/目标类型，以及 `document_identity_match`、`site_identity_match`、`business_identity_match`、`target_code_match`、`target_type_match` 和 `binding_id_match`。只有远端 Binding ID 符合历史 `wst_<32 位十六进制>` 形式且其他身份全部一致时，才分类为 `LEGACY_BINDING_ID_MISMATCH`。历史状态若仍标记 `BOUND`，但保存的远端 Binding ID 与本地稳定 ID 不同，客户端会降级为 `UNKNOWN`，要求重新连接验证，不能直接进入正式同步。

界面的“升级旧版绑定标识”是显式远端持久化操作。确认框必须展示文档、局点、业务、旧 Binding ID 和新 Binding ID；确认后调用 `migrate_legacy_binding`，参数包含 `expected_old_binding_id` 与 `new_binding_id`。AirScript 再次严格核对 `document_id`、`site_id`、`business_key`、`target_code`、`target_type`，并确认当前远端 Binding ID 仍等于预检时的旧值，随后只更新 `_NetConsoleSyncMeta` 中 `binding_id` 对应的 B 列单元格。任一业务身份不一致、旧值已变化或远端值不是已知旧格式，均返回 `WPS_DOCUMENT_BINDING_MISMATCH` 且零写入；远端已经是新稳定 ID 时返回 `already_migrated=true`，不重复写入。迁移成功后服务端自动执行连接测试、写入能力探针和 `sync_test_sheet`，三项都通过才向界面返回完成。

修改在线文档连接、webhook、webhook 中的文档 ID 或脚本 ID 会清除旧远端身份、四类诊断和运行时探针状态，并将运行时能力降级为 `DEPLOYMENT_PENDING`；已有绑定记录保留，待新的连接测试重新确认。保存完全相同的连接地址和 webhook 是 no-op；修改超时、启用开关或 Token 不会清除远端部署身份、运行时探针或绑定身份。前端仅在草稿真实变化或输入新 Token 时保存，未修改配置时“测试连接”直接执行连接测试。

普通在线表格的数据写入链路已由杭州地铁 10 号线真实 9 Sheet 同步确认，证据等级为 `USER_FIELD_CONFIRMED`。该 `2.2.0-standard` / `trackside-ap-standard-2.2.0` 状态固定标记为 `WPS_STANDARD_DATA_SYNC_LAST_KNOWN_GOOD`。Phase A 的 `2.3.0-standard` / `trackside-ap-standard-2.3.0` 已在本地接入动态 Sheet 排序和独立探针，但真实 WPS `Sheet.Move()` 与 9 Sheet 回归仍为 `UNVERIFIED`；在用户完成现场验证前不能替代上述基线，也不能提交 Phase A。格式镜像开关继续关闭，列宽、行高、字体、填充、数字格式、对齐、换行、合并和边框均未启用。

## Phase A：Sheet 顺序（等待真实验证）

普通在线表格复用轨旁 AP 本地 XLSX 的同一次冻结快照和同一个 workbook builder，不维护第二套样式。`WorkbookDTO.sheet_order` 无条件按 `openpyxl workbook.worksheets` 的实际枚举顺序从零递增，且排除 `_NetConsole*` 系统 Sheet；Sheet 名称和顺序不包含杭州地铁 10 号线专属硬编码。可见性、标签色、合并区域、行高、列宽、冻结窗格和矩形 `format_runs` 仍由 `WPS_STANDARD_FORMAT_MIRROR_EXPERIMENTAL = false` 关闭。

`FULL_REPLACE` 和 `APPEND_SNAPSHOT` 继续使用 `WPS_STANDARD_DATA_SYNC_LAST_KNOWN_GOOD` 的 `writeStableSheet()`，函数内的清理、插行和二维 `Value2` 写入顺序不变。全部业务值写完后才进入独立 `reorderBusinessSheets()`：按 DTO 的 `sheet_order` 排序，使用 AirScript 2.0 官方 `Worksheet.Move(Before, After)` 位置参数显式移动，再重新枚举 `Application.Worksheets.Item(1..Count)`。业务 Sheet 读回顺序与 DTO 不完全一致时返回 `WPS_SHEET_ORDER_VERIFY_FAILED`，正式同步失败，但不会改变值写入协议。

`AP上线情况概览` 使用 `APPEND_SNAPSHOT`：先在顶部插入本次快照行，再写入值；旧历史块不执行清理，不覆盖历史备注或人工格式。

`_NetConsoleSyncMeta`、`_NetConsoleRuntimeProbe`、`_NetConsoleSyncTest` 及其他 `_NetConsole*` 系统 Sheet 不参与业务顺序，排序后尽量移动到业务 Sheet 后方并隐藏。系统 Sheet 移动或隐藏不兼容只记录 warning，返回 `SUCCESS_WITH_WARNINGS`，不会把已成功的数据写入降为失败。独立 `sheet_order_probe` 只创建或移动两个系统探针 Sheet，分别真实执行 `Move(Before)` 和 `Move(null, After)` 并读回校验，不清理或写入业务 Sheet 值。

Phase B～D 仍未启用：Phase B 为列宽和行高，Phase C 为字体、填充、数字格式、对齐和换行，Phase D 为合并与边框。每个阶段必须在前一阶段真实通过后独立实现、验证和提交。

## AirScript 部署

脚本源码位于：

- [`tools/wps_airscript/trackside_ap_standard_spreadsheet_sync.js`](../tools/wps_airscript/trackside_ap_standard_spreadsheet_sync.js)
- [`tools/wps_airscript/trackside_ap_smart_sheet_sync.js`](../tools/wps_airscript/trackside_ap_smart_sheet_sync.js)
- [`tools/wps_airscript/trackside_ap_standard_spreadsheet_connection_probe.js`](../tools/wps_airscript/trackside_ap_standard_spreadsheet_connection_probe.js)
- [`tools/wps_airscript/trackside_ap_smart_sheet_connection_probe.js`](../tools/wps_airscript/trackside_ap_smart_sheet_connection_probe.js)

需要分别复制到对应 WPS 文档并发布。Codex 不能直接修改或发布远端 AirScript。脚本中的 WPS `Application` 对象调用需以当前 WPS AirScript 运行时的实际 API 为准。仓库自动化测试会模拟 `_NetConsoleSyncMeta` 和 AirScript 2.0 `Move(Before, After)`，验证旧绑定迁移边界、动态 DTO 顺序、乱序纠正、系统 Sheet 后置、隐藏告警和业务顺序失败；这些本地模拟仍不能替代 WPS 运行时验收。

AirScript `sync_task` 的 HTTP 200 响应按 WPS 执行 envelope 解析：外层 `status=finished` 后读取 `data.result`，其中允许是 JSON 字符串或对象；再校验 NetConsole 的 `protocol_version`、`target_type`、`target_code`、`document_id`、`script_id`、`script_version` 和 `deployment_id`。正式同步收到 `success=false` 后立即保留远端 `error_code`、消息、绑定状态、失败 Sheet 和失败操作，不要求错误响应回显批次或快照字段；只有 `success=true` 时才严格校验 `target_batch_id`、局点、业务、revision 和摘要，并在不一致时返回 expected/remote 对照。直接返回协议对象仅作为本地测试 double 的兼容形式，不能据此宣称远端脚本已验证。WPS 编辑器显示“执行完毕”只代表编辑器执行结束，不代表 webhook 有返回值；必须确认 `data.result` 不是 `[Undefined]`。四个部署脚本的顶层入口必须是 `return main();`，不能使用单独 `main();` 或 `console.log(main())`。脚本版本与部署 ID 由本地常量和脚本常量共同维护，每次发布脚本必须同步更新。

连接探针只读取 `Context.argv` 与既有 `_NetConsoleSyncMeta`，不创建 Sheet、字段或记录，不清空、不删除、不初始化绑定。它返回 `UNBOUND`、`BOUND`、`LEGACY_BINDING_ID_MISMATCH` 或 `MISMATCH`，并附带本地/远端 Binding ID 和逐项身份匹配结果。只读探针明确拒绝 `migrate_legacy_binding`；必须先在同一文档共享脚本中部署正式同步脚本，才能执行受控迁移。仓库没有可替代 WPS 编辑器的 AirScript 运行时；四个脚本都必须以顶层 `return main();` 返回 JSON。仅调用 `main();` 或使用 `console.log(main())` 会使 webhook 的 `data.result` 缺少协议结果，即使 WPS 编辑器显示“执行完毕”，也不能视为连接验证通过。

普通表格在正式同步前建议依次完成连接测试、运行时能力探针和 `sync_test_sheet`；其中运行时能力探针成功后目标才标为 `VERIFIED`。核心能力包括 Sheet 枚举、定位、创建、单值和二维 `Value2` 写后读回、`UsedRange`、`ClearContents` 和 `EntireRow.Insert()`；系统 Sheet 隐藏属于可选能力。`Worksheet.Visible` 按布尔值、数值或 `XlSheetVisibility` 文本兼容判断，无法确认隐藏状态时返回 `SUCCESS_WITH_WARNINGS`，不会把已经通过的核心数据写入能力降级。连接测试和同步测试的历史诊断用于页面和任务中心定位问题，不会因旧部署记录单独锁死正式同步。正式脚本使用 `Value2` 写二维数组，追加模式通过 N 行 Range 的 `EntireRow.Insert()` 插行；业务写入前严格核验远端 `_NetConsoleSyncMeta` 的 `document_id`、`binding_id`、`site_id`、`business_key`、`target_code` 和 `target_type`。未绑定文档必须在 UI 二次确认后才允许初始化；任一不一致返回 `WPS_DOCUMENT_BINDING_MISMATCH`，不会触碰业务 Sheet。

智能表格脚本不再使用未验证的 `book.Tables`、`DataTables`、`EnsureFields`、`DeleteWhere` 或 `AddRecords`。正式写入前需要在目标运行时核对官方 `Application.Sheet`、`Application.Field`、`Application.Record.CreateRecords` 和 `Application.Record.DeleteRecords` 的实际参数、分页和限额；未完成前脚本返回 `WPS_SMART_SHEET_RUNTIME_UNVERIFIED`。

连接测试失败会返回阶段化脱敏诊断：`LOCAL_CONFIGURATION`、`HTTP_AUTH`、`SCRIPT_EXECUTION`、`PROTOCOL_HANDSHAKE`、`DOCUMENT_IDENTITY` 或 `SUCCESS`，并在适用时包含 HTTP 状态、WPS 错误码、原因和建议。HTTP 错误正文最多读取 64 KiB，不保存令牌、请求头、完整 webhook 或业务 payload；真实 403 原因仍取决于 WPS 返回内容和远端账号/脚本权限。

## 真实验证顺序

1. 在“配置云文档”中为每个目标独立保存在线文档地址、webhook 和脚本令牌；智能表格默认关闭。
2. 使用界面的“复制连接测试脚本”，在对应文档新建 AirScript 2.0 脚本，确认末尾是 `return main();`，运行只读探针后再复制同一个脚本的 webhook。
3. 回到 NetConsole 更新 webhook，点击“测试连接”，先确认 `sync_task` 的 `data.result` 不是 `[Undefined]`，再核对返回的 `document_id`、`target_type`、`target_code`、`protocol_version`、脚本版本和部署 ID。
4. 通过“复制正式同步脚本”替换同一个脚本内容并保存；Phase A 普通表格候选脚本身份必须是 `2.3.0-standard` / `trackside-ap-standard-2.3.0`，再重新测试。不要把普通表格和智能表格 webhook 交叉使用。
5. 对普通表格点击“测试写入能力”，确认 `_NetConsoleRuntimeProbe` 的二维数组写入与回读通过；未通过时正式同步保持禁用。
6. 点击“测试同步 Sheet”，确认 `_NetConsoleSyncTest` 写入、回读和清理通过；若更换脚本或部署，使用“重新验证当前部署”自动清理旧验证状态并依次重跑三项测试。
7. 点击“测试 Sheet 排序”，确认返回 `sheet_order_verified=true`、`sheet_move_before_verified=true`、`sheet_move_after_verified=true`；系统 Sheet 隐藏不兼容可以是 warning。该探针不并入“重新验证当前部署”。
8. 连接测试若显示 `LEGACY_BINDING_ID_MISMATCH`，先核对本地/远端 Binding ID 和五类业务身份均匹配，再点击“升级旧版绑定标识”；在确认框复核文档、局点、业务和新旧 ID。完成后系统会自动重跑连接、写入能力和同步测试，Binding 状态必须变为 `BOUND`。`MISMATCH` 不允许迁移。
9. 首次同步会显示当前局点与未绑定文档的二次确认；只有确认后才初始化远端绑定。绑定不匹配时停止写入并在任务详情显示原始错误码、失败 Sheet 和失败操作。
10. 确认当前局点业务 revision 后，手动点击页面的“同步云文档”。
11. 将同一次本地 XLSX 与普通在线表格逐 Sheet 对比名称、顺序、行列数和关键值；业务 Sheet 顺序必须完全一致，颜色、宽高及其他格式仍不作为 Phase A 验收项。
12. 检查 `AP上线情况概览` 新块位于顶部且旧历史值未被覆盖。
13. 任一目标失败时，只重试失败目标；已成功目标不重复写入。

同步按钮只提交 `trackside_ap_wps_sync` Job Center 任务，不在 FastAPI 请求线程执行工作簿构建或 webhook 网络请求。任务完成后，在统一任务中心查看父任务的 `SUCCESS`、`SUCCESS_WITH_WARNINGS`、`PARTIAL_SUCCESS` 或 `FAILED` 业务结果，以及普通表格和智能表格各自的目标结果与格式告警。

当前令牌已在会话中公开出现，真实验证完成后应在 WPS 重新生成令牌，再通过安全配置入口录入新令牌。
