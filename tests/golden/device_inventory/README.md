# 设备库存回放 Golden

本目录保存 `device.inventory.collect` 回放的稳定归一化结果，供 `tests/test_device_inventory_replay.py` 与现有 Parser 组合回归比较。

- 快照不连接真实设备、不写入数据库，也不包含凭据或生产数据。
- 文件名与 `tests/fixtures/device_cli/` 中的 Fixture manifest 对应。
- 任何快照变化都必须由人工显式审阅和提交；测试不会提供自动更新开关。
