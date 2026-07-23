# 局点现场采集增量回传交接

- 日期：2026-07-24
- 分支：`main`
- 功能提交：`aaf75aec 实现局点现场采集增量回传`

## 修改内容

- 新增完整迁移包、现场采集包和采集回传包三种类型；通过不可变 `site_uuid`、现场基准、SHA-256 和来源电脑 ID 识别同一局点及增量数据。
- 回传导入先预检，再按文件哈希追加、按 `task_id`/`event_id` 合并任务，并对具有稳定 UUID 的设备/FIT-AP/AP 记录执行三方字段合并。
- 合并前自动创建数据库恢复快照；删除请求只记录不自动执行；Legacy 局点必须先审计才可现场增量同步。
- 设置页改为“导入数据包”和三种导出入口，提供预检摘要、冲突逐项选择和“仅导入原始采集数据”。

## 验证

- `.venv\Scripts\python.exe -m py_compile`（局点同步相关 Python 模块）
- `.venv\Scripts\python.exe -m ruff check`（相关 Python 与测试）
- `.venv\Scripts\python.exe -m pytest tests\test_site_storage.py tests\test_site_storage_api.py tests\test_paths.py -q`：47 通过
- `apps/web`：`pnpm exec vitest run src/views/settings/SiteStoragePanel.test.ts`：11 通过；`pnpm build` 通过
- `apps/desktop_electron`：`pnpm typecheck` 通过；`pnpm exec vitest run tests/ipc.test.ts`：20 通过

## 遗留事项

- 仅对现有稳定 UUID 主键表自动合并；使用本地自增 ID 或自然键的旧基础资料会在预检中计为未支持记录，保持本机数据，不进行猜测性覆盖。
- 完整迁移包当前提供“恢复为新局点 / 替换现有局点”；跨电脑增量合并应使用采集回传包。
