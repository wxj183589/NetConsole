# Phase 7 网络服务实测与组件评估

2026-11-25，工作树 `organization-task-network-services-phase6`。当前服务定向验证为 PASS，完整交付为 PARTIAL。正式安装包、虚拟机和真实设备验收由集成任务继续执行。

## 当前实现矩阵

| 能力 | 源码实现 | 本轮证据 | 状态 |
| --- | --- | --- | --- |
| 进程隔离 | HTTP、HTTPS、FTP/FTPS、TFTP、Syslog 各由 `worker.py` 独立进程运行，iPerf 独立工具进程 | 现有进程隔离、异常退出、重启和关闭回收测试 | PASS |
| 监督与恢复 | Manager 保存 Popen / Windows Job Object，后台监督退出，自动恢复默认关闭，最多每五分钟三次 | 现有 `test_supervisor_bounds_automatic_recovery` | PASS |
| 退出控制 | stdin 控制管道发送 stop，父管道 EOF 触发停止，必要时按持有的进程对象 terminate/kill | 新 BrokenPipe、强制等待超时和 Job 清理回归 | PASS |
| 日志线程 | Manager 持有 stdout/stderr 读取线程，进程结束后有界 join，再关闭日志 Handler | 新真实 HTTP Worker 关闭及读取线程回收回归 | PASS |
| HTTP / HTTPS | 文件 GET/HEAD、独立根、绑定限制，HTTPS TLS 1.2+ | 真实 Windows 回环下载、证书生成/轮换、慢 TLS 客户端和另一连接并行 | PASS |
| TFTP | octet 上传/下载、禁止覆盖、最小隔离根，上传最大 8 MiB | 现有真实 UDP 上传、下载和覆盖拒绝测试 | PASS |
| FTP / FTPS | 会话随机凭据、受限用户、上传开关、文件独占创建、拒绝 PORT/EPRT，FTPS 控制和数据 TLS 必须启用 | FTP/FTPS 真实回环传输、用户名、凭据轮换、上传和覆盖保护 | PASS |
| FTP 被动端口 | 可选固定端口区间，耗尽返回 425，控制会话继续可用 | 新单端口占用、NOOP、释放后 PASV 使用原端口测试 | PASS |
| Syslog | UDP 配置端口、TCP 相邻端口，RFC3164/RFC5424 基础解析，4096 项有界写入队列 | UDP/TCP、结构化字段与脱敏、并发队列和 HTTP 隔离回归 | PASS |
| iPerf3 | 项目已有工具，独立进程及 Job Object | 本机真实 TCP、UDP JSON 吞吐/抖动/丢包、退出与重启 | PASS |
| SSH / SFTP Server | 检测 Windows OpenSSH 客户端与服务端文件、服务状态、PID、版本和监听 | 当前仍缺受管 Server 生命周期与 SFTP 根权限适配 | PARTIAL |
| Telnet / NFS / VNC | 注册表显示未接入和依赖状态 | 本轮完成源码与许可证来源评估 | PARTIAL |
| DHCP / DNS / NTP | 稳定 ID，deferred，禁止启动 | 现有 deferred API 回归 | PASS |

实现位于 `src/netconsole/services/local_network_services/manager.py`、`worker.py`、`protocols.py` 和 `ftp.py`。服务日志中心接入与来源边界见 [日志报告](./PHASE7_LOG_CENTER.md)。

## 本轮修复

1. 已复现 stdin 写入报 BrokenPipe 后，`BufferedWriter.close()` 再次抛异常并跳过 wait / Job 回收的问题。修复前两个专用回归均 FAIL，修复后通过。已退出进程的控制管道也使用相同保护。
2. Job Object 关闭进入 finally，即使强制 kill 后的等待仍超时，持有的进程树保护也会执行关闭。异常保留原进程对象供后续诊断。
3. 为服务 stdout/stderr 与 iPerf 输出保存线程句柄并执行有界收尾。Worker 无法写诊断响应时捕获管道异常，继续退出清理。
4. pyftpdlib 对被动端口冲突存在内核随机端口回退。Windows 独占占用还可能进入 PermissionError 分支，随后未绑定 socket 的 listen 可隐式分配端口。Adapter 同时校验 bind 与 listen，拒绝范围外端口，并返回 425。
5. Syslog 停止时先关闭两个接收入口和 TCP 请求线程，再通知写入队列排空。原先只观察共享 stopping 标记的写入线程可能在接收线程停止前提前退出。

