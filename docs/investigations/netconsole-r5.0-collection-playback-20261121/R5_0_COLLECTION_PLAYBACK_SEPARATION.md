# 采集与回放分离

`GroundUnattendedView.vue` 新增一级工作区切换：

- 实时采集：保留原控制按钮、运行状态、采集页面和原有上下文。
- 历史回放：由 `GroundHistoryPlayback.vue` 提供 Site、线路、运行、列车/MR、时间范围与显式查询。

进入历史回放只渲染组件，不自动查询，也不启动任何采集。组件只导入 `getGroundMrMonitoring` GET API；首次查询必须由用户点击“查询回放”触发。切换工作区不会调用停止接口，因此不影响既有实时任务。

Site 与线路显示当前 Backend 注册上下文，不允许在回放页面暗中切换 DataRoot 或激活其他 Site。运行选择用于设定历史时间上下文；多源证据按实际时间戳对齐，不用单一采集 run_id 强行裁掉 `heartbeat-resident` 数据。

隔离测试 `GroundHistoryPlayback.test.ts` 断言进入页面时查询调用次数为 0。
