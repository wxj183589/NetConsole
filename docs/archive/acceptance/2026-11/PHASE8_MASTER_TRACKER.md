# NetConsole Phase 8 / 8.1 总任务台账

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
| P8-08 | 控制台成熟终端交互 | 现有 xterm.js 与 SSH/Telnet 通道 | Phase 8 | 验证键盘、分页、大输出和会话关闭并修复重现问题 | vitest run src/views/console | 部分 | 实连和视觉矩阵待执行 |
| P8-09 | 管理按钮与批量命令 | 控制台已有命令栏 | Phase 8 | 验证普通布局、显式批量模式、逐会话状态和取消 | vitest run src/views/console | 部分 | 待继续实施 |
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
