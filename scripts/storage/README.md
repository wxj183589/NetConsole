# 存储审计与迁移脚本

本目录保存 SQLite 存储盘点和生命周期分析工具。脚本必须明确数据根、读写模式和回滚边界；不得把 Legacy external HistoryStore 作为迁移或维护对象。

`audit_engineering_state.py` 是只读盘点工具，不得访问或修改 `D:\NetConsoleData`。
