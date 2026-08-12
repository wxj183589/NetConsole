# Windows 开发工具说明

本目录只保存开发/诊断工具的说明和受控子目录，不是主程序或 Agent 的运行时工具来源。fping/iPerf 的版本化来源以 `resources/tools/` 为准；IPOP 仅允许用户自备。

修改工具说明或子目录时检查 `resources/tools/README.md`、构建 Guard 和许可证边界。不得提交二进制运行依赖、日志或测试输出。

## 用途与边界

本目录只保存开发/诊断工具边界的说明，不是主程序或 Agent 的运行时工具来源；fping/iPerf 的版本化来源仍是 `resources/tools/`，IPOP 仅可由用户自备。

## 主要入口

`ipop/` 仅提供外部工具说明；任何运行工具探测和交付由资源/构建脚本完成，不从这里复制第二份二进制。

## 依赖关系

开发工具使用明确的本机路径或用户配置；正式产品和 Agent 依赖 `resources/tools`、Tool Path Resolver 与构建 Guard。

## 数据与状态

本目录不保存工具运行结果、日志或配置；测试和诊断结果进入 `.local/` 或临时目录，真实 IPOP 文件不得提交。

## 测试与修改

修改说明、工具来源或许可证时运行运行时工具 Guard、构建制品和相关 smoke 测试，并检查资源来源唯一性。

## 生成与清理

不在此目录生成交付包；临时工具、日志和测试输出完成后按项目维护脚本清理，不递归删除未知用户目录。

## 相关文档

参见 [工具资源说明](../../resources/tools/README.md)、[构建与发布](../../docs/release/BUILD_AND_RELEASE.md) 和 [目录规范](../../docs/development/repository-layout.md)。
