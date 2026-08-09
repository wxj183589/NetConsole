# 轨旁 AP 业务 WPS 双目标同步

本功能将当前局点、`rail_transit.trackside_ap_business` 的一次冻结快照同时发送到两个独立目标：

- 普通在线表格：`wps_standard_spreadsheet`，按 Sheet 执行 `FULL_REPLACE` 或 `PREPEND_SNAPSHOT`。
- 智能表格：`wps_smart_sheet`，目标配置默认关闭。当前仅提供只读连接探针；多维表正式写入标记为 `RUNTIME_UNVERIFIED`，在 WPS 运行时完成 API 验收前不会宣称同步成功。

两个目标共享同一个 `snapshot_revision`、`snapshot_sha256`、工作簿数据和父批次，但每个目标拥有独立的在线文档地址、webhook、DPAPI 凭据、`target_batch_id`、稳定 `binding_id`、身份校验、状态和重试记录。默认目标名称从当前局点的 `display_name` 动态生成；仅历史硬编码默认名会自动纠正，用户自定义名绝不覆盖。普通数据库不保存明文 Token；Windows 使用 DPAPI 加密保存凭据，开发连接验证可以临时使用目标专属环境变量 `NETCONSOLE_WPS_STANDARD_AIRSCRIPT_TOKEN` 或 `NETCONSOLE_WPS_SMART_AIRSCRIPT_TOKEN`。

轨旁 AP 页面中的“配置云文档”会分别保存每个目标的“在线文档连接”“webhook地址”和“脚本令牌”。保存 webhook 后，服务端从 webhook 的 `/file/{document_id}/.../script/{script_id}/sync_task` 路径固定文档和脚本身份；同步前会拒绝空地址、非 HTTPS、非 `kdocs.cn` 域名、IP 地址、查询参数和身份不一致的配置。普通在线表格与智能表格不能交叉复用 webhook 或脚本令牌。

连接门禁是：`BOUND` 允许同步；`UNBOUND` 只有在本次请求显式确认初始化绑定时允许；`UNKNOWN` 必须先执行连接测试；`LEGACY_BINDING_ID_MISMATCH` 必须先由用户显式迁移；`MISMATCH` 直接拒绝。连接测试、写入能力探针、`sync_test_sheet`、独立 `sheet_order_probe`、独立 `sheet_tab_color_probe` 和独立 `column_width_probe` 分别持久化执行时间、状态、操作、文档 ID、脚本 ID、脚本版本、部署 ID 和脱敏消息；写入探针还完整保存核心能力、可选能力、全量替换与顶部插行就绪状态。诊断和远端身份是诊断证据，不是互相独立的永久硬门禁。正式同步只要求当前运行时写入探针为 `VERIFIED`，并继续执行绑定校验与运行时身份校验。配置页的“重新验证当前部署”会保留 URL、webhook、令牌和绑定，清除本地验证状态后依次执行连接测试、写入能力探针和 `sync_test_sheet`；三个 Sheet 格式/位置探针都保持独立，不并入既有三项验证链。上述动作只读取或运行探针，绝不自动修改远端绑定。

本地数据库行标识 `target_id` 与云端逻辑绑定 `binding_id` 已分离。`binding_id` 按规范化后的 `site_id + business_key + target_code` 使用 `wpsbind:v1` 规则确定性生成，因此同一业务目标在开发数据根、恢复副本或重新安装后保持一致，不同局点或目标保持隔离。`wps_sync.sqlite` 只执行幂等增量迁移：旧库新增 `binding_id` 列并只回填空值，不重建表、不删除目标、凭据或历史批次；重复初始化不会改变已有稳定值。这个本地迁移不会自动修改远端 `_NetConsoleSyncMeta`。

