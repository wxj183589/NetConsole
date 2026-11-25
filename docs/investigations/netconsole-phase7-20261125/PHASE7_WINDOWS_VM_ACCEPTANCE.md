# Phase 7.1 Windows VM 安装验收

记录日期：2026-11-26。产品分支为 `codex-A/organization-task-network-services-phase6`，当前报告 HEAD 起点为 `266acbcd5b4561130b26277719ca7780089d7bef`。本报告只记录本阶段新增检查，Phase 7 的源码测试、Full Gate 和 package smoke 结果保留在各自原始报告中。

## 结果摘要

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| 正式包文件及 SHA-256 | PASS | 文件存在，159,505,594 bytes，复算 SHA-256 与 release manifest 相同 |
| 安装器容器和版本资源 | PASS | 7-Zip 识别为 `NSIS-3 Unicode`；PE FileVersion / ProductVersion 均为 1.5.19 |
| Installer / Backend / Frontend 身份 | PASS（包内元数据） | release manifest 记录三者均为 `a66455b251bf220ca418da01547102c684030246`，`packaged_dirty=false`；manifest 的 build ID 与版本策略字段完整 |
| Authenticode 签名 | UNSIGNED | 当前与上一正式包均为 `NotSigned`，不存在签名者或时间戳证书 |
| SBOM / NOTICE / 离线工具 | PASS（静态包内核验） | 嵌套应用归档可读取，SBOM 为 CycloneDX 1.5、68 components，声明文件及固定版本工具存在，fping / iperf3 哈希匹配白名单 |
| Windows 全新安装、安装态业务与冻结 Worker | NOT VERIFIED | VM Guest 未登录，无法执行 GUI 操作或启动安装器 |
| 升级、卸载与数据保留 | NOT VERIFIED | 未在 Guest 内运行任何安装或卸载操作 |
| Full Gate | PASS（沿用既有证据） | 见 `PHASE7_FULL_GATE_REPORT.md` 的 2026-11-25 最终 Gate，不在本阶段重跑 |

## 安装包静态复核

正式候选包：

```text
D:\study\NetConsole-Workspace\worktrees\organization-task-network-services-phase6\dist\electron\NetConsole-Full-1.5.19.0-a66455b2-x64-setup.exe
SHA-256: 048067404813DA700B035558101A361FD96C9B34F5FAB72CDC8D8B21FAC16495
Length: 159505594 bytes
```

SHA-256 与包旁 `.exe.release.json` 中的 `artifact_sha256`、文件长度、版本、build ID 和策略源码 SHA-256 一致。安装器内部 `netconsole-installer-build.json` 和包内 `desktop-renderer-build-meta.json` 的 Installer、Backend、Frontend commit 均为 `a66455b251bf220ca418da01547102c684030246`，dirty 状态均为 false。7-Zip 直接识别 NSIS 容器并成功列出内容。Windows Authenticode 检查返回 `NotSigned`。上一正式包 v1.5.18 存在，SHA-256 为 `A40B08FB7C7C0C7D753B19B58D1550842A2623EC680F48148A3499B962DFC01D`，同样未签名。

从安装器嵌套应用归档只读提取的 SBOM 为 CycloneDX 1.5，包含 68 个组件，并包含 Electron、Chromium、Node.js 和 Python 条目。`THIRD_PARTY_COMPONENTS.md` 和 `build_info.json` 存在，后者声明 `edition=full`、`feature_profile=full`、`admin_unlock_enabled=false`。Python 运行时 `python313.dll`、`fping.exe` 和 `iperf3.exe` 存在于应用归档。两个工具的 SHA-256 与仓库固定值一致，分别为 `9c9ab2f26d3d32818b53ed7b664ec53546fc5cd59f4d953e06f9d3e28673f9d9` 和 `4aae5eee2b90c716d93bdc54c530a854596c92ff996859973b9f44e73799294e`。这只证明归档内容可读和元数据匹配，不证明它们已在 Windows 安装态成功运行。

