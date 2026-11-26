# NetConsole Phase 8.1 总验收

状态：**PARTIAL**

最终 Full Gate 已在提交 `27f7d662a56a9e8439548ce520c0dba3dd76cfde` 通过。Python `5890 passed / 3 skipped / 35 warnings`，Renderer `224 files / 1619 tests`，Electron `41 files / 326 tests`，架构 `12/12`，文档门禁 `22 passed`，package smoke PASS。该结果覆盖自动化质量门禁，不改变真实设备、Windows 安装态、现场故障注入、外部终端自动认证和长时间性能项目的未验收状态。

[Phase 8 / 8.1 总任务台账](./PHASE8_MASTER_TRACKER.md)涵盖 P8-01 至 P8-23 的原始需求、实施、证据、测试入口及尚未完成的验收。下面保留真实数据专项审计结果，并记录实际产品回放进度。

## 真实产品回放

| 数据 | 隔离 Backend 健康 | Electron 交互就绪 | 局点 |
| --- | --- | --- | --- |
| HZL9 | 5.54 秒 | 6.29 秒 | `hzdt-09` |
| HZL10 | 17.49 秒 | 23.30 秒 | `hzl10` |

两次使用 `NETCONSOLE_COLLECTION_MODE=disabled`，各为单次启动读数。复制范围为启动配置、设备及任务数据库、Ground 历史和 Online MR 解析数据库。首次启动拒绝使用记录原位置的存储清单，隔离副本保留原清单并由应用生成新清单后成功启动。现场及压力测试仍见总台账。

两条线均进入设备管理、FIT-AP、轨旁 AP、Online MR 分析、任务中心和 Ground，并操作 Ground 的 Heartbeat、Quick Ping、Syslog、时间轴、AC-Mesh-Link 和归档页。HZL9 设备管理显示 117 台设备，Ground 可选择归档运行。HZL10 的实际回放复现了旧归档失败出现在实时页的问题，修复后重新打开页面显示「暂无运行」。历史失败记录继续保存在原有数据中。

截图和 Ground 导航记录见 Workspace 的 `reports/diagnostic/phase8-real-replay/pages/`。最终 Full Gate 日志见 `reports/tests/phase8-final-27f7d662-full-gate.log`，首次 Gate 发现的 Renderer 类型错误、文档目录缺失和 Syslog 端口回归均已修复。

## 2026-11-26 续作验收

| 项目 | 当前证据 | 待验收 |
| --- | --- | --- |
| Ground Syslog | Windows 回环 TCP/UDP 实际收包。验证 RFC 6587、半包、粘包、多连接、截断诊断、中文原文、两台 MR 和未知来源隔离、SQLite 投影、原始历史查询、独占绑定和停止后重绑。实际 Electron 显示测试 WMESH 事件，同一记录在显式停止后可按 run 查询 | 真实设备 TCP 回传 |
| Heartbeat / Quick Ping | Windows fping 回环真实采集两个目标，两轮启停，每轮每目标保存 8 个成功样本。调度、丢包状态、缺样及页面用定向回归补齐 | 网络层丢包、主备故障切换及长稳 |
| 外部终端 | Windows OpenSSH 9.5p2 在回环 fixture 上实际完成公钥认证，验证备用地址、中文空格用户名、失败反馈。修复 Xshell SSH URL 的凭据编码，SecureCRT 和 PuTTY 明文 argv 通过构造回归 | SecureCRT、PuTTY、Xshell 和 WinSCP 实机启动与认证 |
| Portable | 从 `11061806` ZIP 在两个中文空格程序路径实际启动全新外部 DataRoot 及复用场景，交互就绪 5.187 秒与 5.170 秒。冻结 Worker、Backend 退出及端口重绑通过 | 最新候选复核与跨版本迁移 |
| 安装迁移 | 复现安装器迁移入口的授权错误。修复提升权限和 HKLM 来源核验后调用现有迁移服务。合成已配置根实迁移与目标非空保护通过 | 受支持 Windows Guest 的 GUI 安装、升级、卸载、数据保留和回滚 |
| Comware | 已授权实验 AC 和 AC2 在 TCP 建连阶段超时。协议/能力矩阵通过脱敏 fixture 验证 | 真实 Comware V5/V7/V9 设备版本识别与只读 WLAN 采集 |
| Ground 历史性能 | HZL10 同一隔离索引的 25 条混合历史查询，三次测量从 38.74、6.20、6.07 秒降为 1.94、1.00、0.97 秒。先排序标识和时间，再批量投影当前页详情 | 完整业务页面与连续运行性能矩阵 |

最终 Full NSIS `NetConsole-Full-1.5.19.0-27f7d662-x64-setup.exe` SHA-256 为
`4b9e40aff838bd69b0a0ffea5ff5ae8ea79adb71ce55101eedea68dcce1f757f`。Portable ZIP
`NetConsole-1.5.19-portable.zip` SHA-256 为
`33b63f57056d0106228bf56fd7817394af4b033cfe7c3d6c176c68d00955274f`。Backend、
Frontend 与 installer identity 都绑定 `27f7d662`，`BUILD_DIRTY=false`。两包 SBOM
均为 CycloneDX 1.5、68 个组件。Portable 新建外部 DataRoot 的启动就绪 5.022 秒，
冻结 Worker、正常退出和端口重绑通过。候选和报告在
`temp/build/phase8-final-package/build-27f7d662-20261126-111637/candidates/` 与
`reports/build/phase8-final-package-build-27f7d662-20261126-111637/`。

