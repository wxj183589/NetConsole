# 现场诊断包设计

入口为系统日志维护页的“导出现场诊断包”。请求先由 `SystemMaintenanceApplicationService` 预留 Artifact，再由 `WebExportProcessAdapter` 启动独立 Export Worker。Worker 只接收可序列化参数，输出到受管 Artifact 临时文件，成功后原子替换。

ZIP 固定包含存储、runtime、performance、files、logs、samples、config，以及 manifest/summary/integrity。文件库存只扫描当前局点并限制为 50000 个文件；应用日志和当前局点 Ground 日志最多选取 3 个近期文件、20 MiB/文件。Raw 仅从当前局点 Ground active 目录采集，必须由用户明确勾选，最多 1000 行或 5 MiB。压缩使用单线程中等压缩级别，软上限 200 MiB。每个采集区段独立捕获异常并写入 `failed_sections`/`warnings`，不影响其它区段。

配置和 Ground 运行摘要分别使用 allowlist；密码、community、token、authorization、cookie、私钥、内网地址和物理路径等内容统一脱敏。数据根只在 Worker 内用于解析当前局点和当前卷，ZIP 不记录其物理路径，文件清单只使用局点相对路径。
