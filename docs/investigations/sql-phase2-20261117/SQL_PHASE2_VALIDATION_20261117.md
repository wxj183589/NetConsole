# SQL 第二阶段定向验证

状态：`LOCAL_PASS_SQL_PHASE2`

## 已执行门禁

以下命令均在 `D:\study\NetConsole-Workspace\NetConsole` 执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_task_storage_optimization.py tests/test_job_center.py tests/test_job_center_web_api.py -q --basetemp D:\study\NetConsole-Workspace\test-data\NetConsole\sql-phase2-pytest-20261117
.\.venv\Scripts\python.exe -m ruff check src/netconsole/services/job_center/query_service.py scripts/dev/job_center_sql_profile_20261116.py tests/test_task_storage_optimization.py
.\.venv\Scripts\python.exe -m py_compile src/netconsole/services/job_center/query_service.py scripts/dev/job_center_sql_profile_20261116.py tests/test_task_storage_optimization.py
.\.venv\Scripts\python.exe scripts/architecture/check_direct_sql_access.py
python -m scripts.check_workspace_layout
git diff --check
```

结果：**79 passed**，1 条既有 Starlette/httpx 弃用警告；Ruff、py_compile、Direct SQL Audit、Workspace Layout、diff check 均 PASS。没有执行全量 pytest、Renderer/Electron、Release Gate、GUI、真实设备或真实数据测试。

## SQL 次数上界回归

`tests/test_task_storage_optimization.py::test_task_center_result_list_hydrates_many_bodies_with_bounded_connections` 使用 24 个独立终态任务，验证结果完整、结果顺序/内容保留且连接数不超过 2。该测试防止恢复逐任务连接读取。

## 数据安全

验证只使用 pytest/Job profiler 隔离目录。`PRODUCTION_DATA_MODIFIED=0`、`DATABASES_REMOVED=0`、`MAINTENANCE_AUTHORIZED=NO`。未执行 VACUUM、checkpoint、WAL/SHM 删除、历史清理或生产写入。
