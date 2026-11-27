# NetConsole Phase 8 / 8.1 总任务台账

## 2026-11-27 地面无人值守 R3.0 阶段验证

- 选定 Run 的多来源历史页改为每个来源有界取候选，再执行全局时间合并。源导出、分页、API、归档查询、规模和时间轴定向回归共 95 passed / 1 skipped。32 次真实库测量中，HZL10 最新 Run 多源页 P95 首屏/游标分别为 65.3/69.5 ms，时间轴 125.4/127.5 ms。未选 Run 的 807 ms 跨历史查询没有优化，保留原路径并记录为待处理项。见 [SQL 查询审计](./real-data-20261125/SQL_QUERY_AUDIT.md)。

- 状态 `PARTIAL`。从 `1d47344a` 建立独立开发工作树 `worktrees/ground-unattended-r3-20261127`，工作树内布局检查通过。主工作区已有的根目录 `build`、未登记旧工作树目录和三项历史临时输出继续保留，主工作区布局检查仍失败。
- 实时页面仅选取活动 Run，空闲时跳过 Syslog、时间轴和深度采集查询。Run 切换取消旧查询并清空相应结果。历史回放过滤活动和收尾中的 Run，并提供历史 Syslog 查询和保留既有删除校验的入口。
- Renderer 定向 61 项通过，Vue 类型检查通过。TCP、UDP 和共享投影已有实现的定向验证 12 项通过。
- 已复核两份历史归档的 SHA-256 与既有记录一致。使用已有隔离回放副本，以 `6adc5a15` 启动真实 Electron，关闭采集。HZL9、HZL10 时间轴均返回 25 条首屏事件，下一页首条记录变化，切回实时后历史表格退出。点击至完成截图的单次计时分别为 309 ms、898 ms。四张截图位于 Workspace 的 `reports/diagnostic/ground-unattended-r3-20261127`。退出后六个测试监听端口均释放。
- TCP 空行处理已修复，回环验证长度帧、换行帧、UDP 数据报共用持久化链路。独立数据集导入、完整 Electron 回放矩阵、设备配置闭环、混合负载与长稳、Full Gate 和制品仍待完成。
- 回放切换 Run 时取消上一 Run 的 MR、图表和时间轴查询。Renderer 定向 63 项与 Vue 类型检查通过，源码提交 `379b02b2`。
- 混合历史分页 API 提供跳过精确总数选项。HZL10 25 条查询中位数从 1,276.9 ms 降到 807.0 ms，仍高于目标。[SQL 查询审计](./real-data-20261125/SQL_QUERY_AUDIT.md)

整体状态为 **PARTIAL**。开发继续使用 `codex-A/organization-task-network-services-phase6`。集成提交 `f55e75b1` 同时包含 `42709227`、`fd8f6e58` 和 `d1c4b65f`。真实数据专项见 [Phase 8.1 总验收](./PHASE8_1_ACCEPTANCE.md)，前期结果见 [Phase 8 验收](./PHASE8_ACCEPTANCE.md) 与 [Phase 7.1 Windows 验收](../../../investigations/netconsole-phase7-20261125/PHASE7_WINDOWS_VM_ACCEPTANCE.md)。

