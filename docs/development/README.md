# 开发文档

## 用途与边界

本目录维护跨领域工程规则；根 [AGENTS.md](../../AGENTS.md) 是 Codex 与仓库操作约束，[开发规则](../DEVELOPMENT_RULES.md) 是当前工程规则入口。生产代码、测试与机器可读 Registry 优先于说明文档。

## 主要入口

- [Change Impact Framework](./CHANGE_IMPACT_FRAMEWORK.md)：L1-L4、共享契约、消费者和合并后验证。
- [API / Application 边界](./API_APPLICATION_BOUNDARY.md)：FastAPI Router、Service、Repository 与传输职责。
- [仓库目录规范](./repository-layout.md)：源码、测试、脚本、运行数据和构建产物归位。
- [Self-hosted CI](./SELF_HOSTED_CI.md)：本地 Runner 与 CI 安全边界。
- [Codex Skills](./CODEX_SKILLS.md)：项目 Skill 路由和维护规则。

## 依赖关系

工程规则由代码、测试、构建脚本、机器可读 Registry 和项目 Skills 消费；文档不得创建与 Guard 冲突的例外。

## 数据与状态

本目录只保存版本化规则，不保存运行数据库、日志、设备回显、凭据或生成报告。

## 测试与修改

修改规则时同步相关 Guard、测试、Skills 和索引，并运行 Markdown 链接检查与直接消费者回归。

## 生成与清理

一次性 Audit、Assessment、Plan、Investigation 和已完成迁移波次不进入本目录；仍有价值的长期规则应并入以上 SSOT，必要历史证据进入受控归档。

## 相关文档

参见 [文档索引](../README.md)、[测试基线](../testing/BASELINE.md)和[当前架构](../ARCHITECTURE.md)。
