# Ground Unattended R2 测试报告

## 已执行

- `.venv\Scripts\python.exe -m pytest tests/test_ground_unattended_schedule.py tests/test_ground_unattended_syslog_field_validation.py tests/test_ground_unattended_api.py -q`：90 passed，1 warning。
- 修改范围 Ruff：PASS。
- `py_compile`：PASS。
- `git diff --check`：PASS。

新增覆盖：原有配置不取得所有权、迁移旧审计为 UNKNOWN、新建并复查后可退出、退出失败保留 ACTIVE、其他 loghost 不被撤销；同一 MR 多批次 FIFO、批次取消隔离、逐设备状态映射、重复加入只读复查，以及 Backend 重启后从批次设备清单和 Task Center 事件恢复未完成批次。

## 未执行

真实设备、Electron/GUI、400 目标、大量 UDP、50 台 MR 批次、长时间稳定性、真实进程崩溃窗口和完整 R2 Gate。