6. 子进程输出原先统一以 INFO 写入 Manager，WARNING 配置会丢失子进程警告。现在保留受识别的日志等级，真实 TCP 超长 Syslog 在 WARNING 配置下仍可查询。

7. Windows venv 的 Popen PID 可能指向 launcher。Worker readiness 现在返回真实 PID，Manager 以 QUERY_LIMITED_INFORMATION / VM_READ 打开查询句柄，验证属于所持 Job Object 后保存句柄并采集真实 Worker CPU / 内存，停止时关闭。UI PID 同步使用真实 Worker。真实内存与拒绝非所属进程两个回归通过，进程控制继续使用 Popen / Job Object。

## 并发与资源边界

隔离队列测试在启动消费者前，由八个生产线程各提交 1000 条消息。8000 条记录中，4096 条排队、3904 条按上限丢弃，入队阶段未调用日志 IO。停止后写入 4096 条并记录 received/dropped 汇总，全部服务线程退出。

真实 socket 测试同时启动独立 Syslog 与 HTTP Worker。四个 UDP 发送者各发送 1500 条消息，期间完成十次 HTTP 文件下载，逐请求超时为两秒，总测试阶段上限为十秒。两项服务保持 running。该测试证明此负载下的隔离可用性，UDP 操作系统接收缓冲丢包没有逐包确认，received/dropped 只统计到达应用入口后的队列行为。

接收队列、连接槽、socket timeout、三份轮转文件与日志查询行数均有上限。Syslog parser 当前将输入限制为 2048 字节、展示 message 为 1500 字符，保留的 raw 也经过脱敏。TCP 当前采用换行分帧，RFC6587 octet-counted framing、完整 RFC5424 Structured Data、多网卡与长期峰值验收仍需补齐。轮转大小为每文件 256000 bytes，backupCount 为 2，当前轮转按大小执行，独立保留天数配置待完善。

## Windows 扩展组件评估

以下来源均于本轮通过 HTTPS 实际读取。候选二进制的安装、打包和运行兼容性为 NOT VERIFIED。

### Telnet

