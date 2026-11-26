# NetConsole v1.5.19 Console 专项验收

状态：PARTIAL。产品分支 `codex-A/organization-task-network-services-phase6`，起点 `f77f4e42`。

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

实验室授权变更：AC 进入 `probe` 后执行 `wlan ap-execute all exec-console enable`，随后 FIT-AP Telnet 连通。未执行保存配置，也未验证重启后的状态。

## 集成验证与候选制品

源码与候选绑定 `39eaa4ac6e7e1b86d2918d38b5049cfdf8a60198`，版本为 1.5.19，`BUILD_DIRTY=false`，发布状态为 unpublished。Full Gate PASS，Python 5,901 通过、3 跳过，Renderer 1,622、Electron 326、架构 12/12，冻结规则 smoke PASS。日志为 Workspace 的 `reports/tests/console-39eaa4ac-full-gate.log`。

| 制品 | SHA-256 |
| --- | --- |
| `NetConsole-Full-1.5.19.0-39eaa4ac-x64-setup.exe` | `dfa4a64c39a16b6f0faa95f3ef8622ecf2af6acf32b70859bbff8eb86ec9ff61` |
| `NetConsole-1.5.19-portable.zip` | `a0bd25f84f4bdd492b1fa37d495a6d95e00f8579516cc794c1449e7ca4dd6dae` |

候选位于 Workspace 的 `temp/build/phase8-final-package/build-39eaa4ac-20261126-141420/candidates/`，验证记录见 `reports/build/phase8-final-package-build-39eaa4ac-20261126-141420/`。两包的 CycloneDX 1.5 SBOM 均有 68 个组件。Portable 使用中文空格程序路径和全新外部 DataRoot，Renderer 就绪 5.188 秒，冻结 Worker、正常退出与端口重绑通过。NSIS 包级 smoke 通过，Windows 安装、升级、卸载和回滚现场验收仍为 NOT VERIFIED。

`PRODUCTION_DATA_MODIFIED=0`、`DEV_REAL_BUSINESS_DATA_MODIFIED=0`、`DATABASES_REMOVED=0`、`REAL_DEVICE_CONFIGURATION_WRITES=1`（授权实验室 AC）、`MAINTENANCE_AUTHORIZED=NO`（生产维护）。
