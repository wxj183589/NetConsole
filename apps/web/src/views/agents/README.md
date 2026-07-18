# Agent 管理页面

本目录展示 Windows Go Agent 列表、健康状态和受控配置入口，不在 Renderer 保存 Token 或执行任意命令。

主要入口是 `AgentListView.vue`；数据通过 Agent Controller API/Store 获取。修改状态或认证展示时运行 Web 测试，并同步 Controller 契约。

Agent 列表、远端工具、远端任务和采集包 4 张表统一使用 `NcDataTable`；路径、提示和错误列明确左对齐，其他字段默认居中。列布局属于本机视图偏好，不写 Agent 配置或 Controller 数据库。
