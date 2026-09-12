# H3C Comware V7 Capability 收口记录

完成时间：2026-09-12
基线：`github/main@cc1c8e3a4cb2501f706cf1b62513e933698c9786`
Rebase 后 H3C 提交：`ca1e8fca`、`c1765ae0`、`5d9d287e`

## 本轮内容

- 修复 AC 查询服务对 `sqlite3.Row` 与 `dict` 的兼容读取；缺少字段时返回 `None` 或调用方指定的默认值。
- 补齐 `DevicePlatformFactsDTO.software_release`，保持设备详情、能力兼容性和采集事实链路一致。
- 同步 H3C command reference 条目及对应测试契约。
- 增加 AC 查询 Row/dict/缺字段回归测试，并保留 H3C resolver、adapter、parser、collection、compatibility 和 SFTP 相关回归覆盖。

## 验证

- Ruff：PASS
- compileall：PASS
- diff check：PASS
- H3C/AC/设备详情定向测试：`500 passed, 2 warnings`
- Python full：`4853 passed, 2 skipped, 33 warnings`

## 明确边界

Production rollback、storage registry 和相关维护失败不属于本功能，保持 `OUT_OF_SCOPE`，本轮未修改相关代码、数据或门禁逻辑。

真实设备测试仍为 `PENDING`，本日志不替代现场验收。

## 最终状态

`READY_FOR_MAIN_FAST_FORWARD`