连接测试会同时返回本地与远端 Binding ID、远端文档/局点/业务/目标代码/目标类型，以及 `document_identity_match`、`site_identity_match`、`business_identity_match`、`target_code_match`、`target_type_match` 和 `binding_id_match`。只有远端 Binding ID 符合历史 `wst_<32 位十六进制>` 形式且其他身份全部一致时，才分类为 `LEGACY_BINDING_ID_MISMATCH`。历史状态若仍标记 `BOUND`，但保存的远端 Binding ID 与本地稳定 ID 不同，客户端会降级为 `UNKNOWN`，要求重新连接验证，不能直接进入正式同步。

界面的“升级旧版绑定标识”是显式远端持久化操作。确认框必须展示文档、局点、业务、旧 Binding ID 和新 Binding ID；确认后调用 `migrate_legacy_binding`，参数包含 `expected_old_binding_id` 与 `new_binding_id`。AirScript 再次严格核对 `document_id`、`site_id`、`business_key`、`target_code`、`target_type`，并确认当前远端 Binding ID 仍等于预检时的旧值，随后只更新 `_NetConsoleSyncMeta` 中 `binding_id` 对应的 B 列单元格。任一业务身份不一致、旧值已变化或远端值不是已知旧格式，均返回 `WPS_DOCUMENT_BINDING_MISMATCH` 且零写入；远端已经是新稳定 ID 时返回 `already_migrated=true`，不重复写入。迁移成功后服务端自动执行连接测试、写入能力探针和 `sync_test_sheet`，三项都通过才向界面返回完成。

修改在线文档连接、webhook、webhook 中的文档 ID 或脚本 ID 会清除旧远端身份、六类诊断和运行时探针状态，并将运行时能力降级为 `DEPLOYMENT_PENDING`；已有绑定记录保留，待新的连接测试重新确认。保存完全相同的连接地址和 webhook 是 no-op；修改超时、启用开关或 Token 不会清除远端部署身份、运行时探针或绑定身份。前端仅在草稿真实变化或输入新 Token 时保存，未修改配置时“测试连接”直接执行连接测试。

普通在线表格的数据写入链路已由杭州地铁 10 号线真实 9 Sheet 同步确认，证据等级为 `USER_FIELD_CONFIRMED`。该 `2.2.0-standard` / `trackside-ap-standard-2.2.0` 状态固定标记为 `WPS_STANDARD_DATA_SYNC_LAST_KNOWN_GOOD`。Phase A 的 Sheet 排序、统一 registry、上线历史块和六个标签色也已由用户现场确认。`2.4.1-standard` 的独立列宽探针已确认 A-D 列写后读回和视觉递增，不能重复要求用户验证能力探针。`2.5.0-standard` 增加了正式 143 列的 XLSX、DTO、payload、`ColumnWidth` 和 `Width(points)` 全链路报告。当前候选 `2.8.3-standard` / `trackside-ap-standard-2.8.3` 增加真实业务列 AutoFit、本地宽度下限、按字段布局 Clamp、FULL_REPLACE 受管区域清理、百分比显示读回和确定性空表 Freeze；本地模拟与杭州 10 号线源 Workbook 审计完成后，真实 WPS 格式报告仍必须标记为 `UNVERIFIED`，发布前不得写成现场已验收。

## Phase A：Sheet 顺序（现场已验证）

普通在线表格复用轨旁 AP 本地 XLSX 的同一次冻结快照和同一个 workbook builder，不维护第二套样式。`TRACKSIDE_AP_BUSINESS_SHEET_DEFINITIONS` 是业务 Sheet 身份、名称、顺序、同步模式和标签色的唯一真源；`WorkbookDTO.sheet_order` 无条件按 `openpyxl workbook.worksheets` 的实际枚举顺序从零递增，且排除 `_NetConsole*` 系统 Sheet。固定业务顺序为：`AP上线情况概览`、`轨旁AP业务`、`当前异常光衰`、`AP光衰处理记录`、`AP离线情况`、`AP离线台账`、`新增上线AP概览`、`待关联在线AP`、`交换机光模块统计`。`AP上线情况概览` 与 `新增上线AP概览` 分别使用 `ap_online_history_overview` 和 `newly_online_ap_overview`，不得按中文相似名称混用。

