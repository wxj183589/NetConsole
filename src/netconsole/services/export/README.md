# Export Process 服务

本目录定义正式导出的任务模型、writer、进度、XLSX 样式和处理器。导出必须在独立 Export Process 中执行，使用临时文件完成后原子替换，不阻塞 UI。

主要入口为 `export_job.py`、`export_handlers.py`、`common_exporters.py` 和 `xlsx_style.py`。修改列、文件契约或取消语义时运行导出进程/报告定向测试并检查 WPS/Excel 占用处理。

## 用途与边界

本目录定义正式 XLSX/CSV/报告导出的 Job、writer、进度、处理器和样式；所有正式导出通过独立 Export Process 完成，不阻塞 UI。

## 主要入口

`export_job.py` 负责任务模型，`export_handlers.py` 注册 writer，`common_exporters.py`/`xlsx_style.py` 处理格式和列样式，builders 组装任务输入。

## 依赖关系

导出服务依赖 Repository/Query Service、File Contract、PathResolver 和独立 worker，由 API/Application/Job 调用；不得直接从 Vue 或 Router 写文件。

## 数据与状态

输入是脱敏查询快照/任务数据，进度与取消通过 Job/Export 协议传递；目标文件需写用户选择路径或 outputs，凭据和原始数据库连接不进入 writer。

## 测试与修改

修改列、类型、样式、文件契约、取消或原子替换时运行 Export Process、XLSX/CSV/PDF/ZIP、进度和文件占用测试。

## 生成与清理

先写临时文件，成功后原子替换目标；失败/取消清理临时文件，正式报告、原始日志和数据库不由导出清理逻辑静默删除。

## 相关文档

参见 [导出进程规范](../../../../docs/export_process_policy.md)、[数据与路径](../../../../docs/DATA_LAYOUT.md) 和 [导出 Skill](../../../../.agents/skills/netconsole-export-report-skill/SKILL.md)。
