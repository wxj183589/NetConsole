# NetConsole v1.5.19 Console 专项验收

## 2026-11-27 Console 专项续作四

终端设置首屏与规则请求解耦，规则表按页签和分页挂载，配置服务复用未变化的文件版本。真实 Electron 记录了首次与重复打开、页签切换及录制搜索，测量条件见[续作四性能报告](./CONSOLE_SETTINGS_REPLAY_20261127.md)。会话回放支持普通文本关键字搜索、匹配计数、循环定位和 ANSI 基础色。真实隔离 SSH 录制的 LOG、ZIP、JSONL 搜索前后 SHA-256 一致。

Full Gate、冻结 Worker、NSIS 和 Portable 本轮未生成。工作树仍有旧的 `node_modules/.vite/vitest` 缓存，Workspace Layout 检查失败。现有 Python 3.13 构建虚拟环境已通过锁定依赖检查。实际 Telnet/COM 并发设置场景待验收。

状态：PARTIAL。产品分支 `codex-A/organization-task-network-services-phase6`，已推送起点 `bd42e924`，当前续作尚未提交。

| 项目 | 状态 | 实际结果 |
| --- | --- | --- |
| 实验室 AC SSH | PASS | `192.168.56.2` 登录，一次 Enter 执行 `display version`，返回 Comware 7.1.064 Alpha 7165 |
| 实验室 FIT-AP Telnet | PASS | `192.168.56.4` 使用仅密码认证，一次 Enter 执行 `display version` 并返回设备版本 |
| 实验室 SW SSH | BLOCKED | `192.168.56.3:22` 可达，设备拒绝所提供的认证 |
| Electron 标签和分屏 | PASS | 关闭 AC、FIT-AP 任一标签后另一会话仍在线；关闭最后一条后活动会话列表为空，应用退出后所属进程和测试端口已释放 |
| Electron 截图 | PASS | 实际窗口 1920×1080、2560×1440，证据位于 Workspace 的 `reports/diagnostic/phase8-real-replay/pages/`，前缀 `phase8-console-59d7a397` 和 `phase8-console-panels-90d32c7d` |
| 外部终端 | PARTIAL | 本机 PATH 检出 Windows OpenSSH。此前隔离 SSH 服务已验证该客户端；SecureCRT、PuTTY、Xshell 实际启动及认证待验收 |
| 管理与批量命令 | PARTIAL | 默认仅显示管理按钮。向 AC 和 FIT-AP 批量发送 `display clock` 后，各窗格显示各自设备时间。支持保存命令查询、按会话查看写入状态及取消。批量输出汇总与导出、暂停和可配置超时待实现 |
| 输入与会话扩展矩阵 | PARTIAL | SSH 原样转发、Telnet CRLF、拆分 CRLF 和关闭并发有专项回归。真实界面的全部控制键、多行粘贴、备用地址及重连组合待验收 |
| 规则文件 | PARTIAL | 旧 Portable 缺少两个默认 JSON。修复资源清单和白名单后，实际 Electron 面板与冻结 API 均显示 22 条高亮规则、226 条高危命令规则。历史数组和编码、导入及错误诊断有专项测试，真实界面导入导出待验收 |
| 终端设置与保存连接 | PARTIAL | 已登记设备可用备用地址及已配置的外部终端。保存连接的备用地址字段及外部启动仍待实现。完整终端设置矩阵待验收 |

## 2026-11-26 Console 功能续作

映射按钮栏现可收起/展开、切换已保存按钮组并在栏内执行 Send String。Menu Function 复用当前 TerminalPane 已有的查找、全选、清屏及清除滚动缓冲区动作。Run Script 使用版本化 JSON DSL，只支持 Send String 和等待步骤，最多 100 步、单步等待不超过 60 秒、累计等待不超过 10 分钟；脚本经确认后顺序调用现有批量 Session API，显示设备输出、支持停止，页面卸载时请求取消。Launch Application 只允许引用已经登记的 External Tool ID，并复用 Electron 现有启动服务。