`FULL_REPLACE` 和 `PREPEND_SNAPSHOT` 继续使用 `WPS_STANDARD_DATA_SYNC_LAST_KNOWN_GOOD` 的二维 `Value2` 写入和顶部插行协议。`FULL_REPLACE` 在写值前按 `_NetConsoleSyncMeta.managed_ranges_json` 清除上一轮与本轮最大受管区域的值、格式和 Merge；首次升级没有受管元数据时只用 `UsedRange` 做一次兼容清理。全部业务值写完后才进入独立 `reorderBusinessSheets()`：按 DTO 的 `sheet_order` 排序，使用 AirScript 2.0 官方 `Worksheet.Move(Before, After)` 位置参数显式移动，再重新枚举 `Application.Worksheets.Item(1..Count)`。业务 Sheet 读回顺序与 DTO 不完全一致时返回 `WPS_SHEET_ORDER_VERIFY_FAILED`，正式同步失败，但不会改变值写入协议。

`AP上线情况概览` 使用 `PREPEND_SNAPSHOT`。每个动态长度块依次包含北京时间日期、目标实际执行的北京时间、表头、站点数据、合计和一行全空分隔行；上线率保持 `0..1` 数值，数据区和合计行精确使用 `0.0%`，远端样本同时读回 Value、NumberFormat 和显示文本。旧历史块不执行清理，不覆盖历史值或人工格式。同一 `target_batch_id` 成功写入后记录在 `_NetConsoleSyncMeta`，重试时跳过该历史块，其他 `FULL_REPLACE` Sheet 仍可安全重放。本地 XLSX 使用相同块 DTO，更新时间取本地导出实际执行时间；该历史 Sheet 不启用跨块 AutoFilter。

`_NetConsoleSyncMeta`、`_NetConsoleRuntimeProbe`、`_NetConsoleSyncTest` 及其他 `_NetConsole*` 系统 Sheet 不参与业务顺序，排序后尽量移动到业务 Sheet 后方并隐藏。系统 Sheet 移动或隐藏不兼容只记录 warning，返回 `SUCCESS_WITH_WARNINGS`，不会把已成功的数据写入降为失败。独立 `sheet_order_probe` 只创建或移动两个系统探针 Sheet，分别真实执行 `Move(Before)` 和 `Move(null, After)` 并读回校验，不清理或写入业务 Sheet 值。

本地 XLSX 从 registry 应用六个标签色：`AP上线情况概览` 和 `轨旁AP业务` 为 `#C6EFCE`，`当前异常光衰` 为 `#FFEB9C`，`AP光衰处理记录` 为 `#DDEBF7`，`AP离线情况` 和 `AP离线台账` 为 `#D9D9D9`；其余三个业务 Sheet 保持默认。WPS 的 `sheet_tab_color_probe` 只在 `_NetConsoleSyncTest` 上将 `#C6EFCE` 经统一 `toWpsColor()` 转为 RGB 数值并写后读回。只有该目标探针成功后，正式同步才尝试镜像六个业务标签色；单个标签色失败只产生 `sheet_tab_color` warning 和 `SUCCESS_WITH_WARNINGS`，不会把数据同步判为失败。系统 Sheet 不设置业务标签色。字体、填充和边框颜色的后续格式阶段也必须复用同一转换函数。

## Phase B1：列宽与 AutoFit（探针现场已验证，正式读回待验证）

Python 从同一次本地导出 Workbook 提取 `column_widths`，并把每个真实业务列都加入 `auto_fit_columns`。共享字段定义同时下发 `compact / normal / identifier / datetime / long_text` 布局及各自 Min/Max，AirScript 不按中文表头猜类型。每列先对真实 `Columns` 执行 `AutoFit()`，再计算 `max(local_width, auto_width)` 并按布局边界 Clamp；长文本列上限为 48、保持 WrapText。每列都读回最终 `ColumnWidth` 与 `Width(points)`，报告同时保留本地宽度、AutoFit 宽度、最终请求值和远端读回；不换算像素，不维护按 Sheet 或杭州 10 号线专属倍率。

