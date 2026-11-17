# NetConsole v1.5.15 轨旁 AP 报告归档索引

## 验收结论

- 产品：NetConsole 旧版 v1.5.15
- 数据根：`D:\NetConsoleData-dev`
- Site：`hzdt-09`
- AP：491 条；正线422、车辆段44、停车场25
- 正式 station_id：422/422
- 昌达路：12/12
- 交换机/端口：491/491
- 跨 Site：0；无效 station_id：0
- 数据库身份和哈希原因已核实
- 本轮定向测试：17 passed, 1 warning
- Fixture 历史失败：连续3次未复现
- 本轮不执行全量测试
- 本轮不重新导入 AP，不修改真实数据库

## 报告清单

### GUI 和数据验收

- `TRACKSIDE_AP_GUI_ACCEPTANCE_FINAL.md`
- `TRACKSIDE_AP_REAL_SITE_ID_AUDIT.md`
- `TRACKSIDE_AP_PERSISTENCE_AUDIT.md`
- `TRACKSIDE_AP_491_FINAL_REGRESSION.md`
- `TRACKSIDE_AP_STATION_COMPLETION_REPORT.md`
- `TRACKSIDE_AP_491_IMPORT_FINAL_REPORT.md`
- `TRACKSIDE_AP_PERSISTENCE_FINAL_REPORT.md`
- `TRACKSIDE_AP_EXPORT_REIMPORT_REPORT.md`
- `TRACKSIDE_AP_BACKUP_AND_RECOVERY_REPORT.md`

### 数据库和定向回归

- `TRACKSIDE_AP_DATABASE_IDENTITY_AUDIT.md`
- `TRACKSIDE_AP_HASH_CONSISTENCY_REPORT.md`
- `TRACKSIDE_AP_FIXTURE_TEST_INVESTIGATION.md`
- `TRACKSIDE_AP_TARGETED_REGRESSION.md`

历史验收报告保留原始内容；本索引不覆盖或改写历史证据。所有报告均为 Markdown，不包含数据库、WAL/SHM、原始 Excel、凭据或临时日志。
