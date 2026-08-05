# 外部终端白名单

NetConsole 只支持系统设置中登记的 SecureCRT、Xshell 和 PuTTY。Renderer 仅提交语义终端类型，不能提交任意程序、参数、扩展名或 allowlist。

| 终端类型 | 允许的 executable basename | 比较规则 |
| --- | --- | --- |
| SecureCRT | `SecureCRT.exe` | 不区分大小写 |
| Xshell | `Xshell.exe` | 不区分大小写 |
| PuTTY | `putty.exe`、`putty64.exe` | 不区分大小写 |

Electron Main 根据共享定义生成仅限 `exe` 的原生文件过滤器，并在选择后复验绝对路径和 basename。文件过滤器不是安全边界；FastAPI 保存配置和 Python 实际启动前仍通过 `settings_tool_validation.py` 验证路径存在、指向普通文件、不是符号链接且 basename 与终端类型匹配。`.lnk`、`.bat`、`.cmd`、`.ps1`、PuTTYgen、Plink、PSFTP 及其他任意程序均拒绝。

已有 `PuTTY64.exe`、`PUTTY64.EXE` 等配置按大小写不敏感规则继续有效，保存时保留用户选择路径的原始写法。新增终端类型时必须同时更新共享 Bridge 定义、Python 白名单、原生选择器测试、系统设置测试和本目录，不得只在 Vue 页面增加文件名判断。

外部终端真实启动仍使用既有 Python Desktop/Application Service 和 `shell=False` 参数链；本规则不改变通用设备连接协议、设备命令或密码传递策略。AC/FIT-AP 行菜单是独立业务入口，固定由后端生成 Telnet 23 连接参数，并强制不传递 FIT-AP 用户名和密码。

设备管理通用链路先调用 `POST /api/device-management/external-terminal/preflight`。预检只根据设备 UUID 构建并校验白名单启动描述，返回可启动 UUID 与有界不可用原因，不启动进程、不返回程序参数或凭据；确认后才调用批量启动接口。设备管理页和轨旁 AP 业务页共用该前端协调逻辑，并在请求进行中拒绝重复提交。轨旁 AP 业务投影只把精确解析到设备管理记录的交换机/AP `device_uuid` 交给预检，不把 FIT-AP `ap_uuid`、名称或 MAC 当作启动目标。

上述通用设备终端与 AC/FIT-AP 固定 Telnet 入口是两套明确边界：轨旁页面找不到独立 AP 设备管理记录时菜单保持禁用，不继承 AC 的地址或凭据，也不回退打开 AC；AC/FIT-AP 页面仍按既有固定 Telnet 23 规则运行。
