# NetConsole 文档

本文档集描述当前的 Electron Desktop + Vue Renderer + FastAPI/Python Core 产品。生产代码、测试、Feature Registry 和构建脚本优先于文档；行为变化时必须在同一改动中更新对应文档。

## Current Architecture

- [总体架构](./ARCHITECTURE.md)：当前分层、运行形态、任务、导出、数据与安全边界。
- [架构专题](./architecture/README.md)：Electron Desktop、Backend Runtime、Native Bridge、Feature 与重构地图。
- [数据布局](./storage/DATA_LAYOUT.md)：业务数据根、局点目录、运行数据与生命周期。
- [真实数据根验证](./storage/DATA_ROOT_VALIDATION.md)：Production/Dev Copy 隔离、复制流程和生命周期审计结果。

## Development

- [开发规则](./DEVELOPMENT_RULES.md)：分层、编码、数据、任务、导出与测试约束。
- [开发专题](./development/README.md)：Change Impact、仓库布局、API 边界、自托管 CI 与 Codex Skills。
- [用户文件交互](./export/USER_FILE_INTERACTION.md)：导入、导出、Artifact 保存与文件选择的永久契约。
- [导出进程](./export/PROCESS_POLICY.md)：Export Worker、临时文件、原子替换与 Artifact 规则。
- [UI 规范](./ui/README.md)：设计系统、表格、响应性和交互规则。

## Testing

- [测试基线](./testing/BASELINE.md)：风险分层、定向测试、消费者回归和完整门禁。
- [Change Impact Framework](./development/CHANGE_IMPACT_FRAMEWORK.md)：L1-L4、共享契约和合并后验证。
- [变更记录](./CHANGELOG.md)：用户可见与重要架构变化。

## Build & Release

- [构建与发布](./release/BUILD_AND_RELEASE.md)：Python Backend、Electron、NSIS、Agent 和制品验证。
- [发布专题](./release/README.md)：版本、Full/Customer、第三方依赖和正式包状态。
- [独立 Agent](./agent/README.md)：Windows Go Agent、Controller 和 Traffic API。

## Core Domains

- [设备管理](./device-management/README.md)：设备、配置采集、厂商兼容与命令参考。
- [设备文件](./device-files/README.md)：只读 SFTP、主机密钥和下载工作流。
- [Job Center](./job-center/README.md)：后台任务、Worker、状态和取消。
- [Traffic](./traffic/README.md)：fping/iPerf、本地与 Agent 执行。
- [轨道交通](./rail-transit/README.md)：基础资料、AC、轨旁 AP、MESH、Online MR、Ground 与车内通信。
- [MESH 分析规则](./rail-transit/mesh/ANALYSIS_RULES.md)：原始事实、解析、主备链、时间轴、阈值和报告语义。
- [AP Identity](./AP_IDENTITY.md)：统一身份、消费者、诊断和数据安全边界。

## Storage & Operations

- [存储与数据安全](./storage/README.md)：SQLite、备份、升级、路径和清理。
- [全局存储架构](./storage/STORAGE_ARCHITECTURE.md)：数据库/raw/Artifact/cache/staging/backup 的 authority 与 lifecycle owner。
- [存储验收](./storage/STORAGE_TESTING_GUIDE.md)：全局 inventory、功能透明、No-Reinflation 和真实 snapshot 安全边界。
- [外部终端](./external-terminal/README.md)：受控终端选择与启动。
- [逆向工程](./reverse-engineering/README.md)：协议证据等级与受控逆向资料。

## Historical Archive

[历史归档](./archive/README.md)只保存当前代码无法恢复且仍有维护价值的迁移决策或取证证据，不是当前规范、待办清单或功能授权。Qt 与早期 Browser 双轨迁移已经结束，当前产品状态以本页的活动文档、生产代码和测试为准。

## Maintenance

提交前运行 Markdown 相对链接检查、根文件 allowlist Gate 和适用的文档 Guard。活动文档不得引用已删除的 standalone Renderer 目录；除 `docs/archive/` 与 `docs/investigations/` 外，任何活动文档目录都不得新增 Assessment、Audit、Observation Plan、Migration Plan、Handoff、Status Report 或临时 Investigation 过程文件。真正的业务规划文档（例如 Trackside AP Planning）使用明确的领域名称，不按通用 `PLAN` 关键字误杀；历史迁移资料不得写成当前架构。
