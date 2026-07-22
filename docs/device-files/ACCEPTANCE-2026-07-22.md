# 设备文件下载业务流程验收记录（2026-07-22）

## 自动验收

| 场景 | 覆盖方式 | 结果 |
| --- | --- | --- |
| SSH 正常、SFTP 未启用 | Service/API 测试模拟 `SftpUnavailableError`，确认后执行 `device.sftp.enable` 并重连 | 通过 |
| Paramiko 返回 `Channel closed.` | Service/API 测试模拟原始异常并检查稳定错误码、确认令牌和页面禁显原文 | 通过 |
| H3C 拒绝后 Transport 失活 | Service/API 测试在认证成功后将 `transport.active=False`，仍分类为 `DEVICE_FILE_SFTP_UNAVAILABLE` | 通过 |
| 认证后 SFTP 协商异常矩阵 | 覆盖 `Channel closed`、`EOFError`、`SSHException`、`ChannelException` 和 H3C disabled 原文 | 通过 |
| SSH 建连阶段 EOF | 反向测试确认不触发 SFTP 自动启用，仍返回连接类错误 | 通过 |
| 五个 MESH 日志只勾选一个 | Vue 源码契约与提交模型测试检查任务只来自 `remoteSelected` | 通过 |
| “MESH 日志”只选择 | Vue 测试检查按钮仅调用选择逻辑且不存在独立下载动作 | 通过 |
| 普通文件真实落盘 | Service 测试检查真实设备目录、队列本地路径和直接打开动作；Vue 测试检查刷新及无“保存” | 通过 |
| 车载 MR MESH 归档 | Service 测试检查精确分组/Profile、raw 路由、自动导入及解析失败保留 raw | 通过 |
| 切换设备 | Vue 测试检查先断开旧连接、清空远程状态并加载新设备目录 | 通过 |
| 未知主机密钥 | API 测试检查 trust-once 后继续原连接，未启用 AutoAddPolicy | 通过 |
| 启用后重连遇到未知主机密钥 | API 测试确认信任后继续既有启用意图，不重复提交写任务 | 通过 |
| 大量无关任务 | 5000 条其他模块任务与 50 条文件任务，SQL 过滤且仅一次批量事件读取 | 通过 |
| WinSCP 特殊字符密码 | `@ : / % 空格 # 中文` 均正确 URL 编码，原始和编码密码均从安全命令移除 | 通过 |

## 执行记录

- 2026-07-23 根因修复定向验证：Python `26 + 17 + 38 + 2 + 7` 项通过；Web 全量 Vitest `96 files / 428 tests` 通过；Vue TypeScript 与 Vite 生产构建通过；Ruff 和 `py_compile` 通过。
- Python 文件管理/外部终端定向测试：`48 passed`。
- Python TaskRepository、Job Center 与 Electron Runtime 回归：`93 passed`。
- Web 文件管理 Vitest：`3 files / 14 tests passed`；另一次完整 Web Vitest 为 `96 files / 409 tests passed`。
- Web TypeScript 与 Vite 构建：通过。
- Electron Vitest：`18 files / 128 tests passed`。
- Electron typecheck 与 main/preload build：通过。
- 首屏后端基准：临时数据根包含 5000 个 MESH raw 文件和 200 个历史下载目录，`status=0.460 ms`、本地根目录读取 `104.011 ms`。
- 先前将指定现场设备记录为 `DEVICE_FILE_NETWORK_UNREACHABLE` 的结论已由现场 WinSCP 证据推翻：设备网络和 SSH 认证均成功，失败发生在认证后的 SFTP 子系统请求，设备明确返回 SFTP disabled/service type not supported。
- 当前现场设备已有可信设备事实：H3C 交换机、Comware V7，可精确解析到 `h3c.comware.switch.v7.sftp-enable.v1`；配置写入与重连结果以本次现场复验记录为准。
- 指定现场 H3C 交换机复验：真实 Paramiko 异常为 `SSHException`，日志记录 `failure_stage=open_sftp`、`ssh_authenticated=True`、`transport_active=False`，分类为 `DEVICE_FILE_SFTP_UNAVAILABLE`。
- 用户确认后，任务中心按精确 Profile 完成 5/5 个受控步骤；每一步均在设备返回且未命中拒绝标记后发布进度，终态为 `COMPLETED`。随后新建 SSH/SFTP 会话并读取远程根目录，共返回 17 项。
- 独立 WinSCP Console 复验使用同一主用直连目标、22 端口和设备凭据，完成认证、启动 SFTP 会话并执行只读 `ls`，返回码为 0；密码仅经进程 stdin 传递，输出已脱敏。

本次已完成一台 H3C Comware V7 交换机的配置写入、NetConsole 重连/根目录读取和 WinSCP Console 独立读取。无线 AC、车载 MR、未知主机密钥首次信任、WinSCP GUI 视觉确认和大文件异常仍待现场验收；三个角色共用的 Profile 目录状态继续保持 `REAL_DEVICE_PENDING`，不以单台交换机验收替代全部设备类型。
