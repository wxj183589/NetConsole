# 测试报告

## 已执行

| 检查 | 结果 |
| --- | --- |
| 修改 Python `compileall` | PASS |
| AP 台账、Mesh、性能 profile 定向测试 | PASS，14 passed |
| 导入预览/应用/幂等/回滚/基础资料/无人值守规模测试 | PASS，40 passed，1 skipped |
| 无人值守 API、查询规模、Quick Ping、Heartbeat、历史、基础资料相关回归 | PASS，157 passed，1 skipped |
| AP 台账、基础资料查询、性能 profile 最新定向回归 | PASS，20 passed |
| Renderer `vue-tsc -b --pretty false` | PASS |
| Renderer Vitest | PASS，209 files / 1537 tests |
| `git diff --check` | PASS（报告生成前最后复核） |
| 安装包/全量发布打包 | NOT RUN（本轮明确不打包） |
| Electron GUI / Playwright / 真实现场 | NOT RUN |

## 真实资料证据

- `1q(1).zip`：21 个车站 LLDP 文件，464 条原始邻居，422 条精确 AP，42 条非 AP；
- 正式工作簿预览：`ap_switch_port_point_table`，422 条可导入行；
- 隔离 Site 预览分类：CREATE 422、UPDATE 0、UNCHANGED 0、CONFLICT 0、INVALID 0、WARNING 422；
- 请求中指定的汇总/二期 Excel：未找到，二期完整验收待补资料。

隔离 Site 的实际 apply/rollback 不写入真实数据；现有受控导入专项测试已覆盖 apply、重复 apply 拒绝、人工字段保留、数据库变更后 rollback 拒绝以及成功 rollback。

## 数据安全

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DATABASES_REMOVED=0/0
MAINTENANCE_AUTHORIZED=NO
```

性能 harness 只使用 `diagnostic/ap-ledger-sql-opt-20261115` 下的隔离 fixture。性能 JSON、SQLite fixture 和 Excel 均为诊断产物，不作为真实数据 Authority。