Ground 实时 UDP/TCP、逐帧 TCP 和 TCP/UDP 独占监听已通过合成 Electron/Backend；
独立 600 秒 TCP 负载完整接收、写入和解析 12,000 条，应用丢弃 0，停止后端口释放。
真实实验设备回传仍待验证。

HZL9 与 HZL10 实际源码 Electron 的 Backend 健康 / 首屏分别为 4.992 / 5.030 秒、
4.423 / 6.919 秒。HZL9 的 Quick Ping 两页各 25 条且无重复，窗口查询 200 条，五次请求
最大 38.87 ms。独立百万行 fixture 的起始两页耗时 3.58–4.47 ms，末端两页
73.35–79.65 ms，两处均保留失败点。实际 Ground CSV 导出在两线分别完成 2 条和 7 条，
下载内容与 Artifact SHA-256 一致。真实光模块资源已查询，光衰明细时序仍待验收。

HZL9 长任务的末五分钟此前停在空扫描页。历史单目标初次加载现在可在收到空扫描页后
继续使用原查询游标，最多 32 页，切窗时取消。复测首屏 3.513 秒显示 1,000 个样本，
第二页 492 个，截图可见 RTT、成功点和丢包点。多目标对比和任意时间定位仍待验收。

两线短时回放约 79 / 96 秒，Backend RSS 峰值 263.5 / 317.9 MiB，最大 Electron 子进程
RSS 峰值 803.4 / 745.1 MiB，退出码均为 0，四个回环端口均关闭。独立 TCP 120 秒
负载写入并解析 3,600 条，应用丢弃 0，写入与解析队列排空，观察到的句柄数为 164。
回放测量、截图和下载结果位于 `reports/diagnostic/phase8-real-replay/PHASE8_REPLAY_PERFORMANCE.md`。

定向结果及运行证据位于 Workspace 的 `reports/tests/phase8-continuation-gate.log`、
`phase8-tcp-mr.log`、`phase8-continuation-scale.log`、`phase8-continuation-renderer.log`、
`phase8-fping-quick-ping-service.log`、`phase8-heartbeat-faults.log`、
`phase8-quick-ping-million.log`、`phase8-syslog-bind-conflict.log`、`phase8-syslog-soak.log` 和
`phase8-portable-external-20261126/`。
OpenSSH 与设备超时见同一目录下 `phase8-integrated-11061806/external-openssh-loopback.log`
及 `phase8-integrated-11061806/comware-lab-readonly.json`。

## 真实数据历史审计

本阶段完成杭州地铁 9 号线和 10 号线真实运行数据的本地隔离解压、压缩包 SHA-256 核对、DataRoot 结构审计、SQLite 只读 Schema/行数审计和对比报告。原始压缩包保持原位，未上传、未修改或删除。

## 证据报告

- [HZL9_REAL_DATA_ACCEPTANCE.md](./real-data-20261125/HZL9_REAL_DATA_ACCEPTANCE.md)
- [HZL10_REAL_DATA_ACCEPTANCE.md](./real-data-20261125/HZL10_REAL_DATA_ACCEPTANCE.md)
- [REAL_DATA_COMPARISON.md](./real-data-20261125/REAL_DATA_COMPARISON.md)

## 状态边界

- 结构审计和 SQLite 只读查询：PASS。
- HZL9 Ground、MESH、Quick Ping、AP/设备和任务历史具备真实记录，结果为 PASS_WITH_EVIDENCE_CAVEATS。
- HZL10 Ground、MESH、AP/设备和车辆 MR 具备真实记录。当前 Ground 数据无 Quick Ping 记录，标记 NOT AVAILABLE。
- 本节历史审计未覆盖实际应用。当前源码启动证据见上表，Windows 安装态、完整 GUI 回放、页面性能、内存/CPU、写入式迁移与回滚保持待验收。Full Gate 和冻结制品 smoke 已通过，不能替代这些现场验收。

## 数据安全

Console v1.5.19 专项在隔离数据根验证，记录了用户授权的实验室 AC 远程登录配置变更。下列数据指标适用于此前 Phase 8 验收。[Console 专项验收](./CONSOLE_1_5_19_ACCEPTANCE.md)

`PRODUCTION_DATA_MODIFIED=0`、`DEV_REAL_BUSINESS_DATA_MODIFIED=0`、`DATABASES_REMOVED=0`、`REAL_DEVICE_CONFIGURATION_WRITES=0`、`MAINTENANCE_AUTHORIZED=NO`。

验证数据仅位于 Workspace 的 `test-data/NetConsole/real-data-20261125-hz9` 和 `real-data-20261125-hzl10`，未纳入 Git。
