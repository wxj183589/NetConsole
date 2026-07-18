# Job Center 领域处理器

本目录按 AC、配置、设备、文件、Mesh、Online MR、Traffic 等领域注册后台 handler，把 JobContext 映射到既有 Application/Domain Service。handler 不应直接被 Router 调用。

`legacy_tasks.py` 保留部分历史任务的薄适配；新增 handler 需注册、声明能力并覆盖取消/错误/事件测试。修改后运行 Job Registry 与对应领域 Job 测试。