独立 `column_width_probe` 只操作 `_NetConsoleSyncTest`：写入 A-D 列可视标签，通过 `Worksheet.Columns.Item(column).ColumnWidth` 将列宽依次设置为 `8 / 15 / 25 / 40`，再读回并按 `0.5` 容差校验。该能力已现场确认，不再作为每次正式同步的本地状态门禁；普通在线表格正式同步始终发送 `column_width_enabled=true`，避免重新部署脚本后因清空历史诊断而要求用户重复探针。正式流程在数据和基础格式写完后执行真实业务列 AutoFit，随后才执行行 AutoFit、最小行高、Filter、排序、TabColor 和 Freeze；`AP上线情况概览` 只更新新插入块的格式，旧历史块保持不变。

每个正式业务列保留完整远端项目：模式、Sheet、列、Range、请求宽度、写入前后 `ColumnWidth`、写入前后 `Width(points)`、差异、物理宽度变化、Clamp、读回状态、验证状态、分类和原因。Python 在临时 XLSX 删除前建立源清单，再与 `SheetDTO`、序列化 payload 和远端项目合并成 `column_width_verification_report`。分类包括 `WORKBOOK_DTO_WIDTH_MISMATCH`、`WPS_PAYLOAD_WIDTH_MISMATCH`、`WPS_COLUMN_WIDTH_APPLY_MISMATCH`、`WPS_COLUMN_WIDTH_VALUE_VERIFIED` 和 `WPS_COLUMN_WIDTH_AUTOFIT_VERIFIED`；不在没有证据时引入宽度换算系数。

单列失败记录 `sheet_name`、`feature=column_width`、`range=A:A` 和脱敏原因，目标返回 `SUCCESS_WITH_WARNINGS`，不得把已经成功的数据写入降为失败。报告统计本地显式宽度、DTO 匹配、payload 匹配、设置、远端读回、物理宽度读回、验证通过、告警、失败、验证比例和各故障层级，保留全部列项目，并仅在任务详情展示最大差异和代表列摘要。`轨旁AP业务` 固定抽取 A/B/C/G/H/P 作为代表列。任务详情不能再把“赋值未抛异常”显示为列宽成功。

## Phase B2：正式格式镜像（本地规则已固定，WPS 读回待现场验证）

本地 XLSX 是样式唯一真源。共享 Workbook Builder 设置表头加粗/居中/换行、普通短字段居中、原因/备注/说明等长文本左对齐并换行、状态行填充、数字格式、边框、冻结窗格和筛选；WPS 不按业务值再次判断颜色。冻结规则固定为：`AP上线情况概览` 不冻结，其余 8 个业务 Sheet 只冻结首行（`A2`），所有 Sheet 均不冻结列，包括只有表头的空数据 Sheet。实际非空业务块使用 All Borders（外框、内部横线、内部竖线），历史概览块末尾的单独空白分隔行保持空白且不加边框。行高以本地显式值为下限：先写基线、执行 `Rows.AutoFit()`，再只抬高低于本地下限的行，长文本换行后的更高行不得压回 `24`。Python 将连续相同样式压缩为 `FormatRun`，单 Sheet 超过 1000 个 run 时停止该 Sheet 格式阶段并告警。格式失败只返回 `SUCCESS_WITH_WARNINGS`，不会把已经成功的数据同步降为失败。

`FULL_REPLACE` 按上一轮与本轮最大受管范围清理后重建，因此 `100 -> 0/20` 行不会残留旧 Value、Fill、Border、NumberFormat、Alignment、Merge 或 Filter；空数据 `当前异常光衰` 只保留本地定义的表头/占位内容，不允许残留大片红色。`AP上线情况概览` 的 `PREPEND_SNAPSHOT` 只清理并格式化本次顶部新插入块，旧历史值、旧历史格式和旧 Merge 不处理。同批次去重跳过的新块也不重新格式化。每个格式组执行 `WRITE -> READ BACK -> COMPARE`，记录 attempted、applied、read_back、verified、failed 和失败 Range；颜色和对齐可附带 `DisplayFormat` 作为只读辅助证据。代表样本覆盖表头、首行、中间行、末行以及最多四种不同填充行。

