# 测试支持代码

本目录提供 Fake Online MR Agent、API 辅助和共享 fixture 构造，供测试模拟外部服务和事件流。这里不放生产逻辑，也不使用真实凭据或设备地址。

主要入口为 `fake_online_mr_agent.py` 与 `online_mr_api.py`；修改 fake 状态机或响应 DTO 时运行 Online MR、Agent 和 Web API 测试。
