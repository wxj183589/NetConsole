# v1.5.13 集成核对

- 产品版本：`1.5.13`，唯一版本源 `src/netconsole/core/version.py` 已核对。
- Renderer 标题、Electron `package.json`、运行时 changelog 和构建脚本使用 `1.5.13`。
- changelog 已合并为唯一 v1.5.13 段，覆盖 Ground Unattended、Syslog 位置、Heartbeat、AC 差异、MESH、DataRoot、安装版/免安装版和无 Demo 首次初始化。
- Customer/定制版及旧“版本与功能交付”机制在 v1.5.13 日志中标记为 Deprecated；兼容脚本仍保留，未宣称 Customer 生命周期验收完成。
- 免安装构建入口为 `apps/desktop_electron/scripts/package-portable.mjs`；正式安装器仍受 Full Gate、clean/upstream 和人工 Windows 验收约束。

状态：`V1_5_13_INTEGRATION=PASS_WITH_GATE_CAVEATS`，`CHANGELOG_1_5_13=PASS`，`RELEASE_READINESS=NOT_READY`。
