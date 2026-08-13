# 配置采集页面

本目录呈现配置快照、差异、批量采集和导出状态。采集、原始文本、数据库和后台任务全部由 Core/Job Center 管理，页面只负责交互和状态绑定。

主要入口为 `ConfigCollectionView.vue`、`configDiff.ts` 和 `configDiffAdapter.ts`。页面只把后台结果适配为共享模型；只读 Monaco、工具栏、导航、结构化明细和降级统一位于 `apps/desktop_renderer/src/components/config-diff/`。

快照、结构化双栏 Diff 和代码面板只消费 `theme/` 的面板与代码语义 Token；Monaco 通过全局主题事件切换 `vs` / `vs-dark`。新增 Diff 状态不得在页面内写固定色值。

当前勾选恰好两条快照时，勾选项直接作为可见左右对比对；勾选超过两条只禁用对比和差异导出，仍允许批量 ZIP 与删除。切换设备、快照类型或刷新会清空不可见勾选，手工“设为左/右”可保留跨设备对比。正文裁剪、空/相同文件处理和 Diff 计算由 Python 完成，Vue 不读取本机路径；任务列表只轮询轻量结果，focused 终态差异会通过单任务详情加载完整左右正文、结构化行和 raw diff；Monaco 失败时保留同一完整详情的结构化明细。当前裁剪是首个 `#` 到最后 `return`，不是 `display version` 到末尾 `#`；页面也没有左侧树收起控件。

完整业务与验收边界见 [配置采集与快照对比](../../../../../docs/device-management/CONFIG_COLLECTION.md)。
