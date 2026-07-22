# 设备文件下载业务流程验收记录（2026-07-22）

## 自动验收

| 场景 | 覆盖方式 | 结果 |
| --- | --- | --- |
| SSH 正常、SFTP 未启用 | Service/API 测试模拟 `SftpUnavailableError`，确认后执行 `device.sftp.enable` 并重连 | 通过 |
| Paramiko 返回 `Channel closed.` | Service/API 测试模拟原始异常并检查稳定错误码、确认令牌和页面禁显原文 | 通过 |
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

- Python 文件管理/外部终端定向测试：`48 passed`。
- Python TaskRepository、Job Center 与 Electron Runtime 回归：`93 passed`。
- Web 文件管理 Vitest：`3 files / 14 tests passed`；另一次完整 Web Vitest 为 `96 files / 409 tests passed`。
- Web TypeScript 与 Vite 构建：通过。
- Electron Vitest：`18 files / 128 tests passed`。
- Electron typecheck 与 main/preload build：通过。
- 首屏后端基准：临时数据根包含 5000 个 MESH raw 文件和 200 个历史下载目录，`status=0.460 ms`、本地根目录读取 `104.011 ms`。
- 指定现场设备只读连接：当前开发机无法建立到 SSH 端口的 TCP 连接，受控连接返回 `DEVICE_FILE_NETWORK_UNREACHABLE`；未进入认证、`open_sftp` 或自动启用任务。
- WinSCP 配置级检查：程序存在，生成参数的地址、端口、用户名和密码均与设备记录一致，`safe_command` 不含原始或编码密码；因现场网络不可达，未宣称 GUI 实际登录成功。

真实 H3C/MR 设备的 SFTP 配置写入、主机密钥首次信任、WinSCP GUI 登录和大文件异常仍保持 `REAL_DEVICE_PENDING`；自动测试与配置级验证不替代网络恢复后的现场验收。