独立调用 `scripts.build.build_installer --verify` 时，当前工作树 HEAD 是后续报告提交 `266acbcd…`，而制品刻录的源码提交是 `a66455b2…`，脚本按发布构建规则拒绝将当前 HEAD 视为该包的源码复验对象。构建期已有 verifier、package smoke 和 Full Gate 结果保留为 Phase 7 证据。本次通过 release manifest、安装器内构建清单、包内 Renderer 构建元数据、PE 版本资源、NSIS 内容、嵌套归档和其内文件进行制品基线核对，没有改写或替换正式包。

## 虚拟化环境与 Guest 状态

- 已有 VMware Workstation 17.0.2 和 VirtualBox 6.0.14。Hyper-V PowerShell 状态查询因当前会话无提升权限未完成，主机 `HyperVisorPresent=False`。未开启 Windows 功能、安装虚拟化软件或更改主机网络和防火墙。
- 常用既有目录内没有找到可用 Windows ISO。没有下载 ISO。
- 找到一台现有 Windows 10 Pro x64 VM，VMware Guest 信息为 `10.0.18363.418`，即 Windows 10 1909。它低于任务提出的 Windows 10 20H2 验收目标，不能据此宣称 20H2 通过。
- 已将该 VM 完整克隆至 `D:\study\NetConsole-Workspace\temp\installer-test\phase7.1-windows10-1909`。克隆 VM 配置为 2 vCPU、8 GiB RAM，虚拟网卡 `ethernet0.present=false`、`startConnected=false`。原始 VM 的 VMX / VMSD SHA-256 已记录于 `reports\build\phase7.1-windows-vm-20261125\source-vm-metadata-hashes.json`。本阶段没有修改原 VM 文件。
- VMware `captureScreen` 和 Guest Operations 返回“此虚拟机不允许执行匿名客户机操作，必须先登录 Guest”。当前没有可用的 Guest 登录凭据。没有猜测凭据或尝试绕过登录。克隆未执行安装、升级、卸载，也没有修改 Guest 用户数据。
- 主机 D 盘检查时剩余 389.8 GiB。该容量足以继续使用已有隔离 VM，但没有可登录的 Guest。

虚拟机克隆目录保存原始状态和锁文件，VM 配置日志位于 `reports\build\phase7.1-windows-vm-20261125\vm-clone.log`。Guest 截图、安装日志、升级日志和卸载日志均未生成，因为没有进入 Guest 桌面。VM 配置的网络保持断开。

## 按验收矩阵的结论

Windows 10 20H2、Windows 11 和 Windows Server 2016 是后续版本按正式支持矩阵需覆盖的环境。当前唯一可用 Guest 是 Windows 10 1909 且无法登录，因此以下均为 `NOT VERIFIED`：GUI 安装、安装目录、Backend / Renderer 启动、Python frozen runtime、Worker 路径和子进程退出、中文与空格路径、数据库初始化、HTTP / FTP / TFTP / Syslog / iPerf3 服务、文件管理和只读设备任务、端口释放、升级数据迁移、卸载数据保留和重装恢复。

没有对设备执行配置写入，没有执行真实安装器，也没有改动 Production 或 Dev Real Data。

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DEVICE_CONFIGURATION_WRITES=0
INSTALLER_EXECUTED_IN_GUEST=0
GUEST_DATA_MODIFIED=0
GLOBAL_SERVICES_MODIFIED=0
HOST_NETWORK_MODIFIED=0
FIREWALL_MODIFIED=0
```

## 问题清单

1. 缺少可登录克隆 Guest 的凭据，Guest Operations 拒绝匿名访问，安装态验收无法继续。
2. 可用 Guest 为 Windows 10 1909，不满足本次优先要求的 Windows 10 20H2 目标。
3. 当前正式包与上一正式包均没有 Authenticode 签名。本阶段只确认签名状态，没有签名证书或签名发布流程的本机证据。
4. v1.5.18 安装包可用，但没有在 Guest 内执行升级，因此升级和数据保留为 `UPGRADE_NOT_VERIFIED`。

最终阶段状态为 `PARTIAL`。自动化和静态制品核验不能替代真实 Windows GUI 安装验收。
