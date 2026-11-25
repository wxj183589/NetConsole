# Phase 7 网络服务安全审计

2026-11-25，审计范围为 `local_network_services` 的 Manager、Worker、协议与 FTP Adapter，以及直接相关定向测试。当前自动化证据为 PASS，正式交付验收为 PARTIAL。

## 已验证边界

| 边界 | 源码与验证 | 结论 |
| --- | --- | --- |
| 监听范围 | Manager 保存配置与启动时检查回环或实际 Host-only 地址，拒绝任意地址 | 现有非授权地址回归 PASS |
| 进程所有权 | Popen 句柄、Windows Job Object KILL_ON_JOB_CLOSE、控制管道与监督器 | 子进程异常退出不影响其他服务，真实隔离/回收测试 PASS |
| 退出失败 | 控制写入/flush/close 分别保护，Job 关闭进入 finally | 新 BrokenPipe 与 wait 超时回归 PASS |
| 资源查询身份 | readiness 提供真实 Worker PID，查询句柄仅 QUERY_LIMITED_INFORMATION / VM_READ，IsProcessInJob 验证归属，保持句柄防 PID 复用，退出关闭 | 真实 Worker 内存与非所属 PID 拒绝回归 PASS |
| 日志管道 | 后台持续读取 stdout/stderr，保存读取线程并有界 join | 真实 HTTP Worker 停止后两条 drainer 均退出 |
| 文件范围 | `shared_path()` 拒绝点路径、Windows 保留名、冒号/反斜杠、Symlink 和 Reparse Point。FTP validpath 复用该检查 | 现有 HTTP 越界拒绝与 FTP/FTPS 文件传输测试 PASS |
| FTP 权限 | 默认无匿名写入，随机会话密码，仅启动/重启响应返回，日志不含明文密码。写入开启后用独占文件创建 | 下载、用户名、上传和既有文件保护 PASS |
| FTP 数据端口 | 拒绝主动 PORT/EPRT，被动 bind/listen 均校验配置区间 | 单端口耗尽返回 425，NOOP 可用，释放后使用相同端口 PASS |
| TLS | HTTPS 最低 TLS 1.2，FTPS 要求控制和数据加密，自动证书校验地址、有效期及公私钥匹配 | HTTPS/FTPS、地址改变与错配私钥轮换回归 PASS |
| Syslog 资源 | UDP 无逐包线程，队列 maxsize=4096，TCP 受限连接槽、包长及超时 | 八生产者 8000 条的有界队列、6000 条真实 UDP 与 HTTP 并行回归 PASS |
| Syslog 停止 | 先停止接收与 TCP handler，再排空已接收队列 | 最终 received/dropped 计数及线程退出测试 PASS |
| 警告保留 | 子进程日志等级传递至 Manager，WARNING 配置下超长 TCP Syslog 警告仍可查询 | 新真实 Worker 回归 PASS |
| 输出脱敏 | Syslog message/raw 进入现有 redaction，再以 JSON 转义输出 | 现有密码脱敏回归 PASS |

## 修复前证据

`tests/test_network_service_resilience.py` 最初两个退出测试均因 `stdin.close()` 的二次 BrokenPipe 失败，错误位置为 `_release`。该异常会中断进程等待和 Job Object 关闭。修复后，同一测试及其他服务回归通过。

FTP 被动端口检查依据当前锁定 pyftpdlib 的 `handlers/ftp/dispatchers.py`。上游在 EADDRINUSE 时尝试端口 0，在 PermissionError 后也可能走未绑定 socket 的 listen。Adapter 增加 listen 前核验与 425 错误响应。真实 Windows 独占端口回归覆盖该路径。[pyftpdlib 源码](https://github.com/giampaolo/pyftpdlib) [MIT 许可](https://github.com/giampaolo/pyftpdlib/blob/master/LICENSE)

## 尚待验证的具体事项

- 现有 `shared_path` 在访问前检查链接。恶意本机进程并发替换已检查目录的竞争条件尚无专用文件句柄级防护证明，需在后续本机文件威胁模型与文件管理集成中验证。
- HTTP / TFTP / 普通 FTP 为明文协议，绑定范围受限。真实现场网络与客户端凭据处理仍需用户最终验收。
- TLS 使用应用自行生成的服务证书，当前自动化客户端以显式测试上下文验证传输。现场信任、指纹确认、安装态私钥 ACL 和证书恢复需要安装态验收。
- TCP Syslog 当前按换行读取，完整 RFC6587 与 RFC5424 多段 Structured Data 尚未通过互通验证。输入 raw 有长度限制且经过脱敏，不能作为逐字节原始报文归档。
- Syslog 队列溢出采用丢弃并在停止时记录计数。内核 UDP 丢包、磁盘满和长时间峰值没有本轮完整计量，独立保留天数及归档策略仍待实现。
- 输出线程收尾使用有界 join，磁盘/日志 Handler 长期卡死场景尚待故障注入。新测试覆盖正常进程退出、控制管道异常和等待超时。
- FTPS 的单一运行会话用户与密码轮换已实现，完整持久化多用户管理仍为 PARTIAL。
- Telnet / NFS / VNC 缺受管 Provider、版本锁定、权限和 Windows 运行验收，具体组件与许可证证据见 [组件评估](./PHASE7_NETWORK_SERVICES.md)。

## 许可证与发布核对

当前实现复用 pyftpdlib MIT、pyasyncore/pyasynchat PSF，以及现有 iPerf 工具 notices。TLS 使用锁定的 cryptography 和 pyOpenSSL，仓库分发清单与附带许可文件由集成任务统一核对。新评估组件本轮只读取公开源码与许可文本，二进制分发和系统服务安装为 NOT VERIFIED。

```powershell
python -m pytest tests/test_network_service_resilience.py tests/test_local_network_services.py tests/test_service_log_query.py -q
python -m ruff check src/netconsole/services/local_network_services tests/test_network_service_resilience.py
```

结果为 27 passed（28.75 秒）/ Ruff PASS。测试覆盖真实回环 socket 与服务进程，复现/修复退出故障的用例使用显式受控对象。正式设备、真实数据和完整安装包安全验收为 NOT VERIFIED。

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DATABASES_REMOVED=0
DEVICE_CONFIGURATION_WRITES=0
```

## 持续运行证据版本

Workspace reports 的 `phase7-network-services-soak-20261125` 使用资源修复前 Manager，并附实际进程树资源采样。`phase7-network-services-soak-fixed-metrics-20261125` 使用资源修复后 Manager，真实 PID 与大于 10 MB 的内存指标逐周期验证。两轮完整结果待结束且打包完成后补录。