| ID | 原始工作项 | 当前实现 | 已有证据 | 剩余缺口和下一步 | 验证入口 | 实施 | 验收状态与阻塞 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P8-01 | Comware V5/V7/V9 无线 AC 兼容 | 版本能力族及 V5 降级已有代码 | 能力族定向回归通过 | 实验 AC 和 AC2 TCP 超时。等待可达的 V5/V7/V9 设备 | tests/test_device_command_profile_service.py | 部分 | 实际 WLAN 采集 NOT VERIFIED |
| P8-02 | Syslog TCP/UDP 完整链路 | Ground 默认 UDP，显式开启同端口 TCP | 实际回环和 Electron 验证分帧、MR 关联、SQLite、实时记录与历史查询 | 实验设备 TCP 回传 | tests/test_ground_unattended_syslog_v2_stress.py | 已实施 | 隔离链路 PASS，现场待验收 |
| P8-03 | Heartbeat 自然秒与丢包真实性 | 单调调度和图表缺样处理 | 真实 fping 双目标、定向故障状态与 Renderer 回归 | 网络层故障时序和主备切换实测 | tests/test_ground_unattended_heartbeat_resident.py | 部分 | 真实故障注入待执行 |
| P8-04 | Quick Ping Portable 首次写入 | 已有目录初始化与独占文件创建 | Quick Ping 定向回归、Portable 中文空格路径冷启动 | 冻结程序测试新根、长路径、中文路径和并发轮转 | pytest tests/test_ground_unattended_quick_ping.py | 部分 | 并发轮转与完整迁移矩阵待现场验收 |
| P8-05 | Quick Ping 大数据分页与曲线 | 保留有界查询，历史曲线续读空扫描页 | HZL9 实际分页和窗口，独立百万行分页，失败点保留 | 保留全目标对比边界，验证现场失连曲线 | tests/test_ground_unattended_quick_ping.py | 已实施 | HZL9 单目标历史曲线与连续分页 |
| P8-06 | 外部终端自动认证 | OpenSSH 实际运行；修复 Xshell URL 凭据保留字符 | OpenSSH 回环认证、失败、中文空格、备用地址；其他 Provider 参数定向回归 | SecureCRT、PuTTY、Xshell 和 WinSCP 客户端实测 | external-openssh-loopback.log | 部分 | Windows OpenSSH 公钥 PASS，其余客户端未安装 |
| P8-07 | Ground 实时与历史回放 | 已隔离陈旧归档失败提示，完整统一回放待实施 | Ground 37 项定向测试及 HZL10 Electron 复测 | 隔离运行会话、订阅和历史查询，再实现统一时间轴、导航及导出 | vitest run GroundUnattendedView.behavior | 部分 | 当前实时空闲态已验，完整回放待实施 |
| P8-08 | Console 设置与会话回放 | SSH/Telnet/Serial 共用 Session Manager；设置页按需分页和轻量规则控件；回放全文搜索支持 ANSI 256/True Color | Python 设置/录制 58、Renderer Console 47、Electron 328 定向通过；真实 Electron >1 MiB 隔离 SSH 录制全文搜索，LOG/ZIP/JSONL 哈希一致 | 实体 Telnet/COM 并发、真冷缓存、高输出资源曲线、提交后 Full Gate/NSIS/Portable | Console 定向测试、Full Gate、Electron 隔离录制 | 部分 | 空闲首开 75/83 ms；Full Gate CPU 密集负载首开 281/293 ms；热开 P95 62 ms；实体 Telnet/COM NOT VERIFIED |
| P8-09 | 管理按钮与批量命令 | 映射按钮栏、Send String、受限 Menu Function/Run Script、登记工具启动、批量调度及受限 Launch Application 会话变量已实现；按钮配置 v1 兼容迁移到 v2。Renderer 仅传固定限长会话 DTO，Main 使用登记参数模板展开 argv | 本次固定 DTO 改造后的 Renderer Console/API 31 项、Electron External Tool/IPC 18 项、Python Console/Session 26 项通过；Renderer/Electron 类型检查和 Python Ruff 通过；Electron 隔离 SSH/SFTP 与复合 GUI 验收通过，证据在 Workspace reports/tests/console-1.5.19-resume-20261126/electron-sftp-fix-20261126 | 完成真实客户端参数/认证兼容、按钮动作全矩阵和原生对话框/拖放验收 | Console 定向 Renderer/Electron/Python 测试及隔离 Electron 复合验收 | 部分 | 源码与隔离 GUI 定向验证 PASS；SecureCRT/PuTTY/Xshell/WinSCP 实机认证、原生对话框和 Explorer 拖放仍未验收 |
| P8-10 | 终端规则文件兼容 | 现有规则加载器，旧格式兼容待核对 | Phase 8 | 用历史样本复现校验失败，验证迁移、默认恢复及导入导出 | python -m scripts.quality.local_gate --mode auto | 部分 | 样本及现有行为待核对 |
| P8-11 | 备用地址连接 | Phase 8 已传递备用地址字段 | Phase 8 | 核对手工 backup_host 和各入口的真实目标地址与端口 | pytest tests/test_device_management_table_rules.py | 部分 | 实际连接待验收 |
| P8-12 | Portable 完整产品能力 | 独立数据根及 ZIP | 实际外部 DataRoot 初始化、程序换路径复用、冻结 Worker、退出重绑 | 复核升级、迁移和新候选 | phase8-portable-external-20261126 | 部分 | 旧候选两次运行 PASS，跨版本待验收 |
| P8-13 | 数据迁移、校验与回滚 | 保留清单、SHA-256、SQLite 校验、源根；修复 NSIS 提升权限并核验 HKLM 来源 | 合成已配置根实迁移及目标非空保护通过 | 执行受支持 Windows Guest 的 GUI 迁移及回滚 | tests/test_installer_backend_diagnostics.py | 部分 | 安装态 NOT VERIFIED |
| P8-14 | 外部工具配置迁移 | V1 升级及 IPOP 去重和失败重试保留 | 16 个 Electron 迁移相关测试通过 | 验证现有客户端路径和真实启动 | node node_modules/vitest/vitest.mjs run tests/external-tool-store.test.ts | 已有 | 真实工具启动待验收 |
| P8-15 | HZL9 真实业务回放 | 隔离 Backend 和 Electron 实际回放 | HZL9 Quick Ping 分页、时间窗、历史 CSV 和截图 | 部分明细与现场完整矩阵 | PHASE8_REPLAY_PERFORMANCE.md | 部分 | 已验业务路径见报告 |
| P8-16 | HZL10 大规模真实回放 | 混合历史先排序再投影 | 实际 Electron 和 API，HZL10 同库热查询约 6.1 秒降至约 1.0 秒 | 光衰明细与更长连续回放 | PHASE8_REPLAY_PERFORMANCE.md | 部分 | 真实 Ground 无 Quick Ping 数据 |
| P8-17 | 性能与长时间稳定性 | Ground 混合历史优化并加入复测 | 两线短时真实运行、独立 TCP 负载、CPU / RSS / 句柄 / 队列 | 长时真实多 MR 运行 | PHASE8_REPLAY_PERFORMANCE.md | 部分 | 短时资源证据可复核 |
| P8-18 | Electron 视觉与交互 | 实际 Electron 运行两套隔离数据及合成 TCP | 保留 1920×1080 与 HZL9 Ground 2560×1440 截图 | 完整矩阵与 Windows 原生 DPI | 隔离数据 Electron 回放 | 部分 | 验收截图已保存 |
| P8-19 | Windows 安装、升级、卸载 | Full NSIS 候选构建 | VM 清单仅发现 Windows 10 1909 原机和隔离克隆 | 使用可登录且受支持的 Windows Guest | NSIS 安装态矩阵 | 部分 | 支持版本 Guest 与登录环境缺失 |
| P8-20 | Full Gate | 项目现有 FULL 入口 | 27f7d662 Full Gate 日志 | 最终代码提交运行 FULL，验证制品及消费者 | python -m scripts.quality.local_gate --mode full | 已有 | PASS，外部现场缺口仍见 P8-01 至 P8-19 |
| P8-21 | Full NSIS 安装包 | 已有 Full 打包入口 | `NetConsole-Full-1.5.19.0-27f7d662-x64-setup.exe`，SHA-256 `4b9e40aff838bd69b0a0ffea5ff5ae8ea79adb71ce55101eedea68dcce1f757f` | 最终源码构建、离线 smoke、清单和 SHA-256 | scripts/build/package_local.ps1 -Edition full | 已有 | 包内提交和 dirty 状态、CycloneDX 1.5 68 components、package smoke PASS，真实安装升级卸载待验收 |
| P8-22 | Portable ZIP | 已有 Portable 打包入口 | `NetConsole-1.5.19-portable.zip`，SHA-256 `33b63f57056d0106228bf56fd7817394af4b033cfe7c3d6c176c68d00955274f` | 与 NSIS 使用同一源码，验证冻结 Worker 与迁移 | 按项目 Portable 打包入口 | 已有 | 包内提交及 SBOM PASS，中文空格程序目录和外部 DataRoot 冷启动 5.022 秒、冻结 Worker 与端口重绑 PASS，迁移现场矩阵待验收 |
| P8-23 | 最终代码集成、Git 与交付 | 产品与真实审计基线已在原分支合并 | Full Gate PASS、产品与 DevStatus 远端 SHA 已核对 | 分支推送、更新 DevStatus，最终在同一基线复核 | git merge-base --is-ancestor d1c4b65f HEAD | 部分 | 产品与 DevStatus 更新后完成本轮交付，真实设备、安装态和长稳仍待验收 |