冻结窗格在所有数据、格式、AutoFit、筛选、Sheet 排序和标签色操作完成后统一执行最终化。脚本先直接写入并立即读回 `SplitRow`/`SplitColumn`/`FreezePanes`；若 WPS runtime 仍返回当前 ActiveCell 导致的旧行号，则清除旧状态，Activate 目标 Sheet，严格选择 `A2` 并验证 `ActiveCell`，随后再次明确写入 `SplitRow=1`、`SplitColumn=0` 才启用冻结。任何实际读回不等于期望值都会记录 `WPS_FREEZE_READBACK_FAILED` 或 `WPS_FREEZE_SELECTION_FAILED`，作为格式 warning，不得显示为冻结成功。

默认无填充、透明、Theme 或 Indexed 颜色不进入 DTO；只有显式不透明 ARGB 才规范化为 `#RRGGBB`。共享 Builder 用 `FFRRGGBB` 写入 openpyxl，AirScript 统一通过 `toWpsColor()` 转为 WPS RGB 数值，禁止把字符串直接赋给 `Color`，也禁止把无填充转换成黑色。

2026-08-08 杭州 10 号线本地源审计为 `LOCAL_DATASET_VERIFIED`：9 个 Sheet、143 个已用列全部有共享 Builder 计算出的显式宽度；从 `2.8.3-standard` 起这些列仍全部执行真实 AutoFit，显式宽度作为下限而不是跳过 AutoFit。共享 Builder 为业务区域生成统一行高规则（普通行最小 `24`，概览末尾分隔行最小 `16`），每次批次的 FormatRun、布局类型、行高和 payload 数量写入 `source_workbook_format_manifest`，不能用历史固定数字代替当前快照。该统计只能证明本地源和 payload，不替代远端 WPS 读回。

默认、真正透明、Theme 或 Indexed 颜色不进入 DTO；OpenXML 常见的 `00RRGGBB` 非黑色值视为显式颜色，和 `FFRRGGBB` 一样规范化为 `#RRGGBB`。后续所有 WPS 颜色写入必须继续通过唯一 `toWpsColor()` 转换，不能直接把 `#RRGGBB` 字符串赋给 `Color`。

## 正式同步的异步执行与恢复

用户仍只配置 WPS 编辑器复制出的 `.../sync_task` webhook。后端使用唯一 `parse_wps_webhook()` 严格提取 host、文件 ID 和脚本 ID，并集中派生同步探针地址 `.../sync_task`、正式提交地址 `.../task` 和查询地址 `/api/v3/script/task`；配置页不增加第二套 URL，也不通过分散的字符串替换拼接端点。

连接测试、运行时写入探针、同步测试 Sheet、Sheet 排序、标签色和列宽能力探针继续使用 `/sync_task`。包含 9 个业务 Sheet、格式写入和远端读回的 `sync_trackside_ap_business` 固定使用官方异步接口：`POST .../task` 快速取得 `task_id`，随后用 URL 编码后的 `task_id` 轮询 `GET /api/v3/script/task`。单次 HTTP timeout 与远端任务总等待分离；当前总等待上限为 600 秒，不能通过把 `/sync_task` timeout 增加到 60/120 秒替代异步执行。

`wps_sync_target_runs` 幂等新增 `remote_task_id`、`remote_task_type`、`remote_task_status`、提交/最近轮询/完成时间，以及无凭据的请求载荷和源格式清单。提交前先持久化 `target_batch_id` 与恢复载荷；拿到完整 `task_id` 后立即单独提交事务。完整 ID 只保存在局点 `sync/wps_sync.sqlite`，任务进度、任务中心和最近批次 API 只返回脱敏形式。脚本令牌仍由目标自己的 DPAPI Credential 解析，不能进入请求载荷、任务参数、结果、日志或错误详情。

