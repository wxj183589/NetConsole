# Desktop Native Bridge 契约

## 当前状态

Desktop Native Bridge 当前为 `NOT_STARTED` 契约，只定义后续 Web 替代 Qt 时可用的本机能力和安全边界。本轮没有新增 Router、Service 或可调用 API，Server Mode 仍不得访问桌面文件选择器、目录或外部程序。

## 允许的宿主条件

未来实现必须同时满足：

- `RuntimeMode.DESKTOP`；
- 请求来自 `127.0.0.1`；
- 已通过 Desktop WebHost 的短期 HttpOnly Cookie；
- 对应 Feature Gate 已启用；
- 动作属于固定白名单并写入脱敏审计。

## 动作白名单

- `select_file`
- `select_files`
- `select_directory`
- `open_controlled_directory`
- `open_controlled_artifact`
- `launch_registered_terminal`
- `launch_registered_tool`
- `show_native_notification`

请求只能携带 `device_id`、`artifact_id`、`registered_tool_id`、`site_id`、`directory_kind` 等业务标识。宿主从既有 Repository、SettingsStore 或 PathResolver 解析实际对象，不信任浏览器提供的本机路径。

## 永久禁止的输入

- 任意命令、PowerShell/cmd 文本或 `shell=True`；
- 任意 executable、绝对路径、数据库路径或 URL；
- 浏览器拼接的终端参数、工具参数或设备命令；
- 绕过 Registry 的未知工具、未知目录类型或未知 Artifact。

Native Bridge 只承担桌面宿主动作，不复制设备、文件、配置、Traffic、Online MR 或 Mesh 业务 Service。实现前必须另行建立 DTO、Feature、直接 URL/任意路径拒绝测试和 Desktop/Server 模式测试。