## 证据路径

- Console v1.5.19 续作五制品以 `fb883f37e43d49fb26c229c655a5dddbac3c306f` 为源码身份。Full NSIS SHA-256 `ca8708f09139c7a1d3bac44ab3e7a1edfb12fc2986dd0a0bb1bd0157f84bdde3`，Portable ZIP SHA-256 `2a5d9b51a98e6c56ed909b9da107d37b6512594081802870cdf066435b8f756a`；双方 CycloneDX 1.5 各 68 components，package smoke PASS。Full Gate 最终提交后按用户要求未重跑，前一次代码组合的 Full Gate 有 3 条架构失败，修复后架构、Ruff 和定向回归通过。安装态 GUI 和实体 Telnet/COM 未验收。

- Console 续作四在 P8-08 下继续追踪。设置首屏解耦和规则轻量分页、完整录制流式搜索、ANSI 256/True Color 已实施。实际 Electron 验证大于 1 MiB 录制和三种导出 SHA 一致。Workspace Layout 已通过；首轮 Full Gate 架构/Ruff/包 smoke 失败项修复后，需提交源码再跑最终门禁。[专项报告](./CONSOLE_SETTINGS_REPLAY_20261127.md)

- Console v1.5.19 专项为 PARTIAL。历史真实 AC SSH、FIT-AP Telnet 单次回车、批量发送及 Portable/NSIS 证据仍绑定旧候选。本轮新增 pySerial 3.5 串口会话、中文化和设置性能修复通过定向测试，实际 Electron 设置重开 30 次中位数 30 ms；枚举到的 COM3/COM4 为蓝牙端口，没有执行硬件读写。当前源码的 Full Gate、冻结 Worker、NSIS 与 Portable 尚未构建验收。外部客户端认证及真实 USB 串口仍待完成。[Console 专项验收](./CONSOLE_1_5_19_ACCEPTANCE.md)

