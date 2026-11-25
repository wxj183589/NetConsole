# NetConsole Phase 8 / 8.1 总任务台账

整体状态为 **PARTIAL**。开发继续使用 `codex-A/organization-task-network-services-phase6`。集成提交 `f55e75b1` 同时包含 `42709227`、`fd8f6e58` 和 `d1c4b65f`。真实数据专项见 [Phase 8.1 总验收](./PHASE8_1_ACCEPTANCE.md)，前期结果见 [Phase 8 验收](./PHASE8_ACCEPTANCE.md) 与 [Phase 7.1 Windows 验收](../../../investigations/netconsole-phase7-20261125/PHASE7_WINDOWS_VM_ACCEPTANCE.md)。

| ID | 原始工作项 | 当前实现 | 已有证据 | 剩余缺口和下一步 | 验证入口 | 实施 | 验收状态与阻塞 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P8-01 | Comware V5/V7/V9 无线 AC 兼容 | 版本能力族及 V5 降级已有代码 | Phase 8 定向回归 | 执行设备版本识别、只读 WLAN 命令及多 AC 隔离验证 | pytest tests/test_device_command_profile_service.py | 部分 | 实验版本矩阵待确认 |
| P8-02 | Syslog TCP/UDP 完整链路 | 网络服务已有 RFC 6587，Ground 接收器仅 UDP | Phase 8 与 socket 回归 | 复用分帧器接入 Ground 队列并验证 MR 位置、回放和端口释放 | pytest tests/test_local_network_services.py tests/test_ground_unattended_syslog_v2_stress.py | 部分 | Ground TCP 尚待实施 |
| P8-03 | Heartbeat 自然秒与丢包真实性 | 单调调度和图表故障点已有修订 | Phase 8 与调度回归 | 受控网络测试超时、错误、缺样、主备切换及多 MR，核对持久化曲线 | pytest tests/test_heartbeat_scheduler_timing.py | 部分 | 真实故障注入待执行 |
| P8-04 | Quick Ping Portable 首次写入 | 已有目录初始化与独占文件创建 | Quick Ping 定向回归 | 冻结程序测试新根、长路径、中文路径和并发轮转 | pytest tests/test_ground_unattended_quick_ping.py | 部分 | 冻结制品待构建 |
| P8-05 | Quick Ping 大数据分页与曲线 | 有游标和扫描预算，晚时间窗增加无关分区跳过 | Quick Ping 定向回归 | 独立曲线查询与明细，补任意定位及百万级数据压测 | pytest tests/test_ground_unattended_quick_ping.py tests/test_ground_unattended_quick_ping_repository.py | 部分 | 真实 HZL9 查询与百万级采样待完成 |
| P8-06 | 外部终端自动认证 | 已有客户端相关入口与 OpenSSH 工具支持 | Phase 8、外部工具回归 | 核对各 Provider 能力并实测登录、特殊字符和主机校验 | node node_modules/vitest/vitest.mjs run tests/external-tool-store.test.ts | 部分 | 客户端版本、认证环境待确认 |
| P8-07 | Ground 实时与历史回放 | 有多个业务页面和运行查询，完整统一回放待实施 | 真实 Electron 启动记录 | 隔离运行会话、订阅和历史查询，再实现统一时间轴、导航及导出 | vitest run GroundUnattendedView.behavior | 部分 | 待继续实施 |
| P8-08 | 控制台成熟终端交互 | 现有 xterm.js 与 SSH/Telnet 通道 | Phase 8 | 验证键盘、分页、大输出和会话关闭并修复重现问题 | vitest run src/views/console | 部分 | 实连和视觉矩阵待执行 |
| P8-09 | 管理按钮与批量命令 | 控制台已有命令栏 | Phase 8 | 验证普通布局、显式批量模式、逐会话状态和取消 | vitest run src/views/console | 部分 | 待继续实施 |
| P8-10 | 终端规则文件兼容 | 现有规则加载器，旧格式兼容待核对 | Phase 8 | 用历史样本复现校验失败，验证迁移、默认恢复及导入导出 | python -m scripts.quality.local_gate --mode auto | 部分 | 样本及现有行为待核对 |
| P8-11 | 备用地址连接 | Phase 8 已传递备用地址字段 | Phase 8 | 核对手工 backup_host 和各入口的真实目标地址与端口 | pytest tests/test_device_management_table_rules.py | 部分 | 实际连接待验收 |
| P8-12 | Portable 完整产品能力 | 已有独立数据根与 ZIP 路径 | Phase 8 Portable 架构 | 从冻结程序验证空库、外部根、移动、升级及排他锁 | 按制品 smoke 与冷启动矩阵 | 部分 | 冻结制品待构建 |
| P8-13 | 数据迁移、校验与回滚 | 有清单、SHA-256、SQLite 检查与源保留 | Phase 8 数据迁移 | 执行 HZL9 隔离迁移、失败回滚、跨盘和 DPAPI 迁移 | pytest tests/test_site_storage.py | 部分 | 写入迁移待执行 |
| P8-14 | 外部工具配置迁移 | V1 升级及 IPOP 去重和失败重试保留 | 16 个 Electron 迁移相关测试通过 | 验证现有客户端路径和真实启动 | node node_modules/vitest/vitest.mjs run tests/external-tool-store.test.ts | 已有 | 真实工具启动待验收 |
| P8-15 | HZL9 真实业务回放 | 隔离副本已启动 Backend 与 Electron | HZL9 专项与真实 Electron 启动记录 | 核验历史 Run、Quick Ping 故障点和实际分页 | 运行 Electron 隔离回放 | 部分 | 完整业务矩阵待验收 |
| P8-16 | HZL10 大规模真实回放 | 隔离副本已启动 Backend 与 Electron | HZL10 专项与真实 Electron 启动记录 | 核验 Ground、AC 快照、MESH 和 Online MR；真实 Quick Ping 缺失 | 运行 Electron 隔离回放 | 部分 | 完整业务矩阵待验收 |
| P8-17 | 性能与长时间稳定性 | 有首轮进程就绪计时和 Quick Ping 局部优化 | 真实 Electron 启动记录 | 建立重复基准，采集各页面与查询分位数、资源及前后对照 | 运行 Electron 隔离回放及规模压测 | 部分 | 长稳、分位数待测 |
| P8-18 | Electron 视觉与交互 | 实际 Electron 已启动两套隔离数据 | 真实 Electron 启动记录 | 完成 1920×1080 和 2560×1440 的完整交互矩阵 | 运行 Electron 并操作业务页面 | 部分 | 完整交互与尺寸待验收 |
| P8-19 | Windows 安装、升级、卸载 | Phase 7.1 有静态检查 | Phase 7.1 VM | 在支持版本 Guest 实测安装、升级及保留数据卸载 | 运行 NSIS 安装态矩阵 | 部分 | 历史 Guest 未登录且为 Windows 10 1909 |
| P8-20 | Full Gate | 项目现有 FULL 入口 | Phase 7 历史 Gate | 最终代码提交运行 FULL，验证制品及消费者 | python -m scripts.quality.local_gate --mode full | 已有 | 最终 Gate 待执行 |
| P8-21 | Full NSIS 安装包 | 已有 Full 打包入口 | Phase 7 历史制品 | 最终源码构建、离线 smoke、清单和 SHA-256 | scripts/build/package_local.ps1 -Edition full | 已有 | 当前候选待构建 |
| P8-22 | Portable ZIP | 已有 Portable 打包入口 | Phase 8 Portable 架构 | 与 NSIS 使用同一源码，验证冻结 Worker 与迁移 | 按项目 Portable 打包入口 | 已有 | 当前候选待构建 |
| P8-23 | 最终代码集成、Git 与交付 | 产品与真实审计基线已在原分支合并 | Git 祖先关系与 DevStatus | 分支推送、更新 DevStatus，最终在同一基线复核 | git merge-base --is-ancestor d1c4b65f HEAD | 部分 | 最终交付依赖前置验收 |

## 证据路径

- 产品前期证据在 [Phase 8 验收](./PHASE8_ACCEPTANCE.md) 和 [Phase 7 历史报告](../../../investigations/netconsole-phase7-20261125/PHASE7_ACCEPTANCE.md)。
- 真实数据副本启动日志位于 Workspace 的 `test-data/NetConsole/phase8-replay-hz9/runtime/logs/electron.log` 和 `test-data/NetConsole/phase8-replay-hz10/runtime/logs/electron.log`。应用时间从 Electron 进程启动计时，以日志中的 `STARTUP_PERFORMANCE_SUMMARY` 为准。
- 工作树仓库级目录检查通过。主仓目录检查报告历史顶层 `build` 和 `temp/phase6-electron-runtime`，原样保留。
