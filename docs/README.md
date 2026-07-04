# NetConsole 文档入口

本文档目录面向后续人工开发和 Codex 维护。开始任何非简单改动前，优先阅读本页列出的约定文档。

## 必读顺序

1. [项目概览](PROJECT_OVERVIEW.md)
2. [开发约定](DEVELOPMENT_CONVENTIONS.md)
3. [Codex 工作流](CODEX_WORKFLOW.md)
4. [功能模块说明](FEATURE_MODULES.md)
5. [数据目录规范](DATA_LAYOUT.md)
6. [轨道交通业务规则](RAIL_TRANSIT_RULES.md)
7. [构建与发布](BUILD_AND_RELEASE.md)
8. [开发历史](DEVELOPMENT_HISTORY.md)

## 现有编号文档

仓库还保留了早期编号文档：

- `01-product.md`
- `02-architecture.md`
- `03-device-management.md`
- `04-database.md`
- `05-runtime-paths.md`
- `06-roadmap.md`
- `07-windows-server-test-checklist.md`
- `08-project-rules.zh.md`
- `08-project-rules.en.md`

这些文档可作为历史和补充参考。若与本次新增专题文档冲突，优先以当前代码和专题文档中的“当前实现”说明为准，并在后续任务中统一更新旧编号文档。

## 文档维护原则

- 只把已确认的长期规则写成约定。
- 一次性修复说明不要沉淀成永久规则，除非用户明确确认。
- 不写真实账号、密码、现场专有数据或截图里的样例作为规则。
- 内网 IP 如需示例，必须标注为示例或调试环境。
- 当代码和历史文档冲突时，先标注“当前实现与待统一事项”，不要在文档任务里顺手改业务代码。
