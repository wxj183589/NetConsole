# 轨道交通基础资料组件

`TracksideApPlanningTab.vue` 是轨旁 AP 规划的唯一 Renderer 入口。它复用现有规划查询、导入预览、导出和 Task Center，仅维护编辑区状态；正式保存由父级基础资料页面统一提交到 Python Application Service 的 revision + transaction 接口。

组件不得复制规划 DTO、数据库规则或 IP/VLAN 校验。页面锁定时所有写操作禁用，导出和任务查看保持可用。
