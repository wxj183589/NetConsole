# NetConsole-Next 架构映射

只读检查对象：`D:\study\NetConsole-Next-Workspace\NetConsole-Next` 当前源码，而不是历史状态报告。

| Next 思路 | 旧版实现 | 状态 |
| --- | --- | --- |
| TerminalSessionManager | Python `TerminalSessionManager` | IMPLEMENTED / MOCK_VERIFIED |
| 稳定 Session ID 与状态迁移 | 32 位随机 ID、显式迁移表 | IMPLEMENTED / TESTED |
| 一次性 WebSocket Ticket | 30 秒短期、Session 绑定、单次消费 | IMPLEMENTED / TESTED |
| Next 的命令限制 | R2 明确不移植；控制台透传原始交互输入，高危规则只提示和审计 | NOT_APPLICABLE / TESTED |
| 独立有界 JSONL 录制 | 每会话目录、2048 事件有界队列、异步 writer | IMPLEMENTED / MOCK_VERIFIED |
| 搜索、回放、导出 | 历史搜索、输出查看、TXT/JSONL | IMPLEMENTED / TESTED |
| 分屏 | Renderer 布局层，连接实例不重建 | IMPLEMENTED / BUILD_VERIFIED |
| SSH.NET / .NET Service | 不移植；旧版以 Paramiko `invoke_shell()` 建立独立交互通道 | IMPLEMENTED / ISOLATED_SERVER_VERIFIED |
| Telnet IAC/TTYPE/NAWS 专用实现 | Python 独立 Socket/IAC 状态机、登录、TTYPE、NAWS | IMPLEMENTED / ISOLATED_SERVER_VERIFIED |
| 独立 SFTP subsystem | 每个 SFTP 会话单独 SSH/SFTP 连接和有界传输任务 | IMPLEMENTED / ISOLATED_SERVER_VERIFIED |
| COM 串口 | 旧版范围/硬件证据不足 | NOT_IMPLEMENTED |
| 崩溃恢复 | 本轮未建立恢复索引 | NOT_IMPLEMENTED |
