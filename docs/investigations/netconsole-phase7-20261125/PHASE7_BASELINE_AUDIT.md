# Phase 7 基线审计

审计日期：2026-11-25（Asia/Shanghai）

## Git 与工作区

- 产品分支：`codex-A/organization-task-network-services-phase6`
- 产品 HEAD：`7b8e82f1bf86308c3fe5d83b20d2946dc36ac1bd`
- 产品远端：`github/codex-A/organization-task-network-services-phase6` 与本地 SHA 一致。
- 产品 worktree：干净。DevStatus 当前分支为 `codex-A/organization-task-network-services-phase6-status`，HEAD `39edbe750b7fa08567ebd9f41174ed5e94ae610a`，远端 SHA 一致。
- 两个 repo 各自的 `main` checkout 保持既有提交，未切换、合并或修改。
- Workspace Layout 检查：`PASS`。Phase 6 留下的 runtime/test 目录及个人 Temp 目录此前删除操作被本机自动审批策略拒绝，本阶段按任务书要求保留，不扩大清理范围。

## 基线能力矩阵

| 模块 | 基线实现 | 基线证据 | 缺口 |
| --- | --- | --- | --- |
| 网络服务 Supervisor | Backend 内线程/进程生命周期、独立配置、监听状态和轮转文本日志 | `manager.py`、`tests/test_local_network_services.py` | 没有独立 supervisor worker、PID/运行时间/CPU/内存 DTO、健康探针策略或有界自动恢复策略；Python 内置服务异常不能自动重启 |
| TFTP | 内置 UDP，octet 上传/下载、覆盖保护、8 MiB 上传限制、路径检查、连接数信号量 | 回环测试完成实际上传、下载和越界拒绝 | 未验证大量并发和长时运行 |
| FTP | pyftpdlib 独立 FTP 服务，随机会话口令、被动传输、匿名关闭、默认只读目录权限 | 回环 FTP 登录、下载、禁主动模式、禁上传、重启换口令测试通过 | 未接入 FTPS、用户/权限策略与被动端口范围可配置；无真实设备传输验收 |
| HTTP | 内置受管目录 GET/HEAD，路径穿越拒绝 | 回环 HTTP 下载和越界测试通过 | 无 HTTPS、证书生命周期和访问统计摘要 |
| HTTPS | 仅有 unavailable service 定义 | UI/API 显示依赖缺失 | 未接入 |
| SSH/SFTP Server | 检测 Windows `sshd.exe` 文件存在 | 代码检查 | 仅客户端能力和文件检测，不检查 sshd 服务状态、版本、端口或实际 SFTP 服务端状态；未管理系统服务 |
| SFTP Client | 复用现有 Paramiko 终端 SFTP、受管文件传输 | Phase 6 隔离 SFTP 与同步测试报告 | 不属于本地网络服务中的 SFTP Server；真实设备与 Electron GUI 未验收 |
| iPerf | 复用仓库固定 iPerf3 二进制独立 server 进程，Backend 持有 Windows Job Object；可启动/停止/检测意外退出 | 本机 TCP 吞吐客户端回环测试通过 | 未覆盖 UDP、丢包、抖动、JSON 客户端任务、历史任务关联、健康与资源快照 |
| Syslog | 内置 UDP/TCP 双 listener，RFC 3164/5424 部分解析，来源/facility/severity/hostname/message 写入轮转日志 | UDP/TCP 回环、端口冲突回滚和停止测试通过 | 没有持久化索引/历史查询、原始消息事实、空间/保留策略和高并发压测；不得替代 Ground Syslog authority |
| Telnet Server | 依赖缺失占位 | API unavailable 状态测试 | 未接入，HTTP/明文 Telnet Server 有显著凭据风险 |
| NFS Server | 依赖缺失占位 | API unavailable 状态测试 | 未接入；Windows Server for NFS 仅显示依赖文案，不代表能力可用 |
| VNC Server | 依赖缺失占位 | API unavailable 状态测试 | 未接入；不能将 VNC Viewer/Client 当 Server |
| DHCP/DNS/NTP | 当前 DNS A 与 NTP client responder 被标记为 built-in，DHCP 为 unavailable | DNS/NTP 回环测试通过 | Phase 7 明确暂缓 DNS/NTP，必须关闭产品入口/执行并保留扩展槽位；DHCP 不实施 |

## 领域关系与消费者审计

### 网络服务

写入方为 `LocalNetworkServicesView.vue` 经 `local_network_services_router.py` 调用 `LocalNetworkServiceManager.configure/action`。配置、文件根及日志写入应用 runtime root 下的 `local_network_services/<service>/`，文件共享由 `shared_path()` 限定；HTTP/FTP/TFTP 各有独立目录。运行态为进程内 manager state，重启后显式服务启动，不存在跨进程任务记录。

