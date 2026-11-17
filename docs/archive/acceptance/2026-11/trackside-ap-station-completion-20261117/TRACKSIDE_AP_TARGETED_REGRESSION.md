# TRACKSIDE AP 定向回归报告

- 最终状态：`LOCAL_PASS_DATABASE_VERIFIED`
- Branch：`codex-A/trackside-ap-template-station-closure-20261116`
- HEAD：`3f110cf85ec289b8b4d986c8dee40fe646de9d44`
- 产品源码修改：无
- 本轮 GUI：未重新执行
- 本轮数据库：只读

## 执行清单

| 测试范围 | 结果 |
|---|---|
| 站点名称/编号精确匹配、显式 ID 冲突、歧义和跨 Site 过滤 | 通过 |
| 七列模板导出列契约 | 通过 |
| 七列模板导入解析 station_id | 通过 |
| 七列模板重导入车辆段/停车场记录 | 通过 |
| 字段说明页只作为说明，不混入数据 | 通过 |
| AP 交换机/端口预览及占位行过滤 | 通过 |
| 正线/非正线位置分类与 station_id 规则 | 通过 |
| 事务保存 AP、站点和计划 | 通过 |
| 编辑子页依赖范围隔离 | 通过 |

命令执行结果：

```text
17 passed, 1 warning in 7.01s
```

站点模板 fixture 失败测试另行执行3次，结果为 `3/3 passed`，详见 `TRACKSIDE_AP_FIXTURE_TEST_INVESTIGATION.md`。本轮没有执行全量 Python、全量 Renderer、全量 Electron 或完整 Architecture 门禁。

## 真实数据库只读结果

| 指标 | 实际结果 |
|---|---:|
| AP 总数 | 491 |
| 正线 | 422 |
| 车辆段 | 44 |
| 停车场 | 25 |
| 有效正式 station_id | 422 |
| 无效 station_id | 0 |
| 跨 Site | 0 |
| 重复 MAC | 0 |
| 重复名称 | 0 |
| 交换机 | 491 |
| 端口 | 491 |
| 昌达路 AP | 12，均为 `station:0f0599c1f124` |

## 数据安全

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_CONTENT_MODIFIED=0
AP_RECORDS_MODIFIED=0
STATION_RECORDS_MODIFIED=0
DATABASES_DELETED=0
USER_WORKBOOKS_MODIFIED=0
```

本轮未执行导入、保存、迁移、checkpoint、VACUUM、清理、打包、Push、PR 或合并。已有 `D:\study\NetConsole-Workspace\NetConsole\apps\desktop_renderer` 的 Node/Vite 进程未被关闭，遵守了“不关闭用户正在使用的 NetConsole”的要求。
