# 网络服务集成

工具集 → 网络服务集成通过 `/api/local-network-services` 调用后端服务管理器。页面分为核心网络服务、文件服务和远程与诊断，每项服务独立初始化、保存配置、启停、重启和查看日志。可操作范围由后端能力检测决定。

## 服务和依赖

| 服务 | 当前接入 | 行为 |
| --- | --- | --- |
| DNS | 本阶段暂缓 | API 保留稳定 ID，状态为 deferred，不允许初始化、配置或启动 |
| NTP | 本阶段暂缓 | API 保留稳定 ID，状态为 deferred，不允许初始化、配置或启动 |
| TFTP | 内置 | UDP 69，支持 octet 下载，配置可开启新文件上传。单次上传最大 8 MiB，已有文件受保护 |
| FTP / FTPS | pyftpdlib；FTPS 另需 pyOpenSSL | FTP 支持被动模式认证只读下载。FTPS 在锁定运行环境含 pyOpenSSL 时启用，要求 TLS 控制/数据通道。启动和重启返回一次性展示的会话凭据 |
| HTTP | 内置 | TCP 8080，提供受管文件的 GET 和 HEAD 下载 |
| HTTPS | 内置 | TCP 8443，TLS 1.2+，提供受管文件的 GET 和 HEAD 下载；自动生成本机自签证书并显示 SHA-256 指纹 |
| iPerf | 受管工具 | TCP 5201，复用项目已有的 iPerf3 路径和发布依赖 |
| 任务计划程序 | Windows 系统组件 | 根据系统组件存在情况显示已安装状态，仍由 Windows 管理 |
| DHCP、SFTP Server、SSH Server、Telnet、NFS、VNC | 待接入 | 显示依赖和未接入状态；SSH/SFTP Client 不代表 Server |

FTP 使用 `pyftpdlib` 2.2.0（MIT），其 Python 3.13 运行依赖 `pyasyncore` 和 `pyasynchat` 1.0.5 使用 PSF License v2。版本由 `constraints.txt` 固定，PyInstaller 清单记录同一发行版本。iPerf3 延用仓库中的 [既有工具来源和许可](../../resources/tools/windows-x64/iperf3/README.md)。

TLS 服务使用运行依赖 `cryptography` 49.0.0 生成 RSA-2048、SHA-256 自签证书；证书和私钥放在权限受限的服务运行目录，过期前 7 天会轮换。HTTPS 只允许 TLS 1.2 及以上。FTP/FTPS 使用 pyftpdlib TLS adapter，并用 pyOpenSSL 26.4.0。已在 Windows 回环完成 FTPS TLS 登录、加密下载与主动模式拒绝测试。

## 运行边界

- 所有服务默认关闭。初始化写入独立的配置和文件根，后端关闭时停止受管服务。重启应用以后需要显式启动。
- 默认监听 IPv4 回环地址。非回环地址必须是 Windows 实际检测到的、没有默认网关的活动 Host-only 网卡地址。保存和启动时均重新校验。
- 配置、轮转日志、TLS 私钥和文件共享分别位于应用运行目录下的 `local_network_services/<service>/`。HTTP、HTTPS、FTP 和 TFTP 各自使用其 `files/` 目录。
- FTP 密码随机生成，只在本次启动响应中返回，服务重启时轮换。FTP、HTTP 和 TFTP 使用明文协议。FTPS/HTTPS 使用各服务独立的本机证书，首次连接必须按现场信任策略核对指纹。
- HTTP、HTTPS、TFTP、Syslog 与 FTP 各自运行于独立受管子进程，启动凭据通过 stdin 管道传递，后台监督器检查异常退出，关闭控制管道会停止 Worker。Windows 通过持有的进程句柄与 Job Object 管理回收。可选自动恢复默认关闭，开启后最多每 5 分钟尝试 3 次。iPerf3 单独运行并用 Windows Job Object 管理进程树。
- 快照显示服务独立 PID、启动时间、运行时长、健康状态与 Windows 进程 CPU/工作集内存。自动恢复保留当前 FTP 会话凭据，手动重启轮换凭据。
- DHCP 需要具备可验证的隔离网卡、网段、地址池、租约和次级 DHCP 检测。SFTP、SSH、HTTPS 需要相应的凭据或证书管理。待接入的外部服务需具备受管适配器和绑定核验，防止启动时改变宿主机服务边界。

## 参考系统核验

使用授权账号登录本地全天猴 1.4.3，以只读方式检查了以下真实页面：

| 页面 | 实际交互与字段 |
| --- | --- |
| 网络服务仪表盘 | DHCP、TFTP、FTP、NTP、DNS 独立列出停止状态、监听 IP 和端口，并提供运行、重启、初始化、配置和日志入口 |
| DHCP 服务配置 | 监听 IP、地址池列表、起止地址、子网掩码、网关、DNS、租约、例外和静态 MAC 绑定，页面包含运行日志和服务监控 Tab |
| 配置备份 | 创建任务提供立即、周期、定时、手动执行，设备行包含现行配置与下次启动的命令。任务表展示启用、执行进度和最近执行时间，结果页提供按设备对比和最新结果筛选 |
| 智能配置 | 智能配置任务与模板管理分离，任务行包含下发方式、时间、设备数量、状态、进度和删除标记。模板列表包含描述和交互命令数 |
| 监控助手 | 任务管理与模板管理分离，任务行增加告警设备数和告警数。模板列表显示描述与最后修改时间 |
| 版本升级 | 任务表展示执行状态、结果、设备总数和成功数，模板列表包含模板类型、描述和更新时间 |

页面截图保存在本轮 Workspace 的 `reports/diagnostic/organization-task-network-services-phase6/` 中。截图已遮盖账号。服务日志入口和智能配置的创建按钮在本轮页面自动化中部分超时，字段记录以已实际打开的页面为范围。

采集参考仓库可公开只读访问。目录包含命令目录、回放采集、显式目标在线采集、H3C 身份/硬件/LLDP/光模块/诊断解析、统计阈值和 CSV/Markdown 报告。原始输出证据通过 SHA-256、状态和路径关联。NetConsole 后续可按命令兼容性、原始证据、LLDP 表头变化、设备回显阈值和输出格式分别增加回放夹具及消费者验证。 [采集参考仓库](https://nas.love-ok.com:3021/mengyou/netconfig-collection-reference)

## 验证范围

- `tests/test_local_network_services.py` 使用真实回环 socket 验证 HTTP/HTTPS 下载、HTTPS TLS 生命周期、越界拒绝、端口冲突、TFTP 上传/下载和禁止覆盖、FTP 下载和凭据轮换、Syslog UDP/TCP、DNS/NTP deferred、iPerf 进程退出和有界监督恢复；FTPS 用例要求真实 pyOpenSSL 安装，未安装时跳过并标为 `NOT VERIFIED`。
- 本次在 Windows 检测到实际 VirtualBox Host-only 网卡，并通过该网卡地址在宿主机完成隔离 HTTP 下载和停止。虚拟机访问该地址、DHCP 分配、NTP 客户端对时、SSH/Telnet 服务端和正式安装包仍待验收。
