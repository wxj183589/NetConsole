# NetConsole v1.5.17 变更记录

日期：2026-11-21

## 复审与修复

- 覆盖 1267 个 Backend/Renderer/Electron/构建/配置/资源文件，建立功能矩阵和安全/Windows 兼容性报告。
- 修复 `scripts/maintenance/audit_lifecycle_dev.py` 的隐式真实开发数据读取（NC-1517-001，P1）。
- 静态架构、直接 SQL、运行路径、命令 Profile、动态图表稳定性检查全部 PASS。

## 构建

- Full Installer：`NetConsole-v1.5.17-Setup.exe`。
- Full Portable：`NetConsole-v1.5.17-Portable.zip`。
- 包级 smoke：PASS；真实 GUI 安装状态：PENDING。

## 保留限制

六项上一版本真实环境验收继续保持 PARTIAL：Heartbeat AP/站点真实证据、MR 真实 GUI、8 小时长稳、V5 真实设备、完整站序和 Windows 10 20H2 实机。
