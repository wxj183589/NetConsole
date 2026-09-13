# H3C Comware V7/V9 Capability 发布说明

完成时间：2026-09-13
产品测试基线：`cdd9eb53e3dbb398739879c18bb25c737ced34d1`
最终验收文档：`github/main@f56500f2f6a641d00646af3ddbb21f6e4ef6824c`
收口分支：`main`

## 本轮内容

- H3C Comware capability 从 V7-only 扩展为 V7/V9；版本事实先于 capability plan，未知 major 不默认 V7。
- V9 `9.1.081 / R1615P01` 进入 `h3c_comware_v9_wireless_controller`，并复用已验证的 AC/FIT-AP/LLDP/BSSID 只读命令。
- 保留 AC 查询服务对 `sqlite3.Row`、`dict` 和缺字段的兼容语义。
- 保留 `DevicePlatformFactsDTO.software_release` 契约，贯通设备详情、兼容性和采集事实链路。
- 同步 H3C command reference，并增加版本探测、Resolver、Adapter、Parser、Collection、Compatibility 和 AC 回归测试。

## 验证

- Ruff：PASS
- compileall：PASS
- diff check：PASS
- H3C/AC/设备详情定向测试：PASS；V7/V9 Resolver、Adapter、Parser、Collection、Compatibility 和 AC 回归均覆盖
- Python full：`4868 passed, 2 skipped`
- Renderer：`1300 passed`，类型检查和构建 PASS
- Electron：`298 passed`，类型检查和主进程构建 PASS
- Architecture：`12/12 passed`
- `NEW_FAILURES=0`，Full Gate PASS
- 真实设备：杭州地铁10号线 `hzl10` 的 `251-无线控制器-主`（`WX3540X`，`9.1.081 / R1615P01`）识别为 V9；SSH/bootstrap、AC/FIT-AP、BSSID/LLDP、设备详情、只读 API、GUI 查看/刷新和正常重启恢复 PASS，V7 回归 PASS

## 明确边界

Production rollback、storage registry、task lifecycle 和相关维护失败不属于本功能，保持 `OUT_OF_SCOPE`；本轮未修改相关代码、数据或门禁逻辑。

本轮只执行真实设备只读版本探测和采集；未执行设备配置写入、SFTP enable 或手工 SQL。

## 最终状态

`READY_FOR_RELEASE`
