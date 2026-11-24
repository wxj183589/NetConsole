# Phase 3.6 基线证据审计

2026-11-24，产品起点 `82e0ad8ed64f3685647f7220ad9e91ef2db81029`，远端 github/codex-A/rail-relationship-phase3 同 SHA；DevStatus 起点 `5d0f4628cee97b0b3be0edc651a1b96d1ba12861`，远端同 SHA。起始两工作树 clean，全部提交已推送。`76eb295a..82e0ad8e` 仅验收文档；已验收的关系实现包含在基线内。

复用原 rail-relationship-phase3 产品工作树建立 codex-A/rail-asset-safety-phase3-6；复用原 status 工作树建立对应 status 分支，不增加工作目录，不合并 main，不删除旧分支。其他 Phase 1/2/main checkout 保留。

| 证据 | 归属与结论 |
| --- | --- |
| Phase 2.5 Full Gate PASS | 历史基线；不能代替本次验收 |
| Phase 3 定向 419 PASS、Renderer 1582 PASS | 历史定向证据，详见 PHASE3_ACCEPTANCE.md |
| Phase 3 Full Gate | STOPPED，不能拼接各轮结果为 PASS |
| Phase 3 Electron | 合成局点、两种 CSS 视口、36 截图；不是现场验收 |
| 真实设备/现场/生产迁移 | NOT RUN |

已阅读 Phase 3 验收、能力审计、写入契约、历史语义，以及 Workspace reports/tests/rail-relationship-phase3 的测试/迁移/UI 报告。新任务证据独立保存于 reports/tests/rail-asset-safety-phase3-6。

## Change Impact / Consumer Audit

风险 L4：物理资产删除安全边界，未更改 Schema/DataRoot/Feature。旧 CRUD 中删除成功改为固定拒绝，是有意收紧的兼容变化；导入、新增、编辑、排除当前工作、分组删除均保留。

写入方：设备管理 token/batch API、legacy device_crud Job、Repository 单删/批删；均禁止物理资产删除。读取方：设备/工程关系、凭据、事实、Ground、AC/FIT-AP、AP Identity、MESH、Online MR、导出。预检不缓存、不写数据库/文件；旧 revision/未知源/失败均拒绝，不广播删除事件。

测试矩阵：删除安全 → 关系 → Devices/Infrastructure → Ground/AP/AC/MESH/Online MR → Architecture/main smoke/Ruff/docs。无 Renderer 修改，不新增按钮，因此本轮 Renderer/Electron 场景 NOT RUN，沿用历史证据时明确标注。未合并 main，未来合并提交仍应复验这些消费者。并行已有工作树不做迁移或清理。