- 产品前期证据在 [Phase 8 验收](./PHASE8_ACCEPTANCE.md) 和 [Phase 7 历史报告](../../../investigations/netconsole-phase7-20261125/PHASE7_ACCEPTANCE.md)。
- 真实数据副本启动日志位于 Workspace 的 `test-data/NetConsole/phase8-replay-hz9/runtime/logs/electron.log` 和 `test-data/NetConsole/phase8-replay-hz10/runtime/logs/electron.log`。应用时间从 Electron 进程启动计时，以日志中的 `STARTUP_PERFORMANCE_SUMMARY` 为准。
- 业务截图和 Ground 导航记录位于 Workspace 的 `reports/diagnostic/phase8-real-replay/pages/`，其中 `hz10-ground-idle-after.png` 记录陈旧失败提示修复后的实时空闲态。
- 工作树仓库级目录检查通过。主仓目录检查报告历史顶层 `build` 和 `temp/phase6-electron-runtime`，原样保留。
- 最终 Full Gate：`RESULT: PASS`，Python `5890 passed / 3 skipped / 35 warnings`，Renderer `224 files / 1619 tests`，Electron `41 files / 326 tests`，Architecture `12/12`，Main contract `12 passed`，Docs/path `22 passed`，Ruff、diff-check 和 package smoke 均通过。日志见 `reports/tests/phase8-final-27f7d662-full-gate.log`。
- Full NSIS 和 Portable ZIP 均绑定提交 `27f7d662a56a9e8439548ce520c0dba3dd76cfde` 且 `BUILD_DIRTY=false`。Portable 隔离冷启动的交互时间为 5.022 秒。真实 Windows 安装升级卸载、Comware V5/V7/V9 实机、SecureCRT/PuTTY/Xshell 实机、主备网络故障注入和长时间现场运行仍为 `NOT VERIFIED`。
