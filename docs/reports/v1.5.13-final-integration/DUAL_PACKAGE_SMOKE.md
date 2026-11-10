# Dual Package Smoke

## Portable

`PORTABLE_SMOKE=PASS`。

- 直接运行解压包 `NetConsole.exe`：`EXIT_0`
- 启动/退出握手：`SHUTDOWN_STARTED`、`DOWNLOADS_STOPPED`、`BACKEND_STOPPED`、`EXIT_REQUESTED`、`EXIT_RETURNED`
- 程序目录默认数据根：验证创建 `<portable-program-dir>\data`
- 新鲜包 Demo 扫描：未发现 Demo/example 业务数据
- `node scripts/package-smoke.mjs`：PASS
- 版本一致性：`1.5.13`
- `SOURCE_GIT_HEAD`、前端/Backend 包内 commit：一致，`PACKAGED_DIRTY=false`

包级 smoke 同时覆盖冻结时区数据、设备兼容 profile、设备数据库迁移/list HTTP 200、Ground unattended status HTTP 200、MESH import context 幂等、重复 basename、归档命名、中文 Worker 协议、无 Qt 残留、NOTICE/SBOM 和退出握手。

## Installer

`INSTALLER_SMOKE=NOT_RUN`。由于 Installer 在正式构建前被 upstream 保护阻断，没有可执行的安装器对象可以 smoke；详见 [INSTALLER_BUILD_REPORT.md](INSTALLER_BUILD_REPORT.md)。

## 综合

`DUAL_PACKAGE_SMOKE=PARTIAL`：Portable 已通过，Installer 受 GitHub/upstream 门禁阻断。该状态不等价于双版本正式发布通过。
