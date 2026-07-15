# Desktop Native Bridge 契约

## 当前状态

Desktop Native Bridge 当前为 `NOT_STARTED` 契约，只定义后续 Electron 替代 Qt 桌面外壳时可用的本机能力和安全边界。本轮没有新增 Electron、Router、Service 或可调用 API，Browser/Server Mode 仍不得访问桌面文件选择器、目录或外部程序。

## 允许的宿主条件

未来实现必须同时满足：

- `RuntimeMode.DESKTOP`；
- 请求来自 `127.0.0.1`；
- 已通过 Desktop WebHost 的短期 HttpOnly Cookie；
- 对应 Feature Gate 已启用；
- 动作属于固定白名单并写入脱敏审计。

## 动作白名单

- `selectFile`
- `selectDirectory`
- `openArtifact`
- `openFolder`
- `launchTerminal`
- `notification`

请求只能携带 `device_id`、`artifact_id`、`site_id`、`directory_kind` 等业务标识。宿主从既有 Application Service、SettingsStore 或 PathResolver 解析实际对象，不信任页面提供的本机路径。`openFolder` 只打开受控目录类型，`launchTerminal` 只允许已登记终端及由服务端生成的连接参数。

WinSCP、IPOP 和其他外部工具不在初始白名单内；如未来确有业务需要，必须单独立项、安全评审并显式修改本契约，不能通过通用工具启动接口绕过。

## 永久禁止的输入

- 任意命令、PowerShell/cmd 文本或 `shell=True`；
- 任意 executable、绝对路径、数据库路径或 URL；
- 浏览器拼接的终端参数、工具参数或设备命令；
- 绕过 Registry 的未知终端、未知目录类型或未知 Artifact；
- 通用 `execute(command)`、任意 `open(path)` 或任意 `run(exe)`。

Native Bridge 只承担 Electron 桌面宿主动作，不复制设备、文件、配置、Traffic、Online MR 或 Mesh 业务 Service。实现前必须另行建立 DTO、Feature、路径归属/参数白名单测试和 Electron/Browser/Server 模式隔离测试。
