# Console 串口会话架构与参数

## 会话边界

Python Backend 使用锁定的 `pyserial==3.5` 管理 COM 设备。`TerminalSessionManager` 持有串口会话状态、独占端口登记、发送队列、接收缓冲区、录制器和关闭回收。`SerialInteractiveTransport` 实现现有终端传输接口，Renderer 继续使用现有 xterm.js、标签、分屏、WebSocket、日志和会话状态视图。

Electron Renderer 通过现有 Terminal API 请求 Backend，不直接访问串口。Electron Main 不负责串口读写。串口会话与 SSH/Telnet 共享 Session Manager 生命周期，串口特有的二进制发送及接收缓冲能力通过独立 Backend API 暴露，后续设备工作流可调用这些接口而不依赖 UI。

## API 能力

| 能力 | API 路径 | 用途 |
| --- | --- | --- |
| 枚举端口 | `GET /api/terminal/serial/ports` | 刷新系统端口、名称、描述、厂商和硬件 ID |
| 配置模板 | `GET/PUT /api/terminal/serial/profiles` | 读取内置和用户模板、保存用户模板 |
| 导入模板 | `POST /api/terminal/serial/profiles/import` | 校验 schema 后合并用户模板 |
| 导出模板 | `GET /api/terminal/serial/profiles/export` | 导出用户模板，不包含内置模板 |
| 打开会话 | `POST /api/terminal/serial/sessions` | 创建并打开串口会话 |
| 发送字节 | `POST /api/terminal/serial/sessions/{id}/send-bytes` | 发送 Base64 编码的原始字节 |
| 接收字节 | `GET /api/terminal/serial/sessions/{id}/receive` | 读取带偏移和超时的接收缓冲 |
| 等待模式 | `POST /api/terminal/serial/sessions/{id}/wait-for-pattern` | 在指定超时内等待编码后的字节模式 |
| 清理缓冲 | `POST /api/terminal/serial/sessions/{id}/flush` | 清理输入、输出或双向缓冲 |
| 取消会话 | `POST /api/terminal/serial/sessions/{id}/cancel` | 关闭会话并释放端口 |

文本交互继续使用共用 Terminal Session 输入和 WebSocket 输出。批量命令入口拒绝 SERIAL 会话，避免把网络设备命令调度误用于串口。

## 参数默认值

| 参数 | H3C Console 默认值 | 支持范围 |
| --- | --- | --- |
| 波特率 | 9600 | 50 至 4,000,000，含 19200、38400、57600、115200 快捷项 |
| 数据位 | 8 | 5、6、7、8 |
| 校验位 | None | None、Odd、Even、Mark、Space |
| 停止位 | 1 | 1、1.5、2；1.5 仅用于 5 数据位 |
| 流控 | None | None、RTS/CTS、DTR/DSR、XON/XOFF |
| 编码 | UTF-8 | UTF-8、GBK、GB18030、Big5、Windows ANSI |
| 发送换行 | CR | CR、LF、CRLF |
| 本地回显 | 关闭 | 开启或关闭 |
| DTR / RTS | 保持原状态 | 保持、启用或关闭 |

内置模板还提供 H3C 高速 Console `115200 8N1`。默认不自动切换波特率、不发送探测命令。Windows 端口打开时通过保留未指定控制线状态的 pySerial transport 处理 DTR/RTS；用户明确选择状态或流控时才应用相应配置。

## 资源与错误处理

端口使用 case-insensitive key 做进程内独占登记。关闭、打开失败和连接线程退出时释放登记并关闭 pySerial 句柄。发送、接收和关闭操作通过所属会话协调；异常会结束当前串口会话，不影响其他 SSH/Telnet 会话。串口配置模板单独保存在当前配置根的 `terminal/serial-profiles.json`，导入保存采用临时文件和原子替换。

本轮未使用真实 USB 串口设备验证硬件断连行为、占用竞争、驱动差异或 DTR/RTS 电气状态。虚拟 `loop://` 模拟覆盖参数、中文收发、CR/LF、原始字节、等待、flush、端口独占和关闭后重新打开。

## 本轮功能矩阵

| 功能 | 实施状态 | 本轮验收 |
| --- | --- | --- |
| Console 自有 UI 中文化 | 已实施 | Renderer 定向测试及 1920×1080 Electron 截图；完整逐页英文残留审计 NOT VERIFIED |
| 设置弹窗缓存、按需读取和错误重试 | 已实施 | Electron 30 次重开 PASS；冷启动、保存失败注入及高输出并发 NOT VERIFIED |
| H3C Console `9600 8N1` 默认参数 | 已实施 | 真实 Electron 窗口 PASS |
| 端口枚举和刷新 | 已实施 | 系统真实枚举到 COM3/COM4；设备描述 PASS |
| Serial Session API 与共享会话生命周期 | 已实施 | Python `loop://` 模拟回归 PASS |
| 中文、CR/LF、原始字节和模式等待 | 已实施 | Python `loop://` 模拟回归 PASS |
| 独占端口、关闭释放和其他协议隔离 | 已实施 | Python 模拟端口回归 PASS；真实 COM 占用竞争 NOT VERIFIED |
| 模板保存、校验、导入与导出 | 已实施 | Python Service/API 与 Renderer 定向回归 PASS |
| SSH/Telnet 与实际活动 COM 标签及分屏混用 | 已实施 | UI 共享架构，实际 COM 会话混合验收 NOT VERIFIED |
| 冻结 Worker、NSIS、Portable 离线运行 | 依赖锁和批准清单已更新 | 本轮构建受 Workspace Layout 检查失败阻断，NOT RUN |
| USB 串口现场通信和拔插 | 未完成 | NOT VERIFIED，当前环境未提供实验室 USB 设备 |
