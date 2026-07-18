# Core 基础能力

本目录承载版本、Feature Registry、PathResolver、运行环境、数据库基础、日志、清理和共享 ViewModel 等跨域基础能力。它不应依赖 Web/Electron UI。

主要事实源包括 `version.py`、`feature_registry.py` 和 `paths.py`；运行数据遵守系统应用数据根。修改核心边界后运行路径、Feature、数据库和依赖层测试。


## 用途与边界

本目录承载版本、Feature Registry、PathResolver、运行环境、数据库基础、日志、清理和共享 ViewModel 等跨域基础能力；不依赖 Vue、Electron UI 或具体领域 Router。

## 主要入口

`version.py` 是版本事实源，`feature_registry.py` 是用户可见能力注册，`paths.py`/runtime environment 是数据路径入口；子目录提供 MR/Ping/来源辅助。

## 依赖关系

Core 被 Application、Service、Repository、Backend 和构建脚本共同使用；路径/版本/Feature 的消费者必须通过公开 helper，不复制常量。

## 数据与状态

PathResolver 生成系统应用数据根、局点 DB、runtime、缓存和会话目录；Core 只定义边界，具体业务数据由 Repository/Service 管理。

## 测试与修改

运行 paths、Feature、database、logging、cleanup 和依赖层测试。修改版本、Feature key、路径或基础状态时同步所有消费者和 docs。

## 生成与清理

运行时目录由 PathResolver/ensure helper 创建；清理必须使用维护 Service 的白名单/dry-run 机制，不递归删除未知数据库、原始日志或报告。

## 相关文档

参见 [数据与路径](../../../docs/DATA_LAYOUT.md)、[功能模块](../../../docs/FEATURE_MODULES.md) 和 [永久架构](../../../docs/ARCHITECTURE_NEXT.md)。
