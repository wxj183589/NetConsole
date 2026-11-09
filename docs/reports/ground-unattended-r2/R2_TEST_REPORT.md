# Ground Unattended R2 测试报告

## 已执行

- `.venv\Scripts\python.exe -m pytest tests/test_ground_unattended_syslog_field_validation.py -q`：30 passed。
- `.venv\Scripts\python.exe -m pytest tests/test_ground_unattended_api.py -q`：39 passed，1 warning。
- `.venv\Scripts\python.exe -m pytest tests/test_ground_unattended_schedule.py -q`：16 passed。
- 修改范围 Ruff：PASS。
- `py_compile`：PASS。
- `git diff --check`：PASS。

新增覆盖：原有配置不取得所有权、迁移旧审计为 UNKNOWN、新建并复查后可退出、退出失败保留 ACTIVE、其他 loghost 不被撤销。调度回归同时验证取消路径兼容未初始化设备占用表的旧式测试夹具。

## 未执行

真实设备、Electron/GUI、400 目标、大量 UDP、50 台 MR 批次、长时间稳定性、Backend 重启恢复和完整 R2 Gate。
