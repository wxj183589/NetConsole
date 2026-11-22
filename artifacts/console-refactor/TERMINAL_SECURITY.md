# Terminal Security

## 已实现

- IMPLEMENTED：Ticket 随机、短期、一次性、与 Session ID 绑定。
- IMPLEMENTED：WebSocket 仅允许 loopback Host/Origin；限制消息大小。
- IMPLEMENTED：设备凭据只在后端通过现有 Device Repository/DPAPI 路径解析，不进入 REST 响应、Ticket、URL 内容、录制元数据或导出。
- IMPLEMENTED：控制台没有 `RESTRICTED_READONLY`、命令白名单或命令改写；xterm 输入原样进入交互 transport。
- IMPLEMENTED：高危命令附件规则只生成非阻断提醒和审计事件，提示后仍发送原始命令。
- IMPLEMENTED：Ctrl+C、Ctrl+D、Backspace、Tab、方向键和 ANSI 序列直接交给设备 CLI。
- IMPLEMENTED：输出经过既有敏感信息 sanitizer 后才广播和录制。
- IMPLEMENTED：会话 ID 目录进行格式和越界校验；导出文件名净化。

## 尚未验证

- MOCK_VERIFIED：非法 Origin、Ticket 单次消费和过期 Ticket；浏览器级安全 E2E 尚未完成。
- 真实 SSH 指纹变化与 Site Relay 隔离沿用旧版能力，本轮没有现场验证。
- 人工控制台允许设备 CLI 正常进入配置模式；自动化写任务继续使用设备级互斥和独立 Netmiko 连接。