远端状态是 WPS 业务状态，不扩展 Job Center 的七状态。运行记录使用 `REMOTE_SUBMITTING / REMOTE_SUBMITTED / REMOTE_RUNNING / REMOTE_FINISHED / REMOTE_RESULT_UNKNOWN`，WPS 明确返回脚本执行错误后才落为终态失败。取得 `task_id` 后的 timeout、10054、临时 DNS/5xx/429 只更新最近轮询和 `REMOTE_RESULT_UNKNOWN`，继续轮询且绝不再次 POST；程序或 Backend 重启后，再次进入同一同步用例会优先恢复未完成批次并查询已有 ID。提交阶段在未取得 ID 前发生 timeout 时，同样保留原 `target_batch_id` 和请求载荷；后续只允许用同一批次重试，依赖 AirScript `_NetConsoleSyncMeta` 的 `target_batch_id` 幂等保护，避免 `AP上线情况概览` 重复插入历史块。

`REMOTE_RESULT_UNKNOWN` 表示远端任务已经提交或提交结果不确定，当前尚不能确认最终结果；它不是 `FAILED`，批次不写完成时间，后续恢复仍使用原批次。`WPS_REMOTE_EXECUTION_FAILED` 只表示查询接口明确返回 `status=finished` 且带脚本执行错误。任务中心展示脱敏 Remote Task ID、任务类型、提交时间、最近查询和远端状态，不展示令牌、完整 ID、webhook 或持久化请求载荷。

## AirScript 部署

脚本源码位于：

- [`tools/wps_airscript/trackside_ap_standard_spreadsheet_sync.js`](../tools/wps_airscript/trackside_ap_standard_spreadsheet_sync.js)
- [`tools/wps_airscript/trackside_ap_smart_sheet_sync.js`](../tools/wps_airscript/trackside_ap_smart_sheet_sync.js)
- [`tools/wps_airscript/trackside_ap_standard_spreadsheet_connection_probe.js`](../tools/wps_airscript/trackside_ap_standard_spreadsheet_connection_probe.js)
- [`tools/wps_airscript/trackside_ap_smart_sheet_connection_probe.js`](../tools/wps_airscript/trackside_ap_smart_sheet_connection_probe.js)

需要分别复制到对应 WPS 文档并发布。Codex 不能直接修改或发布远端 AirScript。仓库自动化测试会模拟绑定、二维数据写入、顶部插行、Sheet 排序、标签色、显式列宽、AutoFit、行高、字体、填充、数字格式、对齐、Merge、Border、冻结窗格、筛选和远端读回；这些本地模拟仍不能替代 WPS 运行时验收。

AirScript 的同步探针响应和正式异步查询终态使用同一执行 envelope 解析：外层 `status=finished` 后读取 `data.result`，其中允许是 JSON 字符串或对象；再校验 NetConsole 的 `protocol_version`、`target_type`、`target_code`、`document_id`、`script_id`、`script_version` 和 `deployment_id`。正式同步收到 `success=false` 后立即保留远端 `error_code`、消息、绑定状态、失败 Sheet 和失败操作，不要求错误响应回显批次或快照字段；只有 `success=true` 时才严格校验 `target_batch_id`、局点、业务、revision 和摘要，并在不一致时返回 expected/remote 对照。直接返回协议对象仅作为本地测试 double 的兼容形式，不能据此宣称远端脚本已验证。WPS 编辑器显示“执行完毕”只代表编辑器执行结束，不代表 webhook 或异步查询有业务返回值；必须确认终态 `data.result` 不是 `[Undefined]`。四个部署脚本的顶层入口必须是 `return main();`，不能使用单独 `main();` 或 `console.log(main())`。脚本版本与部署 ID 由本地常量和脚本常量共同维护，每次发布脚本必须同步更新。

