# 轨旁 AP 业务 WPS 双目标同步

本功能将当前局点、`rail_transit.trackside_ap_business` 的一次冻结快照同时发送到两个独立目标：

- 普通在线表格：`wps_standard_spreadsheet`，按 Sheet 执行 `FULL_REPLACE` 或 `APPEND_SNAPSHOT`。
- 智能表格：`wps_smart_sheet`，按记录和批次执行受管数据替换，保留非 NetConsole 记录。

两个目标共享同一个 `snapshot_revision`、`snapshot_sha256`、工作簿数据和父批次，但每个目标拥有独立的在线文档地址、webhook、DPAPI 凭据、`target_batch_id`、身份校验、状态和重试记录。普通数据库不保存明文 Token；Windows 使用 DPAPI 加密保存凭据，开发连接验证可以临时使用目标专属环境变量 `NETCONSOLE_WPS_STANDARD_AIRSCRIPT_TOKEN` 或 `NETCONSOLE_WPS_SMART_AIRSCRIPT_TOKEN`。

轨旁 AP 页面中的“配置云文档”会分别保存每个目标的“在线文档连接”“webhook地址”和“脚本令牌”。保存 webhook 后，服务端从 webhook 的 `/file/{document_id}/...` 路径固定文档身份；同步前会拒绝空地址、非 HTTPS、非 `kdocs.cn` 域名、IP 地址、查询参数和身份不一致的配置。

## AirScript 部署

脚本源码位于：

- [`tools/wps_airscript/trackside_ap_standard_spreadsheet_sync.js`](../tools/wps_airscript/trackside_ap_standard_spreadsheet_sync.js)
- [`tools/wps_airscript/trackside_ap_smart_sheet_sync.js`](../tools/wps_airscript/trackside_ap_smart_sheet_sync.js)

需要分别复制到对应 WPS 文档并发布。Codex 不能直接修改或发布远端 AirScript。脚本中的 WPS `Application` 对象调用需以当前 WPS AirScript 运行时的实际 API 为准，仓库自动化测试只覆盖本地协议、身份、幂等数据模型和敏感信息边界，不能替代 WPS 运行时验收。

## 真实验证顺序

1. 分别设置两个目标专属环境变量，或在“配置云文档”中为每个目标独立保存在线文档地址、webhook 和脚本令牌，然后只执行 `connection_test`。
2. 核对返回的 `document_id`、`target_type`、`protocol_version` 和对象清单。
3. 确认杭州地铁10号线当前业务 revision 后，手动点击页面的“同步云文档”。
4. 分别检查普通表格历史概览追加、智能表格批次记录追加、两个目标的 revision/SHA-256 一致和幂等重试。
5. 任一目标失败时，只重试失败目标；已成功目标不重复写入。

同步按钮只提交 `trackside_ap_wps_sync` Job Center 任务，不在 FastAPI 请求线程执行工作簿构建或 webhook 网络请求。任务完成后，在统一任务中心查看父任务的 `SUCCESS`、`PARTIAL_SUCCESS` 或 `FAILED` 业务结果，以及普通表格和智能表格各自的目标结果。

当前令牌已在会话中公开出现，真实验证完成后应在 WPS 重新生成令牌，再通过安全配置入口录入新令牌。
