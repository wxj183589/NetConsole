# NetConsole v1.5.19 Console 专项验收

状态：PARTIAL。产品分支 `codex-A/organization-task-network-services-phase6`，起点 `f77f4e42`。

| 项目 | 状态 | 实际结果 |
| --- | --- | --- |
| 实验室 AC SSH | PASS | `192.168.56.2` 登录，一次 Enter 执行 `display version`，返回 Comware 7.1.064 Alpha 7165 |
| 实验室 FIT-AP Telnet | PASS | `192.168.56.4` 使用仅密码认证，一次 Enter 执行 `display version` 并返回设备版本 |
| 实验室 SW SSH | BLOCKED | `192.168.56.3:22` 可达，设备拒绝所提供的认证 |
| Electron 标签和分屏 | PASS | 源码 Electron 同时承载 AC、FIT-AP；关闭两标签后活动会话列表为空，应用退出后所属进程和测试端口已释放 |
| Electron 截图 | PASS | 实际窗口 1920×1080、2560×1440，证据位于 Workspace 的 `reports/diagnostic/phase8-real-replay/pages/`，前缀 `phase8-console-eb0bdcd2` |
| 外部终端 | PARTIAL | 本机 PATH 检出 Windows OpenSSH。此前隔离 SSH 服务已验证该客户端；SecureCRT、PuTTY、Xshell 实际启动及认证待验收 |
| 管理与批量命令 | PARTIAL | 默认仅显示管理按钮；支持保存命令查询、终端输入分发、按会话查看写入状态以及取消。逐设备命令输出及导出、暂停和可配置超时待实现 |
| 输入与会话扩展矩阵 | PARTIAL | SSH 原样转发、Telnet CRLF、拆分 CRLF 和关闭并发有专项回归。真实界面的全部控制键、多行粘贴、备用地址及重连组合待验收 |
| 规则文件 | PARTIAL | 在旧 Portable 复现两个默认 JSON 未纳入冻结包；修复资源清单与白名单，支持旧数组、常见编码、导入预览和明确的损坏诊断。实际规则面板交互仍待验收 |
| 终端设置与保存连接 | PARTIAL | 已登记设备可用备用地址及已配置的外部终端。保存连接的备用地址字段及外部启动仍待实现。完整终端设置矩阵待验收 |

实验室授权变更：AC 进入 `probe` 后执行 `wlan ap-execute all exec-console enable`，随后 FIT-AP Telnet 连通。未执行保存配置，也未验证重启后的状态。

`PRODUCTION_DATA_MODIFIED=0`、`DEV_REAL_BUSINESS_DATA_MODIFIED=0`、`DATABASES_REMOVED=0`、`REAL_DEVICE_CONFIGURATION_WRITES=1`（授权实验室 AC）、`MAINTENANCE_AUTHORIZED=NO`（生产维护）。
