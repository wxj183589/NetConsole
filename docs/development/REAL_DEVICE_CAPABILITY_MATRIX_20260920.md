# 真实设备能力矩阵（2026-09-20）

本矩阵是当前主线 `github/main@e93ae6b0a92fe3bbedd7a3cef5f307ca183d80fe` 的
能力与验收状态事实源。它只整理已有代码、自动化测试、正式文档和已保存的现场证据，
不执行设备连接、不读取 Production/Development Real Data，也不改变任何产品行为。

## 口径

`AUTOMATED_TEST` 只说明代码契约和回归测试；`REAL_DEVICE_EVIDENCE` 只说明实际设备或真实
协议拓扑证据；`MANUAL_ACCEPTANCE` 只说明有人机/现场步骤的证据。三者不能互相替代。

`CURRENT_STATUS` 只使用以下值：`PASS`、`PASS_WITH_LIMITATION`、`PENDING_NO_ENV`、
`PENDING_REAL_DEVICE`、`NOT_COMPLETED`、`OUT_OF_SCOPE`、`HISTORICAL_ONLY`、
`UNKNOWN_REQUIRES_REVIEW`。

`PASS_WITH_LIMITATION` 表示已在明确设备、版本、站点或场景范围内通过，不能外推为全系列、
全生命周期或所有现场路径通过。`PENDING_NO_ENV` 表示产品代码已有边界，但当前没有所需
Jump Host/Relay 等环境；`PENDING_REAL_DEVICE` 表示仍需目标真实设备或现场流程证据。

## 当前矩阵

