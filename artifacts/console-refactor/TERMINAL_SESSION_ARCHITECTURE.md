# Terminal Session Architecture

```text
Vue/xterm
  -> POST /api/terminal/sessions
  -> one-time ticket
  -> /ws/terminal/{session_id}
  -> TerminalSessionManager
  -> existing DeviceRepository + SiteManager + credential resolution
  -> Paramiko invoke_shell OR direct Telnet IAC transport

Automation jobs
  -> existing bounded Job Center execution
  -> shared Netmiko connection adapter
```

## 会话约束

- 状态：CREATED、CONNECTING、CONNECTED、RUNNING、DISCONNECTED、RECONNECTING、CLOSING、CLOSED、FAILED、CANCELLED。
- 状态迁移由显式迁移表验证；终态拒绝 ticket、resize 和输入。
- 全局最多 8 个活动会话；同一设备最多 2 个。旧版 Electron 是本机单用户进程，因此全局限制同时构成本机用户限制。
- WebSocket 断开只卸载该前端 listener，不自动删除录制，也不影响其他会话。
- 关闭 UI 标签后可从会话树重新附着；每个活动会话保留最多 1,000,000 字符的内存显示缓冲，用于恢复标签关闭期间的已净化输出，不写入新的凭据事实源。
- 重连创建新 Session ID，保留旧会话历史，避免覆盖审计链。
- 控制台 transport 与自动化 Netmiko 连接对象相互独立；终端断开不会关闭后台任务，后台任务也不会取得 Shell Channel。
- 运行中的设备级自动化写任务通过共享审计资源键显示在会话状态中，但不会静默接管或覆盖人工输入。

## 生命周期

Backend lifespan 创建 manager，并在退出时请求关闭活动会话、等待线程和录制收尾。连接错误只向前端返回稳定错误码，不返回凭据或原始异常文本。