读取方为同一 Vue 页面轮询服务快照、读取文本日志；iPerf 测试结果没有写入设备任务台账。Syslog 本地服务只写其自有 rotating log，不写 Ground Raw、SQLite 或 Log Center 的其他事实源。

兼容和安全边界：服务 ID/API 对所有声明服务稳定返回可用或 dependency-missing 状态；服务配置额外字段拒绝；绑定地址只允许回环或检测到的活动 Host-only IPv4；服务各自启停；FTP 会话口令只从启动响应短暂返回。不得修改 Windows 系统服务、账户、防火墙、网卡或全局配置。

### 文件管理

文件管理经现有 `TerminalSftpManager`、`FileManagementApplicationService`、局点下载目录授权和 SFTP Relay 运行。Phase 6 已有双向补齐同步预览、过期 Revision 拒绝、同名冲突保护和受限文本编辑。新增本地文件服务整合必须复用现有受管文件授权及路径检查，不得直接公开任意磁盘路径，也不得更改 SFTP Host Key / Relay 身份来源。

### 设备任务与 Task/Job

设备任务通过设备操作 Router/Application Service 提交现有 Task Runtime/Worker。消费者包括 Devices、AC/FIT-AP、配置采集、File Management、MESH、Online MR、Ground、Trackside AP、Network Tools、Export。共享不变量为七状态、唯一终态、进度、协作取消、部分成功、Artifact 和 Worker 协议。现有自定义命令模板预览可识别配置变更，但执行 Service 只允许只读 H3C 命令；任务书要求保持该拒绝边界。

本阶段沿用 Task/Job 生命周期、终态、Worker protocol 和 AP Identity 契约，任务扩展复用既有执行与导出入口。已读取工作树现有 `netconsole-change-review-skill`，依据上述 Consumer Matrix 审计共享层和最终回归。打包依赖与新增隔离服务 Worker 入口使本任务最高风险为 L4，覆盖冻结入口、依赖闭包、Notice/SBOM、Electron 关闭与服务回收。并行任务分别负责文件、设备任务和日志模块，主 Agent 负责服务 Supervisor 与打包，同文件的必要接线按局部范围协调。

### 轨道交通基础设施与基础资料

基础设施与基础资料保持独立。基础设施负责工程组织关系；基础资料、AC/FIT-AP、Trackside AP、光衰、MESH、Ground、Online MR 和历史导入仍有既有消费者。物理设备 UUID 不随多项目关系复制。轨旁 AP 光衰来源、时间、AC/交换机 LLDP 身份、光模块 Rx/Tx、Current/history、缓存及导出均须维持既有实现。本审计不授权退役页面、API、Schema 或历史数据。

## 风险等级与回归

- 服务 Provider 与其单页的本轮生命周期/协议完善按 L2 领域变更处理；若触及 API client、Task/Job、SQLite、Electron lifecycle、Feature Registry 或构建发布，风险提升至 L3/L4 并先执行对应 Consumer Audit。
- 首轮定向回归：`tests/test_local_network_services.py`、本地网络服务 Renderer 定向测试、Ruff、TypeScript、Renderer build、Workspace Layout 和 diff check。
- 文件管理和任务中心仅在相应实现有修改时执行其消费者套件；不得用当前服务回环测试替代真实设备、GUI 或安装态验收。
- 发布门需覆盖 Python/Renderer/Electron、架构门、主线 contract smoke、package smoke 和离线制品合规。真实 GUI、虚拟设备、安装/卸载/升级、长时间运行分别记录，自动化通过不代替人工验收。

## 基线验证

- Phase 6 交接记录：Python 42 项、Renderer 24 项、AppRouteView/Dashboard 8 项定向测试通过；TypeScript、Ruff、Workspace Layout、Renderer production build 和 diff check 通过。
- 本次启动时重新检查 Git 和 Workspace Layout，Layout 为 `PASS`。
- 实际服务回环测试基线包括 TFTP、FTP、HTTP、DNS、NTP、Syslog UDP/TCP 与 iPerf TCP server/client；没有将回环测试标记为真实设备或安装态验收。

## 当前范围决定

1. 先补齐网络服务运行事实、TLS 能力和日志/健康管理，不新增 DHCP、DNS、NTP 功能入口。
2. 评估并行高负载 Syslog 的接收路径，不把本地 Network Service Syslog 与 Ground Syslog 持久事实混为一谈。
3. 继续维持设备配置写入为 0；网络服务控制操作不会改动 H3C 设备配置。
4. 真实虚拟设备只能执行只读联调。配置写入、系统服务/防火墙/网卡变更不在本阶段既有授权内。
