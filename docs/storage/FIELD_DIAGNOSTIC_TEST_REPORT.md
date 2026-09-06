# 现场诊断包测试报告

## 覆盖范围

- 临时目录、空目录和不存在的 Windows CIM/RAID 工具。
- Raw/日志大小与条数限制、metadata-only 文件扫描。
- allowlist 脱敏、部分 section 不可用、取消点和 ZIP 完整性。
- Export Worker 注册及 System Maintenance 请求参数校验。

## 未覆盖

本地环境未连接 Windows Server 2016、真实 RAID6 HDD、Ground ACTIVE 或生产数据根；未访问 `D:\NetConsoleData`。现场磁盘映射和性能计数器需主机集成验证。

## 本分支结果

- PASS：`pytest tests/test_field_diagnostic_bundle.py tests/test_system_maintenance_web.py tests/test_export_process_framework.py tests/test_job_center_web_api.py -q`（93 passed）。
- PASS：Renderer 导出审计（16 passed）与 `pnpm build`。
- PASS：Ruff、`py_compile`、`git diff --check`；consumer gate Python 58 passed、基础 Renderer 7 passed。
- NOT RUN：完整 Renderer consumer gate 需要本地 `127.0.0.1:3000` Backend，当前环境连接被拒绝后停止。
