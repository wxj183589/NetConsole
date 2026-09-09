# 现场诊断包测试报告

## 覆盖范围

- 临时目录、空目录和不存在的 Windows CIM/RAID 工具。
- Raw/日志大小与条数限制、当前局点范围、metadata-only 文件扫描。
- Raw 默认关闭、跨局点排除、site path escape 拒绝、allowlist 脱敏、部分 section 不可用、取消点和 ZIP 完整性。
- Export Worker 注册及 System Maintenance 请求参数校验。

## 未覆盖

本地环境未连接 Windows Server 2016、真实 RAID6 HDD、Ground ACTIVE 或生产数据根；未访问 `D:\NetConsoleData`。现场磁盘映射和性能计数器需主机集成验证。

## 本分支结果

- PASS：`pytest tests/test_field_diagnostic_bundle.py tests/test_system_maintenance_web.py tests/test_export_process_framework.py tests/test_job_center_web_api.py -q`（96 passed）。
- PASS：Renderer Vitest 全量（181 files / 1296 tests）；测试期间无 Backend 的 `ECONNREFUSED :3000` 探针消息不影响最终退出码。
- PASS：相关 Python Ruff 与 `git diff --check`。
- PASS：Renderer build（`vue-tsc -b && vite build`）。
- PENDING：仓库全量 gate 和 Windows Server 2016/真实 RAID6 HDD/Ground ACTIVE 现场验证由 v1.5.6 主线收口统一执行和记录。
