# 轨道交通基础资料组件

`TracksideApPlanningTab.vue` 是轨旁 AP 规划的唯一 Renderer 入口。站点来源只复用设备管理“站点”字段的预览与草稿应用流程；组件仅维护规划编辑区状态，正式保存由父级基础资料页面统一提交到 Python Application Service 的 revision + transaction 接口。

组件不得复制规划 DTO、数据库规则或 VLAN 分组校验。IP 只作只读参考，Renderer 不提供地址生成、重算或校验。页面锁定时只能预览设备管理站点来源，不能应用草稿；规划数据不再提供模板导入、模板下载或当前导出入口。
