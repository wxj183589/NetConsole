# 维护入口

本目录仅承载需要明确维护授权的独立操作入口，不参与 NetConsole 普通启动流程。

- `site_database_recovery.py`：复用站点数据库备份、路径校验和删除安全边界；每次破坏性操作都必须提供显式维护授权。
- 维护脚本位于 `scripts/maintenance/recover_site_databases.py`，必须同时提供数据根、授权令牌和显式删除确认。

维护入口不得自动删除业务数据、绕过备份校验或替代生产启动路径。测试必须使用隔离数据根。
