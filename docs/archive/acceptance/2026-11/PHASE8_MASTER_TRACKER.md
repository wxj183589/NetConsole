# NetConsole Phase 8 / 8.1 总任务台账

整体状态为 **PARTIAL**。开发继续使用 `codex-A/organization-task-network-services-phase6`。集成提交 `f55e75b1` 同时包含 `42709227`、`fd8f6e58` 和 `d1c4b65f`。真实数据专项见 [Phase 8.1 总验收](./PHASE8_1_ACCEPTANCE.md)，前期结果见 [Phase 8 验收](./PHASE8_ACCEPTANCE.md) 与 [Phase 7.1 Windows 验收](../../../investigations/netconsole-phase7-20261125/PHASE7_WINDOWS_VM_ACCEPTANCE.md)。

| ID | 原始工作项 | 当前实现 | 已有证据 | 剩余缺口和下一步 | 验证入口 | 实施 | 验收状态与阻塞 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P8-01 | Comware V5/V7/V9 无线 AC 兼容 | 版本能力族及 V5 降级已有代码 | 能力族定向回归通过 | 实验 AC 和 AC2 TCP 超时。等待可达的 V5/V7/V9 设备 | tests/test_device_command_profile_service.py | 部分 | 实际 WLAN 采集 NOT VERIFIED |
| P8-02 | Syslog TCP/UDP 完整链路 | Ground 默认 UDP，显式开启同端口 TCP；使用单条持久化管线 | 回环 RFC 6587、半包、粘包、中文、截断、MR 隔离、SQLite、历史及端口重绑 | 复验真实 Electron 实时 Syslog 与实验设备 | tests/test_ground_unattended_syslog_v2_stress.py | 已实施 | 隔离 Socket PASS，现场与实时页面待验收 |
| P8-03 | Heartbeat 自然秒与丢包真实性 | 单调调度和图表缺样处理 | 真实 fping 双目标、定向故障状态与 Renderer 回归 | 网络层故障时序和主备切换实测 | tests/test_ground_unattended_heartbeat_resident.py | 部分 | 真实故障注入待执行 |
| P8-04 | Quick Ping Portable 首次写入 | 已有目录初始化与独占文件创建 | Quick Ping 定向回归、Portable 中文空格路径冷启动 | 冻结程序测试新根、长路径、中文路径和并发轮转 | pytest tests/test_ground_unattended_quick_ping.py | 部分 | 并发轮转与完整迁移矩阵待现场验收 |
| P8-05 | Quick Ping 大数据分页与曲线 | 有游标和扫描预算，晚时间窗增加无关分区跳过 | Quick Ping 定向回归 | 独立曲线查询与明细，补任意定位及百万级数据压测 | pytest tests/test_ground_unattended_quick_ping.py tests/test_ground_unattended_quick_ping_repository.py | 部分 | 真实 HZL9 查询与百万级采样待完成 |
| P8-06 | 外部终端自动认证 | OpenSSH 实际运行；修复 Xshell URL 凭据保留字符 | OpenSSH 回环认证、失败、中文空格、备用地址；其他 Provider 参数定向回归 | SecureCRT、PuTTY、Xshell 和 WinSCP 客户端实测 | external-openssh-loopback.log | 部分 | Windows OpenSSH 公钥 PASS，其余客户端未安装 |
| P8-07 | Ground 实时与历史回放 | 已隔离陈旧归档失败提示，完整统一回放待实施 | Ground 37 项定向测试及 HZL10 Electron 复测 | 隔离运行会话、订阅和历史查询，再实现统一时间轴、导航及导出 | vitest run GroundUnattendedView.behavior | 部分 | 当前实时空闲态已验，完整回放待实施 |
| P8-08 | 控制台成熟终端交互 | 现有 xterm.js 与 SSH/Telnet 通道 | Phase 8 | 验证键盘、分页、大输出和会话关闭并修复重现问题 | vitest run src/views/console | 部分 | 实连和视觉矩阵待执行 |
| P8-09 | 管理按钮与批量命令 | 控制台已有命令栏 | Phase 8 | 验证普通布局、显式批量模式、逐会话状态和取消 | vitest run src/views/console | 部分 | 待继续实施 |
| P8-10 | 终端规则文件兼容 | 现有规则加载器，旧格式兼容待核对 | Phase 8 | 用历史样本复现校验失败，验证迁移、默认恢复及导入导出 | python -m scripts.quality.local_gate --mode auto | 部分 | 样本及现有行为待核对 |
| P8-11 | 备用地址连接 | Phase 8 已传递备用地址字段 | Phase 8 | 核对手工 backup_host 和各入口的真实目标地址与端口 | pytest tests/test_device_management_table_rules.py | 部分 | 实际连接待验收 |
| P8-12 | Portable 完整产品能力 | 独立数据根及 ZIP | 实际外部 DataRoot 初始化、程序换路径复用、冻结 Worker、退出重绑 | 复核升级、迁移和新候选 | phase8-portable-external-20261126 | 部分 | 旧候选两次运行 PASS，跨版本待验收 |
| P8-13 | 数据迁移、校验与回滚 | 保留清单、SHA-256、SQLite 校验、源根；修复 NSIS 提升权限并核验 HKLM 来源 | 合成已配置根实迁移及目标非空保护通过 | 执行受支持 Windows Guest 的 GUI 迁移及回滚 | tests/test_installer_backend_diagnostics.py | 部分 | 安装态 NOT VERIFIED |
| P8-14 | 外部工具配置迁移 | V1 升级及 IPOP 去重和失败重试保留 | 16 个 Electron 迁移相关测试通过 | 验证现有客户端路径和真实启动 | node node_modules/vitest/vitest.mjs run tests/external-tool-store.test.ts | 已有 | 真实工具启动待验收 |
| P8-15 | HZL9 真实业务回放 | 隔离副本已启动 Backend 与 Electron | HZL9 专项与真实 Electron 启动记录 | 核验历史 Run、Quick Ping 故障点和实际分页 | 运行 Electron 隔离回放 | 部分 | 完整业务矩阵待验收 |
| P8-16 | HZL10 大规模真实回放 | 隔离副本已启动 Backend 与 Electron | HZL10 专项与真实 Electron 启动记录 | 核验 Ground、AC 快照、MESH 和 Online MR；真实 Quick Ping 缺失 | 运行 Electron 隔离回放 | 部分 | 完整业务矩阵待验收 |
| P8-17 | 性能与长时间稳定性 | 有首轮进程就绪计时和 Quick Ping 局部优化 | 真实 Electron 启动记录 | 建立重复基准，采集各页面与查询分位数、资源及前后对照 | 运行 Electron 隔离回放及规模压测 | 部分 | 长稳、分位数待测 |
| P8-18 | Electron 视觉与交互 | 实际 Electron 已启动两套隔离数据 | 真实 Electron 启动记录 | 完成 1920×1080 和 2560×1440 的完整交互矩阵 | 运行 Electron 并操作业务页面 | 部分 | 完整交互与尺寸待验收 |
| P8-19 | Windows 安装、升级、卸载 | Full NSIS 候选构建 | VM 清单仅发现 Windows 10 1909 原机和隔离克隆 | 使用可登录且受支持的 Windows Guest | NSIS 安装态矩阵 | 部分 | 支持版本 Guest 与登录环境缺失 |
| P8-20 | Full Gate | 项目现有 FULL 入口 | 11061806 Full Gate 日志 | 最终代码提交运行 FULL，验证制品及消费者 | python -m scripts.quality.local_gate --mode full | 已有 | PASS，外部现场缺口仍见 P8-01 至 P8-19 |
| P8-21 | Full NSIS 安装包 | 已有 Full 打包入口 | `NetConsole-Full-1.5.19.0-11061806-x64-setup.exe`，SHA-256 `410a592a3190e05cc45281be53ece605067558f8e793207e9f0e669493195462` | 最终源码构建、离线 smoke、清单和 SHA-256 | scripts/build/package_local.ps1 -Edition full | 已有 | 构建与 smoke PASS，真实安装升级卸载待验收 |
| P8-22 | Portable ZIP | 已有 Portable 打包入口 | `NetConsole-1.5.19-portable.zip`，SHA-256 `19D4ADA01654DB6EF0FEE7AF1A756362F396CE3AD77C1CE35AAF14FF5715B4D0` | 与 NSIS 使用同一源码，验证冻结 Worker 与迁移 | 按项目 Portable 打包入口 | 已有 | 构建、package smoke、中文空格路径冷启动 PASS，迁移现场矩阵待验收 |
| P8-23 | 最终代码集成、Git 与交付 | 产品与真实审计基线已在原分支合并 | Full Gate PASS、产品与 DevStatus 远端 SHA 已核对 | 分支推送、更新 DevStatus，最终在同一基线复核 | git merge-base --is-ancestor d1c4b65f HEAD | 部分 | DevStatus 更新后完成本轮交付，真实设备、安装态和长稳仍待验收 |