本轮定向结果为 Renderer Console 42 项、Electron IPC/Preload 44 项、Python Console API/Service 19 项通过；Ruff、Renderer 类型检查、Electron 类型检查和 Renderer/Electron 构建通过。证据日志和隔离 Electron 截图位于 Workspace `reports/tests/console-1.5.19-resume-20261126/`。真实 Electron 采集到 1920×1080 和 2560×1440 分屏、窄窗口及按钮栏截图。现有复合视觉脚本在 SFTP 文件行选择器超时退出，该 SFTP 检查未通过，本轮截图不作为 SFTP 验收证据。

该段记录的是本节开始前的历史状态。后续“Console 专项续作二”记录了 schema version 2、会话上下文模板及本轮更新后的 GUI 验收结果。外部客户端认证矩阵、原生文件对话框/拖放和完整真实键盘/粘贴矩阵仍待完成。

### Console 专项续作二

按钮栏配置已升级为 schema version 2。Backend 首次读取旧版配置时保留原按钮及顺序，补齐新字段并原子写回；Renderer 导入也兼容 v1 并规范化为 v2。用户在已登记 External Tool 的参数中配置 `{host}`、`{address}`、`{backup_host}`、`{backup_address}`、`{port}`、`{username}` 或 `{password}` 模板，并在映射按钮启用“传递当前会话参数”后，Main 进程从登记参数生成最终 argv。Renderer 只能发送固定且限长的终端上下文 DTO，不能传任意 argv。配置包含 `{password}` 时点击按钮会单独提示密码，用户授权的明文参数仅用于本次外部进程启动；启动日志、按钮配置和 Session 录制元数据不保存密码或用户名，进程使用 `shell: false`。

本次固定 DTO 改造后的定向回归为 Renderer Console/API 31 项、Electron External Tool/IPC 18 项、Python Console/Session 26 项通过；Renderer 与 Electron 类型检查及 Python Ruff 通过。覆盖 v1 配置自动迁移、固定上下文 DTO 校验、中文/空格参数模板展开、密码临时提示以及日志和存储不泄漏密码。实际 Electron 复合验收通过隔离 SSH/SFTP 列表与下载、映射按钮、批量写入、独立会话标签和窗口、80 次页面切换及生命周期；证据位于 Workspace `reports/tests/console-1.5.19-resume-20261126/electron-sftp-fix-20261126/`。2560×1440 实际显示器验收 PASS，1920×1080 仅验证窗口尺寸。原生 Windows 文件对话框、Explorer 拖放和外部真实终端客户端认证仍未验证。

### Console 专项续作三：中文化、设置性能与串口

Console 自有映射按钮、按钮管理、脚本、终端右键菜单、SFTP 面板及状态文案接入现有 i18n。终端设置复用已缓存的设置与规则，危险命令规则按需读取，失败显示错误和重试入口，并记录弹窗、读取、表单渲染、保存和 Renderer long-task 性能指标。

串口使用锁定的 pySerial 3.5，由 Python Backend 的 `TerminalSessionManager` 管理 `SerialInteractiveTransport`，与 SSH/Telnet 共用会话、WebSocket、xterm.js、终端标签、分屏、录制和关闭生命周期。串口 API 包含端口枚举、会话开关、文本/字节收发、接收缓冲、模式等待、flush、cancel 和配置模板导入导出。新会话默认 H3C Console `9600 8N1`、无流控、UTF-8、CR、关闭本地回显及 DTR/RTS 保持原状态。当前批量命令不发送到串口。

