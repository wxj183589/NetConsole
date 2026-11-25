# Phase 7 交付验收

2026-11-25，继续既有产品分支 `codex-A/organization-task-network-services-phase6`。当前代码、源码实测、Full Gate 和正式离线 Full NSIS 自动验收完成。因真实 Windows 安装/升级/卸载与若干真实场景验收仍缺，整体 PARTIAL。

## 功能矩阵

| 模块 | 当前状态 | 证据与缺口 |
| --- | --- | --- |
| 网络服务管理 | PASS | 独立进程、真实 Worker PID、Job Object、资源、退出与有界恢复 |
| TFTP | PASS | 真实 UDP 上传下载与覆盖保护 |
| FTP / FTPS | PARTIAL | 真实 TLS/权限/被动端口实传通过，完整多用户管理待完善 |
| HTTP / HTTPS | PASS | 实际下载、证书与慢 TLS 隔离、大文件并发 |
| SSH / SFTP | PARTIAL | 真实交换机 SFTP 下载通过，系统 Server 缺受管生命周期 |
| Iperf | PARTIAL | iPerf3 TCP/UDP JSON 通过，iPerf2 与组织目标参数链待完善 |
| Syslog | PARTIAL | UDP/TCP、有界队列、结构化与轮转通过，完整 framing/保留天数待完善 |
| Telnet | PARTIAL | Windows 候选源码及许可已评估，未集成 Provider |
| NFS | PARTIAL | Windows 多端口、许可及身份映射待完成 |
| VNC | PARTIAL | Windows 候选已评估，受管桌面会话及分发未验收 |
| 文件管理联动 | PARTIAL | 实际 Electron 上传复制校验另存为、真实 SFTP 与大文件通过，上传接收阶段字节进度待完善 |
| 设备任务中心 | PARTIAL | 多设备、组织、并发、取消重试与导出通过，FIT-AP 独立任务与文件/iPerf父子任务映射待完善 |
| Jinja2 模板 | PASS | 参数、分支、循环、版本、预览、保存及执行只读边界 |
| 日志中心 | PARTIAL | 服务筛选/实时/轮转查询通过，统一导出归档及所有来源关联待完善 |
| 基础资料退役审计 | PASS | 消费者审计完成，实际退役条件尚未达到 |
| 轨旁 AP 光衰兼容性 | PARTIAL | 原链未重写，自动回归待最终 Full Gate，真实光衰现场更新待验收 |
| Electron 验收 | PARTIAL | 源码真实窗口四分辨率52张截图与文件交互通过，安装态待验收 |
| 离线安装包 | PARTIAL | 依赖/Notice/SBOM与61项构建合同通过，正式包待构建 |
| Full Gate | PASS | 最终 clean checkpoint `a66455b251bf220ca418da01547102c684030246`，5870 Python passed / 2 skipped，Renderer 224 files / 1610 tests，Electron 41 files / 326 tests，Architecture 12/12，package-smoke PASS |
| Git Push | PASS | 产品源码 checkpoint `a66455b2` 已推送，Phase 7 报告和 DevStatus 使用独立提交 |

## 证据索引

- [网络服务](./PHASE7_NETWORK_SERVICES.md)与[安全审计](./PHASE7_SECURITY_AUDIT.md)。
- [设备任务](./PHASE7_TASK_CENTER.md)与[真实设备实验](./PHASE7_DEVICE_TASK_LAB.md)。
- [文件传输](./PHASE7_FILE_TRANSFER.md)与[日志中心](./PHASE7_LOG_CENTER.md)。
- [基础资料退役审计](./BASE_DATA_RETIREMENT_AUDIT.md)。
- [Electron 验收](./PHASE7_ELECTRON_ACCEPTANCE.md)。
- [安装包](./PHASE7_INSTALLER_ACCEPTANCE.md)与[Full Gate](./PHASE7_FULL_GATE_REPORT.md)。
- [第三方声明](./THIRD_PARTY_NOTICES.md)、`sbom.cdx.json` 与 `dependency-provenance.json`。

## 最终分支与制品

- 产品分支 `codex-A/organization-task-network-services-phase6`，产品源码与验证基线 `a66455b251bf220ca418da01547102c684030246`，已推送至 `github` 且构建前工作区 clean。产品报告提交只增加验收证据。最终产品分支 HEAD 与 DevStatus HEAD 以本次独立提交后的 Git 状态为准。
- 最终 Full NSIS：`D:/study/NetConsole-Workspace/worktrees/organization-task-network-services-phase6/dist/electron/NetConsole-Full-1.5.19.0-a66455b2-x64-setup.exe`，159,505,594 bytes，SHA-256 `048067404813DA700B035558101A361FD96C9B34F5FAB72CDC8D8B21FAC16495`。
- Full Gate 日志：`D:/study/NetConsole-Workspace/reports/tests/phase7-full-gate-20261125/attempt5-full-gate.log`。截图位于 `D:/study/NetConsole-Workspace/reports/diagnostic/netconsole-phase7-20261125/screenshots`，13 种 UI 状态 × 4 种分辨率，共 52 张真实 Electron 窗口截图。

## 数据与执行记录

实验 AC、AC2、SW 仅执行查询或 SFTP 读取。两台 AC 无线任务成功，MESH 实测明确返回未配置 WMESH，结果记 skipped，真实非零链路仍待验收。FIT-AP TCP23 可达，本轮没有配置其远程控制台。

并行任务恢复上下文时误改主机 `D:/study/AGENTS.md`，已从原始内容精确恢复，SHA-256 为 `423af17ac5661fff097b17b2bbf855db61d54637edce80e1daa5ea202a403ce4`。没有主机治理 Git 写入。Phase 6 已被自动审批拒绝的目录清理保持原状态。

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DEVICE_CONFIGURATION_WRITES=0
DATABASES_REMOVED=0
GLOBAL_SERVICES_MODIFIED=0
FIREWALL_MODIFIED=0
MAINTENANCE_AUTHORIZED=NO
```
