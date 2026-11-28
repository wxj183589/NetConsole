# 旧版桌面架构治理进度

产品分支 `codex-A/legacy-architecture-governance`，审计基线 `7d423a73`。每项的提交以本文件所在分支历史及 DevStatus 对应记录核对。阶段状态不代替安装态验收。

| 阶段 | 依赖 | 状态 | 当前证据 / 尚缺的验收 |
| --- | --- | --- | --- |
| A 全面审计 | 基线 | PARTIAL | [实现清单](../architecture/LEGACY_IMPLEMENTATION_INVENTORY.md)逐项索引 API、页面、Store 和静态表声明，业务真机行为待核验 |
| B 设计与开源研究 | A | PARTIAL | [源码研究](../architecture/OPEN_SOURCE_REFERENCE_STUDY.md)覆盖七个项目。设备详情复用 DeviceDetailApplicationService，文件与设备任务保留各自所有者 |
| C 安装与启动 | A | PARTIAL | 修正七处 NSIS 子进程调用，保留退出码、诊断 ID、日志与安装事务。细分功能、平台、无人值守和路由初始化；看门狗分别记录阶段上报时刻、无进展时长和总时长，保留原有硬截止时间 |
| D 控制台 | A | NOT VERIFIED | 检查粘贴、同步目标、前后端命令解析、断线清理 |
| E 设备资料 | B | NOT VERIFIED | 验证同一设备 ID 的台账、技术事实及工程关联 |
| F 设备任务中心 | B、E | NOT VERIFIED | 验证列表、详情、取消、重试、导出均在 Site 与设备任务域内 |
| G 轨交与无人值守 | A | NOT VERIFIED | 验证活动 Run、回放、云同步 opt-in、通断状态与统计 |
| H 日志与文件 | B、F | NOT VERIFIED | 结构化事件、受管 Explorer、传输记录及网络服务 |
| I 全局菜单 | B、D–H | NOT VERIFIED | 逐项检查 Feature、深链接、旧导航与交付配置 |
| J 集成验收 | C–I | NOT VERIFIED | 完整回归、真实 Electron 截图、Installer、Portable、升级、重启、校验和均待验收 |

## 安装和启动的验证记录

- Windows NSIS 与 Backend 定向验证：`pytest -q tests/test_installer_build.py tests/test_electron_runtime.py`，55 passed，含 NSIS include 编译。
- Electron Backend 管理器和启动页：两个 Vitest 文件共 36 passed，Electron typecheck 通过。
- 截图中的 `last_stage_elapsed=1065.032ms` 来源于子进程累计时钟。它只能定位到两个已上报事件之间，不能从该数值确定现场是数据库锁、磁盘慢或依赖缺失。需要相同安装环境的阶段日志来关闭此问题。
- L4 共享契约涉及 Desktop 生命周期、安装事务、DataRoot 和 API 组装。写入端为 Backend 阶段协议，读取端为 Electron Main 和启动页。未改协议字段、Schema、业务路径或恢复流程。主仓库只有一个已注册工作树。集成后需复跑 architecture-guards、electron-contract、main-contract-smoke、python-full、renderer-full。
- 工作区布局检查发现 6 项历史例外，用户确认保留并允许在规范路径生成本专项产物。此次测试使用隔离测试根。
- 发布状态为未发布，生产数据修改 0，删除数据库 0。