连接探针只读取 `Context.argv` 与既有 `_NetConsoleSyncMeta`，不创建 Sheet、字段或记录，不清空、不删除、不初始化绑定。它返回 `UNBOUND`、`BOUND`、`LEGACY_BINDING_ID_MISMATCH` 或 `MISMATCH`，并附带本地/远端 Binding ID 和逐项身份匹配结果。只读探针明确拒绝 `migrate_legacy_binding`；必须先在同一文档共享脚本中部署正式同步脚本，才能执行受控迁移。仓库没有可替代 WPS 编辑器的 AirScript 运行时；四个脚本都必须以顶层 `return main();` 返回 JSON。仅调用 `main();` 或使用 `console.log(main())` 会使 webhook 的 `data.result` 缺少协议结果，即使 WPS 编辑器显示“执行完毕”，也不能视为连接验证通过。

普通表格在正式同步前建议依次完成连接测试、运行时能力探针和 `sync_test_sheet`；其中运行时能力探针成功后目标才标为 `VERIFIED`。核心能力包括 Sheet 枚举、定位、创建、单值和二维 `Value2` 写后读回、`UsedRange`、`ClearContents` 和 `EntireRow.Insert()`；系统 Sheet 隐藏属于可选能力。`Worksheet.Visible` 按布尔值、数值或 `XlSheetVisibility` 文本兼容判断，无法确认隐藏状态时返回 `SUCCESS_WITH_WARNINGS`，不会把已经通过的核心数据写入能力降级。连接测试和同步测试的历史诊断用于页面和任务中心定位问题，不会因旧部署记录单独锁死正式同步。正式脚本使用 `Value2` 写二维数组，追加模式通过 N 行 Range 的 `EntireRow.Insert()` 插行；业务写入前严格核验远端 `_NetConsoleSyncMeta` 的 `document_id`、`binding_id`、`site_id`、`business_key`、`target_code` 和 `target_type`。未绑定文档必须在 UI 二次确认后才允许初始化；任一不一致返回 `WPS_DOCUMENT_BINDING_MISMATCH`，不会触碰业务 Sheet。

智能表格脚本不再使用未验证的 `book.Tables`、`DataTables`、`EnsureFields`、`DeleteWhere` 或 `AddRecords`。正式写入前需要在目标运行时核对官方 `Application.Sheet`、`Application.Field`、`Application.Record.CreateRecords` 和 `Application.Record.DeleteRecords` 的实际参数、分页和限额；未完成前脚本返回 `WPS_SMART_SHEET_RUNTIME_UNVERIFIED`。

连接测试失败会返回阶段化脱敏诊断：`LOCAL_CONFIGURATION`、`HTTP_AUTH`、`SCRIPT_EXECUTION`、`PROTOCOL_HANDSHAKE`、`DOCUMENT_IDENTITY` 或 `SUCCESS`，并在适用时包含 HTTP 状态、WPS 错误码、原因和建议。HTTP 错误正文最多读取 64 KiB，不保存令牌、请求头、完整 webhook 或业务 payload；真实 403 原因仍取决于 WPS 返回内容和远端账号/脚本权限。

## 真实验证顺序