| CAPABILITY | AUTOMATED_TEST | REAL_DEVICE_EVIDENCE | MANUAL_ACCEPTANCE | LATEST_EVIDENCE_DATE | LATEST_EVIDENCE_SOURCE | CURRENT_STATUS | ACTION_REQUIRED |
| --- | --- | --- | --- | --- | --- | --- | --- |
| H3C_SWITCH | H3C device detail、采集、Parser、Trackside 定向回归通过 | HZ10 Stage 3 只读交换机分支通过；H3C V9 Device Detail 12 条命令通过；5 个 DOWN 端口为预期现场状态 | `HZ10_FIELD_VALIDATION=PASS` | 2026-09-20 | `NetConsole-DevStatus/acceptance/HZ10_FINAL_ACCEPTANCE_20260920.md`、[H3C V9 能力验收](./H3C_COMWARE_V9_CAPABILITY_ACCEPTANCE.md) | `PASS_WITH_LIMITATION` | 保留严格站点边界和预期 DOWN 口；其他型号/Release 需独立证据 |
| H3C_AC | AC/FIT-AP API、Job、Parser 回归通过 | HZ10 AC 只读采集、FIT-AP 资源、LLDP、BSSID、连接记录及只读 API 通过 | HZ10 范围 `MANUAL_ACCEPTANCE=PASS` | 2026-09-20 | `NetConsole-DevStatus/acceptance/HZ10_FINAL_ACCEPTANCE_20260920.md`、[H3C V9 能力验收](./H3C_COMWARE_V9_CAPABILITY_ACCEPTANCE.md) | `PASS_WITH_LIMITATION` | AC 写动作、导出、外部终端等独立能力不能由只读采集结论替代 |
| H3C_AC_TELNET_HOSTKEY | FIT-AP Telnet HostKey 回归通过 | `FIT_AP_TELNET_HOSTKEY=0`；正式 FIT-AP 链路使用 Telnet/23，HZ10 已现场验证 | `PASS` | 2026-09-20 | `NetConsole-DevStatus/acceptance/HZ10_FINAL_ACCEPTANCE_20260920.md` | `PASS` | 继续与 SSH HostKey 轮换分开记录；Telnet 不套用 SSH known_hosts 结论 |
| FIT_AP | FIT-AP 资源、详情、批量读取和 AC Job 回归通过 | HZ10 正式 Stage 4：874 total / 627 success / 0 failed / 247 structured skips | `HZ10_FIELD_VALIDATION=PASS`；跳过为 `connection_incomplete`，不计失败 | 2026-09-20 | `NetConsole-DevStatus/acceptance/HZ10_FINAL_ACCEPTANCE_20260920.md` | `PASS_WITH_LIMITATION` | 保留结构化跳过统计；新站点或不同连接条件需重新验收 |
| MR_OFFLINE_MESH | MESH 导入、查询、解析、报告和下载回归通过 | 宁波 6 号线历史真实 MESH 只读查询完成，但 GUI heap/long-task/报告矩阵未闭环 | 旧现场记录仅完成服务端/查询范围 | 2026-08-26 | [历史 MESH 证据](../archive/evidence/2026-08/REAL_MESH_TEST.md) | `HISTORICAL_ONLY` | 若重新放行现场 GUI/报告，建立新的绑定验收记录 |
| MR_ONLINE | Online MR 生命周期、Traffic、Session 和解析自动化通过 | 当前没有新的真实 MR 采集闭环证据 | 未完成目标 MR 现场生命周期验收 | 2026-09-16 | [MESH/下载收口记录](./MESH_DOWNLOAD_IMPORT_DECOUPLE_FINAL_ACCEPTANCE_20260916.md) | `PENDING_REAL_DEVICE` | 在受控 MR 环境验证正常停止、自动到期、强停、最终化和报告 |
| MR_FILE_TRANSFER | 下载队列、重试、原子落盘和 MESH 解耦回归通过 | 真实协议拓扑 SFTP 通过；真实 MR 现场网络未到达 Jump Host SSH/SFTP | 未完成真实 MR 文件链路验收 | 2026-07-28 | [设备文件历史验收](../device-files/ACCEPTANCE-2026-07-28.md) | `PENDING_REAL_DEVICE` | 目标 MR 的 Jump Host → SSH → SFTP → 文件落盘需现场验证 |
| MR_SSH_SFTP | SSH/SFTP 连接、重连、失败分类和 SCP fallback 回归通过 | 真实 Paramiko 拓扑通过；目标 MR 现场不可达，未收到现场 HostKey | 未完成 | 2026-07-28 | [设备文件历史验收](../device-files/ACCEPTANCE-2026-07-28.md) | `PENDING_REAL_DEVICE` | 现场确认真实 MR 的 SSH/SFTP 和重连行为 |
| MR_UNATTENDED | Ground/Online MR 无人值守任务合同回归通过 | 无真实长时无人值守 MR 证据 | 未完成 | 2026-09-16 | [MESH/下载收口记录](./MESH_DOWNLOAD_IMPORT_DECOUPLE_FINAL_ACCEPTANCE_20260916.md) | `PENDING_REAL_DEVICE` | 单独执行长时窗口、取消、恢复和托盘隐藏验收 |
| ZTE_SWITCH | ZTE Profile、Parser、Trackside 固定命令回归通过 | C89E-4 V1.9.0 的 SSH、版本、端口/PVID、光模块摘要、LLDP Brief/Entry 已实机验证；不外推 5960X 或全 ZXR10 | 当前现场证据为受限设备范围 | 2026-07-28 | [ZTE 交换机 Adapter](../rail-transit/trackside-ap/ZTE_SWITCH_ADAPTER.md)、[设备兼容性](../device-management/DEVICE_COMPATIBILITY.md) | `PASS_WITH_LIMITATION` | 继续按 C89E-4 Release 限定；光模块 detail、写操作、ZTE AC 保持未完成/不支持边界 |
| ZTE_TELNET | 无对应正式现场验收闭环 | 未发现目标 ZTE Telnet 现场证据 | 未完成 | 2026-07-28 | [ZTE 交换机 Adapter](../rail-transit/trackside-ap/ZTE_SWITCH_ADAPTER.md) | `PENDING_REAL_DEVICE` | 需要明确产品范围和现场协议证据；不得由 SSH 证据推断 |
| ZTE_HOSTKEY | Managed SSH HostKey 自动化回归通过 | C89E 固定只读命令有 SSH 实机证据，但未完成 HostKey 轮换专项 | 未完成 | 2026-07-28 | [ZTE 交换机 Adapter](../rail-transit/trackside-ap/ZTE_SWITCH_ADAPTER.md) | `PENDING_REAL_DEVICE` | 现场验证 unknown/match/mismatch/rotation；不扩展到 Telnet |
| DIRECT_SFTP | SFTP list/download、大小/SHA-256、重试和原子替换回归通过 | H3C SFTP 受控闭环已有限定设备证据；MR 现场路径仍未到达 | H3C 受限范围通过 | 2026-09-13 | [H3C V9 能力验收](./H3C_COMWARE_V9_CAPABILITY_ACCEPTANCE.md)、[CHANGELOG](../CHANGELOG.md) | `PASS_WITH_LIMITATION` | 维持设备/角色/版本边界；MR 现场另行验收 |
| H3C_SFTP_AUTO_ENABLE | Profile gate、controlled-write、reconnect 回归通过 | H3C WX3540X / Comware V9 自动启用真实验证通过 | H3C 受限范围通过 | 2026-09-13 | [CHANGELOG](../CHANGELOG.md)、[SFTP 连接](../device-files/SFTP_CONNECTION.md) | `PASS_WITH_LIMITATION` | 不外推到 Huawei/ZTE/未知设备；MR 仍需现场闭环 |
| SFTP_RECONNECT | 旧 SSH 关闭、重建 SFTP、继续原始意图回归通过 | H3C V9 受限设备验证通过；MR 现场未验证 | H3C 受限范围通过 | 2026-09-13 | [CHANGELOG](../CHANGELOG.md)、[SFTP 连接](../device-files/SFTP_CONNECTION.md) | `PASS_WITH_LIMITATION` | 保持失败关闭和版本化 Profile |
| SCP_FALLBACK | SCP fallback、route selection 和失败分类回归通过 | 真实协议拓扑覆盖；Site Relay 目标环境不存在 | 未完成 Site Relay 现场验收 | 2026-09-16 | [MESH/下载收口记录](./MESH_DOWNLOAD_IMPORT_DECOUPLE_FINAL_ACCEPTANCE_20260916.md) | `PASS_WITH_LIMITATION` | 现场 Relay 验收独立处理 |
| ATOMIC_DOWNLOAD | `.part`、大小校验、SHA-256 校验和 atomic replace 回归通过 | 真实协议拓扑下载文件大小和 SHA-256 一致 | 未要求单独 GUI 验收 | 2026-09-16 | [下载流程](../device-files/DOWNLOAD_WORKFLOW.md)、[设备文件历史验收](../device-files/ACCEPTANCE-2026-07-28.md) | `PASS_WITH_LIMITATION` | 不把本地拓扑证据外推为 MR/Site Relay 现场 PASS |
| HASH_VERIFY | 下载 SHA-256/完整性契约回归通过 | 真实协议拓扑已核对 | 未要求单独 GUI 验收 | 2026-09-16 | [下载流程](../device-files/DOWNLOAD_WORKFLOW.md) | `PASS` | 继续保持失败关闭和临时文件清理 |
| SITE_RELAY_FILETRANSFER | Site Relay route、SFTP/SCP fallback 自动化回归通过 | 没有可用真实 Jump Host 环境 | 未执行 | 2026-09-20 | [CHANGELOG](../CHANGELOG.md)、[SFTP 连接](../device-files/SFTP_CONNECTION.md) | `PENDING_NO_ENV` | 获得 Jump Host/目标设备环境后单独完成现场验收 |
| SSH_HOSTKEY | managed known_hosts unknown/match/mismatch/atomic replace 自动化与本地拓扑回归通过 | H3C/ZTE 有普通 SSH 证据，但没有完整轮换现场证据 | 现场轮换未完成 | 2026-07-28 | [Host Key Trust](../device-files/HOST_KEY_TRUST.md)、[设备文件历史验收](../device-files/ACCEPTANCE-2026-07-28.md) | `PASS_WITH_LIMITATION` | 现场验证 Jump/Target rotation；SSH 策略保持 fail-closed |
| TELNET | FIT-AP Telnet/23、AP console sequence 和相关回归通过 | HZ10 FIT-AP Telnet HostKey=0；其他 Telnet 外部终端未全部验证 | HZ10 范围通过 | 2026-09-20 | `NetConsole-DevStatus/acceptance/HZ10_FINAL_ACCEPTANCE_20260920.md` | `PASS_WITH_LIMITATION` | `TELNET_HOSTKEY_NOT_APPLICABLE=YES`；不把 Telnet 结论当 SSH HostKey 轮换 |
| SITE_RELAY | Relay lifecycle、route identity、恢复和失败关闭自动化通过 | 无真实 Jump Host/Relay 环境 | 未执行 | 2026-09-20 | [CHANGELOG](../CHANGELOG.md) | `PENDING_NO_ENV` | 仅在具备真实 Jump Host 时复验；当前不是产品 FAIL |
| WINSCP | WinSCP 白名单/参数安全自动化通过 | 未实现 Site Relay 复用 | 未完成 | 2026-09-20 | [SFTP 连接](../device-files/SFTP_CONNECTION.md) | `NOT_COMPLETED` | 保留为独立产品后续项，不在本轮扩展实现 |
| GUI | Renderer/Electron 自动化、H3C V9 GUI 查看/刷新/重启现场证据通过 | HZ10/H3C V9 GUI 范围通过 | `MANUAL_GUI_ACCEPTANCE=PASS` | 2026-09-20 | [CHANGELOG](../CHANGELOG.md)、[H3C V9 能力验收](./H3C_COMWARE_V9_CAPABILITY_ACCEPTANCE.md) | `PASS_WITH_LIMITATION` | `FULL_VISUAL_MATRIX=PENDING`（真实页面截图、尺寸、缩放、主题、中英文仍独立） |
| INSTALLER | Backend/Renderer/Electron/NSIS/package smoke 自动化通过 | Full/Customer 安装启动运行人工验收已记录；完整修复/升级/卸载矩阵未闭环 | `MANUAL_GUI_ACCEPTANCE=PASS`；生命周期仍未全覆盖 | 2026-09-14 | [v1.5.8 最终验收](../release/V1.5.8_FINAL_ACCEPTANCE_20260914.md)、[CHANGELOG](../CHANGELOG.md) | `PASS_WITH_LIMITATION` | 分别完成 clean install、launch、repair、upgrade、uninstall；不要用 GUI PASS 代替全生命周期 PASS |

## 当前结论

- `HZ10_PRODUCTION_ACCEPTED=YES`，`HZ10_FIELD_VALIDATION=PASS`。
- `MANUAL_GUI_ACCEPTANCE=PASS`，但 `FULL_VISUAL_MATRIX=PENDING`。
- `P3_SITE_RELAY=PENDING_NO_ENV`；`WINSCP_SITE_RELAY=NOT_COMPLETED`。
- 本矩阵不修改 provenance schema、数据库值或历史数据；不改变 Trackside AP、HZ10、Recovery、并发逻辑。
- 发现的文档冲突属于状态整理，不构成新的产品缺陷；本轮 `FOLLOW_UP_REQUIRED=NONE`。
