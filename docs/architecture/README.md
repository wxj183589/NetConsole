# 架构专题

## 用途与边界

本目录维护当前 Electron Desktop + Vue Renderer + FastAPI/Python Core 架构的专题规则。总体分层以 [当前架构](../ARCHITECTURE.md) 为入口；历史迁移映射只在 [归档](../archive/README.md) 中保存。

## 主要入口

- [Desktop](./DESKTOP.md)：Electron Main/Preload、Backend 生命周期、窗口、托盘和日志。
- [Renderer Runtime](./RUNTIME.md)：唯一 Vue Renderer、FastAPI、REST/WebSocket 和 Browser 开发诊断。
- [Native Bridge](./NATIVE_BRIDGE.md)：受控文件、终端、通知和本机动作白名单。
- [Feature Modules](./FEATURE_MODULES.md)：Feature Registry 与模块状态表达。
- [Architecture Compliance](./COMPLIANCE.md)：分层、Guard、迁移分类和发布阻塞规则。
- [Refactor Map](./REFACTOR_MAP.md)：当前技术债务、永久入口与集成门。
- [External Tools](./EXTERNAL_TOOL_COLLECTION.md)：第三方工具注册与受控启动。
- [Storage Authority And Lifecycle ADR](./ADR-storage-authority-and-lifecycle.md)：全局存储分类、authority、owner、No-Reinflation 与生产边界。

## 依赖关系

架构文档以生产代码、Feature/Navigation Registry、构建配置、测试和 Guard 为事实源，不独立授权跨层依赖或兼容入口。

## 数据与状态

本目录不保存运行数据、设备回显或构建产物。模块状态必须区分自动化、Electron 人工、真实设备/局点和正式制品证据。

## 测试与修改

修改架构契约后运行 Change Impact、相关消费者测试、架构 Guard 和 Markdown 链接检查；L3/L4 在最终集成提交重新验证。

## 生成与清理

扫描报告和一次性阶段记录不进入活动架构目录；可恢复过程由 Git 保存，必要冻结证据进入受控归档。

## 相关文档

目录内文档描述当前约束，不维护阶段计划、兼容跳转或迁移流水账。修改架构事实后同步代码、机器可读配置、测试和文档索引。
