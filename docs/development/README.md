# 开发专题规则

本目录维护仓库布局、Web/Electron 对等迁移和 API 边界等工程规则。它补充 `AGENTS.md` 与 `docs/DEVELOPMENT_RULES.md`，不替代生产代码和测试事实。

修改规则时同步索引、相关 Skill/测试和相对链接；不得新增与当前架构冲突的旧目录或运行入口。

## 用途与边界

本目录维护仓库布局、API 边界、对等迁移和开发流程专题规则，补充但不替代 `AGENTS.md`、`docs/DEVELOPMENT_RULES.md` 和生产测试。

## 主要入口

`repository-layout.md` 约束目录和数据，`parity/` 保存历史规格，`api-boundary-wave-1/` 保存 API/Application 边界专题。

## 依赖关系

规则以代码、测试、构建脚本和 Git 事实为来源，并由项目 Skill/质量测试消费；文档不可引入与架构 Guard 冲突的例外。

## 数据与状态

本目录是版本化 Markdown 规则，不保存运行数据、设备回显或构建产物；历史规格须标明冻结/兼容状态。

## 测试与修改

修改规则后运行 `tests/test_project_docs_layout.py`、相关质量/架构测试和 Markdown 链接检查，并同步索引与受影响 Skill。

## 生成与清理

规则文档不生成业务文件；审计临时报告放临时目录，历史归档不能因清理任务被静默删除。

## 相关文档

参见 [项目文档索引](../README.md)、[开发规则](../DEVELOPMENT_RULES.md) 和 [仓库目录规范](repository-layout.md)。
