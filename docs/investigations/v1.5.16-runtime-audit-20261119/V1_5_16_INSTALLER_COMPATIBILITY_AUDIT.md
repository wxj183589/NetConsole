# NetConsole v1.5.16 Installer 兼容性审计

## 已验证

- 制品：`NetConsole-Full-1.5.16.0-6e72b67a-x64-setup.exe`
- 大小：`158159825` bytes
- SHA-256：`2e90f185d46667733a503a6f66b035b495a3cfce7b3682a048deb9974826ee38`
- PE 外层 NSIS stub：`0x014c`（32-bit Unicode bootstrap，NSIS 常见形态）
- 内置用户入口 `NetConsole.exe`：`0x8664`（x64）
- 内置用户入口版本：FileVersion `1.5.16`，ProductVersion `1.5.16.0`
- NSIS：`NSIS-3 Unicode`
- Installer release manifest：`packaged_dirty=false`、Installer/Backend/Frontend commit 全部为 `6e72b67a65d3c1f72d87372ef9c62a6feced2ee5`
- Canonical package smoke：PASS；资源、Backend、Renderer、Health、Ground、设备迁移/list、MESH 幂等、NOTICE/SBOM 和依赖检查通过。
- 数字签名：`NOT_SIGNED`，未伪称签名通过。

## 数据保护静态契约

`apps/desktop_electron/build/installer-data-root.nsh` 保留：

- `REUSE_EXISTING_DATA`、`FRESH_CLEAN_INSTALL`、显式 `MIGRATE_EXISTING_DATA` 三态；
- 初始化/验证失败时不发布新 Registry DataRoot 并恢复旧指针；
- `NORMAL_UNINSTALL` 保留业务数据和 DataRoot；
- `CLEAN_UNINSTALL` 只清除 NetConsole DataRoot 指针，明确保留业务数据；
- 不删除真实数据库、日志、备份或未知 Registry 项。

## 未完成

真实管理员权限下的安装、升级、卸载、签名信任链、跨 Windows 版本和人工 GUI 验收未执行，仍为 `PENDING/NOT_RUN`。本轮没有启动 Installer、没有修改真实安装或数据根。

## 结论

`INSTALLER_CANONICAL_SMOKE=PASS`
`INSTALLER_RUNTIME=NOT_RUN`
`INSTALLER_DATA_PROTECTION=STATIC_CONTRACT_PASS`
