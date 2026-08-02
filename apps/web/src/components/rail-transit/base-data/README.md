# 轨道交通基础资料组件

`TracksideApPlanningTab.vue` 是轨旁 AP 规划的唯一 Renderer 入口，也是完全受控组件。它只接收 `modelValue / stations / editing / readonly / saving`：`editing=false` 使用纯文本和状态标签，不渲染选择、输入、增删或生成入口；`editing=true` 才发出 `update:modelValue / validation-change / request-generate-stations`。服务端快照、规划子页草稿、脏状态和作用域保存由基础资料页面中的规划编辑上下文持有；其他子页拥有各自独立的编辑上下文，不能共用锁或草稿。

组件不得读取规划 API、复制页面级编辑上下文或服务端基线、私自维护第二套 dirty/锁状态、轮询保存任务。规划关系只以 `station_id` 为键；历史缺失、歧义或失效 ID 的行保留在待关联区，由用户选择正式站点或删除。IP 只作只读参考，Renderer 不提供地址生成、重算或校验；规划数据不再提供模板导入、模板下载或当前导出入口。
