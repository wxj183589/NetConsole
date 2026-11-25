# Phase 8 Portable 架构验收

状态：PARTIAL

## 已验证

- Electron 通过 `portable.mode` 识别便携模式。
- 默认数据根为便携程序目录下的 `data`。
- `portable-data-root.json` 支持外部绝对路径，采用临时文件加原子替换写入。
- 安装版与便携版共用 Python、Renderer、数据库和任务实现。
- DataRoot 迁移使用空目标目录、同卷 staging 和原子发布，源目录保留。
- 迁移报告保存文件数量、容量、SHA-256、SQLite quick_check、表计数、Schema 版本及凭据迁移状态。

## 自动化证据

- `tests/test_site_storage.py`：80 passed，1 skipped。
- `tests/test_data_root_configuration.py`：本轮未重复全量执行。
- `apps/desktop_renderer` Ground 图表定向测试：23 passed。

## 未验证

- 真实 Windows ZIP 冷启动、程序目录移动、外部磁盘断开和无管理员权限运行：NOT VERIFIED。
- 真实安装版与便携版互相迁移：NOT VERIFIED。

## 数据边界

本轮未读取、复制或修改 `D:\NetConsoleData` 和 `D:\NetConsoleData-dev`。测试使用隔离临时数据根。
