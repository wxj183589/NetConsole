# 存储审计与迁移脚本

本目录保存 SQLite 存储盘点、生命周期分析和受控迁移工具。脚本必须明确数据根、读写模式和回滚边界；涉及工程态历史的工具只允许对 `NetConsoleData-dev` 执行。

`audit_engineering_state.py` 是只读盘点工具；`engineering_recent10_migration.py` 是候选优先的 DEV 迁移工具，默认 dry-run，只有显式 `--apply --cutover` 才会切换 DEV 副本。两者都不得访问或修改 `D:\NetConsoleData`。