## 证据路径

- 产品前期证据在 [Phase 8 验收](./PHASE8_ACCEPTANCE.md) 和 [Phase 7 历史报告](../../../investigations/netconsole-phase7-20261125/PHASE7_ACCEPTANCE.md)。
- 真实数据副本启动日志位于 Workspace 的 `test-data/NetConsole/phase8-replay-hz9/runtime/logs/electron.log` 和 `test-data/NetConsole/phase8-replay-hz10/runtime/logs/electron.log`。应用时间从 Electron 进程启动计时，以日志中的 `STARTUP_PERFORMANCE_SUMMARY` 为准。
- 业务截图和 Ground 导航记录位于 Workspace 的 `reports/diagnostic/phase8-real-replay/pages/`，其中 `hz10-ground-idle-after.png` 记录陈旧失败提示修复后的实时空闲态。
- 工作树仓库级目录检查通过。主仓目录检查报告历史顶层 `build` 和 `temp/phase6-electron-runtime`，原样保留。
- 最终 Full Gate：`RESULT: PASS`，Python `5878 passed / 3 skipped / 35 warnings`，Renderer `224 files / 1616 tests`，Electron `41 files / 326 tests`，Architecture `12/12`，Main contract `12 passed`，Docs/path `22 passed`，Ruff、diff-check 和 package smoke 均通过。日志见 `reports/tests/phase8-integrated-11061806/full-gate.log`。
- 最终制品均绑定提交 `11061806` 且 `BUILD_DIRTY=false`。真实 Windows 安装升级卸载、真实设备、外部终端自动认证、Ground TCP、故障注入和长时间性能仍保持 PARTIAL/NOT VERIFIED。
