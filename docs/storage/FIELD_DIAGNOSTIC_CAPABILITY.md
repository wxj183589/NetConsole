# 现场诊断包能力

## 已有能力

- `SyslogUdpReceiver.health_snapshot()` 和 Ground 健康 Application Service 已提供 UDP、Raw、Parser、Spool、StorageIOProfile 摘要。
- `core.storage_io.detect_storage_profile()` 已按实际 `data_root` 所在卷执行只读介质识别，并在失败时返回保守策略。
- `WebArtifactStore`、`WebExportProcessAdapter`、Task Center 和 `useUserSelectedExport` 已提供内部 Artifact、进度、取消、完整性校验和用户另存。
- System Maintenance 页面和路由已有日志维护、任务查询、取消及下载入口。

## 新增只读采集

- 当前数据卷的 Windows CIM/LogicalDisk Performance Counter 快照、常见 RAID CLI 存在性检测。
- 当前局点内有 50000 文件上限的 metadata-only 文件库存、最大文件、推断活动写文件。
- 应用日志与当前局点 Ground 目录内的有界日志 tail；Raw NDJSON 仅在用户明确勾选时采样。
- `manifest.json`、`summary.json`、`bundle_integrity.json` 及 ZIP 原子生成。

诊断 Worker 不连接业务数据库写事务，不执行 checkpoint、VACUUM、repair、清理或服务停止。运行态摘要通过字段白名单传递；未提供时以 `unavailable/null` 表示，不伪造零值，也不导出 `raw_file`、错误文本等潜在物理路径。
