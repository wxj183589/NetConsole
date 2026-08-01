# 轨道交通基础资料组件

`TracksideApPlanningTab.vue` 是轨旁 AP 规划的唯一 Renderer 入口，也是完全受控组件。它只接收 `modelValue / stations / readonly / saving`，发出 `update:modelValue / validation-change / request-generate-stations`；服务端快照、完整编辑草稿、脏状态和统一保存均由父级基础资料页面持有。

组件不得读取规划 API、复制父级草稿或服务端基线、维护独立 dirty/锁状态、轮询保存任务、发出独立保存事件。规划关系只以 `station_id` 为键；历史缺失、歧义或失效 ID 的行保留在待关联区，由用户选择正式站点或删除。IP 只作只读参考，Renderer 不提供地址生成、重算或校验；规划数据不再提供模板导入、模板下载或当前导出入口。