KpyM Telnet/SSH Server 的公开源码镜像 `jdstroy/kts` 提供 Windows Telnet/SSH Server，主 License.txt 为保留版权、二进制声明和禁止背书的三条 BSD 风格许可。GitHub 当前元数据的最后 push 时间为 2014-05-31。具体阻断包括当前 Windows 11 / Server 2025 构建运行证明、依赖清单、受管身份与退出、绑定限制、凭据处理和明文会话的现场使用范围。当前材料不足以证明其适合本阶段直接交付。[源码](https://github.com/jdstroy/kts) [许可](https://raw.githubusercontent.com/jdstroy/kts/master/License.txt) [仓库元数据](https://api.github.com/repos/jdstroy/kts)

### NFS

WinNFSd README 明确提供 Windows NFS v3，并支持 `-addr`、export path / alias 和 UID/GID。README 声明 GPL，但仓库根的 `LICENSE` 路径返回 404，本轮未确定完整分发的精确 SPDX 与依赖许可。源码 `winnfsd.cpp` 定义 RPC portmap 111、mount 1058、NFS 2049。接入前需补齐三端口绑定及冲突、客户端权限与身份映射、受管根目录只读/写权限、路径穿越、关闭和挂载验收。现有单端口 Provider 不能直接代表完整 NFS 能力。[README 与许可声明](https://github.com/winnfsd/winnfsd/blob/master/README.md) [实际端口源码](https://raw.githubusercontent.com/winnfsd/winnfsd/d833130fab6ed1fcf7fe89ecc628ad1fdf464c86/src/winnfsd.cpp)

Microsoft Server for NFS 是 Windows Server 角色，官方支持矩阵覆盖 Server 2025 / 2022 及 NFS v2/v3/v4.1，并介绍身份映射和认证。Windows 11 主开发机的客户端能力无法证明该 Server 角色可用。具体接入依赖目标主机版本、角色安装与授权、现有服务所有权、exports 与身份策略、幂等配置及回滚。当前任务没有安装或变更该系统角色。[官方 NFS 概览](https://learn.microsoft.com/en-us/windows-server/storage/nfs/nfs-overview)

### VNC

UltraVNC 当前官方 README 明确支持 Windows 11、Server 2022 / 2025，并区分 Server 和 Viewer。README 标注 `GPL-3.0-or-later`，根 LICENSE 为 GPL v3。其 Windows Server 能力具备评估依据，当前具体阻断为受管版本与哈希、服务/交互桌面会话、UAC 与 Session 0 行为、密码与加密配置、监听范围、服务所有权、关闭和恢复、分发 notices 与对应源码材料。当前未接入 Provider。[官方源码和支持矩阵](https://github.com/ultravnc/UltraVNC/blob/main/README.md) [许可](https://github.com/ultravnc/UltraVNC/blob/main/LICENSE)

TigerVNC 的根许可为 GPL v2 文本，其 README 明确说明 Windows `winvnc` Server 当前无人维护，并指出 Fast User Switching / Remote Desktop 兼容问题。该明确限制构成本阶段 Windows Server 候选交付阻断，Viewer 可用性不足以消除服务端缺口。[官方 Windows 限制](https://github.com/TigerVNC/tigervnc/blob/master/README.rst) [许可](https://github.com/TigerVNC/tigervnc/blob/master/LICENCE.TXT)

## 实测命令与结果

测试使用主仓库 `.venv/Scripts/python.exe`，cwd 为当前工作树。项目 pytest fixture 将所有可写内容放入 Workspace 的隔离测试根。

```powershell
python -m pytest tests/test_network_service_resilience.py tests/test_local_network_services.py tests/test_service_log_query.py -q
python -m ruff check src/netconsole/services/local_network_services tests/test_network_service_resilience.py
```

第一次命令 PASS，27 tests，28.75 秒。FTPS 与 iPerf 用例均执行，没有 skip。第二次命令 PASS。FTP 被动端口、队列、并发 Syslog 和输出线程四项集成回归另重复两轮，均为 4 passed，耗时 4.07 秒和 3.64 秒。现有 Starlette/httpx 弃用提示保留。相关文档链接和 `git diff --check` 在本分工收尾时复核。

## 待集成验收

- Windows 安装态 frozen Worker 路由、离线依赖和完整卸载/升级行为。
- 虚拟机 Host-only 访问、真实设备上传下载、长时间多客户端和磁盘满场景。
- Syslog 完整 framing / Structured Data、按时间历史保留、跨设备任务关联。
- Telnet / NFS / VNC 具体版本锁定与真实客户端验收。

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DATABASES_REMOVED=0
DEVICE_CONFIGURATION_WRITES=0
```

## 持续运行验收

Workspace reports 隔离目录内的最终 600 秒 soak 记录在 `D:/study/NetConsole-Workspace/reports/tests/phase7-network-services-soak-history-query-20261125/result.json`，PASS，120 周期。HTTP 和 FTP 各完成 120 次下载，Syslog 完成 1,200 条 UDP 与 120 条 TCP 消息。HTTP Worker 异常退出后自动恢复，FTP Worker 在凭据轮换时重启，Syslog Worker 重启后成功重新绑定 UDP/TCP 端口对。HTTP 最大延迟 20.8 ms，FTP 39.3 ms。实际 Worker Working Set 分别稳定在 HTTP 56,807,424–57,143,296 bytes（144 handles）、FTP 56,963,072–57,389,056 bytes（143 handles）、Syslog 57,008,128–57,298,944 bytes（152 handles）。Manager handles 195–198，线程数稳定为 8。测试后 6 个受管进程、12 个输出读取线程及 supervisor 均退出，监听端口全部可重新绑定，Windows 观测到的 13 个进程均消失。

第二轮 `phase7-network-services-soak-fixed-metrics-20261125` 的 TCP marker 已轮转到 `service.log.1`，测试 harness 只查当前日志而误报 FAIL。第三轮使用有界历史日志查询后 PASS。持续运行验收使用源码 Worker，正式安装态协议验证由同一提交的 Full package smoke 覆盖冻结 Worker 中文协议，外部 GUI 安装环境仍为 NOT VERIFIED。
