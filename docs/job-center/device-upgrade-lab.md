# 设备升级实验

隔离 fixture 使用合成镜像和进程内设备状态，验证目标身份、镜像 SHA-256、激活后版本检查及失败恢复。可运行 `python -m pytest -q tests/test_device_upgrade_lab.py`。

建议的生产执行器阶段为能力检查、镜像验证、暂存、激活、重连、版本确认与回滚。设备标识使用 Site 和设备 UUID。镜像应先进入受管目录，并由明确登记的厂商型号和签名策略授权。执行实例持续记录阶段与结果，激活前允许取消，激活后优先恢复设备状态。重启恢复从设备事实重查当前阶段，避免重新激活。

实验执行通过已有 Device Job 提交接口，任务类型为 `upgrade_lab`，限同时设置 `NETCONSOLE_RUNTIME_MODE=test` 与 `NETCONSOLE_DEVICE_UPGRADE_LAB=1` 的隔离环境。它使用 Site 内的设备 UUID、既有资源锁和任务结果导出。模拟 Worker 使用固定合成镜像和进程内设备状态，实现无需网络调用。生产固件传输、签名授权、真实设备启动和回滚，以及产品界面入口均未接入。