本轮定向结果为 Python 串口/Session 32 项、Renderer 38 项、Electron 328 项、PyInstaller artifact inventory 22 项通过，Electron TypeScript 检查通过。新串口 Service 和测试的定向 Ruff 检查通过。SBOM 定向测试组合中 9 项因环境缺少 `pyftpdlib` 失败；完整运行时锁定环境检查也未通过，现有 Python 环境 FastAPI、python-multipart、matplotlib、tzdata 版本与 constraints 不符，并缺少 Jinja2、pyftpdlib、pyOpenSSL、XlsxWriter、pip-licenses、cyclonedx-bom；没有安装或替换环境依赖。pySerial 3.5 已在 `constraints.txt` 和 PyInstaller 批准分发清单中，但本轮未重新构建冻结 Worker、NSIS 或 Portable。真实 Electron 在混合 SSH 标签和分屏中验证了 COM 窗口、H3C 默认值、系统端口枚举和终端设置反复开关。设置弹窗连续重开 30 次，实测中位数 28 ms、范围 24–32 ms；外壳测量 6–44 ms，缓存设置读取 0 ms，表单渲染 6–43 ms（常见 6 ms），采集到的 Renderer long-task 合计 0 ms。上述结果和截图位于 Workspace `reports/tests/console-1.5.19-resume-20261126/console-serial-electron-20261126/`。

环境枚举到 COM3/COM4，描述均为 Microsoft 蓝牙串口。本轮没有打开这些端口，也未进行 USB 串口硬件通信；真实设备收发、拔插、占用冲突、实际 Windows DTR/RTS 电气状态及硬件断连处理保持 NOT VERIFIED。`node_modules/.vite/vitest` 生成缓存导致 Workspace Layout 检查失败，精确清理请求被自动审查拒绝；构建环境锁定检查也失败。因此冻结 Worker、NSIS、Portable 重建及包级 pySerial 收集验收为 NOT RUN。现有 v1.5.19 包证据不能代表本轮代码。

架构与参数说明见[串口会话架构与参数](./CONSOLE_SERIAL_TRANSPORT.md)，设置性能数据见[终端设置性能报告](./CONSOLE_TERMINAL_SETTINGS_PERFORMANCE_20261126.md)。

数据影响：仅使用 Workspace 隔离 Console 测试根。`PRODUCTION_DATA_MODIFIED=0`、`DEV_REAL_BUSINESS_DATA_MODIFIED=0`、`DATABASES_REMOVED=0`、`REAL_DEVICE_CONFIGURATION_WRITES=0`。

实验室授权变更：AC 进入 `probe` 后执行 `wlan ap-execute all exec-console enable`，随后 FIT-AP Telnet 连通。未执行保存配置，也未验证重启后的状态。

## 集成验证与候选制品

源码与候选绑定 `39eaa4ac6e7e1b86d2918d38b5049cfdf8a60198`，版本为 1.5.19，`BUILD_DIRTY=false`，发布状态为 unpublished。Full Gate PASS，Python 5,901 通过、3 跳过，Renderer 1,622、Electron 326、架构 12/12，冻结规则 smoke PASS。日志为 Workspace 的 `reports/tests/console-39eaa4ac-full-gate.log`。

| 制品 | SHA-256 |
| --- | --- |
| `NetConsole-Full-1.5.19.0-39eaa4ac-x64-setup.exe` | `dfa4a64c39a16b6f0faa95f3ef8622ecf2af6acf32b70859bbff8eb86ec9ff61` |
| `NetConsole-1.5.19-portable.zip` | `a0bd25f84f4bdd492b1fa37d495a6d95e00f8579516cc794c1449e7ca4dd6dae` |

候选位于 Workspace 的 `temp/build/phase8-final-package/build-39eaa4ac-20261126-141420/candidates/`，验证记录见 `reports/build/phase8-final-package-build-39eaa4ac-20261126-141420/`。两包的 CycloneDX 1.5 SBOM 均有 68 个组件。Portable 使用中文空格程序路径和全新外部 DataRoot，Renderer 就绪 5.188 秒，冻结 Worker、正常退出与端口重绑通过。NSIS 包级 smoke 通过，Windows 安装、升级、卸载和回滚现场验收仍为 NOT VERIFIED。

`PRODUCTION_DATA_MODIFIED=0`、`DEV_REAL_BUSINESS_DATA_MODIFIED=0`、`DATABASES_REMOVED=0`、`REAL_DEVICE_CONFIGURATION_WRITES=1`（授权实验室 AC）、`MAINTENANCE_AUTHORIZED=NO`（生产维护）。
