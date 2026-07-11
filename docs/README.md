# NetConsole 文档入口

本文档目录面向后续人工开发和 Codex 维护。开始任何非简单改动前，优先阅读本页列出的约定文档。

## 必读顺序

1. [项目概览](PROJECT_OVERVIEW.md)
2. [分层架构](ARCHITECTURE.md)
3. [开发规则](DEVELOPMENT_RULES.md)
4. [Job Center](JOB_CENTER.md)
5. [架构迁移地图](REFACTOR_MAP.md)
6. [AP Identity 工具](AP_IDENTITY.md)
7. [轨旁 AP Identity 只读接入评估](TRACKSIDE_AP_IDENTITY_ASSESSMENT.md)
8. [MR/Mesh AP Identity Resolver Shadow 评估](MR_MESH_AP_IDENTITY_ASSESSMENT.md)
9. [开发约定](DEVELOPMENT_CONVENTIONS.md)
10. [UI 线程全局规范](ui_thread_policy.md)
11. [存量例外与新增代码约束](ui_governance_guardrails.md)
12. [后台任务规范](background_task_policy.md)
13. [导出进程规范](export_process_policy.md)
14. [Codex 工作流](CODEX_WORKFLOW.md)
15. [UI 表格与全选框规范](ui_table_guidelines.md)
16. [MR 原始 MESH 日志分析规则](mr_mesh_log_analysis_rules.md)
17. [功能模块说明](FEATURE_MODULES.md)
18. [数据目录规范](DATA_LAYOUT.md)
19. [轨道交通业务规则](RAIL_TRANSIT_RULES.md)
20. [构建与发布](BUILD_AND_RELEASE.md)
21. [第三方依赖说明](THIRD_PARTY_DEPENDENCIES.md)
22. [开发历史](DEVELOPMENT_HISTORY.md)

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
