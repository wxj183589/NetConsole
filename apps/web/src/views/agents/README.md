# Agent 管理页面

本目录展示 Windows Go Agent 列表、健康状态和受控配置入口，不在 Renderer 保存 Token 或执行任意命令。

主要入口是 `AgentListView.vue`；数据通过 Agent Controller API/Store 获取。修改状态或认证展示时运行 Web 测试，并同步 Controller 契约。
