# 车载 MR 端位语义交接

- 日期：2026-07-24
- 分支：main
- 修改前修订：4515c806
- 提交修订：8c1ed4e
- 推送结果：`github/main` 成功

## 修改内容

- 新增 `mr_end_role_service.py`：固定映射 `MR-CT -> CT / 1车厢端 / 1`、`MR-CW -> CW / 6车厢端 / 6`，并仅依据运行方向、`increasing_direction_leading_end` 与物理端位计算 `leading_end / trailing_end / turnback_transition / unknown`。
- 基础资料 API、查询和页面新增 `mr_position_code`、`physical_end`、`car_number` 与线路级 `increasing_direction_leading_end`；旧 `role` 字段仅作兼容，不表示运行头尾。
- 修正基础资料、无线、MESH 和车内通信页面的 CT/CW 文案，统一显示物理车厢端位。

## 测试结果

- `.venv/Scripts/python.exe -m pytest -q tests/test_mr_end_role_service.py tests/test_rail_transit_base_data_query_service.py tests/test_rail_transit_base_data_edit_api.py`：26 passed。
- `python -m ruff check ...`：通过。
- `python -m py_compile ...`：通过。
- `pnpm exec vitest run`（基础资料与车内通信相关 5 文件）：25 passed。
- `pnpm build`：通过。
- 上述结果均在从最终暂存树生成的独立 worktree 中复验，已包含前序 `4515c806` 的集成结果。

## 遗留事项

- 行程重建、折返识别、MESH 页面“行程与头尾分析”Tab、报告与双端联合评分尚未实现；后续应复用本次 `mr_end_role_service.py`，不得以 RSSI 静默交换 CT/CW。
- 工作区存在其他会话的未提交修改，本次提交只应包含本任务相关文件。
