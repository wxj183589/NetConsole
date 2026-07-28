# 设备文件 SSH 隧道回归验收记录（2026-07-28）

## 自动与本地集成验收

| 场景 | 证据 | 结果 |
| --- | --- | --- |
| 连接目标组合 | 主用/备用直连、第一跳到主用/备用、第二跳到主用/备用，覆盖空地址和重复地址 | 通过 |
| 仅备用地址 | 真实 Paramiko 拓扑先尝试备用直连，再通过 `tunnel1_backup` 连接目标 | 通过 |
| 双隧道回退 | 服务测试覆盖第一跳失败后继续第二跳并连接备用地址 | 通过 |
| 真实 SSH 转发 | 两个本地 Paramiko SSH 服务完成跳板认证、`direct-tcpip` 和目标认证 | 通过 |
| 真实 SFTP | 完成 `listdir` 和 2,293,763 字节文件下载，大小与 SHA-256 一致 | 通过 |
| 隧道生命周期 | 下载期间转发 Channel 保持活动，断开后 SFTP、目标 SSH、转发和跳板连接释放 | 通过 |
| 跳板机未知密钥 | 返回 `DEVICE_FILE_JUMP_HOST_KEY_UNKNOWN`，精确授权后继续到目标确认 | 通过 |
| 双端密钥变化 | 跳板机和目标设备分别返回对应 `*_HOST_KEY_MISMATCH` 并阻止连接 | 通过 |
| 表单凭据复用 | 密码留空时引用已保存的设备和两条隧道凭据，主机存在即启用且不回写空密码 | 通过 |
| 全候选失败摘要 | 返回全部实际尝试路径、目标角色、隧道标签、失败阶段和稳定错误码，不含密码 | 通过 |
| 下载失败 | 返回 `DEVICE_FILE_DOWNLOAD_FAILED`，记录 `failure_stage=download` 并清理 `.part` | 通过 |

最终组合回归结果：Python `179 passed`；Web 全量 `121 files / 631 tests passed`。其中真实
Paramiko 集成测试为 `3 passed`。Vue TypeScript 与 Vite 生产构建、修改范围 Ruff、
`py_compile`、Markdown 相对链接检查和 `git diff --check` 均通过。

## 真实 MR 只读尝试

使用真实局点中已保存的设备与两条隧道凭据，只读查询设备记录后在进程内构造“仅备用地址”场景；
未修改设备数据库、主机密钥或设备配置。测试只允许连接、目录读取和测试文件下载。

| 路径 | 阶段 | 脱敏结果 |
| --- | --- | --- |
| 备用地址直连 | `target_connect` | 约 20.1 秒超时，`DEVICE_FILE_DIRECT_UNREACHABLE` |
| 第一跳到备用地址 | `jump_connect` | 约 20.0 秒超时，`DEVICE_FILE_JUMP_HOST_UNREACHABLE` |
| 第二跳到备用地址 | `jump_connect` | 约 20.0 秒超时，`DEVICE_FILE_JUMP_HOST_UNREACHABLE` |

本次现场网络未到达跳板 SSH 握手，因此没有进入主机密钥确认、目标 SSH、SFTP `listdir` 或文件下载，
也没有生成测试下载文件。NetConsole 管理的 `known_hosts` 对三端均无现有记录，但由于 TCP 连接超时，
本次没有收到可供人工核验的现场密钥指纹，未执行“仅本次信任”或持久信任。

结论：代码回归和本地真实协议拓扑通过；真实 MR 的“隧道 -> 目标设备 -> SFTP -> 文件落盘”仍被现场
网络可达性阻塞，状态必须保持 `REAL_DEVICE_PENDING`，不得标记为 `COMPLETE`。
