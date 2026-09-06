# 现场诊断包设计

入口为系统日志维护页的“导出现场诊断包”。请求先由 `SystemMaintenanceApplicationService` 预留 Artifact，再由 `WebExportProcessAdapter` 启动独立 Export Worker。Worker 只接收可序列化参数，输出到受管 Artifact 临时文件，成功后原子替换。

ZIP 固定包含存储、runtime、performance、files、logs、samples、config，以及 manifest/summary/integrity。日志最多 20 MiB/文件，Raw 最多 1000 行或 5 MiB，压缩使用单线程中等压缩级别，软上限 200 MiB。每个采集区段独立捕获异常并写入 `failed_sections`/`warnings`，不影响其它区段。

配置使用 allowlist；密码、community、token、authorization、cookie、私钥等字段统一替换为 `[REDACTED]`。data root 仅作为诊断上下文，文件清单使用相对路径。