1. 在“配置云文档”中为每个目标独立保存在线文档地址、webhook 和脚本令牌；智能表格默认关闭。
2. 使用界面的“复制连接测试脚本”，在对应文档新建 AirScript 2.0 脚本，确认末尾是 `return main();`，运行只读探针后再复制同一个脚本的 webhook。
3. 回到 NetConsole 更新 webhook，点击“测试连接”，先确认 `sync_task` 的 `data.result` 不是 `[Undefined]`，再核对返回的 `document_id`、`target_type`、`target_code`、`protocol_version`、脚本版本和部署 ID。
4. 通过“复制正式同步脚本”手工替换同一个 WPS 文档共享脚本内容并保存、发布；当前普通表格候选脚本身份必须是 `2.8.3-standard` / `trackside-ap-standard-2.8.3`，再重新测试。NetConsole 不能远程替用户编辑 WPS 脚本，不要把普通表格和智能表格 webhook 交叉使用。
5. 对普通表格点击“测试写入能力”，确认 `_NetConsoleRuntimeProbe` 的二维数组写入与回读通过；未通过时正式同步保持禁用。
6. 点击“测试同步 Sheet”，确认 `_NetConsoleSyncTest` 写入、回读和清理通过；若更换脚本或部署，使用“重新验证当前部署”自动清理旧验证状态并依次重跑三项测试。
7. 点击“测试 Sheet 排序”，确认返回 `sheet_order_verified=true`、`sheet_move_before_verified=true`、`sheet_move_after_verified=true`；系统 Sheet 隐藏不兼容可以是 warning。该探针不并入“重新验证当前部署”。
8. 点击“测试标签颜色”，确认 `_NetConsoleSyncTest` 返回 `sheet_tab_color_verified=true`、期望颜色 `#C6EFCE`，且写后读回的 RGB 数值一致。该探针不并入“重新验证当前部署”；失败时仍可执行数据同步，但正式同步不会启用业务标签色。
9. 列宽能力探针已经现场确认，不重复运行，也不要求用户再次查看 `_NetConsoleSyncTest`。连接测试若显示 `LEGACY_BINDING_ID_MISMATCH`，先核对本地/远端 Binding ID 和五类业务身份均匹配，再点击“升级旧版绑定标识”；在确认框复核文档、局点、业务和新旧 ID。完成后系统会自动重跑连接、写入能力和同步测试，Binding 状态必须变为 `BOUND`。`MISMATCH` 不允许迁移。
10. 首次同步会显示当前局点与未绑定文档的二次确认；只有确认后才初始化远端绑定。绑定不匹配时停止写入并在任务详情显示原始错误码、失败 Sheet 和失败操作。
11. 确认当前局点业务 revision 后，手动点击页面的“同步云文档”；任务详情应先显示脱敏 Remote Task ID 和 `submitted/running`，不能继续保持一个约 20 秒的 `/sync_task` HTTP 等待。
12. 远端状态进入 `finished` 后，在任务详情核对列宽的本地值、AutoFit 值、最终请求值、Clamp、远端读回、验证、告警和失败数量，以及 RowHeight、Font、Fill、NumberFormat、Alignment、Wrap、Merge、Border、FreezePane、Filter 和业务样本的写后读回结果。杭州 10 号线当前源应报告 143 个真实 AutoFit 请求；重点查看 `轨旁AP业务` 的 A/B/C/G/H/P 代表列，以及 `AP上线情况概览` 的 `0.81 / 0.0% / 81.0%` 样本。不能只依据 API 未抛异常判断格式成功。
13. 只有自动报告完成后，用户才做一次整体视觉抽查；不要求用户逐列测量宽度或逐项确认颜色。`Width(points)` 和 `DisplayFormat` 用于辅助判断平台单位或渲染差异，在形成稳定证据前不加入换算系数。
14. 检查 `AP上线情况概览` 新块依次为日期、更新时间、表头、数据、合计和恰好一行空白，且旧历史值与旧历史格式未被覆盖。
15. 使用相同 `target_batch_id` 重放脚本，确认不会再次插入历史块；使用新的批次再次同步，确认新块位于顶部、旧块完整下移。
16. 任一目标失败时，只重试失败目标；已成功目标不重复写入。

同步按钮只提交 `trackside_ap_wps_sync` Job Center 任务，不在 FastAPI 请求线程执行工作簿构建或 webhook 网络请求。任务完成后，在统一任务中心查看父任务的 `SUCCESS`、`SUCCESS_WITH_WARNINGS`、`PARTIAL_SUCCESS` 或 `FAILED` 业务结果，以及普通表格和智能表格各自的目标结果与格式告警。

当前令牌已在会话中公开出现，真实验证完成后应在 WPS 重新生成令牌，再通过安全配置入口录入新令牌。
